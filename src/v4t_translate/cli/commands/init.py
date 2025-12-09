"""``init``: scaffold a new localisation project."""

from __future__ import annotations

from pathlib import Path

import click

from ...ops.discover import discover_sources
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
@click.option("--from", "search", metavar="DIRECTORY",
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Look for sources in here instead of being told them.")
@click.option("--yes", is_flag=True,
              help="Take what --from found without asking.")
@pass_context
def init(context: Context, directory: Path, name: str, sources: tuple[str, ...],
         locales: tuple[str, ...], no_gitignore: bool, search: Path | None,
         yes: bool) -> None:
    """Scaffold a new localisation project."""
    parsed = [_split(entry) for entry in sources]

    if search is not None:
        parsed.extend(_discovered(context, search, directory, confirmed=yes))

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


def _discovered(context: Context, search: Path, directory: Path, *,
                confirmed: bool) -> list[tuple[str, str]]:
    """What a walk of ``search`` found, once somebody has agreed to it.

    Confirmed rather than written straight in. Guessing which of forty header
    files is the string table and writing the answer silently is how a project
    ends up reading the wrong one for a year.
    """
    found = discover_sources(search)

    for entry in found.sources:
        context.say(entry.describe())
    for note in found.skipped:
        context.say(f"  not a source: {note}", level=1)

    if found.included:
        context.say(
            f"  read through the main script: {', '.join(found.included)}",
            level=1,
        )

    context.say(found.summary())

    if not found.sources:
        return []

    if not confirmed and not click.confirm("Use these?", default=True):
        return []

    return [(entry.kind, _relative(search / entry.path, directory))
            for entry in found.sources]


def _relative(target: Path, directory: Path) -> str:
    """A source path as the config should hold it.

    Relative to the project directory where that is expressible, because the
    two trees are usually siblings in one checkout and an absolute path is a
    path that works on exactly one machine.
    """
    import os

    try:
        return Path(os.path.relpath(target.resolve(),
                                    directory.resolve())).as_posix()
    except ValueError:
        # A different drive on Windows. Nothing relative to say.
        return target.resolve().as_posix()


def _split(entry: str) -> tuple[str, str]:
    kind, separator, path = entry.partition(":")
    if not separator or not path:
        raise click.BadParameter(
            f"{entry!r} should look like rc:../V4T-TIJ/V4T/V4T.rc", param_hint="--source"
        )
    return (kind, path)
