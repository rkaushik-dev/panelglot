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
from .ops.build import BuildResult, build_project, check_before_build
from .ops.check import check_project
from .ops.extract import ExtractResult, extract_project
from .ops.pretranslate import pretranslate_project
from .ops.stats import project_stats
from .ops.sync import ImportResult, export_workbooks, import_workbook
from .report.console import DEFAULT_LIMIT, format_check
from .report.structured import check_to_json, report_to_junit

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
@click.option("--format", "output_format",
              type=click.Choice(["text", "json", "junit"]), default="text",
              show_default=True, help="How to print the findings.")
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path),
              help="Write the report here instead of to the terminal.")
@pass_context
def check(context: Context, locales: tuple[str, ...], limit: int, no_detail: bool,
          fail_on: str | None, output_format: str, output: Path | None) -> None:
    """Run every rule over the translated catalog."""
    config = context.config
    result = check_project(config, locales=list(locales) or None)

    for warning in result.warnings:
        context.warn(warning)

    text = _format_check(result, output_format, limit=limit, detail=not no_detail)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        context.say(f"wrote {output}", level=1)
    elif not context.quiet:
        click.echo(text)

    threshold = fail_on or config.check.fail_on
    if result.should_fail(threshold):
        raise CheckFailed(
            f"{len(result.report.errors)} errors and "
            f"{len(result.report.warnings)} warnings",
            error_count=len(result.report.errors),
            warning_count=len(result.report.warnings),
        )


def _format_check(result, output_format: str, *, limit: int, detail: bool) -> str:
    if output_format == "json":
        return check_to_json(result)
    if output_format == "junit":
        return report_to_junit(result.report)
    return format_check(result, limit=limit, show_detail=detail)


@main.command()
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


@main.command()
@click.argument("locale")
@click.option("--provider", "-p",
              help="Machine translation provider for what memory cannot fill. "
                   "Built in: passthrough, pseudo.")
@click.option("--trust-memory", is_flag=True,
              help="Land exact memory hits as approved rather than needs-review.")
@click.option("--threshold", type=float, default=0.75, show_default=True,
              help="How close a fuzzy memory match has to be.")
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@pass_context
def pretranslate(context: Context, locale: str, provider: str | None,
                 trust_memory: bool, threshold: float, dry_run: bool) -> None:
    """Fill one language from translation memory, and optionally a provider."""
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


@main.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable. Defaults to all of them.")
@click.option("--dry-run", is_flag=True, help="Report what would be built, write nothing.")
@click.option("--no-check", is_flag=True,
              help="Build even when check is failing. You had better mean it.")
@pass_context
def build(context: Context, locales: tuple[str, ...], dry_run: bool,
          no_check: bool) -> None:
    """Produce every configured output."""
    wanted = list(locales) or None

    if not no_check:
        check_before_build(context.config, locales=wanted)

    result = build_project(context.config, locales=wanted, dry_run=dry_run)
    _report_build(context, result, dry_run=dry_run)


def _report_build(context: Context, result: BuildResult, *, dry_run: bool) -> None:
    for warning in result.warnings:
        context.warn(warning)

    for tag, kind, emitted in result.outputs:
        context.say(f"{tag} {kind}: {emitted.summary()}")

    context.say(f"{result.summary()}, {result.total_bytes} bytes", level=1)

    if dry_run:
        context.say("dry run, nothing written")


@main.command()
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


@main.command("import")
@click.argument("workbook", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", "-l", help="Insist the sheet is this language.")
@click.option("--sheet", help="Sheet name. Defaults to the first one.")
@click.option("--dry-run", is_flag=True, help="Report what would change, write nothing.")
@click.option("--draft", is_flag=True,
              help="Land rows as draft rather than approved.")
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
    _report_import(context, result, dry_run=dry_run)

    if strict and not result.is_clean():
        raise CheckFailed(
            f"{len(result.unmatched)} rows matched nothing and "
            f"{len(result.ambiguous)} were ambiguous",
            error_count=len(result.unmatched) + len(result.ambiguous),
        )


def _report_import(context: Context, result: ImportResult, *, dry_run: bool) -> None:
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
