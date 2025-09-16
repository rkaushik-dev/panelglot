"""Run every rule over every translated message.

The loop itself is dull on purpose. Everything interesting is either in a rule
or in how the context for a locale gets built, and building that context is
the part that goes wrong: the wrong font makes the fitting rule confidently
wrong rather than silent, which is the worst failure mode a checker has.

So the resolved context is reported back with the findings. A run that
measured Traditional Chinese against a fallback monospace font has to be able
to say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..analyses.registry import build_analyses
from ..catalog.store import Catalog, load_catalog, load_translations
from ..catalog.translations import TranslationSet
from ..config import LocaleEntry, ProjectConfig
from ..errors import CatalogError
from ..glossary import Term, load_glossary
from ..layout.font import FontMetrics
from ..layout.panels import Panel, font_for, get_panel
from ..rules.base import RuleContext
from ..rules.registry import build_rules
from ..rules.result import Finding, Report
from ..waivers import WaiverOutcome, apply_waivers, load_waivers

__all__ = [
    "CheckResult",
    "LocaleCheck",
    "check_project",
    "context_for_locale",
    "changed_keys",
]

#: Panel assumed when a locale entry does not name one.
DEFAULT_PANEL = "tij-800x600"


@dataclass
class LocaleCheck:
    """What was checked for one language, and with what."""

    tag: str
    panel: Panel
    font: FontMetrics
    translated: int = 0
    total: int = 0
    font_is_fallback: bool = False

    @property
    def coverage(self) -> float:
        return self.translated / self.total if self.total else 0.0

    def describe(self) -> str:
        return (
            f"{self.tag}: {self.translated}/{self.total} translated "
            f"({self.coverage:.0%}) on {self.panel.name} in {self.font.name}"
        )


@dataclass
class CheckResult:
    """A report plus the context it was produced in."""

    report: Report
    catalog: Catalog
    locales: list[LocaleCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    waivers: WaiverOutcome | None = None
    """What the waiver file did to this report, or None if there was no file.

    The report above is the one after waiving, because everything downstream
    wants the findings somebody still has to act on. The findings that were
    accepted are here, and they are still real: a report that says nothing was
    found when four things were waived is a report that lies.
    """

    def should_fail(self, fail_on: str) -> bool:
        return self.report.should_fail(fail_on)

    @property
    def waived(self) -> list[Finding]:
        return list(self.waivers.waived) if self.waivers else []


def changed_keys(config: ProjectConfig, previous: Path | str) -> set[str]:
    """Keys that are new or different since a saved copy of the catalog.

    The set a review wants. A check that reports six hundred findings on a
    branch that touched four strings blocks nothing, because nobody reads the
    six hundred to find the four, and after the second time nobody reads the
    report at all.
    """
    from .diff import diff_against

    diff = diff_against(config, previous)
    return {m.key for m in diff.added} | {c.key for c in diff.changed}


def check_project(config: ProjectConfig, *, locales: list[str] | None = None,
                  use_waivers: bool = True,
                  only_keys: set[str] | None = None) -> CheckResult:
    """Check every configured language, or only the ones named.

    ``only_keys`` restricts the per-message rules to part of the catalog. It
    does not restrict the analyses, and that asymmetry is deliberate: an
    analysis finding is about a relationship between messages, and a mnemonic
    collision between a string somebody just changed and one they did not is
    exactly the regression this mode is for. Filtering it on the key it
    happens to be anchored to would throw half of those away.
    """
    catalog = _load_catalog(config)
    glossary = load_glossary(config.root / config.glossary) if config.glossary else None
    rules = build_rules(config.check)
    analyses = build_analyses(config.check)

    wanted = _select(config, locales)
    result = CheckResult(report=Report(), catalog=catalog)

    for entry in wanted:
        translations = load_translations(config.translations_path(entry.tag))
        context, is_fallback = context_for_locale(config, entry, glossary)

        summary = LocaleCheck(
            tag=entry.tag,
            panel=context.panel,
            font=context.font,
            total=len(catalog),
            font_is_fallback=is_fallback,
        )

        if is_fallback:
            result.warnings.append(
                f"{entry.tag}: no font metrics found, measured against "
                f"{context.font.name}. Fitting findings are approximate."
            )

        _check_locale(catalog, translations, context, rules, result.report, summary,
                      only_keys=only_keys)
        _analyse_locale(catalog, translations, context, analyses, result.report)
        result.locales.append(summary)

    result.report.checked = sum(check.translated for check in result.locales)

    if use_waivers:
        _apply_project_waivers(config, result)

    return result


def _apply_project_waivers(config: ProjectConfig, result: CheckResult) -> None:
    """Filter the report through the project's waiver file, if it has one.

    Problems with the file itself come back as warnings on the result rather
    than as findings. A waiver that expired last Tuesday is not a translation
    problem, and putting it in the findings list would mean it could be waived.
    """
    waivers = load_waivers(config.waivers_path())
    if not waivers:
        return

    outcome = apply_waivers(result.report, waivers)
    result.report = outcome.report
    result.waivers = outcome
    result.warnings.extend(outcome.problems)


def context_for_locale(config: ProjectConfig, entry: LocaleEntry,
                       glossary=None) -> tuple[RuleContext, bool]:
    """Build the rule context for one language.

    Returns the context and whether the font had to be faked, because a
    fitting report measured against a stand-in font needs saying out loud.
    """
    panel = get_panel(entry.panel or DEFAULT_PANEL)

    explicit = (config.root / entry.font) if entry.font else None
    if explicit is not None and not explicit.exists():
        explicit = None

    font = font_for(panel, search=_font_search_path(config), explicit=explicit)
    is_fallback = font.name.endswith("-fallback")

    terms: dict[str, Term] = {}
    if glossary is not None:
        terms = glossary.for_locale(entry.tag)

    context = RuleContext(
        locale=entry.locale,
        panel=panel,
        font=font,
        glossary=terms,
        source_locale=config.source_locale.tag,
    )
    return context, is_fallback


def _check_locale(catalog: Catalog, translations: TranslationSet, context: RuleContext,
                  rules, report: Report, summary: LocaleCheck, *,
                  only_keys: set[str] | None = None) -> None:
    for key in catalog.sorted_keys():
        message = catalog.messages[key]
        translation = translations.get(key)

        if translation.text:
            # Counted before the filter. The coverage line says how much of
            # the language is done, and that number must not change because
            # somebody asked to see a subset of the findings.
            summary.translated += 1

        if only_keys is not None and key not in only_keys:
            continue

        # Every rule runs, including on messages with no translation. The
        # content rules all return immediately on an empty one, and the state
        # rule needs to see them: an entry marked approved with nothing in it
        # is exactly the case that has to be caught.
        for rule in rules:
            report.extend(list(rule.check(message, translation, context)))


def _analyse_locale(catalog: Catalog, translations: TranslationSet,
                    context: RuleContext, analyses, report: Report) -> None:
    """Add the whole-language findings to the same report as the rules.

    They are a separate kind of check because they need a different input, but
    a person reading the output does not care about that distinction and
    having to run two commands to see everything is how findings get missed.
    """
    for analysis in analyses:
        report.extend(list(analysis.run(catalog, translations, context)))


def _select(config: ProjectConfig, locales: list[str] | None) -> list[LocaleEntry]:
    if not locales:
        return list(config.locales)
    return [config.locale_entry(tag) for tag in locales]


def _font_search_path(config: ProjectConfig) -> list[Path]:
    return [config.root / "fonts", config.root]


def _load_catalog(config: ProjectConfig) -> Catalog:
    path = config.catalog_path()
    if not path.exists():
        raise CatalogError(
            f"{path} does not exist. Run extract before check."
        )
    return load_catalog(path)
