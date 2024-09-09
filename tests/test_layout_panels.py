import pytest

from v4t_translate.errors import ConfigError
from v4t_translate.layout.panels import (
    PANELS,
    Panel,
    font_for,
    get_panel,
    panel_names,
    register_panel,
)


def test_the_shipped_panels_are_all_there():
    assert set(panel_names()) == {
        "tij-800x600",
        "tij8pen-1024x768",
        "mini-20x4",
        "mini-oled-128x64",
        "mobile",
    }


def test_every_panel_names_itself_consistently():
    for name, panel in PANELS.items():
        assert panel.name == name


def test_the_windows_panels_take_any_character():
    for name in ("tij-800x600", "tij8pen-1024x768"):
        panel = get_panel(name)
        assert panel.codepage is None
        assert panel.supports_dbcs


def test_the_mini_is_an_ansi_character_grid():
    panel = get_panel("mini-20x4")
    assert panel.is_character_grid
    assert panel.char_budget() == 20
    assert panel.line_budget() == 4
    assert panel.codepage == 1252
    assert not panel.supports_dbcs


def test_the_oled_is_a_graphic_panel_with_the_same_limits():
    panel = get_panel("mini-oled-128x64")
    assert not panel.is_character_grid
    assert panel.char_budget() is None
    assert panel.line_budget() == 1
    assert not panel.supports_dbcs


def test_both_mini_panels_forbid_the_frame_bytes():
    for name in ("mini-20x4", "mini-oled-128x64"):
        assert get_panel(name).forbidden == ("\x02", "\x03", "\x7f")


def test_the_windows_panels_forbid_nothing():
    assert get_panel("tij-800x600").forbidden == ()


def test_describe_a_grid_panel():
    assert get_panel("mini-20x4").describe() == "mini-20x4 (20x4 characters)"


def test_describe_a_graphic_panel():
    assert get_panel("tij-800x600").describe() == "tij-800x600 (800x600 pixels)"


def test_an_unknown_panel_lists_the_known_ones():
    with pytest.raises(ConfigError) as excinfo:
        get_panel("crt")
    assert "mini-20x4" in str(excinfo.value)


def test_registering_a_panel():
    panel = Panel(name="test-panel", description="only in a test", columns=16, rows=2)
    register_panel(panel)
    try:
        assert get_panel("test-panel") is panel
        assert "test-panel" in panel_names()
    finally:
        PANELS.pop("test-panel")


def test_font_for_uses_the_explicit_path(fixtures_dir):
    font = font_for(get_panel("mini-20x4"), explicit=fixtures_dir / "fonts" / "tahoma-8.fmx")
    assert font.name == "Tahoma"


def test_font_for_searches_for_the_panel_default(fixtures_dir):
    font = font_for(get_panel("mini-20x4"), search=[fixtures_dir / "fonts"])
    assert font.name == "Mini 5x7"


def test_font_for_tries_each_search_directory_in_order(fixtures_dir, tmp_path):
    font = font_for(get_panel("tij-800x600"), search=[tmp_path, fixtures_dir / "fonts"])
    assert font.name == "Tahoma"


def test_font_for_falls_back_rather_than_failing(tmp_path):
    font = font_for(get_panel("mini-20x4"), search=[tmp_path])
    assert font.name == "mini-20x4-fallback"
    assert font.advance("W") == 6


def test_the_fallback_is_reachable_with_no_search_path_at_all():
    assert font_for(get_panel("mobile")).name == "mobile-fallback"
