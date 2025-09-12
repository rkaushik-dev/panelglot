"""A record of what a run did, for the runs nobody watched.

The build machines run extract, check and build on a schedule and mail the
result. When one of them takes eleven minutes instead of forty seconds, the
only evidence is that it took eleven minutes.

So a run can be asked to write down what it did: one JSON object per line, one
line per event, with how long each step took and how many things it touched.
JSON lines rather than a log format, because the questions people actually ask
are "which language was slow" and "how many did it read from cache", and both
of those are one filter over structured records and a paragraph of regular
expressions over text.

Three rules, all learned the hard way.

Nothing here ever raises. A diagnostics writer that takes a build down because
a disk filled up has made the problem worse than the problem.

Timings come from a monotonic clock. Wall clock time goes backwards twice a
year and one of those is inside our nightly window.

Values are recorded, never formatted. A field holds 44 and not "44 messages",
because the second one has to be parsed back out by whoever wants to add it up.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

__all__ = ["Event", "Diagnostics", "REDACTED", "redact"]

REDACTED = "***"

#: Field names whose values never reach the log. A provider key arriving in a
#: diagnostics file that gets mailed around is the one mistake here that
#: cannot be taken back.
_SECRET_NAMES = frozenset(
    {"token", "key", "api_key", "apikey", "secret", "password", "auth",
     "authorization", "credential"}
)


def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """A copy with anything that looks like a credential replaced.

    Matched on the field name rather than on the value, because a value that
    looks like a key is a guess and a field called auth_token is not.
    """
    cleaned: dict[str, Any] = {}
    for name, value in fields.items():
        lowered = name.lower()
        if any(secret in lowered for secret in _SECRET_NAMES):
            cleaned[name] = REDACTED
        elif isinstance(value, dict):
            cleaned[name] = redact(value)
        else:
            cleaned[name] = value
    return cleaned


@dataclass
class Event:
    """One thing that happened."""

    name: str
    fields: dict[str, Any] = field(default_factory=dict)
    seconds: float | None = None
    at: str = ""

    def to_json(self) -> str:
        payload: dict[str, Any] = {"at": self.at, "event": self.name}
        if self.seconds is not None:
            # Milliseconds, rounded. Microseconds on a step that takes four
            # minutes is noise with a decimal point in front of it.
            payload["ms"] = round(self.seconds * 1000)
        payload.update(redact(self.fields))
        return json.dumps(payload, ensure_ascii=False, sort_keys=False)


class Diagnostics:
    """Collects events, and optionally writes them out.

    Always collects. The in-memory list is what ``--timings`` prints and what
    the tests read, and it is small: a run produces a few dozen events, not a
    few thousand.
    """

    def __init__(self, path: Path | str | None = None, *,
                 clock=None, now=None) -> None:
        self.path = Path(path) if path is not None else None
        self.events: list[Event] = []
        self._clock = clock or time.monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._handle: TextIO | None = None
        self._broken = False

    # -- recording ------------------------------------------------------

    def record(self, name: str, seconds: float | None = None, **fields: Any) -> Event:
        """Note that something happened."""
        event = Event(name=name, fields=fields, seconds=seconds,
                      at=self._now().isoformat(timespec="seconds"))
        self.events.append(event)
        self._write(event)
        return event

    @contextmanager
    def step(self, name: str, **fields: Any):
        """Time a block, and record it whether or not it worked.

        A step that raised is the one anybody wants the timing for, so the
        event is written either way and carries what went wrong.
        """
        started = self._clock()
        extra: dict[str, Any] = {}
        try:
            yield extra
        except BaseException as exc:
            self.record(name, self._clock() - started, ok=False,
                        error=type(exc).__name__, **{**fields, **extra})
            raise
        else:
            self.record(name, self._clock() - started, ok=True,
                        **{**fields, **extra})

    # -- reading back ---------------------------------------------------

    def total_seconds(self) -> float:
        return sum(event.seconds or 0.0 for event in self.events)

    def slowest(self, limit: int = 5) -> list[Event]:
        timed = [event for event in self.events if event.seconds is not None]
        return sorted(timed, key=lambda e: -(e.seconds or 0.0))[:limit]

    def summary(self) -> str:
        if not self.events:
            return "nothing recorded"
        return (
            f"{len(self.events)} events, {self.total_seconds():.2f}s accounted for"
        )

    # -- the file -------------------------------------------------------

    def _write(self, event: Event) -> None:
        if self.path is None or self._broken:
            return

        try:
            if self._handle is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._handle = self.path.open("a", encoding="utf-8", newline="\n")
            self._handle.write(event.to_json() + "\n")
            self._handle.flush()
        except OSError:
            # Never take a build down for this. Stop trying, keep collecting
            # in memory, and let the command carry on doing its actual job.
            self._broken = True
            self.close()

    def close(self) -> None:
        if self._handle is not None:
            with suppress(OSError):
                self._handle.close()
            self._handle = None

    def __enter__(self) -> Diagnostics:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def path_from_environment(name: str = "V4T_LOG") -> Path | None:
    """A log path out of the environment, for a runner that owns the command.

    The CI job knows where its artifacts go and the command line inside it is
    usually somebody else's. An environment variable is the seam that does not
    require editing the schedule.
    """
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None
