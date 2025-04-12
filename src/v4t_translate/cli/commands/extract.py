"""``extract``: read every source and update the catalog."""

from __future__ import annotations

import click

from ...ops.extract import ExtractResult, extract_project
from ..context import Context, pass_context

__all__ = ["extract"]


@click.command()
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@click.option("--keep-going", is_flag=True, help="Skip sources that cannot be read.")
@pass_context
def extract(context: Context, dry_run: bool, keep_going: bool) -> None:
    """Read every source and update the catalog."""
    result = extract_project(context.config, dry_run=dry_run, keep_going=keep_going)
    report(context, result, dry_run=dry_run)


def report(context: Context, result: ExtractResult, *, dry_run: bool) -> None:
    for skipped in result.skipped:
        context.warn(f"skipped {skipped}")
    for warning in result.warnings:
        context.warn(warning)

    for source, stats in result.stats_by_source().items():
        summary = ", ".join(f"{value} {name}" for name, value in stats.items() if value)
        context.say(f"  {source}: {summary}", level=1)

    context.say(f"{result.message_count} messages: {result.report.summary()}")

    for old_key, new_key in result.report.rewordings:
        context.say(f"  carried {old_key} -> {new_key}", level=1)

    if dry_run:
        context.say("dry run, nothing written")
        return

    for path in result.written:
        context.say(f"wrote {path}", level=1)
