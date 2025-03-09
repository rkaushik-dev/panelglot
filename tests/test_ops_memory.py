import shutil

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError
from v4t_translate.mt.memory import TranslationMemory
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.memory import (
    absorb_catalog,
    absorb_workbook,
    memory_path,
    memory_stats,
    suggest_for,
)

CONFIG = """
[project]
name = "V4T-TIJ"

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
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def translate(config, tag, pairs, state=TranslationState.APPROVED):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for source, target in pairs.items():
        translations.set(message_key(source), Translation(text=target, state=state))
    save_translations(path, translations)


def sheet(tmp_path, rows, name="legacy.xlsx"):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    path = tmp_path / name
    book.save(path)
    return path


def test_memory_path_sits_beside_the_catalog(project):
    assert memory_path(project) == project.root / "catalog" / "memory.sqlite3"


def test_an_empty_memory_reports_nothing(project):
    assert memory_stats(project) == {}


def test_absorb_takes_approved_entries(project):
    translate(project, "de-DE", {
        "Print started": "Druck gestartet",
        "Service restarted": "Dienst neu gestartet",
    })
    report = absorb_catalog(project)
    assert report.added == 2
    assert report.locales == ["de-DE"]
    assert report.total == 2


def test_absorb_leaves_drafts_alone(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"},
              state=TranslationState.DRAFT)
    assert absorb_catalog(project).added == 0


def test_absorb_can_be_told_to_take_needs_review(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"},
              state=TranslationState.NEEDS_REVIEW)
    assert absorb_catalog(project, include_drafts=True).added == 1


def test_absorb_across_two_languages(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    translate(project, "zh-TW", {"Print started": "列印已開始"})
    report = absorb_catalog(project)
    assert sorted(report.locales) == ["de-DE", "zh-TW"]
    assert memory_stats(project) == {"de-DE": 1, "zh-TW": 1}


def test_absorb_can_be_limited_to_one_language(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    translate(project, "zh-TW", {"Print started": "列印已開始"})
    assert absorb_catalog(project, locales=["de-DE"]).locales == ["de-DE"]


def test_absorb_before_extract(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError, match="Run extract first"):
        absorb_catalog(config)


def test_the_summary_reads(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    assert absorb_catalog(project).summary() == "1 units from de-DE, 1 in memory"


def test_an_empty_absorb_summary(project):
    assert absorb_catalog(project).summary() == "0 units from nothing, 0 in memory"


def test_a_workbook_goes_straight_into_memory(project, tmp_path):
    path = sheet(tmp_path, [
        ["English", "German"],
        ["A string this project has never seen", "Ein voellig fremder Text"],
        ["Print started", "Druck gestartet"],
    ])
    report = absorb_workbook(project, path)
    assert report.added == 2
    assert report.locales == ["de-DE"]


def test_a_workbook_entry_that_matches_nothing_is_still_kept(project, tmp_path):
    # This is the whole point: sheets from products that shipped before this
    # tool existed have no catalog to match against.
    path = sheet(tmp_path, [
        ["English", "German"],
        ["Group Combination", "Gruppenkombination"],
    ])
    absorb_workbook(project, path)
    with TranslationMemory(memory_path(project)) as memory:
        assert memory.recall("de-DE", "Group Combination").target == (
            "Gruppenkombination"
        )


def test_the_workbook_name_is_recorded_as_the_origin(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Pen", "Stift"]],
                 name="tij8pen-german.xlsx")
    absorb_workbook(project, path)
    with TranslationMemory(memory_path(project)) as memory:
        assert memory.recall("de-DE", "Pen").origin == "tij8pen-german.xlsx"


def test_untranslated_rows_are_skipped(project, tmp_path):
    path = sheet(tmp_path, [
        ["English", "German"],
        ["Pen", "Stift"],
        ["Width", None],
    ])
    assert absorb_workbook(project, path).added == 1


def test_workbook_warnings_are_carried_through(project, tmp_path):
    path = sheet(tmp_path, [
        ["English", "German"],
        ["Pen", "Stift"],
        ["Pen", "Feder"],
    ])
    assert any("disagree" in w for w in absorb_workbook(project, path).warnings)


def test_suggest_finds_what_was_absorbed(project):
    translate(project, "de-DE", {
        "Purge offset must be less than group offset":
            "Der Versatz muss kleiner als der Gruppenversatz sein",
    })
    absorb_catalog(project)
    matches = suggest_for(project, "de-DE",
                          "Purge offset must be less than the group offset")
    assert matches
    assert matches[0].target.startswith("Der Versatz")


def test_suggest_of_an_empty_memory(project):
    assert suggest_for(project, "de-DE", "Anything at all") == []


def test_suggest_accepts_a_locale_alias(project):
    translate(project, "zh-TW", {"Print started": "列印已開始"})
    absorb_catalog(project)
    assert suggest_for(project, "Taiwan", "Print started")


def test_the_command_line_stats_of_an_empty_memory(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "memory", "stats",
    ])
    assert result.exit_code == 0
    assert "memory is empty" in result.output


def test_the_command_line_absorb_then_stats(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    runner = CliRunner()
    config_arg = ["-c", str(project.root / "v4t-translate.toml")]

    assert runner.invoke(main, [*config_arg, "memory", "absorb"]).exit_code == 0
    result = runner.invoke(main, [*config_arg, "memory", "stats"])
    assert "de-DE: 1" in result.output


def test_the_command_line_import(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Pen", "Stift"]])
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "memory", "import", str(path),
    ])
    assert result.exit_code == 0
    assert "1 units from de-DE" in result.output


def test_the_command_line_suggest(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    absorb_catalog(project)
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "memory", "suggest", "de-DE", "Print started",
    ])
    assert "100%" in result.output
    assert "Druck gestartet" in result.output


def test_the_command_line_suggest_with_nothing_to_offer(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "memory", "suggest", "de-DE", "Bearer thickness",
    ])
    assert "nothing close enough" in result.output


def test_the_memory_group_has_help():
    result = CliRunner().invoke(main, ["memory", "--help"])
    assert result.exit_code == 0
    for command in ("stats", "absorb", "import", "suggest"):
        assert command in result.output
