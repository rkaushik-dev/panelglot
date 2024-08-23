import shutil

import pytest
from click.testing import CliRunner

from v4t_translate import __version__
from v4t_translate.cli import main, run

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


def invoke(runner, project, *args):
    return runner.invoke(main, ["-c", str(project / "v4t-translate.toml"), *args])


def test_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_extract(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "extract" in result.output


def test_short_help_flag_works(runner):
    assert runner.invoke(main, ["-h"]).exit_code == 0


def test_extract_writes_and_says_so(runner, project):
    result = invoke(runner, project, "extract")
    assert result.exit_code == 0
    assert "messages:" in result.output
    assert (project / "catalog" / "v4t-tij.json").exists()


def test_extract_dry_run_says_it_wrote_nothing(runner, project):
    result = invoke(runner, project, "extract", "--dry-run")
    assert result.exit_code == 0
    assert "dry run, nothing written" in result.output
    assert not (project / "catalog").exists()


def test_quiet_prints_nothing_on_success(runner, project):
    result = invoke(runner, project, "-q", "extract")
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_verbose_lists_the_files_written(runner, project):
    result = invoke(runner, project, "-v", "extract")
    assert "wrote " in result.output
    assert "src/V4T.rc:" in result.output


def test_verbose_shows_carried_rewordings(runner, project):
    invoke(runner, project, "extract")
    path = project / "src" / "V4T.rc"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "This distance cannot be greater than print spacing",
            "This distance cannot be greater than the print spacing",
        ),
        encoding="utf-8",
    )
    result = invoke(runner, project, "-v", "extract")
    assert "carried " in result.output


def test_a_missing_source_is_an_error_not_a_traceback(runner, project):
    (project / "src" / "V4T.rc").unlink()
    result = invoke(runner, project, "extract")
    assert result.exit_code != 0


def test_keep_going_warns_instead(runner, project):
    (project / "src" / "V4T.rc").unlink()
    result = invoke(runner, project, "extract", "--keep-going")
    assert result.exit_code == 0
    assert "skipped" in result.output


def test_a_bad_config_path_is_rejected_by_click(runner, tmp_path):
    result = runner.invoke(main, ["-c", str(tmp_path / "nope.toml"), "extract"])
    assert result.exit_code == 2


def test_run_returns_the_error_exit_code(project, monkeypatch):
    monkeypatch.chdir(project)
    (project / "src" / "V4T.rc").unlink()
    assert run(["extract"]) == 65


def test_run_returns_zero_on_success(project, monkeypatch):
    monkeypatch.chdir(project)
    assert run(["extract", "--dry-run"]) == 0


def test_run_finds_the_config_by_walking_up(project, monkeypatch):
    deep = project / "src"
    monkeypatch.chdir(deep)
    assert run(["extract", "--dry-run"]) == 0


def test_run_without_a_config_anywhere_reports_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(["extract"]) == 78


def test_traceback_flag_lets_the_exception_through(project, monkeypatch):
    from v4t_translate.errors import SourceError

    monkeypatch.chdir(project)
    (project / "src" / "V4T.rc").unlink()
    with pytest.raises(SourceError):
        run(["--traceback", "extract"])


def test_module_entry_point_exists():
    from v4t_translate.__main__ import main as module_main

    assert callable(module_main)
