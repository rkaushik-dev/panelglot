import pytest

from v4t_translate.layout.font import load_metrics, monospace
from v4t_translate.layout.measure import (
    drawn_text,
    fits,
    is_breakable_after,
    line_count,
    mnemonic_of,
    overflow_px,
    visible_length,
    wrap,
)


@pytest.fixture(scope="module")
def font():
    # Six pixels a character makes every expected width easy to read.
    return monospace(6, ranges=[(0x20, 0x7E), (0x4E00, 0x9FFF), (0xC0, 0xFF)])


@pytest.fixture(scope="module")
def tahoma(fixtures_dir):
    return load_metrics(fixtures_dir / "fonts" / "tahoma-8.fmx")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Print", "Print"),
        ("&Print", "Print"),
        ("P&rint", "Print"),
        ("Date&&Time Format", "Date&Time Format"),
        ("&Date&&Time", "Date&Time"),
        ("trailing&", "trailing"),
        ("&&&x", "&x"),
        ("", ""),
    ],
)
def test_drawn_text(raw, expected):
    assert drawn_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("&Print", "P"),
        ("P&rint", "R"),
        ("E&xit", "X"),
        ("Date&&Time Format", None),
        ("Print", None),
        ("Date&&Time &Offset", "O"),
        ("trailing&", None),
        ("&First and &Second", "F"),
    ],
)
def test_mnemonic_of(raw, expected):
    assert mnemonic_of(raw) == expected


def test_is_breakable_after():
    assert is_breakable_after("刪")
    assert is_breakable_after("。")
    assert is_breakable_after("あ")
    assert not is_breakable_after("A")
    assert not is_breakable_after(" ")


def test_a_short_string_is_one_line(font):
    assert wrap("Bar Height", font, 200) == ["Bar Height"]


def test_wrapping_at_a_space(font):
    # 60 pixels is ten characters.
    assert wrap("Print started now", font, 60) == ["Print", "started", "now"]


def test_the_space_that_justified_the_break_is_trimmed(font):
    for line in wrap("Print started now", font, 60):
        assert line == line.strip()


def test_explicit_newlines_always_break(font):
    assert wrap("one\ntwo", font, 600) == ["one", "two"]


def test_an_unbreakable_run_is_left_long_rather_than_cut(font):
    assert wrap("Gruppendruckversaetze", font, 30) == ["Gruppendruckversaetze"]


def test_a_long_word_after_a_short_one_still_gets_its_own_line(font):
    assert wrap("a Gruppendruckversaetze", font, 30) == ["a", "Gruppendruckversaetze"]


def test_chinese_breaks_between_characters(font):
    # No spaces anywhere, and it still has to wrap.
    assert wrap("條形碼數據列表", font, 24) == ["條形碼數", "據列表"]


def test_chinese_does_not_start_a_line_with_closing_punctuation(font):
    lines = wrap("時間戳列表：預覽", font, 24)
    assert not any(line.startswith("：") for line in lines)


def test_mnemonics_are_not_measured(font):
    assert wrap("&Print started now", font, 60) == ["Print", "started", "now"]


def test_an_empty_string_wraps_to_one_empty_line(font):
    assert wrap("", font, 60) == [""]


def test_a_zero_width_budget_falls_back_to_the_raw_lines(font):
    assert wrap("a\nb", font, 0) == ["a", "b"]


def test_line_count(font):
    assert line_count("Print started now", font, 60) == 3
    assert line_count("Print started now", font, 600) == 1


def test_fits_on_one_line(font):
    assert fits("Bar Height", font, 60)
    assert not fits("Bar Height and Width", font, 60)


def test_fits_across_several_lines(font):
    assert fits("Print started now", font, 60, max_lines=3)
    assert not fits("Print started now", font, 60, max_lines=2)


def test_nothing_fits_in_no_space(font):
    assert not fits("a", font, 0)


def test_overflow_is_zero_when_it_fits(font):
    assert overflow_px("Bar Height", font, 60) == 0


def test_overflow_on_one_line_is_the_whole_overhang(font):
    # "Bar Height and Width" is 20 characters, 120 pixels, budget 60.
    assert overflow_px("Bar Height and Width", font, 60) == 60


def test_overflow_on_a_wrapping_control_is_zero_when_wrapping_saves_it(font):
    assert overflow_px("Print started now", font, 60, max_lines=3) == 0


def test_overflow_on_a_wrapping_control_reports_an_unbreakable_run(font):
    assert overflow_px("Gruppendruckversaetze", font, 60, max_lines=3) == 66


def test_overflow_of_an_empty_string(font):
    assert overflow_px("", font, 60) == 0


def test_overflow_with_no_budget_at_all(font):
    assert overflow_px("abc", font, 0) == 18


def test_a_real_german_caption_against_a_real_control(tahoma):
    # "Human Readable" sits in a 68 unit checkbox: 102 pixels less 17 of box.
    english = "Human Readable"
    german = "Menschenlesbar"
    assert fits(english, tahoma, 85)
    assert fits(german, tahoma, 85)


def test_a_german_caption_that_does_not_fit(tahoma):
    # "Traverse Printing" is an 68 unit checkbox on the pen offsets page.
    assert not fits("Querdruck im Wechselbetrieb", tahoma, 85)
    assert overflow_px("Querdruck im Wechselbetrieb", tahoma, 85) > 0


def test_visible_length_ignores_mnemonic_markers():
    assert visible_length("&Print") == 5
    assert visible_length("Date&&Time") == 9


def test_visible_length_ignores_combining_marks():
    assert visible_length("Auflösung") == len("Auflösung")
