"""Which analyses exist, and which of them a project runs.

Mirrors the rule registry, including the promote and demote handling, because
a project that can raise ``merged`` to an error should not have to learn that
it is a different kind of thing to ``fitting``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..config import CheckSettings
from ..rules.result import Finding, Severity
from .base import Analysis, AnalysisContext
from .collisions import CollisionAnalysis
from .merged import MergedAnalysis
from .untranslated import UntranslatedAnalysis

__all__ = ["ALL_ANALYSES", "analysis_names", "build_analyses"]


class AnalysisType(Protocol):
    """The class object of an analysis, read before anything is built."""

    name: str
    default_severity: Severity

    def __call__(self) -> Analysis:
        ...


#: Worst consequence first, same as the rules.
ALL_ANALYSES: tuple[AnalysisType, ...] = (
    CollisionAnalysis,     # two controls answer one key
    UntranslatedAnalysis,  # a delivery that was not done
    MergedAnalysis,        # a distinction that was lost
)


class _Overridden:
    """An analysis whose findings come out at a different level."""

    def __init__(self, analysis: Analysis, severity: Severity) -> None:
        self._analysis = analysis
        self._severity = severity
        self.name = analysis.name
        self.default_severity = severity

    def run(self, catalog: Catalog, translations: TranslationSet,
            context: AnalysisContext) -> Iterable[Finding]:
        for found in self._analysis.run(catalog, translations, context):
            yield Finding(
                rule=found.rule,
                severity=self._severity,
                locale=found.locale,
                key=found.key,
                summary=found.summary,
                source_text=found.source_text,
                translated_text=found.translated_text,
                detail=found.detail,
                origin=found.origin,
            )


def analysis_names() -> list[str]:
    """Every analysis name, in report order."""
    return [cls.name for cls in ALL_ANALYSES]


def build_analyses(settings: CheckSettings | None = None) -> list[Analysis]:
    """Instantiate the analyses a project should run, in report order.

    Unknown names are not rejected here. The rule registry validates the whole
    set of names in one place, because a name is either known to one of the
    two registries or it is a typo, and finding that out twice would mean
    reporting it twice.
    """
    settings = settings or CheckSettings()
    built: list[Analysis] = []

    for cls in ALL_ANALYSES:
        if cls.name in settings.disabled_rules:
            continue
        analysis: Analysis = cls()
        if cls.name in settings.promoted_rules:
            analysis = _Overridden(analysis, Severity.ERROR)
        elif cls.name in settings.demoted_rules:
            analysis = _Overridden(analysis, Severity.WARNING)
        built.append(analysis)

    return built
