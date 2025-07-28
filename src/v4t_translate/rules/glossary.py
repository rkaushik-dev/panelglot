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

Three kinds of row, three findings.

A term with an agreed translation has to have it. A term marked ``=`` is left
alone, and that one is case sensitive, because V4t is not the product name and
neither is v4T. And a term with forbidden renderings must not have any of
them, which is an error rather than a warning: a forbidden rendering is
something a person already looked at and rejected, so seeing it again means
the decision was lost rather than that a judgement call went the other way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..glossary import Term
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
        drawn = drawn_text(translation.text)
        target = drawn.lower()

        for key, term in sorted(context.glossary.items()):
            if not _word_pattern(key).search(source):
                continue

            yield from self._banned(term, target, message, translation, context)

            if term.keep_source:
                yield from self._verbatim(term, drawn, message, translation, context)
            elif term.required not in target:
                yield finding(
                    self, context, message, translation,
                    f"{term.term!r} should be translated as {term.translation!r}",
                    detail=self._explain(term, context),
                )

    def _banned(self, term: Term, target: str, message: Message,
                translation: Translation, context: RuleContext) -> Iterable[Finding]:
        """Renderings somebody already rejected, turning up again."""
        for banned in term.forbidden:
            if banned not in target:
                continue

            yield finding(
                self, context, message, translation,
                f"{banned!r} is not used for {term.term!r} in {context.tag}",
                detail=self._explain(term, context),
                severity=Severity.ERROR,
            )

    def _verbatim(self, term: Term, drawn: str, message: Message,
                  translation: Translation, context: RuleContext) -> Iterable[Finding]:
        """A do not translate term, matched with the case it was given.

        Case matters here and nowhere else in this rule. A product name that
        has been lowercased or title cased has been translated, just badly,
        and that is the failure this row exists to catch.

        Plain substring, not a word match. The word boundary that keeps "pen"
        off "open" also refuses to match V4T sitting between two Chinese
        characters, because those count as word characters too, and a rule
        that fires on every correct Chinese string is worse than no rule.
        """
        if term.term in drawn:
            return

        if term.required in drawn.lower():
            yield finding(
                self, context, message, translation,
                f"{term.term!r} has had its capitals changed",
                detail=f"{term.term!r} is a name, not a word. Copy it across "
                       f"exactly as the English has it.",
                severity=Severity.ERROR,
            )
            return

        yield finding(
            self, context, message, translation,
            f"{term.term!r} is not translated, and has gone missing",
            detail=f"{term.term!r} is marked do not translate. It should appear "
                   f"in the translation unchanged.",
        )

    @staticmethod
    def _explain(term: Term, context: RuleContext) -> str:
        lines = [f"The agreed term for {context.tag} is {term.translation!r}."]
        if term.forbidden:
            lines.append("Rejected: " + ", ".join(sorted(term.forbidden)) + ".")
        if term.note:
            lines.append(term.note)
        return " ".join(lines)
