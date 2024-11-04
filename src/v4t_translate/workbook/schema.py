"""Working out what the columns of a workbook mean.

Two shapes have to be readable.

The sheets already delivered are two columns: an English heading and a
language heading that says whatever the person who built the sheet felt like
typing. "Taiwan". "German". No key, no context, no status. Those still come
back from translators and dropping them would mean retyping nine hundred
rows.

The sheets this tool writes carry a key, the source, the target, a status, a
note and the constraint. They also come back with the columns moved, renamed
and occasionally sorted, because it is a spreadsheet and people use it like
one. So nothing is found by position. Everything is found by heading, and the
heading match is loose on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import WorkbookError
from ..locales import Locale, lookup

__all__ = ["Column", "SheetSchema", "detect_schema", "HEADINGS"]


class Column:
    """Canonical column names. These are what the writer emits."""

    KEY = "Key"
    CONTEXT = "Context"
    SOURCE = "Source"
    TARGET = "Translation"
    STATUS = "Status"
    NOTE = "Note"
    LIMIT = "Limit"
    ORIGIN = "Where"


#: Headings we accept for each column, lowered. The target column is not here
#: because it is matched against the locale table instead.
HEADINGS: dict[str, tuple[str, ...]] = {
    Column.KEY: ("key", "id", "message id", "msgid"),
    Column.CONTEXT: ("context", "disambiguation", "sense"),
    Column.SOURCE: ("source", "english", "source text", "en", "en-us", "original"),
    Column.STATUS: ("status", "state", "review"),
    Column.NOTE: ("note", "notes", "comment", "comments", "translator note"),
    Column.LIMIT: ("limit", "max", "max width", "budget", "space"),
    Column.ORIGIN: ("where", "origin", "location", "found in", "dialog"),
}

_BY_HEADING: dict[str, str] = {}
for _column, _aliases in HEADINGS.items():
    for _alias in _aliases:
        _BY_HEADING[_alias] = _column
del _column, _aliases, _alias


@dataclass
class SheetSchema:
    """Where each column is in one sheet."""

    columns: dict[str, int] = field(default_factory=dict)
    """Canonical column name to zero-based index."""

    locale: Locale | None = None
    """The language the target column holds."""

    target_heading: str = ""
    """The heading as written, so the writer can keep it if asked to."""

    header_row: int = 1
    """One-based row the headings were on."""

    @property
    def legacy(self) -> bool:
        """True when the sheet has no key column and has to be matched on text."""
        return Column.KEY not in self.columns

    def index(self, column: str) -> int | None:
        return self.columns.get(column)

    def has(self, column: str) -> bool:
        return column in self.columns

    def describe(self) -> str:
        ordered = sorted(self.columns.items(), key=lambda item: item[1])
        return ", ".join(f"{name}@{index + 1}" for name, index in ordered)


def detect_schema(header: list[object], *, sheet: str = "", row: int = 1) -> SheetSchema:
    """Work out the schema from a header row.

    The source column must be found and exactly one target language column
    must be found. Everything else is optional, because the delivered sheets
    do not have it and this has to read those.
    """
    schema = SheetSchema(header_row=row)
    target_candidates: list[tuple[int, str, Locale]] = []

    for index, raw in enumerate(header):
        heading = _clean(raw)
        if not heading:
            continue

        canonical = _BY_HEADING.get(heading)
        if canonical is not None and canonical not in schema.columns:
            schema.columns[canonical] = index
            continue

        locale = lookup(heading)
        if locale is not None and locale.tag != "en-US":
            target_candidates.append((index, str(raw).strip(), locale))

    where = f"{sheet}: " if sheet else ""

    if Column.SOURCE not in schema.columns:
        raise WorkbookError(
            f"{where}no source column. Expected one headed "
            f"{' or '.join(HEADINGS[Column.SOURCE][:3])}"
        )

    if not target_candidates:
        raise WorkbookError(
            f"{where}no target language column. One heading has to name a language, "
            f"for example German or zh-TW"
        )

    if len(target_candidates) > 1:
        names = ", ".join(f"{heading!r}" for _, heading, _ in target_candidates)
        raise WorkbookError(
            f"{where}several target language columns ({names}). "
            f"One sheet holds one language"
        )

    index, heading, locale = target_candidates[0]
    schema.columns[Column.TARGET] = index
    schema.locale = locale
    schema.target_heading = heading
    return schema


def _clean(value: object) -> str:
    """Normalise a heading cell for matching."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    # Sheets come back with a trailing colon, a footnote marker or a line
    # break in the heading often enough to be worth handling.
    text = text.replace("\n", " ").replace("*", "").rstrip(":")
    return " ".join(text.split())
