"""The third sheet: the terms that are already decided.

The glossary rule reports a term used wrongly, and reporting it is the last
possible moment. By then somebody has translated four hundred strings using
Feder and every one of them comes back as a finding, which is a bad afternoon
for them and a bad email from us.

The terms have been decided since before the round started. They belong in the
file the work is done in, on a sheet next to it, not in a CSV in a repository
that half the people filling these in have never had an account on.

Three columns, and the third is the one nobody else ships. Along with the
agreed term it lists the ones that were rejected, because a decision is more
than the word that won: somebody spent an afternoon settling that a pen is a
Stift and not a Feder, and without the second half written down the next
person reaches for Feder again.

Only this language's terms. A German translator does not need the Chinese
column and a sheet with eleven columns is a sheet nobody scrolls.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from ..glossary import Glossary, Term

__all__ = ["SHEET_TITLE", "COLUMNS", "write_glossary", "rows_for"]

SHEET_TITLE = "Agreed terms"

COLUMNS: tuple[str, ...] = ("English", "Use this", "Not this", "Why")

#: Widths in Excel's own units, chosen against the real term list.
_WIDTHS = (24, 30, 30, 60)

_HEADING = Font(bold=True, size=10)
_BODY = Font(size=10)
_KEPT = "leave it in English"


def rows_for(glossary: Glossary, tag: str) -> list[tuple[str, str, str, str]]:
    """The rows for one language, in English alphabetical order.

    Alphabetical by the English rather than by the translation, because the
    English is the column somebody scans when they are looking a word up.
    """
    terms = glossary.for_locale(tag)
    return [_row(terms[key]) for key in sorted(terms)]


def _row(term: Term) -> tuple[str, str, str, str]:
    return (
        term.term,
        _KEPT if term.keep_source else term.translation,
        ", ".join(term.forbidden),
        term.note,
    )


def write_glossary(book, glossary: Glossary, tag: str) -> int:
    """Add the agreed terms sheet. Returns the row count.

    No sheet at all when there are no terms for this language. An empty sheet
    headed "Agreed terms" reads as "nothing has been agreed", which is not the
    same thing as "nobody has written them down yet" and is the wrong one to
    imply.
    """
    rows = rows_for(glossary, tag)
    if not rows:
        return 0

    sheet = book.create_sheet(SHEET_TITLE)

    for column, name in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = _HEADING

    for number, values in enumerate(rows, start=2):
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=number, column=column, value=value)
            cell.font = _BODY
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for column, width in enumerate(_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width

    sheet.freeze_panes = "A2"
    sheet.protection.sheet = True
    sheet.protection.enable()

    return len(rows)
