import shutil

import pytest
from click.testing import CliRunner
from openpyxl import load_workbook

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.locales import resolve
from v4t_translate.ops.extract import extract_project
from v4t_translate.workbook.styles import CHANGED_FILL, PROTECTED_FILL, REVIEW_FILL
from v4t_translate.workbook.writer import write_workbook

CONFIG = """
[project]
name = "V4T-TIJ"
workbook_dir = "Translate"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def origin(container="IDD_BARCODE", symbol="IDC_STATIC", line=26):
    return Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                  container=container, symbol=symbol, line=line)


def catalog_of(*messages):
    catalog = Catalog(project="V4T-TIJ")
    for message in messages:
        catalog.add(message)
    return catalog


def msg(text, **kw):
    kw.setdefault("origins", [origin()])
    return Message(key=message_key(text), source_text=text, **kw)


def sheet_of(path):
    return load_workbook(path).active


def row_for(sheet, key):
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == key:
            return row
    raise AssertionError(f"{key} is not in the sheet")


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def test_without_a_previous_catalog_nothing_is_marked(tmp_path):
    catalog = catalog_of(msg("Bar Height", max_width_px=54))
    path = tmp_path / "a.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))

    sheet = sheet_of(path)
    row = row_for(sheet, message_key("Bar Height"))
    assert sheet.cell(row=row, column=3).fill.fgColor.rgb != CHANGED_FILL.fgColor.rgb


def test_a_new_row_is_marked(tmp_path):
    before = catalog_of(msg("Bar Height", max_width_px=54))
    after = catalog_of(msg("Bar Height", max_width_px=54), msg("Module size"))

    path = tmp_path / "a.xlsx"
    write_workbook(path, after, TranslationSet(locale="de-DE"), resolve("de-DE"),
                   previous=before)

    sheet = sheet_of(path)
    new = row_for(sheet, message_key("Module size"))
    old = row_for(sheet, message_key("Bar Height"))
    assert sheet.cell(row=new, column=3).fill.fgColor.rgb == CHANGED_FILL.fgColor.rgb
    assert sheet.cell(row=old, column=3).fill.fgColor.rgb != CHANGED_FILL.fgColor.rgb


def test_a_row_whose_control_shrank_is_marked(tmp_path):
    before = catalog_of(msg("Bar Height", max_width_px=90))
    after = catalog_of(msg("Bar Height", max_width_px=54))

    path = tmp_path / "a.xlsx"
    write_workbook(path, after, TranslationSet(locale="de-DE"), resolve("de-DE"),
                   previous=before)

    sheet = sheet_of(path)
    row = row_for(sheet, message_key("Bar Height"))
    assert sheet.cell(row=row, column=3).fill.fgColor.rgb == CHANGED_FILL.fgColor.rgb


def test_a_row_whose_line_budget_changed_is_marked(tmp_path):
    before = catalog_of(msg("Hint", max_width_px=90, max_lines=3))
    after = catalog_of(msg("Hint", max_width_px=90, max_lines=1))

    path = tmp_path / "a.xlsx"
    write_workbook(path, after, TranslationSet(locale="de-DE"), resolve("de-DE"),
                   previous=before)
    sheet = sheet_of(path)
    row = row_for(sheet, message_key("Hint"))
    assert sheet.cell(row=row, column=3).fill.fgColor.rgb == CHANGED_FILL.fgColor.rgb


def test_protected_beats_changed(tmp_path):
    before = catalog_of()
    after = catalog_of(msg("mm", protected=True))

    path = tmp_path / "a.xlsx"
    write_workbook(path, after, TranslationSet(locale="de-DE"), resolve("de-DE"),
                   previous=before)

    sheet = sheet_of(path)
    row = row_for(sheet, message_key("mm"))
    assert sheet.cell(row=row, column=3).fill.fgColor.rgb == PROTECTED_FILL.fgColor.rgb


def test_changed_beats_the_state_fill(tmp_path):
    before = catalog_of()
    after = catalog_of(msg("Bar Height"))

    entries = TranslationSet(locale="de-DE")
    entries.set(message_key("Bar Height"),
                Translation(text="Balkenhöhe", state=TranslationState.NEEDS_REVIEW))

    path = tmp_path / "a.xlsx"
    write_workbook(path, after, entries, resolve("de-DE"), previous=before)

    sheet = sheet_of(path)
    row = row_for(sheet, message_key("Bar Height"))
    fill = sheet.cell(row=row, column=3).fill.fgColor.rgb
    assert fill == CHANGED_FILL.fgColor.rgb
    assert fill != REVIEW_FILL.fgColor.rgb


def test_the_source_cell_carries_a_comment(tmp_path):
    catalog = catalog_of(msg("Bar Height"))
    path = tmp_path / "a.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))

    sheet = sheet_of(path)
    comment = sheet.cell(row=row_for(sheet, message_key("Bar Height")), column=2).comment
    assert comment is not None
    assert "IDD_BARCODE" in comment.text


def test_the_comment_lists_several_origins(tmp_path):
    message = msg("OK", origins=[origin(container=f"IDD_{n}") for n in range(6)])
    path = tmp_path / "a.xlsx"
    write_workbook(path, catalog_of(message), TranslationSet(locale="de-DE"),
                   resolve("de-DE"))

    sheet = sheet_of(path)
    comment = sheet.cell(row=row_for(sheet, message.key), column=2).comment
    assert "and 2 more places" in comment.text


def test_the_comment_says_where_the_last_answer_came_from(tmp_path):
    entries = TranslationSet(locale="de-DE")
    entries.set(message_key("Bar Height"),
                Translation(text="Balkenhöhe", state=TranslationState.APPROVED,
                            origin="round-3.xlsx", updated="2025-05-01"))

    path = tmp_path / "a.xlsx"
    write_workbook(path, catalog_of(msg("Bar Height")), entries, resolve("de-DE"))

    sheet = sheet_of(path)
    comment = sheet.cell(row=row_for(sheet, message_key("Bar Height")), column=2).comment
    assert "round-3.xlsx" in comment.text
    assert "2025-05-01" in comment.text


def test_the_comment_says_when_a_row_changed(tmp_path):
    before = catalog_of()
    after = catalog_of(msg("Bar Height"))

    path = tmp_path / "a.xlsx"
    write_workbook(path, after, TranslationSet(locale="de-DE"), resolve("de-DE"),
                   previous=before)

    sheet = sheet_of(path)
    comment = sheet.cell(row=row_for(sheet, message_key("Bar Height")), column=2).comment
    assert "since the last round" in comment.text


def test_a_message_with_nothing_to_say_gets_no_comment(tmp_path):
    catalog = catalog_of(Message(key="bare.1", source_text="Bare"))
    path = tmp_path / "a.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))
    assert sheet_of(path).cell(row=2, column=2).comment is None


def test_comments_survive_a_read_back(tmp_path):
    from v4t_translate.workbook.reader import read_workbook

    catalog = catalog_of(msg("Bar Height"))
    path = tmp_path / "a.xlsx"
    write_workbook(path, catalog, TranslationSet(locale="de-DE"), resolve("de-DE"))
    assert len(read_workbook(path)) == 1


def test_the_command_line_since(project, tmp_path):
    saved = tmp_path / "old.json"
    shutil.copy(project.catalog_path(), saved)

    source = project.root / "src" / "V4T.rc"
    source.write_text(
        source.read_text(encoding="utf-8").replace('"Module size"', '"Module width"'),
        encoding="utf-8",
    )
    extract_project(project)

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "export", "-l", "de-DE", "--since", str(saved),
    ])
    assert result.exit_code == 0

    sheet = sheet_of(project.workbook_path("de-DE"))
    changed = [
        row for row in range(2, sheet.max_row + 1)
        if sheet.cell(row=row, column=3).fill.fgColor.rgb == CHANGED_FILL.fgColor.rgb
    ]
    assert len(changed) == 1
    assert sheet.cell(row=changed[0], column=2).value == "Module width"
