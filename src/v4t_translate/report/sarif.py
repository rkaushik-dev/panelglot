"""SARIF, which is what a code scanning dashboard reads.

The point of this format over the JSON one is that a host understands it
without being taught. Upload it and every finding lands on the line of the
resource script it came from, in the review, next to the change that caused
it. Nobody has to open a build log to find out that the Polish translation of
the purge dialog stopped fitting.

Two things about the mapping are worth writing down.

Findings point at the source file, not at the catalog. The catalog is
generated and the line numbers in it move whenever anything is extracted, so
anchoring there would produce a comment on a different string every round. The
origin string a finding carries is a path and a line in the .rc, which is a
file a person edits and a reviewer is already looking at.

Warnings stay warnings. A scanning host decides on its own whether a warning
blocks anything, and flattening the severity here would take that decision
away from the one place it belongs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import __version__
from ..ops.check import CheckResult
from ..rules.registry import rule_names
from ..rules.result import Finding, Report, Severity

__all__ = ["report_to_sarif", "check_to_sarif", "SARIF_VERSION", "SCHEMA"]

SARIF_VERSION = "2.1.0"
SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

TOOL_URI = "https://github.com/edge-solutions86/V4T-Translate"

#: SARIF has three levels a host acts on. Ours map straight across.
_LEVELS = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
}

#: ``V4T.rc:41`` and ``V4T.rc:41 IDD_BARCODE_PROPS`` both come out of Origin.
_ORIGIN = re.compile(r"^(?P<path>[^\s:]+?)(?::(?P<line>\d+))?(?:\s|$)")


def _location(finding: Finding) -> list[dict[str, Any]]:
    """Where a host should draw this finding.

    A finding with no usable origin gets no location rather than a made up
    one. A host shows those in the run summary, which is the honest place for
    something that cannot be pointed at.
    """
    match = _ORIGIN.match(finding.origin) if finding.origin else None
    if match is None:
        return []

    region: dict[str, Any] = {}
    if match.group("line"):
        region["startLine"] = int(match.group("line"))

    physical: dict[str, Any] = {
        "artifactLocation": {"uri": match.group("path").replace("\\", "/")}
    }
    if region:
        physical["region"] = region

    return [{"physicalLocation": physical}]


def _result(finding: Finding) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": finding.rule,
        "level": _LEVELS[finding.severity],
        "message": {"text": _message(finding)},
        "partialFingerprints": {
            # Keyed on the message and the language rather than on the text or
            # the line. A host uses this to tell "the same finding, still
            # there" from "a new one", and rewording a translation should not
            # count as a new finding when the problem is that it overflows.
            "v4tMessageKey": f"{finding.locale}/{finding.key}",
        },
    }

    locations = _location(finding)
    if locations:
        result["locations"] = locations

    return result


def _message(finding: Finding) -> str:
    parts = [f"{finding.locale}: {finding.summary}"]
    if finding.translated_text:
        parts.append(f"Translation: {finding.translated_text!r}")
    if finding.detail:
        parts.append(finding.detail)
    return " ".join(parts)


def _rules() -> list[dict[str, Any]]:
    """Every rule, declared whether or not it fired.

    Declared up front so a host can show a rule as passing. A dashboard that
    only ever hears about rules that failed cannot tell a rule that passed
    from one that was switched off.
    """
    from ..rules.registry import ALL_RULES

    described = {cls.name: cls for cls in ALL_RULES}
    return [
        {
            "id": name,
            "name": name,
            "shortDescription": {"text": _first_line(described[name].__doc__)},
            "defaultConfiguration": {
                "level": _LEVELS[described[name].default_severity]
            },
            "helpUri": f"{TOOL_URI}/blob/main/docs/rules.md#{name}",
        }
        for name in rule_names()
    ]


def _first_line(doc: str | None) -> str:
    if not doc:
        return "No description."
    return doc.strip().splitlines()[0]


def report_to_sarif(report: Report, *, indent: int = 2) -> str:
    """One run, with every finding as a result."""
    payload = {
        "$schema": SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "v4t-translate",
                        "version": __version__,
                        "informationUri": TOOL_URI,
                        "rules": _rules(),
                    }
                },
                "results": [_result(f) for f in report.sorted()],
            }
        ],
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"


def check_to_sarif(result: CheckResult, *, indent: int = 2) -> str:
    """A whole check run, with the context as run properties.

    The per language context is attached rather than dropped because a
    fitting result measured against a fallback font is a different claim from
    one measured against the real metrics, and the dashboard is where somebody
    will be looking when they doubt it.
    """
    text = report_to_sarif(result.report, indent=indent)
    payload = json.loads(text)

    run = payload["runs"][0]
    run["properties"] = {
        "project": result.catalog.project,
        "checked": result.report.checked,
        "locales": [
            {
                "locale": check.tag,
                "panel": check.panel.name,
                "font": check.font.name,
                "fontIsFallback": check.font_is_fallback,
                "coverage": round(check.coverage, 4),
            }
            for check in result.locales
        ],
        "warnings": list(result.warnings),
    }

    if result.waivers is not None:
        run["properties"]["waived"] = len(result.waivers.waived)

    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"
