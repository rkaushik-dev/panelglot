"""``stats``, ``diff`` and ``doctor``: the commands that only look."""

from __future__ import annotations

from pathlib import Path

import click

from ...errors import CheckFailed
from ...ops.diff import diff_against, outstanding_after
from ...ops.doctor import run_doctor
from ...ops.stats import project_stats
from ...ops.verify import verify_pack
from ..context import Context, pass_context

__all__ = ["stats", "diff", "doctor", "verify"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable.")
@click.option("--worst-first", is_flag=True,
              help="Order by how far behind each language is.")
@pass_context
def stats(context: Context, locales: tuple[str, ...], worst_first: bool) -> None:
    """Report how far along each language is."""
    result = project_stats(context.config, locales=list(locales) or None)

    context.say(result.summary())
    if result.protected:
        context.say(f"{result.protected} messages are protected", level=1)

    ordered = result.worst_first() if worst_first else result.locales
    for locale_stats in ordered:
        context.say(f"  {locale_stats.describe()}")
        for state, count in locale_stats.by_state.items():
            if count:
                context.say(f"      {state}: {count}", level=1)


@click.command()
@click.argument("previous",
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", "-l", help="Also report what is still unanswered here.")
@pass_context
def diff(context: Context, previous: Path, locale: str | None) -> None:
    """Say what changed since a saved copy of the catalog."""
    result = diff_against(context.config, previous)

    for message in result.added:
        context.say(f"  new      {message.source_text!r}")
    for change in result.changed:
        context.say(f"  changed  {change.describe()}")
    for message in result.removed:
        context.say(f"  gone     {message.source_text!r}", level=1)

    context.say(result.summary())

    if locale is not None:
        outstanding = outstanding_after(context.config, result, locale)
        context.say(f"{locale}: {len(outstanding)} of those are still unanswered")


@click.command()
@click.argument("pack", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--header", "-H",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="The firmware's language header, to check the signature against.")
@click.option("--locale", "-l", help="Insist the pack is this language.")
@pass_context
def verify(context: Context, pack: tuple[Path, ...], header: Path | None,
           locale: str | None) -> None:
    """Say whether a built .v4l pack would be loaded by the firmware."""
    refused = 0

    for path in pack:
        result = verify_pack(path, header=header, expect_locale=locale)
        context.say(result.describe())

        for problem in result.problems:
            context.warn(f"{path.name}: {problem}")
        for note in result.notes:
            context.say(f"  {note}", level=1)

        if not result.accepted:
            refused += 1

    if refused:
        raise CheckFailed(
            f"{refused} of {len(pack)} packs would be refused", error_count=refused
        )


@click.command()
@click.option("--all", "show_all", is_flag=True,
              help="List the checks that passed as well.")
@pass_context
def doctor(context: Context, show_all: bool) -> None:
    """Check the project is set up before anything relies on it."""
    report = run_doctor(context.config)

    for finding in report.findings:
        if finding.ok and not (show_all or context.verbose):
            continue
        context.say(finding.describe())

    context.say(report.summary())

    if report.problems:
        raise CheckFailed(
            f"{len(report.problems)} problems with the project setup",
            error_count=len(report.problems),
        )
