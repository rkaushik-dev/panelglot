import json
import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import ConfigError
from v4t_translate.ops.check import check_project
from v4t_translate.ops.extract import extract_project
from v4t_translate.report.registry import (
    FORMATS,
    format_names,
    get_format,
    render_check,
)
from v4t_translate.report.sarif import SARIF_VERSION, check_to_sarif, report_to_sarif
from v4t_translate.rules.registry import rule_names
from v4t_translate.rules.result import Finding, Report, Severity

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def finding(severity=Severity.ERROR, origin="src/V4T.rc:41 IDD_BARCODE_PROPS"):
    return Finding(rule="fitting", severity=severity, locale="de-DE", key="bar.9a2f",
                   summary="overflows by 12px", source_text="Bar Height",
                   translated_text="Balkenhöhe", detail="54px available",
                   origin=origin)


def report(*findings, checked=40):
    result = Report(checked=checked)
    for item in findings:
        result.add(item)
    return result


def sarif(*findings):
    return json.loads(report_to_sarif(report(*findings)))


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)

    path = config.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Balkenhöhe des Barcodes ganz rechts",
                                 state=TranslationState.APPROVED))
    save_translations(path, translations)
    return config


# -- the document -------------------------------------------------------


def test_it_is_valid_json():
    assert sarif(finding())["version"] == SARIF_VERSION


def test_the_schema_is_named():
    assert sarif()["$schema"].endswith("sarif-2.1.0.json")


def test_there_is_exactly_one_run():
    assert len(sarif(finding())["runs"]) == 1


def test_the_tool_names_itself_and_its_version():
    from v4t_translate import __version__

    driver = sarif()["runs"][0]["tool"]["driver"]
    assert driver["name"] == "v4t-translate"
    assert driver["version"] == __version__


def test_every_rule_is_declared_even_when_nothing_fired():
    declared = [rule["id"] for rule in sarif()["runs"][0]["tool"]["driver"]["rules"]]
    assert declared == rule_names()


def test_a_declared_rule_carries_a_description_and_a_help_link():
    rule = sarif()["runs"][0]["tool"]["driver"]["rules"][0]
    assert rule["shortDescription"]["text"]
    assert rule["helpUri"].endswith(f"docs/rules.md#{rule['id']}")


def test_a_declared_rule_carries_its_default_level():
    rules = {r["id"]: r for r in sarif()["runs"][0]["tool"]["driver"]["rules"]}
    assert rules["placeholders"]["defaultConfiguration"]["level"] == "error"


# -- results ------------------------------------------------------------


