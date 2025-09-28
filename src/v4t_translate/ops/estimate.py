"""What a pretranslate run would cost, before it spends anything.

Engines bill by character and the number is never the one people expect. The
catalog is two thousand messages, so the guess is "two thousand strings, that
is nothing". It is about ninety thousand characters, and eleven languages of
it is a million, and half of those characters are already answered in the
memory from the round before.

None of that is visible until the invoice. So this counts it first.

Three numbers, and the third is the useful one.

The first is what is outstanding: messages with no translation and no
protection, which is what a run would work on at all. The second is what the
memory already answers exactly, which costs nothing and is usually a third of
a follow-up round. The third is what is left, which is what gets posted and
what gets billed.

The count is characters rather than words, because that is what the engines
charge on, and it counts the protected form rather than the raw English. A
string is never posted as written: its placeholders are swapped for tokens
first. The tokens are not always shorter, and on a catalog full of ``%s`` they
are longer, which is exactly why this counts what goes out rather than what
is in the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..catalog.store import Catalog, load_translations
from ..config import ProjectConfig
from ..mt.base import protect_placeholders
from ..mt.memory import TranslationMemory
from .project import require_catalog

__all__ = ["LocaleEstimate", "ProjectEstimate", "estimate_project", "billable_length"]


def billable_length(text: str) -> int:
    """Characters an engine would charge for.

    The protected form, because that is what is posted. A token is not always
    shorter than the placeholder it replaced, and on a catalog full of ``%s``
    it is longer, so counting the raw English would undercount the bill.
    """
    protected, _ = protect_placeholders(text)
    return len(protected)


@dataclass
class LocaleEstimate:
    """What one language would cost."""

    tag: str
    outstanding: int = 0
    """Messages with no translation, not protected."""

    from_memory: int = 0
    """Of those, the ones an exact memory hit already answers."""

    billable_messages: int = 0
    billable_characters: int = 0
    already_answered: int = 0
    protected: int = 0

    @property
    def saved_by_memory(self) -> float:
        return self.from_memory / self.outstanding if self.outstanding else 0.0

    def requests(self, batch_size: int) -> int:
        size = max(1, batch_size)
        return -(-self.billable_messages // size)

    def describe(self, batch_size: int) -> str:
        return (
            f"{self.tag}: {self.outstanding} outstanding, "
            f"{self.from_memory} from memory ({self.saved_by_memory:.0%}), "
            f"{self.billable_messages} to post "
            f"({self.billable_characters} characters, "
            f"{self.requests(batch_size)} requests)"
        )


@dataclass
class ProjectEstimate:
    """Every language, and the total somebody is going to be asked to sign."""

    project: str
    batch_size: int = 50
    locales: list[LocaleEstimate] = field(default_factory=list)

    @property
    def billable_characters(self) -> int:
        return sum(entry.billable_characters for entry in self.locales)

    @property
    def billable_messages(self) -> int:
        return sum(entry.billable_messages for entry in self.locales)

    @property
    def requests(self) -> int:
        return sum(entry.requests(self.batch_size) for entry in self.locales)

    @property
    def from_memory(self) -> int:
        return sum(entry.from_memory for entry in self.locales)

    def cost(self, per_million: float) -> float:
        """What that many characters comes to at a per-million-character rate.

        A rate rather than a built-in price list. Every engine prices
        differently, the prices change, and a number baked in here would be
        wrong within a quarter and believed anyway.
        """
        return self.billable_characters / 1_000_000 * per_million

    def summary(self) -> str:
        return (
            f"{self.project}: {self.billable_messages} messages to post across "
            f"{len(self.locales)} languages, {self.billable_characters} characters, "
            f"{self.requests} requests. {self.from_memory} answered from memory."
        )


def estimate_project(config: ProjectConfig, *, locales: list[str] | None = None,
                     memory: TranslationMemory | None = None,
                     batch_size: int = 50) -> ProjectEstimate:
    """Count what a pretranslate run would post, without posting anything."""
    catalog = require_catalog(config)
    estimate = ProjectEstimate(project=config.name, batch_size=batch_size)

    owned = memory is None
    memory = memory or TranslationMemory(
        config.root / config.catalog_dir / "memory.sqlite3"
    )

    try:
        for tag in locales or config.target_tags():
            entry = config.locale_entry(tag)
            estimate.locales.append(
                _for_locale(catalog, config, entry.tag, entry.locale, memory)
            )
    finally:
        if owned:
            memory.close()

    return estimate


def _for_locale(catalog: Catalog, config: ProjectConfig, tag: str, locale,
                memory: TranslationMemory) -> LocaleEstimate:
    translations = load_translations(config.translations_path(tag))
    found = LocaleEstimate(tag=tag)

    for key in catalog.sorted_keys():
        message = catalog.messages[key]
        translation = translations.get(key)

        if message.protected:
            found.protected += 1
            continue
        if translation.text:
            found.already_answered += 1
            continue

        found.outstanding += 1

        if memory.recall(locale.tag, message.source_text) is not None:
            found.from_memory += 1
            continue

        found.billable_messages += 1
        found.billable_characters += billable_length(message.source_text)

    return found
