"""Which characters a project actually needs, and which the font has.

Two questions, and they pull in opposite directions.

The first is what the glyph rule already asks per string: can this font draw
this character. The answer per string is not enough for planning, because the
useful form is the set. Six hundred fitting findings and one glyph finding are
the same afternoon; forty missing ideographs and none of them in the font is a
conversation with the firmware team about flash.

The second is the reverse, and it is the one nobody asks. The Traditional
Chinese font on the 800x600 board covers most of the BMP because it was built
from a desktop font, and the panel has 2MB of flash for everything. A project
that ships eleven languages uses about four thousand distinct characters. The
rest is a rounding error in a font file and half the flash budget on the
board.

So this counts both directions, and the subset it produces is the answer to
the second. It is deliberately built from the catalog rather than from a
language: the difference between "every character Chinese can use" and "every
character this product says in Chinese" is two orders of magnitude.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .font import FontMetrics
from .measure import drawn_text

__all__ = ["CoverageReport", "measure_coverage", "subset_metrics", "used_codepoints"]

#: Never counted as needed. These never reach the font: the renderer eats the
#: tab and the newline, and a stray control character is a data problem rather
#: than a glyph one.
_IGNORED = frozenset("\t\n\r\x00")


def used_codepoints(texts: list[str]) -> Counter[int]:
    """Every codepoint the given strings draw, with how often.

    Counted through ``drawn_text`` so a mnemonic ampersand does not appear as
    a required glyph. The panel never draws it; it draws an underline.
    """
    counts: Counter[int] = Counter()
    for text in texts:
        for char in drawn_text(text):
            if char not in _IGNORED:
                counts[ord(char)] += 1
    return counts


@dataclass
class CoverageReport:
    """What one font can and cannot do for one set of strings."""

    font: str
    needed: int = 0
    """Distinct codepoints the strings use."""

    covered: int = 0
    missing_codepoints: list[int] = field(default_factory=list)
    counts: Counter[int] = field(default_factory=Counter)

    unused: int = 0
    """Codepoints the font carries that nothing in the project draws."""

    font_size: int = 0
    """Codepoints the font carries in total."""

    examples: dict[int, str] = field(default_factory=dict)
    """One string per missing codepoint, so a report can show where it hurts."""

    @property
    def is_complete(self) -> bool:
        return not self.missing_codepoints

    @property
    def fraction(self) -> float:
        return self.covered / self.needed if self.needed else 1.0

    def missing_characters(self) -> list[str]:
        """The missing ones as characters, most used first."""
        return [
            chr(cp)
            for cp in sorted(self.missing_codepoints,
                             key=lambda cp: (-self.counts[cp], cp))
        ]

    def describe(self) -> str:
        head = (
            f"{self.font}: {self.covered}/{self.needed} needed glyphs "
            f"({self.fraction:.0%})"
        )
        if self.unused:
            head += f", {self.unused} of {self.font_size} carried but unused"
        return head

    def worst_first(self) -> list[tuple[str, int, str]]:
        """Missing characters as ``(char, uses, an example string)``."""
        return [
            (chr(cp), self.counts[cp], self.examples.get(cp, ""))
            for cp in sorted(self.missing_codepoints,
                             key=lambda cp: (-self.counts[cp], cp))
        ]


def measure_coverage(font: FontMetrics, texts: list[str]) -> CoverageReport:
    """Compare what ``texts`` need against what ``font`` carries."""
    counts = used_codepoints(texts)

    report = CoverageReport(
        font=font.name,
        needed=len(counts),
        counts=counts,
        font_size=font.coverage_size,
    )

    for codepoint in sorted(counts):
        if font.covers(chr(codepoint)):
            report.covered += 1
        else:
            report.missing_codepoints.append(codepoint)

    report.unused = max(0, font.coverage_size - report.covered)
    report.examples = _examples(report.missing_codepoints, texts)

    return report


def _examples(missing: list[int], texts: list[str]) -> dict[int, str]:
    """One string per missing codepoint, the shortest one that contains it.

    The shortest rather than the first: a report that shows a whole message
    box paragraph to point at one character is a report nobody reads.
    """
    wanted = {chr(cp) for cp in missing}
    found: dict[int, str] = {}

    for text in texts:
        drawn = drawn_text(text)
        for char in wanted:
            if char not in drawn:
                continue
            existing = found.get(ord(char))
            if existing is None or len(text) < len(existing):
                found[ord(char)] = text

    return found


def subset_metrics(font: FontMetrics, texts: list[str], *,
                   keep_ascii: bool = True) -> FontMetrics:
    """A copy of ``font`` carrying only the glyphs ``texts`` draw.

    ASCII is kept whatever the catalog says. Every panel shows a firmware
    version, an IP address and an error code that never went through this
    tool, and a font that dropped the digits because no translated string
    happened to contain a 7 would be a very confusing morning.
    """
    counts = used_codepoints(texts)
    wanted = {cp for cp in counts if font.covers(chr(cp))}

    if keep_ascii:
        wanted.update(cp for cp in range(0x20, 0x7F) if font.covers(chr(cp)))

    reduced = FontMetrics(
        name=f"{font.name}-subset",
        pixel_size=font.pixel_size,
        line_height=font.line_height,
        default_width=font.default_width,
        widths={cp: font.advance(chr(cp)) for cp in sorted(wanted)},
    )
    reduced.invalidate()
    return reduced
