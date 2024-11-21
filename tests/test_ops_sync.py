import shutil
from datetime import date

import pytest
from openpyxl import Workbook

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations
from v4t_translate.catalog.translations import TranslationState
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError, WorkbookError
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.sync import export_workbooks, import_workbook
from v4t_translate.workbook.reader import read_workbook

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
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def sheet(tmp_path, rows, name="delivery.xlsx"):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    path = tmp_path / name
    book.save(path)
    return path


def test_export_writes_one_sheet_per_locale(project):
    result = export_workbooks(project)
    assert [tag for tag, _, _ in result.written] == ["de-DE", "zh-TW"]
    for _, path, rows in result.written:
        assert path.exists()
        assert rows > 30


def test_export_uses_the_configured_directory(project):
    result = export_workbooks(project)
    for _, path, _ in result.written:
        assert path.parent.name == "Translate"


def test_export_can_be_limited_to_one_locale(project):
    result = export_workbooks(project, locales=["de-DE"])
    assert len(result.written) == 1


def test_export_summary(project):
    assert "de-DE" in export_workbooks(project, locales=["de-DE"]).summary()


def test_export_before_extract_is_an_error(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError, match="Run extract first"):
        export_workbooks(config)


def test_a_full_round_trip(project):
    export_workbooks(project, locales=["de-DE"])
    path = project.workbook_path("de-DE")

    from openpyxl import load_workbook
    book = load_workbook(path)
    ws = book.active
    for row in range(2, ws.max_row + 1):
        if ws.cell(row=row, column=2).value == "Print started":
            ws.cell(row=row, column=3, value="Druck gestartet")
            break
    book.save(path)

    result = import_workbook(project, path)
    assert result.locale == "de-DE"
    assert message_key("Print started") in result.applied
    assert result.is_clean()

    translations = load_translations(project.translations_path("de-DE"))
    entry = translations.get(message_key("Print started"))
    assert entry.text == "Druck gestartet"
    assert entry.state is TranslationState.APPROVED


def test_a_stale_empty_status_beside_a_filled_cell_is_ignored(project, tmp_path):
    # The sheet goes out with every status set to empty. A translator fills in
    # the translation column and leaves the dropdown alone, because nobody
    # touches a control they were not asked about.
    path = sheet(tmp_path, [
        ["Key", "Source", "German", "Status"],
        [message_key("Print started"), "Print started", "Druck gestartet", "empty"],
    ])
    import_workbook(project, path)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.state is TranslationState.APPROVED


def test_a_legacy_two_column_delivery_matches_on_text(project, tmp_path):
    path = sheet(tmp_path, [
        ["English", "German"],
        ["Print started", "Druck gestartet"],
        ["Service restarted", "Dienst neu gestartet"],
    ])
    result = import_workbook(project, path)
    assert len(result.applied) == 2
    assert result.is_clean()


def test_a_row_that_matches_nothing_is_counted(project, tmp_path):
    path = sheet(tmp_path, [
        ["English", "German"],
        ["Print started", "Druck gestartet"],
        ["A string that was deleted last release", "Ein geloeschter Text"],
    ])
    result = import_workbook(project, path)
    assert len(result.applied) == 1
    assert len(result.unmatched) == 1
    assert result.unmatched[0].source.startswith("A string that")
    assert not result.is_clean()


def test_an_unchanged_row_is_not_reapplied(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Print started", "Druck gestartet"]])
    import_workbook(project, path)
    again = import_workbook(project, path)
    assert again.applied == []
    assert len(again.unchanged) == 1


def test_the_status_column_is_honoured(project, tmp_path):
    path = sheet(tmp_path, [
        ["Source", "German", "Status"],
        ["Print started", "Druck gestartet", "needs-review"],
    ])
    import_workbook(project, path)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.state is TranslationState.NEEDS_REVIEW


def test_an_unreadable_status_falls_back_to_approved(project, tmp_path):
    path = sheet(tmp_path, [
        ["Source", "German", "Status"],
        ["Print started", "Druck gestartet", "fertig"],
    ])
    import_workbook(project, path)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.state is TranslationState.APPROVED


def test_approve_false_lands_as_draft(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Print started", "Druck gestartet"]])
    import_workbook(project, path, approve=False)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.state is TranslationState.DRAFT


def test_an_emptied_cell_does_not_erase_an_existing_translation(project, tmp_path):
    import_workbook(project, sheet(tmp_path, [
        ["English", "German"], ["Print started", "Druck gestartet"]], name="first.xlsx"))
    result = import_workbook(project, sheet(tmp_path, [
        ["English", "German"], ["Print started", None]], name="second.xlsx"))

    assert any("keeping the existing translation" in w for w in result.warnings)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.text == "Druck gestartet"


def test_dry_run_writes_nothing(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Print started", "Druck gestartet"]])
    result = import_workbook(project, path, dry_run=True)
    assert result.written is None
    assert len(result.applied) == 1
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.text == ""


def test_the_locale_comes_from_the_heading(project, tmp_path):
    path = sheet(tmp_path, [["English", "Taiwan"], ["Print started", "列印已開始"]])
    result = import_workbook(project, path)
    assert result.locale == "zh-TW"


def test_asking_for_a_locale_the_sheet_does_not_hold(project, tmp_path):
    path = sheet(tmp_path, [["English", "Taiwan"], ["Print started", "列印已開始"]])
    with pytest.raises(WorkbookError, match="but de-DE was asked for"):
        import_workbook(project, path, locale="de-DE")


def test_asking_for_the_locale_the_sheet_does_hold(project, tmp_path):
    path = sheet(tmp_path, [["English", "Taiwan"], ["Print started", "列印已開始"]])
    assert import_workbook(project, path, locale="Taiwan").locale == "zh-TW"


def test_the_origin_records_the_workbook_name(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Print started", "Druck gestartet"]],
                 name="round-3.xlsx")
    import_workbook(project, path)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.origin == "round-3.xlsx"


def test_the_update_date_is_recorded(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Print started", "Druck gestartet"]])
    import_workbook(project, path, today=date(2024, 11, 20))
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.updated == "2024-11-20"


def test_a_translator_note_is_kept(project, tmp_path):
    path = sheet(tmp_path, [
        ["Source", "German", "Note"],
        ["Print started", "Druck gestartet", "assuming this is a status line"],
    ])
    import_workbook(project, path)
    entry = load_translations(project.translations_path("de-DE")).get(
        message_key("Print started"))
    assert entry.note == "assuming this is a status line"


def test_workbook_warnings_are_carried_through(project, tmp_path):
    path = sheet(tmp_path, [
        ["English", "German"],
        ["Print started", "Druck gestartet"],
        ["Print started", "Druck laeuft"],
    ])
    result = import_workbook(project, path)
    assert any("disagree" in w for w in result.warnings)


def test_summary_reads_as_a_sentence(project, tmp_path):
    path = sheet(tmp_path, [["English", "German"], ["Print started", "Druck gestartet"]])
    assert import_workbook(project, path).summary().startswith("1 rows: 1 applied")


def test_only_outstanding_export_shrinks_after_a_delivery(project, tmp_path):
    export_workbooks(project, locales=["de-DE"])
    full = read_workbook(project.workbook_path("de-DE"))

    import_workbook(project, sheet(tmp_path, [
        ["English", "German"],
        ["Print started", "Druck gestartet"],
        ["Service restarted", "Dienst neu gestartet"],
    ]))

    export_workbooks(project, locales=["de-DE"], only_outstanding=True)
    follow_up = read_workbook(project.workbook_path("de-DE"))
    assert len(follow_up) == len(full) - 2
