from v4t_translate.catalog.ids import message_key, source_fingerprint
from v4t_translate.catalog.merge import (
    MergeReport,
    carry_translations,
    merge_catalog,
)
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)


def origin(container="IDD_A", symbol="IDC_STATIC", line=1):
    return Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                  container=container, symbol=symbol, line=line)


def msg(text, **kw):
    kw.setdefault("origins", [origin()])
    return Message(key=message_key(text), source_text=text, **kw)


def catalog_of(*texts, **kw):
    catalog = Catalog(project="V4T-TIJ")
    for text in texts:
        catalog.add(msg(text, **kw))
    return catalog


def extracted_of(*messages):
    return {m.key: m for m in messages}


def test_a_merge_that_changes_nothing():
    existing = catalog_of("Bar Height", "Print Spacing")
    merged, report = merge_catalog(existing, extracted_of(*existing.messages.values()))
    assert report.is_noop()
    assert len(report.unchanged) == 2
    assert set(merged.messages) == set(existing.messages)


def test_new_strings_are_added():
    existing = catalog_of("Bar Height")
    merged, report = merge_catalog(existing, extracted_of(msg("Bar Height"), msg("Module size")))
    assert report.added == [message_key("Module size")]
    assert len(merged) == 2


def test_gone_strings_are_retired():
    existing = catalog_of("Bar Height", "Module size")
    merged, report = merge_catalog(existing, extracted_of(msg("Bar Height")))
    assert report.removed == [message_key("Module size")]
    assert message_key("Module size") not in merged


def test_a_moved_constraint_is_reported_as_updated():
    existing = catalog_of("Bar Height", max_width_px=54)
    merged, report = merge_catalog(
        existing, extracted_of(msg("Bar Height", max_width_px=40))
    )
    assert report.updated == [message_key("Bar Height")]
    assert merged.get(message_key("Bar Height")).max_width_px == 40


def test_a_moved_origin_is_reported_as_updated():
    existing = catalog_of("Bar Height")
    moved = msg("Bar Height", origins=[origin(container="IDD_B")])
    _, report = merge_catalog(existing, extracted_of(moved))
    assert report.updated == [message_key("Bar Height")]


def test_summary_reads_as_a_sentence():
    report = MergeReport(added=["a"], removed=["b"], unchanged=["c", "d"])
    assert report.summary() == "1 new, 1 retired, 0 reworded, 0 updated, 2 unchanged"


def test_a_rewording_is_paired():
    existing = catalog_of("Purge offset must be less than group offset")
    new = msg("Purge offset must be less than the group offset")
    _, report = merge_catalog(existing, extracted_of(new))
    assert report.rewordings == [
        (message_key("Purge offset must be less than group offset"), new.key)
    ]


def test_two_unrelated_strings_are_not_paired():
    existing = catalog_of("Horizontal Offset")
    new = msg("Simulated Speed")
    _, report = merge_catalog(existing, extracted_of(new))
    assert report.rewordings == []


def test_short_strings_are_never_paired():
    # "Pen" and "Pens" score above the threshold and are not the same string.
    existing = catalog_of("Pen")
    _, report = merge_catalog(existing, extracted_of(msg("Pens")))
    assert report.rewordings == []


def test_similar_but_distinct_domain_terms_stay_apart():
    existing = catalog_of("Print Offset")
    _, report = merge_catalog(existing, extracted_of(msg("Purge Offset")))
    assert report.rewordings == []


def test_each_retired_string_is_claimed_once():
    existing = catalog_of("This distance cannot be greater than print spacing")
    close = msg("This distance cannot be greater than the print spacing")
    closer = msg("This distance cannot be greater than print spacing.")
    _, report = merge_catalog(existing, extracted_of(close, closer))
    assert len(report.rewordings) == 1
    assert report.rewordings[0][1] == closer.key


