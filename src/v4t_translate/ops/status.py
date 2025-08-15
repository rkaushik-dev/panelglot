"""One screen answering "where is this project".

Everything here can already be found out. The catalog freshness is in doctor,
the coverage is in stats, the outstanding work is in the workbook export, and
whether anything is blocking a release is in check. Getting all four means
running four commands, and in practice nobody does, so the question that
actually gets asked on a Friday afternoon is answered from memory.

The whole value is in the ordering. It goes: can you ship, what is stopping
you, and how much work is left. A screen that opens with a percentage puts
the reassuring number where the blocking one belongs.

Nothing here is a check. It reads what is on disk and reports it. Running the
rules costs several seconds per language and this is the command somebody runs
when they want an answer in one, so the last check result is read from the
catalog's own state fields rather than recomputed. Where that is not enough
the report says so rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path

from ..catalog.store import Catalog, load_catalog, load_translations
from ..catalog.translations import TranslationSet, TranslationState
from ..config import ProjectConfig
from ..waivers import load_waivers
from .stats import LocaleStats, count_words

__all__ = ["LocaleStatus", "ProjectStatus", "project_status", "Readiness"]


class Readiness(str, Enum):
    """Where one language stands, in the order that matters.

    Ordered worst first, which is the order a status screen reads in.
    """

    STALE = "stale"
    """Approved translations made against English that has since moved."""

    BLOCKED = "blocked"
    """Started, and something is still outstanding."""

    UNSTARTED = "unstarted"
    """Nothing approved. Not a blocker, because nobody expected it yet."""

    READY = "ready"

    def __str__(self) -> str:
        return self.value


@dataclass
class LocaleStatus:
    """Where one language is."""

    tag: str
    stats: LocaleStats

    stale: int = 0
    """Translations made against English that has moved since."""

    empty: int = 0
    drafts: int = 0
    needs_review: int = 0

    last_touched: date | None = None
    """The most recent update stamp on any translation in this language."""

    @property
    def readiness(self) -> Readiness:
        if self.stats.approved == 0:
            return Readiness.UNSTARTED
        if self.stale:
            return Readiness.STALE
        if self.stats.outstanding:
            return Readiness.BLOCKED
        return Readiness.READY

    @property
    def blocking(self) -> int:
        """Messages that stand between this language and a release."""
        return self.stats.outstanding + self.stale

    def describe(self) -> str:
        parts = [
            f"{self.tag:<8} {self.readiness.value:<9} "
            f"{self.stats.approved}/{self.stats.total} approved"
        ]
        if self.stale:
            parts.append(f"{self.stale} stale")
        if self.drafts:
            parts.append(f"{self.drafts} draft")
        if self.needs_review:
            parts.append(f"{self.needs_review} to review")
        if self.stats.outstanding_words:
            parts.append(f"{self.stats.outstanding_words} words left")
        return ", ".join(parts)


@dataclass
class ProjectStatus:
    """Where the whole project is."""

    project: str
    messages: int = 0
    source_words: int = 0

    catalog_path: Path | None = None
    catalog_is_stale: bool = False
    """True when a source file has been edited since the catalog was written."""

    stale_sources: list[str] = field(default_factory=list)
    locales: list[LocaleStatus] = field(default_factory=list)
    waivers: int = 0
    expired_waivers: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def shippable(self) -> list[LocaleStatus]:
        return [entry for entry in self.locales
                if entry.readiness == Readiness.READY]

    @property
    def blocked(self) -> list[LocaleStatus]:
        return [entry for entry in self.locales
                if entry.readiness in (Readiness.BLOCKED, Readiness.STALE)]

    @property
    def unstarted(self) -> list[LocaleStatus]:
        return [entry for entry in self.locales
                if entry.readiness == Readiness.UNSTARTED]

    @property
    def can_ship(self) -> bool:
        """Whether every configured language is ready and the catalog is current.

        An unstarted language counts against this. It is reported under its
        own name because who you go and talk to is different, but a build with
        an empty language in it is not a build anybody wants to ship.
        """
        return (
            bool(self.locales)
            and not self.catalog_is_stale
            and all(entry.readiness is Readiness.READY for entry in self.locales)
        )

    def verdict(self) -> str:
        if self.catalog_is_stale:
            return (
                f"not shippable: the catalog is older than "
                f"{', '.join(self.stale_sources)}"
            )
        if not self.locales:
            return "no languages configured"

        parts: list[str] = []
        if self.blocked:
            parts.append(", ".join(entry.tag for entry in self.blocked))
        if self.unstarted:
            names = ", ".join(entry.tag for entry in self.unstarted)
            parts.append(f"{names} not started")

        if parts:
            return f"not shippable: {'; '.join(parts)}"
        return f"shippable: all {len(self.locales)} languages approved"

    def worst_first(self) -> list[LocaleStatus]:
        """Languages ordered by how much stands between them and a release."""
        return sorted(self.locales, key=lambda e: (-e.blocking, e.tag))

    def total_outstanding_words(self) -> int:
        return sum(entry.stats.outstanding_words for entry in self.locales)


def project_status(config: ProjectConfig, *,
                   locales: list[str] | None = None) -> ProjectStatus:
    """Read everything on disk and say where the project is."""
    catalog_path = config.catalog_path()

    status = ProjectStatus(project=config.name, catalog_path=catalog_path)

    if not catalog_path.exists():
        status.notes.append(
            f"{catalog_path.name} does not exist. Run extract; there is nothing "
            f"to report until there is a catalog."
        )
        return status

    catalog = load_catalog(catalog_path)
    status.messages = len(catalog)
    status.source_words = sum(
        count_words(message.source_text) for message in catalog.messages.values()
    )

    _check_freshness(config, catalog_path, status)
    _read_waivers(config, status)

    for tag in locales or config.target_tags():
        entry = config.locale_entry(tag)
        translations = load_translations(config.translations_path(entry.tag))
        status.locales.append(_for_locale(entry.tag, catalog, translations))

    return status


def _check_freshness(config: ProjectConfig, catalog_path: Path,
                     status: ProjectStatus) -> None:
    """Name the sources that have moved since the catalog was written.

    Naming them rather than saying "stale" is the difference between a line
    somebody acts on and a line somebody has to investigate first.
    """
    written = catalog_path.stat().st_mtime

    for entry in config.sources:
        path = config.root / entry.path
        if path.exists() and path.stat().st_mtime > written:
            # as_posix rather than str: this string ends up in a verdict line
            # and in the JSON, and a backslash there reads as an escape to
            # everything downstream of it.
            status.stale_sources.append(entry.path.as_posix())

    status.catalog_is_stale = bool(status.stale_sources)


def _read_waivers(config: ProjectConfig, status: ProjectStatus) -> None:
    from ..errors import ConfigError

    try:
        waivers = load_waivers(config.waivers_path())
    except ConfigError as exc:
        status.notes.append(f"the waiver file could not be read: {exc}")
        return

    today = date.today()
    status.waivers = len(waivers)
    status.expired_waivers = sum(1 for w in waivers if w.expired_on(today))

    if status.expired_waivers:
        status.notes.append(
            f"{status.expired_waivers} of {status.waivers} waivers have expired "
            f"and are suppressing nothing"
        )


def _for_locale(tag: str, catalog: Catalog,
                translations: TranslationSet) -> LocaleStatus:
    from .stats import _for_locale as counted

    stats = counted(tag, catalog, translations)
    status = LocaleStatus(tag=tag, stats=stats, stale=stats.stale)

    status.empty = stats.by_state.get(TranslationState.EMPTY.value, 0)
    status.drafts = stats.by_state.get(TranslationState.DRAFT.value, 0)
    status.needs_review = stats.by_state.get(TranslationState.NEEDS_REVIEW.value, 0)
    status.last_touched = _most_recent(translations)

    return status


def _most_recent(translations: TranslationSet) -> date | None:
    """The newest update stamp, ignoring anything unparseable.

    Stamps are written by this tool but the catalog is a text file people
    edit, and one hand typed date should not take the whole command down.
    """
    newest: date | None = None

    for translation in translations.entries.values():
        if not translation.updated:
            continue
        try:
            stamp = date.fromisoformat(translation.updated)
        except ValueError:
            continue
        if newest is None or stamp > newest:
            newest = stamp

    return newest
