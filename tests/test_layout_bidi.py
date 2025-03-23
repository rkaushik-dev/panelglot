import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.bidi import (
    ALM,
    LRM,
    RLM,
    direction_of,
    has_mixed_direction,
    needs_isolation,
    runs,
)
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.direction import DirectionRule
from v4t_translate.rules.result import Severity

# "Print" and "Pen" in Hebrew, and "Voltage" in Arabic.
HEBREW_PRINT = "הדפסה"
HEBREW_PEN = "עט"
ARABIC_VOLTAGE = "الجهد"


def context_for(tag):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0xFFFF)]),
    )


def run(tag, source, target):
    return list(DirectionRule().check(
        Message(key="k.1", source_text=source),
        Translation(text=target, state=TranslationState.APPROVED),
        context_for(tag),
    ))


@pytest.mark.parametrize(
    ("char", "expected"),
    [
        ("a", "ltr"), ("Z", "ltr"),
        ("ה", "rtl"), ("ا", "rtl"),
        ("3", "digit"), ("٣", "digit"),
        (" ", "neutral"), (":", "neutral"), ("(", "neutral"), ("%", "neutral"),
    ],
)
def test_direction_of(char, expected):
    assert direction_of(char) == expected


def test_runs_of_a_plain_english_string():
    assert runs("Print started") == [("ltr", "Print started")]


def test_runs_of_a_plain_hebrew_string():
    assert runs(HEBREW_PRINT) == [("rtl", HEBREW_PRINT)]


def test_runs_of_a_mixed_string():
    found = runs(f"{HEBREW_PEN} Sellenis")
    assert [direction for direction, _ in found] == ["rtl", "ltr"]


def test_digits_break_a_run_of_their_own():
    # V4T is three runs: letter, digit, letter. That is what the bidi
    # algorithm sees too, and it is why the product name needs a mark.
    found = runs(f"{HEBREW_PEN} V4T")
    assert [direction for direction, _ in found] == ["rtl", "ltr", "digit", "ltr"]


def test_neutrals_join_the_run_on_their_left():
    found = runs(f"{HEBREW_PEN}: V4T")
    assert found[0][1].endswith(": ")


def test_a_leading_neutral_starts_an_ltr_run():
    assert runs("  abc")[0][0] == "ltr"


def test_marks_are_not_a_run():
    assert runs(f"{HEBREW_PEN}{RLM} V4T") == runs(f"{HEBREW_PEN} V4T")


def test_runs_of_an_empty_string():
    assert runs("") == []


def test_mixed_direction():
    assert has_mixed_direction(f"{HEBREW_PEN} V4T")
    assert not has_mixed_direction("Print started")
    assert not has_mixed_direction(HEBREW_PRINT)


def test_digits_alone_are_not_a_direction_change():
    assert not has_mixed_direction(f"{HEBREW_PEN} 3")


def test_isolation_is_needed_for_trailing_punctuation():
    assert needs_isolation(f"{HEBREW_PEN} V4T:")


def test_isolation_is_needed_at_an_internal_boundary():
    assert needs_isolation(f"{HEBREW_PEN}: V4T {HEBREW_PRINT}")


def test_isolation_is_not_needed_when_a_mark_is_present():
    assert not needs_isolation(f"{HEBREW_PEN}{RLM}: V4T")


def test_any_of_the_three_marks_counts():
    for mark in (RLM, LRM, ALM):
        assert not needs_isolation(f"{HEBREW_PEN}{mark}: V4T:")


def test_isolation_is_not_needed_for_a_single_direction_string():
    assert not needs_isolation("Print started:")
    assert not needs_isolation(f"{HEBREW_PRINT}:")


def test_a_clean_english_translation_is_silent():
    assert run("de-DE", "Print started", "Druck gestartet") == []


def test_a_directional_mark_in_a_latin_language_is_an_error():
    findings = run("de-DE", "Print started", f"Druck{RLM} gestartet")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "not a right to left language" in findings[0].summary
    assert "spends a column" in findings[0].detail


def test_a_plain_rtl_translation_is_silent():
    assert run("he-IL", "Print started", HEBREW_PRINT) == []


def test_a_mixed_rtl_translation_with_no_mark_warns():
    findings = run("he-IL", "Pen V4T:", f"{HEBREW_PEN} V4T:")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "no directional mark" in findings[0].summary
    assert "U+200F" in findings[0].detail


def test_the_finding_quotes_the_english():
    findings = run("he-IL", "Pen V4T:", f"{HEBREW_PEN} V4T:")
    assert "'Pen V4T:'" in findings[0].detail


def test_a_mixed_rtl_translation_with_a_mark_is_accepted():
    assert run("he-IL", "Pen V4T:", f"{HEBREW_PEN}{RLM} V4T:") == []


def test_arabic_is_treated_the_same_way():
    findings = run("ar-SA", "Voltage %.1fV:", f"{ARABIC_VOLTAGE} %.1fV:")
    assert findings


def test_an_empty_translation_is_skipped():
    assert run("he-IL", "Print started", "") == []


def test_mnemonic_markers_are_not_measured():
    # The & is not drawn, so it cannot be the neutral at a boundary.
    assert run("he-IL", "&Print", f"&{HEBREW_PRINT}") == []


def test_the_rule_is_registered():
    from v4t_translate.rules.registry import rule_names

    assert "direction" in rule_names()


def test_the_suggested_mark_is_the_rtl_one():
    assert DirectionRule.suggested_mark() == RLM
