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
from ..layout.bidi import (
    MARKS,
    RLM,
    has_mixed_direction,
    needs_isolation,
    suggest_marks,
    unbalanced_brackets,
    visual_order,
)
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

        yield from self._brackets(text, message, translation, context)

        if needs_isolation(text):
            yield finding(
                self, context, message, translation,
                "mixes directions with no directional mark",
                detail=self._explain(text, message.source_text),
            )

    def _brackets(self, text: str, message: Message, translation: Translation,
                  context: RuleContext) -> Iterable[Finding]:
        """Brackets that do not pair up in a language that mirrors them."""
        wrong = unbalanced_brackets(text)
        if not wrong:
            return

        yield finding(
            self, context, message, translation,
            f"has {len(wrong)} bracket that does not pair up"
            if len(wrong) == 1 else
            f"has {len(wrong)} brackets that do not pair up",
            detail="The panel mirrors brackets when it draws right to left, so "
                   "one typed the other way round comes out mirrored twice. That "
                   "reads as backwards rather than as a missing bracket, which is "
                   "why nobody goes looking for the missing bracket.",
            severity=Severity.ERROR,
        )

    @staticmethod
    def _explain(text: str, source: str) -> str:
        """The finding's second line, with a string that would work.

        Showing the fix rather than describing it. Telling somebody their
        colon will draw at the far end of the line and leaving them to work
        out where a mark goes is most of a report and none of the help.

        The suggestion is quoted with repr on purpose. A directional mark is
        invisible, and a report that prints one is a report that looks like
        it printed the same string twice.
        """
        return (
            f"Punctuation at the boundary will be drawn at the far end of the "
            f"line. On the panel this reads as {visual_order(text)!r}. Try "
            f"{suggest_marks(text)!r}, which puts U+200F at the boundary. "
            f"The source is {source!r}."
        )

    @staticmethod
    def suggested_mark() -> str:
        """The mark a translator into an RTL language usually wants."""
        return RLM
