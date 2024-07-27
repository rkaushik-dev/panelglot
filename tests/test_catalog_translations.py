from datetime import date

from v4t_translate.catalog.ids import source_fingerprint
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)

APPROVED = TranslationState.APPROVED
DRAFT = TranslationState.DRAFT
EMPTY = TranslationState.EMPTY
NEEDS_REVIEW = TranslationState.NEEDS_REVIEW
DNT = TranslationState.DO_NOT_TRANSLATE


def test_state_values_are_the_on_disk_names():
    assert DNT.value == "do-not-translate"
    assert str(NEEDS_REVIEW) == "needs-review"


def test_only_approved_and_dnt_ship():
    shippable = {s for s in TranslationState if s.is_shippable}
    assert shippable == {APPROVED, DNT}


def test_the_other_three_need_a_human():
    assert {s for s in TranslationState if s.needs_a_human} == {EMPTY, DRAFT, NEEDS_REVIEW}


def test_a_fresh_translation_is_empty():
    translation = Translation()
    assert translation.text == ""
    assert translation.state is EMPTY


def test_stale_when_the_english_moved():
    translation = Translation(
        text="Zündspannung",
        state=APPROVED,
        fingerprint=source_fingerprint("Firing Voltage"),
    )
    assert not translation.is_stale_against("Firing Voltage")
    assert translation.is_stale_against("Firing voltage")


def test_an_empty_translation_is_never_stale():
    assert not Translation().is_stale_against("anything")


def test_a_translation_without_a_fingerprint_is_not_called_stale():
    # Hand-written catalog entries look like this and we do not want to
    # flood the report with them.
    translation = Translation(text="Zündspannung", state=APPROVED)
    assert not translation.is_stale_against("Firing Voltage")


def test_with_text_refingerprints_and_dates():
    before = Translation(text="old", state=APPROVED, fingerprint="deadbeef")
    after = before.with_text(
        "Druckabstand", source_text="Print Spacing", state=APPROVED,
        origin="workbook", today=date(2024, 8, 1),
    )
    assert after.text == "Druckabstand"
    assert after.fingerprint == source_fingerprint("Print Spacing")
    assert after.updated == "2024-08-01"
    assert after.origin == "workbook"
    assert not after.is_stale_against("Print Spacing")


def test_with_text_keeps_the_existing_note_when_none_is_given():
    before = Translation(text="a", note="ask the customer")
    after = before.with_text("b", source_text="B", state=DRAFT, today=date(2024, 8, 1))
    assert after.note == "ask the customer"


def test_with_text_can_clear_a_note_by_passing_an_empty_string():
    before = Translation(text="a", note="ask the customer")
    after = before.with_text("b", source_text="B", state=DRAFT, note="",
                             today=date(2024, 8, 1))
    assert after.note == ""


def test_with_text_keeps_the_origin_when_none_is_given():
    before = Translation(text="a", origin="memory")
    after = before.with_text("b", source_text="B", state=DRAFT, today=date(2024, 8, 1))
    assert after.origin == "memory"


def test_marked_changes_state_and_date_only():
    before = Translation(text="Stift", state=APPROVED, fingerprint="abc", origin="workbook")
    after = before.marked(NEEDS_REVIEW, today=date(2024, 9, 2))
    assert after.state is NEEDS_REVIEW
    assert after.text == "Stift"
    assert after.fingerprint == "abc"
    assert after.origin == "workbook"
    assert after.updated == "2024-09-02"


def full_set():
    entries = TranslationSet(locale="de-DE")
    entries.set("a.1", Translation(text="Eins", state=APPROVED))
    entries.set("b.2", Translation(text="Zwei", state=DRAFT))
    entries.set("c.3", Translation(state=EMPTY))
    entries.set("d.4", Translation(text="mm", state=DNT))
    return entries


def test_get_returns_an_empty_translation_for_a_missing_key():
    assert full_set().get("nope").state is EMPTY


def test_contains_and_len():
    entries = full_set()
    assert len(entries) == 4
    assert "a.1" in entries
    assert "zz" not in entries


def test_remove_reports_whether_anything_went():
    entries = full_set()
    assert entries.remove("a.1")
    assert not entries.remove("a.1")


def test_keys_in_state_is_sorted():
    entries = full_set()
    entries.set("a.0", Translation(text="Null", state=APPROVED))
    assert entries.keys_in_state(APPROVED) == ["a.0", "a.1"]


def test_keys_in_several_states():
    assert full_set().keys_in_state(DRAFT, EMPTY) == ["b.2", "c.3"]


def test_counts_include_states_with_nothing_in_them():
    counts = full_set().counts()
    assert counts["approved"] == 1
    assert counts["needs-review"] == 0
    assert set(counts) == {s.value for s in TranslationState}


def test_restrict_to_drops_and_reports_orphans():
    entries = full_set()
    gone = entries.restrict_to({"a.1", "b.2"})
    assert gone == ["c.3", "d.4"]
    assert set(entries.entries) == {"a.1", "b.2"}


def test_restrict_to_nothing_removes_everything():
    entries = full_set()
    assert len(entries.restrict_to(set())) == 4
    assert len(entries) == 0
