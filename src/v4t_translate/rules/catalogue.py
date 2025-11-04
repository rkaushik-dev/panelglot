"""What each rule is, in the tool rather than only in the documentation.

Every rule and analysis already carries the reason it exists in its module
docstring, and those are the best explanations in this repository because they
were written while somebody still remembered the bug. They were also invisible
to anybody who did not have the source open.

So they are read back out. A finding says a translation is wrong; ``--explain``
says why anybody cares, and it is the same text a maintainer reads, which
means it cannot drift from the code the way a separate help string would.

The formatting is deliberate. The first paragraph is the summary and the rest
is the argument, because that is how the docstrings are already written, and a
listing wants the first paragraph while ``--explain`` wants all of it.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from ..analyses.registry import ALL_ANALYSES
from ..errors import ConfigError
from .registry import ALL_RULES
from .result import Severity

__all__ = ["RuleHelp", "describe_rule", "every_rule", "rule_listing"]

DOC_URL = "docs/rules.md"


@dataclass(frozen=True)
class RuleHelp:
    """One rule, explained."""

    name: str
    severity: Severity
    summary: str
    """The first paragraph of the docstring, on one line."""

    body: str
    """Everything after it, paragraphs kept."""

    is_analysis: bool = False

    @property
    def where(self) -> str:
        return f"{DOC_URL}#{self.name}"

    def one_line(self) -> str:
        kind = "analysis" if self.is_analysis else "rule"
        return f"{self.name:<14} {self.severity!s:<8} {kind:<9} {self.summary}"

    def explain(self) -> str:
        parts = [
            f"{self.name} ({self.severity} by default, "
            f"{'an analysis' if self.is_analysis else 'a rule'})",
            "",
            self.summary,
        ]
        if self.body:
            parts.extend(["", self.body])
        parts.extend(["", f"Written up in {self.where}"])
        return "\n".join(parts)


def _split(doc: str | None) -> tuple[str, str]:
    """A docstring as a one line summary and the rest.

    The module docstring rather than the class one. The class is a wrapper
    around the check; the module is where the reasoning was written down.
    """
    if not doc:
        return ("No description.", "")

    paragraphs = [p.strip() for p in inspect.cleandoc(doc).split("\n\n")]
    summary = " ".join(paragraphs[0].split())
    return (summary, "\n\n".join(paragraphs[1:]).strip())


def _help_for(cls: object, *, is_analysis: bool) -> RuleHelp:
    """One entry, from whichever registry it came out of.

    Takes the class as a plain object because a rule class and an analysis
    class are two different protocols that happen to share the two attributes
    read here. Widening one of them to cover both would be inventing a
    relationship they do not have, for the sake of one loop.
    """
    module = inspect.getmodule(cls)
    summary, body = _split(module.__doc__ if module else None)
    return RuleHelp(
        name=getattr(cls, "name", "?"),
        severity=getattr(cls, "default_severity", Severity.WARNING),
        summary=summary,
        body=body,
        is_analysis=is_analysis,
    )


def every_rule() -> list[RuleHelp]:
    """Every rule and analysis, in report order."""
    return [
        *(_help_for(cls, is_analysis=False) for cls in ALL_RULES),
        *(_help_for(cls, is_analysis=True) for cls in ALL_ANALYSES),
    ]


def describe_rule(name: str) -> RuleHelp:
    """One rule by name, or a refusal listing the ones that exist."""
    for help_entry in every_rule():
        if help_entry.name == name:
            return help_entry

    known = ", ".join(entry.name for entry in every_rule())
    raise ConfigError(f"there is no rule called {name!r}",
                      remedy=f"The rules are: {known}.")


def rule_listing() -> str:
    """Every rule, one line each, in report order."""
    return "\n".join(entry.one_line() for entry in every_rule())
