import json

import pytest

from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import (
    FORMAT_VERSION,
    OLDEST_READABLE,
    TRANSLATIONS_VERSION,
    Catalog,
    SourceTable,
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


def origin(source, line=10, container="IDD_MAIN"):
    return Origin(source=source, kind=OriginKind.DIALOG_CONTROL,
                  container=container, symbol="IDC_STATIC", line=line)


def catalog_of(*pairs):
    catalog = Catalog(project="V4T-TIJ")
    for key, text, sources in pairs:
        catalog.add(Message(key=key, source_text=text,
                            origins=[origin(s) for s in sources]))
    return catalog


def roundtrip(tmp_path, catalog):
    path = tmp_path / "catalog.json"
    save_catalog(path, catalog)
    return load_catalog(path), json.loads(path.read_text(encoding="utf-8"))


V1 = {
    "format": 1,
    "project": "V4T-TIJ",
    "source_locale": "en-US",
    "messages": [
        {
            "key": "bar-height.9f2c1a",
            "text": "Bar Height",
            "origins": [
                {
                    "source": "src/V4T.rc",
                    "kind": "dialog-control",
                    "container": "IDD_BARCODE_PROPS",
                    "symbol": "IDC_STATIC",
                    "line": 41,
                }
            ],
        }
    ],
}


def write(tmp_path, payload, name="catalog.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# -- the source table ---------------------------------------------------


def test_a_path_gets_an_index():
    table = SourceTable()
    assert table.index_of("a.rc") == 0
    assert table.index_of("b.rc") == 1


def test_the_same_path_gets_the_same_index():
    table = SourceTable()
    assert table.index_of("a.rc") == table.index_of("a.rc")
    assert len(table) == 1


def test_indices_are_first_seen_not_sorted():
    table = SourceTable()
    table.index_of("z.rc")
    table.index_of("a.rc")
    assert table.paths == ["z.rc", "a.rc"]


def test_a_path_comes_back():
    table = SourceTable(["a.rc", "b.rc"])
    assert table.path_at(1) == "b.rc"


def test_an_index_past_the_end_is_refused():
    with pytest.raises(CatalogError, match="refers to source 4"):
        SourceTable(["a.rc"]).path_at(4)


def test_a_negative_index_is_refused():
    with pytest.raises(CatalogError):
        SourceTable(["a.rc"]).path_at(-1)


# -- writing format 2 ---------------------------------------------------


def test_the_version_is_written(tmp_path):
    _, payload = roundtrip(tmp_path, catalog_of(("a.1", "A", ["src/V4T.rc"])))
    assert payload["format"] == FORMAT_VERSION == 2


def test_the_table_is_written(tmp_path):
    _, payload = roundtrip(tmp_path, catalog_of(
        ("a.1", "A", ["src/V4T.rc"]), ("a.2", "B", ["src/other.rc"])))
    assert payload["sources"] == ["src/V4T.rc", "src/other.rc"]


def test_a_repeated_path_is_listed_once(tmp_path):
    _, payload = roundtrip(tmp_path, catalog_of(
        ("a.1", "A", ["src/V4T.rc"]), ("a.2", "B", ["src/V4T.rc"])))
    assert payload["sources"] == ["src/V4T.rc"]


def test_an_origin_carries_an_index_not_a_path(tmp_path):
    _, payload = roundtrip(tmp_path, catalog_of(("a.1", "A", ["src/V4T.rc"])))
    written = payload["messages"][0]["origins"][0]
    assert written["src"] == 0
    assert "source" not in written


def test_an_empty_catalog_still_has_a_table(tmp_path):
    _, payload = roundtrip(tmp_path, Catalog(project="p"))
    assert payload["sources"] == []


def test_the_path_survives_the_round_trip(tmp_path):
    reread, _ = roundtrip(tmp_path, catalog_of(("a.1", "A", ["src/V4T.rc"])))
    assert reread.messages["a.1"].origins[0].source == "src/V4T.rc"


def test_two_files_survive(tmp_path):
    reread, _ = roundtrip(tmp_path, catalog_of(
        ("a.1", "A", ["src/V4T.rc"]), ("a.2", "B", ["src/other.rc"])))
    assert reread.messages["a.2"].origins[0].source == "src/other.rc"


def test_one_message_from_two_files(tmp_path):
    reread, _ = roundtrip(tmp_path, catalog_of(
        ("a.1", "A", ["src/V4T.rc", "src/other.rc"])))
    assert [o.source for o in reread.messages["a.1"].origins] == [
        "src/V4T.rc", "src/other.rc"
    ]


def test_writing_twice_gives_the_same_bytes(tmp_path):
    catalog = catalog_of(("a.1", "A", ["src/V4T.rc"]), ("a.2", "B", ["src/b.rc"]))
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    save_catalog(first, catalog)
    save_catalog(second, catalog)
    assert first.read_bytes() == second.read_bytes()


def test_the_file_is_smaller_than_the_old_form(tmp_path):
    catalog = catalog_of(*[
        (f"a.{n}", f"Message {n}", ["src/ui/dialogs/V4T.rc"]) for n in range(50)
    ])
    path = tmp_path / "catalog.json"
    save_catalog(path, catalog)

    payload = json.loads(path.read_text(encoding="utf-8"))
    for message in payload["messages"]:
        for entry in message["origins"]:
            entry["source"] = "src/ui/dialogs/V4T.rc"
            del entry["src"]
    del payload["sources"]

    assert path.stat().st_size < len(json.dumps(payload, indent=2))


# -- reading format 1 ---------------------------------------------------


def test_a_format_1_catalog_still_loads(tmp_path):
    catalog = load_catalog(write(tmp_path, V1))
    assert catalog.messages["bar-height.9f2c1a"].source_text == "Bar Height"


def test_its_origin_path_comes_through(tmp_path):
    catalog = load_catalog(write(tmp_path, V1))
    assert catalog.messages["bar-height.9f2c1a"].origins[0].source == "src/V4T.rc"


def test_saving_a_loaded_format_1_catalog_writes_format_2(tmp_path):
    catalog = load_catalog(write(tmp_path, V1))
    out = tmp_path / "again.json"
    save_catalog(out, catalog)
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == 2


def test_an_inline_source_wins_over_an_index(tmp_path):
    payload = json.loads(json.dumps(V1))
    payload["format"] = 2
    payload["sources"] = ["wrong.rc"]
    payload["messages"][0]["origins"][0]["src"] = 0

    catalog = load_catalog(write(tmp_path, payload))
    assert catalog.messages["bar-height.9f2c1a"].origins[0].source == "src/V4T.rc"


def test_an_index_with_no_table_is_refused(tmp_path):
    payload = json.loads(json.dumps(V1))
    del payload["messages"][0]["origins"][0]["source"]
    payload["messages"][0]["origins"][0]["src"] = 0

    with pytest.raises(CatalogError, match="no source table"):
        load_catalog(write(tmp_path, payload))


def test_a_table_that_is_not_a_list_is_refused(tmp_path):
    payload = json.loads(json.dumps(V1))
    payload["sources"] = {"0": "src/V4T.rc"}
    with pytest.raises(CatalogError, match="not a list of paths"):
        load_catalog(write(tmp_path, payload))


def test_a_table_holding_numbers_is_refused(tmp_path):
    payload = json.loads(json.dumps(V1))
    payload["sources"] = [3]
    with pytest.raises(CatalogError, match="not a list of paths"):
        load_catalog(write(tmp_path, payload))


def test_a_non_numeric_index_is_refused(tmp_path):
    payload = {
        "format": 2, "project": "p", "source_locale": "en-US",
        "sources": ["a.rc"],
        "messages": [{"key": "a.1", "text": "A",
                      "origins": [{"src": "a.rc", "kind": "dialog-control"}]}],
    }
    with pytest.raises(CatalogError, match="non-numeric source index"):
        load_catalog(write(tmp_path, payload))


def test_an_origin_with_neither_is_empty(tmp_path):
    payload = {
        "format": 2, "project": "p", "source_locale": "en-US",
        "sources": [],
        "messages": [{"key": "a.1", "text": "A",
                      "origins": [{"kind": "dialog-control"}]}],
    }
    assert load_catalog(write(tmp_path, payload)).messages["a.1"].origins[0].source == ""


# -- version bounds -----------------------------------------------------


def test_a_future_catalog_is_refused(tmp_path):
    payload = dict(V1, format=FORMAT_VERSION + 1)
    with pytest.raises(CatalogError, match="only reads up to 2"):
        load_catalog(write(tmp_path, payload))


def test_a_format_too_old_is_refused(tmp_path):
    # Nothing is that old yet, so this is checking the guard rather than a
    # real file. It exists because the day one is dropped the message has to
    # say so instead of failing on a missing key.
    payload = dict(V1, format=OLDEST_READABLE - 1)
    if OLDEST_READABLE > 1:
        with pytest.raises(CatalogError, match="no longer reads"):
            load_catalog(write(tmp_path, payload))


def test_the_translation_files_did_not_move(tmp_path):
    translations = TranslationSet(locale="de-DE")
    translations.set("a.1", Translation(text="A", state=TranslationState.APPROVED))
    path = tmp_path / "de-DE.json"
    save_translations(path, translations)

    assert json.loads(path.read_text(encoding="utf-8"))["format"] == 1
    assert TRANSLATIONS_VERSION == 1


def test_a_translation_file_from_the_future_is_refused(tmp_path):
    path = tmp_path / "de-DE.json"
    path.write_text(json.dumps({"format": 2, "locale": "de-DE", "entries": {}}),
                    encoding="utf-8")
    with pytest.raises(CatalogError, match="only reads up to 1"):
        load_translations(path)


def test_a_current_translation_file_reads(tmp_path):
    path = tmp_path / "de-DE.json"
    path.write_text(
        json.dumps({"format": 1, "locale": "de-DE",
                    "entries": {"a.1": {"text": "A", "state": "approved"}}}),
        encoding="utf-8",
    )
    assert load_translations(path).get("a.1").text == "A"


# -- the cache is unaffected --------------------------------------------


def test_the_cache_still_writes_paths_inline(tmp_path):
    from v4t_translate.catalog.cache import ExtractionCache

    cache = ExtractionCache()
    cache.store("src/V4T.rc", "abc",
                [Message(key="a.1", source_text="A", origins=[origin("src/V4T.rc")])],
                [], {})

    path = tmp_path / "cache.json"
    cache.save(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    written = payload["sources"]["src/V4T.rc"]["messages"][0]["origins"][0]
    assert written["source"] == "src/V4T.rc"
    assert "src" not in written


def test_the_cache_round_trips(tmp_path):
    from v4t_translate.catalog.cache import ExtractionCache

    cache = ExtractionCache()
    cache.store("src/V4T.rc", "abc",
                [Message(key="a.1", source_text="A", origins=[origin("src/V4T.rc")])],
                [], {})
    path = tmp_path / "cache.json"
    cache.save(path)

    reread = ExtractionCache.load(path)
    entry = reread.lookup("src/V4T.rc", "abc")
    assert entry.messages[0].origins[0].source == "src/V4T.rc"
