"""Punctuation and whitespace that carries meaning.

None of this is pedantry about style. Each of these is a case where the
surrounding code or layout depends on the character.

A trailing colon means the label is followed by a control. Drop it and the
dialog reads as a sentence that stops in the middle. Add one where there was
none and a group box title acquires a colon nothing follows.

An ellipsis on a menu item or a button means the command opens another dialog
rather than doing something. It is a UI convention the whole product follows,
and dropping it changes what the button promises.

Leading and trailing spaces are load bearing surprisingly often. "Add  variable
data" in the barcode dialog has two spaces in the middle because the layout
wanted them, and several status strings are concatenated at runtime with a
trailing space doing the joining.

Full width punctuation is the CJK case. A Traditional Chinese translation that
ends in an ASCII colon looks wrong next to the rest of the panel, and one that
ends in a full width colon after an English label looks wrong the other way.
The rule only checks that the two ends agree about which kind is in use.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.measure import drawn_text
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["PunctuationRule", "WhitespaceRule", "ELLIPSES", "COLONS"]

#: Both spellings of an ellipsis. The dialog editor writes three dots, the
#: string table sometimes holds the single character.
ELLIPSES = ("...", "…")

#: ASCII colon and its full width form, which is what the Taiwan sheet uses.
COLONS = (":", "：")

_TERMINAL_MARKS = {
    "colon": COLONS,
    "ellipsis": ELLIPSES,
}


class PunctuationRule:
    """Terminal punctuation agrees between source and translation."""

    name = "punctuation"
    default_severity = Severity.WARNING

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        source = drawn_text(message.source_text).rstrip()
        target = drawn_text(translation.text).rstrip()

        for name, marks in _TERMINAL_MARKS.items():
            in_source = source.endswith(marks)
            in_target = target.endswith(marks)

            if in_source and not in_target:
                yield finding(
                    self, context, message, translation,
                    f"translation drops the trailing {name}",
                    detail=_explain(name),
                )
            elif in_target and not in_source:
                yield finding(
                    self, context, message, translation,
                    f"translation adds a trailing {name} the source does not have",
                    detail=_explain(name),
                )


class WhitespaceRule:
    """Leading and trailing whitespace matches, and runs are not introduced."""

    name = "whitespace"
    default_severity = Severity.WARNING

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        source = message.source_text
        target = translation.text

        source_lead = _leading(source)
        target_lead = _leading(target)
        if source_lead != target_lead:
            yield finding(
                self, context, message, translation,
                f"leading whitespace changed from {len(source_lead)} to {len(target_lead)}",
                detail="Several status lines are joined at runtime and the space is "
                       "what separates them.",
            )

        source_trail = _trailing(source)
        target_trail = _trailing(target)
        if source_trail != target_trail:
            yield finding(
                self, context, message, translation,
                f"trailing whitespace changed from {len(source_trail)} to "
                f"{len(target_trail)}",
                detail="Several status lines are joined at runtime and the space is "
                       "what separates them.",
            )

        if "  " in target.strip() and "  " not in source.strip():
            yield finding(
                self, context, message, translation,
                "translation has a double space the source does not",
                detail="Probably a typing artefact rather than layout.",
                severity=Severity.INFO,
            )

        if "\t" in target and "\t" not in source:
            yield finding(
                self, context, message, translation,
                "translation contains a tab and the source does not",
                detail="In a menu caption a tab starts the accelerator label, so this "
                       "will be drawn right aligned in the menu.",
                severity=Severity.ERROR,
            )


def _leading(text: str) -> str:
    return text[: len(text) - len(text.lstrip())]


def _trailing(text: str) -> str:
    return text[len(text.rstrip()):]


def _explain(name: str) -> str:
    if name == "colon":
        return "A trailing colon means a control follows the label."
    return "An ellipsis means the command opens another dialog rather than acting."
