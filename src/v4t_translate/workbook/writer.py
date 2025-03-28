"""Writing the workbook a translator gets sent.

Three decisions in here are worth defending.

The source column is locked and the sheet is protected. Not to be difficult:
editing the source in the sheet has no effect whatsoever, the resource is the
source, and people did it and then asked why their change had not shipped.

The status column is a dropdown of the real states. Free text there came back
as "done", "DONE", "ok", "fertig" and "?" in one delivery.

The space budget is a column the translator can see. Telling someone after the
fact that their translation is nine pixels too wide is much worse than telling
them beforehand that they have room for about eleven characters.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet, TranslationState
from ..locales import Locale
from .instructions import write_instructions
from .schema import Column
from .styles import (
    COLUMN_WIDTHS,
    header_style,
    metadata_style,
    note_style,
    row_fill_for,
    source_style,
    target_style,
)

__all__ = ["WORKBOOK_COLUMNS", "write_workbook", "sheet_title_for"]

#: Column order in a generated sheet. Key first because it is what makes the
#: sheet round trip, and Source next to Translation because that is the pair
#: a person reads.
WORKBOOK_COLUMNS: tuple[str, ...] = (
    Column.KEY,
    Column.SOURCE,
    Column.TARGET,
    Column.STATUS,
    Column.NOTE,
    Column.LIMIT,
    Column.ORIGIN,
)

_STATUS_CHOICES = ",".join(state.value for state in TranslationState)

#: Excel refuses a sheet title longer than this, and silently truncates one
#: containing its reserved characters.
_TITLE_LIMIT = 31
_TITLE_FORBIDDEN = set(r"[]:*?/\\")


def sheet_title_for(project: str, locale: Locale) -> str:
    """A sheet name Excel will accept, derived from project and language."""
    raw = f"{project} {locale.tag}"
    cleaned = "".join("-" if c in _TITLE_FORBIDDEN else c for c in raw)
    return cleaned[:_TITLE_LIMIT].strip() or locale.tag


def write_workbook(
    path: Path | str,
    catalog: Catalog,
    translations: TranslationSet,
    locale: Locale,
    *,
    only_outstanding: bool = False,
    with_instructions: bool = True,
) -> int:
    """Write the sheet for one language. Returns how many rows it holds.

    ``only_outstanding`` drops everything already approved, which is what you
    send for a follow-up round. The key column is what lets the result be
    merged back into the full set.

    The instructions sheet goes second, so the translation sheet is the one
    that opens. Putting it first was tried and people closed the file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    book = Workbook()
    sheet = book.active
    sheet.title = sheet_title_for(catalog.project, locale)

    _write_header(sheet, locale)

    written = 0
    for key in catalog.sorted_keys():
        message = catalog.messages[key]
        translation = translations.get(key)

        if only_outstanding and translation.state is TranslationState.APPROVED:
            continue

        _write_row(sheet, written + 2, message, translation)
        written += 1

    _finish(sheet, written)

    if with_instructions:
        write_instructions(book, locale, catalog.project)

    book.save(path)
    return written


def _write_header(sheet, locale: Locale) -> None:
    for index, column in enumerate(WORKBOOK_COLUMNS, start=1):
        heading = locale.english_name if column == Column.TARGET else column
        cell = sheet.cell(row=1, column=index, value=heading)
        header_style(cell)
        sheet.column_dimensions[get_column_letter(index)].width = COLUMN_WIDTHS.get(
            column, 20
        )


def _write_row(sheet, row: int, message, translation) -> None:
    origin = message.primary_origin
    values = {
        Column.KEY: message.key,
        Column.SOURCE: message.source_text,
        Column.TARGET: translation.text,
        Column.STATUS: translation.state.value,
        Column.NOTE: _note_for(message, translation),
        Column.LIMIT: _limit_for(message),
        Column.ORIGIN: origin.describe() if origin else "",
    }

    fill = row_fill_for(translation.state.value, protected=message.protected)

    for index, column in enumerate(WORKBOOK_COLUMNS, start=1):
        cell = sheet.cell(row=row, column=index, value=values[column])

        if column == Column.SOURCE:
            source_style(cell, protected=message.protected)
        elif column == Column.TARGET:
            target_style(cell, protected=message.protected)
        elif column == Column.NOTE:
            note_style(cell)
        else:
            metadata_style(cell)

        if fill is not None and column != Column.SOURCE:
            cell.fill = fill


def _finish(sheet, rows: int) -> None:
    last_column = get_column_letter(len(WORKBOOK_COLUMNS))
    last_row = rows + 1

    sheet.freeze_panes = "C2"
    sheet.auto_filter.ref = f"A1:{last_column}{last_row}"

    if rows:
        status_index = WORKBOOK_COLUMNS.index(Column.STATUS) + 1
        letter = get_column_letter(status_index)
        validation = DataValidation(
            type="list",
            formula1=f'"{_STATUS_CHOICES}"',
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Not a status",
            error="Pick one of the listed states.",
        )
        sheet.add_data_validation(validation)
        validation.add(f"{letter}2:{letter}{last_row}")

    # Locked cells only bite once the sheet is protected. No password: this is
    # a guard rail, not a security measure, and a translator who really needs
    # to unprotect it should be able to.
    sheet.protection.sheet = True
    sheet.protection.enable()


def _note_for(message, translation) -> str:
    parts = [part for part in (message.developer_note, translation.note) if part]
    if message.protected:
        parts.insert(0, "Do not translate. This string ships unchanged.")
    return " ".join(parts)


def _limit_for(message) -> str:
    if message.max_chars:
        return f"{message.max_chars} chars"
    if message.max_width_px:
        lines = f" x{message.max_lines}" if message.max_lines > 1 else ""
        return f"{message.max_width_px}px{lines}"
    return ""
