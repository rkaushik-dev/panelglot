"""A translation that is character for character the English.

In German that is correct for OK and Barcode and wrong for everything else,
and the ratio between the two is what tells you whether a delivery was
actually done or whether somebody copied the source column across.

Protected messages are excluded, since shipping unchanged is the whole point
of them, and so is a short list of words that genuinely do not move. That list
lives with the computation in ops.analysis rather than here, because the diff
report wants the same exclusions.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..ops.analysis import identical_to_source
from ..rules.result import Finding, Severity
from .base import AnalysisContext, finding

__all__ = ["UntranslatedAnalysis"]


class UntranslatedAnalysis:
    """Translations identical to their source."""

    name = "untranslated"
    default_severity = Severity.WARNING

    def run(self, catalog: Catalog, translations: TranslationSet,
            context: AnalysisContext) -> Iterable[Finding]:
        for key in identical_to_source(catalog, translations):
            message = catalog.messages[key]
            origin = message.primary_origin

            yield finding(
                self, context, key,
                "translation is identical to the English",
                detail="Either it was skipped, or it genuinely does not change "
                       "and should be marked do-not-translate.",
                source_text=message.source_text,
                translated_text=message.source_text,
                origin=origin.describe() if origin else "",
            )
