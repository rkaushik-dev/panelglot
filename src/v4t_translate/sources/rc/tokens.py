"""Token types for the resource script lexer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    """What a token is.

    ``BEGIN`` and ``END`` cover both spellings. Visual Studio writes
    ``BEGIN``/``END``, hand-edited blocks and anything that came through a
    C preprocessor tend to use braces, and both appear in V4T.rc.
    """

    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    BEGIN = auto()
    END = auto()
    COMMA = auto()
    PIPE = auto()
    PLUS = auto()
    MINUS = auto()
    LPAREN = auto()
    RPAREN = auto()
    DIRECTIVE = auto()
    EOF = auto()

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Token:
    """One lexed token, with enough position to report a useful error."""

    kind: TokenKind
    text: str
    line: int
    column: int

    #: Parsed value. A string token carries its unescaped contents here, a
    #: number token carries an int, everything else carries ``None``.
    value: str | int | None = None

    def is_ident(self, *names: str) -> bool:
        """True when this is an identifier matching one of ``names``, case-insensitively.

        Resource keywords are conventionally upper case but the compiler does
        not insist, and V4T.rc has at least one ``Pushbutton`` in it.
        """
        return self.kind is TokenKind.IDENT and self.text.upper() in {n.upper() for n in names}

    def __str__(self) -> str:
        return f"{self.kind}({self.text!r}) at {self.line}:{self.column}"


#: Statements that introduce a top-level resource. The lexer does not care,
#: but the parser needs one shared list and this is the natural home for it.
RESOURCE_KEYWORDS = frozenset(
    {
        "DIALOG",
        "DIALOGEX",
        "MENU",
        "MENUEX",
        "STRINGTABLE",
        "ACCELERATORS",
        "VERSIONINFO",
        "TOOLBAR",
        "BITMAP",
        "ICON",
        "CURSOR",
        "FONT",
        "RCDATA",
        "MESSAGETABLE",
        "TEXTINCLUDE",
        "DESIGNINFO",
        "HTML",
        "AFX_DIALOG_LAYOUT",
    }
)

#: Dialog control statements whose first argument is a caption we must translate.
#: Anything not in here either has no caption or carries one we must leave alone.
CAPTIONED_CONTROLS = frozenset(
    {
        "PUSHBUTTON",
        "DEFPUSHBUTTON",
        "LTEXT",
        "RTEXT",
        "CTEXT",
        "GROUPBOX",
        "CHECKBOX",
        "AUTOCHECKBOX",
        "RADIOBUTTON",
        "AUTORADIOBUTTON",
        "AUTO3STATE",
        "STATE3",
        "PUSHBOX",
    }
)

#: Control statements whose first argument is a resource id, never text.
#: Listing them explicitly means an unknown statement gets reported rather
#: than silently skipped.
UNCAPTIONED_CONTROLS = frozenset(
    {
        "EDITTEXT",
        "COMBOBOX",
        "LISTBOX",
        "SCROLLBAR",
        "ICON",
    }
)

#: ``CONTROL`` is its own case. Its first argument is a caption for a button
#: or a static, and a bitmap or icon id for everything else, so the parser has
#: to look at the token rather than the statement name.
GENERIC_CONTROL = "CONTROL"
