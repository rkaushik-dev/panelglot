"""Every span has to name exactly the characters a rewrite should replace.

Testing spans by asserting numbers would be unreadable and would break on any
whitespace change in the fixture, so every test here slices the source with
the span and checks what it got.
"""

import pytest

from v4t_translate.sources.rc.lexer import tokenize
from v4t_translate.sources.rc.parser import parse_resource_script
from v4t_translate.sources.rc.tokens import TokenKind


@pytest.fixture(scope="module")
def script(sample_rc_text):
    return parse_resource_script(sample_rc_text, path="V4T.rc")


def slice_of(script, span):
    assert span is not None
    return script.text[span[0]:span[1]]


def test_every_token_slices_back_to_itself():
    text = 'LTEXT "Bar Height",IDC_STATIC,7,26,40,8 // trailing\n0x10 BEGIN END'
    for token in tokenize(text):
        if token.kind is TokenKind.EOF:
            continue
        if token.kind is TokenKind.STRING:
            assert text[token.start:token.end] == f'"{token.text}"'
        else:
            assert text[token.start:token.end] == token.text


def test_a_wide_literal_span_includes_the_prefix():
    text = 'IDS_A L"Firing Voltage"'
    token = next(t for t in tokenize(text) if t.kind is TokenKind.STRING)
    assert text[token.start:token.end] == 'L"Firing Voltage"'


def test_a_directive_span():
    text = '#include "resource.h"\nIDD_X DIALOG'
    token = tokenize(text)[0]
    assert text[token.start:token.end] == '#include "resource.h"'


def test_the_script_keeps_its_source(script, sample_rc_text):
    assert script.text == sample_rc_text


def test_a_dialog_caption_span(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert slice_of(script, dialog.caption_span) == '"Barcode Properties"'


def test_a_dialog_font_span(script):
    dialog = script.dialog("IDD_BARCODE_PROPS")
    assert slice_of(script, dialog.font_span) == '"MS Shell Dlg"'


def test_a_control_caption_span(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_HUMAN_READABLE")
    assert slice_of(script, control.caption_span) == '"Human Readable"'


def test_a_caption_that_wrapped_onto_the_next_line(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_HINT")
    assert slice_of(script, control.caption_span) == (
        '"This distance cannot be greater than print spacing"'
    )


def test_an_empty_caption_still_has_a_span(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_PREVIEW")
    assert slice_of(script, control.caption_span) == '""'


def test_a_control_with_no_caption_has_no_span(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_BAR_HEIGHT")
    assert control.caption_span is None


def test_a_generic_control_over_a_bitmap_has_no_caption_span(script):
    control = script.dialog("IDD_BARCODE_PROPS").control_by_symbol("IDC_TOOLBAR_IMAGE")
    assert control.caption_span is None


def test_a_string_table_entry_span(script):
    entry = next(e for e in script.string_entries() if e.symbol == "IDS_PRINT_STARTED")
    assert slice_of(script, entry.span) == '"Print started"'


def test_a_joined_entry_span_covers_the_whole_run(script):
    entry = next(e for e in script.string_entries() if e.symbol == "IDS_PURGE_OFFSET")
    taken = slice_of(script, entry.span)
    assert taken.startswith('"Purge offset must be less than "')
    assert taken.endswith('"group offset"')


def test_an_escaped_ampersand_entry_span(script):
    entry = next(e for e in script.string_entries() if e.symbol == "IDS_TITLE_FORMAT")
    assert slice_of(script, entry.span) == '"Date&&Time Format"'


def test_a_menu_item_span(script):
    item = next(i for i in script.menu_items() if i.symbol == "ID_APP_EXIT")
    assert slice_of(script, item.span) == '"E&xit"'


def test_a_popup_span(script):
    item = next(i for i in script.menu_items() if i.text == "&Printer")
    assert slice_of(script, item.span) == '"&Printer"'


def test_a_separator_has_no_span(script):
    item = next(i for i in script.menu_items() if i.is_separator)
    assert item.span is None


def test_the_language_span_covers_the_whole_statement(script):
    assert slice_of(script, script.language_span) == (
        "LANGUAGE LANG_ENGLISH, SUBLANG_ENGLISH_US"
    )


def test_spans_do_not_overlap(script):
    spans = []
    for dialog in script.dialogs:
        if dialog.caption_span:
            spans.append(dialog.caption_span)
        for control in dialog.controls:
            if control.caption_span:
                spans.append(control.caption_span)
    for entry in script.string_entries():
        if entry.span:
            spans.append(entry.span)

    spans.sort()
    for earlier, later in zip(spans, spans[1:]):
        assert earlier[1] <= later[0]
