import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.emit.base import EmitOptions
from v4t_translate.emit.rcpack import RcEmitter, splice
from v4t_translate.errors import EmitError
from v4t_translate.locales import resolve
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.rc.extract import RcSource
from v4t_translate.sources.rc.lexer import escape_rc_string, quote_rc_string
from v4t_translate.sources.rc.parser import parse_resource_script

GERMAN = {
    "Barcode Properties": "Barcode-Eigenschaften",
    "Bar Height": "Balkenhöhe",
    "Width": "Breite",
    "Human Readable": "Menschenlesbar",
    "Print started": "Druck gestartet",
    "Purge offset must be less than group offset": (
        "Der Purge-Versatz muss kleiner als der Gruppenversatz sein"
    ),
    "Date&&Time Format": "Datums&&Zeitformat",
    "&File": "&Datei",
    "E&xit": "B&eenden",
    'Please input from %.1fV to %.1fV.': "Bitte geben Sie %.1fV bis %.1fV ein.",
}


@pytest.fixture
def catalog(sample_rc_path):
    extraction = RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent)
    )
    catalog = Catalog(project="V4T-TIJ")
    for message in extraction.by_key().values():
        catalog.add(message)
    return catalog


@pytest.fixture
def translations():
    entries = TranslationSet(locale="de-DE")
    for source, target in GERMAN.items():
        entries.set(message_key(source),
                    Translation(text=target, state=TranslationState.APPROVED))
    return entries


@pytest.fixture
def emitted(tmp_path, sample_rc_path, catalog, translations):
    path = tmp_path / "out" / "V4T.de-DE.rc"
    result = RcEmitter().emit(
        catalog, translations,
        EmitOptions(path=path, locale=resolve("de-DE"), source_path=sample_rc_path),
    )
    return path, result, path.read_text(encoding="cp1252")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "plain"),
        ('a "quote"', 'a \\"quote\\"'),
        ("back\\slash", "back\\\\slash"),
        ("a\nb", "a\\nb"),
        ("a\tb", "a\\tb"),
        ("Date&&Time", "Date&&Time"),
        ("&Print", "&Print"),
    ],
)
def test_escape(text, expected):
    assert escape_rc_string(text) == expected


def test_quote_wraps():
    assert quote_rc_string("Bar Height") == '"Bar Height"'


def test_escape_round_trips():
    from v4t_translate.sources.rc.lexer import unescape_rc_string

    for text in ('a "quote"', "back\\slash", "a\nb", "Date&&Time", "&Print"):
        assert unescape_rc_string(escape_rc_string(text)) == text


def test_splice_applies_in_the_right_places():
    from v4t_translate.emit.rcpack import _Replacement

    source = "abcdefgh"
    result = splice(source, [_Replacement(0, 2, "XY"), _Replacement(6, 8, "ZZZ")])
    assert result == "XYcdefZZZ"


def test_splice_of_nothing_returns_the_source():
    assert splice("abc", []) == "abc"


def test_splice_rejects_an_overlap():
    from v4t_translate.emit.rcpack import _Replacement

    with pytest.raises(EmitError, match="overlap"):
        splice("abcdef", [_Replacement(0, 4, "X"), _Replacement(2, 6, "Y")])


def test_the_file_is_written(emitted):
    path, result, _ = emitted
    assert path.exists()
    assert result.bytes_written > 0


def test_translations_are_spliced_in(emitted):
    _, _, text = emitted
    assert '"Balkenhöhe"' in text
    assert '"Menschenlesbar"' in text
    assert '"Druck gestartet"' in text


def test_untranslated_strings_keep_their_english(emitted):
    _, _, text = emitted
    assert '"Bearer thickness"' in text
    assert '"Module size"' in text


def test_everything_we_do_not_understand_is_untouched(emitted):
    _, _, text = emitted
    assert 'VALUE "CompanyName", "Sellenis"' in text
    assert "IDD_BARCODE_PROPS AFX_DIALOG_LAYOUT" in text
    assert 'IDR_MAINFRAME           ICON                    "res\\\\V4T.ico"' in text


def test_comments_survive(emitted):
    _, _, text = emitted
    assert "// Microsoft Visual C++ generated resource script." in text
    assert "// String Table" in text


def test_geometry_is_untouched(emitted):
    _, _, text = emitted
    assert "IDD_BARCODE_PROPS DIALOGEX 0, 0, 316, 214" in text