def test_carry_moves_the_translation_to_the_new_key():
    old_text = "Purge offset must be less than group offset"
    new_text = "Purge offset must be less than the group offset"
    existing = catalog_of(old_text)
    merged, report = merge_catalog(existing, extracted_of(msg(new_text)))

    translations = TranslationSet(locale="de-DE")
    translations.set(message_key(old_text), Translation(
        text="Der Purge-Offset muss kleiner als der Gruppen-Offset sein",
        state=TranslationState.APPROVED,
        fingerprint=source_fingerprint(old_text),
        origin="workbook",
    ))

    carry_translations(translations, report, catalog=merged)

    carried = translations.get(message_key(new_text))
    assert carried.text.startswith("Der Purge-Offset")
    assert carried.state is TranslationState.NEEDS_REVIEW
    assert message_key(old_text) not in translations


def test_a_carried_entry_keeps_the_old_fingerprint_so_it_stays_flagged():
    old_text = "Please restart software for connecting MCR"
    new_text = "Please restart the software for connecting MCR"
    existing = catalog_of(old_text)
    merged, report = merge_catalog(existing, extracted_of(msg(new_text)))

    translations = TranslationSet(locale="de-DE")
    translations.set(message_key(old_text), Translation(
        text="Bitte starten Sie die Software neu",
        state=TranslationState.APPROVED,
        fingerprint=source_fingerprint(old_text),
    ))
    carry_translations(translations, report, catalog=merged)

    carried = translations.get(message_key(new_text))
    assert carried.is_stale_against(new_text)


def test_carry_does_not_overwrite_an_existing_answer():
    old_text = "Value must be between <V1> and <V2>"
    new_text = "Value must be between <V1> and <V2>."
    existing = catalog_of(old_text)
    merged, report = merge_catalog(existing, extracted_of(msg(new_text)))

    translations = TranslationSet(locale="de-DE")
    translations.set(message_key(old_text), Translation(text="alt", state=TranslationState.APPROVED))
    translations.set(message_key(new_text), Translation(text="neu", state=TranslationState.APPROVED))

    carry_translations(translations, report, catalog=merged)
    assert translations.get(message_key(new_text)).text == "neu"


def test_carry_skips_an_empty_source_translation():
    old_text = "Parameter cannot be changed when printing"
    new_text = "Parameter cannot be changed while printing"
    existing = catalog_of(old_text)
    merged, report = merge_catalog(existing, extracted_of(msg(new_text)))

    translations = TranslationSet(locale="de-DE")
    translations.set(message_key(old_text), Translation(state=TranslationState.EMPTY))
    carry_translations(translations, report, catalog=merged)
    assert message_key(new_text) not in translations


def test_an_approved_entry_whose_source_moved_is_sent_back_for_review():
    text = "Firing Voltage"
    catalog = catalog_of(text)
    translations = TranslationSet(locale="de-DE")
    translations.set(message_key(text), Translation(
        text="Zündspannung",
        state=TranslationState.APPROVED,
        fingerprint=source_fingerprint("Firing voltage"),
    ))

    carry_translations(translations, MergeReport(), catalog=catalog)
    assert translations.get(message_key(text)).state is TranslationState.NEEDS_REVIEW


def test_a_current_approved_entry_is_left_alone():
    text = "Firing Voltage"
    catalog = catalog_of(text)
    translations = TranslationSet(locale="de-DE")
    translations.set(message_key(text), Translation(
        text="Zündspannung",
        state=TranslationState.APPROVED,
        fingerprint=source_fingerprint(text),
    ))
    carry_translations(translations, MergeReport(), catalog=catalog)
    assert translations.get(message_key(text)).state is TranslationState.APPROVED


def test_orphan_translations_are_dropped():
    catalog = catalog_of("Bar Height")
    translations = TranslationSet(locale="de-DE")
    translations.set(message_key("Bar Height"), Translation(text="Balkenhöhe"))
    translations.set("gone.000000", Translation(text="weg"))
    carry_translations(translations, MergeReport(), catalog=catalog)
    assert set(translations.entries) == {message_key("Bar Height")}
