import pytest
from openpyxl import load_workbook

from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.locales import resolve
from v4t_translate.workbook.reader import read_workbook
from v4t_translate.workbook.styles import PROTECTED_FILL, REVIEW_FILL
from v4t_translate.workbook.writer import (
    WORKBOOK_COLUMNS,
    sheet_title_for,
    write_workbook,
)


def origin(container="IDD_BARCODE", symbol="IDC_STATIC", line=26):
    return Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                  container=container, symbol=symbol, line=line)


@pytest.fixture
def catalog():
    catalog = Catalog(project="V4T-TIJ")
    catalog.add(Message(key="bar-height.aaa111", source_text="Bar Height",
                        origins=[origin()], max_width_px=54))
    catalog.add(Message(key="hint.bbb222",
                        source_text="This distance cannot be greater than print spacing",
                        origins=[origin(symbol="IDC_HINT")], max_width_px=340, max_lines=2))
    catalog.add(Message(key="mm.ccc333", source_text="mm", protected=True,
                        origins=[origin(container="STRINGTABLE", symbol="IDS_MM")]))
    catalog.add(Message(key="pen.ddd444", source_text="Pen", origins=[origin()],
                        developer_note="The cartridge, not a writing pen.",
                        max_chars=20))
    return catalog


@pytest.fixture
def translations():
    entries = TranslationSet(locale="de-DE")
    entries.set("bar-height.aaa111", Translation(text="Balkenhöhe",
                                                 state=TranslationState.APPROVED))
    entries.set("hint.bbb222", Translation(text="Zu gross",
                                           state=TranslationState.NEEDS_REVIEW,
                                           note="check with the customer"))
    entries.set("mm.ccc333", Translation(text="mm",
                                         state=TranslationState.DO_NOT_TRANSLATE))
    return entries


@pytest.fixture
def written(tmp_path, catalog, translations):
    path = tmp_path / "out" / "german.xlsx"
    count = write_workbook(path, catalog, translations, resolve("de-DE"))
    return path, count


def sheet_of(path):
    return load_workbook(path).active


def test_every_message_gets_a_row(written):
    path, count = written
    assert count == 4
    assert sheet_of(path).max_row == 5


def test_parent_directories_are_created(written):
    path, _ = written
    assert path.exists()


def test_the_header(written):
    path, _ = written
    sheet = sheet_of(path)
    headings = [sheet.cell(row=1, column=i + 1).value
                for i in range(len(WORKBOOK_COLUMNS))]
    assert headings[:4] == ["Key", "Source", "German", "Status"]


def test_the_target_column_is_headed_with_the_language_name(written):
    path, _ = written
    assert sheet_of(path).cell(row=1, column=3).value == "German"


def test_rows_are_in_key_order(written):
    path, _ = written
    sheet = sheet_of(path)
    keys = [sheet.cell(row=r, column=1).value for r in range(2, 6)]
    assert keys == sorted(keys)


def test_translations_are_written(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value
               == "bar-height.aaa111")
    assert sheet.cell(row=row, column=3).value == "Balkenhöhe"
    assert sheet.cell(row=row, column=4).value == "approved"


def test_an_untranslated_row_has_an_empty_target(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "pen.ddd444")
    assert sheet.cell(row=row, column=3).value in (None, "")
    assert sheet.cell(row=row, column=4).value == "empty"


def test_the_pixel_budget_is_shown(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value
               == "bar-height.aaa111")
    assert sheet.cell(row=row, column=6).value == "54px"


def test_a_wrapping_control_shows_its_line_count(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "hint.bbb222")
    assert sheet.cell(row=row, column=6).value == "340px x2"


def test_a_character_budget_is_shown_in_characters(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "pen.ddd444")
    assert sheet.cell(row=row, column=6).value == "20 chars"


def test_the_origin_is_shown(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value
               == "bar-height.aaa111")
    assert "IDD_BARCODE" in sheet.cell(row=row, column=7).value


def test_notes_combine_the_developer_and_translator_ones(written):
    path, _ = written
    sheet = sheet_of(path)
    hint = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "hint.bbb222")
    assert "check with the customer" in sheet.cell(row=hint, column=5).value


