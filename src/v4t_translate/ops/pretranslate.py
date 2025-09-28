"""Filling in what can be filled in before a person is asked.

Three sources, in order, and the order is the whole design.

An exact translation memory hit is the same English already answered in this
language. It lands as needs-review rather than approved, because "the same
English" is not "the same context" and somebody should look once. With
``trust_memory`` it lands approved, which is right for a follow-up round on a
product that shares most of its strings with one already shipped.

A fuzzy memory hit is a suggestion. It lands as a draft with a note saying
what it was matched against and how closely, so the translator can see whether
to keep it or start again.

A provider answer lands as a draft and never as anything better. That is what
the state is for.

Nothing here ever touches a message that is already answered, and nothing
touches a protected one. Both are silently skipped and counted.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date

from ..catalog.store import Catalog, load_translations, save_translations
from ..catalog.translations import TranslationSet, TranslationState
from ..config import ProjectConfig
from ..errors import ConfigError
from ..locales import Locale
from ..mt.base import Provider
from ..mt.memory import DEFAULT_THRESHOLD, TranslationMemory
from ..mt.providers import get_provider
from .project import require_catalog

__all__ = [
    "PretranslateResult",
    "pretranslate_project",
    "build_provider",
    "MEMORY_BATCH",
    "BUILTIN_PROVIDERS",
]

#: Names that always mean the built-in provider, whatever a project calls its
#: own engines.
BUILTIN_PROVIDERS = ("passthrough", "pseudo")

#: Strings sent to a provider in one call.
MEMORY_BATCH = 50


@dataclass
class PretranslateResult:
    """What one pretranslate run filled in."""

    locale: str
    from_memory: list[str] = field(default_factory=list)
    from_fuzzy: list[str] = field(default_factory=list)
    from_provider: list[str] = field(default_factory=list)
    already_answered: int = 0
    protected: int = 0
    left_empty: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    written: bool = False

    @property
    def filled(self) -> int:
        return len(self.from_memory) + len(self.from_fuzzy) + len(self.from_provider)

    def summary(self) -> str:
        return (
            f"{self.locale}: {self.filled} filled "
            f"({len(self.from_memory)} exact, {len(self.from_fuzzy)} fuzzy, "
            f"{len(self.from_provider)} machine), "
            f"{len(self.left_empty)} left empty, "
            f"{self.already_answered} already answered"
        )


def pretranslate_project(
    config: ProjectConfig,
    locale: str,
    *,
    memory: TranslationMemory | None = None,
    provider: Provider | str | None = None,
    trust_memory: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
    dry_run: bool = False,
    today: date | None = None,
) -> PretranslateResult:
    """Fill in one language from memory and, optionally, a provider."""
    catalog = require_catalog(config)
    entry = config.locale_entry(locale)
    translations = load_translations(config.translations_path(entry.tag))

    owned_memory = memory is None
    memory = memory or TranslationMemory(config.root / config.catalog_dir / "memory.sqlite3")

    engine = _resolve_provider(config, provider)
    result = PretranslateResult(locale=entry.tag)

    try:
        outstanding = _fill_from_memory(
            catalog, translations, memory, entry.locale, result,
            trust_memory=trust_memory, threshold=threshold, today=today,
        )
        if engine is not None and outstanding:
            _fill_from_provider(
                catalog, translations, engine, config.source_locale, entry.locale,
                outstanding, result, today=today,
            )
        else:
            result.left_empty.extend(outstanding)
    finally:
        if owned_memory:
            memory.close()

    if not dry_run:
        save_translations(config.translations_path(entry.tag), translations)
        result.written = True

    return result


def _fill_from_memory(catalog: Catalog, translations: TranslationSet,
                      memory: TranslationMemory, locale: Locale,
                      result: PretranslateResult, *, trust_memory: bool,
                      threshold: float, today: date | None) -> list[str]:
    """Fill what memory can and return the keys it could not."""
    outstanding: list[str] = []

    for key in catalog.sorted_keys():
        message = catalog.messages[key]
        existing = translations.get(key)

        if existing.text:
            result.already_answered += 1
            continue

        if message.protected:
            result.protected += 1
            continue

        exact = memory.recall(locale.tag, message.source_text)
        if exact is not None:
            state = (TranslationState.APPROVED if trust_memory
                     else TranslationState.NEEDS_REVIEW)
            translations.set(key, existing.with_text(
                exact.target, source_text=message.source_text, state=state,
                origin="memory", today=today,
            ))
            result.from_memory.append(key)
            continue

        matches = memory.suggest(locale.tag, message.source_text,
                                 threshold=threshold, limit=1)
        if matches:
            match = matches[0]
            translations.set(key, existing.with_text(
                match.target, source_text=message.source_text,
                state=TranslationState.DRAFT, origin="memory",
                note=f"{match.score:.0%} match against {match.source!r}",
                today=today,
            ))
            result.from_fuzzy.append(key)
            continue

        outstanding.append(key)

    return outstanding


def _fill_from_provider(catalog: Catalog, translations: TranslationSet,
                        provider: Provider, source: Locale, target: Locale,
                        keys: list[str], result: PretranslateResult,
                        *, today: date | None) -> None:
    for batch in _batched(keys, MEMORY_BATCH):
        texts = [catalog.messages[key].source_text for key in batch]
        answer = provider.translate(texts, source, target)
        result.warnings.extend(answer.warnings)

        if len(answer.texts) != len(batch):
            result.warnings.append(
                f"{provider.name} returned {len(answer.texts)} answers for "
                f"{len(batch)} strings, so the batch was dropped"
            )
            result.left_empty.extend(batch)
            continue

        for key, text in zip(batch, answer.texts, strict=False):
            if not text:
                result.left_empty.append(key)
                continue
            message = catalog.messages[key]
            translations.set(key, translations.get(key).with_text(
                text, source_text=message.source_text,
                state=TranslationState.DRAFT, origin=provider.name, today=today,
            ))
            result.from_provider.append(key)


def build_provider(config: ProjectConfig, name: str) -> Provider:
    """A provider by name: the built-ins first, then the project's own.

    Built-ins win on a name clash. A project that calls its engine "pseudo"
    is a project that would otherwise spend an afternoon working out why its
    translations are full of accents.
    """
    if name in BUILTIN_PROVIDERS:
        return get_provider(name)

    entry = config.providers.get(name)
    if entry is None:
        known = sorted({*BUILTIN_PROVIDERS, *config.providers})
        raise ConfigError(
            f"unknown provider {name!r}. Known: {', '.join(known)}"
        )

    # Imported here so a run that does not use an engine never loads urllib.
    from ..mt.http import HttpProvider, HttpProviderConfig

    fields = {f.name for f in dataclasses.fields(HttpProviderConfig)}
    unknown = set(entry.settings) - fields
    if unknown:
        raise ConfigError(
            f"[provider.{name}] does not understand {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(fields - {'name'}))}"
        )

    return HttpProvider(
        HttpProviderConfig(name=name, endpoint=entry.endpoint, **entry.settings)
    )


def _resolve_provider(config: ProjectConfig,
                      provider: Provider | str | None) -> Provider | None:
    if provider is None:
        return None
    if isinstance(provider, str):
        return build_provider(config, provider)
    return provider


def _batched(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]
