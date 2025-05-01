import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.numbers import (
    NumberRule,
    literal_numbers,
    normalise_number,
)
from v4t_translate.rules.result import Severity


def context_for(tag="de-DE"):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0xFFFF)]),
    )


def run(source, target, tag="de-DE"):
    return list(NumberRule().check(
        Message(key="k.1", source_text=source),
        Translation(text=target, state=TranslationState.APPROVED),
        context_for(tag),
    ))


def summaries(findings):
    return [f.summary for f in findings]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Print started", []),
        ("Maximum 8 pens", ["8"]),
        ("Set 0 to disable", ["0"]),
        ("Firing voltage 12.4V", ["12.4"]),
        ("Between 4 and 16 pens", ["4", "16"]),
        ("1.250 mm", ["1.250"]),
    ],
)
def test_literal_numbers(text, expected):
    assert literal_numbers(text) == expected


def test_placeholders_are_not_numbers():
    assert literal_numbers("Please input from %.1fV to %.1fV.") == []
    assert literal_numbers("Pen %02d of %d") == []


def test_a_placeholder_beside_a_real_number():
    assert literal_numbers("Pen %d of 8") == ["8"]


def test_a_version_number_is_not_a_quantity():
    assert literal_numbers("V4T version 4.1.0") == []


def test_a_year_is_not_a_quantity():
    assert literal_numbers("Copyright 2024 Sellenis") == []


def test_a_serial_standard_is_not_a_quantity():
    assert literal_numbers("Connect over RS-232") == []
    assert literal_numbers("Connect over RS485") == []


def test_a_mnemonic_marker_does_not_hide_a_number():
    assert literal_numbers("&Maximum 8 pens") == ["8"]


@pytest.mark.parametrize(
    ("text", "tag", "expected"),
    [
        ("12.4", "en-US", "124"),
        ("12,4", "de-DE", "124"),
        ("1,250", "en-US", "1250"),
        ("1.250", "de-DE", "1250"),
        ("8", "de-DE", "8"),
    ],
)
def test_normalise(text, tag, expected):
    assert normalise_number(text, resolve(tag)) == expected


def test_a_string_with_no_numbers_is_silent():
    assert run("Print started", "Druck gestartet") == []


def test_a_number_that_survived():
    assert run("Maximum 8 pens", "Maximal 8 Stifte") == []


def test_a_dropped_number_is_an_error():
    findings = run("Maximum 8 pens", "Maximale Stiftanzahl")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "the number 8 is in the English" in findings[0].summary


def test_a_changed_number_is_reported_both_ways():
    findings = run("Maximum 8 pens", "Maximal 6 Stifte")
    assert len(findings) == 2
    assert any("8 is in the English" in s for s in summaries(findings))
    assert any("has the number 6" in s for s in summaries(findings))


def test_an_invented_number():
    findings = run("Maximum pens", "Maximal 8 Stifte")
    assert len(findings) == 1
    assert "the English has none" in findings[0].summary


def test_two_numbers_both_kept():
    assert run("Between 4 and 16 pens", "Zwischen 4 und 16 Stiften") == []


def test_two_numbers_reordered_is_fine():
    # German word order moves them and the values are what matter.
    assert run("Between 4 and 16 pens", "16 und 4 Stifte dazwischen") == []


def test_one_of_two_dropped():
    findings = run("Between 4 and 16 pens", "Zwischen 4 Stiften")
    assert any("the number 16" in s for s in summaries(findings))


def test_a_repeated_number_has_to_be_repeated():
    findings = run("Set 0 or 0 to disable", "Auf 0 setzen")
    assert findings


def test_the_decimal_mark_is_converted():
    assert run("Firing voltage 12.4V", "Zündspannung 12,4V") == []


def test_the_english_mark_left_in_is_a_warning():
    findings = run("Firing voltage 12.4V", "Zündspannung 12.4V")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "English convention" in findings[0].summary
    assert "12,4" in findings[0].detail


def test_a_language_that_uses_a_point_never_warns():
    assert run("Firing voltage 12.4V", "點火電壓 12.4V", tag="zh-TW") == []


def test_a_thousands_group_is_not_mistaken_for_a_decimal():
    # "1.250" in a German string is one thousand two hundred and fifty.
    assert run("1,250 mm", "1.250 mm") == []


def test_an_integer_never_warns_about_its_mark():
    assert run("Maximum 8 pens", "Maximal 8 Stifte") == []


def test_an_empty_translation_is_skipped():
    assert run("Maximum 8 pens", "") == []


def test_a_placeholder_only_string_is_silent():
    assert run("Please input from %.1fV to %.1fV.",
               "Bitte geben Sie %.1fV bis %.1fV ein.") == []


def test_the_rule_is_registered():
    from v4t_translate.rules.registry import rule_names

    assert "numbers" in rule_names()


def test_it_runs_near_the_top():
    from v4t_translate.rules.registry import rule_names

    names = rule_names()
    assert names.index("numbers") < names.index("fitting")
