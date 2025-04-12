"""Command line entry points.

Every command is a thin wrapper: resolve the config, call one function in
:mod:`v4t_translate.ops`, print the result. If a command starts making
decisions, the decision belongs in ops and the command is doing it wrong.

Errors from the package come out as a message and an exit code, not a
traceback. ``--traceback`` puts the traceback back for the times a message is
not enough.

This was one module until it reached six hundred lines and four people had
edited it in the same week. It is a package now, one module per command, and
the only thing here is the group they hang off.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .. import __version__
from ..errors import V4TError
from .commands import register
from .context import Context, pass_context

__all__ = ["main", "run", "Context", "pass_context"]


class OrderedGroup(click.Group):
    """A group that lists its commands in the order they were added.

    Click sorts alphabetically, which put build at the top of the help. Build
    is the last thing anybody runs and having it first made the help read like
    the workflow starts there.
    """

    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)


@click.group(cls=OrderedGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="v4t-translate")
@click.option(
    "--config", "-c", "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Project file. Defaults to searching upward for v4t-translate.toml.",
)
@click.option("--verbose", "-v", count=True, help="More detail. Repeatable.")
@click.option("--quiet", "-q", is_flag=True, help="Only errors.")
@click.option("--traceback", is_flag=True, help="Show the traceback on failure.")
@click.pass_context
def main(ctx: click.Context, config_path: Path | None, verbose: int, quiet: bool,
         traceback: bool) -> None:
    """Localisation toolchain for the V4T coder family."""
    ctx.obj = Context(config_path, verbose, quiet, traceback)


register(main)


def run(argv: list[str] | None = None) -> int:
    """Invoke the CLI and turn package errors into exit codes.

    ``--traceback`` is read straight off the argument list rather than from
    the parsed context, because the errors most worth a traceback are the ones
    thrown before the context exists.
    """
    arguments = sys.argv[1:] if argv is None else argv
    show_traceback = "--traceback" in arguments

    try:
        main.main(args=arguments, standalone_mode=False)
    except V4TError as exc:
        if show_traceback:
            raise
        click.echo(click.style("error: ", fg="red") + str(exc), err=True)
        return exc.exit_code
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("aborted", err=True)
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
