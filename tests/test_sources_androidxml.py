import pytest

from v4t_translate.catalog.model import OriginKind
from v4t_translate.errors import ParseError, SourceError
from v4t_translate.sources.androidxml import (
    AndroidXmlSource,
    escape_android,
    unescape_android,
)
from v4t_translate.sources.base import SourceOptions


@pytest.fixture(scope="module")
def extraction(fixtures_dir):
    path = fixtures_dir / "strings.xml"
    return AndroidXmlSource().extract(SourceOptions(path=path, root=fixtures_dir))


@pytest.fixture(scope="module")
def messages(extraction):
    return {m.source_text: m for m in extraction.by_key().values()}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Print started", "Print started"),
        (r"It\'s here", "It's here"),
        (r"Say \"hi\"", 'Say "hi"'),
        (r"a\nb", "a\nb"),
        (r"a\tb", "a\tb"),
        (r"path\\to", "path\\to"),
        ('"  keeps spaces  "', "  keeps spaces  "),
        ("collapses\n   whitespace", "collapses whitespace"),
        (r"trailing\\", "trailing\\"),
        (r"\q", "q"),
    ],
)
def test_unescape(raw, expected):
    assert unescape_android(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Print started", "Print started"),
        ("It's here", r"It\'s here"),
        ('Say "hi"', r"Say \"hi\""),
        ("a\nb", r"a\nb"),
        ("trailing ", '"trailing\\ "'.replace("\\ ", " ")),
    ],
)
def test_escape(text, expected):
    assert escape_android(text) == expected


def test_escape_round_trips_through_unescape():
    for text in ("It's here", 'Say "hi"', "a\nb", " leading", "trailing "):
        assert unescape_android(escape_android(text)) == text


def test_plain_strings_are_collected(messages):
    assert "Print started" in messages
    assert "Firing Voltage" in messages


def test_the_origin_names_the_resource(messages):
    origin = messages["Print started"].origins[0]
    assert origin.kind is OriginKind.ANDROID_STRING
    assert origin.container == "print_started"


def test_an_escaped_apostrophe_reaches_the_translator_unescaped(messages):
    assert "It's not safe to open the printhead" in messages


def test_a_quoted_string_keeps_its_trailing_space(messages):
    assert "Purge offset must be less than " in messages


def test_source_wrapping_is_collapsed(messages):
    assert "A caption that the developer wrapped over two lines" in messages


def test_an_escaped_newline_survives(messages):
    assert "First line\nSecond line" in messages


def test_inline_markup_is_kept(messages):
    assert "Tap <b>Purge</b> to continue" in messages


def test_an_empty_string_is_not_a_message(messages):
    assert "" not in messages


def test_a_non_string_element_is_ignored(messages):
    assert "#FF6600" not in messages


def test_translatable_false_is_protected(messages):
    assert messages["V4T Mobile"].protected
    assert "translatable" in messages["V4T Mobile"].developer_note


def test_a_normal_string_is_not_protected(messages):
    assert not messages["Print started"].protected


def test_plural_items_are_separate_messages(messages):
    assert "%d pen" in messages
    assert "%d pens" in messages


def test_plural_symbols_carry_the_quantity(messages):
    assert messages["%d pen"].origins[0].symbol == "pen_count[one]"
    assert messages["%d pens"].origins[0].symbol == "pen_count[other]"


def test_array_items_are_separate_messages(messages):
    assert messages["Normal"].origins[0].symbol == "orientations[0]"
    assert messages["Inverted"].origins[0].symbol == "orientations[1]"


def test_translatable_false_on_an_array_covers_its_items(messages):
    assert messages["SENC"].protected
    assert messages["MCR"].protected


def test_protected_patterns_still_apply(fixtures_dir):
    extraction = AndroidXmlSource().extract(
        SourceOptions(path=fixtures_dir / "strings.xml", root=fixtures_dir,
                      protected_patterns=("mm",))
    )
    assert {m.source_text: m for m in extraction.messages}["mm"].protected


def test_stats(extraction):
    assert extraction.stats["strings"] == 13
    assert extraction.stats["plurals"] == 1
    assert extraction.stats["arrays"] == 2


def test_a_missing_file(tmp_path):
    with pytest.raises(SourceError, match="does not exist"):
        AndroidXmlSource().extract(SourceOptions(path=tmp_path / "nope.xml"))


def test_broken_xml_reports_a_position(tmp_path):
    path = tmp_path / "strings.xml"
    path.write_text("<resources><string name='a'>unclosed</resources>", encoding="utf-8")
    with pytest.raises(ParseError):
        AndroidXmlSource().extract(SourceOptions(path=path, root=tmp_path))


def test_the_wrong_root_element(tmp_path):
    path = tmp_path / "strings.xml"
    path.write_text("<manifest/>", encoding="utf-8")
    with pytest.raises(ParseError, match="expected <resources>"):
        AndroidXmlSource().extract(SourceOptions(path=path, root=tmp_path))


def test_a_string_with_no_name_warns(tmp_path):
    path = tmp_path / "strings.xml"
    path.write_text("<resources><string>anonymous</string></resources>", encoding="utf-8")
    extraction = AndroidXmlSource().extract(SourceOptions(path=path, root=tmp_path))
    assert any("no name" in w for w in extraction.warnings)
    assert extraction.messages == []


def test_the_reader_is_reachable_through_the_registry():
    from v4t_translate.sources.registry import get_source

    assert get_source("androidxml").kind == "androidxml"