def test_a_finding_becomes_a_result():
    results = sarif(finding())["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "fitting"


@pytest.mark.parametrize(
    ("severity", "level"),
    [(Severity.ERROR, "error"), (Severity.WARNING, "warning"),
     (Severity.INFO, "note")],
)
def test_severity_maps_across(severity, level):
    assert sarif(finding(severity))["runs"][0]["results"][0]["level"] == level


def test_the_message_names_the_language():
    text = sarif(finding())["runs"][0]["results"][0]["message"]["text"]
    assert text.startswith("de-DE: overflows by 12px")


def test_the_message_carries_the_translation_and_the_detail():
    text = sarif(finding())["runs"][0]["results"][0]["message"]["text"]
    assert "Balkenhöhe" in text
    assert "54px available" in text


def test_the_location_points_at_the_resource_script():
    location = sarif(finding())["runs"][0]["results"][0]["locations"][0]
    physical = location["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == "src/V4T.rc"
    assert physical["region"]["startLine"] == 41


def test_a_windows_path_is_written_with_forward_slashes():
    found = finding(origin="src\\ui\\V4T.rc:41")
    uri = sarif(found)["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "src/ui/V4T.rc"


def test_an_origin_with_no_line_still_names_the_file():
    physical = sarif(finding(origin="src/V4T.rc"))["runs"][0]["results"][0][
        "locations"][0]["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == "src/V4T.rc"
    assert "region" not in physical


def test_a_finding_with_no_origin_gets_no_location():
    assert "locations" not in sarif(finding(origin=""))["runs"][0]["results"][0]


def test_the_fingerprint_is_the_message_and_the_language():
    result = sarif(finding())["runs"][0]["results"][0]
    assert result["partialFingerprints"]["v4tMessageKey"] == "de-DE/bar.9a2f"


def test_the_fingerprint_survives_a_reworded_translation():
    first = sarif(finding())["runs"][0]["results"][0]["partialFingerprints"]
    reworded = Finding(rule="fitting", severity=Severity.ERROR, locale="de-DE",
                       key="bar.9a2f", summary="overflows by 4px",
                       translated_text="Balkenhoehe", origin="src/V4T.rc:41")
    second = sarif(reworded)["runs"][0]["results"][0]["partialFingerprints"]
    assert first == second


def test_an_empty_report_has_no_results():
    assert sarif()["runs"][0]["results"] == []


# -- the whole check ----------------------------------------------------


def test_the_check_document_carries_the_context(project):
    payload = json.loads(check_to_sarif(check_project(project)))
    properties = payload["runs"][0]["properties"]
    assert properties["project"] == "V4T-TIJ"
    assert properties["locales"][0]["locale"] == "de-DE"
    assert "panel" in properties["locales"][0]


def test_the_check_document_says_when_a_font_was_faked(project):
    properties = json.loads(check_to_sarif(check_project(project)))[
        "runs"][0]["properties"]
    assert properties["locales"][0]["fontIsFallback"] in (True, False)


def test_the_waived_count_appears_only_when_there_are_waivers(project):
    payload = json.loads(check_to_sarif(check_project(project)))
    assert "waived" not in payload["runs"][0]["properties"]

    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")

    payload = json.loads(check_to_sarif(check_project(project)))
    assert payload["runs"][0]["properties"]["waived"] >= 0


# -- the registry -------------------------------------------------------


def test_every_format_is_named_once():
    assert len(format_names()) == len(set(format_names()))


def test_the_known_formats():
    assert format_names() == ["text", "json", "junit", "sarif", "html"]


def test_only_text_is_colourable():
    colourable = [entry.name for entry in FORMATS if entry.colourable]
    assert colourable == ["text"]


def test_every_format_declares_an_extension_and_a_description():
    for entry in FORMATS:
        assert entry.extension.startswith(".")
        assert entry.description.endswith(".")


def test_an_unknown_format_is_refused():
    with pytest.raises(ConfigError, match="unknown report format"):
        get_format("yaml")


def test_the_refusal_lists_what_is_known():
    with pytest.raises(ConfigError, match="sarif"):
        get_format("yaml")


@pytest.mark.parametrize("name", ["text", "json", "junit", "sarif", "html"])
def test_every_format_renders(project, name):
    assert render_check(check_project(project), name, config=project).strip()


def test_a_non_text_format_is_never_coloured(project):
    text = render_check(check_project(project), "json", config=project, colour=True)
    assert "\033[" not in text


# -- through the command line -------------------------------------------


def test_the_command_writes_sarif(project, tmp_path):
    out = tmp_path / "check.sarif"
    runner = CliRunner()
    runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--format", "sarif", "-o", str(out),
    ])
    assert json.loads(out.read_text(encoding="utf-8"))["version"] == SARIF_VERSION


def test_a_mismatched_extension_is_warned_about(project, tmp_path):
    out = tmp_path / "check.json"
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--format", "sarif", "-o", str(out),
    ])
    assert "does not end in .sarif" in result.output


def test_a_matching_extension_is_quiet(project, tmp_path):
    out = tmp_path / "check.sarif"
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--format", "sarif", "-o", str(out),
    ])
    assert "does not end in" not in result.output


def test_sarif_is_offered_in_the_help(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "check", "--help",
    ])
    assert "sarif" in result.output
