import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.layout.coverage import (
    measure_coverage,
    subset_metrics,
    used_codepoints,
)
from v4t_translate.layout.font import FontMetrics, load_metrics, monospace, parse_metrics
from v4t_translate.ops.extract import extract_project

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fonts"

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
font = "fonts/latin.fmx"

[locale."zh-TW"]
font = "fonts/latin.fmx"
"""

LATIN = """\
name: latin-8
pixel_size: 8
line_height: 11
default_width: 6

20..7E 6
"""


def ascii_font():
    return monospace(6, name="ascii", ranges=[(0x20, 0x7E)])


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "fonts").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "fonts" / "latin.fmx").write_text(LATIN, encoding="utf-8")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), "font", *args,
    ])


# -- counting what is used ----------------------------------------------


def test_every_character_is_counted():
    counts = used_codepoints(["abc", "abd"])
    assert counts[ord("a")] == 2
    assert counts[ord("c")] == 1


def test_a_mnemonic_ampersand_is_not_a_glyph():
    # The panel draws an underline, not an ampersand.
    assert ord("&") not in used_codepoints(["&Print"])


def test_a_doubled_ampersand_is_one():
    assert used_codepoints(["Date&&Time"])[ord("&")] == 1


def test_tabs_and_newlines_are_not_needed():
    counts = used_codepoints(["a\tb\nc"])
    assert ord("\t") not in counts
    assert ord("\n") not in counts


def test_nothing_in_returns_nothing():
    assert used_codepoints([]) == {}


# -- the report ---------------------------------------------------------


def test_a_font_that_has_everything_is_complete():
    report = measure_coverage(ascii_font(), ["Bar Height"])
    assert report.is_complete
    assert report.fraction == 1.0


def test_a_missing_character_is_found():
    report = measure_coverage(ascii_font(), ["Balkenhöhe"])
    assert not report.is_complete
    assert "ö" in report.missing_characters()


def test_the_count_of_needed_glyphs():
    report = measure_coverage(ascii_font(), ["abc"])
    assert report.needed == 3
    assert report.covered == 3


def test_the_fraction_is_of_needed_not_of_the_font():
    report = measure_coverage(ascii_font(), ["aö"])
    assert report.fraction == 0.5


def test_missing_characters_come_out_most_used_first():
    report = measure_coverage(ascii_font(), ["ö", "ö", "ä"])
    assert report.missing_characters() == ["ö", "ä"]


def test_an_example_string_is_kept_for_each_missing_one():
    report = measure_coverage(ascii_font(), ["Balkenhöhe des Feldes", "höhe"])
    assert report.worst_first()[0][2] == "höhe"


def test_the_shortest_example_wins():
    report = measure_coverage(ascii_font(), ["a very long string with ö in it",
                                             "ö"])
    assert report.worst_first()[0][2] == "ö"


def test_unused_glyphs_are_counted():
    report = measure_coverage(ascii_font(), ["a"])
    assert report.font_size == 95
    assert report.unused == 94


def test_the_description_mentions_both_directions():
    described = measure_coverage(ascii_font(), ["a"]).describe()
    assert "1/1 needed glyphs" in described
    assert "carried but unused" in described


def test_a_complete_font_does_not_mention_missing_ones():
    report = measure_coverage(ascii_font(), ["abc"])
    assert report.worst_first() == []


def test_an_empty_project_is_complete():
    report = measure_coverage(ascii_font(), [])
    assert report.is_complete
    assert report.fraction == 1.0


# -- subsetting ---------------------------------------------------------


def test_a_subset_keeps_what_is_used():
    reduced = subset_metrics(ascii_font(), ["abc"])
    assert reduced.covers("a")
    assert reduced.covers("c")


def test_a_subset_keeps_ascii_whatever_the_catalog_says():
    # The firmware version and the IP address never went through this tool.
    reduced = subset_metrics(ascii_font(), ["abc"])
    assert reduced.covers("7")
    assert reduced.covers(".")


def test_ascii_can_be_dropped_on_purpose():
    reduced = subset_metrics(ascii_font(), ["abc"], keep_ascii=False)
    assert reduced.covers("a")
    assert not reduced.covers("7")


def test_a_subset_is_smaller():
    reduced = subset_metrics(ascii_font(), ["abc"], keep_ascii=False)
    assert reduced.coverage_size < ascii_font().coverage_size


def test_a_subset_never_invents_a_glyph():
    reduced = subset_metrics(ascii_font(), ["höhe"])
    assert not reduced.covers("ö")


def test_a_subset_keeps_the_metrics():
    font = FontMetrics(name="x", pixel_size=12, line_height=16, default_width=7)
    font.ranges.append((0x20, 0x7E))
    reduced = subset_metrics(font, ["abc"])
    assert reduced.pixel_size == 12
    assert reduced.line_height == 16
    assert reduced.default_width == 7


def test_a_subset_keeps_explicit_widths():
    font = monospace(6, ranges=[(0x20, 0x7E)])
    font.widths[ord("W")] = 9
    font.invalidate()
    assert subset_metrics(font, ["W"]).advance("W") == 9


def test_the_subset_is_named_after_its_parent():
    assert subset_metrics(ascii_font(), ["a"]).name == "ascii-subset"


def test_a_subset_round_trips_through_the_file_format():
    from v4t_translate.layout.bdf import metrics_to_fmx

    reduced = subset_metrics(ascii_font(), ["abc"], keep_ascii=False)
    reread = parse_metrics(metrics_to_fmx(reduced))
    assert reread.covers("a")
    assert not reread.covers("z")


# -- the commands -------------------------------------------------------


def test_coverage_reports_every_language(project):
    output = run(project, "coverage").output
    assert "de-DE" in output
    assert "zh-TW" in output


def test_coverage_finds_a_missing_character(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Balkenhöhe", state=TranslationState.APPROVED))
    save_translations(path, translations)

    output = run(project, "coverage", "-l", "de-DE").output
    assert "U+00F6" in output
    assert "'ö'" in output


def test_coverage_shows_where_it_hurts(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Balkenhöhe", state=TranslationState.APPROVED))
    save_translations(path, translations)

    assert "first in 'Balkenhöhe'" in run(project, "coverage", "-l", "de-DE").output


def test_coverage_is_quiet_when_everything_fits(project):
    output = run(project, "coverage", "-l", "de-DE").output
    assert "U+" not in output


def test_strict_fails_when_something_is_missing(project):
    path = project.translations_path("zh-TW")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="條碼高度", state=TranslationState.APPROVED))
    save_translations(path, translations)

    assert run(project, "coverage", "--strict").exit_code != 0


def test_strict_passes_when_nothing_is(project):
    assert run(project, "coverage", "--strict").exit_code == 0


def test_a_metrics_override_is_used(project, tmp_path):
    other = tmp_path / "digits.fmx"
    other.write_text("name: digits\npixel_size: 8\ndefault_width: 6\n\n30..39 6\n",
                     encoding="utf-8")
    output = run(project, "coverage", "-l", "de-DE", "--metrics", str(other)).output
    assert "digits" in output


def test_subset_writes_a_smaller_file(project, tmp_path):
    out = tmp_path / "latin-subset.fmx"
    result = run(project, "subset", str(project.root / "fonts" / "latin.fmx"),
                 str(out))
    assert result.exit_code == 0
    assert out.exists()
    assert load_metrics(out).coverage_size <= 95


def test_the_subset_still_covers_the_catalog(project, tmp_path):
    out = tmp_path / "latin-subset.fmx"
    run(project, "subset", str(project.root / "fonts" / "latin.fmx"), str(out))

    from v4t_translate.catalog.store import load_catalog

    catalog = load_catalog(project.catalog_path())
    texts = [m.source_text for m in catalog.messages.values()]
    assert measure_coverage(load_metrics(out), texts).is_complete


def test_subset_says_what_it_dropped(project, tmp_path):
    out = tmp_path / "latin-subset.fmx"
    output = run(project, "subset", str(project.root / "fonts" / "latin.fmx"),
                 str(out)).output
    assert "down from 95" in output


def test_both_commands_are_in_the_help(project):
    output = run(project, "--help").output
    assert "coverage" in output
    assert "subset" in output
