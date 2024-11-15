"""How the generated workbook looks.

Appearance is not decoration here. A translator working through nine hundred
rows in Excel navigates by colour, and the two things they most need to see
without reading are "do not touch this row" and "this one changed since you
last looked".

Colours are chosen to survive being printed in greyscale and to be
distinguishable with the common forms of colour blindness, because one of the
people who does the German is red-green colour blind and said so.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side

__all__ = [
    "HEADER_FILL",
    "PROTECTED_FILL",
    "REVIEW_FILL",
    "DRAFT_FILL",
    "COLUMN_WIDTHS",
    "header_style",
    "source_style",
    "target_style",
    "row_fill_for",
]

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
PROTECTED_FILL = PatternFill("solid", fgColor="D9D9D9")
REVIEW_FILL = PatternFill("solid", fgColor="FFE699")
DRAFT_FILL = PatternFill("solid", fgColor="DEEBF7")

HEADER_FONT = Font(color="FFFFFF", bold=True)
SOURCE_FONT = Font(color="404040")
NOTE_FONT = Font(color="808080", italic=True)

_THIN = Side(style="thin", color="BFBFBF")
CELL_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

WRAP = Alignment(vertical="top", wrap_text=True)
NOWRAP = Alignment(vertical="top")

#: Widths in Excel's character units, per canonical column name.
COLUMN_WIDTHS: dict[str, int] = {
    "Key": 28,
    "Context": 14,
    "Source": 52,
    "Translation": 52,
    "Status": 14,
    "Note": 34,
    "Limit": 10,
    "Where": 38,
}

#: State to row fill. Anything not listed gets no fill at all, which is what
#: an approved row should look like: unremarkable.
_STATE_FILLS = {
    "needs-review": REVIEW_FILL,
    "draft": DRAFT_FILL,
}


def header_style(cell) -> None:
    cell.fill = HEADER_FILL
    cell.font = HEADER_FONT
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    cell.border = CELL_BORDER


def source_style(cell, *, protected: bool = False) -> None:
    """The source column. Locked, because editing it there does nothing."""
    cell.font = SOURCE_FONT
    cell.alignment = WRAP
    cell.border = CELL_BORDER
    cell.protection = Protection(locked=True)
    if protected:
        cell.fill = PROTECTED_FILL


def target_style(cell, *, protected: bool = False) -> None:
    """The one column a translator is meant to type in."""
    cell.alignment = WRAP
    cell.border = CELL_BORDER
    cell.protection = Protection(locked=protected)
    if protected:
        cell.fill = PROTECTED_FILL


def note_style(cell) -> None:
    cell.font = NOTE_FONT
    cell.alignment = WRAP
    cell.border = CELL_BORDER
    cell.protection = Protection(locked=True)


def metadata_style(cell) -> None:
    """Key, limit and origin. Read only and quiet."""
    cell.font = SOURCE_FONT
    cell.alignment = NOWRAP
    cell.border = CELL_BORDER
    cell.protection = Protection(locked=True)


def row_fill_for(state: str, *, protected: bool) -> PatternFill | None:
    """Background for a row in a given translation state."""
    if protected:
        return PROTECTED_FILL
    return _STATE_FILLS.get(state)
