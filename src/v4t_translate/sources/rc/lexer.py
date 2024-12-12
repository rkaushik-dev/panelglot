"""Lexer for Win32 resource scripts.

Reads the token stream a resource script is made of. It is deliberately more
forgiving than ``rc.exe``: this tool has to survive files that are mid-edit,
and a lexer that stops at the first oddity is useless for that.

The one thing it will not paper over is an unterminated string literal, which
is almost always a real mistake and which silently swallows the rest of the
file if you let it through.
"""

from __future__ import annotations

from ...errors import ParseError
from .tokens import Token, TokenKind

__all__ = ["tokenize", "unescape_rc_string"]

_SIMPLE_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "?": "?",
}

_PUNCTUATION = {
    ",": TokenKind.COMMA,
    "|": TokenKind.PIPE,
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "{": TokenKind.BEGIN,
    "}": TokenKind.END,
}

_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_BODY = _IDENT_START | set("0123456789")
_DIGITS = set("0123456789")


class _Cursor:
    """Position tracking that keeps line and column honest across newlines."""

    def __init__(self, text: str, path: str | None) -> None:
        self.text = text
        self.path = path
        self.pos = 0
        self.line = 1
        self.column = 1

    def at_end(self) -> bool:
        return self.pos >= len(self.text)

    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.text[index] if index < len(self.text) else ""

    def advance(self, count: int = 1) -> str:
        taken = self.text[self.pos : self.pos + count]
        for char in taken:
            if char == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
        self.pos += len(taken)
        return taken

    def fail(self, message: str, *, line: int | None = None, column: int | None = None):
        return ParseError(
            message,
            path=self.path,
            line=self.line if line is None else line,
            column=self.column if column is None else column,
        )


def tokenize(text: str, *, path: str | None = None) -> list[Token]:
    """Turn resource script text into a token list.

    Comments and whitespace are dropped. Preprocessor lines survive as a
    single :attr:`~.TokenKind.DIRECTIVE` token holding the whole line, because
    the parser only cares that they exist, not what they say.
    """
    cursor = _Cursor(text, path)
    tokens: list[Token] = []

    while not cursor.at_end():
        char = cursor.peek()

        if char in " \t\r\n\f\v":
            cursor.advance()
            continue

        if char == "/" and cursor.peek(1) == "/":
            _skip_line_comment(cursor)
            continue

        if char == "/" and cursor.peek(1) == "*":
            _skip_block_comment(cursor)
            continue

        if char == "#" and cursor.column == 1:
            tokens.append(_read_directive(cursor))
            continue

        if char == '"':
            tokens.append(_read_string(cursor))
            continue

        if char in "Ll" and cursor.peek(1) == '"':
            # Wide literal. The L is a storage hint, not part of the text, but
            # it is part of the span so a rewrite keeps the prefix.
            prefix = cursor.pos
            cursor.advance()
            tokens.append(_read_string(cursor, start=prefix))
            continue

        if char in _IDENT_START:
            tokens.append(_read_identifier(cursor))
            continue

        if char in _DIGITS:
            tokens.append(_read_number(cursor))
            continue

        kind = _PUNCTUATION.get(char)
        if kind is not None:
            line, column, start = cursor.line, cursor.column, cursor.pos
            cursor.advance()
            tokens.append(Token(kind, char, line, column, start=start, end=cursor.pos))
            continue

        raise cursor.fail(f"unexpected character {char!r}")

    tokens.append(
        Token(TokenKind.EOF, "", cursor.line, cursor.column,
              start=cursor.pos, end=cursor.pos)
    )
    return tokens


def _skip_line_comment(cursor: _Cursor) -> None:
    while not cursor.at_end() and cursor.peek() != "\n":
        cursor.advance()


def _skip_block_comment(cursor: _Cursor) -> None:
    start_line, start_column = cursor.line, cursor.column
    cursor.advance(2)
    while True:
        if cursor.at_end():
            raise cursor.fail("unterminated block comment", line=start_line, column=start_column)
        if cursor.peek() == "*" and cursor.peek(1) == "/":
            cursor.advance(2)
            return
        cursor.advance()


def _read_directive(cursor: _Cursor) -> Token:
    line, column, start = cursor.line, cursor.column, cursor.pos
    chars: list[str] = []
    while not cursor.at_end():
        char = cursor.peek()
        if char == "\n":
            break
        if char == "\\" and cursor.peek(1) in ("\n", "\r"):
            # Continued directive. Keep reading, drop the backslash.
            cursor.advance()
            while cursor.peek() in ("\r", "\n"):
                cursor.advance()
            chars.append(" ")
            continue
        chars.append(cursor.advance())
    return Token(TokenKind.DIRECTIVE, "".join(chars).strip(), line, column,
                 start=start, end=cursor.pos)


