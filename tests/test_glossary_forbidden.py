from pathlib import Path

import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation
from v4t_translate.errors import ConfigError
from v4t_translate.glossary import Glossary, Term, load_glossary
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.glossary import GlossaryRule
from v4t_translate.rules.result import Severity

SHIPPED = Path(__file__).resolve().parents[1] / "glossary" / "v4t-terms.csv"

HEADER = "term,locale,translation,forbidden,note\n"


def context(*terms, tag="de-DE"):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0x9FFF)]),
        glossary={term.key: term for term in terms},
    )


def run(term, source, target, tag="de-DE"):
    message = Message(key="a.1", source_text=source)
    return list(GlossaryRule().check(message, Translation(text=target),
                                     context(term, tag=tag)))


def write(tmp_path, body):
    path = tmp_path / "terms.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_the_forbidden_column_is_parsed(tmp_path):
    glossary = load_glossary(write(tmp_path, "pen,de-DE,Stift,Feder;Patrone,\n"))
    term = glossary.for_locale("de-DE")["pen"]
    assert term.forbidden == ("feder", "patrone")


def test_forbidden_renderings_are_lowered_and_trimmed(tmp_path):
    glossary = load_glossary(write(tmp_path, "pen,de-DE,Stift, Feder ; PATRONE ,\n"))
    assert glossary.for_locale("de-DE")["pen"].forbidden == ("feder", "patrone")


def test_a_repeated_forbidden_rendering_is_kept_once(tmp_path):
    glossary = load_glossary(write(tmp_path, "pen,de-DE,Stift,Feder;feder,\n"))
    assert glossary.for_locale("de-DE")["pen"].forbidden == ("feder",)


def test_an_empty_forbidden_column_is_fine(tmp_path):
    glossary = load_glossary(write(tmp_path, "pen,de-DE,Stift,,\n"))
    assert glossary.for_locale("de-DE")["pen"].forbidden == ()


def test_a_glossary_without_the_column_still_loads(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("term,locale,translation,note\npen,de-DE,Stift,\n", encoding="utf-8")
    assert load_glossary(path).for_locale("de-DE")["pen"].forbidden == ()


def test_forbidding_what_is_required_is_refused(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load_glossary(write(tmp_path, "pen,de-DE,Stift,Stift,\n"))
    assert "also what it requires" in str(caught.value)


def test_that_refusal_names_the_row(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load_glossary(write(tmp_path, "pen,de-DE,Stift,Feder,\nink,de-DE,Tinte,Tinte,\n"))
    assert ":3:" in str(caught.value)


def test_an_empty_forbidden_rendering_is_refused_when_built_directly():
    with pytest.raises(ConfigError):
        Glossary().add(Term(term="pen", locale="de-DE", translation="Stift",
                            forbidden=("",)))


def test_two_rows_join_their_forbidden_lists(tmp_path):
    glossary = load_glossary(
        write(tmp_path, "pen,de-DE,Stift,Feder,\npen,de-DE,Stift,Patrone,\n")
    )
    assert glossary.for_locale("de-DE")["pen"].forbidden == ("feder", "patrone")


def test_two_rows_that_disagree_are_still_refused(tmp_path):
    with pytest.raises(ConfigError):
        load_glossary(write(tmp_path, "pen,de-DE,Stift,,\npen,de-DE,Feder,,\n"))


def test_a_forbidden_rendering_is_reported():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder",))
    findings = run(term, "Pen offset", "Federversatz")
    assert any("feder" in f.summary for f in findings)


def test_a_forbidden_rendering_is_an_error_not_a_warning():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder",))
    banned = [f for f in run(term, "Pen offset", "Federversatz")
              if "feder" in f.summary]
    assert banned[0].severity is Severity.ERROR


def test_the_missing_term_finding_stays_a_warning():
    term = Term(term="pen", locale="de-DE", translation="Stift")
    findings = run(term, "Pen offset", "Versatz")
    assert findings[0].severity is Severity.WARNING


def test_a_forbidden_rendering_matches_regardless_of_case():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder",))
    assert run(term, "Pen offset", "FEDER Versatz")


def test_the_right_translation_reports_nothing():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder",))
    assert not run(term, "Pen offset", "Stiftversatz")


def test_both_findings_can_come_from_one_string():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder",))
    findings = run(term, "Pen offset", "Federversatz")
    assert len(findings) == 2


def test_the_detail_lists_what_was_rejected():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder", "patrone"))
    findings = run(term, "Pen offset", "Versatz")
    assert "feder, patrone" in findings[0].detail


def test_the_note_reaches_the_detail():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                note="Settled 2024-03.")
    assert "Settled 2024-03." in run(term, "Pen offset", "Versatz")[0].detail


def test_forbidden_still_fires_when_the_term_is_not_configured_for_the_source():
    term = Term(term="pen", locale="de-DE", translation="Stift",
                forbidden=("feder",))
    # The source has no "pen" in it, so the rule never looks at this row.
    assert not run(term, "Bar height", "Federhöhe")


def test_a_do_not_translate_term_kept_as_it_is_reports_nothing():
    term = Term(term="V4T", locale="de-DE", translation="=")
    assert not run(term, "V4T setup", "V4T Einrichtung")


def test_a_do_not_translate_term_that_was_recased_is_an_error():
    term = Term(term="V4T", locale="de-DE", translation="=")
    findings = run(term, "V4T setup", "V4t Einrichtung")
    assert findings[0].severity is Severity.ERROR
    assert "capitals" in findings[0].summary


def test_a_do_not_translate_term_that_vanished_is_a_warning():
    term = Term(term="V4T", locale="de-DE", translation="=")
    findings = run(term, "V4T setup", "Einrichtung")
    assert findings[0].severity is Severity.WARNING
    assert "missing" in findings[0].summary


def test_a_do_not_translate_term_survives_chinese_neighbours():
    term = Term(term="V4T", locale="zh-TW", translation="=")
    assert not run(term, "V4T setup", "設定V4T印表機", tag="zh-TW")


def test_keep_source_is_visible_on_the_term():
    assert Term(term="V4T", locale="de-DE", translation="=").keep_source
    assert not Term(term="pen", locale="de-DE", translation="Stift").keep_source


def test_the_required_text_of_a_kept_term_is_the_term():
    assert Term(term="V4T", locale="de-DE", translation="=").required == "v4t"


def test_describe_reads_differently_for_a_kept_term():
    assert "not translated" in Term(term="V4T", locale="de-DE",
                                    translation="=").describe()
    assert Term(term="pen", locale="de-DE",
                translation="Stift").describe() == "pen is Stift"


def test_the_shipped_glossary_loads():
    glossary = load_glossary(SHIPPED)
    assert glossary.forbidden_count > 0


def test_the_shipped_glossary_records_the_pen_decision():
    term = load_glossary(SHIPPED).for_locale("de-DE")["pen"]
    assert "feder" in term.forbidden
    assert "patrone" in term.forbidden


def test_the_shipped_glossary_keeps_the_product_name():
    for tag in ("de-DE", "zh-TW"):
        assert load_glossary(SHIPPED).for_locale(tag)["v4t"].keep_source


def test_the_shipped_notes_do_not_repeat_the_forbidden_list():
    # The note used to be where a rejected rendering was written down, which
    # meant nothing enforced it. If one is in both places the data has drifted.
    glossary = load_glossary(SHIPPED)
    for tag in glossary.locales():
        for term in glossary.for_locale(tag).values():
            for banned in term.forbidden:
                assert f"Never {banned.title()}" not in term.note
