from pathlib import Path

import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.errors import ConfigError
from v4t_translate.glossary import Glossary, Term, load_glossary
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.glossary import GlossaryRule

CSV = """\
term,locale,translation,note
pen,de-DE,Stift,Never Feder.
printhead,de-DE,Druckkopf,
purge,zh-TW,清洗,
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "terms.csv"
    path.write_text(text, encoding="utf-8")
    return path


def context_for(tag="de-DE", terms=None):
    # Written as term to translation here because that is what these tests are
    # about. The context wants whole Terms, which carry the forbidden list and
    # the note as well.
    agreed = {
        key: Term(term=key, locale=tag, translation=value)
        for key, value in (terms or {}).items()
    }
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0x9FFF)]),
        glossary=agreed,
    )


def run(context, source, target):
    message = Message(key="k.1", source_text=source)
    translation = Translation(text=target, state=TranslationState.APPROVED)
    return list(GlossaryRule().check(message, translation, context))


def test_load(tmp_path):
    glossary = load_glossary(write(tmp_path, CSV))
    assert len(glossary) == 3
    assert glossary.locales() == ["de-DE", "zh-TW"]
    assert glossary.for_locale("de-DE")["pen"].translation == "Stift"
    assert glossary.for_locale("de-DE")["pen"].note == "Never Feder."


def test_terms_are_keyed_lowercase(tmp_path):
    glossary = load_glossary(write(tmp_path, "term,locale,translation\nPen,de-DE,Stift\n"))
    assert "pen" in glossary.for_locale("de-DE")


def test_for_locale_of_an_unknown_locale_is_empty(tmp_path):
    assert load_glossary(write(tmp_path, CSV)).for_locale("fr-FR") == {}


def test_for_locale_returns_a_copy(tmp_path):
    glossary = load_glossary(write(tmp_path, CSV))
    glossary.for_locale("de-DE").clear()
    assert glossary.for_locale("de-DE")


def test_a_missing_file_is_an_empty_glossary(tmp_path):
    glossary = load_glossary(tmp_path / "nothing.csv")
    assert not glossary
    assert len(glossary) == 0


def test_blank_rows_are_skipped(tmp_path):
    glossary = load_glossary(write(tmp_path, CSV + ",,,\n"))
    assert len(glossary) == 3


def test_a_row_missing_a_field_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="all required"):
        load_glossary(write(tmp_path, "term,locale,translation\npen,de-DE,\n"))


def test_the_error_names_the_line(tmp_path):
    with pytest.raises(ConfigError, match=":3:"):
        load_glossary(write(tmp_path, "term,locale,translation\npen,de-DE,Stift\nx,,\n"))


def test_a_missing_column_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="missing the translation column"):
        load_glossary(write(tmp_path, "term,locale\npen,de-DE\n"))


def test_contradictory_terms_are_rejected():
    glossary = Glossary()
    glossary.add(Term(term="pen", locale="de-DE", translation="Stift"))
    with pytest.raises(ConfigError, match="two translations"):
        glossary.add(Term(term="Pen", locale="de-DE", translation="Feder"))


def test_repeating_the_same_term_is_fine():
    glossary = Glossary([
        Term(term="pen", locale="de-DE", translation="Stift"),
        Term(term="pen", locale="de-DE", translation="Stift"),
    ])
    assert len(glossary) == 1


def test_the_checked_in_glossary_loads():
    root = Path(__file__).resolve().parents[1]
    glossary = load_glossary(root / "glossary" / "v4t-terms.csv")
    assert glossary.for_locale("de-DE")["pen"].translation == "Stift"
    assert glossary.for_locale("zh-TW")["printhead"].translation == "列印頭"


def test_no_glossary_means_no_findings():
    assert run(context_for(), "Pen", "Feder") == []


def test_a_term_used_correctly():
    context = context_for(terms={"pen": "Stift"})
    assert run(context, "Pen", "Stift") == []


def test_a_term_used_wrongly():
    context = context_for(terms={"pen": "Stift"})
    findings = run(context, "Pen", "Feder")
    assert len(findings) == 1
    assert "'pen' should be translated as 'Stift'" in findings[0].summary


def test_the_source_match_is_case_insensitive():
    context = context_for(terms={"pen": "Stift"})
    assert run(context, "PEN offsets", "Feder-Versätze")


def test_the_source_match_is_whole_word():
    context = context_for(terms={"pen": "Stift"})
    assert run(context, "Open the door", "Tür öffnen") == []
    assert run(context, "Spent cartridge", "Verbrauchte Patrone") == []


def test_the_target_match_allows_compounds():
    context = context_for(terms={"printhead": "Druckkopf"})
    assert run(context, "Printhead voltage", "Druckkopfspannung") == []


def test_the_target_match_is_case_insensitive():
    context = context_for(terms={"pen": "Stift"})
    assert run(context, "Pen", "stift") == []


def test_several_terms_in_one_string():
    context = context_for(terms={"pen": "Stift", "spacing": "Abstand"})
    findings = run(context, "Pen spacing", "Feder-Zwischenraum")
    assert len(findings) == 2


def test_findings_come_out_in_term_order():
    context = context_for(terms={"pen": "Stift", "barcode": "Barcode"})
    findings = run(context, "Barcode pen", "Strichcode Feder")
    assert findings[0].summary.startswith("'barcode'")


def test_a_multiword_term():
    context = context_for(terms={"firing voltage": "Zündspannung"})
    assert run(context, "Firing Voltage", "Zündspannung") == []
    assert run(context, "Firing Voltage", "Feuerspannung")


def test_mnemonic_markers_do_not_break_matching():
    context = context_for(terms={"pen": "Stift"})
    assert run(context, "&Pen", "&Stift") == []


def test_an_empty_translation_is_skipped():
    context = context_for(terms={"pen": "Stift"})
    assert run(context, "Pen", "") == []
