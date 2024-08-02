import json

import pytest

from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import (
    FORMAT_VERSION,
    Catalog,
    load_catalog,
    load_translations,
    save_catalog,
    save_translations,
)
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.errors import CatalogError


def origin(container="IDD_BARCODE", symbol="IDC_STATIC", line=26, ordinal=0):
    return Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL, container=container,
                  symbol=symbol, line=line, ordinal=ordinal)


def sample_catalog():
    catalog = Catalog(project="V4T-TIJ")
    catalog.add(Message(key="bar-height.aaa111", source_text="Bar Height",
                        origins=[origin()], max_width_px=54))
    catalog.add(Message(key="ok.bbb222", source_text="OK",
                        origins=[origin(container="IDD_A", symbol="IDOK")],
                        max_width_px=42, max_lines=1))
    catalog.add(Message(key="mm.ccc333", source_text="mm", protected=True,
                        origins=[origin(container="STRINGTABLE", symbol="IDS_UNITS_MM")]))
    catalog.add(Message(key="print.ddd444", source_text="Print", context="verb",
                        developer_note="Menu command.",
                        origins=[origin(container="IDR_MAIN", symbol="ID_PRINT")]))
    return catalog


def test_round_trip(tmp_path):
    path = tmp_path / "catalog" / "v4t-tij.json"
    save_catalog(path, sample_catalog())
    loaded = load_catalog(path)

    assert loaded.project == "V4T-TIJ"
    assert loaded.source_locale == "en-US"
    assert len(loaded) == 4
    assert loaded.get("bar-height.aaa111").source_text == "Bar Height"
    assert loaded.get("bar-height.aaa111").max_width_px == 54
    assert loaded.get("mm.ccc333").protected
    assert loaded.get("print.ddd444").context == "verb"
    assert loaded.get("print.ddd444").developer_note == "Menu command."


def test_origins_survive_the_round_trip(tmp_path):
    path = tmp_path / "c.json"
    save_catalog(path, sample_catalog())
    loaded = load_catalog(path)
    origins = loaded.get("bar-height.aaa111").origins
    assert origins == [origin()]


def test_parent_directories_are_created(tmp_path):
    path = tmp_path / "deep" / "deeper" / "c.json"
    save_catalog(path, sample_catalog())
    assert path.exists()


def test_the_file_is_utf8_and_not_escaped(tmp_path):
    catalog = Catalog(project="V4T-TIJ")
    catalog.add(Message(key="x.1", source_text="Auflösung", origins=[origin()]))
    path = tmp_path / "c.json"
    save_catalog(path, catalog)
    assert "Auflösung" in path.read_text(encoding="utf-8")


def test_the_file_ends_with_one_newline(tmp_path):
    path = tmp_path / "c.json"
    save_catalog(path, sample_catalog())
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert not text.endswith("\n\n")


def test_saving_twice_produces_identical_bytes(tmp_path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    save_catalog(first, sample_catalog())
    save_catalog(second, sample_catalog())
    assert first.read_bytes() == second.read_bytes()


def test_messages_are_written_in_key_order(tmp_path):
    path = tmp_path / "c.json"
    save_catalog(path, sample_catalog())
    payload = json.loads(path.read_text(encoding="utf-8"))
    keys = [m["key"] for m in payload["messages"]]
    assert keys == sorted(keys)


def test_defaults_are_not_written_out(tmp_path):
    path = tmp_path / "c.json"
    save_catalog(path, sample_catalog())
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_key = {m["key"]: m for m in payload["messages"]}
    assert "protected" not in by_key["bar-height.aaa111"]
    assert "max_lines" not in by_key["ok.bbb222"]
    assert "context" not in by_key["ok.bbb222"]


def test_no_temporary_files_are_left_behind(tmp_path):
    path = tmp_path / "c.json"
    save_catalog(path, sample_catalog())
    assert [p.name for p in tmp_path.iterdir()] == ["c.json"]


def test_a_missing_catalog_is_an_error(tmp_path):
    with pytest.raises(CatalogError, match="does not exist"):
        load_catalog(tmp_path / "nope.json")


def test_broken_json_is_reported_with_the_path(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError, match="not valid JSON"):
        load_catalog(path)


def test_a_json_array_is_rejected(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(CatalogError, match="does not contain a JSON object"):
        load_catalog(path)


def test_a_newer_format_is_refused(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"format": FORMAT_VERSION + 1, "messages": []}), encoding="utf-8")
    with pytest.raises(CatalogError, match="only reads up to"):
        load_catalog(path)


