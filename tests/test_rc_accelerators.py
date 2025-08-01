import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.registry import rule_names
from v4t_translate.rules.result import Severity
from v4t_translate.rules.shortcuts import ShortcutRule, final_key, split_hint
from v4t_translate.sources.rc.ast import Accelerator, MenuItem
from v4t_translate.sources.rc.extract import shortcut_note
from v4t_translate.sources.rc.parser import parse_resource_script

TABLE = """\
IDR_MAINFRAME ACCELERATORS
BEGIN
    "N",            ID_FILE_NEW,            VIRTKEY, CONTROL, NOINVERT
    "^O",           ID_FILE_OPEN,           ASCII,  NOINVERT
    VK_F5,          ID_DIAG_VERIFY,         VIRTKEY, NOINVERT
    VK_DELETE,      ID_PEN_CLEAR,           VIRTKEY, SHIFT, NOINVERT
    VK_PRIOR,       ID_PAGE_UP,             VIRTKEY, ALT
END
"""

MENU_AND_TABLE = """\
IDR_MAINFRAME MENU
BEGIN
    POPUP "&File"
    BEGIN
        MENUITEM "&New\\tCtrl+N",     ID_FILE_NEW
        MENUITEM "&Purge\\tShift+Del", ID_PEN_CLEAR
        MENUITEM "&Nothing\\tCtrl+Q",  ID_UNBOUND
    END
END

IDR_MAINFRAME ACCELERATORS
BEGIN
    "N",            ID_FILE_NEW,            VIRTKEY, CONTROL, NOINVERT
    VK_DELETE,      ID_PEN_CLEAR,           VIRTKEY, SHIFT, NOINVERT
END
"""


def parse(text):
    return parse_resource_script(text, path="V4T.rc")


def context(tag="de-DE"):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0x9FFF)]),
    )


def run(source, target, tag="de-DE"):
    message = Message(key="m.1", source_text=source)
    return list(ShortcutRule().check(message, Translation(text=target), context(tag)))


# -- parsing ------------------------------------------------------------


def test_the_table_is_parsed():
    script = parse(TABLE)
    assert len(script.accelerators) == 1
    assert len(script.accelerators[0].entries) == 5


def test_the_table_keeps_its_name():
    assert parse(TABLE).accelerators[0].symbol == "IDR_MAINFRAME"


def test_a_quoted_key_is_unquoted():
    entry = parse(TABLE).accelerator_for("ID_FILE_NEW")
    assert entry.key == "N"
    assert entry.quoted


def test_a_virtual_key_is_not_quoted():
    entry = parse(TABLE).accelerator_for("ID_DIAG_VERIFY")
    assert entry.key == "VK_F5"
    assert not entry.quoted


def test_flags_are_collected():
    entry = parse(TABLE).accelerator_for("ID_FILE_NEW")
    assert entry.has_flag("virtkey")
    assert entry.has_flag("CONTROL")
    assert not entry.has_flag("SHIFT")


def test_a_virtual_key_row_does_not_swallow_the_next_one():
    # VK_F5 is a bare identifier on its own line, which the general statement
    # reader treats as a continuation of the row above it.
    script = parse(TABLE)
    assert script.accelerator_for("ID_PEN_CLEAR").key == "VK_DELETE"


def test_the_line_number_survives():
    assert parse(TABLE).accelerator_for("ID_FILE_NEW").line == 3


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ID_FILE_NEW", "Ctrl+N"),
        ("ID_FILE_OPEN", "Ctrl+O"),
        ("ID_DIAG_VERIFY", "F5"),
        ("ID_PEN_CLEAR", "Shift+Delete"),
        ("ID_PAGE_UP", "Alt+PgUp"),
    ],
)
def test_a_row_describes_itself_the_way_a_menu_would(command, expected):
    assert parse(TABLE).accelerator_for(command).describe() == expected


def test_the_caret_form_means_control_whatever_the_flags_say():
    entry = Accelerator(key="^O", symbol="ID_FILE_OPEN", flags=["ASCII"], quoted=True)
    assert entry.describe() == "Ctrl+O"


def test_an_unbound_command_finds_nothing():
    assert parse(TABLE).accelerator_for("ID_NOT_THERE") is None


def test_a_short_row_is_skipped_rather_than_fatal():
    script = parse('IDR_X ACCELERATORS\nBEGIN\n    "N"\nEND\n')
    assert script.accelerators[0].entries == []