def test_the_language_statement_is_swapped(emitted):
    _, _, text = emitted
    assert "LANGUAGE LANG_GERMAN, SUBLANG_GERMAN" in text
    assert "SUBLANG_ENGLISH_US" not in text


def test_the_escaped_ampersand_survives_the_round_trip(emitted):
    _, _, text = emitted
    assert '"Datums&&Zeitformat"' in text


def test_a_joined_string_becomes_one_literal(emitted):
    _, _, text = emitted
    assert '"Der Purge-Versatz muss kleiner als der Gruppenversatz sein"' in text


def test_a_format_string_keeps_its_specifiers(emitted):
    _, _, text = emitted
    assert '"Bitte geben Sie %.1fV bis %.1fV ein."' in text


def test_the_result_counts(emitted):
    _, result, _ = emitted
    assert result.written == len(GERMAN)
    assert result.fell_back
    assert 0 < result.coverage < 1


def test_the_summary_reads(emitted):
    _, result, _ = emitted
    assert "translated" in result.summary()


def test_the_output_still_parses(emitted):
    _, _, text = emitted
    script = parse_resource_script(text, path="V4T.de-DE.rc")
    assert script.counts()["dialogs"] == 2
    assert script.dialog("IDD_BARCODE_PROPS").caption == "Barcode-Eigenschaften"


def test_the_output_has_the_same_shape_as_the_input(emitted, sample_rc_text):
    _, _, text = emitted
    before = parse_resource_script(sample_rc_text).counts()
    after = parse_resource_script(text).counts()
    assert before == after


def test_the_dialog_font_is_swapped_for_chinese(tmp_path, sample_rc_path, catalog):
    path = tmp_path / "V4T.zh-TW.rc"
    RcEmitter().emit(
        catalog, TranslationSet(locale="zh-TW"),
        EmitOptions(path=path, locale=resolve("zh-TW"), source_path=sample_rc_path),
    )
    text = path.read_text(encoding="cp950")
    assert '"PMingLiU"' in text
    assert '"MS Shell Dlg"' not in text


def test_the_font_is_left_alone_for_a_latin_locale(emitted):
    _, _, text = emitted
    assert '"MS Shell Dlg"' in text


def test_fallback_off_blanks_the_untranslated(tmp_path, sample_rc_path, catalog,
                                              translations):
    path = tmp_path / "strict.rc"
    RcEmitter().emit(
        catalog, translations,
        EmitOptions(path=path, locale=resolve("de-DE"), source_path=sample_rc_path,
                    fallback_to_source=False),
    )
    text = path.read_text(encoding="cp1252")
    assert '"Bearer thickness"' not in text
    assert '"Balkenhöhe"' in text


def test_a_character_outside_the_codepage_is_refused(tmp_path, sample_rc_path, catalog):
    entries = TranslationSet(locale="de-DE")
    entries.set(message_key("Bar Height"),
                Translation(text="條高", state=TranslationState.APPROVED))
    with pytest.raises(EmitError, match="cannot be written in cp1252"):
        RcEmitter().emit(
            catalog, entries,
            EmitOptions(path=tmp_path / "bad.rc", locale=resolve("de-DE"),
                        source_path=sample_rc_path),
        )


def test_the_encoding_can_be_overridden(tmp_path, sample_rc_path, catalog):
    entries = TranslationSet(locale="de-DE")
    entries.set(message_key("Bar Height"),
                Translation(text="條高", state=TranslationState.APPROVED))
    path = tmp_path / "utf8.rc"
    RcEmitter().emit(
        catalog, entries,
        EmitOptions(path=path, locale=resolve("de-DE"), source_path=sample_rc_path,
                    encoding="utf-8"),
    )
    assert "條高" in path.read_text(encoding="utf-8")


def test_the_emitter_needs_a_source_path(tmp_path, catalog):
    with pytest.raises(EmitError, match="needs source_path"):
        RcEmitter().emit(catalog, TranslationSet(locale="de-DE"),
                         EmitOptions(path=tmp_path / "x.rc", locale=resolve("de-DE")))


def test_a_missing_source_file(tmp_path, catalog):
    with pytest.raises(EmitError, match="does not exist"):
        RcEmitter().emit(
            catalog, TranslationSet(locale="de-DE"),
            EmitOptions(path=tmp_path / "x.rc", locale=resolve("de-DE"),
                        source_path=tmp_path / "nope.rc"),
        )
