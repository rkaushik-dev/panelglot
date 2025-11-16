"""``stats``, ``diff`` and ``doctor``: the commands that only look."""

from __future__ import annotations

from pathlib import Path

import click

from ...errors import CheckFailed
from ...ops.audit import audit_against
from ...ops.diff import diff_against, diff_to_json, outstanding_after
from ...ops.doctor import run_doctor
from ...ops.history import history_path, movement_since, record
from ...ops.prune import prune_project
from ...ops.stats import project_stats
from ...ops.verify import compare_packs, verify_pack
from ..context import Context, pass_context

__all__ = ["stats", "diff", "doctor", "verify", "prune", "pack_diff", "audit"]


@click.command()
@click.option("--memory", "drop_memory", is_flag=True,
              help="Also drop memory units whose English is gone from the catalog.")
@click.option("--cache", "drop_cache", is_flag=True,
              help="Also delete the extraction cache.")
@click.option("--dry-run", is_flag=True, help="Report what would go, remove nothing.")
@pass_context
def prune(context: Context, drop_memory: bool, drop_cache: bool,
          dry_run: bool) -> None:
    """Drop translations and cached data the catalog no longer needs."""
    result = prune_project(context.config, drop_memory=drop_memory,
                           drop_cache=drop_cache, dry_run=dry_run)

    for tag, keys in result.orphans.items():
        context.say(f"{tag}: {len(keys)} translations with no message")
        for key in keys:
            context.say(f"  {key}", level=1)

    context.say(result.summary())

    if dry_run:
        context.say("dry run, nothing removed")


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable.")
@click.option("--worst-first", is_flag=True,
              help="Order by how far behind each language is.")
@click.option("--since-last", is_flag=True,
              help="Also say what has moved since the last recorded run.")
@click.option("--record", "record_it", is_flag=True,
              help="Append today's figures to the coverage history.")
@pass_context
def stats(context: Context, locales: tuple[str, ...], worst_first: bool,
          since_last: bool, record_it: bool) -> None:
    """Report how far along each language is."""
    result = project_stats(context.config, locales=list(locales) or None)

    if since_last:
        _say_movement(context, result)

    context.say(result.summary())
    if result.protected:
        context.say(f"{result.protected} messages are protected", level=1)

    ordered = result.worst_first() if worst_first else result.locales
    for locale_stats in ordered:
        context.say(f"  {locale_stats.describe()}")
        for state, count in locale_stats.by_state.items():
            if count:
                context.say(f"      {state}: {count}", level=1)

    if record_it:
        # Only when asked. A read-only command that quietly appends to a file
        # is a read-only command that makes a diff on somebody's branch.
        written = record(context.config, result)
        context.say(f"recorded {len(written)} languages in "
                    f"{history_path(context.config).name}")


def _say_movement(context: Context, result) -> None:
    movements = movement_since(context.config, result)
    if not movements:
        context.say("nothing recorded before today, so nothing to compare")
        context.say("")
        return

    for movement in movements:
        context.say(movement.describe())
    context.say("")


@click.command()
@click.argument("previous",
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", "-l", help="Also report what is still unanswered here.")
@click.option("--json", "as_json", is_flag=True,
              help="Machine readable, for a review bot.")
@pass_context
def diff(context: Context, previous: Path, locale: str | None,
         as_json: bool) -> None:
    """Say what changed since a saved copy of the catalog."""
    result = diff_against(context.config, previous)

    if as_json:
        click.echo(diff_to_json(result), nl=False)
        return

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
@click.argument("manifest",
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--root", type=click.Path(exists=True, file_okay=False,
                                        path_type=Path),
              help="The project directory the manifest's paths are relative "
                   "to. Defaults to the project this config names.")
@click.option("--extension", "extensions", multiple=True,
              help="Only these suffixes count as unexpected. Repeatable.")
@pass_context
def audit(context: Context, manifest: Path, root: Path | None,
          extensions: tuple[str, ...]) -> None:
    """Check a directory of built files against a release manifest."""
    # The project root rather than the manifest's own directory. A manifest
    # records project-relative paths and usually sits in the output directory,
    # so auditing from beside itself reports every file as missing.
    result = audit_against(manifest, root or context.config.root,
                           extensions=tuple(e.lower() for e in extensions))

    for verdict in result.problems:
        context.warn(verdict.describe())
    for name in result.unexpected:
        context.warn(f"{name} is not in the manifest")

    for verdict in result.files:
        if verdict.ok:
            context.say(f"  {verdict.describe()}", level=1)

    context.say(result.summary())

    if not result.matches:
        raise CheckFailed(
            f"{len(result.problems) + len(result.unexpected)} files do not "
            f"match the manifest",
            error_count=len(result.problems) + len(result.unexpected),
            remedy="Rebuild, or find out which run produced these files.",
        )


@click.command("pack-diff")
@click.argument("before",
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("after",
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--limit", type=int, default=20, show_default=True,
              help="Differences shown before the rest are counted. 0 for all.")
@pass_context
def pack_diff(context: Context, before: Path, after: Path, limit: int) -> None:
    """Say which strings differ between two built .v4l packs."""
    comparison = compare_packs(before, after)

    for problem in comparison.problems:
        context.warn(problem)

    shown = (comparison.differences if limit <= 0
             else comparison.differences[:limit])
    for difference in shown:
        context.say(f"  {difference.describe()}")

    hidden = len(comparison.differences) - len(shown)
    if hidden > 0:
        context.say(f"  ... and {hidden} more, use --limit 0 to see them all")

    context.say(comparison.summary())

    if comparison.problems:
        raise CheckFailed("the two packs are not comparable", error_count=1)


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