def _read_identifier(cursor: _Cursor) -> Token:
    line, column, start = cursor.line, cursor.column, cursor.pos
    chars: list[str] = []
    while not cursor.at_end() and cursor.peek() in _IDENT_BODY:
        chars.append(cursor.advance())
    word = "".join(chars)
    upper = word.upper()
    if upper == "BEGIN":
        kind = TokenKind.BEGIN
    elif upper == "END":
        kind = TokenKind.END
    else:
        kind = TokenKind.IDENT
    return Token(kind, word, line, column, start=start, end=cursor.pos)


def _read_number(cursor: _Cursor) -> Token:
    line, column, start = cursor.line, cursor.column, cursor.pos
    chars: list[str] = []
    if cursor.peek() == "0" and cursor.peek(1) in "xX":
        chars.append(cursor.advance())
        chars.append(cursor.advance())
        while not cursor.at_end() and cursor.peek() in "0123456789abcdefABCDEF":
            chars.append(cursor.advance())
        text = "".join(chars)
        return Token(TokenKind.NUMBER, text, line, column, value=int(text, 16),
                     start=start, end=cursor.pos)

    while not cursor.at_end() and cursor.peek() in _DIGITS:
        chars.append(cursor.advance())
    # Resource scripts write suffixed integers such as 40001L in a few places.
    while not cursor.at_end() and cursor.peek() in "lLuU":
        cursor.advance()
    text = "".join(chars)
    return Token(TokenKind.NUMBER, text, line, column, value=int(text),
                 start=start, end=cursor.pos)


def _read_string(cursor: _Cursor, *, start: int | None = None) -> Token:
    line, column = cursor.line, cursor.column
    if start is None:
        start = cursor.pos
    else:
        # A wide literal's L was already consumed, so the column has moved on.
        column -= 1
    cursor.advance()  # opening quote
    raw: list[str] = []

    while True:
        if cursor.at_end():
            raise cursor.fail("unterminated string literal", line=line, column=column)

        char = cursor.peek()

        if char == '"':
            if cursor.peek(1) == '"':
                # Doubled quote is how a resource script escapes one quote.
                cursor.advance(2)
                raw.append('""')
                continue
            cursor.advance()
            break

        if char == "\\":
            raw.append(cursor.advance())
            if cursor.at_end():
                raise cursor.fail("unterminated string literal", line=line, column=column)
            raw.append(cursor.advance())
            continue

        if char == "\n":
            raise cursor.fail("newline inside string literal", line=line, column=column)

        raw.append(cursor.advance())

    text = "".join(raw)
    return Token(TokenKind.STRING, text, line, column,
                 value=unescape_rc_string(text), start=start, end=cursor.pos)


def unescape_rc_string(raw: str) -> str:
    """Resolve resource-script escapes in the body of a string literal.

    ``raw`` is the text between the quotes, quotes excluded. Two conventions
    live side by side and both have to work: C escapes (``\\n``, ``\\t``,
    ``\\x41``, ``\\101``) and the doubled quote (``""``).

    The ampersand is left alone. ``&&`` means a literal ampersand and a lone
    ``&`` marks the mnemonic, but both matter to the translator, so they stay
    in the message and are handled by the mnemonic rule instead.
    """
    out: list[str] = []
    index = 0
    length = len(raw)

    while index < length:
        char = raw[index]

        if char == '"' and index + 1 < length and raw[index + 1] == '"':
            out.append('"')
            index += 2
            continue

        if char != "\\":
            out.append(char)
            index += 1
            continue

        index += 1
        if index >= length:
            out.append("\\")
            break

        esc = raw[index]

        if esc in "xX":
            index += 1
            digits = ""
            while index < length and len(digits) < 4 and raw[index] in "0123456789abcdefABCDEF":
                digits += raw[index]
                index += 1
            if not digits:
                out.append("x")
                continue
            out.append(chr(int(digits, 16)))
            continue

        if esc in "01234567":
            digits = ""
            while index < length and len(digits) < 3 and raw[index] in "01234567":
                digits += raw[index]
                index += 1
            out.append(chr(int(digits, 8)))
            continue

        replacement = _SIMPLE_ESCAPES.get(esc)
        if replacement is not None:
            out.append(replacement)
        else:
            # rc.exe drops the backslash and keeps the character for anything
            # it does not recognise. Matching that is safer than guessing.
            out.append(esc)
        index += 1

    return "".join(out)
