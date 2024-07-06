from v4t_translate.sources.rc.ast import (
    Control,
    Dialog,
    Menu,
    MenuItem,
    RawBlock,
    ResourceScript,
    StringEntry,
    StringTable,
)


def label(caption="Bar Height", symbol="IDC_STATIC", **kw):
    kw.setdefault("statement", "LTEXT")
    return Control(symbol=symbol, caption=caption, **kw)


def test_has_style_is_case_insensitive():
    control = label(styles=["WS_TABSTOP", "bs_multiline"])
    assert control.has_style("BS_MULTILINE")
    assert control.has_style("ws_tabstop")
    assert not control.has_style("SS_CENTER")


def test_a_short_static_is_single_line():
    assert not label(height=8).is_multiline


def test_a_tall_static_wraps():
    assert label(height=24).is_multiline


def test_nowordwrap_beats_height():
    assert not label(height=24, styles=["SS_LEFTNOWORDWRAP"]).is_multiline


def test_a_multiline_button_wraps_regardless_of_height():
    control = Control(statement="PUSHBUTTON", symbol="IDOK", caption="OK", height=8,
                      styles=["BS_MULTILINE"])
    assert control.is_multiline


def test_an_edit_control_is_not_multiline_by_height_alone():
    control = Control(statement="EDITTEXT", symbol="IDC_EDIT", height=40)
    assert not control.is_multiline


def test_captioned_controls_skips_the_ones_without_text():
    dialog = Dialog(
        symbol="IDD_BARCODE",
        controls=[
            label("Bar Height"),
            Control(statement="EDITTEXT", symbol="IDC_HEIGHT"),
            label("Width"),
        ],
    )
    assert [c.caption for c in dialog.captioned_controls()] == ["Bar Height", "Width"]


def test_captioned_controls_skips_an_empty_caption():
    dialog = Dialog(symbol="IDD_X", controls=[label(""), label("Real")])
    assert [c.caption for c in dialog.captioned_controls()] == ["Real"]


def test_control_by_symbol():
    dialog = Dialog(symbol="IDD_X", controls=[label(symbol="IDC_A"), label(symbol="IDC_B")])
    assert dialog.control_by_symbol("IDC_B").symbol == "IDC_B"
    assert dialog.control_by_symbol("IDC_MISSING") is None


def test_dialog_defaults_match_what_the_editor_writes():
    dialog = Dialog(symbol="IDD_X")
    assert dialog.statement == "DIALOGEX"
    assert dialog.font_name == "MS Shell Dlg"
    assert dialog.font_size == 8


def test_menu_walk_is_depth_first():
    menu = Menu(
        symbol="IDR_MAIN",
        items=[
            MenuItem(text="&File", is_popup=True, children=[
                MenuItem(text="&New", symbol="ID_FILE_NEW"),
                MenuItem(text="&Open", symbol="ID_FILE_OPEN"),
            ]),
            MenuItem(text="&Help", is_popup=True, children=[
                MenuItem(text="&About", symbol="ID_APP_ABOUT"),
            ]),
        ],
    )
    assert [i.text for i in menu.walk()] == ["&File", "&New", "&Open", "&Help", "&About"]


def test_separator_carries_no_text():
    item = MenuItem(text=None, is_separator=True)
    assert list(item.walk()) == [item]


def script():
    return ResourceScript(
        path="V4T.rc",
        dialogs=[
            Dialog(symbol="IDD_A", controls=[label(), label("Width")]),
            Dialog(symbol="IDD_B", controls=[label("Spacing")]),
        ],
        string_tables=[
            StringTable(entries=[
                StringEntry("IDS_STARTED", "Print started"),
                StringEntry("IDS_STOPPED", "Print stopped"),
            ]),
            StringTable(entries=[StringEntry("IDS_PURGE", "Purge Settings")]),
        ],
        menus=[Menu(symbol="IDR_MAIN", items=[
            MenuItem(text="&File", is_popup=True, children=[MenuItem(text="E&xit")]),
        ])],
        raw_blocks=[RawBlock(symbol="IDB_LOGO", statement="BITMAP", text="...")],
    )


def test_dialog_lookup():
    assert script().dialog("IDD_B").controls[0].caption == "Spacing"
    assert script().dialog("IDD_NOPE") is None


def test_string_entries_spans_every_table():
    assert [e.symbol for e in script().string_entries()] == [
        "IDS_STARTED",
        "IDS_STOPPED",
        "IDS_PURGE",
    ]


def test_menu_items_flattens_every_menu():
    assert [i.text for i in script().menu_items()] == ["&File", "E&xit"]


def test_counts():
    assert script().counts() == {
        "dialogs": 2,
        "controls": 3,
        "string_tables": 2,
        "strings": 3,
        "menus": 1,
        "menu_items": 2,
        "raw_blocks": 1,
    }


def test_an_empty_script_counts_zeros():
    assert set(ResourceScript(path="x.rc").counts().values()) == {0}
