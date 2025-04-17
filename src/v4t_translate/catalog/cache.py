"""Not re-reading a source that has not changed.

``V4T.rc`` is nine thousand lines and the config tool's is four. Parsing both
takes about a second, which is nothing once and quite a lot when ``check`` and
``build`` and ``stats`` each run an extraction first and somebody is going
round that loop while a translator is on the phone.

The fingerprint is the content hash, not the modification time. A checkout
touches every file it restores and a build machine that trusted mtimes would
re-parse everything on every run while a developer's machine, where mtimes are
stable, would not. Same tool, opposite behaviour, and the one that misbehaves
is the one nobody is watching.

The cache is disposable by construction: it stores what an extraction produced
and the fingerprint of what produced it. Delete it and the next run is slower
and identical. Anything that cannot say that about itself does not belong in
a cache file.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import CatalogError
from .model import Message
from .store import _message_from_json, _message_to_json

__all__ = ["CACHE_VERSION", "ExtractionCache", "fingerprint_file"]

#: Bumped whenever a change would make a cached extraction wrong. Which is
#: any change to what the readers produce, so this moves more than the catalog
#: format version does.
CACHE_VERSION = 2

_CHUNK = 64 * 1024


def fingerprint_file(path: Path) -> str:
    """Content hash of a file, or ``""`` when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()[:32]


@dataclass
class _Entry:
    fingerprint: str
    messages: list[Message] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class ExtractionCache:
    """What each source produced last time, keyed by its content."""

    entries: dict[str, _Entry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def lookup(self, source: str, fingerprint: str) -> _Entry | None:
        """The cached extraction for ``source``, if it still matches."""
        entry = self.entries.get(source)
        if entry is None or not fingerprint or entry.fingerprint != fingerprint:
            self.misses += 1
            return None
        self.hits += 1
        return entry

    def store(self, source: str, fingerprint: str, messages: list[Message],
              warnings: list[str], stats: dict[str, int]) -> None:
        if not fingerprint:
            # A source we could not fingerprint is a source we must not cache.
            self.entries.pop(source, None)
            return
        self.entries[source] = _Entry(
            fingerprint=fingerprint,
            messages=list(messages),
            warnings=list(warnings),
            stats=dict(stats),
        )

    def restrict_to(self, sources: list[str]) -> None:
        """Drop entries for sources the project no longer lists."""
        for stale in set(self.entries) - set(sources):
            del self.entries[stale]

    @property
    def summary(self) -> str:
        return f"{self.hits} cached, {self.misses} read"

    # -- persistence ----------------------------------------------------

    def save(self, path: Path | str) -> None:
        payload = {
            "version": CACHE_VERSION,
            "sources": {
                source: {
                    "fingerprint": entry.fingerprint,
                    "warnings": entry.warnings,
                    "stats": entry.stats,
                    "messages": [_message_to_json(m) for m in entry.messages],
                }
                for source, entry in sorted(self.entries.items())
            },
        }

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | str) -> ExtractionCache:
        """Read a cache file. Anything wrong with it means an empty cache.

        A corrupt cache must never be an error. It is derived data, the
        recovery is to ignore it, and a tool that refuses to run because its
        cache is broken is worse than one with no cache at all.
        """
        path = Path(path)
        if not path.exists():
            return cls()

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return cls()

        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            return cls()

        cache = cls()
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            return cls()

        for source, raw in sources.items():
            entry = _entry_from_json(source, raw)
            if entry is not None:
                cache.entries[source] = entry

        return cache


def _entry_from_json(source: str, raw: Any) -> _Entry | None:
    if not isinstance(raw, dict):
        return None

    fingerprint = raw.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return None

    try:
        messages = [
            _message_from_json(item, path=source, index=index)
            for index, item in enumerate(raw.get("messages", []))
        ]
    except CatalogError:
        return None

    return _Entry(
        fingerprint=fingerprint,
        messages=messages,
        warnings=[str(w) for w in raw.get("warnings", [])],
        stats={str(k): int(v) for k, v in (raw.get("stats") or {}).items()},
    )
