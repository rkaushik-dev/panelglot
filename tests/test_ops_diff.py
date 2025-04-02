import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Message
from v4t_translate.catalog.store import (
    Catalog,
    load_translations,
    save_catalog,
    save_translations,
)
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError
from v4t_translate.ops.diff import diff_against, diff_catalogs, outstanding_after
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def catalog_of(*messages):
    catalog = Catalog(project="V4T-TIJ")
    for message in messages:
        catalog.add(message)
    return catalog


def msg(text, **kw):
    return Message(key=message_key(text), source_text=text, **kw)


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def test_two_identical_catalogs():
    before = catalog_of(msg("Bar Height"), msg("Width"))
    diff = diff_catalogs(before, catalog_of(msg("Bar Height"), msg("Width")))
    assert not diff
    assert diff.unchanged == 2


def test_a_new_message():
    diff = diff_catalogs(catalog_of(msg("Bar Height")),
                         catalog_of(msg("Bar Height"), msg("Module size")))
    assert [m.source_text for m in diff.added] == ["Module size"]
    assert diff.needs_attention == 1


def test_a_gone_message():
    diff = diff_catalogs(catalog_of(msg("Bar Height"), msg("Module size")),
                         catalog_of(msg("Bar Height")))
    assert [m.source_text for m in diff.removed] == ["Module size"]
    # Gone is not attention. Nobody has to do anything about it.
    assert diff.needs_attention == 0


def test_a_control_that_got_smaller():
    diff = diff_catalogs(catalog_of(msg("Bar Height", max_width_px=90)),
                         catalog_of(msg("Bar Height", max_width_px=54)))
    assert len(diff.changed) == 1
    assert "space changed from 90px to 54px" in diff.changed[0].describe()


def test_a_control_that_gained_a_budget():
    diff = diff_catalogs(catalog_of(msg("Bar Height")),
                         catalog_of(msg("Bar Height", max_width_px=54)))
    assert "from unbounded to 54px" in diff.changed[0].describe()


def test_a_character_budget_change():
    diff = diff_catalogs(catalog_of(msg("Pen", max_chars=20)),
                         catalog_of(msg("Pen", max_chars=6)))
    assert "character budget changed from 20 to 6" in diff.changed[0].describe()


def test_a_line_budget_change():
    diff = diff_catalogs(catalog_of(msg("Hint", max_lines=3)),
                         catalog_of(msg("Hint", max_lines=1)))
    assert "lines changed from 3 to 1" in diff.changed[0].describe()


def test_becoming_protected():
    diff = diff_catalogs(catalog_of(msg("mm")),
                         catalog_of(msg("mm", protected=True)))
    assert "is now protected" in diff.changed[0].describe()


def test_stopping_being_protected():
    diff = diff_catalogs(catalog_of(msg("mm", protected=True)),
                         catalog_of(msg("mm")))
    assert "is no longer protected" in diff.changed[0].describe()


def test_a_note_change():
    diff = diff_catalogs(catalog_of(msg("Pen")),
                         catalog_of(msg("Pen", developer_note="The cartridge.")))
    assert "the note changed" in diff.changed[0].describe()


def test_a_context_change():
    diff = diff_catalogs(catalog_of(msg("Print")),
                         catalog_of(msg("Print", context="verb")))
    assert "context changed to 'verb'" in diff.changed[0].describe()


def test_several_reasons_at_once():
    diff = diff_catalogs(
        catalog_of(msg("Pen", max_width_px=90)),
        catalog_of(msg("Pen", max_width_px=54, protected=True)),
    )
    assert len(diff.changed[0].reasons) == 2


def test_added_words_are_counted():
    diff = diff_catalogs(catalog_of(), catalog_of(msg("Print started now")))
    assert diff.added_words == 3


def test_the_summary_reads():
    diff = diff_catalogs(catalog_of(msg("a"), msg("Bar Height")),
                         catalog_of(msg("a"), msg("Module size")))
    assert diff.summary() == "1 new (2 words), 0 changed, 1 gone, 1 untouched"


def test_diff_against_a_saved_copy(project, tmp_path):
    saved = tmp_path / "sent-to-translator.json"
    shutil.copy(project.catalog_path(), saved)

    source = project.root / "src" / "V4T.rc"
    source.write_text(
        source.read_text(encoding="utf-8").replace("Bar Height", "Bar height"),
        encoding="utf-8",
    )
    extract_project(project)

    diff = diff_against(project, saved)
    assert [m.source_text for m in diff.added] == ["Bar height"]
    assert [m.source_text for m in diff.removed] == ["Bar Height"]


def test_diff_against_before_extract(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")

    saved = tmp_path / "old.json"
    save_catalog(saved, catalog_of(msg("Bar Height")))

    with pytest.raises(CatalogError, match="Run extract first"):
        diff_against(config, saved)


def test_outstanding_skips_what_memory_already_answered(project, tmp_path):
    saved = tmp_path / "old.json"
    save_catalog(saved, Catalog(project="V4T-TIJ"))

    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Print started"),
                     Translation(text="Druck gestartet",
                                 state=TranslationState.APPROVED))
    save_translations(path, translations)

    diff = diff_against(project, saved)
    outstanding = outstanding_after(project, diff, "de-DE")

    assert len(diff.added) > len(outstanding)
    assert message_key("Print started") not in outstanding


def test_the_command_line(project, tmp_path):
    saved = tmp_path / "old.json"
    shutil.copy(project.catalog_path(), saved)

    source = project.root / "src" / "V4T.rc"
    source.write_text(
        source.read_text(encoding="utf-8").replace("Module size", "Module width"),
        encoding="utf-8",
    )
    extract_project(project)

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "diff", str(saved),
    ])
    assert result.exit_code == 0
    assert "new      'Module width'" in result.output
    assert "1 new" in result.output


def test_the_command_line_with_a_locale(project, tmp_path):
    saved = tmp_path / "old.json"
    save_catalog(saved, Catalog(project="V4T-TIJ"))

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "diff", str(saved),
        "-l", "de-DE",
    ])
    assert "still unanswered" in result.output


def test_gone_messages_only_show_when_verbose(project, tmp_path):
    saved = tmp_path / "old.json"
    shutil.copy(project.catalog_path(), saved)

    source = project.root / "src" / "V4T.rc"
    source.write_text(
        source.read_text(encoding="utf-8").replace('"Module size"', '"Module width"'),
        encoding="utf-8",
    )
    extract_project(project)

    runner = CliRunner()
    args = ["-c", str(project.root / "v4t-translate.toml")]
    quiet = runner.invoke(main, [*args, "diff", str(saved)]).output
    loud = runner.invoke(main, [*args, "-v", "diff", str(saved)]).output

    assert "  gone " not in quiet
    assert "  gone     'Module size'" in loud
