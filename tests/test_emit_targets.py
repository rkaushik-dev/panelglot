import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.emit.androidxml import (
    AndroidXmlEmitter,
    qualifier_for,
    values_directory,
)
from v4t_translate.emit.base import EmitOptions
from v4t_translate.emit.cheader import CHeaderEmitter, escape_c_string
from v4t_translate.errors import EmitError
from v4t_translate.locales import resolve
from v4t_translate.sources.androidxml import AndroidXmlSource
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.cheader import CHeaderSource


def catalog_from(source, path, root):
    extraction = source.extract(SourceOptions(path=path, root=root))
    catalog = Catalog(project="V4T")
    for message in extraction.by_key().values():
        catalog.add(message)
    return catalog


@pytest.fixture
def android_catalog(fixtures_dir):
    return catalog_from(AndroidXmlSource(), fixtures_dir / "strings.xml", fixtures_dir)


@pytest.fixture
def c_catalog(fixtures_dir):
    return catalog_from(CHeaderSource(), fixtures_dir / "v4t_lang.h", fixtures_dir)


def translations_of(locale, pairs):
    entries = TranslationSet(locale=locale)
    for source, target in pairs.items():
        entries.set(message_key(source),
                    Translation(text=target, state=TranslationState.APPROVED))
    return entries


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("de-DE", "de-rDE"),
        ("zh-TW", "zh-rTW"),
        ("zh-CN", "zh-rCN"),
        ("pt-BR", "pt-rBR"),
        ("he-IL", "iw-rIL"),
        ("en-US", "en-rUS"),
    ],
)
def test_qualifier(tag, expected):
    assert qualifier_for(resolve(tag)) == expected


def test_values_directory():
    assert values_directory(resolve("zh-TW")) == "values-zh-rTW"


def test_a_language_only_tag_has_no_region():
    from v4t_translate.locales import Locale

    made_up = Locale(tag="eo", english_name="Esperanto",
                     win32_language="LANG_NEUTRAL", win32_sublanguage="SUBLANG_DEFAULT",
                     lcid=0, codepage=1252)
    assert qualifier_for(made_up) == "eo"


def test_android_output_parses(tmp_path, android_catalog):
    from xml.etree import ElementTree

    path = tmp_path / "values-de-rDE" / "strings.xml"
    AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"Print started": "Druck gestartet"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    root = ElementTree.parse(path).getroot()
    assert root.tag == "resources"


def test_android_writes_only_translated_strings(tmp_path, android_catalog):
    path = tmp_path / "strings.xml"
    result = AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"Print started": "Druck gestartet"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    text = path.read_text(encoding="utf-8")
    assert "Druck gestartet" in text
    assert "Printer status" not in text
    assert result.written == 1
    assert result.skipped


def test_android_uses_the_resource_name(tmp_path, android_catalog):
    path = tmp_path / "strings.xml"
    AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"Print started": "Druck gestartet"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    assert '<string name="print_started">' in path.read_text(encoding="utf-8")


def test_android_never_writes_an_untranslatable_string(tmp_path, android_catalog):
    path = tmp_path / "strings.xml"
    AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"V4T Mobile": "V4T Mobil"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    assert "V4T Mobil" not in path.read_text(encoding="utf-8")


def test_android_escapes_an_apostrophe(tmp_path, android_catalog):
    path = tmp_path / "strings.xml"
    AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"Print started": "L'impression"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    assert "L\\'impression" in path.read_text(encoding="utf-8")


def test_android_escapes_xml_markup(tmp_path, android_catalog):
    path = tmp_path / "strings.xml"
    AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"Print started": "Druck & Prüfung"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    assert "&amp;" in path.read_text(encoding="utf-8")


def test_android_round_trips_through_its_own_reader(tmp_path, android_catalog):
    path = tmp_path / "strings.xml"
    AndroidXmlEmitter().emit(
        android_catalog,
        translations_of("de-DE", {"Print started": "L'impression a démarré"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    read = AndroidXmlSource().extract(SourceOptions(path=path, root=tmp_path))
    assert read.messages[0].source_text == "L'impression a démarré"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "plain"),
        ('a "quote"', 'a \\"quote\\"'),
        ("back\\slash", "back\\\\slash"),
        ("a\nb", "a\\nb"),
    ],
)
def test_escape_c(text, expected):
    assert escape_c_string(text) == expected


