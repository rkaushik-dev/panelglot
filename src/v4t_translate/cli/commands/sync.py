"""``export`` and ``import``: the workbook round trip."""

from __future__ import annotations

from pathlib import Path

import click

from ...errors import CheckFailed
from ...ops.sync import (
    ImportResult,
    export_workbooks,
    import_workbook,
    import_xliff_file,
)
from ..context import Context, pass_context

__all__ = ["export", "import_", "XLIFF_SUFFIXES"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable.")
@click.option("--outstanding", is_flag=True,
              help="Leave out anything already approved. For a follow-up round.")
@click.option("--since", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="A saved catalog. Rows that changed since it are coloured.")
@click.option("--parts", type=int, default=1, show_default=True,
              help="Split each language across this many sheets, keeping every "
                   "dialog whole. They merge back on import.")
@pass_context
def export(context: Context, locales: tuple[str, ...], outstanding: bool,
           since: Path | None, parts: int) -> None:
    """Write the workbook a translator gets sent."""
    if parts < 1:
        raise click.UsageError("--parts has to be at least 1")

    result = export_workbooks(
        context.config, locales=list(locales) or None, only_outstanding=outstanding,
        since=since, parts=parts,
    )
    for tag, path, rows in result.written:
        context.say(f"{tag}: {rows} rows -> {path}")

    if parts > 1:
        context.say(
            "Parts are split by dialog, so they come out uneven. A dialog is "
            "one person's afternoon: its labels have to agree with each other "
            "and its Alt keys have to be distinct, and two people cannot do "
            "that between them.",
            level=1,
        )


#: Suffixes that mean the delivery is XLIFF rather than a spreadsheet.
XLIFF_SUFFIXES = (".xlf", ".xliff")


@click.command("import")
@click.argument("delivery", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", "-l", help="Insist the delivery is this language.")
@click.option("--sheet", help="Sheet name. Defaults to the first one. Workbooks only.")
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@click.option("--draft", is_flag=True, help="Land rows as draft rather than approved.")
@click.option("--strict", is_flag=True,
              help="Fail if any row matched nothing or matched more than one message.")
@pass_context
def import_(context: Context, delivery: Path, locale: str | None, sheet: str | None,
            dry_run: bool, draft: bool, strict: bool) -> None:
    """Read a delivered workbook or XLIFF file back into the catalog."""
    if delivery.suffix.lower() in XLIFF_SUFFIXES:
        if sheet is not None:
            context.warn("--sheet means nothing for an XLIFF delivery, ignored")
        result = import_xliff_file(
            context.config, delivery, locale=locale,
            dry_run=dry_run, approve=not draft,
        )
    else:
        result = import_workbook(
            context.config, delivery, locale=locale, sheet=sheet,
            dry_run=dry_run, approve=not draft,
        )

    report(context, result, dry_run=dry_run)

    if strict and not result.is_clean():
        raise CheckFailed(
            f"{len(result.unmatched)} rows matched nothing and "
            f"{len(result.ambiguous)} were ambiguous",
            error_count=len(result.unmatched) + len(result.ambiguous),
        )


def report(context: Context, result: ImportResult, *, dry_run: bool) -> None:
    for warning in result.warnings:
        context.warn(warning)

    for row in result.unmatched:
        context.warn(f"row {row.row}: {row.source!r} matches no message, ignored")

    if result.unmatched:
        context.say(
            "A delivery is made against a catalog. Rows that match nothing are "
            "usually strings that were removed after it went out.",
            level=1,
        )

    for row, keys in result.ambiguous:
        context.warn(
            f"row {row.row}: {row.source!r} matches {len(keys)} messages "
            f"({', '.join(keys)}), ignored"
        )

    context.say(f"{result.locale}: {result.summary()}")

    for key in result.applied:
        context.say(f"  applied {key}", level=2)

    if dry_run:
        context.say("dry run, nothing written")
    elif result.written is not None:
        context.say(f"wrote {result.written}", level=1)
