import pytest

from v4t_translate.catalog.model import OriginKind
from v4t_translate.errors import SourceError
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.rc.ast import Control
from v4t_translate.sources.rc.extract import RcSource, control_text_budget

RESOURCE_H = """\
#define IDD_BARCODE_PROPS 101
#define IDC_BAR_HEIGHT    1301
#define IDC_HUMAN_READABLE 1302
#define IDC_HINT          1303
"""


@pytest.fixture(scope="module")
def extraction(sample_rc_path):
    return RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent)
    )


@pytest.fixture(scope="module")
def messages(extraction):
    return {m.source_text: m for m in extraction.by_key().values()}


def test_source_is_relative_to_the_root(extraction):
    assert extraction.source == "v4t_sample.rc"


def test_dialog_captions_are_collected(messages):
    assert "Barcode Properties" in messages
    assert messages["Barcode Properties"].origins[0].kind is OriginKind.DIALOG_CAPTION


def test_control_captions_are_collected(messages):
    assert "Bar Height" in messages
    assert "Human Readable" in messages
    assert "Traverse Printing" in messages


def test_string_table_entries_are_collected(messages):
    assert "Print started" in messages
    assert "Please input from %.1fV to %.1fV." in messages


def test_menu_items_are_collected(messages):
    assert "&File" in messages
    assert "E&xit" in messages


def test_a_popup_and_an_item_get_different_kinds(messages):
    assert messages["&File"].origins[0].kind is OriginKind.MENU_POPUP
    assert messages["E&xit"].origins[0].kind is OriginKind.MENU_ITEM


def test_accelerator_suffix_gets_a_note(messages):
    note = messages["&New\tCtrl+N"].developer_note
    assert note and "accelerator" in note


def test_empty_captions_are_dropped(messages):
    assert "" not in messages


def test_a_caption_that_is_only_punctuation_is_dropped():
    # The old script pushed "4." through and got "4。" back from the engine.
    source = RcSource()
    extraction = _extract_text(source, 'IDD_X DIALOGEX 0,0,10,10\nBEGIN\n'
                                       '  LTEXT "4.",IDC_STATIC,1,1,20,8\n'
                                       '  LTEXT "Pen",IDC_STATIC,1,10,20,8\n'
                                       'END\n')
    assert [m.source_text for m in extraction.messages] == ["Pen"]


def test_units_are_still_extracted_because_they_are_words(messages):
    # "mm" is a word as far as the reader is concerned. Marking it
    # untranslatable is the protected-pattern job, not the reader's.
    assert "mm" in messages


def test_protected_patterns_mark_matching_messages(sample_rc_path):
    extraction = RcSource().extract(
        SourceOptions(
            path=sample_rc_path,
            root=sample_rc_path.parent,
            protected_patterns=("mm", "YYYY", r"hh:mm"),
        )
    )
    by_text = {m.source_text: m for m in extraction.messages}
    assert by_text["mm"].protected
    assert by_text["YYYY"].protected
    assert not by_text["Print started"].protected


def test_a_partial_pattern_match_does_not_protect(sample_rc_path):
    # The pattern is matched against the whole string, so "mm" must not
    # protect "Please input from %.1fV to %.1fV." by accident.
    extraction = RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent,
                      protected_patterns=("m",))
    )
    by_text = {m.source_text: m for m in extraction.messages}
    assert not by_text["mm"].protected


def test_identical_text_in_two_dialogs_is_one_message(extraction):
    merged = extraction.by_key()
    spacing = [m for m in merged.values() if m.source_text == "Spacing"]
    assert len(spacing) == 1


def test_width_budget_charges_a_checkbox_for_its_box(messages):
    # 68 dialog units at 6 pixels per 4 units is 102, less 17 for the box.
    assert messages["Human Readable"].max_width_px == 85


def test_width_budget_of_a_plain_label(messages):
    # "Bar Height" sits in a 36 unit LTEXT, which is 54 pixels and no chrome.
    assert messages["Bar Height"].max_width_px == 54


def test_a_group_box_label_pays_for_its_frame(messages):
    # 153 units is 230 pixels, less 15.
    assert messages["Extra options"].max_width_px == 215


def test_string_table_messages_have_no_width_budget(messages):
    assert messages["Print started"].max_width_px is None


def test_single_line_controls_get_one_line(messages):
    assert messages["Bar Height"].max_lines == 1


def test_nowordwrap_keeps_a_tall_control_at_one_line(messages):
    assert messages["This distance cannot be greater than print spacing"].max_lines == 1


def test_anonymous_controls_get_a_note_naming_their_position(messages):
    note = messages["Bar Height"].developer_note
    assert note and "IDD_BARCODE_PROPS" in note


def test_stats_report_what_was_read(extraction):
    assert extraction.stats["dialogs"] == 2
    assert extraction.stats["messages"] == len(extraction.by_key())


def test_a_missing_symbols_file_warns_rather_than_failing(sample_rc_path, tmp_path):
    extraction = RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent,
                      symbols_path=tmp_path / "nope.h")
    )
    assert any("does not exist" in w for w in extraction.warnings)
    assert extraction.messages


def test_symbols_file_is_used_when_present(sample_rc_path, tmp_path):
    header = tmp_path / "resource.h"
    header.write_text(RESOURCE_H, encoding="utf-8")
    extraction = RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent, symbols_path=header)
    )
    assert not extraction.warnings


def test_a_missing_file_raises():
    with pytest.raises(SourceError, match="does not exist"):
        RcSource().extract(SourceOptions(path=_missing_path()))


def test_a_cp1252_file_is_read_after_utf8_fails(tmp_path):
    path = tmp_path / "ansi.rc"
    path.write_bytes(
        'STRINGTABLE\nBEGIN\n  IDS_A "Aufl\xf6sung"\nEND\n'.encode("cp1252")
    )
    extraction = RcSource().extract(SourceOptions(path=path, root=tmp_path))
    assert extraction.messages[0].source_text == "Auflösung"


def test_control_text_budget_for_an_unknown_statement():
    control = Control(statement="SOMETHING", symbol="IDC_X", caption="x")
    assert control_text_budget(control, 100) == 100


def test_control_text_budget_detects_a_boxed_generic_control():
    control = Control(statement="CONTROL", symbol="IDC_X", caption="x",
                      styles=["BS_AUTOCHECKBOX", "WS_TABSTOP"])
    assert control_text_budget(control, 100) == 83


def test_a_control_too_narrow_for_text_warns(tmp_path):
    path = tmp_path / "tiny.rc"
    path.write_text(
        'IDD_X DIALOGEX 0,0,100,50\nBEGIN\n'
        '  AUTOCHECKBOX "On",IDC_ON,1,1,4,10\n'
        'END\n',
        encoding="utf-8",
    )
    extraction = RcSource().extract(SourceOptions(path=path, root=tmp_path))
    assert any("too narrow" in w for w in extraction.warnings)


def _extract_text(source, text):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "t.rc"
        path.write_text(text, encoding="utf-8")
        return source.extract(SourceOptions(path=path, root=Path(directory)))


def _missing_path():
    from pathlib import Path

    return Path(__file__).parent / "fixtures" / "definitely-not-here.rc"
