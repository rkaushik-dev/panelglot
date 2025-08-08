"""Which report formats exist, and what each one is for.

This was a chain of ifs inside the check command. It moved because the command
had grown into the only place that knew a format needed a config, that two of
them are binary-ish enough to never be coloured, and that html costs a second
pass over the catalog to get coverage numbers. None of that is command line
argument parsing.

Each format declares those facts about itself instead, so adding one is one
entry rather than one entry and three remembered edits somewhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..config import ProjectConfig
from ..errors import ConfigError
from ..ops.check import CheckResult
from .console import DEFAULT_LIMIT, format_check
from .html import render_report
from .sarif import check_to_sarif
from .structured import check_to_json, report_to_junit

__all__ = ["Format", "FORMATS", "format_names", "get_format", "render_check"]


@dataclass(frozen=True)
class Format:
    """One way of writing a check result out."""

    name: str
    render: Callable[[CheckResult, RenderOptions], str]
    description: str

    colourable: bool = False
    """Whether colour means anything here. Only the terminal report."""

    extension: str = ".txt"
    """What an --output path should end in, used only to warn."""


@dataclass
class RenderOptions:
    """Everything a renderer might want that is not the result itself."""

    config: ProjectConfig
    limit: int = DEFAULT_LIMIT
    detail: bool = True
    colour: bool | None = None


def _text(result: CheckResult, options: RenderOptions) -> str:
    return format_check(result, limit=options.limit, show_detail=options.detail,
                        colour=options.colour)


def _json(result: CheckResult, options: RenderOptions) -> str:
    return check_to_json(result)


def _junit(result: CheckResult, options: RenderOptions) -> str:
    return report_to_junit(result.report)


def _sarif(result: CheckResult, options: RenderOptions) -> str:
    return check_to_sarif(result)


def _html(result: CheckResult, options: RenderOptions) -> str:
    # Coverage numbers are a second pass over the catalog. The HTML report is
    # the one place anybody compares languages, so it is worth the read; the
    # other formats do not pay for it.
    from ..ops.stats import project_stats

    return render_report(result, project_stats(options.config))


FORMATS: tuple[Format, ...] = (
    Format("text", _text, "For a person, in a terminal.",
           colourable=True, extension=".txt"),
    Format("json", _json, "Everything the check knows, for a dashboard.",
           extension=".json"),
    Format("junit", _junit, "One test case per finding, for a CI display.",
           extension=".xml"),
    Format("sarif", _sarif, "For code scanning, anchored to the .rc line.",
           extension=".sarif"),
    Format("html", _html, "A page comparing languages, with coverage.",
           extension=".html"),
)


def format_names() -> list[str]:
    return [entry.name for entry in FORMATS]


def get_format(name: str) -> Format:
    for entry in FORMATS:
        if entry.name == name:
            return entry
    raise ConfigError(
        f"unknown report format {name!r}. Known formats: {', '.join(format_names())}"
    )


def render_check(result: CheckResult, name: str, *, config: ProjectConfig,
                 limit: int = DEFAULT_LIMIT, detail: bool = True,
                 colour: bool | None = None) -> str:
    """Render ``result`` in the named format."""
    entry = get_format(name)
    options = RenderOptions(
        config=config,
        limit=limit,
        detail=detail,
        colour=colour if entry.colourable else False,
    )
    return entry.render(result, options)
