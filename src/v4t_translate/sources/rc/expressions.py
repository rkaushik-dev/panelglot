"""Evaluating the small integer expressions a resource header contains.

``#define IDC_PEN_2 (IDC_PEN_BASE + 1)`` and about six shapes like it. The
first version of this substituted the symbol values into the string and
handed it to ``eval`` with an empty builtins dict.

That worked and it should not have been written. ``resource.h`` is a file this
tool is pointed at, and on a build machine it is pointed at whatever the
checkout contains. An empty builtins dict is not a sandbox: everything reachable
from a literal is still reachable, and the guard that kept letters out of the
expression was a regex that had already needed two fixes.

So this is a real parser. It is forty lines, it handles exactly the C operators
that turn up in a generated header, and there is nothing in it that can run.

Grammar, lowest precedence first::

    expression := bitor
    bitor      := bitxor ('|' bitxor)*
    bitxor     := bitand ('^' bitand)*
    bitand     := shift ('&' shift)*
    shift      := additive (('<<' | '>>') additive)*
    additive   := term (('+' | '-') term)*
    term       := unary (('*' | '/' | '%') unary)*
    unary      := ('+' | '-' | '~')* primary
    primary    := NUMBER | IDENT | '(' expression ')'
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["evaluate_expression", "ExpressionError"]


class ExpressionError(ValueError):
    """The text is not an integer expression this can evaluate.

    Deliberately not a :class:`~v4t_translate.errors.V4TError`. A header is
    allowed to contain defines that are not integers, and the caller treats
    this as "skip that line" rather than as a failure.
    """


_TOKENS = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<hex>0[xX][0-9a-fA-F]+[uUlL]*)
  | (?P<dec>\d+[uUlL]*)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<shift><<|>>)
  | (?P<op>[-+*/%|^&~()])
    """,
    re.VERBOSE,
)

#: The U and L suffixes a C integer literal may carry. Stripped per literal
#: rather than off the end of the whole expression, because (IDC_BASE + 3L)
#: is a real line in one of the headers.
_INT_SUFFIX = re.compile(r"[uUlL]+$")


@dataclass
class _Token:
    kind: str
    text: str


def _lex(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0

    while position < len(text):
        match = _TOKENS.match(text, position)
        if match is None:
            raise ExpressionError(f"unexpected character {text[position]!r}")
        position = match.end()

        kind = match.lastgroup or ""
        if kind == "space":
            continue
        tokens.append(_Token(kind, match.group()))

    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token], symbols: dict[str, int]) -> None:
        self.tokens = tokens
        self.symbols = symbols
        self.index = 0

    def peek(self) -> str:
        return self.tokens[self.index].text if self.index < len(self.tokens) else ""

    def take(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, *texts: str) -> str | None:
        if self.peek() in texts:
            return self.take().text
        return None

    def parse(self) -> int:
        value = self.bitor()
        if self.index != len(self.tokens):
            raise ExpressionError(f"trailing {self.peek()!r}")
        return value

    def bitor(self) -> int:
        value = self.bitxor()
        while self.accept("|"):
            value |= self.bitxor()
        return value

    def bitxor(self) -> int:
        value = self.bitand()
        while self.accept("^"):
            value ^= self.bitand()
        return value

    def bitand(self) -> int:
        value = self.shift()
        while self.accept("&"):
            value &= self.shift()
        return value

    def shift(self) -> int:
        value = self.additive()
        while True:
            operator = self.accept("<<", ">>")
            if operator is None:
                return value
            right = self.additive()
            if right < 0 or right > 63:
                raise ExpressionError(f"shift by {right}")
            value = value << right if operator == "<<" else value >> right

    def additive(self) -> int:
        value = self.term()
        while True:
            operator = self.accept("+", "-")
            if operator is None:
                return value
            right = self.term()
            value = value + right if operator == "+" else value - right

    def term(self) -> int:
        value = self.unary()
        while True:
            operator = self.accept("*", "/", "%")
            if operator is None:
                return value
            right = self.unary()
            if operator in ("/", "%") and right == 0:
                raise ExpressionError("division by zero")
            if operator == "*":
                value *= right
            elif operator == "/":
                # C truncates toward zero; Python floors. On a resource header
                # every value is positive so it never shows, but getting it
                # wrong here would be a silent off by one somewhere else.
                value = int(value / right)
            else:
                value = abs(value) % abs(right) * (1 if value >= 0 else -1)

    def unary(self) -> int:
        operator = self.accept("+", "-", "~")
        if operator is None:
            return self.primary()
        value = self.unary()
        if operator == "-":
            return -value
        if operator == "~":
            return ~value
        return value

    def primary(self) -> int:
        if self.index >= len(self.tokens):
            raise ExpressionError("expression ends early")

        token = self.take()

        if token.text == "(":
            value = self.bitor()
            if self.accept(")") is None:
                raise ExpressionError("unclosed bracket")
            return value

        if token.kind == "hex":
            return int(_INT_SUFFIX.sub("", token.text), 16)

        if token.kind == "dec":
            return int(_INT_SUFFIX.sub("", token.text))

        if token.kind == "ident":
            if token.text in self.symbols:
                return self.symbols[token.text]
            raise ExpressionError(f"unknown symbol {token.text!r}")

        raise ExpressionError(f"unexpected {token.text!r}")


def evaluate_expression(text: str, symbols: dict[str, int]) -> int:
    """Evaluate ``text`` against ``symbols``. Raises :class:`ExpressionError`."""
    stripped = text.strip()
    if not stripped:
        raise ExpressionError("empty expression")

    return _Parser(_lex(stripped), symbols).parse()
