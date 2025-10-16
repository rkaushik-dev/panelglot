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

from ..diagnostics import Diagnostics, path_from_environment
from ..errors import V4TError
from ..versions import describe
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


def _version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    """Print the version, or the whole build when -v came first.

    The question people ask is never what version it is. It is why this
    machine behaves differently from that one, and the answer is usually one
    of the three format numbers rather than the package version.
    """
    del param
    if not value or ctx.resilient_parsing:
        return

    detailed = "-v" in sys.argv or "--verbose" in sys.argv
    click.echo(describe(detailed=detailed))
    ctx.exit()


@click.group(cls=OrderedGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--version", "-V", is_flag=True, expose_value=False, is_eager=True,
              callback=_version,
              help="Print the version. With -v, the whole build.")
@click.option(
    "--config", "-c", "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Project file. Defaults to searching upward for v4t-translate.toml.",
)
@click.option("--verbose", "-v", count=True, help="More detail. Repeatable.")
@click.option("--quiet", "-q", is_flag=True, help="Only errors.")
@click.option("--traceback", is_flag=True, help="Show the traceback on failure.")
@click.option("--log-file", type=click.Path(dir_okay=False, path_type=Path),
              help="Append a JSON line per step. For the runs nobody watches. "
                   "V4T_LOG in the environment does the same thing.")
@click.option("--timings", is_flag=True,
              help="Print where the time went when the command finishes.")
@click.pass_context
def main(ctx: click.Context, config_path: Path | None, verbose: int, quiet: bool,
         traceback: bool, log_file: Path | None, timings: bool) -> None:
    """Localisation toolchain for the V4T coder family."""
    context = Context(config_path, verbose, quiet, traceback,
                      diagnostics=Diagnostics(log_file or path_from_environment()),
                      timings=timings)
    ctx.obj = context

    # Closed on the way out however the command ended, including the failures,
    # which are the ones the log is for.
    ctx.call_on_close(context.finish)


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
        if exc.remedy:
            # On its own line because it is an instruction and the line above
            # is a statement about the past. Run together they read as one
            # long sentence that ends in a suggestion nobody notices.
            click.echo(f"  try: {exc.remedy}", err=True)
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
