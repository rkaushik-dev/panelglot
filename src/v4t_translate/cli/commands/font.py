"""``font``: build and inspect the metrics the fitting check measures with."""

from __future__ import annotations

from pathlib import Path

import click

from ...layout.bdf import load_bdf, metrics_to_fmx
from ...layout.font import load_metrics
from ...layout.measure import drawn_text
from ..context import Context, pass_context

__all__ = ["font"]


@click.group()
def font() -> None:
    """Build and inspect panel font metrics."""


@font.command("build")
@click.argument("bdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output", type=click.Path(dir_okay=False, path_type=Path))
@pass_context
def font_build(context: Context, bdf: Path, output: Path) -> None:
    """Turn a BDF font into a .fmx metrics file."""
    metrics = load_bdf(bdf)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(metrics_to_fmx(metrics, source=bdf.name), encoding="utf-8")

    context.say(
        f"{output}: {metrics.name}, {metrics.coverage_size} glyphs, "
        f"default width {metrics.default_width}"
    )


@font.command("show")
@click.argument("metrics", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--text", "-t", help="Measure this string as well.")
@pass_context
def font_show(context: Context, metrics: Path, text: str | None) -> None:
    """Report what a metrics file holds."""
    font_metrics = load_metrics(metrics)

    context.say(
        f"{font_metrics.name}: {font_metrics.coverage_size} glyphs, "
        f"{font_metrics.pixel_size}px, line height {font_metrics.line_height}, "
        f"default width {font_metrics.default_width}"
    )

    if text is None:
        return

    drawn = drawn_text(text)
    missing = font_metrics.missing(drawn)

    context.say(f"{text!r} is {font_metrics.measure(drawn)}px wide")
    if missing:
        listed = ", ".join(f"{c!r} (U+{ord(c):04X})" for c in missing)
        context.say(f"not in this font: {listed}")
