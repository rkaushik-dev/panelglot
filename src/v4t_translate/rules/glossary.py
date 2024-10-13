"""Agreed terminology.

If the English says pen, the German says Stift, and it says Stift in all
forty-one places. The alternative is what we had: Stift on the offsets page,
Feder in the maintenance dialog and Patrone in the error strings, all in one
product, because four people translated four dialogs over two years.

Two things make this less strict than it sounds.

Matching in the target is a substring match, not a word match, because German
compounds. Requiring "Druckkopf" is satisfied by "Druckkopfspannung", which is
the correct translation of "printhead voltage" and would fail a word match.

Matching in the source is a word match, because "pen" has to not fire on
"open" and "spent". That asymmetry is deliberate.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.measure import drawn_text
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["GlossaryRule"]

_WORD_CACHE: dict[str, re.Pattern[str]] = {}


def _word_pattern(term: str) -> re.Pattern[str]:
    """A cached whole-word matcher for a source term.

    Terms are matched thousands of times per run against a set that changes
    once, so compiling each one repeatedly showed up in a profile.
    """
    pattern = _WORD_CACHE.get(term)
    if pattern is None:
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        _WORD_CACHE[term] = pattern
    return pattern


class GlossaryRule:
    """A source term that has an agreed translation gets that translation."""

    name = "glossary"
    default_severity = Severity.WARNING

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text or not context.glossary:
            return

        source = drawn_text(message.source_text)
        target = drawn_text(translation.text).lower()

        for term, required in sorted(context.glossary.items()):
            if not _word_pattern(term).search(source):
                continue
            if required.lower() in target:
                continue

            yield finding(
                self, context, message, translation,
                f"{term!r} should be translated as {required!r}",
                detail=f"The agreed term for {context.tag} is {required!r} and this "
                       f"translation does not contain it.",
            )
