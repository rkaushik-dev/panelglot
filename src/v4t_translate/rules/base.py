"""What a rule looks like, and what it is given to work with.

A rule sees one message and one translation at a time, plus a context holding
everything that is the same for the whole run: the locale, the panel, the
font, the glossary. Keeping the per-message arguments to two is deliberate.
A rule that needs to see the whole catalog is not a rule, it is an analysis,
and those live in ops.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..glossary import Term
from ..layout.font import FontMetrics
from ..layout.panels import Panel
from ..locales import Locale
from .result import Finding, Severity

__all__ = ["RuleContext", "Rule", "finding"]


@dataclass
class RuleContext:
    """Everything a rule needs that does not change per message."""

    locale: Locale
    panel: Panel
    font: FontMetrics
    glossary: dict[str, Term] = field(default_factory=dict)
    """Lowered source term to the agreed term, for this locale only.

    This used to be a plain term to translation mapping. It carries the whole
    Term now because a decision is more than the word that won: it is also the
    words that lost, and the note saying why.
    """

    source_locale: str = "en-US"

    @property
    def tag(self) -> str:
        return self.locale.tag


@runtime_checkable
class Rule(Protocol):
    """One check."""

    name: str
    """Short slug used in config, in reports and in the registry."""

    default_severity: Severity

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        """Yield a finding for each problem. Yield nothing when it is fine."""
        ...


def finding(rule: Rule, context: RuleContext, message: Message, translation: Translation,
            summary: str, *, detail: str = "", severity: Severity | None = None) -> Finding:
    """Build a finding, filling in everything that comes from the inputs.

    Every rule would otherwise repeat the same eight assignments, and the two
    that did it slightly differently made the report inconsistent.
    """
    origin = message.primary_origin
    return Finding(
        rule=rule.name,
        severity=severity if severity is not None else rule.default_severity,
        locale=context.tag,
        key=message.key,
        summary=summary,
        source_text=message.source_text,
        translated_text=translation.text,
        detail=detail,
        origin=origin.describe() if origin else "",
    )
