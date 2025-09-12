import json
import shutil
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.diagnostics import (
    REDACTED,
    Diagnostics,
    path_from_environment,
    redact,
)
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.25
        return self.now


def frozen():
    return datetime(2025, 3, 4, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def lines(path):
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- redaction ----------------------------------------------------------


def test_a_token_field_is_replaced():
    assert redact({"token": "abc"})["token"] == REDACTED


def test_matching_is_on_the_name_not_the_value():
    assert redact({"endpoint": "sk-looks-like-a-key"})["endpoint"] != REDACTED


def test_a_compound_name_is_caught():
    assert redact({"auth_env": "x", "api_key": "y"}) == {
        "auth_env": REDACTED, "api_key": REDACTED
    }


def test_a_nested_field_is_caught():
    assert redact({"provider": {"password": "p"}})["provider"]["password"] == REDACTED


def test_everything_else_comes_through():
    assert redact({"messages": 44, "ok": True}) == {"messages": 44, "ok": True}


def test_the_original_is_not_changed():
    fields = {"token": "abc"}
    redact(fields)
    assert fields["token"] == "abc"


# -- recording ----------------------------------------------------------


def test_an_event_is_kept_in_memory():
    diagnostics = Diagnostics()
    diagnostics.record("extract", messages=44)
    assert [e.name for e in diagnostics.events] == ["extract"]


def test_the_fields_are_kept():
    diagnostics = Diagnostics()
    event = diagnostics.record("extract", messages=44)
    assert event.fields == {"messages": 44}


def test_an_event_serialises_as_one_json_object():
    diagnostics = Diagnostics(now=frozen)
    event = diagnostics.record("extract", 1.5, messages=44)
    payload = json.loads(event.to_json())
    assert payload["event"] == "extract"
    assert payload["ms"] == 1500
    assert payload["messages"] == 44
    assert payload["at"].startswith("2025-03-04")


def test_an_untimed_event_has_no_duration():
    payload = json.loads(Diagnostics().record("started").to_json())
    assert "ms" not in payload


def test_a_secret_never_reaches_the_json():
    payload = json.loads(Diagnostics().record("call", auth_token="abc").to_json())
    assert payload["auth_token"] == REDACTED


def test_a_step_records_a_duration():
    diagnostics = Diagnostics(clock=Clock())
    with diagnostics.step("work"):
        pass
    assert diagnostics.events[0].seconds == pytest.approx(0.25)


def test_a_step_records_what_it_was_given():
    diagnostics = Diagnostics(clock=Clock())
    with diagnostics.step("work") as fields:
        fields["messages"] = 44
    assert diagnostics.events[0].fields["messages"] == 44


def test_a_step_that_worked_says_so():
    diagnostics = Diagnostics(clock=Clock())
    with diagnostics.step("work"):
        pass
    assert diagnostics.events[0].fields["ok"] is True


def test_a_step_that_failed_is_still_recorded():
    # The slow step that raised is the one anybody wants the timing for.
    diagnostics = Diagnostics(clock=Clock())
    with pytest.raises(ValueError), diagnostics.step("work"):
        raise ValueError("no")

    event = diagnostics.events[0]
    assert event.fields["ok"] is False
    assert event.fields["error"] == "ValueError"
    assert event.seconds is not None


def test_the_failure_is_not_swallowed():
    diagnostics = Diagnostics(clock=Clock())
    with pytest.raises(ValueError), diagnostics.step("work"):
        raise ValueError("no")


def test_the_total_adds_the_timed_events_only():
    diagnostics = Diagnostics()
    diagnostics.record("a", 1.0)
    diagnostics.record("b")
    diagnostics.record("c", 0.5)
    assert diagnostics.total_seconds() == pytest.approx(1.5)


def test_the_slowest_come_first():
    diagnostics = Diagnostics()
    diagnostics.record("fast", 0.1)
    diagnostics.record("slow", 9.0)
    diagnostics.record("middling", 1.0)
    assert [e.name for e in diagnostics.slowest(2)] == ["slow", "middling"]


def test_an_empty_log_summarises_as_nothing():
    assert Diagnostics().summary() == "nothing recorded"


# -- the file -----------------------------------------------------------


def test_events_are_appended_as_json_lines(tmp_path):
    path = tmp_path / "run.jsonl"
    with Diagnostics(path) as diagnostics:
        diagnostics.record("one", messages=1)
        diagnostics.record("two", messages=2)

    assert [entry["event"] for entry in lines(path)] == ["one", "two"]


def test_a_second_run_appends(tmp_path):
    path = tmp_path / "run.jsonl"
    with Diagnostics(path) as first:
        first.record("one")
    with Diagnostics(path) as second:
        second.record("two")

    assert len(lines(path)) == 2


def test_the_directory_is_created(tmp_path):
    path = tmp_path / "logs" / "deep" / "run.jsonl"
    with Diagnostics(path) as diagnostics:
        diagnostics.record("one")
    assert path.exists()


def test_a_log_that_cannot_be_written_does_not_raise(tmp_path):
    # A diagnostics writer that takes a build down has made the problem worse
    # than the problem.
    blocked = tmp_path / "run.jsonl"
    blocked.mkdir()

    diagnostics = Diagnostics(blocked)
    diagnostics.record("one")
    assert diagnostics.events


def test_it_stops_trying_after_the_first_failure(tmp_path):
    blocked = tmp_path / "run.jsonl"
    blocked.mkdir()

    diagnostics = Diagnostics(blocked)
    for _ in range(5):
        diagnostics.record("one")
    assert len(diagnostics.events) == 5


def test_no_path_means_no_file(tmp_path):
    diagnostics = Diagnostics()
    diagnostics.record("one")
    assert list(tmp_path.iterdir()) == []


def test_the_environment_can_name_the_log(monkeypatch, tmp_path):
    monkeypatch.setenv("V4T_LOG", str(tmp_path / "x.jsonl"))
    assert path_from_environment() == tmp_path / "x.jsonl"


def test_an_unset_variable_is_none(monkeypatch):
    monkeypatch.delenv("V4T_LOG", raising=False)
    assert path_from_environment() is None


def test_an_empty_variable_is_none(monkeypatch):
    monkeypatch.setenv("V4T_LOG", "   ")
    assert path_from_environment() is None


# -- through the command line -------------------------------------------


def run(config, *args, log=None, timings=False):
    before = ["-c", str(config.root / "v4t-translate.toml")]
    if log is not None:
        before += ["--log-file", str(log)]
    if timings:
        before.append("--timings")
    return CliRunner().invoke(main, [*before, *args])


def test_a_command_writes_its_step(project, tmp_path):
    log = tmp_path / "run.jsonl"
    run(project, "extract", log=log)
    assert any(entry["event"] == "extract" for entry in lines(log))


def test_the_step_carries_the_counts(project, tmp_path):
    log = tmp_path / "run.jsonl"
    run(project, "extract", log=log)
    step = next(e for e in lines(log) if e["event"] == "extract")
    assert step["messages"] > 0
    assert "ms" in step


def test_loading_the_config_is_its_own_step(project, tmp_path):
    log = tmp_path / "run.jsonl"
    run(project, "extract", log=log)
    assert any(e["event"] == "load-config" for e in lines(log))


def test_check_is_recorded_too(project, tmp_path):
    log = tmp_path / "run.jsonl"
    run(project, "check", "--fail-on", "never", log=log)
    step = next(e for e in lines(log) if e["event"] == "check")
    assert "findings" in step


def test_a_failing_command_still_writes_its_log(project, tmp_path):
    log = tmp_path / "run.jsonl"
    result = run(project, "build", "--locale", "fr-FR", log=log)
    assert result.exit_code != 0
    assert any(entry["event"] == "load-config" for entry in lines(log))


def test_the_environment_variable_works_end_to_end(project, tmp_path, monkeypatch):
    log = tmp_path / "env.jsonl"
    monkeypatch.setenv("V4T_LOG", str(log))
    run(project, "extract")
    assert log.exists()


def test_the_flag_beats_the_environment(project, tmp_path, monkeypatch):
    monkeypatch.setenv("V4T_LOG", str(tmp_path / "env.jsonl"))
    chosen = tmp_path / "flag.jsonl"
    run(project, "extract", log=chosen)
    assert chosen.exists()
    assert not (tmp_path / "env.jsonl").exists()


def test_timings_are_printed_when_asked_for(project):
    output = run(project, "extract", timings=True).output
    assert "events," in output
    assert "ms  extract" in output


def test_timings_are_quiet_otherwise(project):
    assert "ms  extract" not in run(project, "extract").output


def test_no_log_file_leaves_nothing_behind(project, tmp_path):
    run(project, "extract")
    assert not list(tmp_path.glob("*.jsonl"))
