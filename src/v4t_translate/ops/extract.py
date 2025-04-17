"""Read every configured source and update the catalog.

This is the operation everything else depends on. It reads the sources, merges
the result into whatever catalog already exists, carries translations across
rewordings, and writes the lot back out.

It is also the operation people run most often and trust least, so it can be
asked not to write anything. ``dry_run`` produces the same report from the
same work and leaves the tree alone, which is what makes it safe to run
against a checkout somebody else is editing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.cache import ExtractionCache, fingerprint_file
from ..catalog.merge import MergeReport, carry_translations, merge_catalog
from ..catalog.store import (
    Catalog,
    load_catalog,
    load_translations,
    save_catalog,
    save_translations,
)
from ..config import ProjectConfig, SourceEntry
from ..errors import SourceError
from ..sources.base import Extraction, SourceOptions, merge_extractions
from ..sources.registry import get_source

__all__ = ["ExtractResult", "extract_project"]


@dataclass
class ExtractResult:
    """What an extraction run did."""

    catalog: Catalog
    report: MergeReport
    extractions: list[Extraction] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    """Sources that could not be read, with the reason."""

    cache_summary: str = ""
    """How much of the run came out of the cache."""

    @property
    def warnings(self) -> list[str]:
        return [w for extraction in self.extractions for w in extraction.warnings]

    @property
    def message_count(self) -> int:
        return len(self.catalog)

    def stats_by_source(self) -> dict[str, dict[str, int]]:
        return {extraction.source: dict(extraction.stats) for extraction in self.extractions}


def cache_path(config: ProjectConfig) -> Path:
    """Where the extraction cache lives."""
    return config.root / config.catalog_dir / ".extraction-cache.json"


def extract_project(
    config: ProjectConfig,
    *,
    dry_run: bool = False,
    keep_going: bool = False,
    use_cache: bool = True,
) -> ExtractResult:
    """Extract every configured source and update the catalog on disk.

    ``keep_going`` turns an unreadable source into a note in
    :attr:`ExtractResult.skipped` instead of an exception. Useful when one of
    the sibling checkouts is not present, which on a developer machine is most
    of the time.

    ``use_cache`` skips re-parsing a source whose content has not changed.
    Turn it off to prove that a result came from the files rather than from
    something remembered, which is worth doing before believing a surprise.
    """
    cache = ExtractionCache.load(cache_path(config)) if use_cache else ExtractionCache()

    extractions: list[Extraction] = []
    skipped: list[str] = []

    for entry in config.sources:
        try:
            extractions.append(_read_one(config, entry, cache))
        except SourceError as exc:
            if not keep_going:
                raise
            skipped.append(f"{entry.describe()}: {exc}")

    extracted = merge_extractions(extractions)

    existing = _load_existing(config)
    catalog, report = merge_catalog(existing, extracted)

    result = ExtractResult(
        catalog=catalog, report=report, extractions=extractions, skipped=skipped,
        cache_summary=cache.summary,
    )
    if dry_run:
        return result

    save_catalog(config.catalog_path(), catalog)
    result.written.append(config.catalog_path())

    if use_cache:
        cache.restrict_to([e.source for e in extractions])
        cache.save(cache_path(config))

    for tag in config.target_tags():
        path = config.translations_path(tag)
        translations = load_translations(path)
        before = (len(translations), translations.counts())
        carry_translations(translations, report, catalog=catalog)
        if (len(translations), translations.counts()) != before or not path.exists():
            save_translations(path, translations)
            result.written.append(path)

    return result


def _read_one(config: ProjectConfig, entry: SourceEntry,
              cache: ExtractionCache) -> Extraction:
    options = SourceOptions(
        path=(config.root / entry.path).resolve(),
        encoding=entry.encoding,
        root=config.root.resolve(),
        symbols_path=(config.root / entry.symbols).resolve() if entry.symbols else None,
        protected_patterns=config.protected_patterns,
    )

    fingerprint = _fingerprint(options, config.protected_patterns)
    cached = cache.lookup(options.relative(), fingerprint)
    if cached is not None:
        return Extraction(
            source=options.relative(),
            messages=list(cached.messages),
            warnings=list(cached.warnings),
            stats=dict(cached.stats),
        )

    extraction = get_source(entry.kind).extract(options)
    cache.store(extraction.source, fingerprint, extraction.messages,
                extraction.warnings, extraction.stats)
    return extraction


def _fingerprint(options: SourceOptions, patterns: tuple[str, ...]) -> str:
    """What has to be the same for a cached extraction to still be right.

    The source, the symbols file beside it, and the protected patterns, which
    decide which messages come out marked untranslatable. Leaving the patterns
    out meant editing them changed nothing until somebody touched the rc.
    """
    source = fingerprint_file(options.path)
    if not source:
        return ""

    parts = [source]
    if options.symbols_path is not None:
        parts.append(fingerprint_file(options.symbols_path))
    parts.extend(patterns)

    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:32]


def _load_existing(config: ProjectConfig) -> Catalog:
    path = config.catalog_path()
    if path.exists():
        return load_catalog(path)
    return Catalog(project=config.name, source_locale=config.source_locale.tag)