def test_an_unterminated_table_is_an_error():
    from v4t_translate.errors import ParseError

    with pytest.raises(ParseError):
        parse('IDR_X ACCELERATORS\nBEGIN\n    "N", ID_A, VIRTKEY\n')


def test_accelerators_are_counted():
    assert parse(TABLE).counts()["accelerators"] == 5


def test_the_shipped_fixture_has_a_table(sample_rc_path):
    script = parse(sample_rc_path.read_text(encoding="utf-8"))
    assert script.accelerator_for("ID_FILE_NEW").describe() == "Ctrl+N"


# -- the developer note -------------------------------------------------


def test_the_note_names_the_key_that_fires():
    script = parse(MENU_AND_TABLE)
    item = next(i for i in script.menu_items() if i.symbol == "ID_FILE_NEW")
    note = shortcut_note(script, item)
    assert "The key N is not" in note
    assert "ID_FILE_NEW" in note


def test_the_note_says_the_modifier_may_move():
    script = parse(MENU_AND_TABLE)
    item = next(i for i in script.menu_items() if i.symbol == "ID_FILE_NEW")
    assert "Strg" in shortcut_note(script, item)


def test_an_item_with_no_hint_gets_no_note():
    script = parse(MENU_AND_TABLE)
    item = next(i for i in script.menu_items() if i.text == "&File")
    assert shortcut_note(script, item) == ""


def test_a_hint_with_nothing_behind_it_says_so():
    script = parse(MENU_AND_TABLE)
    item = next(i for i in script.menu_items() if i.symbol == "ID_UNBOUND")
    note = shortcut_note(script, item)
    assert "nothing in this file's accelerator tables binds" in note


def test_the_shortcut_property_reads_after_the_tab():
    assert MenuItem(text="&New\tCtrl+N").shortcut == "Ctrl+N"
    assert MenuItem(text="&New").shortcut is None
    assert MenuItem(text="&New\t").shortcut is None
    assert MenuItem(text=None).shortcut is None


# -- the rule -----------------------------------------------------------


def test_splitting_a_caption():
    assert split_hint("&New\tCtrl+N") == ("&New", "Ctrl+N")
    assert split_hint("&New") == ("&New", None)


def test_only_the_first_tab_splits():
    assert split_hint("a\tb\tc") == ("a", "b\tc")


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("Ctrl+N", "N"),
        ("Ctrl-N", "N"),
        ("Strg+Umschalt+F5", "F5"),
        ("F5", "F5"),
        ("Ctrl + N", "N"),
        ("", ""),
    ],
)
def test_finding_the_key(hint, expected):
    assert final_key(hint) == expected


def test_a_translated_modifier_is_fine():
    assert run("&New\tCtrl+N", "&Neu\tStrg+N") == []


def test_a_moved_key_is_an_error():
    findings = run("&New\tCtrl+N", "&Neu\tStrg+U")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "moved from N to U" in findings[0].summary


def test_the_detail_explains_where_the_key_lives():
    detail = run("&New\tCtrl+N", "&Neu\tStrg+U")[0].detail
    assert "accelerator table" in detail


def test_a_dropped_hint_is_reported():
    findings = run("&New\tCtrl+N", "&Neu")
    assert "dropped" in findings[0].summary


def test_a_hint_of_only_modifiers_is_reported():
    findings = run("&New\tCtrl+N", "&Neu\tStrg")
    assert "lost its key" in findings[0].summary


def test_an_invented_hint_is_a_warning_not_an_error():
    findings = run("&Neu", "&Neu\tStrg+N")
    assert findings[0].severity is Severity.WARNING
    assert "added" in findings[0].summary


def test_no_hint_either_side_is_quiet():
    assert run("&New", "&Neu") == []


def test_an_empty_translation_is_skipped():
    assert run("&New\tCtrl+N", "") == []


def test_the_key_comparison_ignores_case():
    assert run("&New\tCtrl+N", "&Neu\tStrg+n") == []


def test_a_function_key_survives():
    assert run("&Verify\tF5", "&Prüfen\tF5") == []


def test_a_named_key_can_be_translated_and_still_pass_only_if_it_matches():
    # Delete is the key name, not a modifier. German would write Entf, and
    # that is a different key as far as this rule can tell, so it is reported.
    assert run("&Purge\tShift+Delete", "&Bereinigung\tUmschalt+Entf")


def test_the_rule_is_registered():
    assert "shortcuts" in rule_names()
