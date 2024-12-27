import struct

import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.emit.base import EmitOptions
from v4t_translate.emit.v4l import (
    FLAG_RTL,
    FLAG_UTF16,
    FORMAT_VERSION,
    HEADER_SIZE,
    MAGIC,
    V4lEmitter,
    build_pack,
    read_pack,
    table_signature,
)
from v4t_translate.errors import EmitError
from v4t_translate.locales import resolve
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.cheader import CHeaderSource

STRINGS = ["Print started", "Print stopped", "Purge Settings"]
SYMBOLS = ["LNG_PRINT_STARTED", "LNG_PRINT_STOPPED", "LNG_PURGE_SETTINGS"]

GERMAN = {
    "Print started": "Druck gestartet",
    "Print stopped": "Druck gestoppt",
    "Purge Settings": "Bereinigungseinstellungen",
    "Firing Voltage": "Zündspannung",
    "Pen": "Stift",
}


@pytest.fixture
def catalog(fixtures_dir):
    extraction = CHeaderSource().extract(
        SourceOptions(path=fixtures_dir / "v4t_lang.h", root=fixtures_dir)
    )
    catalog = Catalog(project="V4T-Mini")
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


def test_a_pack_starts_with_the_magic():
    data = build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=0x0407, codepage=1252)
    assert data[:4] == MAGIC


def test_round_trip_through_the_reader():
    data = build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=0x0407, codepage=1252)
    pack = read_pack(data)
    assert pack.strings == STRINGS
    assert pack.tag == "de-DE"
    assert pack.lcid == 0x0407
    assert pack.codepage == 1252
    assert pack.version == FORMAT_VERSION
    assert len(pack) == 3


def test_an_eight_bit_pack_is_not_utf16():
    pack = read_pack(build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=0x0407,
                                codepage=1252))
    assert not pack.is_utf16
    assert not pack.flags & FLAG_UTF16


def test_a_utf16_pack_round_trips_chinese():
    strings = ["刪除", "新的", "取消"]
    data = build_pack(strings, SYMBOLS, tag="zh-TW", lcid=0x0404, codepage=None)
    pack = read_pack(data)
    assert pack.is_utf16
    assert pack.strings == strings
    assert pack.codepage == 0


def test_an_rtl_pack_is_flagged():
    pack = read_pack(build_pack(STRINGS, SYMBOLS, tag="he-IL", lcid=0x040D,
                                codepage=1255, rtl=True))
    assert pack.is_rtl
    assert pack.flags & FLAG_RTL


def test_empty_strings_survive():
    pack = read_pack(build_pack(["", "a", ""], SYMBOLS, tag="de-DE", lcid=1,
                                codepage=1252))
    assert pack.strings == ["", "a", ""]


def test_german_accents_survive_cp1252():
    strings = ["Zündspannung", "Auflösung", "Größe"]
    pack = read_pack(build_pack(strings, SYMBOLS, tag="de-DE", lcid=0x0407,
                                codepage=1252))
    assert pack.strings == strings


def test_the_signature_covers_the_names():
    assert table_signature(SYMBOLS) != table_signature(SYMBOLS[::-1])


def test_a_renamed_id_changes_the_signature():
    renamed = ["LNG_PRINT_BEGAN", *SYMBOLS[1:]]
    assert table_signature(renamed) != table_signature(SYMBOLS)


def test_an_inserted_id_changes_the_signature():
    inserted = [SYMBOLS[0], "LNG_NEW_THING", *SYMBOLS[1:]]
    assert table_signature(inserted) != table_signature(SYMBOLS)


def test_the_separator_stops_a_collision():
    assert table_signature(["AB", "C"]) != table_signature(["A", "BC"])


def test_the_signature_is_in_the_header():
    data = build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=1, codepage=1252)
    assert read_pack(data).signature == table_signature(SYMBOLS)


def test_a_mismatched_string_and_symbol_count():
    with pytest.raises(EmitError, match="cannot be paired"):
        build_pack(STRINGS, SYMBOLS[:2], tag="de-DE", lcid=1, codepage=1252)


def test_a_string_outside_the_codepage_names_its_id():
    with pytest.raises(EmitError, match="LNG_PRINT_STOPPED"):
        build_pack(["ok", "刪除", "ok"], SYMBOLS, tag="de-DE", lcid=1, codepage=1252)


def test_a_pack_that_is_too_big():
    many = ["x" * 200] * 400
    with pytest.raises(EmitError, match="the panel can map"):
        build_pack(many, [f"LNG_{i}" for i in range(400)], tag="de-DE", lcid=1,
                   codepage=1252)


def test_the_tag_is_padded_and_trimmed():
    data = build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=1, codepage=1252)
    assert data[28:44] == b"de-DE".ljust(16, b"\x00")


