"""Getting rid of what is no longer needed.

Three years of rounds leave things behind. Translation files hold answers to
strings that were deleted two releases ago, the memory holds every draft
anybody ever imported by mistake, and the cache holds extractions for source
files that are not in the config any more.

None of it is wrong, exactly. It is just noise in a file people read, and the
translation files are read: they are in the repository and they turn up in
every diff.

Nothing here deletes anything that cannot be got back. Retired translations
are in git, and the memory is a cache. The one thing it will not do without
being asked twice is drop memory units, because those are the only copy of
answers that came from a workbook nobody kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.store import Catalog, load_translations, save_translations
from ..config import ProjectConfig
from ..mt.memory import TranslationMemory
from .extract import cache_path
from .memory import memory_path
from .project import require_catalog

__all__ = ["PruneResult", "prune_project"]


@dataclass
class PruneResult:
    """What a prune removed."""

    orphans: dict[str, list[str]] = field(default_factory=dict)
    """Translations dropped, per language."""

    memory_units: int = 0
    cache_removed: bool = False
    written: list[Path] = field(default_factory=list)
    freed_bytes: int = 0

    @property
    def total_orphans(self) -> int:
        return sum(len(keys) for keys in self.orphans.values())

    def __bool__(self) -> bool:
        return bool(self.total_orphans or self.memory_units or self.cache_removed)

    def summary(self) -> str:
        if not self:
            return "nothing to prune"
        parts = [f"{self.total_orphans} translations"]
        if self.memory_units:
            parts.append(f"{self.memory_units} memory units")
        if self.cache_removed:
            parts.append("the extraction cache")
        return f"removed {', '.join(parts)}, {self.freed_bytes} bytes"


def prune_project(config: ProjectConfig, *, drop_memory: bool = False,
                  drop_cache: bool = False, dry_run: bool = False) -> PruneResult:
    """Drop what the current catalog does not need.

    ``drop_memory`` also removes memory units whose English is not in the
    catalog any more. Off by default: a memory unit can be the only surviving
    copy of an answer from a workbook nobody kept.
    """
    catalog = require_catalog(config)
    result = PruneResult()

    _prune_translations(config, catalog, result, dry_run=dry_run)

    if drop_memory:
        _prune_memory(config, catalog, result, dry_run=dry_run)

    if drop_cache:
        _prune_cache(config, result, dry_run=dry_run)

    return result


def _prune_translations(config: ProjectConfig, catalog: Catalog,
                        result: PruneResult, *, dry_run: bool) -> None:
    keys = set(catalog.messages)

    for tag in config.target_tags():
        path = config.translations_path(tag)
        if not path.exists():
            continue

        before = path.stat().st_size
        translations = load_translations(path)
        gone = translations.restrict_to(keys)

        if not gone:
            continue

        result.orphans[tag] = gone
        if dry_run:
            continue

        save_translations(path, translations)
        result.written.append(path)
        result.freed_bytes += max(0, before - path.stat().st_size)


def _prune_memory(config: ProjectConfig, catalog: Catalog, result: PruneResult,
                  *, dry_run: bool) -> None:
    path = memory_path(config)
    if not path.exists():
        return

    live = set(catalog.texts().values())
    before = path.stat().st_size

    with TranslationMemory(path) as memory:
        for tag in memory.locales():
            for source in memory.sources_for(tag):
                if source in live:
                    continue
                result.memory_units += 1
                if not dry_run:
                    memory.forget(tag, source)

    if dry_run or not result.memory_units:
        return

    result.written.append(path)
    result.freed_bytes += max(0, before - path.stat().st_size)


def _prune_cache(config: ProjectConfig, result: PruneResult, *,
                 dry_run: bool) -> None:
    path = cache_path(config)
    if not path.exists():
        return

    result.cache_removed = True
    if dry_run:
        return

    result.freed_bytes += path.stat().st_size
    path.unlink()
