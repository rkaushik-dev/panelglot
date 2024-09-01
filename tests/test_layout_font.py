import pytest

from v4t_translate.errors import SourceError
from v4t_translate.layout.font import (
    FontMetrics,
    load_metrics,
    monospace,
    parse_metrics,
)

SMALL = """\
name: Test
pixel_size: 10
line_height: 12
default_width: 5

20..7E 5
20 3
4D 8
4E00..9FFF 10
20AC 6
"""


@pytest.fixture(scope="module")
def font():
    return parse_metrics(SMALL, path="test.fmx")


@pytest.fixture(scope="module")
def tahoma(fixtures_dir):
    return load_metrics(fixtures_dir / "fonts" / "tahoma-8.fmx")


@pytest.fixture(scope="module")
def mini(fixtures_dir):
    return load_metrics(fixtures_dir / "fonts" / "mini-5x7.fmx")


def test_headers(font):
    assert font.name == "Test"
    assert font.pixel_size == 10
    assert font.line_height == 12
    assert font.default_width == 5


def test_line_height_defaults_from_pixel_size():
    assert FontMetrics(pixel_size=8).line_height == 10


def test_default_width_defaults_from_pixel_size():
    assert FontMetrics(pixel_size=12).default_width == 6


def test_coverage_over_a_range(font):
    assert font.covers("A")
    assert font.covers("~")


def test_coverage_over_an_explicit_codepoint(font):
    assert font.covers("€")


def test_something_outside_every_range(font):
    assert not font.covers("م")


def test_explicit_width_beats_the_range(font):
    assert font.advance("M") == 8
    assert font.advance("A") == 5


def test_space_can_be_narrower_than_the_default(font):
    assert font.advance(" ") == 3


def test_measure_adds_advances(font):
    assert font.measure("MA") == 13
    assert font.measure("M A") == 16


def test_measure_ignores_newlines(font):
    assert font.measure("AB\nCD") == font.measure("ABCD")


def test_an_uncovered_character_still_costs_width(font):
    # The firmware draws its blank slot, so a string full of them is not free.
    assert font.advance("م") == font.default_width


def test_missing_lists_each_character_once(font):
    assert font.missing("مممرم") == ["م", "ر"]


def test_missing_skips_control_characters(font):
    assert font.missing("New\tCtrl+N") == []


def test_missing_is_empty_for_a_covered_string(font):
    assert font.missing("Print started") == []


def test_a_cjk_range_is_covered(font):
    assert font.covers("刪")
    assert font.advance("刪") == 10


def test_coverage_size_counts_range_and_explicit(font):
    small = parse_metrics("name: x\ndefault_width: 4\n41..43 4\n5A 5\n")
    assert small.coverage_size == 4


def test_coverage_size_does_not_double_count():
    overlapping = parse_metrics("name: x\ndefault_width: 4\n41..43 4\n41 6\n")
    assert overlapping.coverage_size == 3


def test_monospace_helper():
    font = monospace(6)
    assert font.advance("W") == 6
    assert font.advance("i") == 6
    assert font.measure("Purge") == 30
    assert font.covers("A")
    assert not font.covers("ö")


def test_comments_and_blank_lines_are_skipped():
    font = parse_metrics("# a comment\n\nname: X  # trailing\ndefault_width: 4\n41 5\n")
    assert font.name == "X"
    assert font.advance("A") == 5


def test_a_backwards_range_is_rejected():
    with pytest.raises(SourceError, match="runs backwards"):
        parse_metrics("name: X\n7E..20 5\n")


def test_an_unreadable_line_is_reported_with_its_number():
    with pytest.raises(SourceError, match=":3:"):
        parse_metrics("name: X\n41 5\nnonsense here\n", path="f.fmx")


def test_an_unknown_header_is_reported():
    with pytest.raises(SourceError, match="unknown header"):
        parse_metrics("name: X\nweight: bold\n")


def test_a_non_numeric_header_is_reported():
    with pytest.raises(SourceError, match="must be a number"):
        parse_metrics("name: X\npixel_size: large\n")


def test_an_empty_file_is_rejected():
    with pytest.raises(SourceError, match="no metrics"):
        parse_metrics("# nothing but a comment\n")


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(SourceError, match="does not exist"):
        load_metrics(tmp_path / "nope.fmx")


def test_load_uses_the_stem_when_the_file_names_nothing(tmp_path):
    path = tmp_path / "panel.fmx"
    path.write_text("default_width: 4\n41..5A 4\n", encoding="utf-8")
    assert load_metrics(path).name == "panel"


def test_the_shipped_tahoma_metrics(tahoma):
    assert tahoma.name == "Tahoma"
    assert tahoma.line_height == 13
    assert tahoma.advance("W") == 11
    assert tahoma.advance("i") == 3
    assert tahoma.advance(" ") == 3


def test_tahoma_covers_german(tahoma):
    assert tahoma.missing("Druckerauflösung") == []
    assert tahoma.missing("Gruppendruckversätze") == []
    assert tahoma.missing("Zündspannung") == []


def test_tahoma_does_not_cover_chinese(tahoma):
    assert tahoma.missing("刪除") == ["刪", "除"]


def test_a_proportional_font_makes_width_depend_on_the_letters(tahoma):
    assert tahoma.measure("WWWW") > tahoma.measure("iiii")


def test_german_is_wider_than_english_in_the_same_font(tahoma):
    assert tahoma.measure("Druckerauflösung") > tahoma.measure("Resolution")


def test_the_mini_font_is_ascii_only(mini):
    assert mini.missing("Print started") == []
    assert mini.missing("Auflösung") == ["ö"]
    assert mini.missing("Résolution") == ["é"]


def test_the_mini_font_is_fixed_pitch(mini):
    assert mini.measure("WWW") == mini.measure("iii") == 18
