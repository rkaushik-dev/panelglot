"""``font``: build and inspect the metrics the fitting check measures with."""

from __future__ import annotations

from pathlib import Path

import click

from ...catalog.store import load_catalog, load_translations
from ...errors import CheckFailed
from ...layout.bdf import load_bdf, metrics_to_fmx
from ...layout.coverage import measure_coverage, subset_metrics
from ...layout.font import load_metrics
from ...layout.measure import drawn_text
from ...layout.panels import font_for, get_panel
from ..context import Context, pass_context

__all__ = ["font"]

#: Missing characters listed before the rest are counted instead.
LISTING_LIMIT = 20


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


@font.command("coverage")
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable. Defaults to all of them.")
@click.option("--metrics", type=click.Path(exists=True, dir_okay=False,
                                           path_type=Path),
              help="Measure against this file instead of the configured font.")
@click.option("--source", "include_source", is_flag=True,
              help="Count the English too. It ships on an untranslated panel.")
@click.option("--strict", is_flag=True,
              help="Exit non-zero when anything is missing. For CI.")
@pass_context
def font_coverage(context: Context, locales: tuple[str, ...], metrics: Path | None,
                  include_source: bool, strict: bool) -> None:
    """Say which characters this project needs and the font does not have."""
    config = context.config
    catalog = load_catalog(config.catalog_path())
    incomplete = 0

    for tag in locales or config.target_tags():
        entry = config.locale_entry(tag)
        texts = _texts(config, catalog, tag, include_source=include_source)
        font_metrics = _metrics_for(config, entry, metrics)

        report = measure_coverage(font_metrics, texts)
        context.say(f"{tag}: {report.describe()}")

        if report.is_complete:
            continue

        incomplete += 1
        for char, uses, example in report.worst_first()[:LISTING_LIMIT]:
            context.say(
                f"    U+{ord(char):04X} {char!r} used {uses} times, "
                f"first in {example!r}"
            )

        hidden = len(report.missing_codepoints) - LISTING_LIMIT
        if hidden > 0:
            context.say(f"    ... and {hidden} more")

    if strict and incomplete:
        raise CheckFailed(
            f"{incomplete} languages need glyphs this font does not have",
            error_count=incomplete,
        )


@font.command("subset")
@click.argument("metrics", type=click.Path(exists=True, dir_okay=False,
                                           path_type=Path))
@click.argument("output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only these languages need to fit. Repeatable.")
@click.option("--no-ascii", is_flag=True,
              help="Drop ASCII too. Almost always wrong; see the docs.")
@pass_context
def font_subset(context: Context, metrics: Path, output: Path,
                locales: tuple[str, ...], no_ascii: bool) -> None:
    """Write a metrics file carrying only the glyphs this project draws."""
    config = context.config
    catalog = load_catalog(config.catalog_path())

    texts: list[str] = []
    for tag in locales or config.target_tags():
        texts.extend(_texts(config, catalog, tag, include_source=True))

    full = load_metrics(metrics)
    reduced = subset_metrics(full, texts, keep_ascii=not no_ascii)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(metrics_to_fmx(reduced, source=metrics.name),
                      encoding="utf-8")

    context.say(
        f"{output}: {reduced.coverage_size} glyphs, down from "
        f"{full.coverage_size}"
    )


def _texts(config, catalog, tag: str, *, include_source: bool) -> list[str]:
    """Every string this language would draw on a panel."""
    translations = load_translations(config.translations_path(tag))

    texts: list[str] = []
    for key, message in catalog.messages.items():
        translated = translations.get(key).text
        if translated:
            texts.append(translated)
        if include_source or not translated:
            # An untranslated message falls back to English at build time, so
            # its characters are drawn whether or not anybody wanted them to be.
            texts.append(message.source_text)

    return texts


def _metrics_for(config, entry, override: Path | None):
    if override is not None:
        return load_metrics(override)

    panel = get_panel(entry.panel or "tij-800x600")
    explicit = (config.root / entry.font) if entry.font else None
    if explicit is not None and not explicit.exists():
        explicit = None

    return font_for(panel, search=[config.root / "fonts", config.root],
                    explicit=explicit)
