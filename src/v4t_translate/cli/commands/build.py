"""``build``: produce every configured output."""

from __future__ import annotations

from pathlib import Path

import click

from ... import __version__
from ...emit.manifest import MANIFEST_NAME, build_manifest
from ...ops.build import BuildResult, build_project, check_before_build
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
@pass_context
def build(context: Context, locales: tuple[str, ...], dry_run: bool,
          no_check: bool, manifest_path: Path | None) -> None:
    """Produce every configured output."""
    wanted = list(locales) or None
    config = context.config

    if not no_check:
        check_before_build(config, locales=wanted)

    result = build_project(config, locales=wanted, dry_run=dry_run)
    report(context, result, dry_run=dry_run)

    if manifest_path is None or dry_run:
        return

    manifest = build_manifest(config, result, tool_version=__version__)
    destination = manifest_path
    if not destination.is_absolute():
        destination = config.root / config.output_dir / destination

    manifest.write(destination)
    context.say(f"{manifest.summary()} -> {destination}")


def report(context: Context, result: BuildResult, *, dry_run: bool) -> None:
    for warning in result.warnings:
        context.warn(warning)

    for tag, kind, emitted in result.outputs:
        context.say(f"{tag} {kind}: {emitted.summary()}")

    context.say(f"{result.summary()}, {result.total_bytes} bytes", level=1)

    if dry_run:
        context.say("dry run, nothing written")
