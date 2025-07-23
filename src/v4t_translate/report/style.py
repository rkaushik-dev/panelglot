"""Colour and width for the terminal report.

Colour is off unless the output is a terminal that wants it. The rule is the
one everybody has settled on: honour ``NO_COLOR`` if it is set at all, honour
``FORCE_COLOR`` the other way, and otherwise ask whether stdout is a tty.

That matters here rather than being a nicety. The check output gets redirected
into a file and mailed to a distributor about once a round, and escape codes
in that file make the report unreadable to exactly the person it is for.

Width comes from the terminal when there is one and is capped anyway. A
finding wrapped to 200 columns is one line that nobody's eye can follow back
to its start.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

from ..rules.result import Severity

__all__ = ["Palette", "palette_for", "terminal_width", "MAX_WIDTH", "MIN_WIDTH"]

#: Beyond this a line is one long line rather than a readable one.
MAX_WIDTH = 100

#: Below this, wrapping does more harm than the overflow it prevents.
MIN_WIDTH = 40

_RESET = "\033[0m"

_CODES = {
    "error": "\033[31m",
    "warning": "\033[33m",
    "info": "\033[36m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "source": "\033[36m",
    "target": "\033[32m",
}


@dataclass(frozen=True)
class Palette:
    """How to colour a report, or how not to."""

    enabled: bool = False

    def paint(self, text: str, style: str) -> str:
        code = _CODES.get(style)
        if not self.enabled or code is None or not text:
            return text
        return f"{code}{text}{_RESET}"

    def severity(self, text: str, severity: Severity) -> str:
        return self.paint(text, str(severity))

    def dim(self, text: str) -> str:
        return self.paint(text, "dim")

    def bold(self, text: str) -> str:
        return self.paint(text, "bold")


def wants_colour(stream=None) -> bool:
    """Whether to colour output on ``stream``.

    ``NO_COLOR`` wins over ``FORCE_COLOR`` because the cost of getting it
    wrong is asymmetric: an uncoloured report is readable everywhere and a
    coloured one is not.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False

    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


def palette_for(stream=None, *, force: bool | None = None) -> Palette:
    """The palette to use. ``force`` overrides the environment entirely."""
    if force is not None:
        return Palette(enabled=force)
    return Palette(enabled=wants_colour(stream))


def terminal_width(default: int = 80) -> int:
    """How wide to wrap, between the two limits."""
    try:
        width = shutil.get_terminal_size((default, 24)).columns
    except (OSError, ValueError):
        width = default

    return max(MIN_WIDTH, min(MAX_WIDTH, width))
