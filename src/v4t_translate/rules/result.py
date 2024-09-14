"""What a check produces.

A finding is one problem with one message in one language. It carries enough
to print a line somebody can act on without going back to the catalog, which
means the source text and the translation both travel with it: a report that
says "fitting: bar-height.9a2f1c overflows" is a report nobody reads twice.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import IntEnum

__all__ = ["Severity", "Finding", "Report"]


class Severity(IntEnum):
    """How bad a finding is. Ordered, so ``max()`` means what it looks like."""

    INFO = 0
    WARNING = 1
    ERROR = 2

    def __str__(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, text: str) -> Severity:
        try:
            return cls[text.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown severity {text!r}") from exc


@dataclass(frozen=True)
class Finding:
    """One problem with one message in one language."""

    rule: str
    severity: Severity
    locale: str
    key: str
    summary: str
    """One line, no trailing full stop, written for a person."""

    source_text: str = ""
    translated_text: str = ""
    detail: str = ""
    """Optional second line: the measurement, the missing characters, the diff."""

    origin: str = ""
    """Where the message came from, for the reader who wants to go and look."""

    def format(self, *, with_detail: bool = True) -> str:
        head = f"{self.severity}: {self.rule}: {self.summary}"
        if not with_detail or not self.detail:
            return head
        return f"{head}\n    {self.detail}"

    def sort_key(self) -> tuple[int, str, str, str]:
        # Errors first, then grouped by rule so a reviewer fixes one class of
        # problem at a time rather than jumping around the catalog.
        return (-int(self.severity), self.rule, self.locale, self.key)


@dataclass
class Report:
    """Every finding from one run."""

    findings: list[Finding] = field(default_factory=list)
    checked: int = 0
    """Messages examined, so a clean report can still say what it looked at."""

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def extend(self, findings: list[Finding]) -> None:
        self.findings.extend(findings)

    def __len__(self) -> int:
        return len(self.findings)

    def __bool__(self) -> bool:
        return bool(self.findings)

    def at_or_above(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity >= severity]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def worst(self) -> Severity | None:
        return max((f.severity for f in self.findings), default=None)

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=Finding.sort_key)

    def by_rule(self) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = {}
        for finding in self.sorted():
            grouped.setdefault(finding.rule, []).append(finding)
        return grouped

    def by_locale(self) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = {}
        for finding in self.sorted():
            grouped.setdefault(finding.locale, []).append(finding)
        return grouped

    def rule_counts(self) -> dict[str, int]:
        return dict(Counter(f.rule for f in self.findings).most_common())

    def summary(self) -> str:
        if not self.findings:
            return f"{self.checked} messages checked, nothing found"
        return (
            f"{self.checked} messages checked, "
            f"{len(self.errors)} errors, {len(self.warnings)} warnings"
        )

    def should_fail(self, fail_on: str) -> bool:
        """Whether ``check`` should exit non-zero given a ``fail_on`` setting."""
        if fail_on == "never":
            return False
        if fail_on == "warning":
            return bool(self.at_or_above(Severity.WARNING))
        return bool(self.errors)
