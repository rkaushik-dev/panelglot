import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import ConfigError
from v4t_translate.ops.check import check_project
from v4t_translate.ops.doctor import run_doctor
from v4t_translate.ops.extract import extract_project
from v4t_translate.rules.result import Finding, Report, Severity
from v4t_translate.waivers import (
    EXPIRY_WARNING_DAYS,
    Waiver,
    WaiverSet,
    apply_waivers,
    load_waivers,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "waivers.example.toml"

TODAY = date(2025, 6, 1)
LATER = TODAY + timedelta(days=90)
EARLIER = TODAY - timedelta(days=1)

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def finding(rule="fitting", locale="de-DE", key="a.1", severity=Severity.ERROR):
    return Finding(rule=rule, severity=severity, locale=locale, key=key,
                   summary="overflows by 12px")


def report(*findings, checked=40):
    result = Report(checked=checked)
    for item in findings:
        result.add(item)
    return result


def waiver(**kwargs):
    defaults = {"rule": "fitting", "reason": "panel is being retired",
                "until": LATER, "owner": "ming"}
    defaults.update(kwargs)
    return Waiver(**defaults)


def write(tmp_path, body):
    path = tmp_path / "waivers.toml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)

    # A translation that overflows, so there is something real to waive.
    path = config.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(
        message_key("Bar Height"),
        Translation(text="Balkenhöhe des Barcodes im Feld ganz rechts",
                    state=TranslationState.APPROVED),
    )
    save_translations(path, translations)
    return config


# -- matching -----------------------------------------------------------


def test_a_rule_waiver_matches_every_language():
    assert waiver().matches(finding(locale="zh-TW"))


def test_a_locale_waiver_only_matches_that_language():
    scoped = waiver(locale="de-DE")
    assert scoped.matches(finding(locale="de-DE"))
    assert not scoped.matches(finding(locale="zh-TW"))


def test_a_key_waiver_only_matches_that_message():
    scoped = waiver(key="a.1")
    assert scoped.matches(finding(key="a.1"))
    assert not scoped.matches(finding(key="a.2"))


def test_a_different_rule_never_matches():
    assert not waiver().matches(finding(rule="glossary"))


def test_an_expired_waiver_stops_matching():
    waivers = WaiverSet([waiver(until=EARLIER)])
    assert waivers.matching(finding(), today=TODAY) is None


def test_a_waiver_expiring_today_still_matches():
    waivers = WaiverSet([waiver(until=TODAY)])
    assert waivers.matching(finding(), today=TODAY) is not None


def test_the_first_matching_waiver_wins():
    first = waiver(reason="first")
    waivers = WaiverSet([first, waiver(reason="second")])
    assert waivers.matching(finding(), today=TODAY) is first


# -- applying -----------------------------------------------------------


def test_a_waived_finding_leaves_the_report():
    outcome = apply_waivers(report(finding()), WaiverSet([waiver()]), today=TODAY)
    assert len(outcome.report) == 0
    assert len(outcome.waived) == 1


def test_an_unwaived_finding_stays():
    outcome = apply_waivers(report(finding(rule="glossary")),
                            WaiverSet([waiver()]), today=TODAY)
    assert len(outcome.report) == 1


def test_the_checked_count_survives():
    outcome = apply_waivers(report(finding(), checked=40), WaiverSet([waiver()]),
                            today=TODAY)
    assert outcome.report.checked == 40


def test_the_original_report_is_not_touched():
    original = report(finding())
    apply_waivers(original, WaiverSet([waiver()]), today=TODAY)
    assert len(original) == 1


def test_an_expired_waiver_is_reported():
    outcome = apply_waivers(report(finding()), WaiverSet([waiver(until=EARLIER)]),
                            today=TODAY)
    assert len(outcome.expired) == 1
    assert len(outcome.report) == 1


def test_a_waiver_that_matches_nothing_is_reported():
    outcome = apply_waivers(report(), WaiverSet([waiver()]), today=TODAY)
    assert len(outcome.unused) == 1
    assert "can go" in outcome.problems[0]


def test_a_waiver_about_to_expire_is_reported():
    soon = TODAY + timedelta(days=EXPIRY_WARNING_DAYS - 1)
    outcome = apply_waivers(report(finding()), WaiverSet([waiver(until=soon)]),
                            today=TODAY)
    assert len(outcome.expiring) == 1
    assert "expires in 6 days" in outcome.problems[0]


def test_a_waiver_with_time_left_says_nothing():
    outcome = apply_waivers(report(finding()), WaiverSet([waiver()]), today=TODAY)
    assert outcome.problems == []


def test_an_expired_waiver_is_not_also_called_unused():
    outcome = apply_waivers(report(), WaiverSet([waiver(until=EARLIER)]),
                            today=TODAY)
    assert len(outcome.expired) == 1
    assert outcome.unused == []


def test_the_summary_names_the_rules():
    outcome = apply_waivers(report(finding(), finding(rule="glossary")),
                            WaiverSet([waiver(), waiver(rule="glossary")]),
                            today=TODAY)
    assert outcome.summary() == "2 findings waived across fitting, glossary"


def test_the_summary_of_nothing():
    assert apply_waivers(report(), WaiverSet(), today=TODAY).summary() == (
        "no findings waived"
    )


def test_the_description_names_the_scope():
    described = waiver(locale="he-IL", key="a.1").describe()
    assert "fitting in he-IL on a.1" in described
    assert LATER.isoformat() in described


# -- loading ------------------------------------------------------------


def test_a_missing_file_is_an_empty_set(tmp_path):
    assert not load_waivers(tmp_path / "nothing.toml")


def test_a_full_entry_loads(tmp_path):
    path = write(tmp_path, """
[[waiver]]
rule = "fitting"
locale = "he-IL"
key = "a.1"
reason = "panel retires in March"
owner = "ming"
until = 2025-09-30
""")
    loaded = next(iter(load_waivers(path)))
    assert loaded.rule == "fitting"
    assert loaded.locale == "he-IL"
    assert loaded.key == "a.1"
    assert loaded.until == date(2025, 9, 30)


def test_the_optional_fields_default_to_everything(tmp_path):
    path = write(tmp_path, """
[[waiver]]
rule = "fitting"
reason = "r"
owner = "o"
until = 2025-09-30
""")
    loaded = next(iter(load_waivers(path)))
    assert loaded.locale is None
    assert loaded.key is None


@pytest.mark.parametrize("dropped", ["rule", "reason", "owner", "until"])
def test_every_required_field_is_required(tmp_path, dropped):
    lines = [
        '[[waiver]]',
        'rule = "fitting"',
        'reason = "r"',
        'owner = "o"',
        'until = 2025-09-30',
    ]
    kept = [line for line in lines if not line.startswith(dropped)]
    with pytest.raises(ConfigError) as caught:
        load_waivers(write(tmp_path, "\n".join(kept)))
    assert dropped in str(caught.value)


def test_a_quoted_date_is_refused(tmp_path):
    path = write(tmp_path, """
[[waiver]]
rule = "fitting"
reason = "r"
owner = "o"
until = "2025-09-30"
""")
    with pytest.raises(ConfigError, match="must be a date"):
        load_waivers(path)


def test_broken_toml_names_the_file(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_waivers(write(tmp_path, "[[waiver]\n"))


def test_the_wrong_shape_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="list of"):
        load_waivers(write(tmp_path, 'waiver = "fitting"\n'))


def test_the_error_says_which_entry(tmp_path):
    path = write(tmp_path, """
[[waiver]]
rule = "fitting"
reason = "r"
owner = "o"
until = 2025-09-30

[[waiver]]
rule = "glossary"
""")
    with pytest.raises(ConfigError, match="waiver 2"):
        load_waivers(path)


def test_the_shipped_example_loads():
    waivers = load_waivers(EXAMPLE)
    assert len(waivers) == 2
    assert all(w.reason and w.owner for w in waivers)


# -- through the project ------------------------------------------------


def test_check_waives_a_finding(project):
    before = check_project(project)
    rule = before.report.findings[0].rule
    key = before.report.findings[0].key

    (project.root / "waivers.toml").write_text(f"""
[[waiver]]
rule = "{rule}"
key = "{key}"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")

    after = check_project(project)
    assert len(after.report) < len(before.report)
    assert after.waived


def test_no_waivers_reports_everything(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")

    with_them = check_project(project)
    without = check_project(project, use_waivers=False)
    assert len(without.report) >= len(with_them.report)
    assert without.waivers is None


def test_a_project_with_no_file_has_no_outcome(project):
    assert check_project(project).waivers is None


def test_a_stale_waiver_becomes_a_warning_on_the_run(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "protocol"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")
    assert any("can go" in w for w in check_project(project).warnings)


def test_the_count_is_printed_after_the_summary(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never",
    ])
    assert "findings waived across fitting" in result.output


def test_the_flag_turns_them_off(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--no-waivers",
    ])
    assert "findings waived" not in result.output


def test_doctor_reports_an_unknown_rule(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "spelling"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")
    problems = run_doctor(project).problems
    assert any("unknown rules: spelling" in p.detail for p in problems)


def test_doctor_reports_an_expired_waiver(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2001-01-01
""", encoding="utf-8")
    assert any("expired" in p.detail for p in run_doctor(project).problems)


def test_doctor_is_happy_with_a_live_one(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")
    named = [f for f in run_doctor(project).findings if f.name == "waivers"]
    assert named and named[0].ok


def test_doctor_says_nothing_without_a_file(project):
    assert not [f for f in run_doctor(project).findings if f.name == "waivers"]


def test_the_path_can_be_moved(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(
        CONFIG.replace('name = "V4T-TIJ"',
                       'name = "V4T-TIJ"\nwaivers = "policy/accepted.toml"'),
        encoding="utf-8",
    )
    config = load_config(tmp_path / "v4t-translate.toml")
    assert config.waivers_path() == tmp_path / "policy" / "accepted.toml"
