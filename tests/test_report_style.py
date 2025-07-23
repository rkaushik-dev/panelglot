import io
import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.extract import extract_project
from v4t_translate.report.console import format_finding, format_report
from v4t_translate.report.style import (
    MAX_WIDTH,
    MIN_WIDTH,
    Palette,
    palette_for,
    terminal_width,
    wants_colour,
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


class FakeStream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def finding(severity=Severity.ERROR):
    return Finding(rule="fitting", severity=severity, locale="de-DE", key="a.1",
                   summary="overflows by 12px", source_text="Bar Height",
                   translated_text="Balkenhöhe", detail="54px available",
                   origin="V4T.rc:41")


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
                     Translation(text="Balkenhöhe des Barcodes im Feld",
                                 state=TranslationState.APPROVED))
    save_translations(path, translations)
    return config


def test_a_disabled_palette_changes_nothing():
    palette = Palette(enabled=False)
    assert palette.paint("text", "error") == "text"
    assert palette.dim("text") == "text"


def test_an_enabled_palette_wraps_in_escapes():
    painted = Palette(enabled=True).paint("text", "error")
    assert painted.startswith("\033[")
    assert painted.endswith("\033[0m")
    assert "text" in painted


def test_an_unknown_style_is_left_alone():
    assert Palette(enabled=True).paint("text", "chartreuse") == "text"


def test_empty_text_is_never_painted():
    assert Palette(enabled=True).paint("", "error") == ""


def test_each_severity_gets_its_own_colour():
    palette = Palette(enabled=True)
    painted = {
        palette.severity("x", severity) for severity in Severity
    }
    assert len(painted) == len(Severity)


def test_no_color_wins(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert not wants_colour(FakeStream(tty=True))


def test_force_color_turns_it_on_for_a_pipe(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert wants_colour(FakeStream(tty=False))


def test_a_dumb_terminal_gets_none(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert not wants_colour(FakeStream(tty=True))


def test_a_tty_gets_colour(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert wants_colour(FakeStream(tty=True))


def test_a_pipe_does_not(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert not wants_colour(FakeStream(tty=False))


def test_something_that_is_not_a_stream_at_all(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert not wants_colour(object())


def test_force_overrides_the_environment(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")
    assert palette_for(force=True).enabled
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert not palette_for(force=False).enabled


def test_the_width_is_capped(monkeypatch):
    monkeypatch.setattr(
        "shutil.get_terminal_size", lambda _=None: type("S", (), {"columns": 400})()
    )
    assert terminal_width() == MAX_WIDTH


def test_the_width_has_a_floor(monkeypatch):
    monkeypatch.setattr(
        "shutil.get_terminal_size", lambda _=None: type("S", (), {"columns": 10})()
    )
    assert terminal_width() == MIN_WIDTH


def test_a_width_in_between_is_used(monkeypatch):
    monkeypatch.setattr(
        "shutil.get_terminal_size", lambda _=None: type("S", (), {"columns": 72})()
    )
    assert terminal_width() == 72


def test_a_finding_without_a_palette_is_plain():
    assert all("\033" not in line for line in format_finding(finding()))


def test_a_finding_with_a_palette_is_not():
    lines = format_finding(finding(), palette=Palette(enabled=True))
    assert any("\033" in line for line in lines)


def test_the_plain_and_coloured_text_say_the_same_thing():
    plain = "\n".join(format_finding(finding()))
    coloured = "\n".join(format_finding(finding(), palette=Palette(enabled=True)))
    stripped = coloured.replace("\033[0m", "")
    for code in ("\033[31m", "\033[2m", "\033[36m", "\033[32m"):
        stripped = stripped.replace(code, "")
    assert stripped == plain


def test_a_report_heading_is_bold_when_coloured():
    report = Report(checked=1)
    report.add(finding())
    assert "\033[1m" in format_report(report, palette=Palette(enabled=True))


def test_a_report_without_a_palette_is_plain():
    report = Report(checked=1)
    report.add(finding())
    assert "\033" not in format_report(report)


def test_the_command_line_can_force_colour_on(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--color",
    ])
    assert "\033[" in result.output


def test_the_command_line_can_force_it_off(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--no-color",
    ])
    assert "\033[" not in result.output


def test_a_report_written_to_a_file_is_never_coloured(project, tmp_path):
    out = tmp_path / "check.txt"
    runner = CliRunner()
    runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--fail-on", "never", "--color", "-o", str(out),
    ])
    assert "\033[" not in out.read_text(encoding="utf-8")
