"""Two controls on one dialog claiming the same Alt key.

Alt+D on a dialog with two D-marked buttons presses one of them and nobody can
predict which. It is invisible until somebody drives the panel from the
keyboard, which on a production line is most of the time, and it is the single
most common thing a translation does wrong that no per-string check can see.

The English is nearly always fine, because whoever laid the dialog out was
looking at all of it. A translator sees one string at a time.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..ops.analysis import mnemonic_collisions
from ..rules.result import Finding, Severity
from .base import AnalysisContext, finding

__all__ = ["CollisionAnalysis"]


class CollisionAnalysis:
    """Mnemonic collisions within one dialog or menu."""

    name = "collisions"
    default_severity = Severity.ERROR

    def run(self, catalog: Catalog, translations: TranslationSet,
            context: AnalysisContext) -> Iterable[Finding]:
        for collision in mnemonic_collisions(catalog, translations):
            yield finding(
                self, context, collision.keys[0],
                f"Alt+{collision.mnemonic} is claimed by {len(collision.keys)} "
                f"controls on {collision.container}",
                detail=collision.describe(),
                origin=collision.container,
            )
