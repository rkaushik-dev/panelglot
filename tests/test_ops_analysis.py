
from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.locales import resolve
from v4t_translate.ops.analysis import (
    analyse,
    identical_to_source,
    merged_targets,
    mnemonic_collisions,
)

DE = resolve("de-DE")


def origin(container, kind=OriginKind.DIALOG_CONTROL, symbol="IDC_X"):
    return Origin(source="V4T.rc", kind=kind, container=container, symbol=symbol)


def build(entries):
    """entries: {source: (translation, container, kind, protected)}"""
    catalog = Catalog(project="V4T-TIJ")
    translations = TranslationSet(locale="de-DE")

    for source, spec in entries.items():
        target = spec[0]
        container = spec[1] if len(spec) > 1 else "IDD_MAIN"
        kind = spec[2] if len(spec) > 2 else OriginKind.DIALOG_CONTROL
        protected = spec[3] if len(spec) > 3 else False

        key = message_key(source)
        catalog.add(Message(key=key, source_text=source, protected=protected,
                            origins=[origin(container, kind)]))
        if target is not None:
            translations.set(key, Translation(text=target,
                                              state=TranslationState.APPROVED))
    return catalog, translations


def test_no_collision_when_mnemonics_differ():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": ("&Abbrechen",),
    })
    assert mnemonic_collisions(catalog, translations) == []


def test_a_collision_on_one_dialog():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": ("&Durchsuchen",),
    })
    collisions = mnemonic_collisions(catalog, translations)
    assert len(collisions) == 1
    assert collisions[0].mnemonic == "D"
    assert collisions[0].container == "IDD_MAIN"
    assert len(collisions[0].keys) == 2


def test_the_collision_describes_itself():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": ("&Durchsuchen",),
    })
    text = mnemonic_collisions(catalog, translations)[0].describe()
    assert "Alt+D" in text
    assert "Drucken" in text


def test_no_collision_across_different_dialogs():
    catalog, translations = build({
        "&Print": ("&Drucken", "IDD_A"),
        "&Cancel": ("&Durchsuchen", "IDD_B"),
    })
    assert mnemonic_collisions(catalog, translations) == []


def test_the_mnemonic_match_is_case_insensitive():
    catalog, translations = build({
        "&Print": ("&drucken",),
        "&Cancel": ("&Durchsuchen",),
    })
    assert len(mnemonic_collisions(catalog, translations)) == 1


def test_an_untranslated_control_cannot_collide():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": (None,),
    })
    assert mnemonic_collisions(catalog, translations) == []


def test_a_string_table_entry_is_not_bound_to_anything():
    catalog, translations = build({
        "&Print": ("&Drucken", "IDD_MAIN"),
        "Use && then &Delete": ("&Durchsuchen", "STRINGTABLE",
                                OriginKind.STRING_TABLE),
    })
    assert mnemonic_collisions(catalog, translations) == []


def test_menu_items_collide_within_their_menu():
    catalog, translations = build({
        "&New": ("&Neu", "IDR_MAIN", OriginKind.MENU_ITEM),
        "&Open": ("&Neu laden", "IDR_MAIN", OriginKind.MENU_ITEM),
    })
    assert len(mnemonic_collisions(catalog, translations)) == 1


def test_an_escaped_ampersand_is_not_a_mnemonic():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "Date&&Time": ("Datum&&Zeit",),
    })
    assert mnemonic_collisions(catalog, translations) == []


def test_three_controls_claiming_one_key():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": ("&Durchsuchen",),
        "&Close": ("&Dann",),
    })
    collisions = mnemonic_collisions(catalog, translations)
    assert len(collisions) == 1
    assert len(collisions[0].keys) == 3


def test_no_merge_when_translations_differ():
    catalog, translations = build({
        "Print": ("Drucken",),
        "Printing": ("Druckvorgang",),
    })
    assert merged_targets(catalog, translations) == []


def test_two_english_strings_with_one_translation():
    catalog, translations = build({
        "Print": ("Drucken",),
        "Printout": ("Drucken",),
    })
    merged = merged_targets(catalog, translations)
    assert len(merged) == 1
    assert merged[0].target == "Drucken"
    assert merged[0].sources == ("Print", "Printout")


def test_the_merge_describes_itself():
    catalog, translations = build({
        "Print": ("Drucken",),
        "Printout": ("Drucken",),
    })
    text = merged_targets(catalog, translations)[0].describe()
    assert "all translate to 'Drucken'" in text


def test_an_untranslated_string_cannot_merge():
    catalog, translations = build({"Print": ("Drucken",), "Printout": (None,)})
    assert merged_targets(catalog, translations) == []


def test_a_translation_identical_to_its_source_is_reported():
    catalog, translations = build({"Bearer thickness": ("Bearer thickness",)})
    assert identical_to_source(catalog, translations) == [
        message_key("Bearer thickness")
    ]


def test_a_protected_string_is_not_reported():
    catalog, translations = build({"mm": ("mm", "IDD_MAIN",
                                          OriginKind.STRING_TABLE, True)})
    assert identical_to_source(catalog, translations) == []


def test_words_that_genuinely_do_not_change_are_not_reported():
    catalog, translations = build({
        "OK": ("OK",),
        "Barcode": ("Barcode",),
        "Normal": ("Normal",),
    })
    assert identical_to_source(catalog, translations) == []


def test_the_unchanged_check_ignores_case_and_spacing():
    catalog, translations = build({"  ok  ": ("  ok  ",)})
    assert identical_to_source(catalog, translations) == []


def test_a_real_translation_is_not_reported():
    catalog, translations = build({"Bearer thickness": ("Stegdicke",)})
    assert identical_to_source(catalog, translations) == []


def test_analyse_runs_everything():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": ("&Durchsuchen",),
        "Printout": ("&Drucken",),
        "Bearer thickness": ("Bearer thickness",),
    })
    result = analyse(catalog, translations, DE)
    assert result
    assert result.collisions
    assert result.merged
    assert result.unchanged
    assert result.checked == 4


def test_a_clean_language_analyses_to_nothing():
    catalog, translations = build({
        "&Print": ("&Drucken",),
        "&Cancel": ("&Abbrechen",),
    })
    result = analyse(catalog, translations, DE)
    assert not result
    assert "0 mnemonic collisions" in result.summary()


def test_the_summary_reads():
    catalog, translations = build({"&Print": ("&Drucken",)})
    assert analyse(catalog, translations, DE).summary().startswith("de-DE: 1 translated")
