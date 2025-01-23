import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Message
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.mt.memory import EXACT, TranslationMemory

GERMAN = {
    "Print started": "Druck gestartet",
    "Print stopped": "Druck gestoppt",
    "Purge Settings": "Bereinigungseinstellungen",
    "Firing Voltage": "Zündspannung",
    "Purge offset must be less than group offset":
        "Der Purge-Versatz muss kleiner als der Gruppenversatz sein",
    "Parameter cannot be changed when printing":
        "Parameter können beim Drucken nicht geändert werden",
}


@pytest.fixture
def memory():
    with TranslationMemory() as memory:
        for source, target in GERMAN.items():
            memory.remember("de-DE", source, target, origin="workbook")
        yield memory


def test_an_empty_memory():
    with TranslationMemory() as memory:
        assert len(memory) == 0
        assert memory.locales() == []
        assert memory.recall("de-DE", "anything") is None


def test_remember_and_recall(memory):
    match = memory.recall("de-DE", "Print started")
    assert match.target == "Druck gestartet"
    assert match.score == EXACT
    assert match.is_exact
    assert match.origin == "workbook"


def test_recall_is_locale_specific(memory):
    assert memory.recall("zh-TW", "Print started") is None


def test_recall_normalises_line_endings(memory):
    memory.remember("de-DE", "one\r\ntwo", "eins\nzwei")
    assert memory.recall("de-DE", "one\ntwo").target == "eins\nzwei"


def test_remembering_again_replaces(memory):
    before = len(memory)
    memory.remember("de-DE", "Print started", "Druck läuft")
    assert len(memory) == before
    assert memory.recall("de-DE", "Print started").target == "Druck läuft"


def test_an_empty_source_or_target_is_not_remembered(memory):
    before = len(memory)
    memory.remember("de-DE", "", "leer")
    memory.remember("de-DE", "Something", "")
    assert len(memory) == before


def test_forget(memory):
    assert memory.forget("de-DE", "Print started")
    assert memory.recall("de-DE", "Print started") is None
    assert not memory.forget("de-DE", "Print started")


def test_counts_and_locales(memory):
    memory.remember("zh-TW", "Print started", "列印已開始")
    assert memory.locales() == ["de-DE", "zh-TW"]
    assert memory.counts()["zh-TW"] == 1


def test_clear_one_locale(memory):
    memory.remember("zh-TW", "Print started", "列印已開始")
    assert memory.clear("zh-TW") == 1
    assert memory.locales() == ["de-DE"]


def test_clear_everything(memory):
    memory.clear()
    assert len(memory) == 0


def test_a_close_match_is_suggested(memory):
    matches = memory.suggest("de-DE", "Purge offset must be less than pen offset")
    assert matches
    assert matches[0].target.startswith("Der Purge-Versatz")
    assert 0.75 <= matches[0].score < EXACT
    assert not matches[0].is_exact


def test_an_unrelated_string_suggests_nothing(memory):
    assert memory.suggest("de-DE", "Bearer thickness") == []


def test_a_much_shorter_string_is_not_a_match(memory):
    assert memory.suggest("de-DE", "Purge") == []


def test_suggestions_come_back_best_first(memory):
    memory.remember("de-DE", "Print started now", "Druck jetzt gestartet")
    matches = memory.suggest("de-DE", "Print started", threshold=0.5)
    assert matches[0].source == "Print started"
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_the_limit_is_honoured(memory):
    matches = memory.suggest("de-DE", "Print started", threshold=0.5, limit=1)
    assert len(matches) == 1


def test_the_threshold_is_honoured(memory):
    loose = memory.suggest("de-DE", "Print starts", threshold=0.5)
    strict = memory.suggest("de-DE", "Print starts", threshold=0.99)
    assert loose
    assert strict == []


def test_best_prefers_the_exact_match(memory):
    memory.remember("de-DE", "Print starte", "falsch")
    assert memory.best("de-DE", "Print started").target == "Druck gestartet"


def test_best_falls_back_to_fuzzy(memory):
    match = memory.best("de-DE", "Purge offset must be less than pen offset")
    assert match is not None
    assert not match.is_exact


def test_best_of_nothing(memory):
    assert memory.best("de-DE", "Bearer thickness") is None


def test_an_empty_query_suggests_nothing(memory):
    assert memory.suggest("de-DE", "") == []


def catalog_and_translations():
    catalog = Catalog(project="V4T-TIJ")
    entries = TranslationSet(locale="de-DE")
    for index, (source, target) in enumerate(GERMAN.items()):
        key = message_key(source)
        catalog.add(Message(key=key, source_text=source))
        state = TranslationState.APPROVED if index % 2 == 0 else TranslationState.DRAFT
        entries.set(key, Translation(text=target, state=state, updated="2025-01-20"))
    return catalog, entries


def test_absorb_takes_only_approved():
    catalog, entries = catalog_and_translations()
    with TranslationMemory() as memory:
        added = memory.absorb(catalog, entries)
        assert added == 3
        assert len(memory) == 3
        assert memory.recall("de-DE", "Print started") is not None
        assert memory.recall("de-DE", "Print stopped") is None


def test_absorb_can_be_told_to_take_drafts():
    catalog, entries = catalog_and_translations()
    with TranslationMemory() as memory:
        added = memory.absorb(
            catalog, entries,
            states=(TranslationState.APPROVED, TranslationState.DRAFT),
        )
        assert added == len(GERMAN)


def test_absorb_skips_a_translation_with_no_message():
    catalog, entries = catalog_and_translations()
    entries.set("orphan.000000", Translation(text="weg",
                                             state=TranslationState.APPROVED))
    with TranslationMemory() as memory:
        assert memory.absorb(catalog, entries) == 3


def test_absorb_carries_the_date():
    catalog, entries = catalog_and_translations()
    with TranslationMemory() as memory:
        memory.absorb(catalog, entries)
        assert memory.recall("de-DE", "Print started").origin == "catalog"


def test_a_memory_on_disk_persists(tmp_path):
    path = tmp_path / "catalog" / "memory.sqlite3"
    with TranslationMemory(path) as memory:
        memory.remember("de-DE", "Print started", "Druck gestartet")

    assert path.exists()
    with TranslationMemory(path) as reopened:
        assert reopened.recall("de-DE", "Print started").target == "Druck gestartet"


def test_the_parent_directory_is_created(tmp_path):
    path = tmp_path / "a" / "b" / "memory.sqlite3"
    TranslationMemory(path).close()
    assert path.exists()
