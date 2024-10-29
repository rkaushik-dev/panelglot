"""Command line entry points.

Every command is a thin wrapper: resolve the config, call one function in
:mod:`v4t_translate.ops`, print the result. If a command starts making
decisions, the decision belongs in ops and the command is doing it wrong.

Errors from the package come out as a message and an exit code, not a
traceback. ``--traceback`` puts the traceback back for the times a message is
not enough.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .config import ProjectConfig, load_config
from .errors import CheckFailed, V4TError
from .ops.check import check_project
from .ops.extract import ExtractResult, extract_project
from .report.console import DEFAULT_LIMIT, format_check

__all__ = ["main"]


class Context:
    """State shared by every command."""

    def __init__(self, config_path: Path | None, verbose: int, quiet: bool,
                 traceback: bool) -> None:
        self.config_path = config_path
        self.verbose = verbose
        self.quiet = quiet
        self.traceback = traceback
        self._config: ProjectConfig | None = None

    @property
    def config(self) -> ProjectConfig:
        if self._config is None:
            self._config = load_config(self.config_path)
        return self._config

    def say(self, message: str, *, level: int = 0) -> None:
        """Print unless quiet, and unless it needs more -v than we were given."""
        if self.quiet or level > self.verbose:
            return
        click.echo(message)

    def warn(self, message: str) -> None:
        # --quiet says only errors, and a warning is not one. Suppressing it
        # here rather than at each call site is what keeps -q honest.
        if self.quiet:
            return
        click.echo(click.style("warning: ", fg="yellow") + message, err=True)


pass_context = click.make_pass_decorator(Context)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
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


@main.command()
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@click.option("--keep-going", is_flag=True, help="Skip sources that cannot be read.")
@pass_context
def extract(context: Context, dry_run: bool, keep_going: bool) -> None:
    """Read every source and update the catalog."""
    result = extract_project(context.config, dry_run=dry_run, keep_going=keep_going)
    _report_extract(context, result, dry_run=dry_run)


@main.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable. Defaults to all of them.")
@click.option("--limit", type=int, default=DEFAULT_LIMIT, show_default=True,
              help="Findings shown per rule. 0 for all of them.")
@click.option("--no-detail", is_flag=True, help="One line per finding.")
@click.option("--fail-on", type=click.Choice(["error", "warning", "never"]),
              help="Override the project's fail_on setting.")
@pass_context
def check(context: Context, locales: tuple[str, ...], limit: int, no_detail: bool,
          fail_on: str | None) -> None:
    """Run every rule over the translated catalog."""
    config = context.config
    result = check_project(config, locales=list(locales) or None)

    for warning in result.warnings:
        context.warn(warning)

    if not context.quiet:
        click.echo(format_check(result, limit=limit, show_detail=not no_detail))

    threshold = fail_on or config.check.fail_on
    if result.should_fail(threshold):
        raise CheckFailed(
            f"{len(result.report.errors)} errors and "
            f"{len(result.report.warnings)} warnings",
            error_count=len(result.report.errors),
            warning_count=len(result.report.warnings),
        )


def _report_extract(context: Context, result: ExtractResult, *, dry_run: bool) -> None:
    for skipped in result.skipped:
        context.warn(f"skipped {skipped}")
    for warning in result.warnings:
        context.warn(warning)

    for source, stats in result.stats_by_source().items():
        summary = ", ".join(f"{value} {name}" for name, value in stats.items() if value)
        context.say(f"  {source}: {summary}", level=1)

    context.say(f"{result.message_count} messages: {result.report.summary()}")

    for old_key, new_key in result.report.rewordings:
        context.say(f"  carried {old_key} -> {new_key}", level=1)

    if dry_run:
        context.say("dry run, nothing written")
        return

    for path in result.written:
        context.say(f"wrote {path}", level=1)


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
