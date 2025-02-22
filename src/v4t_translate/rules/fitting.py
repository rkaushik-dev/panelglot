"""Does the translation fit the control it will be drawn in.

The most common defect there is, and the one the sheet cannot show. German is
routinely a third longer than English and the dialogs were laid out against
English, so a translation can be perfect and still leave half a word behind
the edge of a group box.

Three budgets, and a message may carry any combination of them.

A pixel budget, from the control's width in dialog units converted through
the dialog font. This is the one that matters on the Windows panels.

A character budget, from a fixed grid panel. The Mini's LCD is twenty columns
and the twenty-first character does not exist.

A line budget. A control that cannot wrap has one line whatever its height,
and text that needs two is clipped rather than wrapped.

Near misses get a warning rather than an error. Base units are measured, the
font metrics are a subset export, and the themed control padding moves between
Windows versions, so a string that fills its control to the last three pixels
is a thing to look at rather than a thing to fail the build on.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.measure import drawn_text, line_count, overflow_px, visible_length
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["FittingRule", "NEAR_MISS_FRACTION"]

#: A translation using at least this much of its budget is reported as a
#: near miss even when it technically fits.
NEAR_MISS_FRACTION = 0.97


class FittingRule:
    """The translation fits its control, in pixels, characters and lines."""

    name = "fitting"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        yield from self._check_pixels(message, translation, context)
        yield from self._check_characters(message, translation, context)
        yield from self._check_lines(message, translation, context)

    def _check_pixels(self, message: Message, translation: Translation,
                      context: RuleContext) -> Iterable[Finding]:
        budget = message.max_width_px
        if budget is None:
            return

        if budget <= 0:
            yield finding(
                self, context, message, translation,
                "the control has no room for any text at all",
                detail="Width in the resource is smaller than the control's own chrome.",
            )
            return

        over = overflow_px(translation.text, context.font, budget,
                           max_lines=message.max_lines)
        if over > 0:
            yield finding(
                self, context, message, translation,
                f"overflows its control by {over}px",
                detail=self._measurement(message, translation, context, budget),
            )
            return

        used = context.font.measure(drawn_text(translation.text))
        if message.max_lines <= 1 and used >= budget * NEAR_MISS_FRACTION:
            yield finding(
                self, context, message, translation,
                f"fills {used} of {budget}px, with nothing to spare",
                detail=self._measurement(message, translation, context, budget),
                severity=Severity.WARNING,
            )

    def _check_characters(self, message: Message, translation: Translation,
                          context: RuleContext) -> Iterable[Finding]:
        budget = message.max_chars or context.panel.char_budget()
        if budget is None:
            return

        used = visible_length(translation.text)
        if used > budget:
            yield finding(
                self, context, message, translation,
                f"is {used} characters and the panel shows {budget}",
                detail=f"{context.panel.describe()}. "
                       f"Everything past character {budget} is not drawn.",
            )

    def _check_lines(self, message: Message, translation: Translation,
                     context: RuleContext) -> Iterable[Finding]:
        budget = message.max_lines
        if budget <= 0 or message.max_width_px is None:
            return

        needed = line_count(translation.text, context.font, message.max_width_px)
        if needed > budget:
            yield finding(
                self, context, message, translation,
                f"needs {needed} lines and the control shows {budget}",
                detail="Widen the control, or shorten the translation.",
            )

    @staticmethod
    def _measurement(message: Message, translation: Translation,
                     context: RuleContext, budget: int) -> str:
        source_width = context.font.measure(drawn_text(message.source_text))
        target_width = context.font.measure(drawn_text(translation.text))
        return (
            f"{budget}px available, {target_width}px needed "
            f"(the English is {source_width}px) in {context.font.name}."
        )