def test_a_truncated_pack_is_refused():
    with pytest.raises(EmitError, match="at least 44 bytes"):
        read_pack(b"V4LG")


def test_the_wrong_magic_is_refused():
    data = bytearray(build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=1, codepage=1252))
    data[:4] = b"XXXX"
    with pytest.raises(EmitError, match="not a language pack"):
        read_pack(bytes(data))


def test_a_newer_format_is_refused():
    data = bytearray(build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=1, codepage=1252))
    struct.pack_into("<H", data, 4, FORMAT_VERSION + 1)
    with pytest.raises(EmitError, match="this build reads"):
        read_pack(bytes(data))


def test_a_damaged_payload_is_caught_by_the_checksum():
    data = bytearray(build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=1, codepage=1252))
    data[-4] ^= 0xFF
    with pytest.raises(EmitError, match="checksum does not match"):
        read_pack(bytes(data))


def test_a_truncated_body_is_caught_before_the_checksum():
    data = build_pack(STRINGS, SYMBOLS, tag="de-DE", lcid=1, codepage=1252)
    with pytest.raises(EmitError, match="bytes of body"):
        read_pack(data[:-2])


def test_the_header_is_the_size_it_says():
    data = build_pack([], [], tag="de-DE", lcid=1, codepage=1252)
    assert len(data) == HEADER_SIZE


def test_emitting_from_a_catalog(tmp_path, catalog, translations):
    path = tmp_path / "packs" / "de-DE.v4l"
    result = V4lEmitter().emit(
        catalog, translations, EmitOptions(path=path, locale=resolve("de-DE"))
    )
    assert path.exists()
    assert result.written == 5
    assert result.fell_back

    pack = read_pack(path.read_bytes())
    assert pack.tag == "de-DE"
    assert pack.strings[0] == "Druck gestartet"
    assert pack.strings[2] == "Bereinigungseinstellungen"


def test_slot_order_follows_the_enum_not_the_key_order(tmp_path, catalog, translations):
    path = tmp_path / "de-DE.v4l"
    V4lEmitter().emit(catalog, translations,
                      EmitOptions(path=path, locale=resolve("de-DE")))
    pack = read_pack(path.read_bytes())
    # LNG_PRINT_STARTED, LNG_PRINT_STOPPED, LNG_PURGE_SETTINGS in that order,
    # which is the enum order and not alphabetical by key.
    assert pack.strings[:3] == [
        "Druck gestartet", "Druck gestoppt", "Bereinigungseinstellungen",
    ]


def test_untranslated_slots_fall_back_to_english(tmp_path, catalog, translations):
    path = tmp_path / "de-DE.v4l"
    V4lEmitter().emit(catalog, translations,
                      EmitOptions(path=path, locale=resolve("de-DE")))
    assert "Spacing" in read_pack(path.read_bytes()).strings


def test_fallback_off_leaves_them_empty(tmp_path, catalog, translations):
    path = tmp_path / "de-DE.v4l"
    V4lEmitter().emit(
        catalog, translations,
        EmitOptions(path=path, locale=resolve("de-DE"), fallback_to_source=False),
    )
    strings = read_pack(path.read_bytes()).strings
    assert "" in strings
    assert "Spacing" not in strings


def test_the_signature_of_an_emitted_pack_matches_the_header_ids(tmp_path, catalog,
                                                                 translations):
    path = tmp_path / "de-DE.v4l"
    V4lEmitter().emit(catalog, translations,
                      EmitOptions(path=path, locale=resolve("de-DE")))
    expected = table_signature([
        "LNG_PRINT_STARTED", "LNG_PRINT_STOPPED", "LNG_PURGE_SETTINGS",
        "LNG_FIRING_VOLTAGE", "LNG_PEN", "LNG_SPACING", "LNG_UNITS_MM",
        "LNG_LOW_INK", "LNG_CONFIRM_PURGE",
    ])
    assert read_pack(path.read_bytes()).signature == expected


def test_a_utf16_pack_can_be_asked_for(tmp_path, catalog):
    entries = TranslationSet(locale="zh-TW")
    entries.set(message_key("Print started"),
                Translation(text="列印已開始", state=TranslationState.APPROVED))
    path = tmp_path / "zh-TW.v4l"
    V4lEmitter().emit(
        catalog, entries,
        EmitOptions(path=path, locale=resolve("zh-TW"), encoding="utf-16"),
    )
    pack = read_pack(path.read_bytes())
    assert pack.is_utf16
    assert pack.strings[0] == "列印已開始"


def test_a_catalog_with_no_such_table(tmp_path, translations):
    with pytest.raises(EmitError, match="no slot order"):
        V4lEmitter().emit(
            Catalog(project="X"), translations,
            EmitOptions(path=tmp_path / "x.v4l", locale=resolve("de-DE")),
        )


def test_the_container_can_be_overridden():
    assert V4lEmitter("lng_base").container == "lng_base"
