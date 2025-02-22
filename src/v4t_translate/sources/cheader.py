"""The V4T-Mini firmware string table.

The Mini has no resource system. Its strings live in a generated C header as
one array of pointers indexed by an enum, which is the right design for a part
with 48K of flash and the wrong one for anything that has to be edited by a
person.

Two initialiser styles are in the tree and both have to read::

    static const char * const lng_en[LNG_COUNT] = {
        [LNG_PRINT_STARTED]  = "Print started",   /* max 20 */
        [LNG_PURGE_SETTINGS] = "Purge Settings",
    };

    static const char * const lng_en[LNG_COUNT] = {
        "Print started",
        "Purge Settings",
    };

The designated form is what the generator writes now. The positional form is
what the older files still use, and there the enum order is the only thing
tying a string to its id, so the enum has to be read first and a count
mismatch is a hard error rather than a warning. Getting that pairing wrong
puts the purge confirmation on the print button.

``max`` in a trailing comment is the character budget for that string. The
Mini's LCD is twenty columns, but a string drawn inside a framed box has
fewer, and only the firmware knows which.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..catalog.ids import message_key
from ..catalog.model import Message, Origin, OriginKind
from ..errors import ParseError, SourceError
from .base import Extraction, SourceOptions

__all__ = ["CHeaderSource", "parse_enum", "parse_table", "TableEntry"]

_ENUM = re.compile(
    r"typedef\s+enum\s*\{(?P<body>.*?)\}\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;",
    re.DOTALL,
)

_TABLE = re.compile(
    r"(?:static\s+)?const\s+char\s*\*\s*const\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\[[^\]]*\]\s*=\s*\{(?P<body>.*?)\}\s*;",
    re.DOTALL,
)

_ENTRY = re.compile(
    r"(?:\[\s*(?P<id>[A-Za-z_][A-Za-z0-9_]*)\s*\]\s*=\s*)?"
    r"(?P<literal>\"(?:[^\"\\]|\\.)*\"(?:\s*\"(?:[^\"\\]|\\.)*\")*)"
    r"\s*,?"
    # Only a comment counts as the trailer. Matching to end of line instead
    # swallowed the next entry whenever a table was written on one line.
    r"(?P<trailer>[ \t]*(?:/\*.*?\*/|//[^\n]*)?)"
)

_MAX = re.compile(r"\bmax\s*[:=]?\s*(\d+)", re.IGNORECASE)

_LITERAL_PIECE = re.compile(r"\"((?:[^\"\\]|\\.)*)\"")

_C_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\",
    '"': '"', "'": "'", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
}


class TableEntry:
    """One row of a generated string table."""

    __slots__ = ("symbol", "text", "max_chars", "line")

    def __init__(self, symbol: str, text: str, max_chars: int | None, line: int) -> None:
        self.symbol = symbol
        self.text = text
        self.max_chars = max_chars
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TableEntry({self.symbol!r}, {self.text!r}, {self.max_chars})"


def parse_enum(text: str) -> list[str]:
    """Identifier order from the first ``typedef enum`` in the file.

    Explicit values are ignored. The enum is read for its order, and a table
    written positionally relies on nothing else.
    """
    match = _ENUM.search(text)
    if match is None:
        return []

    names: list[str] = []
    for raw in match.group("body").split(","):
        cleaned = re.sub(r"/\*.*?\*/", " ", raw, flags=re.DOTALL)
        cleaned = re.sub(r"//.*", " ", cleaned).strip()
        if not cleaned:
            continue
        name = cleaned.split("=")[0].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            names.append(name)
    return names


def parse_table(text: str, name: str, *, enum_order: list[str] | None = None,
                path: str | None = None) -> list[TableEntry]:
    """Read the table called ``name``."""
    match = _find_table(text, name)
    if match is None:
        raise ParseError(f"no string table called {name!r} in this header", path=path)

    body = match.group("body")
    body_line = text[: match.start("body")].count("\n") + 1

    entries: list[TableEntry] = []
    for index, entry in enumerate(_ENTRY.finditer(body)):
        symbol = entry.group("id")
        if symbol is None:
            symbol = _positional_symbol(enum_order, index, name, path)

        budget = _MAX.search(entry.group("trailer") or "")
        entries.append(
            TableEntry(
                symbol=symbol,
                text=_unescape(entry.group("literal")),
                max_chars=int(budget.group(1)) if budget else None,
                line=body_line + body[: entry.start()].count("\n"),
            )
        )

    return entries


class CHeaderSource:
    """Reader for the generated firmware string table."""

    kind = "cheader"

    #: Table the source strings live in. The generator always writes English
    #: into this one and the translations into lng_<tag> beside it.
    source_table = "lng_en"

    def extract(self, options: SourceOptions) -> Extraction:
        source = options.relative()
        extraction = Extraction(source=source)

        text = _read(options.path)
        enum_order = parse_enum(text)
        entries = parse_table(text, self.source_table, enum_order=enum_order, path=source)

        protected = [re.compile(p) for p in options.protected_patterns]

        for entry in entries:
            if not entry.text.strip():
                continue
            message = Message(
                key=message_key(entry.text),
                source_text=entry.text,
                origins=[Origin(source=source, kind=OriginKind.C_STRING_TABLE,
                                container=self.source_table, symbol=entry.symbol,
                                line=entry.line)],
                protected=any(p.fullmatch(entry.text) for p in protected),
                max_chars=entry.max_chars,
            )
            extraction.messages.append(message)

        extraction.stats = {
            "enum_ids": len(enum_order),
            "entries": len(entries),
            "messages": len(extraction.by_key()),
        }

        if enum_order and len(entries) != len(_expected(enum_order)):
            extraction.warn(
                f"{source}: enum declares {len(_expected(enum_order))} ids and the "
                f"table has {len(entries)} entries"
            )

        return extraction


def _find_table(text: str, name: str):
    for match in _TABLE.finditer(text):
        if match.group("name") == name:
            return match
    return None


def _expected(enum_order: list[str]) -> list[str]:
    """Enum ids that are real strings, dropping the trailing count sentinel."""
    return [n for n in enum_order if not n.endswith("_COUNT")]


def _positional_symbol(enum_order: list[str] | None, index: int, table: str,
                       path: str | None) -> str:
    names = _expected(enum_order or [])
    if not names:
        raise ParseError(
            f"{table} is written positionally and there is no enum to pair it with",
            path=path,
        )
    if index >= len(names):
        raise ParseError(
            f"{table} has more entries than the enum has ids, so the pairing is "
            f"wrong from entry {index + 1} onward",
            path=path,
        )
    return names[index]


def _unescape(literal: str) -> str:
    """Join adjacent C literals and resolve their escapes."""
    out: list[str] = []
    for piece in _LITERAL_PIECE.findall(literal):
        index = 0
        while index < len(piece):
            char = piece[index]
            if char != "\\":
                out.append(char)
                index += 1
                continue
            index += 1
            if index >= len(piece):
                out.append("\\")
                break
            escape = piece[index]
            if escape == "x":
                index += 1
                digits = ""
                while (index < len(piece) and len(digits) < 2
                       and piece[index] in "0123456789abcdefABCDEF"):
                    digits += piece[index]
                    index += 1
                out.append(chr(int(digits, 16)) if digits else "x")
                continue
            out.append(_C_ESCAPES.get(escape, escape))
            index += 1
    return "".join(out)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise SourceError(f"{path} does not exist") from exc
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252")