def test_escape_c_writes_hex_for_cp1252():
    assert escape_c_string("Zündspannung", codepage=1252) == 'Z\\xFC""ndspannung'


def test_escape_c_closes_the_literal_after_a_hex_escape():
    # "\x41" followed by "2" would read as \x412 without the break.
    assert escape_c_string("ü2", codepage=1252) == '\\xFC""2'


def test_escape_c_uses_a_universal_name_without_a_codepage():
    assert escape_c_string("ü") == "\\u00FC"


def test_escape_c_rejects_what_the_codepage_cannot_hold():
    with pytest.raises(EmitError, match="codepage 1252"):
        escape_c_string("刪", codepage=1252)


def test_cheader_output(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    result = CHeaderEmitter().emit(
        c_catalog,
        translations_of("de-DE", {"Print started": "Druck gestartet", "Pen": "Stift"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    text = path.read_text(encoding="ascii")
    assert "static const char * const lng_de[LNG_COUNT]" in text
    assert '[LNG_PRINT_STARTED]   = "Druck gestartet",' in text
    assert '[LNG_PEN]             = "Stift",' in text
    assert result.written == 2


def test_cheader_uses_designated_initialisers(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(c_catalog, TranslationSet(locale="de-DE"),
                          EmitOptions(path=path, locale=resolve("de-DE")))
    text = path.read_text(encoding="ascii")
    # One per slot. The array bound also reads [LNG_COUNT], so count the
    # initialiser lines rather than the substring.
    assert sum(1 for line in text.splitlines() if line.strip().startswith("[LNG_")) == 9


def test_cheader_marks_untranslated_slots(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(c_catalog, TranslationSet(locale="de-DE"),
                          EmitOptions(path=path, locale=resolve("de-DE")))
    assert "/* untranslated */" in path.read_text(encoding="ascii")


def test_cheader_falls_back_to_english(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(c_catalog, TranslationSet(locale="de-DE"),
                          EmitOptions(path=path, locale=resolve("de-DE")))
    assert '"Print started"' in path.read_text(encoding="ascii")


def test_cheader_can_leave_them_empty(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(
        c_catalog, TranslationSet(locale="de-DE"),
        EmitOptions(path=path, locale=resolve("de-DE"), fallback_to_source=False),
    )
    assert '"Print started"' not in path.read_text(encoding="ascii")


def test_cheader_has_an_include_guard(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(c_catalog, TranslationSet(locale="de-DE"),
                          EmitOptions(path=path, locale=resolve("de-DE")))
    text = path.read_text(encoding="ascii")
    assert "#ifndef V4T_LANG_DE_DE_H" in text
    assert "#endif /* V4T_LANG_DE_DE_H */" in text


def test_cheader_output_is_pure_ascii(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(
        c_catalog,
        translations_of("de-DE", {"Firing Voltage": "Zündspannung"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    data = path.read_bytes()
    assert all(byte < 128 for byte in data)
    assert b"Z\\xFC" in data


def test_cheader_output_can_be_read_back(tmp_path, c_catalog):
    path = tmp_path / "lng_de.h"
    CHeaderEmitter().emit(
        c_catalog,
        translations_of("de-DE", {"Print started": "Druck gestartet"}),
        EmitOptions(path=path, locale=resolve("de-DE")),
    )
    # The reader looks for lng_en, so point it at the array we wrote.
    from v4t_translate.sources.cheader import parse_table

    entries = parse_table(path.read_text(encoding="ascii"), "lng_de")
    assert entries[0].symbol == "LNG_PRINT_STARTED"
    assert entries[0].text == "Druck gestartet"


def test_cheader_with_nothing_to_write(tmp_path):
    with pytest.raises(EmitError, match="no messages came from"):
        CHeaderEmitter().emit(
            Catalog(project="X"), TranslationSet(locale="de-DE"),
            EmitOptions(path=tmp_path / "x.h", locale=resolve("de-DE")),
        )
