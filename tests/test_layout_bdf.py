import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.errors import SourceError
from v4t_translate.layout.bdf import load_bdf, metrics_to_fmx, read_bdf
from v4t_translate.layout.font import parse_metrics

MINIMAL = """\
STARTFONT 2.1
FONT -foundry-Tiny-medium-r-normal--8-80-75-75-C-50-iso10646-1
SIZE 8 75 75
FONTBOUNDINGBOX 6 9 0 -1
STARTCHAR A
ENCODING 65
DWIDTH 6 0
BBX 5 7 0 0
BITMAP
70
ENDCHAR
ENDFONT
"""


@pytest.fixture(scope="module")
def bdf_path(fixtures_dir):
    return fixtures_dir / "fonts" / "mini-5x7.bdf"


@pytest.fixture(scope="module")
def metrics(bdf_path):
    return load_bdf(bdf_path)


def test_the_family_name_comes_from_the_xlfd(metrics):
    assert metrics.name == "Mini 5x7"


def test_the_pixel_size(metrics):
    assert metrics.pixel_size == 7


def test_the_line_height_comes_from_the_bounding_box(metrics):
    assert metrics.line_height == 8


def test_advances_come_from_dwidth_not_the_bounding_box(metrics):
    # A is BBX 5 wide and DWIDTH 6. The advance is 6.
    assert metrics.advance("A") == 6
    assert metrics.advance("W") == 9
    assert metrics.advance(" ") == 3


def test_a_glyph_with_no_encoding_is_not_a_codepoint(metrics):
    # The notdef glyph is ENCODING -1 and must not become a character.
    assert metrics.coverage_size == 5


def test_coverage(metrics):
    assert metrics.covers("A")
    assert metrics.covers("W")
    assert not metrics.covers("Z")
    assert metrics.missing("AWB") == []
    assert metrics.missing("Zebra") == ["Z", "e", "b", "r", "a"]


def test_the_default_width_breaks_a_tie_toward_the_wider_glyph(metrics):
    # Two glyphs at 3, two at 6, one at 9. Charging 3 for an unmeasured
    # character would make strings look shorter than they are.
    assert metrics.default_width == 6


def test_measuring_a_string(metrics):
    assert metrics.measure("AB") == 12
    assert metrics.measure("A B") == 15


def test_a_minimal_font_parses():
    metrics = read_bdf(MINIMAL)
    assert metrics.name == "Tiny"
    assert metrics.advance("A") == 6


def test_something_that_is_not_a_bdf():
    with pytest.raises(SourceError, match="not a BDF font"):
        read_bdf("name: Tahoma\n41 6\n")


def test_a_bdf_with_no_usable_glyphs():
    with pytest.raises(SourceError, match="no glyphs"):
        read_bdf("STARTFONT 2.1\nFONT x\nENDFONT\n")


def test_a_non_numeric_field_is_reported():
    with pytest.raises(SourceError, match="expected a number"):
        read_bdf("STARTFONT 2.1\nPIXEL_SIZE large\nENDFONT\n")


def test_a_missing_file(tmp_path):
    with pytest.raises(SourceError, match="does not exist"):
        load_bdf(tmp_path / "nope.bdf")


def test_bitmap_rows_are_not_read_as_keywords():
    # A bitmap row of "A0" would otherwise look like a STARTCHAR name and a
    # row of "F0" like nothing at all. Both have to be skipped.
    text = MINIMAL.replace("70\nENDCHAR", "70\nA0\nF0\nENCODING 999\nENDCHAR")
    metrics = read_bdf(text)
    assert not metrics.covers(chr(999))


def test_the_fmx_output_reads_back(metrics):
    reparsed = parse_metrics(metrics_to_fmx(metrics, source="mini-5x7.bdf"))
    assert reparsed.name == metrics.name
    assert reparsed.pixel_size == metrics.pixel_size
    assert reparsed.line_height == metrics.line_height
    assert reparsed.advance("A") == metrics.advance("A")
    assert reparsed.advance("W") == metrics.advance("W")
    assert reparsed.coverage_size == metrics.coverage_size


def test_the_fmx_output_names_where_it_came_from(metrics):
    assert "mini-5x7.bdf" in metrics_to_fmx(metrics, source="mini-5x7.bdf")


def test_the_fmx_output_collapses_runs():
    text = "STARTFONT 2.1\nFONT x\n"
    for codepoint in range(0x41, 0x5B):
        text += f"STARTCHAR c\nENCODING {codepoint}\nDWIDTH 6 0\nENDCHAR\n"
    text += "ENDFONT\n"

    fmx = metrics_to_fmx(read_bdf(text))
    assert "0041..005A 6" in fmx


def test_a_run_broken_by_a_different_width():
    text = "STARTFONT 2.1\nFONT x\n"
    for codepoint, width in ((0x41, 6), (0x42, 6), (0x43, 9), (0x44, 6)):
        text += f"STARTCHAR c\nENCODING {codepoint}\nDWIDTH {width} 0\nENDCHAR\n"
    text += "ENDFONT\n"

    fmx = metrics_to_fmx(read_bdf(text))
    assert "0041..0042 6" in fmx
    assert "0043 9" in fmx
    assert "0044 6" in fmx


def test_the_command_line_build(tmp_path, bdf_path):
    out = tmp_path / "fonts" / "mini-5x7.fmx"
    runner = CliRunner()
    result = runner.invoke(main, ["font", "build", str(bdf_path), str(out)])

    assert result.exit_code == 0
    assert out.exists()
    assert "Mini 5x7" in result.output
    assert "5 glyphs" in result.output


def test_the_command_line_show(fixtures_dir):
    runner = CliRunner()
    result = runner.invoke(main, [
        "font", "show", str(fixtures_dir / "fonts" / "tahoma-8.fmx"),
    ])
    assert result.exit_code == 0
    assert "Tahoma" in result.output


def test_the_command_line_show_measures_a_string(fixtures_dir):
    runner = CliRunner()
    result = runner.invoke(main, [
        "font", "show", str(fixtures_dir / "fonts" / "tahoma-8.fmx"),
        "-t", "Druckerauflösung",
    ])
    assert "px wide" in result.output


def test_the_command_line_show_names_missing_glyphs(fixtures_dir):
    runner = CliRunner()
    result = runner.invoke(main, [
        "font", "show", str(fixtures_dir / "fonts" / "mini-5x7.fmx"),
        "-t", "Auflösung",
    ])
    assert "not in this font" in result.output
    assert "U+00F6" in result.output


def test_the_command_line_show_ignores_mnemonic_markers(fixtures_dir):
    runner = CliRunner()
    plain = runner.invoke(main, [
        "font", "show", str(fixtures_dir / "fonts" / "tahoma-8.fmx"), "-t", "Print",
    ]).output
    marked = runner.invoke(main, [
        "font", "show", str(fixtures_dir / "fonts" / "tahoma-8.fmx"), "-t", "&Print",
    ]).output
    assert plain.split("is ")[1] == marked.split("is ")[1]
