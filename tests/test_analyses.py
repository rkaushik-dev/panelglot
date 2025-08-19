import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.analyses.base import Analysis
from v4t_translate.analyses.registry import (
    ALL_ANALYSES,
    analysis_names,
    build_analyses,
)
from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog, load_translations, save_translations
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.cli import main
from v4t_translate.config import CheckSettings, load_config
from v4t_translate.errors import ConfigError
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.ops.check import check_project
from v4t_translate.ops.extract import extract_project
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.registry import build_rules, known_rule_names, rule_names
from v4t_translate.rules.result import Severity

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def context(tag="de-DE"):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0x9FFF)]),
    )


def catalog_of(*pairs, container="IDD_MAIN"):
    """Build a catalog from (key, english) pairs, all on one dialog."""
    catalog = Catalog(project="V4T-TIJ")
    for key, text in pairs:
        catalog.add(Message(
            key=key,
            source_text=text,
            origins=[Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                            container=container, symbol=key, line=10)],
        ))
    return catalog


def translated(*pairs):
    result = TranslationSet(locale="de-DE")
    for key, text in pairs:
        result.set(key, Translation(text=text, state=TranslationState.APPROVED))
    return result


def run(analysis, catalog, translations):
    return list(analysis.run(catalog, translations, context()))


def named(name):
    return next(cls() for cls in ALL_ANALYSES if cls.name == name)


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


# -- the registry -------------------------------------------------------


def test_the_three_analyses_are_named():
    assert analysis_names() == ["collisions", "untranslated", "merged"]


def test_each_one_satisfies_the_protocol():
    for cls in ALL_ANALYSES:
        assert isinstance(cls(), Analysis)


def test_they_share_the_config_namespace_with_rules():
    known = known_rule_names()
    assert set(rule_names()) < set(known)
    for name in analysis_names():
        assert name in known


def test_no_name_is_used_twice():
    assert len(known_rule_names()) == len(set(known_rule_names()))


def test_all_three_are_built_by_default():
    assert len(build_analyses()) == 3


def test_one_can_be_disabled_on_its_own():
    built = build_analyses(CheckSettings(disabled_rules=("merged",)))
    assert [a.name for a in built] == ["collisions", "untranslated"]


def test_disabling_one_no_longer_disables_the_others():
    # They used to be one name. Turning off collisions turned off the
    # untranslated report as well, silently.
    built = build_analyses(CheckSettings(disabled_rules=("collisions",)))
    assert "untranslated" in [a.name for a in built]


def test_one_can_be_promoted():
    built = build_analyses(CheckSettings(promoted_rules=("merged",)))
    promoted = next(a for a in built if a.name == "merged")
    assert promoted.default_severity is Severity.ERROR


def test_one_can_be_demoted():
    built = build_analyses(CheckSettings(demoted_rules=("collisions",)))
    demoted = next(a for a in built if a.name == "collisions")
    assert demoted.default_severity is Severity.WARNING


def test_a_promoted_analysis_reports_at_the_new_level():
    catalog = catalog_of(("a.1", "&Delete"), ("a.2", "&Discard"))
    translations = translated(("a.1", "&Löschen"), ("a.2", "&Ledigen"))

    built = build_analyses(CheckSettings(promoted_rules=("merged",)))
    demoted = build_analyses(CheckSettings(demoted_rules=("collisions",)))

    found = run(next(a for a in demoted if a.name == "collisions"), catalog,
                translations)
    assert found and found[0].severity is Severity.WARNING
    assert built  # the promoted set builds without touching the other two


def test_an_unknown_name_is_still_rejected_once():
    with pytest.raises(ConfigError, match="unknown rule"):
        build_rules(CheckSettings(disabled_rules=("spelling",)))


def test_a_real_analysis_name_is_accepted_by_the_rule_builder():
    build_rules(CheckSettings(disabled_rules=("merged",)))


# -- collisions ---------------------------------------------------------


def test_two_controls_claiming_one_key():
    catalog = catalog_of(("a.1", "&Delete"), ("a.2", "&Discard"))
    translations = translated(("a.1", "&Löschen"), ("a.2", "&Ledigen"))
    found = run(named("collisions"), catalog, translations)
    assert len(found) == 1
    assert "Alt+L" in found[0].summary


def test_a_collision_is_an_error():
    catalog = catalog_of(("a.1", "&Delete"), ("a.2", "&Discard"))
    translations = translated(("a.1", "&Löschen"), ("a.2", "&Ledigen"))
    assert run(named("collisions"), catalog, translations)[0].severity is (
        Severity.ERROR
    )


