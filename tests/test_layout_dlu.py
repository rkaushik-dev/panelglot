import pytest

from v4t_translate.layout.dlu import (
    SHELL_DLG_ALIASES,
    DialogBaseUnits,
    base_units_for,
    resolve_shell_font,
)


def test_four_horizontal_units_is_one_character():
    units = DialogBaseUnits(6, 13)
    assert units.x_to_pixels(4) == 6
    assert units.x_to_pixels(8) == 12


def test_eight_vertical_units_is_one_character():
    units = DialogBaseUnits(6, 13)
    assert units.y_to_pixels(8) == 13
    assert units.y_to_pixels(16) == 26


def test_horizontal_conversion_of_a_real_control_width():
    # The Bar Height label is 36 units wide in the fixture.
    assert DialogBaseUnits(6, 13).x_to_pixels(36) == 54


def test_rounding_is_to_nearest_not_toward_zero():
    units = DialogBaseUnits(7, 15)
    # 5 * 7 / 4 is 8.75, which USER32 lands on 9.
    assert units.x_to_pixels(5) == 9


def test_pixels_back_to_units_rounds_down():
    units = DialogBaseUnits(6, 13)
    assert units.pixels_to_x(54) == 36
    assert units.pixels_to_x(55) == 36


def test_vertical_pixels_back_to_units():
    units = DialogBaseUnits(6, 13)
    assert units.pixels_to_y(13) == 8


def test_a_named_font_is_not_an_alias():
    assert resolve_shell_font("Tahoma", "zh-TW") == "Tahoma"
    assert resolve_shell_font("Courier New", None) == "Courier New"


def test_shell_dlg_resolves_per_locale():
    assert resolve_shell_font("MS Shell Dlg", "en-US") == "Tahoma"
    assert resolve_shell_font("MS Shell Dlg", "de-DE") == "Tahoma"
    assert resolve_shell_font("MS Shell Dlg", "zh-TW") == "PMingLiU"
    assert resolve_shell_font("MS Shell Dlg", "zh-CN") == "SimSun"
    assert resolve_shell_font("MS Shell Dlg", "ja-JP") == "MS UI Gothic"
    assert resolve_shell_font("MS Shell Dlg", "ko-KR") == "Gulim"


def test_shell_dlg_2_is_the_same_alias():
    assert resolve_shell_font("MS Shell Dlg 2", "zh-TW") == "PMingLiU"


def test_shell_dlg_alias_is_case_and_space_tolerant():
    assert resolve_shell_font("  ms shell dlg  ", "ja-JP") == "MS UI Gothic"


def test_an_unknown_locale_falls_back_to_the_english_shell_font():
    assert resolve_shell_font("MS Shell Dlg", "is-IS") == "Tahoma"


def test_no_locale_at_all_falls_back_to_english():
    assert resolve_shell_font("MS Shell Dlg", None) == "Tahoma"


def test_region_specific_chinese_beats_the_language_default():
    # zh alone is not in the table, so the tag has to win.
    assert "zh" not in SHELL_DLG_ALIASES
    assert resolve_shell_font("MS Shell Dlg", "zh-TW") != resolve_shell_font(
        "MS Shell Dlg", "zh-CN"
    )


def test_measured_units_for_the_dialog_font_the_product_uses():
    assert base_units_for("MS Shell Dlg", 8, locale_tag="en-US") == DialogBaseUnits(6, 13)


def test_the_same_dialog_is_wider_in_traditional_chinese():
    english = base_units_for("MS Shell Dlg", 8, locale_tag="en-US")
    chinese = base_units_for("MS Shell Dlg", 8, locale_tag="zh-TW")
    assert chinese.x > english.x
    # A 100 unit control gains real pixels, which is the whole problem.
    assert chinese.x_to_pixels(100) > english.x_to_pixels(100)


def test_an_unmeasured_size_is_scaled_from_the_nearest_one():
    units = base_units_for("Tahoma", 16)
    assert units.x > base_units_for("Tahoma", 8).x


def test_an_unmeasured_size_that_is_smaller_scales_down():
    units = base_units_for("Tahoma", 4)
    assert units.x < base_units_for("Tahoma", 8).x
    assert units.x >= 1


def test_an_unknown_font_falls_back():
    assert base_units_for("Comic Sans MS", 8) == DialogBaseUnits(6, 13)


def test_an_unknown_font_at_an_unusual_size_still_scales():
    assert base_units_for("Comic Sans MS", 16).x == 12


@pytest.mark.parametrize("size", [0, -1])
def test_a_nonsense_size_does_not_explode(size):
    units = base_units_for("Comic Sans MS", size)
    assert units.x >= 1 and units.y >= 1


def test_the_system_font_entry_is_reachable():
    assert base_units_for("System", 0) == DialogBaseUnits(8, 16)
