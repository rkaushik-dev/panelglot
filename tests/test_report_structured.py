import json
import shutil
from xml.etree import ElementTree

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.check import check_project
from v4t_translate.ops.extract import extract_project
from v4t_translate.report.structured import (
    check_to_json,
    report_to_json,
    report_to_junit,
)
from v4t_translate.rules.result import Finding, Report, Severity

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def make(rule="fitting", severity=Severity.ERROR, key="a.1", locale="de-DE",
         summary="overflows by 12px", source="Bar Height", target="Balkenhöhe",
         detail="", origin=""):
    return Finding(rule=rule, severity=severity, locale=locale, key=key,
                   summary=summary, source_text=source, translated_text=target,
                   detail=detail, origin=origin)


@pytest.fixture
def report():
    report = Report(checked=42)
    report.add(make())
    report.add(make(rule="glyphs", severity=Severity.WARNING, key="b.2",
                    detail="U+00F6", origin="V4T.rc:26"))
    return report


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def test_json_is_valid(report):
    payload = json.loads(report_to_json(report))
    assert payload["checked"] == 42
    assert payload["errors"] == 1
    assert payload["warnings"] == 1


def test_json_carries_every_field(report):
    finding = json.loads(report_to_json(report))["findings"][0]
    assert set(finding) == {
        "rule", "severity", "locale", "key", "summary", "source", "translation",
        "detail", "origin",
    }


def test_json_findings_are_sorted_like_the_console(report):
    rules = [f["rule"] for f in json.loads(report_to_json(report))["findings"]]
    assert rules == ["fitting", "glyphs"]


def test_json_counts_by_rule(report):
    assert json.loads(report_to_json(report))["by_rule"] == {"fitting": 1, "glyphs": 1}


def test_json_of_a_clean_report():
    payload = json.loads(report_to_json(Report(checked=10)))
    assert payload["findings"] == []
    assert payload["errors"] == 0


def test_json_keeps_unicode_readable(report):
    assert "Balkenhöhe" in report_to_json(report)


def test_junit_is_valid_xml(report):
    root = ElementTree.fromstring(report_to_junit(report))
    assert root.tag == "testsuite"


def test_junit_counts(report):
    root = ElementTree.fromstring(report_to_junit(report))
    assert root.get("tests") == "2"
    assert root.get("failures") == "1"
    assert root.get("skipped") == "1"
    assert root.get("errors") == "0"


def test_junit_makes_errors_failures_and_warnings_skips(report):
    root = ElementTree.fromstring(report_to_junit(report))
    cases = root.findall("testcase")
    assert cases[0].find("failure") is not None
    assert cases[1].find("skipped") is not None


def test_junit_classname_is_the_rule(report):
    root = ElementTree.fromstring(report_to_junit(report))
    assert root.findall("testcase")[0].get("classname") == "fitting"


def test_junit_name_carries_locale_and_key(report):
    root = ElementTree.fromstring(report_to_junit(report))
    assert root.findall("testcase")[0].get("name") == "de-DE a.1"


def test_junit_failure_body_has_both_texts(report):
    root = ElementTree.fromstring(report_to_junit(report))
    body = root.findall("testcase")[0].find("failure").text
    assert "Bar Height" in body
    assert "Balkenhöhe" in body


def test_junit_of_a_clean_report_still_has_a_case():
    root = ElementTree.fromstring(report_to_junit(Report(checked=10)))
    assert root.get("tests") == "1"
    assert root.get("failures") == "0"
    assert "10 messages checked" in root.findall("testcase")[0].get("name")


def test_junit_escapes_markup_in_a_translation():
    report = Report(checked=1)
    report.add(make(target="Tap <b>Purge</b> & wait"))
    root = ElementTree.fromstring(report_to_junit(report))
    assert "<b>Purge</b>" in root.findall("testcase")[0].find("failure").text


def test_junit_escapes_quotes_in_a_summary():
    report = Report(checked=1)
    report.add(make(summary='the "Pen" label overflows'))
    root = ElementTree.fromstring(report_to_junit(report))
    assert root.findall("testcase")[0].find("failure").get("message") == (
        'the "Pen" label overflows'
    )


def test_check_json_reports_the_context(project):
    result = check_project(project)
    payload = json.loads(check_to_json(result))
    assert payload["project"] == "V4T-TIJ"
    assert payload["locales"][0]["locale"] == "de-DE"
    assert payload["locales"][0]["panel"] == "tij-800x600"
    assert "font_is_fallback" in payload["locales"][0]


def test_the_command_line_json(project):
    # Warnings go to stderr precisely so that stdout stays parseable, and the
    # test has to keep the two apart or it cannot prove that.
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "check", "--format", "json",
    ])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["project"] == "V4T-TIJ"


def test_the_command_line_junit(project):
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "check", "--format", "junit",
    ])
    assert ElementTree.fromstring(result.stdout).tag == "testsuite"


def test_warnings_never_reach_stdout(project):
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "check", "--format", "json",
    ])
    assert "warning:" in result.stderr
    assert "warning:" not in result.stdout


def test_the_command_line_writes_to_a_file(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Please input from %.1fV to %.1fV."),
                     Translation(text="Bitte einen Wert eingeben.",
                                 state=TranslationState.APPROVED))
    save_translations(path, translations)

    out = project.root / "reports" / "check.xml"
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--format", "junit", "-o", str(out),
    ])
    assert result.exit_code != 0
    assert out.exists()
    root = ElementTree.fromstring(out.read_text(encoding="utf-8"))
    assert root.get("failures") == "1"


def test_writing_to_a_file_keeps_the_terminal_quiet(project):
    out = project.root / "check.json"
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--format", "json", "-o", str(out),
    ])
    assert result.stdout.strip() == ""
    assert out.exists()
