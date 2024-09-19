"""Placeholder parity.

The single most expensive class of translation defect, because it does not
show up as bad text. ``%s`` where the code passes an int reads a pointer off
the stack and the HMI closes itself, and it does it on a customer's line at
three in the morning, not in test.

Three notations are in play and they have different rules.

Plain printf specifiers are positional by order. ``%d of %s`` translated as
``%s von %d`` compiles, runs, and crashes, so order is part of the contract.

Explicitly numbered printf specifiers (``%1$s``) carry their own position, so
they may be reordered freely. German needs this for anything with a number
and a unit in it.

The ``<V1>`` tokens the V4T dialogs use are substituted by name before the
string ever reaches a formatter, so those may be reordered and only the set
matters. They may not be invented or dropped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from ..catalog.model import Message
from ..catalog.translations import Translation
from .base import RuleContext, finding
from .result import Finding, Severity

__all__ = ["Placeholder", "find_placeholders", "PlaceholderRule"]

# %[argnum$][flags][width][.precision][length]conversion
_PRINTF = re.compile(
    r"%(?:(?P<argnum>\d+)\$)?"
    r"(?P<flags>[-+ #0']*)"
    r"(?P<width>\d+|\*)?"
    r"(?:\.(?P<precision>\d+|\*))?"
    r"(?P<length>hh|h|ll|l|L|z|j|t)?"
    r"(?P<conversion>[diouxXeEfFgGaAcspn%])"
)

_NAMED = re.compile(r"<(?P<name>V\d+|[A-Z][A-Z0-9_]{1,15})>")

_BRACED = re.compile(r"\{(?P<name>\d+|[a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass(frozen=True)
class Placeholder:
    """One substitution point found in a string."""

    text: str
    """Exactly as it appears, so a report can quote it."""

    kind: str
    """``printf``, ``named`` or ``braced``."""

    index: int
    """Position in the string, used to compare order."""

    positional: bool = False
    """True when the placeholder states its own argument number."""

    @property
    def order_matters(self) -> bool:
        """Whether moving this one changes which value lands in it."""
        return self.kind == "printf" and not self.positional

    def normalized(self) -> str:
        """The form two placeholders must share to be interchangeable.

        Width and flags are cosmetic: ``%5d`` and ``%d`` consume the same
        argument, and a translator widening a field is not a defect. The
        conversion and the length modifier are not cosmetic at all.
        """
        if self.kind != "printf":
            return self.text
        match = _PRINTF.fullmatch(self.text)
        if match is None:  # pragma: no cover - _PRINTF produced it
            return self.text
        return f"%{match.group('length') or ''}{match.group('conversion')}"


def find_placeholders(text: str) -> list[Placeholder]:
    """Every substitution point in ``text``, in the order they appear.

    ``%%`` is a literal percent sign and is not a placeholder, so it is
    skipped rather than reported as one.
    """
    found: list[Placeholder] = []

    for match in _PRINTF.finditer(text):
        if match.group("conversion") == "%":
            continue
        found.append(
            Placeholder(
                text=match.group(0),
                kind="printf",
                index=match.start(),
                positional=match.group("argnum") is not None,
            )
        )

    for match in _NAMED.finditer(text):
        found.append(Placeholder(text=match.group(0), kind="named", index=match.start()))

    for match in _BRACED.finditer(text):
        found.append(Placeholder(text=match.group(0), kind="braced", index=match.start()))

    found.sort(key=lambda p: p.index)
    return found


class PlaceholderRule:
    """Every placeholder in the source appears in the translation, and no others."""

    name = "placeholders"
    default_severity = Severity.ERROR

    def check(self, message: Message, translation: Translation,
              context: RuleContext) -> Iterable[Finding]:
        if not translation.text:
            return

        source = find_placeholders(message.source_text)
        target = find_placeholders(translation.text)

        if not source and not target:
            return

        yield from self._compare_sets(message, translation, context, source, target)
        yield from self._compare_order(message, translation, context, source, target)

    def _compare_sets(self, message, translation, context, source, target
                      ) -> Iterable[Finding]:
        source_counts = Counter(p.normalized() for p in source)
        target_counts = Counter(p.normalized() for p in target)

        missing = source_counts - target_counts
        extra = target_counts - source_counts

        if missing:
            yield finding(
                self, context, message, translation,
                f"translation is missing {_quote(missing)}",
                detail=f"source has {_quote(source_counts)}, "
                       f"translation has {_quote(target_counts) or 'none'}",
            )

        if extra:
            yield finding(
                self, context, message, translation,
                f"translation has {_quote(extra)} that the source does not",
                detail=f"source has {_quote(source_counts) or 'none'}, "
                       f"translation has {_quote(target_counts)}",
            )

    def _compare_order(self, message, translation, context, source, target
                       ) -> Iterable[Finding]:
        source_order = [p.normalized() for p in source if p.order_matters]
        target_order = [p.normalized() for p in target if p.order_matters]

        if source_order == target_order:
            return
        if sorted(source_order) != sorted(target_order):
            # The set check already said so; reporting the order as well would
            # be two findings for one mistake.
            return

        yield finding(
            self, context, message, translation,
            "placeholders are reordered and are not numbered, so the arguments "
            "will not line up",
            detail=f"source order {' '.join(source_order)}, "
                   f"translation order {' '.join(target_order)}. "
                   f"Use %1$s style if the order has to change.",
        )


def _quote(counts: Counter[str] | dict[str, int]) -> str:
    parts: list[str] = []
    for text, count in sorted(counts.items()):
        parts.append(f"{text} x{count}" if count > 1 else text)
    return ", ".join(parts)
