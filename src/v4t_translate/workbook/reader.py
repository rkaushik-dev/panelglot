"""Reading a translator's workbook back in.

Everything here is defence. A sheet that has been round a distributor, opened
in three versions of Excel and pasted into from Word is not a data file, and
treating it like one loses work.

The cases that actually turn up:

Excel decides a cell is a number. "4." comes back as the float 4.0 and would
be written into a resource as "4.0". "1E5" becomes 100000.0. Anything that
looks like a date becomes a datetime.

Word paste brings non-breaking spaces and typographic quotes. The non-breaking
space is invisible, does not match the source, and encodes fine, so nothing
downstream notices.

Rows get sorted, so a legacy sheet cannot be matched by position. Rows get
duplicated by a careless fill-down, and the two copies disagree.

And the header is not always in row 1, because somebody added a title.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from ..errors import WorkbookError
from ..locales import Locale
from .schema import Column, SheetSchema, detect_schema

__all__ = ["WorkbookRow", "WorkbookRead", "read_workbook", "clean_cell", "HEADER_SEARCH_ROWS"]

#: How far down to look for the header row before giving up.
HEADER_SEARCH_ROWS = 10

#: Characters that arrive from a word processor and are never wanted.
_SUBSTITUTIONS = {
    " ": " ",   # non-breaking space
    " ": " ",   # figure space
    " ": " ",   # narrow no-break space
    "﻿": "",    # byte order mark pasted into a cell
    "​": "",    # zero width space
}


@dataclass
class WorkbookRow:
    """One row of a translator's sheet, cleaned."""

    row: int
    source: str
    target: str
    key: str = ""
    context: str = ""
    status: str = ""
    note: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.source or self.target)


@dataclass
class WorkbookRead:
    """Everything read out of one sheet."""

    path: str
    sheet: str
    locale: Locale
    schema: SheetSchema
    rows: list[WorkbookRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def legacy(self) -> bool:
        return self.schema.legacy

    def translated(self) -> list[WorkbookRow]:
        return [row for row in self.rows if row.target]

    def by_key(self) -> dict[str, WorkbookRow]:
        return {row.key: row for row in self.rows if row.key}

    def by_source(self) -> dict[str, WorkbookRow]:
        """Rows keyed on source text, for sheets that have no key column."""
        return {row.source: row for row in self.rows if row.source}


def clean_cell(value: object) -> str:
    """Turn whatever openpyxl handed back into the string that was meant.

    The number cases matter more than they look. A resource string of "4."
    read as a float and written back as "4.0" changes what the panel shows,
    and it is the kind of change nobody reviews.
    """
    if value is None:
        return ""

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        # Excel stores every number as a float. An integral one was almost
        # certainly typed without a decimal point.
        return str(int(value)) if value.is_integer() else repr(value)

    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()

    text = str(value)
    for bad, good in _SUBSTITUTIONS.items():
        text = text.replace(bad, good)

    text = unicodedata.normalize("NFC", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_workbook(path: Path | str, *, sheet: str | None = None) -> WorkbookRead:
    """Read one sheet of a translator's workbook."""
    path = Path(path)
    if not path.exists():
        raise WorkbookError(f"{path} does not exist")

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a zoo of types here
        raise WorkbookError(f"{path} could not be opened: {exc}") from exc

    try:
        worksheet = _pick_sheet(book, path, sheet)
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
        title = worksheet.title
    finally:
        book.close()

    schema, header_index = _find_header(rows, path=str(path), sheet=title)
    assert schema.locale is not None  # detect_schema guarantees it

    read = WorkbookRead(path=str(path), sheet=title, locale=schema.locale, schema=schema)
    _collect(read, rows, header_index, schema)
    _warn_about_duplicates(read)
    return read


def _pick_sheet(book, path: Path, wanted: str | None):
    if wanted is None:
        return book.worksheets[0]
    for worksheet in book.worksheets:
        if worksheet.title == wanted:
            return worksheet
    names = ", ".join(w.title for w in book.worksheets)
    raise WorkbookError(f"{path} has no sheet named {wanted!r}. It has: {names}")


def _find_header(rows: list[list[object]], *, path: str,
                 sheet: str) -> tuple[SheetSchema, int]:
    """Find the header row, allowing for a title above it."""
    last_error: WorkbookError | None = None

    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if not any(cell is not None and str(cell).strip() for cell in row):
            continue
        try:
            return detect_schema(row, sheet=sheet, row=index + 1), index
        except WorkbookError as exc:
            last_error = exc

    if last_error is not None:
        raise WorkbookError(f"{path}: {last_error}")
    raise WorkbookError(f"{path}: {sheet} is empty")


def _collect(read: WorkbookRead, rows: list[list[object]], header_index: int,
             schema: SheetSchema) -> None:
    for offset, raw in enumerate(rows[header_index + 1:], start=header_index + 2):
        row = WorkbookRow(
            row=offset,
            source=_cell(raw, schema, Column.SOURCE),
            target=_cell(raw, schema, Column.TARGET),
            key=_cell(raw, schema, Column.KEY),
            context=_cell(raw, schema, Column.CONTEXT),
            status=_cell(raw, schema, Column.STATUS),
            note=_cell(raw, schema, Column.NOTE),
        )
        if row.is_empty:
            continue
        if not row.source and not row.key:
            read.warnings.append(
                f"row {offset}: a translation with no source and no key, ignored"
            )
            continue
        read.rows.append(row)


def _cell(raw: list[object], schema: SheetSchema, column: str) -> str:
    index = schema.index(column)
    if index is None or index >= len(raw):
        return ""
    return clean_cell(raw[index]).strip() if column != Column.TARGET else clean_cell(raw[index])


def _warn_about_duplicates(read: WorkbookRead) -> None:
    """A fill-down that duplicated a row, where the copies disagree."""
    seen: dict[str, WorkbookRow] = {}
    for row in read.rows:
        identity = row.key or row.source
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = row
            continue
        if previous.target != row.target:
            read.warnings.append(
                f"rows {previous.row} and {row.row} both answer {identity!r} and "
                f"disagree: {previous.target!r} then {row.target!r}. Later wins"
            )
        seen[identity] = row
