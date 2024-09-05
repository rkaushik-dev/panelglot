"""Measuring a string the way the panel will draw it.

Three things stand between the characters in the catalog and the pixels on the
glass, and getting any of them wrong makes the fitting check useless.

The mnemonic marker is not drawn. ``&Print`` is five characters wide, not six,
and ``Date&&Time`` is nine. Measuring the raw string overstates every caption
that has a mnemonic, which is most of the buttons.

Wrapping is not splitting on spaces. Chinese has no spaces and breaks between
almost any two characters, so a Traditional Chinese caption that looks like
one long word wraps fine, and treating it as unbreakable would report an
overflow that does not happen.

And a control that cannot wrap does not wrap. A static with SS_LEFTNOWORDWRAP
clips, so its budget is one line no matter how tall the control is.
"""

from __future__ import annotations

import unicodedata

from .font import FontMetrics

__all__ = [
    "drawn_text",
    "mnemonic_of",
    "wrap",
    "line_count",
    "fits",
    "overflow_px",
    "is_breakable_after",
]

#: Characters after which a line may break without a space being present.
#: The CJK ranges plus the punctuation that trails them.
_BREAK_AFTER_RANGES: tuple[tuple[int, int], ...] = (
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x2E80, 0x2EFF),   # CJK radicals
    (0x3000, 0x303F),   # CJK punctuation
    (0x3040, 0x30FF),   # Kana
    (0x3400, 0x4DBF),   # CJK extension A
    (0x4E00, 0x9FFF),   # CJK unified
    (0xAC00, 0xD7AF),   # Hangul syllables
    (0xF900, 0xFAFF),   # CJK compatibility
    (0xFF00, 0xFF60),   # Fullwidth forms
)

#: Never start a line with one of these, even though the character before it
#: is breakable. Closing brackets and trailing punctuation, mostly.
_NO_LINE_START = "、。，．：；！？）］｝」』〉》〕｠,.:;!?)]}"


def drawn_text(text: str) -> str:
    """The characters that actually reach the glass.

    ``&&`` collapses to one ampersand and a lone ``&`` disappears, marking the
    character after it. Everything else is untouched.
    """
    out: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char != "&":
            out.append(char)
            index += 1
            continue
        if index + 1 < length and text[index + 1] == "&":
            out.append("&")
            index += 2
            continue
        index += 1

    return "".join(out)


def mnemonic_of(text: str) -> str | None:
    """The character a lone ``&`` marks, upper-cased, or ``None``.

    Only the first one counts, which matches USER32: a second ``&`` in the
    same caption is drawn as a marker and then ignored.
    """
    index = 0
    length = len(text)

    while index < length:
        if text[index] != "&":
            index += 1
            continue
        if index + 1 < length and text[index + 1] == "&":
            index += 2
            continue
        if index + 1 < length:
            return text[index + 1].upper()
        return None

    return None


def is_breakable_after(char: str) -> bool:
    """True when a line may end with ``char`` even without a space."""
    codepoint = ord(char)
    return any(low <= codepoint <= high for low, high in _BREAK_AFTER_RANGES)


def wrap(text: str, font: FontMetrics, width_px: int) -> list[str]:
    """Break ``text`` into lines that fit ``width_px``, the way the panel does.

    Explicit newlines always break. Beyond that, breaks happen after spaces
    and after CJK characters. A single unbreakable run wider than the budget
    is left on its own line rather than being cut, because the control clips
    it and reporting one long line is more useful than reporting three
    invented ones.
    """
    if width_px <= 0:
        return [line for line in drawn_text(text).split("\n")]

    lines: list[str] = []
    for paragraph in drawn_text(text).split("\n"):
        lines.extend(_wrap_paragraph(paragraph, font, width_px))
    return lines


def _wrap_paragraph(text: str, font: FontMetrics, width_px: int) -> list[str]:
    if not text:
        return [""]

    lines: list[str] = []
    current = ""
    current_width = 0

    for chunk in _chunks(text):
        chunk_width = font.measure(chunk)

        if current and current_width + chunk_width > width_px:
            lines.append(current.rstrip())
            current = chunk.lstrip() if chunk.startswith(" ") else chunk
            current_width = font.measure(current)
            continue

        current += chunk
        current_width += chunk_width

    lines.append(current.rstrip())
    return lines or [""]


def _chunks(text: str) -> list[str]:
    """Split into the smallest units a break is allowed between.

    A chunk carries any trailing space with it, so the space that justified
    the break gets trimmed off the end of the line rather than starting the
    next one.
    """
    chunks: list[str] = []
    current = ""

    for index, char in enumerate(text):
        current += char

        if char == " ":
            following = text[index + 1] if index + 1 < len(text) else ""
            if following != " ":
                chunks.append(current)
                current = ""
            continue

        if is_breakable_after(char):
            following = text[index + 1] if index + 1 < len(text) else ""
            if following and following not in _NO_LINE_START:
                chunks.append(current)
                current = ""

    if current:
        chunks.append(current)
    return chunks


def line_count(text: str, font: FontMetrics, width_px: int) -> int:
    """How many lines ``text`` needs at ``width_px``."""
    return len(wrap(text, font, width_px))


def fits(text: str, font: FontMetrics, width_px: int, *, max_lines: int = 1) -> bool:
    """True when ``text`` fits in ``width_px`` across at most ``max_lines``."""
    if width_px <= 0:
        return False

    lines = wrap(text, font, width_px)
    if len(lines) > max_lines:
        return False
    return all(font.measure(line) <= width_px for line in lines)


def overflow_px(text: str, font: FontMetrics, width_px: int, *, max_lines: int = 1) -> int:
    """How many pixels ``text`` runs past its budget. Zero when it fits.

    For a single-line control this is the obvious subtraction. For a wrapping
    one it is the widest line's overhang, which is only ever non-zero when
    something could not be broken at all.
    """
    if not text:
        return 0
    if width_px <= 0:
        return font.measure(drawn_text(text))

    lines = wrap(text, font, width_px)
    if max_lines <= 1:
        lines = [drawn_text(text).replace("\n", " ")]

    widest = max((font.measure(line) for line in lines), default=0)
    return max(0, widest - width_px)


def visible_length(text: str) -> int:
    """Characters a translator would count, ignoring mnemonic markers.

    Combining marks do not add to the count because they do not add a cell.
    Used for the character budget on the fixed-grid panels.
    """
    return sum(1 for char in drawn_text(text) if not unicodedata.combining(char))
