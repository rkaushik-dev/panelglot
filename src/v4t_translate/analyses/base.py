"""What an analysis looks like.

The same shape as a rule, with one argument swapped: an analysis gets the
whole catalog and the whole translation set instead of one of each. It yields
the same Finding type, into the same report, so nothing downstream has to know
which of the two produced a line.

That last part is the point. A person reading a check does not care that a
mnemonic collision needs two messages to see and a placeholder mismatch needs
one, and making them run two commands is how findings get missed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..rules.base import RuleContext
from ..rules.result import Finding, Severity

__all__ = ["Analysis", "AnalysisContext", "finding"]

AnalysisContext = RuleContext
"""Deliberately the same context. There is nothing an analysis needs extra."""


@runtime_checkable
class Analysis(Protocol):
    """One whole-language check."""

    name: str
    """Short slug used in config, in reports and in the registry."""

    default_severity: Severity

    def run(self, catalog: Catalog, translations: TranslationSet,
            context: AnalysisContext) -> Iterable[Finding]:
        """Yield a finding for each problem. Yield nothing when it is fine."""
        ...


def finding(analysis: Analysis, context: AnalysisContext, key: str, summary: str,
            *, detail: str = "", origin: str = "", source_text: str = "",
            translated_text: str = "", severity: Severity | None = None) -> Finding:
    """Build a finding, filling in what comes from the analysis and context.

    A finding needs one key even when the problem is about several messages.
    The convention is the first one in catalog order, so the report anchors
    somewhere real and stays stable between runs.
    """
    return Finding(
        rule=analysis.name,
        severity=severity if severity is not None else analysis.default_severity,
        locale=context.tag,
        key=key,
        summary=summary,
        source_text=source_text,
        translated_text=translated_text,
        detail=detail,
        origin=origin,
    )
