import pytest

from v4t_translate.errors import ParseError
from v4t_translate.sources.rc.symbols import (
    STANDARD_IDS,
    SymbolTable,
    load_resource_header,
    parse_resource_header,
)

HEADER = """\
//{{NO_DEPENDENCIES}}
// Microsoft Visual C++ generated include file.
// Used by V4T.rc
//
#define IDD_ABOUTBOX                    100
#define IDD_BARCODE_PROPS               101
#define IDS_PRINT_STARTED               102
#define IDC_PEN_BASE                    1200
#define IDC_PEN_2                       (IDC_PEN_BASE + 1)
#define IDC_BAR_HEIGHT                  1301
#define IDC_FLAGS                       0x0004
#define IDC_LEGACY                      1302L
#define IDS_TITLE_TEXT                  "V4T"
#define MAKE_PEN(n)                     (IDC_PEN_BASE + (n))

// Next default values for new objects
//
#ifdef APSTUDIO_INVOKED
#ifndef APSTUDIO_READONLY_SYMBOLS
#define _APS_NEXT_RESOURCE_VALUE        213
#define _APS_NEXT_CONTROL_VALUE         1400
#endif
#endif
"""


@pytest.fixture
def table():
    return parse_resource_header(HEADER, path="resource.h")


def test_plain_defines(table):
    assert table.get("IDD_ABOUTBOX") == 100
    assert table.get("IDC_BAR_HEIGHT") == 1301


def test_hex_define(table):
    assert table.get("IDC_FLAGS") == 4


def test_integer_suffix_is_ignored(table):
    assert table.get("IDC_LEGACY") == 1302


def test_arithmetic_over_an_earlier_symbol(table):
    assert table.get("IDC_PEN_2") == 1201


def test_string_defines_are_skipped(table):
    assert "IDS_TITLE_TEXT" not in table


def test_function_like_macros_are_skipped(table):
    assert "MAKE_PEN" not in table


def test_apstudio_bookkeeping_is_read_but_harmless(table):
    assert table.get("_APS_NEXT_CONTROL_VALUE") == 1400


def test_standard_ids_are_always_present(table):
    for name, value in STANDARD_IDS.items():
        assert table.get(name) == value


def test_standard_ids_are_present_in_an_empty_table():
    assert SymbolTable().get("IDOK") == 1


def test_a_header_may_override_a_standard_id():
    # Rare, but legal, and the header wins.
    table = parse_resource_header("#define IDHELP 900")
    assert table.get("IDHELP") == 900


def test_names_for_a_shared_value_are_sorted(table):
    table.define("IDC_ALIAS", 1301)
    assert table.names_for(1301) == ["IDC_ALIAS", "IDC_BAR_HEIGHT"]


def test_names_for_a_value_nobody_uses(table):
    assert table.names_for(999999) == []


def test_idc_static_is_anonymous(table):
    assert table.is_anonymous("IDC_STATIC")
    assert table.is_anonymous("-1")
    assert not table.is_anonymous("IDC_BAR_HEIGHT")


def test_a_symbol_defined_as_minus_one_is_anonymous():
    table = parse_resource_header("#define IDC_NOTHING -1")
    assert table.is_anonymous("IDC_NOTHING")


def test_redefining_to_the_same_value_is_allowed(table):
    table.define("IDD_ABOUTBOX", 100)
    assert table.get("IDD_ABOUTBOX") == 100


def test_redefining_to_a_different_value_is_an_error(table):
    with pytest.raises(ParseError, match="defined twice"):
        table.define("IDD_ABOUTBOX", 101)


def test_trailing_comments_do_not_leak_into_the_value():
    table = parse_resource_header("#define IDC_X  1200  // the x control")
    assert table.get("IDC_X") == 1200


def test_block_comment_on_the_same_line():
    table = parse_resource_header("#define IDC_Y  1201  /* y */")
    assert table.get("IDC_Y") == 1201


def test_spacing_around_the_hash_is_tolerated():
    table = parse_resource_header("  #  define IDC_Z 7")
    assert table.get("IDC_Z") == 7


def test_len_counts_standard_ids_too():
    table = parse_resource_header("#define IDC_ONLY 1")
    assert len(table) == len(STANDARD_IDS) + 1


def test_load_from_disk_handles_a_bom(tmp_path):
    path = tmp_path / "resource.h"
    path.write_text(HEADER, encoding="utf-8-sig")
    table = load_resource_header(path)
    assert table.get("IDD_ABOUTBOX") == 100
    assert table.origin == str(path)


def test_load_from_disk_falls_back_to_ansi(tmp_path):
    path = tmp_path / "resource.h"
    path.write_bytes("#define IDS_UMLAUT 5 // Aufl\xf6sung\n".encode("cp1252"))
    table = load_resource_header(path)
    assert table.get("IDS_UMLAUT") == 5
