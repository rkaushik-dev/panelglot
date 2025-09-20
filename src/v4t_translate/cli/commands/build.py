"""``build``: produce every configured output."""

from __future__ import annotations

from pathlib import Path

import click

from ... import __version__
from ...emit.manifest import MANIFEST_NAME, build_manifest
from ...errors import CheckFailed
from ...ops.build import (
    BuildResult,
    build_project,
    check_before_build,
    unreproducible_outputs,
)
from ...reproducible import is_pinned
from ..context import Context, pass_context

__all__ = ["build"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable. Defaults to all of them.")
@click.option("--dry-run", is_flag=True, help="Report what would be built, write nothing.")
@click.option("--no-check", is_flag=True,
              help="Build even when check is failing. You had better mean it.")
@click.option("--manifest", "manifest_path", is_flag=False, flag_value=MANIFEST_NAME,
              default=None, type=click.Path(dir_okay=False, path_type=Path),
              help="Also write a manifest of what was built. Defaults to "
                   f"{MANIFEST_NAME} in the output directory.")
@click.option("--reproducible", is_flag=True,
              help="Build everything twice and fail if the bytes differ. "
                   "Set SOURCE_DATE_EPOCH first or the stamps will.")
@pass_context
def build(context: Context, locales: tuple[str, ...], dry_run: bool,
          no_check: bool, manifest_path: Path | None,
          reproducible: bool) -> None:
    """Produce every configured output."""
    wanted = list(locales) or None
    config = context.config

    if reproducible:
        _check_reproducible(context, config, wanted)

    if not no_check:
        with context.step("check-before-build"):
            check_before_build(config, locales=wanted)

    with context.step("build", dry_run=dry_run) as fields:
        result = build_project(config, locales=wanted, dry_run=dry_run)
        fields["outputs"] = len(result.outputs)
        fields["bytes"] = result.total_bytes
        fields["locales"] = len(result.locales())

    report(context, result, dry_run=dry_run)

    if manifest_path is None or dry_run:
        return

    manifest = build_manifest(config, result, tool_version=__version__)
    destination = manifest_path
    if not destination.is_absolute():
        destination = config.root / config.output_dir / destination

    manifest.write(destination)
    context.say(f"{manifest.summary()} -> {destination}")


def _check_reproducible(context: Context, config, wanted: list[str] | None) -> None:
    """Build twice into memory and complain if the two disagree."""
    if not is_pinned():
        context.warn(
            "SOURCE_DATE_EPOCH is not set, so anything that stamps a date will "
            "differ between the two builds and this will report it. Set it to "
            "the commit time."
        )

    with context.step("reproducible-check") as fields:
        problems = unreproducible_outputs(config, locales=wanted)
        fields["differing"] = len(problems)

    if not problems:
        context.say("built twice, byte for byte the same")
        return

    for name in problems:
        context.warn(f"{name} differs between two builds of the same input")

    raise CheckFailed(
        f"{len(problems)} outputs are not reproducible",
        error_count=len(problems),
    )


def report(context: Context, result: BuildResult, *, dry_run: bool) -> None:
    for warning in result.warnings:
        context.warn(warning)

    for tag, kind, emitted in result.outputs:
        context.say(f"{tag} {kind}: {emitted.summary()}")

    context.say(f"{result.summary()}, {result.total_bytes} bytes", level=1)

    if dry_run:
        context.say("dry run, nothing written")
