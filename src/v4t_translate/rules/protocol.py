"""Characters the transport cannot carry.

The Mini panels are driven over the same framed serial link as the print data.
STX, ETX and DEL are the frame markers, so a translation containing one does
not render badly, it desynchronises the link and the panel goes blank until
somebody power cycles the printer.

Other control characters are a milder version of the same problem: they are
not drawn, they are not stripped, and they consume a byte of a string table
entry that has a hard length.

The tab is the exception. It is legal, it means something in a menu caption,
and the whitespace rule already has an opinion about it.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["ProtocolRule", "control_characters"]

#: Control characters that are legal in a caption and mean something.
_ALLOWED_CONTROLS = frozenset({"\t", "\n"})


def control_characters(text: str) -> list[str]:
    """Control characters in ``text`` that are not the allowed ones."""
    found: list[str] = []
    for char in text:
        if char in _ALLOWED_CONTROLS or char in found:
            continue
        if unicodedata.category(char) in ("Cc", "Cf", "Co", "Cs"):
            found.append(char)
    return found


class ProtocolRule:
    """The translation carries nothing the panel's transport reserves."""

    name = "protocol"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        reserved = [c for c in context.panel.forbidden if c in translation.text]
        if reserved:
            yield finding(
                self, context, message, translation,
                f"translation contains {_names(reserved)}, which {context.panel.name} "
                f"reserves",
                detail="These are the serial frame markers. A string containing one "
                       "desynchronises the link, it does not just draw wrong.",
            )

        stray = [c for c in control_characters(translation.text) if c not in reserved]
        if stray:
            yield finding(
                self, context, message, translation,
                f"translation contains {_names(stray)}",
                detail="Control characters are not drawn and are not stripped. They "
                       "spend bytes out of a string table entry that has a hard limit.",
                severity=Severity.WARNING,
            )


def _names(characters: list[str]) -> str:
    return ", ".join(f"U+{ord(c):04X}" for c in characters)
