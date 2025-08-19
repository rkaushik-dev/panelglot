"""Which rules exist, and which of them a project runs.

The order here is the order findings are grouped in a report, so it is not
alphabetical. It goes from the checks that break the software, through the
ones that break the display, to the ones that are about consistency.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..config import CheckSettings
from ..errors import ConfigError
from .base import Rule, RuleContext
from .direction import DirectionRule
from .fitting import FittingRule
from .glossary import GlossaryRule
from .glyphs import EncodingRule, GlyphRule
from .mnemonics import MnemonicRule
from .numbers import NumberRule
from .placeholders import PlaceholderRule
from .protected import ProtectedRule
from .protocol import ProtocolRule
from .punctuation import PunctuationRule, WhitespaceRule
from .result import Finding, Severity
from .shortcuts import ShortcutRule
from .state import StateRule

__all__ = [
    "ALL_RULES",
    "rule_names",
    "known_rule_names",
    "build_rules",
    "SeverityOverride",
]


class RuleType(Protocol):
    """The class object of a rule.

    Separate from :class:`~.base.Rule` because the registry reads ``name`` off
    the class, before anything is instantiated, and a Protocol describing an
    instance does not say that the class has it too.
    """

    name: str
    default_severity: Severity

    def __call__(self) -> Rule:
        ...


#: Every rule, worst consequence first.
ALL_RULES: tuple[RuleType, ...] = (
    PlaceholderRule,   # crashes the HMI
    NumberRule,        # states the wrong limit and the operator believes it
    ProtocolRule,      # takes the serial link down
    EncodingRule,      # ships as question marks
    GlyphRule,         # draws blank
    ProtectedRule,     # ships a translated unit symbol
    ShortcutRule,      # advertises a key that is not bound
    StateRule,         # ships a confident answer to a question that changed
    FittingRule,       # clips
    MnemonicRule,      # loses or invents a shortcut
    DirectionRule,     # draws its punctuation at the wrong end of the line
    PunctuationRule,   # reads wrong
    WhitespaceRule,    # joins wrong
    GlossaryRule,      # says the same thing two ways
)


class SeverityOverride:
    """Wraps a rule so its findings come out at a different level.

    Used for the ``promote`` and ``demote`` config lists. Rewriting the
    finding after the fact rather than telling the rule what level to use
    keeps every rule ignorant of configuration, which is the only reason they
    are as short as they are.
    """

    def __init__(self, rule: Rule, severity: Severity) -> None:
        self._rule = rule
        self._severity = severity
        self.name = rule.name
        self.default_severity = severity

    def check(self, message, translation, context: RuleContext) -> Iterable[Finding]:
        for found in self._rule.check(message, translation, context):
            yield Finding(
                rule=found.rule,
                severity=self._severity,
                locale=found.locale,
                key=found.key,
                summary=found.summary,
                source_text=found.source_text,
                translated_text=found.translated_text,
                detail=found.detail,
                origin=found.origin,
            )


def rule_names() -> list[str]:
    """Every rule name, in report order."""
    return [cls.name for cls in ALL_RULES]


def known_rule_names() -> list[str]:
    """Everything a project may name in disable, promote or demote.

    Rules and analyses are one namespace as far as config is concerned. They
    are different kinds of thing internally, because one sees a message and
    the other sees a language, and nobody writing a config file cares.

    Imported here rather than at module scope: the analyses import this module
    for its Severity re-export and the rule protocol, so importing them back
    at the top would close the loop.
    """
    from ..analyses.registry import analysis_names

    return [*rule_names(), *analysis_names()]


def build_rules(settings: CheckSettings | None = None) -> list[Rule]:
    """Instantiate the rules a project should run, in report order."""
    settings = settings or CheckSettings()
    known = set(known_rule_names())

    for name in (*settings.disabled_rules, *settings.promoted_rules,
                 *settings.demoted_rules):
        if name not in known:
            raise ConfigError(
                f"unknown rule {name!r}. Known rules: {', '.join(known_rule_names())}"
            )

    overlap = set(settings.promoted_rules) & set(settings.demoted_rules)
    if overlap:
        raise ConfigError(
            f"{', '.join(sorted(overlap))} is both promoted and demoted"
        )

    built: list[Rule] = []
    for cls in ALL_RULES:
        if cls.name in settings.disabled_rules:
            continue
        rule: Rule = cls()
        if cls.name in settings.promoted_rules:
            rule = SeverityOverride(rule, Severity.ERROR)
        elif cls.name in settings.demoted_rules:
            rule = SeverityOverride(rule, Severity.WARNING)
        built.append(rule)

    return built