def test_a_collision_names_the_dialog_as_its_origin():
    catalog = catalog_of(("a.1", "&Delete"), ("a.2", "&Discard"))
    translations = translated(("a.1", "&Löschen"), ("a.2", "&Ledigen"))
    assert run(named("collisions"), catalog, translations)[0].origin == "IDD_MAIN"


def test_distinct_keys_collide_with_nothing():
    catalog = catalog_of(("a.1", "&Delete"), ("a.2", "&Discard"))
    translations = translated(("a.1", "&Löschen"), ("a.2", "&Verwerfen"))
    assert run(named("collisions"), catalog, translations) == []


def test_the_finding_anchors_on_the_first_key():
    catalog = catalog_of(("a.1", "&Delete"), ("a.2", "&Discard"))
    translations = translated(("a.1", "&Löschen"), ("a.2", "&Ledigen"))
    assert run(named("collisions"), catalog, translations)[0].key in {"a.1", "a.2"}


# -- untranslated -------------------------------------------------------


def test_a_copied_source_is_reported():
    catalog = catalog_of(("a.1", "Bar Height"))
    found = run(named("untranslated"), catalog, translated(("a.1", "Bar Height")))
    assert len(found) == 1
    assert "identical to the English" in found[0].summary


def test_it_is_a_warning_not_an_error():
    catalog = catalog_of(("a.1", "Bar Height"))
    found = run(named("untranslated"), catalog, translated(("a.1", "Bar Height")))
    assert found[0].severity is Severity.WARNING


def test_a_word_that_does_not_change_is_left_alone():
    catalog = catalog_of(("a.1", "Barcode"))
    assert run(named("untranslated"), catalog, translated(("a.1", "Barcode"))) == []


def test_the_finding_carries_both_sides():
    catalog = catalog_of(("a.1", "Bar Height"))
    found = run(named("untranslated"), catalog, translated(("a.1", "Bar Height")))
    assert found[0].source_text == "Bar Height"
    assert found[0].translated_text == "Bar Height"


def test_the_finding_names_where_it_came_from():
    catalog = catalog_of(("a.1", "Bar Height"))
    found = run(named("untranslated"), catalog, translated(("a.1", "Bar Height")))
    assert "V4T.rc" in found[0].origin


def test_a_real_translation_is_quiet():
    catalog = catalog_of(("a.1", "Bar Height"))
    assert run(named("untranslated"), catalog, translated(("a.1", "Höhe"))) == []


# -- merged -------------------------------------------------------------


def test_two_english_strings_one_translation():
    catalog = catalog_of(("a.1", "Print"), ("a.2", "Printing"))
    found = run(named("merged"), catalog, translated(("a.1", "Drucken"),
                                                     ("a.2", "Drucken")))
    assert len(found) == 1
    assert "share the translation" in found[0].summary


def test_it_is_a_warning():
    catalog = catalog_of(("a.1", "Print"), ("a.2", "Printing"))
    found = run(named("merged"), catalog, translated(("a.1", "Drucken"),
                                                     ("a.2", "Drucken")))
    assert found[0].severity is Severity.WARNING


def test_the_shared_translation_is_on_the_finding():
    catalog = catalog_of(("a.1", "Print"), ("a.2", "Printing"))
    found = run(named("merged"), catalog, translated(("a.1", "Drucken"),
                                                     ("a.2", "Drucken")))
    assert found[0].translated_text == "Drucken"


def test_the_same_english_twice_is_not_a_merge():
    catalog = catalog_of(("a.1", "Print"), ("a.2", "Print"))
    assert run(named("merged"), catalog, translated(("a.1", "Drucken"),
                                                    ("a.2", "Drucken"))) == []


# -- through the check --------------------------------------------------


def test_the_rule_name_on_a_finding_is_the_analysis_name(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"), Translation(
        text="Bar Height", state=TranslationState.APPROVED))
    save_translations(path, translations)

    rules = {f.rule for f in check_project(project).report.findings}
    assert "untranslated" in rules
    assert "collisions" not in rules


def test_the_report_groups_them_separately(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"), Translation(
        text="Bar Height", state=TranslationState.APPROVED))
    save_translations(path, translations)

    grouped = check_project(project).report.by_rule()
    assert "untranslated" in grouped


def test_a_project_can_disable_one_of_them(project):
    (project.root / "v4t-translate.toml").write_text(
        CONFIG + '\n[check]\ndisable = ["untranslated"]\n', encoding="utf-8")
    config = load_config(project.root / "v4t-translate.toml")

    path = config.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"), Translation(
        text="Bar Height", state=TranslationState.APPROVED))
    save_translations(path, translations)

    rules = {f.rule for f in check_project(config).report.findings}
    assert "untranslated" not in rules


def test_the_help_for_disabling_lists_them(project):
    result = CliRunner().invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "doctor", "--all",
    ])
    assert result.exit_code in (0, 1)
