"""Numbers that were typed into a string, rather than substituted into it.

A placeholder is somebody else's problem: the placeholder rule owns those, and
a formatter puts a locale-correct number into them at run time. This rule is
about the ones a developer wrote by hand, which nothing formats and nobody
converts.

There are more of them than there should be. "Maximum 8 pens", "Set 0 to
disable", "Firing voltage 12.4V" and about forty others across the family, and
every one is a number a translator can quietly change, drop, or leave in the
English convention.

Two failures, and they are not equally bad.

Changing the value is an error. "Maximum 8 pens" coming back as "Maximum 6"
is a specification, and the operator believes it.

Writing 12.4 where the language writes 12,4 is a warning. Nothing breaks, but
a German operator reads a decimal point as a thousands mark for about a
second, and that is a second on a machine with a purge button.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from ..layout.measure import drawn_text
from ..locales import Locale
from .base import RuleContext, finding
from .placeholders import find_placeholders
from .result import Finding, Severity

__all__ = ["NumberRule", "literal_numbers", "normalise_number"]

#: A number as a person would write one, with an optional separated fraction.
#: Grouping marks are matched so "1.250" is one number and not two.
#:
#: A letter immediately before the digits means this is an identifier rather
#: than a quantity: V4T, RS232, TIJ8PEN. A letter immediately after does not,
#: because that is how a unit is written: 12.4V, 8mm, 250ms.
_NUMBER = re.compile(r"(?<![A-Za-z_])\d+(?:[., ٫٬ ]\d+)*")

#: Strings where a run of digits is an identifier rather than a quantity, and
#: converting it would be wrong. Version numbers and date format tokens.
_NOT_A_QUANTITY = re.compile(
    r"\b\d+\.\d+\.\d+"          # 4.1.0
    r"|\b(?:19|20)\d{2}\b"      # a year
    r"|\bRS-?\d{3}\b",          # RS-232, RS485
    re.IGNORECASE,
)


def literal_numbers(text: str) -> list[str]:
    """Numbers written into ``text``, with placeholders removed first.

    Placeholders go first because ``%.1f`` contains a 1 and ``%02d`` contains
    an 02, and reporting those as missing numbers would bury everything real.
    """
    stripped = drawn_text(text)
    for placeholder in find_placeholders(stripped):
        stripped = stripped.replace(placeholder.text, " ", 1)

    stripped = _NOT_A_QUANTITY.sub(" ", stripped)
    return _NUMBER.findall(stripped)


def normalise_number(text: str, locale: Locale) -> str:
    """Strip a number down to the digits, so two conventions compare equal."""
    out = text
    if locale.group_separator:
        out = out.replace(locale.group_separator, "")
    for separator in (",", ".", " ", " ", "٫", "٬"):
        out = out.replace(separator, "")
    return out


class NumberRule:
    """Literal numbers survive, and are written the way the language writes them."""

    name = "numbers"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        source = literal_numbers(message.source_text)
        if not source:
            yield from self._check_invented(message, translation, context)
            return

        target = literal_numbers(translation.text)

        yield from self._check_values(message, translation, context, source, target)
        yield from self._check_convention(message, translation, context, target)

    def _check_values(self, message: Message, translation: Translation,
                      context: RuleContext, source: list[str],
                      target: list[str]) -> Iterable[Finding]:
        wanted = sorted(normalise_number(n, context.locale) for n in source)
        got = sorted(normalise_number(n, context.locale) for n in target)

        if wanted == got:
            return

        missing = _difference(wanted, got)
        extra = _difference(got, wanted)

        if missing:
            yield finding(
                self, context, message, translation,
                f"the number {_listed(missing)} is in the English and not in the "
                f"translation",
                detail=f"The English says {', '.join(source)}. A number a "
                       f"developer wrote is a specification and the operator "
                       f"believes it.",
            )

        if extra:
            yield finding(
                self, context, message, translation,
                f"the translation has the number {_listed(extra)} and the English "
                f"does not",
                detail=f"The English says {', '.join(source) or 'no number'}.",
            )

    def _check_convention(self, message: Message, translation: Translation,
                          context: RuleContext, target: list[str]) -> Iterable[Finding]:
        wrong = [
            number for number in target
            if _uses_the_wrong_mark(number, context.locale)
        ]
        if not wrong:
            return

        example = context.locale.format_number(12.4)
        yield finding(
            self, context, message, translation,
            f"{_listed(wrong)} is written in the English convention",
            detail=f"{context.locale.english_name} writes {example}. Nothing "
                   f"breaks, but the operator reads it wrong for a moment.",
            severity=Severity.WARNING,
        )

    def _check_invented(self, message: Message, translation: Translation,
                        context: RuleContext) -> Iterable[Finding]:
        target = literal_numbers(translation.text)
        if not target:
            return

        yield finding(
            self, context, message, translation,
            f"the translation has the number {_listed(target)} and the English "
            f"has none",
        )


def _uses_the_wrong_mark(number: str, locale: Locale) -> bool:
    """True when a decimal fraction is written with the wrong separator."""
    if locale.decimal_separator == ".":
        return False

    # A trailing group of exactly three digits after a dot is a thousands
    # mark in most conventions and a decimal in none of the ones here, so it
    # is left alone rather than guessed at.
    match = re.search(r"\.(\d+)$", number)
    if match is None:
        return False
    return len(match.group(1)) != 3


def _difference(left: list[str], right: list[str]) -> list[str]:
    """Multiset difference, keeping order."""
    remaining = list(right)
    out: list[str] = []
    for item in left:
        if item in remaining:
            remaining.remove(item)
        else:
            out.append(item)
    return out


def _listed(numbers: list[str]) -> str:
    return ", ".join(numbers) if len(numbers) > 1 else numbers[0]
