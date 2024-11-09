import datetime as dt
from pathlib import Path

import pytest
from openpyxl import Workbook

from v4t_translate.errors import WorkbookError
from v4t_translate.workbook.reader import clean_cell, read_workbook

DELIVERED = Path(__file__).resolve().parents[1] / "Translate"


def build(tmp_path, rows, *, name="sheet.xlsx", title=None, extra_sheets=()):
    book = Workbook()
    sheet = book.active
    if title:
        sheet.title = title
    for row in rows:
        sheet.append(row)
    for extra in extra_sheets:
        book.create_sheet(extra)
    path = tmp_path / name
    book.save(path)
    return path


LEGACY = [
    ["English", "Taiwan"],
    ["Delete", "刪除"],
    ["New", "新的"],
    ["OK", "好的"],
]

FULL = [
    ["Key", "Source", "German", "Status", "Note", "Limit"],
    ["bar-height.aaa111", "Bar Height", "Balkenhöhe", "approved", "", "54px"],
    ["ok.bbb222", "OK", "OK", "approved", "", "42px"],
    ["pen.ccc333", "Pen", "", "empty", "which sense?", "18px"],
]


def test_reading_a_legacy_two_column_sheet(tmp_path):
    read = read_workbook(build(tmp_path, LEGACY))
    assert read.locale.tag == "zh-TW"
    assert read.legacy
    assert len(read) == 3
    assert read.rows[0].source == "Delete"
    assert read.rows[0].target == "刪除"


def test_reading_the_full_shape(tmp_path):
    read = read_workbook(build(tmp_path, FULL))
    assert not read.legacy
    assert read.locale.tag == "de-DE"
    assert read.rows[0].key == "bar-height.aaa111"
    assert read.rows[0].status == "approved"
    assert read.rows[2].note == "which sense?"


def test_row_numbers_are_the_ones_excel_shows(tmp_path):
    read = read_workbook(build(tmp_path, LEGACY))
    assert [row.row for row in read.rows] == [2, 3, 4]


def test_a_title_above_the_header_is_skipped(tmp_path):
    rows = [["V4T-TIJ localisation, round 3"], [], *LEGACY]
    read = read_workbook(build(tmp_path, rows))
    assert len(read) == 3
    assert read.schema.header_row == 3


def test_blank_rows_are_skipped(tmp_path):
    rows = [*LEGACY, [None, None], ["", ""], ["Cancel", "取消"]]
    read = read_workbook(build(tmp_path, rows))
    assert len(read) == 4


def test_untranslated_rows_are_kept(tmp_path):
    read = read_workbook(build(tmp_path, [*LEGACY, ["Cancel", None]]))
    assert len(read) == 4
    assert read.rows[-1].target == ""
    assert len(read.translated()) == 3


def test_a_translation_with_no_source_is_dropped_with_a_warning(tmp_path):
    read = read_workbook(build(tmp_path, [*LEGACY, [None, "孤兒"]]))
    assert len(read) == 3
    assert any("no source and no key" in w for w in read.warnings)


def test_by_key_and_by_source(tmp_path):
    read = read_workbook(build(tmp_path, FULL))
    assert read.by_key()["ok.bbb222"].target == "OK"
    assert read.by_source()["Bar Height"].target == "Balkenhöhe"


def test_a_legacy_sheet_has_no_keys(tmp_path):
    assert read_workbook(build(tmp_path, LEGACY)).by_key() == {}


def test_duplicate_rows_that_agree_are_silent(tmp_path):
    read = read_workbook(build(tmp_path, [*LEGACY, ["Delete", "刪除"]]))
    assert read.warnings == []


def test_duplicate_rows_that_disagree_are_reported(tmp_path):
    read = read_workbook(build(tmp_path, [*LEGACY, ["Delete", "移除"]]))
    assert any("disagree" in w for w in read.warnings)
    assert read.by_source()["Delete"].target == "移除"


def test_columns_in_any_order(tmp_path):
    rows = [["German", "Key", "Source"], ["Balkenhöhe", "bar.1", "Bar Height"]]
    read = read_workbook(build(tmp_path, rows))
    assert read.rows[0].source == "Bar Height"
    assert read.rows[0].target == "Balkenhöhe"


