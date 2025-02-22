"""Keyboard mnemonics.

A lone ``&`` in a caption underlines the next character and binds Alt to it.
Two of them, ``&&``, draw one ampersand and bind nothing. Translators get this
wrong in both directions and neither direction is visible in the sheet.

Dropping the marker silently removes a keyboard shortcut. On a touchscreen
that is invisible; on the TIJ8PEN configuration tool, which is used with a
keyboard on a laptop in a factory, it is a support call.

Adding one is worse. German writes "Größe & Form" and the ampersand goes into
the sheet unescaped, so the panel shows "Größe Form" with an underlined F and
a shortcut nobody asked for that collides with something else on the dialog.

Whether two controls on one dialog end up with the same mnemonic is a real
problem too, but it needs to see more than one message, so it is an analysis
in ops rather than a rule here.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.measure import drawn_text, mnemonic_of
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["MnemonicRule", "count_markers", "marker_positions"]


def marker_positions(text: str) -> list[int]:
    """Indices of the lone ampersands, with escaped pairs skipped whole.

    Stepping two characters past a ``&&`` is the whole subtlety here. Walking
    one at a time sees the second ampersand of the pair as a marker, which
    made "Größe && Form" report a mnemonic before a space.
    """
    positions: list[int] = []
    index = 0
    length = len(text)

    while index < length:
        if text[index] != "&":
            index += 1
            continue
        if index + 1 < length and text[index + 1] == "&":
            index += 2
            continue
        positions.append(index)
        index += 1

    return positions


def count_markers(text: str) -> int:
    """How many lone ampersands the string has, ignoring escaped pairs."""
    return len(marker_positions(text))


class MnemonicRule:
    """The translation keeps the source's mnemonic, and invents none."""

    name = "mnemonics"
    default_severity = Severity.WARNING

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        source_markers = count_markers(message.source_text)
        markers = marker_positions(translation.text)

        if not markers:
            if source_markers:
                yield finding(
                    self, context, message, translation,
                    "translation drops the keyboard mnemonic",
                    detail=f"source marks {mnemonic_of(message.source_text)!r}, "
                           f"translation marks nothing",
                )
            return

        misplaced = list(self._misplaced(message, translation, context, markers))
        if misplaced:
            # A marker that binds nothing is almost always an unescaped
            # ampersand, and saying so once is more use than saying it three
            # different ways.
            yield from misplaced
            return

        if len(markers) > 1:
            yield finding(
                self, context, message, translation,
                f"translation has {len(markers)} mnemonic markers, only the first binds",
                detail="Write && for a literal ampersand.",
                severity=Severity.ERROR,
            )

        if not source_markers:
            yield finding(
                self, context, message, translation,
                "translation adds a mnemonic the source does not have",
                detail="A bare & underlines the next character and binds Alt to it. "
                       "Write && if a literal ampersand was meant.",
                severity=Severity.ERROR,
            )

        yield from self._check_glyph(message, translation, context)

    def _misplaced(self, message: Message, translation: Translation,
                   context: RuleContext, markers: list[int]) -> Iterable[Finding]:
        """A marker before a space, or at the end, binds nothing."""
        text = translation.text
        for index in markers:
            following = text[index + 1] if index + 1 < len(text) else ""
            if following == "":
                yield finding(
                    self, context, message, translation,
                    "translation ends with a mnemonic marker",
                    detail="A trailing & marks nothing and is drawn as nothing.",
                    severity=Severity.ERROR,
                )
                return
            if following.isspace():
                yield finding(
                    self, context, message, translation,
                    "mnemonic marker is followed by a space",
                    detail=f"& before a space in {text!r} binds nothing. "
                           f"Write && for a literal ampersand.",
                    severity=Severity.ERROR,
                )
                return

    def _check_glyph(self, message: Message, translation: Translation,
                     context: RuleContext) -> Iterable[Finding]:
        """The underlined character has to be one the panel font can draw."""
        marker = mnemonic_of(translation.text)
        if marker is None:
            return

        drawn = drawn_text(translation.text)
        if marker.lower() not in drawn.lower():
            return

        if not context.font.covers(marker):
            yield finding(
                self, context, message, translation,
                f"mnemonic {marker!r} is not in the {context.font.name} font",
                detail="The character is drawn blank and the underline lands on nothing.",
            )
