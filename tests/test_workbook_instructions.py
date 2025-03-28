import pytest
from openpyxl import load_workbook

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import TranslationSet, TranslationState
from v4t_translate.locales import resolve
from v4t_translate.workbook.instructions import SHEET_TITLE, lines_for
from v4t_translate.workbook.reader import read_workbook
from v4t_translate.workbook.writer import write_workbook


@pytest.fixture
def catalog():
    catalog = Catalog(project="V4T-TIJ")
    catalog.add(Message(key="a.1", source_text="Bar Height", max_width_px=54))
    catalog.add(Message(key="b.2", source_text="Width", max_width_px=30))
    return catalog


def text_of(locale, project="V4T-TIJ"):
    return "\n".join(
        f"{heading} {body}" for heading, body in lines_for(resolve(locale), project)
    )


def test_the_project_and_language_are_named():
    assert "V4T-TIJ, German" in text_of("de-DE")


def test_every_state_is_explained():
    body = text_of("de-DE")
    for state in TranslationState:
        assert state.value in body


def test_the_mechanics_are_there():
    body = text_of("de-DE")
    assert "only one you type in" in body
    assert "crashes the printer" in body
    assert "<V1>" in body
    assert "Alt+P" in body
    assert "not drawn at all" in body


def test_a_single_byte_language_is_told_about_its_codepage():
    body = text_of("de-DE")
    assert "codepage 1252" in body
    assert "question mark" in body


def test_turkish_gets_its_own_codepage_number():
    assert "codepage 1254" in text_of("tr-TR")


def test_a_double_byte_language_is_told_about_the_font_subset():
    body = text_of("zh-TW")
    assert "font is a subset" in body
    assert "draws as a blank" in body
    assert "codepage" not in body


def test_a_double_byte_language_is_told_full_width_punctuation_is_fine():
    assert "Full width punctuation" in text_of("zh-TW")


def test_a_right_to_left_language_is_told_about_the_mark():
    body = text_of("he-IL")
    assert "U+200F" in body
    assert "far end of the line" in body


def test_a_left_to_right_language_is_not():
    assert "U+200F" not in text_of("de-DE")


def test_the_sheet_is_written_second(tmp_path, catalog):
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))

    book = load_workbook(path)
    assert book.sheetnames[1] == SHEET_TITLE
    assert book.sheetnames[0] != SHEET_TITLE


def test_the_translation_sheet_is_the_active_one(tmp_path, catalog):
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))
    assert load_workbook(path).active.title != SHEET_TITLE


def test_the_instructions_sheet_is_locked(tmp_path, catalog):
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))
    assert load_workbook(path)[SHEET_TITLE].protection.sheet


def test_the_content_reaches_the_sheet(tmp_path, catalog):
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))

    sheet = load_workbook(path)[SHEET_TITLE]
    body = "\n".join(
        str(cell.value or "")
        for row in sheet.iter_rows()
        for cell in row
    )
    assert "crashes the printer" in body


def test_reading_the_workbook_back_still_finds_the_translation_sheet(tmp_path, catalog):
    # The reader takes the first sheet, and the instructions sheet has no
    # source column, so putting it first would break every import.
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))
    assert len(read_workbook(path)) == 2


def test_the_instructions_can_be_left_out(tmp_path, catalog):
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"),
                   with_instructions=False)
    assert SHEET_TITLE not in load_workbook(path).sheetnames


def test_columns_are_wide_enough_to_read(tmp_path, catalog):
    path = tmp_path / "german.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))
    sheet = load_workbook(path)[SHEET_TITLE]
    assert sheet.column_dimensions["A"].width >= 40
    assert sheet.column_dimensions["B"].width >= 80
