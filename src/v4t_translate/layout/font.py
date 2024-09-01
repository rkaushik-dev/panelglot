"""Bitmap font metrics.

The panels do not have a font engine. Each one carries a compiled bitmap font
with a fixed glyph set, and anything outside that set draws as whatever the
firmware puts in the blank slot: on the Mini that is a filled box, on the
older TIJ boards it is nothing at all, which is worse because it looks like a
spacing bug.

So two questions have to be answerable before a translation ships:

* is every character in the font at all;
* how wide is the string once it is drawn.

Both are answered from a metrics file rather than from the font itself. The
fonts are built by a tool that lives in the firmware repo and we do not want
this package depending on it, so it exports a small text format instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import SourceError

__all__ = ["FontMetrics", "parse_metrics", "load_metrics", "monospace"]

_HEADER = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_RANGE = re.compile(r"^([0-9A-Fa-f]{2,6})(?:\.\.([0-9A-Fa-f]{2,6}))?\s+(\d+)$")


@dataclass
class FontMetrics:
    """Advance widths and coverage for one compiled panel font."""

    name: str = "unnamed"
    pixel_size: int = 8
    line_height: int = 0
    default_width: int = 0
    """Advance used for a codepoint that is covered but has no explicit width."""

    widths: dict[int, int] = field(default_factory=dict)
    """Codepoint to advance width in pixels."""

    ranges: list[tuple[int, int]] = field(default_factory=list)
    """Covered codepoint ranges, inclusive at both ends."""

    def __post_init__(self) -> None:
        if not self.line_height:
            self.line_height = self.pixel_size + 2
        if not self.default_width:
            self.default_width = max(1, self.pixel_size // 2)

    def covers(self, char: str) -> bool:
        """True when the font can draw ``char``."""
        codepoint = ord(char)
        if codepoint in self.widths:
            return True
        return any(low <= codepoint <= high for low, high in self.ranges)

    def missing(self, text: str) -> list[str]:
        """Characters of ``text`` the font cannot draw, in order, deduplicated.

        Control characters are skipped. A tab in a menu caption is an
        instruction to the renderer, not something the font has to hold.
        """
        seen: list[str] = []
        for char in text:
            if char in "\t\n\r" or char in seen:
                continue
            if not self.covers(char):
                seen.append(char)
        return seen

    def advance(self, char: str) -> int:
        """Width of one character in pixels, including the gap after it."""
        codepoint = ord(char)
        explicit = self.widths.get(codepoint)
        if explicit is not None:
            return explicit
        if self.covers(char):
            return self.default_width
        # An uncoverable character still takes space: the firmware draws its
        # blank slot at the default width. Charging nothing would let an
        # unfittable string pass the fitting check as well as the glyph one.
        return self.default_width

    def measure(self, text: str) -> int:
        """Rendered width of a single line, in pixels."""
        return sum(self.advance(char) for char in text if char not in "\n\r")

    @property
    def coverage_size(self) -> int:
        """How many codepoints this font can draw."""
        explicit = set(self.widths)
        total = len(explicit)
        for low, high in self.ranges:
            total += sum(1 for cp in range(low, high + 1) if cp not in explicit)
        return total


def monospace(width: int, *, pixel_size: int = 8, name: str = "monospace",
              ranges: list[tuple[int, int]] | None = None) -> FontMetrics:
    """A font where every character is ``width`` pixels.

    The Mini's character LCD really is like this, and it is what tests want
    when they are checking wrapping rather than metrics.
    """
    return FontMetrics(
        name=name,
        pixel_size=pixel_size,
        default_width=width,
        ranges=ranges if ranges is not None else [(0x20, 0x7E)],
    )


def parse_metrics(text: str, *, path: str | None = None) -> FontMetrics:
    """Read the metrics format the firmware font builder exports.

    Headers first, then one line per codepoint or range::

        name: PMingLiU
        pixel_size: 12
        line_height: 16
        default_width: 6

        20..7E 6
        4E00..9FFF 12
        20AC 7
    """
    metrics = FontMetrics()
    seen_header = False

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        header = _HEADER.match(line)
        if header and not _RANGE.match(line):
            _apply_header(metrics, header.group(1), header.group(2), path, number)
            seen_header = True
            continue

        entry = _RANGE.match(line)
        if entry is None:
            raise SourceError(f"{path or '<metrics>'}:{number}: cannot read {line!r}")

        low = int(entry.group(1), 16)
        high = int(entry.group(2), 16) if entry.group(2) else low
        width = int(entry.group(3))

        if high < low:
            raise SourceError(f"{path or '<metrics>'}:{number}: range runs backwards")

        if high == low:
            metrics.widths[low] = width
        else:
            metrics.ranges.append((low, high))
            if width != metrics.default_width:
                for codepoint in range(low, high + 1):
                    metrics.widths[codepoint] = width

    if not seen_header and not metrics.widths and not metrics.ranges:
        raise SourceError(f"{path or '<metrics>'}: no metrics in this file")

    metrics.__post_init__()
    return metrics


def load_metrics(path: Path | str) -> FontMetrics:
    """Read a metrics file from disk."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SourceError(f"{path} does not exist") from exc
    metrics = parse_metrics(text, path=str(path))
    if metrics.name == "unnamed":
        metrics.name = path.stem
    return metrics


def _apply_header(metrics: FontMetrics, key: str, value: str,
                  path: str | None, number: int) -> None:
    key = key.lower()
    if key == "name":
        metrics.name = value.strip()
        return

    if key not in ("pixel_size", "line_height", "default_width"):
        raise SourceError(f"{path or '<metrics>'}:{number}: unknown header {key!r}")

    try:
        setattr(metrics, key, int(value.strip()))
    except ValueError as exc:
        raise SourceError(
            f"{path or '<metrics>'}:{number}: {key} must be a number, got {value.strip()!r}"
        ) from exc
