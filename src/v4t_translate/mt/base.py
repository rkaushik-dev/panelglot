"""What a machine translation provider looks like.

Providers are handed a batch and return a batch. One call per string is what
the original collector did, and against nine hundred strings it took four
minutes and produced a different answer for the same English on two different
days.

Every provider promises the same three things:

the returned list is the same length as the one it was given, in the same
order, so the caller can pair them by index without matching on text;

placeholders come back intact, because a provider that helpfully translates
``%s`` has produced a crash rather than a translation;

and nothing is guessed for a string the provider cannot handle. An empty
result is a fine answer and is better than a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..locales import Locale

__all__ = [
    "ProviderResult",
    "Provider",
    "protect_placeholders",
    "restore_placeholders",
]

#: Everything that must survive a provider untouched. Matches the placeholder
#: rule's notion, plus the escape sequences a caption can carry.
_PROTECTED = re.compile(
    r"%[-+ #0-9.]*[hlL]?[sdfixXeEgGcpu%]"
    r"|<V\d+>"
    r"|\{[0-9a-zA-Z_]+\}"
    r"|\\[nrt]"
)

#: Placeholder stand-in. Doubled brackets rather than a bare number, because a
#: bare number cannot be told apart from one that was already in the string,
#: and this product's strings are full of them. ASCII rather than a private
#: use codepoint because several engines drop those without saying so.
_TOKEN_PATTERN = re.compile(r"\[\[\s*(\d+)\s*\]\]")


def _token(index: int) -> str:
    return f"[[{index}]]"


@dataclass
class ProviderResult:
    """One provider call."""

    texts: list[str] = field(default_factory=list)
    """Same length and order as the input. An empty string means no answer."""

    provider: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def answered(self) -> int:
        return sum(1 for text in self.texts if text)


@runtime_checkable
class Provider(Protocol):
    """A machine translation backend."""

    name: str

    def translate(self, texts: list[str], source: Locale,
                  target: Locale) -> ProviderResult:
        """Translate a batch. Never raises for one bad string; returns empty."""
        ...


def protect_placeholders(text: str) -> tuple[str, list[str]]:
    """Replace placeholders with opaque tokens before sending text out.

    An engine given "Please input from %.1fV to %.1fV." comes back with
    anything from the specifier preserved, to "%.1F v", to the specifier
    rendered as words. Sending tokens instead removes the question.
    """
    found: list[str] = []

    def swap(match: re.Match[str]) -> str:
        found.append(match.group(0))
        return _token(len(found) - 1)

    return _PROTECTED.sub(swap, text), found


def restore_placeholders(text: str, placeholders: list[str]) -> str:
    """Put the placeholders back.

    A token the provider invented, or one whose index is past the end of the
    list, is dropped rather than left in the string. Leaving it would ship
    ``[[3]]`` onto a panel, which is worse than a missing placeholder that the
    placeholder rule will catch anyway.
    """
    def swap(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return placeholders[index] if index < len(placeholders) else ""

    return _TOKEN_PATTERN.sub(swap, text)
