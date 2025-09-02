"""``pretranslate`` and the ``memory`` group."""

from __future__ import annotations

from pathlib import Path

import click

from ...ops.estimate import estimate_project
from ...ops.memory import (
    absorb_catalog,
    absorb_tmx,
    absorb_workbook,
    export_tmx,
    memory_path,
    memory_stats,
    suggest_for,
)
from ...ops.pretranslate import pretranslate_project
from ..context import Context, pass_context

__all__ = ["pretranslate", "memory"]


@click.command()
@click.argument("locale", required=False)
@click.option("--provider", "-p",
              help="Machine translation provider for what memory cannot fill. "
                   "Built in: passthrough, pseudo.")
@click.option("--trust-memory", is_flag=True,
              help="Land exact memory hits as approved rather than needs-review.")
@click.option("--threshold", type=float, default=0.75, show_default=True,
              help="How close a fuzzy memory match has to be.")
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@click.option("--estimate", is_flag=True,
              help="Count what would be posted and stop. Every language unless "
                   "one is named.")
@click.option("--rate", type=float, default=0.0,
              help="Price per million characters, to turn the count into money. "
                   "Yours to supply: every engine prices differently and a "
                   "number baked in here would be wrong within a quarter.")
@pass_context
def pretranslate(context: Context, locale: str | None, provider: str | None,
                 trust_memory: bool, threshold: float, dry_run: bool,
                 estimate: bool, rate: float) -> None:
    """Fill one language from translation memory, and optionally a provider."""
    if estimate:
        _estimate(context, [locale] if locale else None, rate)
        return

    if locale is None:
        raise click.UsageError("which language? pretranslate takes one, "
                               "or use --estimate for all of them")

    result = pretranslate_project(
        context.config, locale, provider=provider, trust_memory=trust_memory,
        threshold=threshold, dry_run=dry_run,
    )

    for warning in result.warnings:
        context.warn(warning)

    context.say(result.summary())

    for key in result.from_fuzzy:
        context.say(f"  fuzzy {key}", level=1)

    if dry_run:
        context.say("dry run, nothing written")


def _estimate(context: Context, locales: list[str] | None, rate: float) -> None:
    """Count what a run would post, and say it before anybody spends it."""
    result = estimate_project(context.config, locales=locales)

    for entry in result.locales:
        context.say(entry.describe(result.batch_size))

    context.say("")
    context.say(result.summary())

    if rate > 0:
        context.say(f"at {rate:g} per million characters, that is "
                    f"{result.cost(rate):.2f}")


@click.group()
def memory() -> None:
    """Look after the translation memory."""


@memory.command("stats")
@pass_context
def memory_stats_command(context: Context) -> None:
    """How many units are in memory, per language."""
    counts = memory_stats(context.config)
    if not counts:
        context.say("memory is empty")
        return
    for tag, count in counts.items():
        context.say(f"{tag}: {count}")
    context.say(f"{sum(counts.values())} units in {memory_path(context.config)}",
                level=1)


@memory.command("absorb")
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable.")
@click.option("--include-drafts", is_flag=True,
              help="Take needs-review entries too. Usually a bad idea.")
@pass_context
def memory_absorb(context: Context, locales: tuple[str, ...],
                  include_drafts: bool) -> None:
    """Take everything approved in the catalog into memory."""
    report = absorb_catalog(context.config, locales=list(locales) or None,
                            include_drafts=include_drafts)
    context.say(report.summary())


@memory.command("import")
@click.argument("workbook", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--sheet", help="Sheet name. Defaults to the first one.")
@pass_context
def memory_import(context: Context, workbook: Path, sheet: str | None) -> None:
    """Take a workbook into memory without matching it against the catalog."""
    report = absorb_workbook(context.config, workbook, sheet=sheet)
    for warning in report.warnings:
        context.warn(warning)
    context.say(report.summary())


@memory.command("import-tmx")
@click.argument("tmx", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("locale")
@pass_context
def memory_import_tmx(context: Context, tmx: Path, locale: str) -> None:
    """Take a TMX from an agency into memory."""
    report = absorb_tmx(context.config, tmx, locale)
    for warning in report.warnings:
        context.warn(warning)
    context.say(report.summary())


@memory.command("export-tmx")
@click.argument("tmx", type=click.Path(dir_okay=False, path_type=Path))
@click.argument("locale")
@pass_context
def memory_export_tmx(context: Context, tmx: Path, locale: str) -> None:
    """Write one language out of memory as a TMX."""
    written = export_tmx(context.config, tmx, locale)
    context.say(f"{written} pairs -> {tmx}")


@memory.command("suggest")
@click.argument("locale")
@click.argument("text")
@click.option("--threshold", type=float, default=0.75, show_default=True)
@click.option("--limit", type=int, default=5, show_default=True)
@pass_context
def memory_suggest(context: Context, locale: str, text: str, threshold: float,
                   limit: int) -> None:
    """Ask memory what it already has for a piece of English."""
    matches = suggest_for(context.config, locale, text, threshold=threshold,
                          limit=limit)
    if not matches:
        context.say("nothing close enough")
        return
    for match in matches:
        context.say(f"{match.score:.0%}  {match.target}")
        context.say(f"      against {match.source!r} from {match.origin or 'unknown'}",
                    level=1)
