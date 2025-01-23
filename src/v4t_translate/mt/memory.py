"""The translation memory.

Every approved translation this project has ever had, keyed by language and
source text, in a SQLite file next to the catalog. It answers two questions:

is this exact English already translated in this language, and is something
close enough to it translated that a person should look at it.

The first is a lookup and is always safe. The second is a suggestion and is
never applied without being marked, because a 90% match on "Purge offset must
be less than group offset" against "Purge offset must be less than pen offset"
is a different sentence with a different meaning.

SQLite rather than a JSON file because this grows to tens of thousands of rows
across a dozen languages and the fuzzy search has to scan a subset of it on
every miss. It is also the one file here that is a cache: deleting it loses
nothing that is not recoverable from the per-locale catalogs.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from ..catalog.ids import normalize_source
from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet, TranslationState

__all__ = ["Match", "TranslationMemory", "EXACT", "DEFAULT_THRESHOLD"]

#: Score of an exact match. Kept as a name so callers compare against it
#: rather than against a bare 1.0 they have to know the meaning of.
EXACT = 1.0

#: How similar a fuzzy candidate has to be before it is worth showing.
DEFAULT_THRESHOLD = 0.75

#: Candidates whose length is outside this ratio of the query are skipped
#: before the expensive comparison. A string half the length is never a match.
_LENGTH_WINDOW = 0.6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    locale      TEXT NOT NULL,
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    length      INTEGER NOT NULL,
    origin      TEXT NOT NULL DEFAULT '',
    updated     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (locale, source)
);
CREATE INDEX IF NOT EXISTS units_by_length ON units (locale, length);
"""


@dataclass(frozen=True)
class Match:
    """One translation memory hit."""

    source: str
    target: str
    score: float
    locale: str
    origin: str = ""

    @property
    def is_exact(self) -> bool:
        return self.score >= EXACT


class TranslationMemory:
    """SQLite backed translation memory."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        target = ":memory:" if self.path is None else str(self.path)

        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(target)
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> TranslationMemory:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- writing --------------------------------------------------------

    def remember(self, locale: str, source: str, target: str, *, origin: str = "",
                 updated: str = "") -> None:
        """Record one translation. A later answer replaces an earlier one."""
        if not source or not target:
            return

        normalized = normalize_source(source)
        self._connection.execute(
            "INSERT INTO units (locale, source, target, length, origin, updated) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(locale, source) DO UPDATE SET "
            "target=excluded.target, origin=excluded.origin, updated=excluded.updated",
            (locale, normalized, target, len(normalized), origin, updated),
        )
        self._connection.commit()

    def absorb(self, catalog: Catalog, translations: TranslationSet, *,
               states: tuple[TranslationState, ...] = (TranslationState.APPROVED,),
               origin: str = "catalog") -> int:
        """Take everything in a translation set that is good enough to reuse.

        Only approved by default. Remembering a draft would let one guess seed
        the next one, and after three rounds nobody can tell which strings a
        person actually looked at.
        """
        wanted = set(states)
        added = 0

        for key, translation in translations.entries.items():
            message = catalog.get(key)
            if message is None or translation.state not in wanted or not translation.text:
                continue
            self.remember(
                translations.locale, message.source_text, translation.text,
                origin=origin, updated=translation.updated or "",
            )
            added += 1

        return added

    def forget(self, locale: str, source: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM units WHERE locale = ? AND source = ?",
            (locale, normalize_source(source)),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    # -- reading --------------------------------------------------------

    def recall(self, locale: str, source: str) -> Match | None:
        """Exact match only. ``None`` when there is not one."""
        normalized = normalize_source(source)
        with closing(self._connection.execute(
            "SELECT target, origin FROM units WHERE locale = ? AND source = ?",
            (locale, normalized),
        )) as cursor:
            row = cursor.fetchone()

        if row is None:
            return None
        return Match(source=normalized, target=row[0], score=EXACT, locale=locale,
                     origin=row[1])

    def suggest(self, locale: str, source: str, *,
                threshold: float = DEFAULT_THRESHOLD, limit: int = 3) -> list[Match]:
        """Close matches, best first. Includes the exact one when there is one."""
        normalized = normalize_source(source)
        length = len(normalized)
        if not length:
            return []

        low = int(length * _LENGTH_WINDOW)
        high = int(length / _LENGTH_WINDOW) + 1

        matcher = SequenceMatcher()
        matcher.set_seq2(normalized)

        found: list[Match] = []
        with closing(self._connection.execute(
            "SELECT source, target, origin FROM units "
            "WHERE locale = ? AND length BETWEEN ? AND ?",
            (locale, low, high),
        )) as cursor:
            for candidate, target, origin in cursor:
                matcher.set_seq1(candidate)
                # Two cheap upper bounds before the real comparison. On a
                # memory of thirty thousand units this is the difference
                # between a second and a minute.
                if matcher.real_quick_ratio() < threshold:
                    continue
                if matcher.quick_ratio() < threshold:
                    continue
                score = matcher.ratio()
                if score >= threshold:
                    found.append(Match(source=candidate, target=target, score=score,
                                       locale=locale, origin=origin))

        found.sort(key=lambda match: (-match.score, match.source))
        return found[:limit]

    def best(self, locale: str, source: str, *,
             threshold: float = DEFAULT_THRESHOLD) -> Match | None:
        """The single best match, exact or fuzzy."""
        exact = self.recall(locale, source)
        if exact is not None:
            return exact
        matches = self.suggest(locale, source, threshold=threshold, limit=1)
        return matches[0] if matches else None

    # -- housekeeping ---------------------------------------------------

    def __len__(self) -> int:
        with closing(self._connection.execute("SELECT COUNT(*) FROM units")) as cursor:
            return int(cursor.fetchone()[0])

    def locales(self) -> list[str]:
        with closing(self._connection.execute(
            "SELECT DISTINCT locale FROM units ORDER BY locale"
        )) as cursor:
            return [row[0] for row in cursor]

    def counts(self) -> dict[str, int]:
        with closing(self._connection.execute(
            "SELECT locale, COUNT(*) FROM units GROUP BY locale ORDER BY locale"
        )) as cursor:
            return {row[0]: row[1] for row in cursor}

    def clear(self, locale: str | None = None) -> int:
        if locale is None:
            cursor = self._connection.execute("DELETE FROM units")
        else:
            cursor = self._connection.execute(
                "DELETE FROM units WHERE locale = ?", (locale,)
            )
        self._connection.commit()
        return cursor.rowcount
