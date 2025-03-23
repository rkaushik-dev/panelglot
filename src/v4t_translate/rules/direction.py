"""Right to left text that will render with its punctuation in the wrong place.

Only runs for a right to left language, and only on strings that mix
directions, which in this product is most of the interesting ones: a pen
number, a voltage, a placeholder, or the word V4T.

Two things are checked and they are not the same.

A mixed direction string with no directional mark in it will very likely draw
its trailing punctuation at the far end of the line. That is a warning, not an
error, because the bidi algorithm sometimes gets it right on its own and this
cannot tell which case it is looking at without rendering.

A directional mark in a string for a left to right language is an error. It
does nothing there, it is invisible in the sheet, and it counts against a
character budget on the Mini.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.bidi import MARKS, RLM, has_mixed_direction, needs_isolation
from ..layout.measure import drawn_text
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["DirectionRule"]


class DirectionRule:
    """Directional marks are present where they are needed and absent where not."""

    name = "direction"
    default_severity = Severity.WARNING

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        text = drawn_text(translation.text)
        marks = [mark for mark in MARKS if mark in text]

        if not context.locale.rtl:
            if marks:
                yield finding(
                    self, context, message, translation,
                    "carries a directional mark and this is not a right to left "
                    "language",
                    detail="The mark does nothing here, it is invisible in the "
                           "sheet, and on a character grid panel it spends a "
                           "column.",
                    severity=Severity.ERROR,
                )
            return

        if not has_mixed_direction(text):
            return

        if needs_isolation(text):
            yield finding(
                self, context, message, translation,
                "mixes directions with no directional mark",
                detail=f"Punctuation at the boundary will be drawn at the far end "
                       f"of the line. Put U+200F before or after the embedded run. "
                       f"The source is {message.source_text!r}.",
            )

    @staticmethod
    def suggested_mark() -> str:
        """The mark a translator into an RTL language usually wants."""
        return RLM
