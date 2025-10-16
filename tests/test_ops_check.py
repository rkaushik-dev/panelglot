import shutil

import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError
from v4t_translate.ops.check import check_project
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"
glossary = "glossary/terms.csv"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
panel = "tij-800x600"
font = "fonts/tahoma-8.fmx"

[locale."zh-TW"]
panel = "tij-800x600"
"""

GLOSSARY = """\
term,locale,translation,note
pen,de-DE,Stift,
"""


@pytest.fixture
def project(tmp_path, sample_rc_path, fixtures_dir):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "fonts").mkdir()
    shutil.copy(fixtures_dir / "fonts" / "tahoma-8.fmx", tmp_path / "fonts" / "tahoma-8.fmx")
    (tmp_path / "glossary").mkdir()
    (tmp_path / "glossary" / "terms.csv").write_text(GLOSSARY, encoding="utf-8")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")

    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def translate(config, tag, pairs, state=TranslationState.APPROVED):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for source, target in pairs.items():
        translations.set(message_key(source), Translation(text=target, state=state))
    save_translations(path, translations)


def test_check_before_extract_says_so(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError) as caught:
        check_project(config)
    assert "Run extract first" in caught.value.remedy


def test_an_untranslated_project_finds_nothing(project):
    result = check_project(project)
    assert len(result.report) == 0
    assert result.report.checked == 0


def test_every_configured_locale_is_reported(project):
    result = check_project(project)
    assert [c.tag for c in result.locales] == ["de-DE", "zh-TW"]


def test_only_the_named_locale_is_checked(project):
    result = check_project(project, locales=["de-DE"])
    assert [c.tag for c in result.locales] == ["de-DE"]


def test_a_clean_translation_finds_nothing(project):
    translate(project, "de-DE", {
        "Print started": "Druck gestartet",
        "Service restarted": "Dienst neu gestartet",
    })
    result = check_project(project, locales=["de-DE"])
    assert len(result.report) == 0
    assert result.report.checked == 2


def test_the_pen_label_really_is_too_narrow_for_german(project):
    # IDC_STATIC on the offsets page is 12 dialog units, 18 pixels, and
    # "Stift" is 27. The English fits and the German does not, which is the
    # whole reason this tool exists.
    translate(project, "de-DE", {"Pen": "Stift"})
    report = check_project(project, locales=["de-DE"]).report
    assert [f.rule for f in report.findings] == ["fitting"]
    assert "overflows its control by 9px" in report.findings[0].summary


def test_coverage_is_reported(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    check = check_project(project, locales=["de-DE"]).locales[0]
    assert check.translated == 1
    assert check.total > 30
    assert 0 < check.coverage < 1


def test_coverage_of_nothing_is_zero(project):
    assert check_project(project, locales=["de-DE"]).locales[0].coverage == 0.0


def test_describe_names_the_panel_and_font(project):
    text = check_project(project, locales=["de-DE"]).locales[0].describe()
    assert "tij-800x600" in text
    assert "Tahoma" in text


def test_a_placeholder_defect_is_found(project):
    translate(project, "de-DE", {
        "Please input from %.1fV to %.1fV.": "Bitte geben Sie einen Wert ein.",
    })
    report = check_project(project, locales=["de-DE"]).report
    assert [f.rule for f in report.findings] == ["placeholders"]


def test_a_fitting_defect_is_found(project):
    translate(project, "de-DE", {"Bar Height": "Balkenhöhe des Barcodes im Feld"})
    report = check_project(project, locales=["de-DE"]).report
    assert any(f.rule == "fitting" for f in report.findings)


def test_a_glyph_defect_is_found_for_chinese_in_a_latin_font(project):
    # zh-TW names no font, so it gets the panel default, which is the Tahoma
    # metrics sitting in fonts/. Those hold no CJK at all.
    translate(project, "zh-TW", {"Print started": "列印已開始"})
    report = check_project(project, locales=["zh-TW"]).report
    assert any(f.rule == "glyphs" for f in report.findings)


def test_a_glossary_defect_is_found(project):
    translate(project, "de-DE", {"Pen": "Feder"})
    report = check_project(project, locales=["de-DE"]).report
    assert any(f.rule == "glossary" for f in report.findings)


def test_the_glossary_only_applies_to_its_own_locale(project):
    translate(project, "zh-TW", {"Pen": "筆"})
    report = check_project(project, locales=["zh-TW"]).report
    assert not any(f.rule == "glossary" for f in report.findings)


def test_disabling_a_rule_silences_it(project):
    (project.root / "v4t-translate.toml").write_text(
        CONFIG + '\n[check]\ndisable = ["glossary"]\n', encoding="utf-8"
    )
    config = load_config(project.root / "v4t-translate.toml")
    translate(config, "de-DE", {"Pen": "Feder"})
    report = check_project(config, locales=["de-DE"]).report
    assert not any(f.rule == "glossary" for f in report.findings)


def test_a_missing_font_falls_back_and_says_so(project):
    (project.root / "fonts" / "tahoma-8.fmx").unlink()
    result = check_project(project, locales=["de-DE"])
    assert result.locales[0].font_is_fallback
    assert any("Fitting findings are approximate" in w for w in result.warnings)


def test_a_present_font_is_not_reported_as_a_fallback(project):
    result = check_project(project, locales=["de-DE"])
    assert not result.locales[0].font_is_fallback
    assert result.warnings == []


def test_should_fail_follows_the_setting(project):
    translate(project, "de-DE", {
        "Please input from %.1fV to %.1fV.": "Bitte geben Sie einen Wert ein.",
    })
    result = check_project(project, locales=["de-DE"])
    assert result.should_fail("error")
    assert not result.should_fail("never")


def test_an_unconfigured_locale_is_rejected(project):
    from v4t_translate.errors import ConfigError

    with pytest.raises(ConfigError, match="is not configured"):
        check_project(project, locales=["fr-FR"])
