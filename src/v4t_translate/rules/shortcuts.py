"""The shortcut hint drawn on the right of a menu item.

``MENUITEM "&New\\tCtrl+N", ID_FILE_NEW`` is one string. The tab is what makes
Windows right align the Ctrl+N part, and the Ctrl+N part is only a label. The
key that actually fires lives in the accelerator table, which is compiled once
and is the same in every language.

That split is where the damage comes from, because it makes two opposite
mistakes both look reasonable.

The first is leaving Ctrl alone. German writes Strg and French writes Ctrl, so
translating the modifier is correct and refusing to translate it produces a
menu that reads as half finished. We shipped four German builds saying Ctrl
because the developer note told the translator to keep the whole suffix.

The second is translating the key. Neu is not New, so N looks like the wrong
letter, and somebody helpfully changes it to U. The menu now advertises Strg+U
and the accelerator table still fires on N. Nothing rebuilds, nothing warns,
and the shortcut is simply dead until a customer reports it.

So this rule allows the modifiers to move and pins the key.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["ShortcutRule", "split_hint", "final_key"]

#: Modifier names in every language this project ships, lowered. A hint made
#: only of these has lost its key rather than kept it.
_MODIFIERS = frozenset(
    {
        "ctrl", "control", "strg", "ctlr", "ctl",
        "alt", "option",
        "shift", "umschalt", "maj", "shft",
        "cmd", "win",
        "控制", "上檔", "替換",
    }
)

_SEPARATORS = re.compile(r"[+\-]")


def split_hint(text: str) -> tuple[str, str | None]:
    """Split a menu caption into its label and its shortcut hint.

    The tab is the separator the resource compiler cares about. A caption
    with more than one tab keeps everything after the first, because that is
    what Windows draws.
    """
    if "\t" not in text:
        return text, None
    label, _, hint = text.partition("\t")
    return label, hint or None


def final_key(hint: str) -> str:
    """The key at the end of a shortcut hint, upper cased.

    Split on both plus and minus: Ctrl-N is written by about a third of the
    resource files here and means the same thing.
    """
    pieces = [piece.strip() for piece in _SEPARATORS.split(hint) if piece.strip()]
    return pieces[-1].upper() if pieces else ""


def _is_only_modifiers(hint: str) -> bool:
    pieces = [piece.strip().lower() for piece in _SEPARATORS.split(hint) if piece.strip()]
    return bool(pieces) and all(piece in _MODIFIERS for piece in pieces)


class ShortcutRule:
    """A menu shortcut hint keeps its key, and keeps its tab."""

    name = "shortcuts"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        _, source_hint = split_hint(message.source_text)
        _, target_hint = split_hint(translation.text)

        if source_hint is None:
            yield from self._invented(target_hint, message, translation, context)
            return

        if target_hint is None:
            yield finding(
                self, context, message, translation,
                f"the {source_hint} shortcut hint has been dropped",
                detail="The tab is what right aligns the hint. Without it the "
                       "shortcut still works and the menu stops mentioning it, "
                       "so nobody finds it.",
            )
            return

        yield from self._key_moved(source_hint, target_hint, message, translation,
                                   context)

    def _key_moved(self, source_hint: str, target_hint: str, message: Message,
                   translation: Translation, context: RuleContext) -> Iterable[Finding]:
        wanted = final_key(source_hint)
        got = final_key(target_hint)

        if wanted == got:
            return

        if _is_only_modifiers(target_hint):
            yield finding(
                self, context, message, translation,
                f"the shortcut hint {target_hint!r} has lost its key",
                detail=f"The English says {source_hint!r}. A hint made only of "
                       f"modifier names advertises nothing.",
            )
            return

        yield finding(
            self, context, message, translation,
            f"the shortcut key moved from {wanted} to {got}",
            detail=f"The modifiers can be translated. {wanted} cannot: it is "
                   f"bound in the accelerator table, which is compiled once and "
                   f"is the same in every language. {target_hint!r} advertises a "
                   f"key that does nothing.",
        )

    def _invented(self, target_hint: str | None, message: Message,
                  translation: Translation,
                  context: RuleContext) -> Iterable[Finding]:
        if target_hint is None:
            return

        yield finding(
            self, context, message, translation,
            f"a shortcut hint {target_hint!r} has been added",
            detail="The English has no tab in it, so there is no accelerator "
                   "behind this. The menu would advertise a key that is not "
                   "bound to anything.",
            severity=Severity.WARNING,
        )
