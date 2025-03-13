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

from ..catalog.store import Catalog, load_catalog, load_translations
from ..catalog.translations import TranslationSet
from ..config import LocaleEntry, ProjectConfig
from ..errors import CatalogError
from ..glossary import load_glossary
from ..layout.font import FontMetrics
from ..layout.panels import Panel, font_for, get_panel
from ..rules.base import RuleContext
from ..rules.registry import build_rules
from ..rules.result import Finding, Report, Severity
from .analysis import analyse

__all__ = ["CheckResult", "LocaleCheck", "check_project", "context_for_locale"]

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

    def should_fail(self, fail_on: str) -> bool:
        return self.report.should_fail(fail_on)


def check_project(config: ProjectConfig, *, locales: list[str] | None = None) -> CheckResult:
    """Check every configured language, or only the ones named."""
    catalog = _load_catalog(config)
    glossary = load_glossary(config.root / config.glossary) if config.glossary else None
    rules = build_rules(config.check)

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

        _check_locale(catalog, translations, context, rules, result.report, summary)
        _analyse_locale(catalog, translations, context, config, result.report)
        result.locales.append(summary)

    result.report.checked = sum(check.translated for check in result.locales)
    return result


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

    terms: dict[str, str] = {}
    if glossary is not None:
        terms = {key: term.translation for key, term in glossary.for_locale(entry.tag).items()}

    context = RuleContext(
        locale=entry.locale,
        panel=panel,
        font=font,
        glossary=terms,
        source_locale=config.source_locale.tag,
    )
    return context, is_fallback


def _check_locale(catalog: Catalog, translations: TranslationSet, context: RuleContext,
                  rules, report: Report, summary: LocaleCheck) -> None:
    for key in catalog.sorted_keys():
        message = catalog.messages[key]
        translation = translations.get(key)

        if translation.text:
            summary.translated += 1

        # Every rule runs, including on messages with no translation. The
        # content rules all return immediately on an empty one, and the state
        # rule needs to see them: an entry marked approved with nothing in it
        # is exactly the case that has to be caught.
        for rule in rules:
            report.extend(list(rule.check(message, translation, context)))


def _analyse_locale(catalog: Catalog, translations: TranslationSet,
                    context: RuleContext, config: ProjectConfig,
                    report: Report) -> None:
    """Add the whole-language findings to the same report as the rules.

    They are separate operations because they need different inputs, but a
    person reading the output does not care about that distinction and having
    to run two commands to see everything is how findings get missed.
    """
    if not config.check.is_enabled("collisions"):
        return

    result = analyse(catalog, translations, context.locale)

    for collision in result.collisions:
        report.add(Finding(
            rule="collisions",
            severity=Severity.ERROR,
            locale=context.tag,
            key=collision.keys[0],
            summary=f"Alt+{collision.mnemonic} is claimed by "
                    f"{len(collision.keys)} controls on {collision.container}",
            detail=collision.describe(),
            origin=collision.container,
        ))

    for merge in result.merged:
        report.add(Finding(
            rule="collisions",
            severity=Severity.WARNING,
            locale=context.tag,
            key=merge.keys[0],
            summary=f"{len(merge.sources)} different English strings share the "
                    f"translation {merge.target!r}",
            detail=merge.describe(),
        ))

    for key in result.unchanged:
        message = catalog.messages[key]
        report.add(Finding(
            rule="collisions",
            severity=Severity.WARNING,
            locale=context.tag,
            key=key,
            summary="translation is identical to the English",
            source_text=message.source_text,
            translated_text=message.source_text,
            detail="Either it was skipped, or it genuinely does not change and "
                   "should be marked do-not-translate.",
        ))


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
