import pytest

from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.emit.base import EmitOptions, Emitter
from v4t_translate.emit.po import PoEmitter, po_quote
from v4t_translate.emit.registry import available_kinds, get_emitter
from v4t_translate.errors import ConfigError
from v4t_translate.locales import resolve


def origin(container="IDD_BARCODE", symbol="IDC_STATIC", line=26):
    return Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                  container=container, symbol=symbol, line=line)


@pytest.fixture
def catalog():
    catalog = Catalog(project="V4T-TIJ")
    catalog.add(Message(key="bar-height.aaa111", source_text="Bar Height",
                        origins=[origin()], max_width_px=54))
    catalog.add(Message(key="hint.bbb222", source_text='Say "no" then\ncontinue',
                        origins=[origin(symbol="IDC_HINT")], max_width_px=340,
                        max_lines=2))
    catalog.add(Message(key="mm.ccc333", source_text="mm", protected=True,
                        origins=[origin(container="STRINGTABLE", symbol="IDS_MM")]))
    catalog.add(Message(key="volts.ddd444",
                        source_text="Please input from %.1fV to %.1fV.",
                        origins=[origin(symbol="IDS_RANGE")],
                        developer_note="Both numbers come from the board."))
    catalog.add(Message(key="pen.eee555", source_text="Pen", origins=[origin()],
                        max_chars=6))
    return catalog


@pytest.fixture
def translations():
    entries = TranslationSet(locale="de-DE")
    entries.set("bar-height.aaa111", Translation(text="Balkenhöhe",
                                                 state=TranslationState.APPROVED))
    entries.set("volts.ddd444", Translation(text="Bitte %.1fV bis %.1fV eingeben.",
                                            state=TranslationState.NEEDS_REVIEW))
    return entries


@pytest.fixture
def written(tmp_path, catalog, translations):
    path = tmp_path / "po" / "de-DE.po"
    result = PoEmitter().emit(catalog, translations,
                              EmitOptions(path=path, locale=resolve("de-DE")))
    return path.read_text(encoding="utf-8"), result


def test_quote_a_simple_string():
    assert po_quote("Bar Height") == ['"Bar Height"']


def test_quote_escapes_quotes_and_backslashes():
    assert po_quote('a "b" \\c') == ['"a \\"b\\" \\\\c"']


def test_quote_of_a_multiline_string():
    assert po_quote("one\ntwo") == ['""', '"one\\n"', '"two"']


def test_quote_of_an_empty_string():
    assert po_quote("") == ['""']


def test_the_header(written):
    text, _ = written
    assert '"Language: de-DE\\n"' in text
    assert '"Content-Type: text/plain; charset=UTF-8\\n"' in text
    assert '"X-Source-Language: en-US\\n"' in text


def test_a_translated_entry(written):
    text, _ = written
    assert 'msgctxt "bar-height.aaa111"' in text
    assert 'msgid "Bar Height"' in text
    assert 'msgstr "Balkenhöhe"' in text


def test_an_untranslated_entry_is_written_empty(written):
    text, result = written
    assert 'msgctxt "pen.eee555"' in text
    assert "pen.eee555" in result.skipped


def test_the_key_is_the_context(written):
    text, _ = written
    assert text.count("msgctxt ") == 5


def test_source_references(written):
    text, _ = written
    assert "#: V4T.rc:26 (IDD_BARCODE/IDC_STATIC)" in text


def test_a_developer_note(written):
    text, _ = written
    assert "#. Both numbers come from the board." in text


def test_a_pixel_budget_is_noted(written):
    text, _ = written
    assert "#. Space: 54 pixels" in text


def test_a_multiline_budget_says_so(written):
    text, _ = written
    assert "#. Space: 340 pixels over 2 lines" in text


def test_a_character_budget_is_noted(written):
    text, _ = written
    assert "#. Space: 6 characters" in text


def test_a_protected_string_says_so(written):
    text, _ = written
    assert "#. Do not translate." in text


def test_a_needs_review_entry_is_fuzzy(written):
    text, _ = written
    assert "#, fuzzy, c-format" in text


def test_an_approved_entry_is_not_fuzzy(written):
    text, _ = written
    block = text.split('msgctxt "bar-height.aaa111"')[0].rsplit("\n\n", 1)[-1]
    assert "fuzzy" not in block


def test_a_multiline_message(written):
    text, _ = written
    assert 'msgid ""\n"Say \\"no\\" then\\n"\n"continue"' in text


def test_the_counts(written):
    _, result = written
    assert result.written == 2
    assert len(result.skipped) == 3
    assert result.bytes_written > 0


def test_the_file_is_utf8(tmp_path, catalog, translations):
    path = tmp_path / "de-DE.po"
    PoEmitter().emit(catalog, translations,
                     EmitOptions(path=path, locale=resolve("de-DE")))
    assert "Balkenhöhe" in path.read_bytes().decode("utf-8")


def test_the_registry_knows_every_emitter():
    assert set(available_kinds()) == {"rc", "v4l", "androidxml", "cheader", "po",
                                      "xliff"}


@pytest.mark.parametrize("kind", ["rc", "v4l", "androidxml", "cheader", "po", "xliff"])
def test_each_emitter_satisfies_the_protocol(kind):
    emitter = get_emitter(kind)
    assert isinstance(emitter, Emitter)
    assert emitter.kind == kind


def test_an_unknown_emitter_lists_the_real_ones():
    with pytest.raises(ConfigError) as excinfo:
        get_emitter("pdf")
    assert "androidxml" in str(excinfo.value)
