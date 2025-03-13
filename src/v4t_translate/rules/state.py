"""The state of a translation, as opposed to its content.

Every other rule reads the text. This one reads everything around it, and it
catches the failures that look like success.

A stale translation is the expensive one. Somebody edited the English after
the German was approved, the German is still there, the sheet still says
approved, and what ships is a confident answer to a question that changed.
Nothing else in the pipeline can see it, which is the only reason the
fingerprint exists.

An approved entry with no text is a state that should not occur and does,
usually because somebody cleared a cell and left the dropdown alone. It
reports as an error because it will ship as an empty label.

Draft and needs-review are reported at info. They are not defects, they are
work in progress, and the point of listing them is that a release build should
have none and a mid-round one will have hundreds.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation, TranslationState
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["StateRule"]


class StateRule:
    """The translation's state agrees with its content and with the English."""

    name = "state"
    default_severity = Severity.WARNING

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        yield from self._check_empty_but_approved(message, translation, context)
        yield from self._check_stale(message, translation, context)
        yield from self._check_in_progress(message, translation, context)

    def _check_empty_but_approved(self, message: Message, translation: Translation,
                                  context: RuleContext) -> Iterable[Finding]:
        if translation.text:
            return
        if translation.state is not TranslationState.APPROVED:
            return

        yield finding(
            self, context, message, translation,
            "marked approved with nothing in it",
            detail="This ships as an empty label. Somebody probably cleared the "
                   "cell and left the status dropdown alone.",
            severity=Severity.ERROR,
        )

    def _check_stale(self, message: Message, translation: Translation,
                     context: RuleContext) -> Iterable[Finding]:
        if not translation.is_stale_against(message.source_text):
            return

        yield finding(
            self, context, message, translation,
            "was translated against different English",
            detail=f"The source has been edited since this was written on "
                   f"{translation.updated or 'an unrecorded date'}. It reads as "
                   f"finished and answers a question that changed.",
            severity=(Severity.ERROR if translation.state.is_shippable
                      else Severity.WARNING),
        )

    def _check_in_progress(self, message: Message, translation: Translation,
                           context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return
        if translation.state not in (TranslationState.DRAFT,
                                     TranslationState.NEEDS_REVIEW):
            return

        origin = f" from {translation.origin}" if translation.origin else ""
        yield finding(
            self, context, message, translation,
            f"is {translation.state} and not shippable",
            detail=f"Written{origin}. A release build should have none of these.",
            severity=Severity.INFO,
        )
