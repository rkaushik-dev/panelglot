import shutil

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from v4t_translate.cli import main

CONFIG = """
[project]
name = "V4T-TIJ"
workbook_dir = "Translate"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]
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


def sheet(project, rows, name="delivery.xlsx"):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    path = project / name
    book.save(path)
    return path


def test_help_lists_both_commands(runner):
    output = runner.invoke(main, ["--help"]).output
    assert "export" in output
    assert "import" in output


def test_export_writes_a_sheet_per_locale(runner, project):
    invoke(runner, project, "extract")
    result = invoke(runner, project, "export")
    assert result.exit_code == 0
    assert "de-DE:" in result.output
    assert "zh-TW:" in result.output
    assert (project / "Translate").exists()


def test_export_of_one_locale(runner, project):
    invoke(runner, project, "extract")
    result = invoke(runner, project, "export", "-l", "de-DE")
    assert "zh-TW" not in result.output


def test_export_before_extract_fails(runner, project):
    assert invoke(runner, project, "export").exit_code != 0


def test_import_reports_what_landed(runner, project):
    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Print started", "Druck gestartet"]])
    result = invoke(runner, project, "import", str(path))
    assert result.exit_code == 0
    assert "de-DE: 1 rows: 1 applied" in result.output


def test_import_warns_about_a_row_that_matches_nothing(runner, project):
    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Long gone", "Verschwunden"]])
    result = invoke(runner, project, "import", str(path))
    assert result.exit_code == 0
    assert "matches no message" in result.output


def test_strict_turns_that_into_a_failure(runner, project, monkeypatch):
    from v4t_translate.cli import run

    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Long gone", "Verschwunden"]])
    monkeypatch.chdir(project)
    assert run(["import", str(path), "--strict"]) == 2


def test_strict_passes_on_a_clean_delivery(runner, project):
    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Print started", "Druck gestartet"]])
    assert invoke(runner, project, "import", str(path), "--strict").exit_code == 0


def test_import_dry_run(runner, project):
    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Print started", "Druck gestartet"]])
    result = invoke(runner, project, "import", str(path), "--dry-run")
    assert "dry run, nothing written" in result.output


def test_import_draft_flag(runner, project):
    from v4t_translate.catalog.ids import message_key
    from v4t_translate.catalog.store import load_translations
    from v4t_translate.catalog.translations import TranslationState
    from v4t_translate.config import load_config

    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Print started", "Druck gestartet"]])
    invoke(runner, project, "import", str(path), "--draft")

    config = load_config(project / "v4t-translate.toml")
    entry = load_translations(config.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.state is TranslationState.DRAFT


def test_import_of_a_missing_file_is_rejected_by_click(runner, project):
    invoke(runner, project, "extract")
    result = invoke(runner, project, "import", str(project / "nope.xlsx"))
    assert result.exit_code == 2


def test_import_insisting_on_the_wrong_locale(runner, project):
    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Print started", "Druck gestartet"]])
    result = invoke(runner, project, "import", str(path), "-l", "zh-TW")
    assert result.exit_code != 0


def test_verbose_import_lists_the_keys(runner, project):
    invoke(runner, project, "extract")
    path = sheet(project, [["English", "German"], ["Print started", "Druck gestartet"]])
    result = invoke(runner, project, "-vv", "import", str(path))
    assert "applied print-started" in result.output


def test_export_import_export_is_stable(runner, project):
    from v4t_translate.workbook.reader import read_workbook

    invoke(runner, project, "extract")
    invoke(runner, project, "export", "-l", "de-DE")
    path = project / "Translate" / "V4T-TIJ - German.xlsx"
    before = len(read_workbook(path))

    invoke(runner, project, "import", str(path))
    invoke(runner, project, "export", "-l", "de-DE")
    assert len(read_workbook(path)) == before
