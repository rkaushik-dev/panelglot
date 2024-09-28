"""Can the panel actually draw this string.

Three separate ways the answer is no, and none of them fail at build time.

The font does not have the glyph. The panel fonts are compiled subsets, so a
character outside the subset draws as a box on the Mini and as nothing at all
on the older TIJ boards.

The codepage cannot encode it. The TIJ resource build is still 8-bit for the
older boards, so a Turkish dotless i in a cp1252 build becomes a question mark
somewhere in the toolchain and nobody notices until a customer photographs it.

The panel cannot do double byte at all. The Mini's controller has a one byte
character path end to end, so Traditional Chinese on it is not a rendering
problem, it is a category error, and it is worth its own message because the
answer is "this language cannot ship on this panel", not "fix the string".
"""

from __future__ import annotations

from typing import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.measure import drawn_text
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["GlyphRule", "EncodingRule", "unencodable"]

#: How many missing characters to list before giving up and saying how many.
_LIST_LIMIT = 8


def unencodable(text: str, codepage: int) -> list[str]:
    """Characters of ``text`` that do not survive ``codepage``, deduplicated."""
    codec = f"cp{codepage}"
    bad: list[str] = []
    for char in text:
        if char in bad:
            continue
        try:
            char.encode(codec)
        except (UnicodeEncodeError, LookupError):
            bad.append(char)
    return bad


class GlyphRule:
    """Every character the translation draws is in the panel font."""

    name = "glyphs"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        missing = context.font.missing(drawn_text(translation.text))
        if not missing:
            return

        yield finding(
            self, context, message, translation,
            f"{_describe(missing)} not in the {context.font.name} font",
            detail=f"Missing codepoints: {_codepoints(missing)}. "
                   f"The panel draws a blank slot for each of them.",
        )


class EncodingRule:
    """The translation survives the panel's codepage, and its byte width."""

    name = "encoding"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        text = drawn_text(translation.text)

        if not context.panel.supports_dbcs and context.locale.double_byte:
            yield finding(
                self, context, message, translation,
                f"{context.locale.english_name} cannot be shown on "
                f"{context.panel.name} at all",
                detail=f"{context.panel.describe()} has a single byte character path. "
                       f"This language needs a panel that does not.",
            )
            return

        codepage = context.panel.codepage
        if codepage is None:
            return

        bad = unencodable(text, codepage)
        if not bad:
            return

        yield finding(
            self, context, message, translation,
            f"{_describe(bad)} cannot be encoded in codepage {codepage}",
            detail=f"Missing codepoints: {_codepoints(bad)}. "
                   f"The resource build is 8-bit for this panel and each of these "
                   f"becomes a question mark.",
        )


def _describe(characters: list[str]) -> str:
    if len(characters) == 1:
        return f"{characters[0]!r} is"
    shown = characters[:_LIST_LIMIT]
    listed = ", ".join(repr(c) for c in shown)
    if len(characters) > _LIST_LIMIT:
        return f"{listed} and {len(characters) - _LIST_LIMIT} more are"
    return f"{listed} are"


def _codepoints(characters: list[str]) -> str:
    return " ".join(f"U+{ord(c):04X}" for c in characters[:_LIST_LIMIT])