def test_a_protected_row_says_so_in_the_note(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "mm.ccc333")
    assert "Do not translate" in sheet.cell(row=row, column=5).value


def test_a_protected_row_is_shaded_and_locked(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "mm.ccc333")
    target = sheet.cell(row=row, column=3)
    assert target.fill.fgColor.rgb == PROTECTED_FILL.fgColor.rgb
    assert target.protection.locked


def test_a_needs_review_row_is_shaded(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value == "hint.bbb222")
    assert sheet.cell(row=row, column=3).fill.fgColor.rgb == REVIEW_FILL.fgColor.rgb


def test_a_normal_target_cell_is_editable(written):
    path, _ = written
    sheet = sheet_of(path)
    row = next(r for r in range(2, 6) if sheet.cell(row=r, column=1).value
               == "bar-height.aaa111")
    assert not sheet.cell(row=row, column=3).protection.locked


def test_the_source_cell_is_always_locked(written):
    path, _ = written
    sheet = sheet_of(path)
    assert sheet.cell(row=2, column=2).protection.locked


def test_the_sheet_is_protected(written):
    path, _ = written
    assert sheet_of(path).protection.sheet


def test_panes_are_frozen_past_the_source(written):
    path, _ = written
    assert sheet_of(path).freeze_panes == "C2"


def test_an_autofilter_covers_the_data(written):
    path, _ = written
    assert sheet_of(path).auto_filter.ref == "A1:G5"


def test_the_status_column_is_a_dropdown(written):
    path, _ = written
    sheet = sheet_of(path)
    assert len(sheet.data_validations.dataValidation) == 1
    validation = sheet.data_validations.dataValidation[0]
    assert "approved" in validation.formula1
    assert "needs-review" in validation.formula1


def test_columns_have_sensible_widths(written):
    path, _ = written
    sheet = sheet_of(path)
    assert sheet.column_dimensions["B"].width == 52


def test_only_outstanding_skips_approved_rows(tmp_path, catalog, translations):
    path = tmp_path / "followup.xlsx"
    count = write_workbook(path, catalog, translations, resolve("de-DE"),
                           only_outstanding=True)
    assert count == 3
    keys = [sheet_of(path).cell(row=r, column=1).value for r in range(2, 5)]
    assert "bar-height.aaa111" not in keys


def test_an_empty_catalog_still_writes_a_header(tmp_path):
    path = tmp_path / "empty.xlsx"
    count = write_workbook(path, Catalog(project="X"), TranslationSet(locale="de-DE"),
                           resolve("de-DE"))
    assert count == 0
    assert sheet_of(path).cell(row=1, column=1).value == "Key"


def test_what_is_written_can_be_read_back(written):
    path, _ = written
    read = read_workbook(path)
    assert read.locale.tag == "de-DE"
    assert not read.legacy
    assert len(read) == 4
    assert read.by_key()["bar-height.aaa111"].target == "Balkenhöhe"
    assert read.by_key()["hint.bbb222"].status == "needs-review"


def test_a_round_trip_preserves_a_trailing_space(tmp_path):
    catalog = Catalog(project="X")
    catalog.add(Message(key="join.1", source_text="Purge offset must be less than ",
                        origins=[origin()]))
    entries = TranslationSet(locale="de-DE")
    entries.set("join.1", Translation(text="Der Versatz muss kleiner sein als ",
                                      state=TranslationState.APPROVED))
    path = tmp_path / "space.xlsx"
    write_workbook(path, catalog, entries, resolve("de-DE"))
    assert read_workbook(path).by_key()["join.1"].target.endswith(" ")


@pytest.mark.parametrize(
    ("project", "tag", "expected"),
    [
        ("V4T-TIJ", "de-DE", "V4T-TIJ de-DE"),
        ("V4T-TIJ", "zh-TW", "V4T-TIJ zh-TW"),
        ("V4T/TIJ:8PEN", "de-DE", "V4T-TIJ-8PEN de-DE"),
    ],
)
def test_sheet_titles(project, tag, expected):
    assert sheet_title_for(project, resolve(tag)) == expected


def test_a_very_long_project_name_is_truncated():
    title = sheet_title_for("V4T " * 20, resolve("de-DE"))
    assert len(title) <= 31
