import shutil

import pytest
from openpyxl import Workbook, load_workbook

from v4t_translate.config import load_config
from v4t_translate.errors import WorkbookError
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.sync import export_workbooks, import_workbook
from v4t_translate.workbook.reader import read_workbook

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
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


@pytest.fixture
def delivered(project):
    """An exported workbook with one row filled in."""
    path = export_workbooks(project, locales=["de-DE"]).written[0][1]

    book = load_workbook(path)
    sheet = book.worksheets[0]
    sheet.cell(row=2, column=3, value="Balkenliste:")
    book.save(path)
    return path


def reorder(path, order):
    """Rewrite the workbook with its sheets in a different order."""
    book = load_workbook(path)
    book._sheets = [book[name] for name in order]
    book.save(path)
    return path


def make(rows, title="Sheet1", extra=None):
    """A minimal workbook, optionally with a decoy sheet in front."""
    book = Workbook()
    if extra is not None:
        first = book.active
        first.title = extra
        first["A1"] = "How to fill this in"
        first["A2"] = "The Translation column is the only one you type in."
        sheet = book.create_sheet(title)
    else:
        sheet = book.active
        sheet.title = title

    for number, row in enumerate(rows, start=1):
        for column, value in enumerate(row, start=1):
            sheet.cell(row=number, column=column, value=value)

    return book


HEADER = ["Key", "Source", "German", "Status", "Note"]


# -- picking the sheet --------------------------------------------------


def test_the_first_sheet_is_used_when_it_reads(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]]).save(path)
    assert read_workbook(path).sheet == "Sheet1"


def test_a_decoy_first_sheet_is_stepped_over(tmp_path):
    # Excel remembers which sheet was open when it was saved, and will happily
    # reorder them if somebody dragged a tab.
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]],
         extra="How to fill this in").save(path)

    read = read_workbook(path)
    assert read.sheet == "Sheet1"
    assert len(read.rows) == 1


def test_stepping_over_one_is_reported(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]],
         extra="How to fill this in").save(path)
    assert any("not the first sheet" in w for w in read_workbook(path).warnings)


def test_using_the_first_sheet_says_nothing(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]]).save(path)
    assert not any("first sheet" in w for w in read_workbook(path).warnings)


def test_a_named_sheet_is_the_only_candidate(tmp_path):
    # Being asked for one sheet and reading a different one would be worse
    # than failing.
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]],
         extra="Notes").save(path)

    with pytest.raises(WorkbookError):
        read_workbook(path, sheet="Notes")


def test_a_sheet_that_does_not_exist_is_refused(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]]).save(path)

    with pytest.raises(WorkbookError, match="no sheet named"):
        read_workbook(path, sheet="Nowhere")


def test_the_refusal_lists_the_sheets(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "Balkenhöhe", "", ""]]).save(path)

    with pytest.raises(WorkbookError, match="Sheet1"):
        read_workbook(path, sheet="Nowhere")


def test_a_workbook_with_no_readable_sheet_is_refused(tmp_path):
    path = tmp_path / "book.xlsx"
    make([["Title"], ["Just prose"]]).save(path)

    with pytest.raises(WorkbookError):
        read_workbook(path)


def test_the_error_is_from_the_first_sheet_tried(tmp_path):
    # The one somebody most likely meant, not whichever failed last.
    path = tmp_path / "book.xlsx"
    make([["Nothing useful here"]], title="First").save(path)

    with pytest.raises(WorkbookError, match="First"):
        read_workbook(path)


# -- our own export round trips -----------------------------------------


def test_our_own_export_reads_back(delivered):
    read = read_workbook(delivered)
    assert read.locale.tag == "de-DE"
    assert read.rows


def test_it_survives_the_tabs_being_reordered(project, delivered):
    from v4t_translate.workbook.instructions import SHEET_TITLE as INSTRUCTIONS

    book = load_workbook(delivered)
    names = book.sheetnames
    reorder(delivered, [INSTRUCTIONS, *[n for n in names if n != INSTRUCTIONS]])

    read = read_workbook(delivered)
    assert read.locale.tag == "de-DE"
    assert read.rows


def test_a_reordered_delivery_still_imports(project, delivered):
    from v4t_translate.workbook.instructions import SHEET_TITLE as INSTRUCTIONS

    names = load_workbook(delivered).sheetnames
    reorder(delivered, [INSTRUCTIONS, *[n for n in names if n != INSTRUCTIONS]])

    result = import_workbook(project, delivered)
    assert result.applied


# -- whitespace ---------------------------------------------------------


def test_a_translation_of_only_spaces_is_empty(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "   ", "", ""]]).save(path)

    read = read_workbook(path)
    assert read.rows[0].target == ""


def test_that_is_reported(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", "   ", "", ""]]).save(path)
    assert any("nothing but whitespace" in w for w in read_workbook(path).warnings)


def test_a_real_leading_space_is_kept(tmp_path):
    # Some of these strings are joined at run time and the space is what
    # separates them.
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Bar Height", " Balkenhöhe", "", ""]]).save(path)
    assert read_workbook(path).rows[0].target == " Balkenhöhe"


def test_a_real_trailing_space_is_kept(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["a.1", "Purge offset must be less than ",
                   "Bereinigungsversatz kleiner als ", "", ""]]).save(path)
    assert read_workbook(path).rows[0].target.endswith(" ")


def test_a_whitespace_only_row_is_dropped_entirely(tmp_path):
    path = tmp_path / "book.xlsx"
    make([HEADER, ["", "", "   ", "", ""]]).save(path)
    assert read_workbook(path).rows == []
