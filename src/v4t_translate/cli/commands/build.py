"""``build``: produce every configured output."""

from __future__ import annotations

import click

from ...ops.build import BuildResult, build_project, check_before_build
from ..context import Context, pass_context

__all__ = ["build"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable. Defaults to all of them.")
@click.option("--dry-run", is_flag=True, help="Report what would be built, write nothing.")
@click.option("--no-check", is_flag=True,
              help="Build even when check is failing. You had better mean it.")
@pass_context
def build(context: Context, locales: tuple[str, ...], dry_run: bool,
          no_check: bool) -> None:
    """Produce every configured output."""
    wanted = list(locales) or None

    if not no_check:
        check_before_build(context.config, locales=wanted)

    result = build_project(context.config, locales=wanted, dry_run=dry_run)
    report(context, result, dry_run=dry_run)


def report(context: Context, result: BuildResult, *, dry_run: bool) -> None:
    for warning in result.warnings:
        context.warn(warning)

    for tag, kind, emitted in result.outputs:
        context.say(f"{tag} {kind}: {emitted.summary()}")

    context.say(f"{result.summary()}, {result.total_bytes} bytes", level=1)

    if dry_run:
        context.say("dry run, nothing written")
