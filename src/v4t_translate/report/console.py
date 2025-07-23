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
from .style import Palette, palette_for

__all__ = ["format_report", "format_finding", "format_check", "DEFAULT_LIMIT"]

#: Findings shown per rule before the rest are counted instead.
DEFAULT_LIMIT = 12

_MARKERS = {
    Severity.ERROR: "E",
    Severity.WARNING: "W",
    Severity.INFO: "i",
}


def format_finding(finding: Finding, *, show_detail: bool = True,
                   palette: Palette | None = None) -> list[str]:
    """One finding as a block of lines."""
    colours = palette if palette is not None else Palette()
    marker = colours.severity(_MARKERS[finding.severity], finding.severity)

    lines = [
        f"  {marker} {colours.dim(finding.locale)} "
        f"{colours.paint(_quote(finding.source_text), 'source')}"
    ]

    if finding.translated_text:
        lines.append(
            f"      -> {colours.paint(_quote(finding.translated_text), 'target')}"
        )

    lines.append(f"      {finding.summary}")

    if show_detail and finding.detail:
        lines.append(f"      {colours.dim(finding.detail)}")

    if finding.origin:
        lines.append(f"      {colours.dim(finding.origin)}")

    return lines


def format_report(report: Report, *, limit: int = DEFAULT_LIMIT,
                  show_detail: bool = True, palette: Palette | None = None) -> str:
    """The whole report, grouped by rule."""
    colours = palette if palette is not None else Palette()

    if not report:
        return report.summary()

    blocks: list[str] = []

    for rule, findings in report.by_rule().items():
        worst = max(f.severity for f in findings)
        heading = colours.bold(f"{rule} ({len(findings)}, worst {worst})")
        lines = [heading]

        shown = findings if limit <= 0 else findings[:limit]
        for finding in shown:
            lines.extend(
                format_finding(finding, show_detail=show_detail, palette=colours)
            )

        hidden = len(findings) - len(shown)
        if hidden:
            lines.append(
                colours.dim(f"  ... and {hidden} more, use --limit 0 to see them all")
            )

        blocks.append("\n".join(lines))

    blocks.append(report.summary())
    return "\n\n".join(blocks)


def format_check(result: CheckResult, *, limit: int = DEFAULT_LIMIT,
                 show_detail: bool = True, colour: bool | None = None) -> str:
    """A check result: what was checked, then what was found."""
    palette = palette_for(force=colour)

    lines = [palette.dim(check.describe()) for check in result.locales]
    if lines:
        lines.append("")
    lines.append(
        format_report(result.report, limit=limit, show_detail=show_detail,
                      palette=palette)
    )
    return "\n".join(lines)


def _quote(text: str) -> str:
    """Show a string with its whitespace visible and its length bounded."""
    shown = text if len(text) <= 60 else text[:57] + "..."
    return repr(shown)
