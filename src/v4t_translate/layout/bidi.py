"""Mixed direction text.

Arabic and Hebrew read right to left, and every string in this product that
matters to an operator has something left to right embedded in it: a pen
number, a voltage, a placeholder, or the product name.

The Unicode bidirectional algorithm mostly gets this right on its own. Where
it does not is at the *edges* of an embedded run, and it goes wrong in the
same way every time. "Pen 3" in an RTL paragraph puts the 3 on the left of
the word, which is correct. "Pen 3:" puts the colon on the far left, away
from the number it belongs to, because a neutral character between an RTL
context and an LTR run resolves to the paragraph direction.

The fix is a directional mark, and the translator has to put it there. This
module can tell whether one is needed and whether one is present; it does not
insert them, because where they go is a judgement about the sentence.
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "RLM",
    "LRM",
    "ALM",
    "MARKS",
    "direction_of",
    "has_mixed_direction",
    "runs",
    "needs_isolation",
]

#: Right to left mark. The one a translator into Arabic or Hebrew needs.
RLM = "‏"

#: Left to right mark.
LRM = "‎"

#: Arabic letter mark, which behaves like RLM for Arabic numerals.
ALM = "؜"

MARKS = (RLM, LRM, ALM)

#: Bidi categories that carry a strong direction.
_STRONG_LTR = frozenset({"L"})
_STRONG_RTL = frozenset({"R", "AL"})

#: Neutral categories. These take their direction from what surrounds them,
#: which is exactly the problem.
_NEUTRAL = frozenset({"WS", "ON", "B", "S", "CS", "ET", "ES"})


def direction_of(char: str) -> str:
    """``"ltr"``, ``"rtl"``, ``"digit"`` or ``"neutral"`` for one character."""
    category = unicodedata.bidirectional(char)
    if category in _STRONG_RTL:
        return "rtl"
    if category in _STRONG_LTR:
        return "ltr"
    if category in ("EN", "AN"):
        return "digit"
    return "neutral"


def runs(text: str) -> list[tuple[str, str]]:
    """Split into ``(direction, text)`` runs, merging neutrals into their left.

    Marks are skipped rather than classified. A run of them between two other
    runs would otherwise show up as a direction change of its own.
    """
    result: list[tuple[str, str]] = []

    for char in text:
        if char in MARKS:
            continue

        direction = direction_of(char)
        if direction == "neutral" and result:
            direction = result[-1][0]
        elif direction == "neutral":
            direction = "ltr"

        if result and result[-1][0] == direction:
            result[-1] = (direction, result[-1][1] + char)
        else:
            result.append((direction, char))

    return result


def has_mixed_direction(text: str) -> bool:
    """True when the string has both a strong RTL run and a strong LTR one."""
    directions = {direction for direction, _ in runs(text)}
    return "rtl" in directions and "ltr" in directions


def needs_isolation(text: str) -> bool:
    """True when an embedded run ends on a neutral and has no mark to hold it.

    This is the case that renders wrong: a colon, a bracket or a full stop
    sitting between an RTL context and an LTR run resolves to the paragraph
    direction and is drawn at the far end of the line, away from what it
    belongs to.
    """
    if not has_mixed_direction(text):
        return False
    if any(mark in text for mark in MARKS):
        return False

    stripped = text.rstrip()
    if stripped and direction_of(stripped[-1]) == "neutral":
        return True

    # A neutral sitting between two runs of different direction.
    previous_strong = ""
    pending_neutral = False

    for char in text:
        direction = direction_of(char)

        if direction == "neutral":
            pending_neutral = previous_strong != ""
            continue

        if direction == "digit":
            continue

        if pending_neutral and previous_strong and previous_strong != direction:
            return True

        previous_strong = direction
        pending_neutral = False

    return False
