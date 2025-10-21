import shutil

import pytest
from openpyxl import Workbook, load_workbook

from v4t_translate.config import load_config
from v4t_translate.glossary import Glossary, Term
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.sync import export_workbooks
from v4t_translate.workbook.glossary import (
    COLUMNS,
    SHEET_TITLE,
    rows_for,
    write_glossary,
)

CONFIG = """
[project]
name = "V4T-TIJ"
glossary = "glossary/terms.csv"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."fr-FR"]
"""

TERMS = """\
term,locale,translation,forbidden,note
pen,de-DE,Stift,feder;patrone,Settled 2024-03.
barcode,de-DE,Barcode,strichcode,Stays English by agreement.
V4T,de-DE,=,,Product name.
"""


def glossary():
    return Glossary([
        Term(term="pen", locale="de-DE", translation="Stift",
             forbidden=("feder", "patrone"), note="Settled 2024-03."),
        Term(term="barcode", locale="de-DE", translation="Barcode"),
        Term(term="V4T", locale="de-DE", translation="="),
        Term(term="pen", locale="zh-TW", translation="筆"),
    ])


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "glossary").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "glossary" / "terms.csv").write_text(TERMS, encoding="utf-8")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def sheet_of(path, title=SHEET_TITLE):
    book = load_workbook(path)
    return book[title] if title in book.sheetnames else None


# -- the rows -----------------------------------------------------------


def test_only_this_language_appears():
    # Eleven columns is a sheet nobody scrolls.
    english = [row[0] for row in rows_for(glossary(), "de-DE")]
    assert "pen" in english
    assert len(english) == 3


def test_the_rows_are_alphabetical_by_the_english():
    # The English is the column somebody scans when looking a word up, and it
    # is shown as it was written rather than as it is keyed.
    assert [row[0] for row in rows_for(glossary(), "de-DE")] == [
        "barcode", "pen", "V4T"
    ]


def test_the_agreed_term_is_in_the_second_column():
    rows = {row[0]: row for row in rows_for(glossary(), "de-DE")}
    assert rows["pen"][1] == "Stift"


def test_a_do_not_translate_term_says_so_in_words():
    rows = {row[0]: row for row in rows_for(glossary(), "de-DE")}
    assert rows["V4T"][1] == "leave it in English"


def test_the_rejected_ones_get_their_own_column():
    # A decision is more than the word that won.
    rows = {row[0]: row for row in rows_for(glossary(), "de-DE")}
    assert rows["pen"][2] == "feder, patrone"


def test_a_term_with_nothing_rejected_has_an_empty_column():
    rows = {row[0]: row for row in rows_for(glossary(), "de-DE")}
    assert rows["barcode"][2] == ""


def test_the_note_comes_through():
    rows = {row[0]: row for row in rows_for(glossary(), "de-DE")}
    assert rows["pen"][3] == "Settled 2024-03."


def test_a_language_with_no_terms_has_no_rows():
    assert rows_for(glossary(), "fr-FR") == []


def test_there_are_four_columns():
    assert len(COLUMNS) == 4
    assert all(len(row) == len(COLUMNS) for row in rows_for(glossary(), "de-DE"))


# -- the sheet ----------------------------------------------------------


def test_the_sheet_is_added(tmp_path):
    book = Workbook()
    assert write_glossary(book, glossary(), "de-DE") == 3
    assert SHEET_TITLE in book.sheetnames


def test_no_sheet_when_nothing_is_agreed(tmp_path):
    # An empty sheet headed "Agreed terms" reads as "nothing has been agreed",
    # which is not the same as "nobody has written them down yet".
    book = Workbook()
    assert write_glossary(book, glossary(), "fr-FR") == 0
    assert SHEET_TITLE not in book.sheetnames


def test_the_headings_are_written(tmp_path):
    book = Workbook()
    write_glossary(book, glossary(), "de-DE")
    sheet = book[SHEET_TITLE]
    assert [sheet.cell(row=1, column=n + 1).value for n in range(4)] == list(COLUMNS)


def test_the_header_row_is_frozen(tmp_path):
    book = Workbook()
    write_glossary(book, glossary(), "de-DE")
    assert book[SHEET_TITLE].freeze_panes == "A2"


def test_the_sheet_is_protected(tmp_path):
    # Nothing on it is for typing in.
    book = Workbook()
    write_glossary(book, glossary(), "de-DE")
    assert book[SHEET_TITLE].protection.sheet


def test_every_column_has_a_width(tmp_path):
    from openpyxl.utils import get_column_letter

    book = Workbook()
    write_glossary(book, glossary(), "de-DE")
    sheet = book[SHEET_TITLE]
    for column in range(1, 5):
        assert sheet.column_dimensions[get_column_letter(column)].width > 0


# -- through the export -------------------------------------------------


def test_the_export_carries_the_terms(project):
    result = export_workbooks(project, locales=["de-DE"])
    sheet = sheet_of(result.written[0][1])
    assert sheet is not None
    assert sheet.cell(row=2, column=1).value == "barcode"


def test_a_language_with_no_terms_gets_no_sheet(project):
    result = export_workbooks(project, locales=["fr-FR"])
    assert sheet_of(result.written[0][1]) is None


def test_the_translation_sheet_is_still_first(project):
    result = export_workbooks(project, locales=["de-DE"])
    book = load_workbook(result.written[0][1])
    assert book.sheetnames[0] != SHEET_TITLE
    assert book.sheetnames[0].startswith("V4T-TIJ")


def test_the_instructions_are_still_there(project):
    from v4t_translate.workbook.instructions import SHEET_TITLE as INSTRUCTIONS

    result = export_workbooks(project, locales=["de-DE"])
    assert INSTRUCTIONS in load_workbook(result.written[0][1]).sheetnames


def test_a_project_with_no_glossary_still_exports(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(
        CONFIG.replace('glossary = "glossary/terms.csv"\n', ""), encoding="utf-8")

    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)

    result = export_workbooks(config, locales=["de-DE"])
    assert sheet_of(result.written[0][1]) is None


def test_every_part_of_a_split_gets_the_terms(project):
    result = export_workbooks(project, locales=["de-DE"], parts=2)
    for _, path, _ in result.written:
        assert sheet_of(path) is not None
