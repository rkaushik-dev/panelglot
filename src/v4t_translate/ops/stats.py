"""How far along each language is.

The number people ask for is "what percent is German". The number that
matters is how much of it is approved, because a language that is 100%
translated and 40% approved is not ready and looks ready on every chart.

So coverage is reported as three separate figures and never as one. Words are
counted as well as strings, because 60 short labels and 60 message box
paragraphs are the same string count and nothing like the same amount of work,
and a schedule built on string counts is wrong by a factor of four.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..catalog.store import Catalog, load_translations
from ..catalog.translations import TranslationSet, TranslationState
from ..config import ProjectConfig
from .project import require_catalog

__all__ = ["LocaleStats", "ProjectStats", "project_stats", "count_words"]


def count_words(text: str) -> int:
    """Rough word count. Whitespace separated, with CJK counted per character.

    Chinese has no spaces, so a whitespace count says one word for a sentence.
    Counting each ideograph is the convention every agency we have dealt with
    invoices on, so it is the one used here.
    """
    words = 0
    run = 0

    for char in text:
        ends_run = char.isspace() or _is_ideograph(char)
        if ends_run and run:
            words += 1
            run = 0

        if _is_ideograph(char):
            words += 1
        elif not char.isspace():
            run += 1

    return words + (1 if run else 0)


def _is_ideograph(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3040 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0xF900 <= codepoint <= 0xFAFF
    )


@dataclass
class LocaleStats:
    """One language's progress."""

    tag: str
    total: int = 0
    translated: int = 0
    approved: int = 0
    stale: int = 0
    protected: int = 0
    total_words: int = 0
    outstanding_words: int = 0
    by_state: dict[str, int] = field(default_factory=dict)

    @property
    def translated_fraction(self) -> float:
        return self.translated / self.total if self.total else 0.0

    @property
    def approved_fraction(self) -> float:
        return self.approved / self.total if self.total else 0.0

    @property
    def outstanding(self) -> int:
        return self.total - self.approved

    def describe(self) -> str:
        return (
            f"{self.tag}: {self.approved}/{self.total} approved "
            f"({self.approved_fraction:.0%}), "
            f"{self.translated} translated ({self.translated_fraction:.0%}), "
            f"{self.stale} stale, {self.outstanding_words} words outstanding"
        )


@dataclass
class ProjectStats:
    """Every language, plus what they have in common."""

    project: str
    messages: int = 0
    source_words: int = 0
    protected: int = 0
    locales: list[LocaleStats] = field(default_factory=list)

    def locale(self, tag: str) -> LocaleStats | None:
        for stats in self.locales:
            if stats.tag == tag:
                return stats
        return None

    def summary(self) -> str:
        return (
            f"{self.project}: {self.messages} messages, {self.source_words} words, "
            f"{len(self.locales)} languages"
        )

    def worst_first(self) -> list[LocaleStats]:
        return sorted(self.locales, key=lambda stats: (stats.approved_fraction, stats.tag))


def project_stats(config: ProjectConfig, *,
                  locales: list[str] | None = None) -> ProjectStats:
    """Count everything worth counting."""
    catalog = require_catalog(config)

    stats = ProjectStats(project=config.name, messages=len(catalog))
    stats.source_words = sum(
        count_words(message.source_text) for message in catalog.messages.values()
    )
    stats.protected = sum(1 for m in catalog.messages.values() if m.protected)

    tags = locales or config.target_tags()
    for tag in tags:
        entry = config.locale_entry(tag)
        translations = load_translations(config.translations_path(entry.tag))
        stats.locales.append(_for_locale(entry.tag, catalog, translations))

    return stats


def _for_locale(tag: str, catalog: Catalog, translations: TranslationSet) -> LocaleStats:
    stats = LocaleStats(tag=tag, total=len(catalog))
    stats.by_state = {state.value: 0 for state in TranslationState}

    for key, message in catalog.messages.items():
        translation = translations.get(key)
        words = count_words(message.source_text)
        stats.total_words += words
        stats.by_state[translation.state.value] += 1

        if message.protected:
            stats.protected += 1

        if translation.text:
            stats.translated += 1
        if translation.state.is_shippable:
            stats.approved += 1
        else:
            stats.outstanding_words += words

        if translation.is_stale_against(message.source_text):
            stats.stale += 1

    return stats
