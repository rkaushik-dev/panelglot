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
module can tell whether one is needed and whether one is present. It will also
propose where they go, which is a suggestion and not an answer: where a mark
belongs is a judgement about the sentence, and the proposal exists so a
finding can show a string that would render correctly rather than only saying
that this one will not.

There is also an approximate reordering here, and it is worth being clear
about what it is not. It is not the Unicode bidirectional algorithm. It does
enough of the algorithm to show somebody who does not read Arabic roughly what
an operator will see, which is the thing nobody can otherwise check without a
panel on the desk. Anything that has to be exact belongs in front of a native
speaker, not in front of this.
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "RLM",
    "LRM",
    "ALM",
    "MARKS",
    "MIRRORED",
    "direction_of",
    "has_mixed_direction",
    "runs",
    "needs_isolation",
    "suggest_marks",
    "visual_order",
    "unbalanced_brackets",
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

#: Brackets and quotes that swap when a run is drawn right to left. The panel
#: mirrors these itself, so a translator who typed the mirrored one by hand
#: gets it mirrored twice and it comes out backwards.
MIRRORED: dict[str, str] = {
    "(": ")", ")": "(",
    "[": "]", "]": "[",
    "{": "}", "}": "{",
    "<": ">", ">": "<",
    "«": "»", "»": "«",
}

#: Opening bracket to its close, for the balance check. Quotes are left out:
#: an apostrophe is not an unbalanced quote and saying so is noise.
_PAIRS = {"(": ")", "[": "]", "{": "}"}


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


def suggest_marks(text: str, *, mark: str = RLM) -> str:
    """``text`` with a mark put where the boundaries need one.

    A suggestion, and only that. Where a mark belongs is a judgement about the
    sentence, and this proposes the mechanical answer: after any neutral that
    sits between two runs of different direction, and at the end of a string
    that finishes on one.

    It exists so a finding can show a string that would render correctly.
    Telling somebody that their string will draw its colon at the far end of
    the line and leaving them to work out the fix is most of a report and none
    of the help.
    """
    if not text or mark in text:
        return text

    out: list[str] = []
    previous_strong = ""
    neutral_run: list[str] = []

    for char in text:
        direction = direction_of(char)

        if direction == "neutral":
            neutral_run.append(char)
            continue

        if neutral_run:
            out.extend(neutral_run)
            crossing = (
                previous_strong
                and direction in ("ltr", "rtl", "digit")
                and _crosses(previous_strong, direction)
            )
            if crossing:
                out.append(mark)
            neutral_run = []

        out.append(char)
        if direction in ("ltr", "rtl"):
            previous_strong = direction

    if neutral_run:
        # Trailing neutrals. A string ending in a colon or a full stop is the
        # single most common case, and the mark goes after them.
        out.extend(neutral_run)
        if previous_strong:
            out.append(mark)

    return "".join(out)


def _crosses(previous: str, current: str) -> bool:
    """Whether a neutral between these two directions resolves the wrong way.

    A digit never counts as a crossing. Numbers sit inside a right to left
    sentence without needing help, and marking every one of them would put a
    mark in most strings in this product and teach people to delete them.
    """
    if current == "digit":
        return False
    return previous != current


def _blocks(text: str, paragraph: str) -> list[tuple[str, str]]:
    """Direction blocks for rendering, with neutrals resolved.

    Different from :func:`runs` in two ways that only matter here. A digit
    joins the left to right side, because a number is drawn left to right
    wherever it sits. And a neutral with nothing before it takes the
    paragraph direction rather than defaulting to left to right, which is
    what makes an opening bracket mirror correctly.
    """
    blocks: list[tuple[str, str]] = []
    previous = ""

    for char in text:
        if char in MARKS:
            continue

        found = direction_of(char)
        if found == "digit":
            found = "ltr"
        elif found == "neutral":
            found = previous or paragraph
        else:
            previous = found

        if blocks and blocks[-1][0] == found:
            blocks[-1] = (found, blocks[-1][1] + char)
        else:
            blocks.append((found, char))

    return blocks


def visual_order(text: str, *, paragraph: str = "rtl") -> str:
    """Roughly what a panel would draw, left to right.

    Not the Unicode algorithm. Strong blocks are reordered and mirrored pairs
    are swapped, which is enough to show somebody who does not read Arabic
    that the colon has ended up at the wrong end. Nested embedding levels,
    shaping and combining marks are all out of scope, and a string that
    depends on any of those needs a native speaker rather than this.
    """
    if paragraph != "rtl":
        return "".join(char for char in text if char not in MARKS)

    rendered: list[str] = []
    for direction, part in _blocks(text, paragraph):
        if direction == "rtl":
            rendered.append("".join(MIRRORED.get(c, c) for c in reversed(part)))
        else:
            rendered.append(part)

    return "".join(reversed(rendered))


def unbalanced_brackets(text: str) -> list[str]:
    """Brackets that do not pair up, in the order they went wrong.

    Worth its own check for a right to left language because the panel
    mirrors brackets when it draws them. A translator who typed the mirrored
    one by hand gets it mirrored twice, and the result reads as backwards
    rather than as a missing bracket, so nobody looks for the missing bracket.
    """
    closers = {close: open_ for open_, close in _PAIRS.items()}
    stack: list[str] = []
    wrong: list[str] = []

    for char in text:
        if char in _PAIRS:
            stack.append(char)
        elif char in closers:
            if stack and stack[-1] == closers[char]:
                stack.pop()
            else:
                wrong.append(char)

    wrong.extend(reversed(stack))
    return wrong
