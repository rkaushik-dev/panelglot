import shutil

import pytest

from v4t_translate.catalog.store import load_catalog
from v4t_translate.catalog.translations import TranslationSet
from v4t_translate.config import load_config
from v4t_translate.emit.base import EmitOptions
from v4t_translate.emit.rcpack import RcEmitter
from v4t_translate.layout.mirror import (
    NO_MIRROR,
    RTL_EXSTYLES,
    mirrored_exstyles,
    render_exstyle,
    should_mirror_control,
    unmirrored_controls,
)
from v4t_translate.locales import resolve
from v4t_translate.ops.extract import extract_project
from v4t_translate.sources.rc.ast import Control
from v4t_translate.sources.rc.parser import parse_resource_script

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."he-IL"]

[locale."de-DE"]
"""

WITH_EXSTYLE = """\
IDD_MAIN DIALOGEX 0, 0, 200, 100
STYLE DS_SETFONT | WS_POPUP
EXSTYLE WS_EX_CONTROLPARENT | WS_EX_APPWINDOW
CAPTION "Setup"
FONT 8, "MS Shell Dlg", 400, 0, 0x1
BEGIN
    LTEXT           "Bar Height",IDC_STATIC,7,7,49,8
END
"""

WITHOUT_EXSTYLE = """\
IDD_MAIN DIALOGEX 0, 0, 200, 100
STYLE DS_SETFONT | WS_POPUP
CAPTION "Setup"
FONT 8, "MS Shell Dlg", 400, 0, 0x1
BEGIN
    LTEXT           "Bar Height",IDC_STATIC,7,7,49,8
END
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def localise(project, tag, tmp_path):
    """Write a localised copy of the sample and read it back."""
    catalog = load_catalog(project.catalog_path())
    out = tmp_path / f"{tag}.rc"
    RcEmitter().emit(catalog, TranslationSet(locale=tag), EmitOptions(
        path=out,
        locale=resolve(tag),
        source_path=project.root / "src" / "V4T.rc",
        encoding="utf-8",
    ))
    return out.read_text(encoding="utf-8")


# -- the style list -----------------------------------------------------


def test_both_styles_are_added():
    assert mirrored_exstyles([]) == list(RTL_EXSTYLES)


def test_existing_styles_are_kept():
    # Dropping WS_EX_CONTROLPARENT because this function only knows about two
    # styles would be a quiet regression in tab order.
    out = mirrored_exstyles(["WS_EX_CONTROLPARENT"])
    assert out[0] == "WS_EX_CONTROLPARENT"
    assert set(RTL_EXSTYLES) <= set(out)


def test_a_style_that_is_already_there_is_not_repeated():
    out = mirrored_exstyles(["WS_EX_LAYOUTRTL"])
    assert out.count("WS_EX_LAYOUTRTL") == 1
    assert len(out) == 2


def test_the_order_matches_what_microsoft_writes():
    assert RTL_EXSTYLES == ("WS_EX_LAYOUTRTL", "WS_EX_RTLREADING")


def test_none_is_the_same_as_empty():
    assert mirrored_exstyles(None) == mirrored_exstyles([])


def test_the_line_is_pipe_separated():
    assert render_exstyle(["A", "B"]) == "EXSTYLE A | B"


def test_one_style_needs_no_pipe():
    assert render_exstyle(["A"]) == "EXSTYLE A"


# -- which controls follow ----------------------------------------------


def test_a_control_with_text_follows_the_dialog():
    assert should_mirror_control(Control(statement="LTEXT", symbol="IDC_STATIC",
                                         caption="Bar Height"))


def test_a_bitmap_does_not():
    # A mirrored picture of a printhead is wrong in a way no string ever is.
    control = Control(statement="CONTROL", symbol="IDC_TOOLBAR",
                      styles=["SS_BITMAP"])
    assert not should_mirror_control(control)


def test_a_frame_does_not():
    control = Control(statement="CONTROL", symbol="IDC_PREVIEW",
                      styles=["SS_BLACKFRAME"])
    assert not should_mirror_control(control)


def test_a_picture_style_with_a_caption_still_follows():
    # If it has text on it, the text has to read the right way round.
    control = Control(statement="CONTROL", symbol="IDC_X", caption="Preview",
                      styles=["SS_BLACKFRAME"])
    assert should_mirror_control(control)


def test_an_edit_box_follows():
    assert should_mirror_control(Control(statement="EDITTEXT",
                                         symbol="IDC_BAR_HEIGHT"))


def test_the_sample_dialog_has_pictures_that_should_not_turn(sample_rc_path):
    script = parse_resource_script(sample_rc_path.read_text(encoding="utf-8"),
                                   path="V4T.rc")
    dialog = script.dialog("IDD_BARCODE_PROPS")
    symbols = {control.symbol for control in unmirrored_controls(dialog)}
    assert "IDC_PREVIEW" in symbols
    assert "IDC_TOOLBAR_IMAGE" in symbols


def test_the_labels_are_not_among_them(sample_rc_path):
    script = parse_resource_script(sample_rc_path.read_text(encoding="utf-8"),
                                   path="V4T.rc")
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert not any(control.caption for control in unmirrored_controls(dialog))


def test_the_style_that_stops_it_is_named():
    assert NO_MIRROR == "WS_EX_NOINHERITLAYOUT"


