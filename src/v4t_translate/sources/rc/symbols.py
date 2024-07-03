"""The ``resource.h`` symbol table.

A resource script refers to controls by name. The names live in a generated
header next to it, and the extractor needs them for two things: telling
``IDC_STATIC`` apart from a real control id, and writing an origin a developer
can grep for.

Values matter less than names here, but they are not free: ``IDC_STATIC`` is
-1 and every unlabelled static in the product shares it, so a symbol is not a
unique id and nothing downstream may assume it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ...errors import ParseError

__all__ = ["SymbolTable", "parse_resource_header", "load_resource_header", "STANDARD_IDS"]

#: Ids the resource compiler knows without a header. Extractions of files that
#: only use standard buttons still have to resolve these.
STANDARD_IDS: dict[str, int] = {
    "IDOK": 1,
    "IDCANCEL": 2,
    "IDABORT": 3,
    "IDRETRY": 4,
    "IDIGNORE": 5,
    "IDYES": 6,
    "IDNO": 7,
    "IDCLOSE": 8,
    "IDHELP": 9,
    "IDC_STATIC": -1,
}

#: Symbols that never name a control. A static label carries IDC_STATIC, and
#: so does every other static label in the file.
ANONYMOUS_SYMBOLS = frozenset({"IDC_STATIC", "-1", "65535"})

_DEFINE = re.compile(
    r"^\s*#\s*define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<body>.+?)\s*$"
)
_TRAILING_COMMENT = re.compile(r"(//.*|/\*.*?\*/)\s*$")
_SIMPLE_INT = re.compile(r"^[-+]?(0[xX][0-9a-fA-F]+|\d+)[uUlL]*$")
_ARITHMETIC = re.compile(r"^[\s()+\-*/0-9A-Za-z_xX]+$")


@dataclass
class SymbolTable:
    """Names to values, with the reverse lookup the writer needs."""

    values: dict[str, int] = field(default_factory=dict)
    origin: str | None = None

    #: Names that came from :data:`STANDARD_IDS` rather than from a header.
    #: A header is allowed to shadow these without it counting as a clash.
    _builtin: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        for name, value in STANDARD_IDS.items():
            if name not in self.values:
                self.values[name] = value
                self._builtin.add(name)

    def __contains__(self, name: object) -> bool:
        return name in self.values

    def __len__(self) -> int:
        return len(self.values)

    def get(self, name: str, default: int | None = None) -> int | None:
        return self.values.get(name, default)

    def define(self, name: str, value: int) -> None:
        """Record a symbol. A redefinition to the same value is fine and common."""
        existing = self.values.get(name)
        if existing is not None and existing != value and name not in self._builtin:
            raise ParseError(
                f"{name} is defined twice with different values ({existing} then {value})",
                path=self.origin,
            )
        self.values[name] = value
        self._builtin.discard(name)

    def names_for(self, value: int) -> list[str]:
        """Every symbol carrying ``value``, sorted so output is reproducible."""
        return sorted(name for name, held in self.values.items() if held == value)

    def is_anonymous(self, name: str) -> bool:
        """True when the symbol does not identify a specific control.

        ``IDC_STATIC`` is the usual case. So is a raw ``-1`` written in place
        of the symbol, which the dialog editor does when it feels like it.
        """
        if name in ANONYMOUS_SYMBOLS:
            return True
        return self.values.get(name) in (-1, 65535)


def parse_resource_header(text: str, *, path: str | None = None) -> SymbolTable:
    """Read ``#define`` lines out of a generated resource header.

    Everything that is not a define is ignored, including the conditional
    blocks the dialog editor writes around its bookkeeping values. Those blocks
    define ``_APS_NEXT_*`` symbols that no resource ever refers to, and reading
    them costs nothing, so we do not bother tracking ``#ifdef`` nesting.
    """
    table = SymbolTable(origin=path)

    for raw_line in text.splitlines():
        match = _DEFINE.match(raw_line)
        if match is None:
            continue

        name = match.group("name")
        body = _TRAILING_COMMENT.sub("", match.group("body")).strip()
        if not body:
            continue

        value = _evaluate(body, table)
        if value is None:
            continue

        table.define(name, value)

    return table


def load_resource_header(path: str | Path, *, encoding: str = "utf-8-sig") -> SymbolTable:
    """Read a resource header from disk.

    Visual Studio writes these as UTF-8 with a BOM more often than not, and
    occasionally as plain ANSI. Fall back rather than fail, since a header we
    cannot read costs the whole extraction.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252")
    return parse_resource_header(text, path=str(path))


def _evaluate(body: str, table: SymbolTable) -> int | None:
    """Resolve a define body to an int, or ``None`` when it is not a number.

    Handles the three forms that actually turn up: a literal, a reference to
    another symbol, and small arithmetic such as ``(IDC_PEN_BASE + 3)``. String
    and macro defines are skipped rather than treated as an error, because a
    resource header is allowed to contain them.
    """
    if _SIMPLE_INT.match(body):
        return int(body.rstrip("uUlL"), 0)

    if body in table.values:
        return table.values[body]

    if not _ARITHMETIC.match(body):
        return None

    expression = body
    for name in sorted(table.values, key=len, reverse=True):
        if name in expression:
            expression = re.sub(rf"\b{re.escape(name)}\b", str(table.values[name]), expression)

    if re.search(r"[A-Za-z_]", expression.replace("0x", "").replace("0X", "")):
        return None

    try:
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
    except (SyntaxError, NameError, TypeError, ZeroDivisionError):
        return None

    return result if isinstance(result, int) else None
