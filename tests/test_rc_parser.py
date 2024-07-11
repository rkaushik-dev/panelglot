import pytest

from v4t_translate.errors import ParseError
from v4t_translate.sources.rc.parser import parse_resource_script


@pytest.fixture(scope="module")
def script(sample_rc_text):
    return parse_resource_script(sample_rc_text, path="V4T.rc")


def test_counts(script):
    counts = script.counts()
    assert counts["dialogs"] == 2
    assert counts["string_tables"] == 2
    assert counts["strings"] == 14
    assert counts["menus"] == 1


def test_language_statement_is_captured(script):
    assert script.language == "LANGUAGE LANG_ENGLISH, SUBLANG_ENGLISH_US"


def test_directives_are_kept_in_order(script):
    assert script.directives[0] == '#include "resource.h"'
    assert "#pragma code_page(1252)" in script.directives


def test_dialog_geometry(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert (dialog.x, dialog.y, dialog.width, dialog.height) == (0, 0, 316, 214)


def test_dialog_caption_and_font(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert dialog.caption == "Barcode Properties"
    assert dialog.font_size == 8
    assert dialog.font_name == "MS Shell Dlg"


def test_dialog_styles(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert "DS_MODALFRAME" in dialog.styles
    assert "WS_SYSMENU" in dialog.styles


def test_a_child_dialog_has_no_caption(script):
    assert script.dialog("IDD_PEN_OFFSETS").caption is None


def test_ltext_control(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    control = dialog.controls[1]
    assert control.statement == "LTEXT"
    assert control.caption == "Bar Height"
    assert control.symbol == "IDC_STATIC"
    assert (control.x, control.y, control.width, control.height) == (163, 26, 36, 8)


def test_edittext_has_no_caption(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_BAR_HEIGHT")
    assert control.caption is None
    assert (control.x, control.y, control.width, control.height) == (205, 24, 40, 14)
    assert control.has_style("ES_AUTOHSCROLL")


def test_control_statement_with_a_wrapped_style_list(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_HUMAN_READABLE")
    assert control.caption == "Human Readable"
    assert control.window_class == "Button"
    assert control.has_style("BS_AUTOCHECKBOX")
    assert control.has_style("WS_TABSTOP")
    assert (control.x, control.y, control.width, control.height) == (163, 64, 68, 10)


def test_style_wrapping_after_a_pipe_is_also_handled(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_AUTO_PARITY")
    assert control.caption == "Auto parity"
    assert control.has_style("WS_TABSTOP")
    assert (control.x, control.y) == (163, 80)


def test_a_control_over_a_non_text_class_carries_no_caption(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_TOOLBAR_IMAGE")
    assert control.caption is None
    assert control.window_class == "Static"


def test_an_empty_caption_survives_as_empty_not_none(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_PREVIEW")
    assert control.caption == ""


def test_caption_wrapped_onto_the_next_line(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_HINT")
    assert control.caption == "This distance cannot be greater than print spacing"
    assert control.has_style("SS_LEFTNOWORDWRAP")


def test_ordinals_count_every_control_in_order(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert [c.ordinal for c in dialog.controls] == list(range(len(dialog.controls)))


def test_combobox_geometry_is_read_past_its_id(script):
    control = script.dialog("IDD_PEN_OFFSETS").control_by_symbol("IDC_ORIENTATION")
    assert (control.x, control.y, control.width, control.height) == (180, 118, 53, 60)
    assert control.caption is None


def test_autocheckbox_is_captioned(script):
    control = script.dialog("IDD_PEN_OFFSETS").control_by_symbol("IDC_TRAVERSE")
    assert control.caption == "Traverse Printing"


def test_string_table_entries(script):
    entries = {e.symbol: e.text for e in script.string_entries()}
    assert entries["IDS_PRINT_STARTED"] == "Print started"
    assert entries["IDS_FIRING_RANGE"] == "Please input from %.1fV to %.1fV."
    assert entries["IDS_VALUE_RANGE"] == "Value must be between <V1> and <V2>"


def test_adjacent_string_literals_are_joined(script):
    entries = {e.symbol: e.text for e in script.string_entries()}
    assert entries["IDS_PURGE_OFFSET"] == "Purge offset must be less than group offset"


def test_escaped_ampersand_survives_into_the_entry(script):
    entries = {e.symbol: e.text for e in script.string_entries()}
    assert entries["IDS_TITLE_FORMAT"] == "Date&&Time Format"


def test_string_entries_carry_their_line(script):
    entry = next(e for e in script.string_entries() if e.symbol == "IDS_PRINT_STARTED")
    assert entry.line > 0


def test_menu_structure(script):
    menu = script.menus[0]
    assert menu.symbol == "IDR_MAINFRAME"
    assert [i.text for i in menu.items] == ["&File", "&Printer"]


def test_menu_items_and_their_ids(script):
    items = {i.text: i.symbol for i in script.menu_items() if not i.is_popup}
    assert items["&New\tCtrl+N"] == "ID_FILE_NEW"
    assert items["E&xit"] == "ID_APP_EXIT"


def test_separators_are_marked_and_carry_no_text(script):
    separators = [i for i in script.menu_items() if i.is_separator]
    assert len(separators) == 1
    assert separators[0].text is None


def test_nested_popups(script):
    texts = [i.text for i in script.menu_items()]
    assert "&Diagnostics" in texts
    assert "&Print and Verify" in texts


def test_version_and_layout_blocks_land_in_raw(script):
    statements = {b.statement.upper() for b in script.raw_blocks}
    assert "VERSIONINFO" in statements
    assert "AFX_DIALOG_LAYOUT" in statements
    assert "ICON" in statements


def test_a_raw_block_keeps_something_of_its_text(script):
    version = next(b for b in script.raw_blocks if b.statement.upper() == "VERSIONINFO")
    assert "StringFileInfo" in version.text


def test_unterminated_dialog_is_reported():
    with pytest.raises(ParseError, match="unterminated dialog"):
        parse_resource_script('IDD_X DIALOGEX 0,0,10,10\nBEGIN\n  LTEXT "a",IDC_STATIC,1,1,1,1\n')


def test_unterminated_string_table_is_reported():
    with pytest.raises(ParseError, match="unterminated STRINGTABLE"):
        parse_resource_script('STRINGTABLE\nBEGIN\n  IDS_A "a"\n')


def test_a_resource_with_no_type_is_reported():
    with pytest.raises(ParseError, match="expected a resource type"):
        parse_resource_script("IDD_X\n")


def test_a_captioned_control_without_a_caption_is_reported():
    with pytest.raises(ParseError, match="without a caption"):
        parse_resource_script(
            "IDD_X DIALOGEX 0,0,10,10\nBEGIN\n  LTEXT IDC_STATIC,1,1,1,1\nEND\n"
        )


def test_negative_coordinates_parse():
    script = parse_resource_script(
        'IDD_X DIALOGEX 0,0,10,10\nBEGIN\n  LTEXT "a",IDC_STATIC,-4,1,20,8\nEND\n'
    )
    assert script.dialog("IDD_X").controls[0].x == -4


def test_a_dialog_written_with_braces():
    script = parse_resource_script(
        'IDD_X DIALOGEX 0,0,10,10\n{\n  LTEXT "a",IDC_STATIC,1,1,1,1\n}\n'
    )
    assert script.dialog("IDD_X").controls[0].caption == "a"
