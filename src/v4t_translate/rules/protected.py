"""Strings that must ship exactly as they are.

Unit symbols, date format tokens and the product names. The extractor marks
them from the project's protected patterns, and this is what enforces it
afterwards, because marking a message untranslatable does not stop anyone
typing in the cell next to it.

The failure this catches is real and it shipped. "4." went through the machine
translator and came back "4。" with an ideographic full stop, and "mm" came
back as "毫米" on a panel whose font holds neither character. Both went out.

There is one deliberate exception. A protected message may be translated when
the target uses a genuinely different symbol for the same thing, and the way
to say so is to mark the entry do-not-translate and then override it, which
is explicit and shows up in review.
"""

from __future__ import annotations

from typing import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation, TranslationState
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["ProtectedRule"]


class ProtectedRule:
    """A protected message ships its source text unchanged."""

    name = "protected"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not message.protected:
            return
        if not translation.text:
            return
        if translation.text == message.source_text:
            return

        if translation.state is TranslationState.DO_NOT_TRANSLATE:
            # Someone said so on purpose. Note it and move on.
            yield finding(
                self, context, message, translation,
                "protected string is overridden for this language",
                detail=f"{message.source_text!r} ships as {translation.text!r}. "
                       f"Marked do-not-translate, so this is deliberate.",
                severity=Severity.INFO,
            )
            return

        yield finding(
            self, context, message, translation,
            "protected string has been translated",
            detail=f"{message.source_text!r} must ship unchanged and this says "
                   f"{translation.text!r}. Mark the entry do-not-translate if the "
                   f"change is intended.",
        )
