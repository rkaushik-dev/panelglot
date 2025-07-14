"""Which strings are behind a preprocessor conditional.

``V4T.rc`` builds four products out of one file. The eight-pen offsets page is
inside ``#ifdef V4T_8PEN``, the mainland variant hides three dialogs behind
``#ifndef V4T_EXPORT``, and none of that is visible in the parse tree because
the parser reads the file the way ``rc.exe`` would with nothing defined.

Two things follow. A build for the base product was sending translators the
eight-pen strings, which is forty rows nobody needed. And a translator had no
way to know that "Pen 5" only exists on one product, which is exactly the
context that stops somebody wondering whether it is a mistake.

So conditions are tracked per line. A project says what it defines, and a
string behind a condition that is definitely false is left out. A string
behind one this cannot decide is kept, with the condition in its note: being
told about a string that will not ship is a nuisance, and silently dropping
one that will is a defect.

Only the forms a resource script actually uses are understood: ``#ifdef``,
``#ifndef``, ``#if defined(X)``, ``#if !defined(X)``, ``#else``, ``#elif``
and ``#endif``. Anything else makes the block undecidable, which is the safe
answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Condition", "ConditionMap", "collect_conditions"]

_DIRECTIVE = re.compile(
    r"^\s*#\s*(?P<word>ifdef|ifndef|if|elif|else|endif)\b(?P<rest>.*)$"
)

_DEFINED = re.compile(r"^\s*(?P<not>!)?\s*defined\s*\(\s*(?P<name>\w+)\s*\)\s*$")
_BARE = re.compile(r"^\s*(?P<not>!)?\s*(?P<name>\w+)\s*$")

#: Symbols the dialog editor writes around its own bookkeeping. They are
#: never defined in a real build and the blocks behind them hold no text, so
#: they are treated as false rather than as undecidable.
EDITOR_SYMBOLS = frozenset({"APSTUDIO_INVOKED", "APSTUDIO_READONLY_SYMBOLS"})


@dataclass(frozen=True)
class Condition:
    """One ``#ifdef`` and whether it was negated."""

    symbol: str
    negated: bool = False

    def describe(self) -> str:
        return f"!{self.symbol}" if self.negated else self.symbol

    def holds(self, symbols: dict[str, bool]) -> bool | None:
        """True, False, or ``None`` when the symbol is not one we were told about."""
        present = symbols.get(self.symbol)
        if present is None:
            return None
        return not present if self.negated else present


@dataclass
class ConditionMap:
    """The conditions in force on each line."""

    by_line: dict[int, tuple[Condition | None, ...]] = field(default_factory=dict)

    def at(self, line: int) -> tuple[Condition | None, ...]:
        return self.by_line.get(line, ())

    def is_live(self, line: int, symbols: dict[str, bool]) -> bool:
        """False only when a condition on this line is definitely not met.

        ``symbols`` maps a name to whether the project defines it. A name it
        does not mention is undecidable, and undecidable means live: being
        told about a string that will not ship is a nuisance, and silently
        dropping one that will is a defect.
        """
        return all(_holds(condition, symbols) for condition in self.at(line))

    def symbols_used(self) -> set[str]:
        """Every symbol any condition in this file mentions.

        Used by doctor to point out a define the project sets that the file
        does not use, which is usually a typo in one or the other.
        """
        return {
            condition.symbol
            for conditions in self.by_line.values()
            for condition in conditions
            if condition is not None
        }

    def describe(self, line: int) -> str:
        """The conditions on a line, for a translator's note."""
        named = [c.describe() for c in self.at(line) if c is not None]
        return " and ".join(named)

    def __len__(self) -> int:
        return len(self.by_line)


def _holds(condition: Condition | None, symbols: dict[str, bool]) -> bool:
    """Whether one condition lets the line through.

    Three answers collapsed into two. An editor symbol is decided as never
    defined. A symbol the project mentions is decided both ways. Anything
    else is unknown, and unknown lets the line through.
    """
    if condition is None:
        return True

    if condition.symbol in EDITOR_SYMBOLS:
        return condition.negated

    verdict = condition.holds(symbols)
    return True if verdict is None else verdict


def collect_conditions(text: str) -> ConditionMap:
    """Walk the preprocessor directives and record what covers each line.

    ``None`` in a line's tuple means a condition that could not be read: an
    ``#else``, or an ``#if`` with an expression this does not understand.
    Those are kept as markers so the nesting depth stays right, and they never
    make a line dead.
    """
    result = ConditionMap()
    stack: list[Condition | None] = []

    for number, raw in enumerate(text.splitlines(), start=1):
        match = _DIRECTIVE.match(raw)

        if match is None:
            if stack:
                result.by_line[number] = tuple(stack)
            continue

        word = match.group("word")
        rest = match.group("rest")

        if word == "endif":
            if stack:
                stack.pop()
            continue

        if word in ("else", "elif"):
            # The other branch of whatever is open. Not decidable either way
            # without evaluating the first, which is more than this needs.
            if stack:
                stack[-1] = None
            continue

        stack.append(_parse(word, rest))

    return result


def _parse(word: str, rest: str) -> Condition | None:
    text = rest.split("//")[0].split("/*")[0].strip()

    if word == "ifdef":
        return Condition(text) if text.isidentifier() else None

    if word == "ifndef":
        return Condition(text, negated=True) if text.isidentifier() else None

    match = _DEFINED.match(text) or _BARE.match(text)
    if match is None:
        return None

    name = match.group("name")
    if not name.isidentifier() or name.isdigit():
        return None

    return Condition(name, negated=bool(match.group("not")))
