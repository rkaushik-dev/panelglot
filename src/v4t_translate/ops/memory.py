"""Housekeeping for the translation memory.

The memory is a cache, and the thing that makes a cache useful is that
somebody can look inside it and throw it away. Four operations, all of them
about that.

``absorb`` takes everything approved in the catalog into memory. Run after a
delivery lands, and once against every product that already shipped, which is
where nearly all of the value comes from.

``import_workbook`` takes a sheet that was never part of this project. The
delivered V4T-TIJ8PEN German workbook is nine hundred rows of answers to
strings that mostly still exist somewhere, and none of it was reachable until
this could read it straight into memory.

``suggest`` answers "what do we already have for this" without touching
anything, which is what somebody wants when a question comes up in review.

``forget`` exists because a wrong entry in memory pollutes every future
pretranslate, and that is much worse than a wrong entry in one catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.store import load_catalog, load_translations
from ..catalog.translations import TranslationState
from ..config import ProjectConfig
from ..errors import CatalogError
from ..mt.memory import DEFAULT_THRESHOLD, Match, TranslationMemory
from ..workbook.reader import read_workbook

__all__ = ["MemoryReport", "memory_path", "absorb_catalog", "absorb_workbook",
           "suggest_for", "memory_stats"]


@dataclass
class MemoryReport:
    """What one housekeeping run did."""

    added: int = 0
    locales: list[str] = field(default_factory=list)
    total: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        where = ", ".join(self.locales) if self.locales else "nothing"
        return f"{self.added} units from {where}, {self.total} in memory"


def memory_path(config: ProjectConfig) -> Path:
    """Where the memory lives for a project."""
    return config.root / config.catalog_dir / "memory.sqlite3"


def absorb_catalog(config: ProjectConfig, *, locales: list[str] | None = None,
                   include_drafts: bool = False) -> MemoryReport:
    """Take everything approved in the catalog into memory."""
    path = config.catalog_path()
    if not path.exists():
        raise CatalogError(f"{path} does not exist. Run extract first.")

    catalog = load_catalog(path)
    states: tuple[TranslationState, ...] = (TranslationState.APPROVED,)
    if include_drafts:
        states = (*states, TranslationState.NEEDS_REVIEW)

    report = MemoryReport()

    with TranslationMemory(memory_path(config)) as memory:
        for tag in locales or config.target_tags():
            entry = config.locale_entry(tag)
            translations = load_translations(config.translations_path(entry.tag))
            added = memory.absorb(catalog, translations, states=states)
            if added:
                report.locales.append(entry.tag)
            report.added += added
        report.total = len(memory)

    return report


def absorb_workbook(config: ProjectConfig, path: Path | str, *,
                    sheet: str | None = None) -> MemoryReport:
    """Take a workbook straight into memory, catalog or no catalog.

    This is how the sheets from products that were localised before this tool
    existed get in. There is nothing to match against and nothing is checked:
    a memory entry is a suggestion, and a suggestion from a shipped product is
    a good one.
    """
    read = read_workbook(path, sheet=sheet)
    report = MemoryReport(warnings=list(read.warnings))

    with TranslationMemory(memory_path(config)) as memory:
        for row in read.rows:
            if not row.source or not row.target:
                continue
            memory.remember(read.locale.tag, row.source, row.target,
                            origin=Path(path).name)
            report.added += 1
        report.total = len(memory)

    if report.added:
        report.locales.append(read.locale.tag)
    return report


def suggest_for(config: ProjectConfig, locale: str, text: str, *,
                threshold: float = DEFAULT_THRESHOLD, limit: int = 5) -> list[Match]:
    """What memory already has for this English."""
    entry = config.locale_entry(locale)
    with TranslationMemory(memory_path(config)) as memory:
        return memory.suggest(entry.tag, text, threshold=threshold, limit=limit)


def memory_stats(config: ProjectConfig) -> dict[str, int]:
    """Units per language."""
    with TranslationMemory(memory_path(config)) as memory:
        return memory.counts()
