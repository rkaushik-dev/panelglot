"""Report formats for things that are not a person.

JSON for whatever the release dashboard is that week. JUnit XML because that
is what every CI system already knows how to display, and a build that shows
sixty fitting failures as sixty rows somebody can click is worth far more than
one that shows a red X and a log.

Both are deliberately lossless. Anything the console report can show, these
carry, because the moment a format drops a field somebody starts parsing the
console output instead and then the console output cannot change.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import escape, quoteattr

from ..ops.check import CheckResult
from ..rules.result import Finding, Report

__all__ = ["report_to_json", "report_to_junit", "check_to_json"]


def _finding_to_dict(finding: Finding) -> dict[str, object]:
    return {
        "rule": finding.rule,
        "severity": str(finding.severity),
        "locale": finding.locale,
        "key": finding.key,
        "summary": finding.summary,
        "source": finding.source_text,
        "translation": finding.translated_text,
        "detail": finding.detail,
        "origin": finding.origin,
    }


def report_to_json(report: Report, *, indent: int = 2) -> str:
    """The findings, with the counts a dashboard wants already summed."""
    payload = {
        "checked": report.checked,
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "by_rule": report.rule_counts(),
        "findings": [_finding_to_dict(f) for f in report.sorted()],
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"


def check_to_json(result: CheckResult, *, indent: int = 2) -> str:
    """A whole check run, including what each language was measured against."""
    payload = {
        "project": result.catalog.project,
        "checked": result.report.checked,
        "errors": len(result.report.errors),
        "warnings": len(result.report.warnings),
        "by_rule": result.report.rule_counts(),
        "locales": [
            {
                "locale": check.tag,
                "panel": check.panel.name,
                "font": check.font.name,
                "font_is_fallback": check.font_is_fallback,
                "translated": check.translated,
                "total": check.total,
                "coverage": round(check.coverage, 4),
            }
            for check in result.locales
        ],
        "warnings_text": list(result.warnings),
        "findings": [_finding_to_dict(f) for f in result.report.sorted()],
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"


def report_to_junit(report: Report, *, suite: str = "v4t-translate") -> str:
    """JUnit XML, one test case per finding.

    A finding is modelled as a failing test rather than as an error, because
    every CI display treats an error as "the runner broke" and a failure as
    "the thing under test is wrong", and the second one is what this is.

    Warnings become skipped cases. That keeps them visible in the display
    without turning the build red, which is exactly the distinction the
    severity was for.
    """
    findings = report.sorted()
    failures = sum(1 for f in findings if f.severity.name == "ERROR")
    skipped = len(findings) - failures

    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    lines.append(
        f"<testsuite name={quoteattr(suite)} tests={quoteattr(str(len(findings)))} "
        f"failures={quoteattr(str(failures))} errors=\"0\" "
        f"skipped={quoteattr(str(skipped))}>"
    )

    for index, finding in enumerate(findings):
        name = f"{finding.locale} {finding.key}"
        lines.append(
            f"  <testcase classname={quoteattr(finding.rule)} "
            f"name={quoteattr(name)} id={quoteattr(str(index))}>"
        )
        body = escape(_body(finding))
        if finding.severity.name == "ERROR":
            lines.append(
                f"    <failure message={quoteattr(finding.summary)} "
                f"type={quoteattr(finding.rule)}>{body}</failure>"
            )
        else:
            lines.append(
                f"    <skipped message={quoteattr(finding.summary)}/>"
            )
        lines.append("  </testcase>")

    if not findings:
        # An empty suite is reported as "no tests ran" by several runners,
        # which reads as a broken pipeline rather than a clean one.
        lines.append(
            f'  <testcase classname="v4t-translate" '
            f'name={quoteattr(f"{report.checked} messages checked")}/>'
        )
        lines[1] = lines[1].replace('tests="0"', 'tests="1"')

    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def _body(finding: Finding) -> str:
    parts = [finding.summary]
    if finding.source_text:
        parts.append(f"source: {finding.source_text!r}")
    if finding.translated_text:
        parts.append(f"translation: {finding.translated_text!r}")
    if finding.detail:
        parts.append(finding.detail)
    if finding.origin:
        parts.append(finding.origin)
    return "\n".join(parts)
