"""Two different English strings that came back as one.

Sometimes right and often a lost distinction. Print the button and Print the
menu heading are one word in English and two in German, and collapsing them
back is a regression that reads as a translation.

A warning rather than an error, because the legitimate case is common enough
that erroring would train people to ignore it.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..ops.analysis import merged_targets
from ..rules.result import Finding, Severity
from .base import AnalysisContext, finding

__all__ = ["MergedAnalysis"]


class MergedAnalysis:
    """Distinct source strings sharing a translation."""

    name = "merged"
    default_severity = Severity.WARNING

    def run(self, catalog: Catalog, translations: TranslationSet,
            context: AnalysisContext) -> Iterable[Finding]:
        for merge in merged_targets(catalog, translations):
            yield finding(
                self, context, merge.keys[0],
                f"{len(merge.sources)} different English strings share the "
                f"translation {merge.target!r}",
                detail=merge.describe(),
                translated_text=merge.target,
            )
