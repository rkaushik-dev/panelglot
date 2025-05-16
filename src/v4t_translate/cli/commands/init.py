"""``init``: scaffold a new localisation project."""

from __future__ import annotations

from pathlib import Path

import click

from ...ops.init import init_project
from ..context import Context, pass_context

__all__ = ["init"]


@click.command()
@click.argument("directory", default=".",
                type=click.Path(file_okay=False, path_type=Path))
@click.option("--name", "-n", required=True, help="The project name, e.g. V4T-TIJ.")
@click.option("--source", "-s", "sources", multiple=True, metavar="KIND:PATH",
              help="A file to read. Repeatable. For example rc:../V4T/V4T.rc.")
@click.option("--locale", "-l", "locales", multiple=True,
              help="A target language. Repeatable.")
@click.option("--no-gitignore", is_flag=True, help="Leave .gitignore alone.")
@pass_context
def init(context: Context, directory: Path, name: str, sources: tuple[str, ...],
         locales: tuple[str, ...], no_gitignore: bool) -> None:
    """Scaffold a new localisation project."""
    parsed = [_split(entry) for entry in sources]

    result = init_project(
        directory, name=name, sources=parsed, locales=list(locales),
        write_gitignore=not no_gitignore,
    )

    for path in result.written:
        context.say(f"wrote {path}")
    for path in result.skipped:
        context.say(f"left alone {path}", level=1)

    context.say(result.summary(), level=1)

    if not parsed:
        context.say("Add a [[source]] to v4t-translate.toml, then run extract.")


def _split(entry: str) -> tuple[str, str]:
    kind, separator, path = entry.partition(":")
    if not separator or not path:
        raise click.BadParameter(
            f"{entry!r} should look like rc:../V4T-TIJ/V4T/V4T.rc", param_hint="--source"
        )
    return (kind, path)
