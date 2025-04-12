"""``export`` and ``import``: the workbook round trip."""

from __future__ import annotations

from pathlib import Path

import click

from ...errors import CheckFailed
from ...ops.sync import ImportResult, export_workbooks, import_workbook
from ..context import Context, pass_context

__all__ = ["export", "import_"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable.")
@click.option("--outstanding", is_flag=True,
              help="Leave out anything already approved. For a follow-up round.")
@pass_context
def export(context: Context, locales: tuple[str, ...], outstanding: bool) -> None:
    """Write the workbook a translator gets sent."""
    result = export_workbooks(
        context.config, locales=list(locales) or None, only_outstanding=outstanding
    )
    for tag, path, rows in result.written:
        context.say(f"{tag}: {rows} rows -> {path}")


@click.command("import")
@click.argument("workbook", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", "-l", help="Insist the sheet is this language.")
@click.option("--sheet", help="Sheet name. Defaults to the first one.")
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@click.option("--draft", is_flag=True, help="Land rows as draft rather than approved.")
@click.option("--strict", is_flag=True,
              help="Fail if any row matched nothing or matched more than one message.")
@pass_context
def import_(context: Context, workbook: Path, locale: str | None, sheet: str | None,
            dry_run: bool, draft: bool, strict: bool) -> None:
    """Read a delivered workbook back into the catalog."""
    result = import_workbook(
        context.config, workbook, locale=locale, sheet=sheet,
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