# -- parsing the existing line ------------------------------------------


def test_an_exstyle_line_is_read():
    dialog = parse_resource_script(WITH_EXSTYLE, path="x.rc").dialogs[0]
    assert dialog.exstyles == ["WS_EX_CONTROLPARENT", "WS_EX_APPWINDOW"]


def test_its_span_covers_the_whole_line():
    script = parse_resource_script(WITH_EXSTYLE, path="x.rc")
    start, end = script.dialogs[0].exstyle_span
    assert script.text[start:end] == "EXSTYLE WS_EX_CONTROLPARENT | WS_EX_APPWINDOW"


def test_a_dialog_without_one_has_no_span():
    dialog = parse_resource_script(WITHOUT_EXSTYLE, path="x.rc").dialogs[0]
    assert dialog.exstyle_span is None
    assert dialog.exstyles == []


def test_the_header_end_is_after_the_geometry():
    script = parse_resource_script(WITHOUT_EXSTYLE, path="x.rc")
    dialog = script.dialogs[0]
    assert script.text[:dialog.header_end].endswith("200, 100")


def test_the_geometry_still_parses():
    dialog = parse_resource_script(WITH_EXSTYLE, path="x.rc").dialogs[0]
    assert (dialog.width, dialog.height) == (200, 100)


# -- writing it out -----------------------------------------------------


def test_a_right_to_left_build_turns_the_dialogs_round(project, tmp_path):
    text = localise(project, "he-IL", tmp_path)
    assert "WS_EX_LAYOUTRTL" in text
    assert "WS_EX_RTLREADING" in text


def test_a_left_to_right_build_does_not(project, tmp_path):
    assert "WS_EX_LAYOUTRTL" not in localise(project, "de-DE", tmp_path)


def test_every_dialog_gets_it(project, tmp_path):
    text = localise(project, "he-IL", tmp_path)
    script = parse_resource_script(text, path="he.rc")
    assert script.dialogs
    for dialog in script.dialogs:
        assert "WS_EX_LAYOUTRTL" in dialog.exstyles


def test_the_result_still_parses(project, tmp_path):
    text = localise(project, "he-IL", tmp_path)
    script = parse_resource_script(text, path="he.rc")
    assert script.dialog("IDD_BARCODE_PROPS") is not None


def test_the_strings_are_untouched(project, tmp_path):
    text = localise(project, "he-IL", tmp_path)
    assert '"Bar Height"' in text


def test_an_existing_exstyle_keeps_what_it_had(tmp_path):
    from v4t_translate.catalog.model import Message
    from v4t_translate.catalog.store import Catalog

    source = tmp_path / "in.rc"
    source.write_text(WITH_EXSTYLE, encoding="utf-8")

    catalog = Catalog(project="p")
    catalog.add(Message(key="a.1", source_text="Bar Height"))

    out = tmp_path / "out.rc"
    RcEmitter().emit(catalog, TranslationSet(locale="he-IL"), EmitOptions(
        path=out, locale=resolve("he-IL"), source_path=source, encoding="utf-8",
    ))

    dialog = parse_resource_script(out.read_text(encoding="utf-8"),
                                   path="out.rc").dialogs[0]
    assert "WS_EX_CONTROLPARENT" in dialog.exstyles
    assert "WS_EX_LAYOUTRTL" in dialog.exstyles


def test_a_dialog_without_one_gets_a_new_line(tmp_path):
    from v4t_translate.catalog.model import Message
    from v4t_translate.catalog.store import Catalog

    source = tmp_path / "in.rc"
    source.write_text(WITHOUT_EXSTYLE, encoding="utf-8")

    catalog = Catalog(project="p")
    catalog.add(Message(key="a.1", source_text="Bar Height"))

    out = tmp_path / "out.rc"
    RcEmitter().emit(catalog, TranslationSet(locale="he-IL"), EmitOptions(
        path=out, locale=resolve("he-IL"), source_path=source, encoding="utf-8",
    ))

    text = out.read_text(encoding="utf-8")
    assert "EXSTYLE WS_EX_LAYOUTRTL | WS_EX_RTLREADING" in text
    assert parse_resource_script(text, path="out.rc").dialogs[0].width == 200


def test_the_new_line_goes_before_the_style_line(tmp_path):
    from v4t_translate.catalog.model import Message
    from v4t_translate.catalog.store import Catalog

    source = tmp_path / "in.rc"
    source.write_text(WITHOUT_EXSTYLE, encoding="utf-8")

    catalog = Catalog(project="p")
    catalog.add(Message(key="a.1", source_text="Bar Height"))

    out = tmp_path / "out.rc"
    RcEmitter().emit(catalog, TranslationSet(locale="he-IL"), EmitOptions(
        path=out, locale=resolve("he-IL"), source_path=source, encoding="utf-8",
    ))

    text = out.read_text(encoding="utf-8")
    assert text.index("EXSTYLE") < text.index("STYLE DS_SETFONT")


def test_no_coordinate_is_rewritten(project, tmp_path):
    # The whole point of using the styles. A mirrored coordinate would have to
    # be recomputed every time somebody drags a control in the English file.
    english = (project.root / "src" / "V4T.rc").read_text(encoding="utf-8")
    hebrew = localise(project, "he-IL", tmp_path)
    assert "163,26,36,8" in english
    assert "163,26,36,8" in hebrew
