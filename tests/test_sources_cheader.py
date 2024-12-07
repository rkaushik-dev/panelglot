import pytest

from v4t_translate.catalog.model import OriginKind
from v4t_translate.errors import ParseError, SourceError
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.cheader import CHeaderSource, parse_enum, parse_table


@pytest.fixture(scope="module")
def header(fixtures_dir):
    return (fixtures_dir / "v4t_lang.h").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def extraction(fixtures_dir):
    return CHeaderSource().extract(
        SourceOptions(path=fixtures_dir / "v4t_lang.h", root=fixtures_dir)
    )


@pytest.fixture(scope="module")
def messages(extraction):
    return {m.source_text: m for m in extraction.by_key().values()}


def test_enum_order(header):
    names = parse_enum(header)
    assert names[0] == "LNG_PRINT_STARTED"
    assert names[-1] == "LNG_COUNT"
    assert len(names) == 10


def test_an_explicit_value_does_not_break_the_order(header):
    assert parse_enum(header)[0] == "LNG_PRINT_STARTED"


def test_enum_of_a_file_without_one():
    assert parse_enum("int x = 1;") == []


def test_designated_entries(header):
    entries = parse_table(header, "lng_en")
    assert entries[0].symbol == "LNG_PRINT_STARTED"
    assert entries[0].text == "Print started"
    assert entries[4].symbol == "LNG_PEN"


def test_max_annotations(header):
    entries = {e.symbol: e for e in parse_table(header, "lng_en")}
    assert entries["LNG_PRINT_STARTED"].max_chars == 20
    assert entries["LNG_PEN"].max_chars == 6
    assert entries["LNG_UNITS_MM"].max_chars is None


def test_adjacent_literals_are_joined(header):
    entries = {e.symbol: e for e in parse_table(header, "lng_en")}
    assert entries["LNG_CONFIRM_PURGE"].text == "Purge all pens?\nPress OK"


def test_line_numbers_are_recorded(header):
    entries = parse_table(header, "lng_en")
    assert entries[0].line > 20
    assert entries[1].line > entries[0].line


def test_a_table_that_does_not_exist(header):
    with pytest.raises(ParseError, match="no string table called 'lng_de'"):
        parse_table(header, "lng_de")


def test_positional_entries_pair_against_the_enum(fixtures_dir):
    text = (fixtures_dir / "v4t_lang_positional.h").read_text(encoding="utf-8")
    entries = parse_table(text, "lng_en", enum_order=parse_enum(text))
    assert [e.symbol for e in entries] == [
        "LNG_PRINT_STARTED", "LNG_PRINT_STOPPED", "LNG_PURGE_SETTINGS",
    ]


def test_positional_with_no_enum_is_an_error():
    text = 'static const char * const lng_en[3] = { "a", "b" };'
    with pytest.raises(ParseError, match="no enum to pair it with"):
        parse_table(text, "lng_en", enum_order=[])


def test_more_entries_than_ids_is_an_error():
    text = """
    typedef enum { LNG_A, LNG_COUNT } lang_id_t;
    static const char * const lng_en[LNG_COUNT] = { "one", "two" };
    """
    with pytest.raises(ParseError, match="pairing is wrong from entry 2"):
        parse_table(text, "lng_en", enum_order=parse_enum(text))


def test_the_count_sentinel_is_not_an_id():
    text = """
    typedef enum { LNG_A, LNG_B, LNG_COUNT } lang_id_t;
    static const char * const lng_en[LNG_COUNT] = { "one", "two" };
    """
    entries = parse_table(text, "lng_en", enum_order=parse_enum(text))
    assert [e.symbol for e in entries] == ["LNG_A", "LNG_B"]


def test_messages_are_extracted(messages):
    assert "Print started" in messages
    assert "Firing Voltage" in messages
    assert "Ink low in pen %d" in messages


def test_the_origin_names_the_table_and_id(messages):
    origin = messages["Firing Voltage"].origins[0]
    assert origin.kind is OriginKind.C_STRING_TABLE
    assert origin.container == "lng_en"
    assert origin.symbol == "LNG_FIRING_VOLTAGE"


def test_the_character_budget_reaches_the_message(messages):
    assert messages["Pen"].max_chars == 6
    assert messages["Print started"].max_chars == 20


def test_a_string_without_a_budget_has_none(messages):
    assert messages["mm"].max_chars is None


def test_protected_patterns_apply(fixtures_dir):
    extraction = CHeaderSource().extract(
        SourceOptions(path=fixtures_dir / "v4t_lang.h", root=fixtures_dir,
                      protected_patterns=("mm",))
    )
    assert {m.source_text: m for m in extraction.messages}["mm"].protected


def test_stats(extraction):
    assert extraction.stats["entries"] == 9
    assert extraction.stats["enum_ids"] == 10


def test_a_count_mismatch_warns(tmp_path):
    path = tmp_path / "short.h"
    path.write_text(
        "typedef enum { LNG_A, LNG_B, LNG_COUNT } lang_id_t;\n"
        'static const char * const lng_en[LNG_COUNT] = { [LNG_A] = "one" };\n',
        encoding="utf-8",
    )
    extraction = CHeaderSource().extract(SourceOptions(path=path, root=tmp_path))
    assert any("2 ids and the table has 1" in w for w in extraction.warnings)


def test_c_escapes_are_resolved(tmp_path):
    path = tmp_path / "esc.h"
    path.write_text(
        "typedef enum { LNG_A, LNG_COUNT } lang_id_t;\n"
        'static const char * const lng_en[LNG_COUNT] = { [LNG_A] = "a\\tb\\x41\\\\c" };\n',
        encoding="utf-8",
    )
    extraction = CHeaderSource().extract(SourceOptions(path=path, root=tmp_path))
    assert extraction.messages[0].source_text == "a\tbA\\c"


def test_a_missing_file(tmp_path):
    with pytest.raises(SourceError, match="does not exist"):
        CHeaderSource().extract(SourceOptions(path=tmp_path / "nope.h"))


def test_the_reader_is_reachable_through_the_registry():
    from v4t_translate.sources.registry import get_source

    assert get_source("cheader").kind == "cheader"
