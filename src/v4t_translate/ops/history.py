"""Coverage over time, which is the only version of it anybody acts on.

"German is 82% approved" answers nothing. The question is always whether it
will be finished by the date somebody promised, and that needs two numbers a
week apart. Without a record the answer comes from whoever remembers what it
said last Tuesday, which in practice is nobody.

So a run can append today's figures to a file, one JSON object per line, and a
later run can read it back and say what has moved. Same format as the
diagnostics log for the same reason: the questions are filters, not text
searches.

Two things this deliberately does not do.

It does not project a finish date. Two points and a straight line would give a
date, and the date would be wrong in a way that reads as authoritative:
translation does not arrive at a constant rate, it arrives in deliveries. What
it reports is the movement and how long ago, and lets the person who knows
about the deliveries do the arithmetic.

It does not write unless asked. A read-only command that quietly appends to a
file is a read-only command that makes a diff on somebody's branch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..config import ProjectConfig
from ..reproducible import build_date
from .stats import ProjectStats

__all__ = [
    "HISTORY_NAME",
    "Snapshot",
    "Movement",
    "history_path",
    "record",
    "read_history",
    "movement_since",
]

HISTORY_NAME = "coverage.jsonl"


@dataclass(frozen=True)
class Snapshot:
    """What one language looked like on one day."""

    day: str
    locale: str
    approved: int
    translated: int
    total: int
    outstanding_words: int

    @property
    def fraction(self) -> float:
        return self.approved / self.total if self.total else 0.0

    def to_json(self) -> str:
        return json.dumps({
            "day": self.day,
            "locale": self.locale,
            "approved": self.approved,
            "translated": self.translated,
            "total": self.total,
            "outstandingWords": self.outstanding_words,
        }, ensure_ascii=False)

    @classmethod
    def parse(cls, line: str) -> Snapshot | None:
        """One line, or None when it is not one.

        A history file is append-only and lives on a share, so a torn line is
        a real possibility. One bad line loses one day, not the file.
        """
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        try:
            return cls(
                day=str(payload["day"]),
                locale=str(payload["locale"]),
                approved=int(payload["approved"]),
                translated=int(payload["translated"]),
                total=int(payload["total"]),
                outstanding_words=int(payload.get("outstandingWords", 0)),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Movement:
    """What one language has done between two snapshots."""

    locale: str
    before: Snapshot
    after: Snapshot

    @property
    def approved_change(self) -> int:
        return self.after.approved - self.before.approved

    @property
    def words_change(self) -> int:
        return self.after.outstanding_words - self.before.outstanding_words

    @property
    def days(self) -> int:
        try:
            first = date.fromisoformat(self.before.day)
            second = date.fromisoformat(self.after.day)
        except ValueError:
            return 0
        return (second - first).days

    def describe(self) -> str:
        span = f" over {self.days} days" if self.days else ""
        if self.approved_change > 0:
            moved = f"+{self.approved_change} approved"
        elif self.approved_change < 0:
            moved = f"{self.approved_change} approved"
        else:
            moved = "no change"

        return (
            f"{self.locale}: {moved}{span}, "
            f"{self.after.approved}/{self.after.total} "
            f"({self.after.fraction:.0%}), "
            f"{self.after.outstanding_words} words left"
        )


def history_path(config: ProjectConfig) -> Path:
    return config.root / config.catalog_dir / HISTORY_NAME


def record(config: ProjectConfig, stats: ProjectStats, *,
           day: date | None = None) -> list[Snapshot]:
    """Append today's figures. Returns what was written."""
    stamp = (day or build_date()).isoformat()

    snapshots = [
        Snapshot(day=stamp, locale=entry.tag, approved=entry.approved,
                 translated=entry.translated, total=entry.total,
                 outstanding_words=entry.outstanding_words)
        for entry in stats.locales
    ]

    path = history_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for snapshot in snapshots:
            handle.write(snapshot.to_json() + "\n")

    return snapshots


def read_history(config: ProjectConfig) -> list[Snapshot]:
    """Every snapshot on file, oldest first, skipping anything unreadable."""
    path = history_path(config)
    if not path.exists():
        return []

    found: list[Snapshot] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        snapshot = Snapshot.parse(line)
        if snapshot is not None:
            found.append(snapshot)
    return found


def movement_since(config: ProjectConfig, stats: ProjectStats, *,
                   day: date | None = None) -> list[Movement]:
    """Compare today's figures against the newest older snapshot per language.

    The newest older one rather than the oldest. The interesting comparison is
    against the last time anybody looked, not against the day the project
    started, and a run recorded twice in one day must not compare against
    itself and report no change.
    """
    stamp = (day or build_date()).isoformat()
    latest: dict[str, Snapshot] = {}

    for snapshot in read_history(config):
        if snapshot.day < stamp:
            latest[snapshot.locale] = snapshot

    movements: list[Movement] = []
    for entry in stats.locales:
        before = latest.get(entry.tag)
        if before is None:
            continue
        movements.append(Movement(
            locale=entry.tag,
            before=before,
            after=Snapshot(day=stamp, locale=entry.tag, approved=entry.approved,
                           translated=entry.translated, total=entry.total,
                           outstanding_words=entry.outstanding_words),
        ))

    return movements