def test_the_first_sheet_is_used_by_default(tmp_path):
    path = build(tmp_path, LEGACY, title="Translation", extra_sheets=("Notes",))
    assert read_workbook(path).sheet == "Translation"


def test_a_named_sheet_can_be_asked_for(tmp_path):
    book = Workbook()
    book.active.title = "Notes"
    book.active.append(["not a translation sheet"])
    sheet = book.create_sheet("Translation")
    for row in LEGACY:
        sheet.append(row)
    path = tmp_path / "two.xlsx"
    book.save(path)

    read = read_workbook(path, sheet="Translation")
    assert len(read) == 3


def test_a_missing_sheet_name_lists_the_real_ones(tmp_path):
    path = build(tmp_path, LEGACY, title="Translation")
    with pytest.raises(WorkbookError, match="It has: Translation"):
        read_workbook(path, sheet="Nope")


def test_a_missing_file(tmp_path):
    with pytest.raises(WorkbookError, match="does not exist"):
        read_workbook(tmp_path / "nope.xlsx")


def test_a_file_that_is_not_a_workbook(tmp_path):
    path = tmp_path / "not.xlsx"
    path.write_text("this is not a spreadsheet", encoding="utf-8")
    with pytest.raises(WorkbookError, match="could not be opened"):
        read_workbook(path)


def test_a_sheet_with_no_usable_header(tmp_path):
    with pytest.raises(WorkbookError, match="no source column"):
        read_workbook(build(tmp_path, [["a", "b"], ["c", "d"]]))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("plain", "plain"),
        (4, "4"),
        (4.0, "4"),
        (4.5, "4.5"),
        (100000.0, "100000"),
        (True, "TRUE"),
        (False, "FALSE"),
        (dt.date(2024, 6, 17), "2024-06-17"),
        (dt.datetime(2024, 6, 17, 13, 36), "2024-06-17T13:36:00"),
    ],
)
def test_clean_cell(value, expected):
    assert clean_cell(value) == expected


def test_clean_cell_strips_a_non_breaking_space():
    assert clean_cell("Druck abstand") == "Druck abstand"


def test_clean_cell_strips_a_zero_width_space():
    assert clean_cell("Druck​abstand") == "Druckabstand"


def test_clean_cell_normalises_line_endings():
    assert clean_cell("a\r\nb") == "a\nb"


def test_clean_cell_composes_unicode():
    assert clean_cell("Auflösung") == "Auflösung"


def test_a_numeric_source_does_not_become_a_float(tmp_path):
    # "4." typed into a cell comes back as 4.0 and must not be written back
    # as "4.0", which is what the old pipeline did.
    read = read_workbook(build(tmp_path, [["English", "Taiwan"], [4, "四"]]))
    assert read.rows[0].source == "4"


def test_trailing_space_in_a_translation_is_kept(tmp_path):
    # The source column is stripped, the target column is not, because a
    # trailing space is sometimes what joins two runtime strings.
    read = read_workbook(build(tmp_path, [["English", "Taiwan"], ["  Delete  ", "刪除 "]]))
    assert read.rows[0].source == "Delete"
    assert read.rows[0].target == "刪除 "


@pytest.mark.skipif(not DELIVERED.exists(), reason="delivered workbooks not present")
def test_the_real_taiwan_workbook_reads():
    read = read_workbook(DELIVERED / "Translation - V4T-TIJ - Taiwan.xlsx")
    assert read.locale.tag == "zh-TW"
    assert read.legacy
    assert len(read) > 600
    assert read.by_source()["Delete"].target == "刪除"


@pytest.mark.skipif(not DELIVERED.exists(), reason="delivered workbooks not present")
def test_the_real_german_workbook_reads():
    read = read_workbook(DELIVERED / "Translation - V4T-TIJ8PEN-Config - German.xlsx")
    assert read.locale.tag == "de-DE"
    assert read.by_source()["Printer Resolution"].target == "Druckerauflösung"
    assert "%.1fV" in read.by_source()["Please input from %.1fV to %.1fV."].target
