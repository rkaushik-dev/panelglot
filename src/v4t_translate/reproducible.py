"""Building the same bytes twice.

The panel firmware is signed and archived, and a support call two years from
now starts with somebody rebuilding the exact language pack that shipped. If
the rebuild does not match the archive, the question stops being about the
customer's problem and becomes about which of the two files is real.

Only one thing in this toolchain is genuinely non-deterministic, and it is the
one every build tool gets caught by: the clock. Three outputs stamp the date
they were made. Two of them are read by tools that want it, so removing the
stamp is not the answer.

The answer is the convention everybody else settled on. ``SOURCE_DATE_EPOCH``
in the environment, seconds since the epoch, and every stamp comes from that
instead of from the clock. Set it to the commit time and a rebuild of that
commit produces the archive byte for byte.

Nothing here fails on a bad value. An unparseable ``SOURCE_DATE_EPOCH`` means
falling back to the clock and saying so, because a build machine with a
mangled environment variable should produce a warning and a build, not no
build.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

__all__ = [
    "SOURCE_DATE_EPOCH",
    "source_date_epoch",
    "build_datetime",
    "build_date",
    "is_pinned",
]

SOURCE_DATE_EPOCH = "SOURCE_DATE_EPOCH"


def source_date_epoch(environ: dict[str, str] | None = None) -> int | None:
    """The pinned build time in seconds, or None when it is not set or is junk.

    A negative value counts as junk. It parses, and a build stamped 1969 is
    not what anybody meant by it.
    """
    raw = (environ if environ is not None else os.environ).get(SOURCE_DATE_EPOCH, "")
    raw = raw.strip()
    if not raw:
        return None

    try:
        seconds = int(raw)
    except ValueError:
        return None

    return seconds if seconds >= 0 else None


def is_pinned(environ: dict[str, str] | None = None) -> bool:
    """Whether this build's timestamps come from the environment."""
    return source_date_epoch(environ) is not None


def build_datetime(environ: dict[str, str] | None = None) -> datetime:
    """The instant to stamp outputs with, in UTC.

    UTC always, pinned or not. A manifest that says 14:02 without saying where
    is a manifest that two people compare and disagree about.
    """
    seconds = source_date_epoch(environ)
    if seconds is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def build_date(environ: dict[str, str] | None = None) -> date:
    """The date to stamp outputs with."""
    return build_datetime(environ).date()