def test_messages_must_be_a_list(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"format": 1, "messages": {}}), encoding="utf-8")
    with pytest.raises(CatalogError, match="not a list"):
        load_catalog(path)


def test_a_message_without_a_key_is_reported(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"format": 1, "messages": [{"text": "x"}]}), encoding="utf-8")
    with pytest.raises(CatalogError, match="needs a string 'key' and 'text'"):
        load_catalog(path)


def test_a_duplicate_key_is_reported(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps({"format": 1, "messages": [{"key": "a.1", "text": "x"},
                                              {"key": "a.1", "text": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="duplicate message key"):
        load_catalog(path)


def test_an_unknown_origin_kind_is_reported(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps({"format": 1, "messages": [
            {"key": "a.1", "text": "x", "origins": [{"kind": "smoke-signal"}]}
        ]}),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="unknown origin kind"):
        load_catalog(path)


def sample_translations():
    entries = TranslationSet(locale="de-DE")
    entries.set("bar-height.aaa111", Translation(
        text="Balkenhöhe", state=TranslationState.APPROVED,
        fingerprint="0011223344556677", updated="2024-07-01", origin="workbook",
    ))
    entries.set("ok.bbb222", Translation(text="OK", state=TranslationState.APPROVED))
    entries.set("mm.ccc333", Translation(text="mm", state=TranslationState.DO_NOT_TRANSLATE))
    entries.set("print.ddd444", Translation(state=TranslationState.EMPTY,
                                            note="which sense?"))
    return entries


def test_translations_round_trip(tmp_path):
    path = tmp_path / "de-DE.json"
    save_translations(path, sample_translations())
    loaded = load_translations(path)

    assert loaded.locale == "de-DE"
    assert len(loaded) == 4
    assert loaded.get("bar-height.aaa111").text == "Balkenhöhe"
    assert loaded.get("bar-height.aaa111").state is TranslationState.APPROVED
    assert loaded.get("bar-height.aaa111").origin == "workbook"
    assert loaded.get("print.ddd444").note == "which sense?"


def test_a_missing_translation_file_is_empty_not_an_error(tmp_path):
    loaded = load_translations(tmp_path / "fr-FR.json")
    assert len(loaded) == 0
    assert loaded.locale == "fr-FR"


def test_translation_entries_are_written_in_key_order(tmp_path):
    path = tmp_path / "de-DE.json"
    save_translations(path, sample_translations())
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload["entries"]) == sorted(payload["entries"])


def test_an_unknown_state_is_reported(tmp_path):
    path = tmp_path / "de-DE.json"
    path.write_text(
        json.dumps({"format": 1, "locale": "de-DE",
                    "entries": {"a.1": {"text": "x", "state": "probably"}}}),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="unknown state"):
        load_translations(path)


def test_entries_must_be_an_object(tmp_path):
    path = tmp_path / "de-DE.json"
    path.write_text(json.dumps({"format": 1, "entries": []}), encoding="utf-8")
    with pytest.raises(CatalogError, match="not an object"):
        load_translations(path)


def test_catalog_helpers():
    catalog = sample_catalog()
    assert "ok.bbb222" in catalog
    assert catalog.get("nope") is None
    assert catalog.texts()["mm.ccc333"] == "mm"
    assert catalog.sorted_keys()[0] == "bar-height.aaa111"


def test_adding_the_same_key_twice_merges():
    catalog = Catalog(project="X")
    catalog.add(Message(key="ok.1", source_text="OK", origins=[origin(container="IDD_A")]))
    catalog.add(Message(key="ok.1", source_text="OK", origins=[origin(container="IDD_B")]))
    assert len(catalog) == 1
    assert len(catalog.get("ok.1").origins) == 2
