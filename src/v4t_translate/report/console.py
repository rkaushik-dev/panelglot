"""The report a person reads in a terminal.

Grouped by rule rather than by message, because the work of fixing them is
grouped that way: somebody sits down and does the placeholders, then somebody
else does the fitting. A list in key order makes them jump between four kinds
of problem forty times.

Findings are truncated per rule by default. A first run on a language that has
never been checked produces several hundred fitting findings and printing all
of them just buries the six placeholder ones underneath.
"""

from __future__ import annotations

from ..ops.check import CheckResult
from ..rules.result import Finding, Report, Severity

__all__ = ["format_report", "format_finding", "DEFAULT_LIMIT"]

#: Findings shown per rule before the rest are counted instead.
DEFAULT_LIMIT = 12

_MARKERS = {
    Severity.ERROR: "E",
    Severity.WARNING: "W",
    Severity.INFO: "i",
}


def format_finding(finding: Finding, *, show_detail: bool = True) -> list[str]:
    """One finding as a block of lines."""
    marker = _MARKERS[finding.severity]
    lines = [f"  {marker} {finding.locale} {_quote(finding.source_text)}"]

    if finding.translated_text:
        lines.append(f"      -> {_quote(finding.translated_text)}")

    lines.append(f"      {finding.summary}")

    if show_detail and finding.detail:
        lines.append(f"      {finding.detail}")

    if finding.origin:
        lines.append(f"      {finding.origin}")

    return lines


def format_report(report: Report, *, limit: int = DEFAULT_LIMIT,
                  show_detail: bool = True) -> str:
    """The whole report, grouped by rule."""
    if not report:
        return report.summary()

    blocks: list[str] = []

    for rule, findings in report.by_rule().items():
        worst = max(f.severity for f in findings)
        heading = f"{rule} ({len(findings)}, worst {worst})"
        lines = [heading]

        shown = findings if limit <= 0 else findings[:limit]
        for finding in shown:
            lines.extend(format_finding(finding, show_detail=show_detail))

        hidden = len(findings) - len(shown)
        if hidden:
            lines.append(f"  ... and {hidden} more, use --limit 0 to see them all")

        blocks.append("\n".join(lines))

    blocks.append(report.summary())
    return "\n\n".join(blocks)


def format_check(result: CheckResult, *, limit: int = DEFAULT_LIMIT,
                 show_detail: bool = True) -> str:
    """A check result: what was checked, then what was found."""
    lines = [check.describe() for check in result.locales]
    if lines:
        lines.append("")
    lines.append(format_report(result.report, limit=limit, show_detail=show_detail))
    return "\n".join(lines)


def _quote(text: str) -> str:
    """Show a string with its whitespace visible and its length bounded."""
    shown = text if len(text) <= 60 else text[:57] + "..."
    return repr(shown)
