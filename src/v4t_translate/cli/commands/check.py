"""``check``: run every rule over the translated catalog."""

from __future__ import annotations

from pathlib import Path

import click

from ...config import ProjectConfig
from ...errors import CheckFailed
from ...ops.check import CheckResult, check_project
from ...ops.stats import project_stats
from ...report.console import DEFAULT_LIMIT, format_check
from ...report.html import render_report
from ...report.structured import check_to_json, report_to_junit
from ..context import Context, pass_context

__all__ = ["check", "FORMATS"]

FORMATS = ["text", "json", "junit", "html"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable. Defaults to all of them.")
@click.option("--limit", type=int, default=DEFAULT_LIMIT, show_default=True,
              help="Findings shown per rule. 0 for all of them.")
@click.option("--no-detail", is_flag=True, help="One line per finding.")
@click.option("--fail-on", type=click.Choice(["error", "warning", "never"]),
              help="Override the project's fail_on setting.")
@click.option("--format", "output_format", type=click.Choice(FORMATS),
              default="text", show_default=True, help="How to print the findings.")
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path),
              help="Write the report here instead of to the terminal.")
@click.option("--color/--no-color", "colour", default=None,
              help="Force colour on or off. Defaults to whether stdout is a "
                   "terminal, and NO_COLOR is always honoured.")
@click.option("--no-waivers", is_flag=True,
              help="Ignore waivers.toml and report everything, including the "
                   "findings the team has accepted.")
@pass_context
def check(context: Context, locales: tuple[str, ...], limit: int, no_detail: bool,
          fail_on: str | None, output_format: str, output: Path | None,
          colour: bool | None, no_waivers: bool) -> None:
    """Run every rule over the translated catalog."""
    config = context.config
    result = check_project(config, locales=list(locales) or None,
                           use_waivers=not no_waivers)

    for warning in result.warnings:
        context.warn(warning)

    # A report going to a file is never coloured. It gets mailed to a
    # distributor about once a round, and escape codes in it make the report
    # unreadable to exactly the person it is for.
    text = render(result, output_format, limit=limit, detail=not no_detail,
                  config=config, colour=False if output is not None else colour)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        context.say(f"wrote {output}", level=1)
    elif not context.quiet:
        # click strips escape codes when stdout is not a terminal, which is
        # right by default and wrong when somebody asked for colour on
        # purpose, usually to pipe it into something that renders them.
        click.echo(text, color=colour)

    threshold = fail_on or config.check.fail_on
    if result.should_fail(threshold):
        raise CheckFailed(
            f"{len(result.report.errors)} errors and "
            f"{len(result.report.warnings)} warnings",
            error_count=len(result.report.errors),
            warning_count=len(result.report.warnings),
        )


def render(result: CheckResult, output_format: str, *, limit: int, detail: bool,
           config: ProjectConfig, colour: bool | None = None) -> str:
    if output_format == "json":
        return check_to_json(result)
    if output_format == "junit":
        return report_to_junit(result.report)
    if output_format == "html":
        # Coverage numbers are a separate pass. The HTML report is the one
        # place a person compares languages, so it is worth the second read.
        return render_report(result, project_stats(config))
    return format_check(result, limit=limit, show_detail=detail, colour=colour)
