import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation
from v4t_translate.layout.bidi import (
    MIRRORED,
    RLM,
    suggest_marks,
    unbalanced_brackets,
    visual_order,
)
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.direction import DirectionRule
from v4t_translate.rules.result import Severity

# "Pen" in Hebrew, and a short Arabic word, so a test reads as text rather
# than as escape sequences.
HEB = "עט"
ARA = "قلم"


def context(tag="he-IL"):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0xFFFF)]),
    )


def run(target, tag="he-IL", source="Pen 3:"):
    message = Message(key="a.1", source_text=source)
    return list(DirectionRule().check(message, Translation(text=target),
                                      context(tag)))


# -- suggesting a mark --------------------------------------------------


def test_a_trailing_colon_gets_a_mark():
    assert suggest_marks(f"{HEB} 3:") == f"{HEB} 3:{RLM}"


def test_a_boundary_between_scripts_gets_one():
    suggested = suggest_marks(f"{HEB}: V4T")
    assert RLM in suggested
    assert suggested.index(RLM) < suggested.index("V")


def test_plain_rtl_text_is_left_alone():
    assert suggest_marks(HEB) == HEB


def test_plain_ltr_text_gets_nothing_added_in_the_middle():
    assert suggest_marks("Pen") == "Pen"


def test_a_string_that_already_has_a_mark_is_untouched():
    text = f"{HEB} 3:{RLM}"
    assert suggest_marks(text) == text


def test_an_empty_string_stays_empty():
    assert suggest_marks("") == ""


def test_the_mark_can_be_chosen():
    from v4t_translate.layout.bidi import LRM

    assert suggest_marks(f"{HEB} 3:", mark=LRM).endswith(LRM)


def test_the_suggestion_keeps_every_original_character():
    text = f"{HEB} V4T 3:"
    assert suggest_marks(text).replace(RLM, "") == text


def test_the_suggestion_satisfies_the_check():
    from v4t_translate.layout.bidi import needs_isolation

    text = f"{HEB} V4T:"
    assert needs_isolation(text)
    assert not needs_isolation(suggest_marks(text))


# -- the visual preview -------------------------------------------------


def test_an_rtl_run_is_reversed():
    assert visual_order(HEB) == HEB[::-1]


def test_an_embedded_latin_run_keeps_its_order():
    assert "V4T" in visual_order(f"{HEB} V4T")


def test_the_embedded_run_ends_up_on_the_left():
    assert visual_order(f"{HEB} V4T").startswith("V4T")


def test_an_ltr_paragraph_is_left_alone():
    assert visual_order(f"{HEB} V4T", paragraph="ltr") == f"{HEB} V4T"


def test_brackets_are_mirrored_in_an_rtl_run():
    assert visual_order(f"({HEB})") == f"({HEB[::-1]})"


def test_every_mirrored_pair_maps_both_ways():
    for left, right in MIRRORED.items():
        assert MIRRORED[right] == left


def test_the_preview_keeps_the_same_characters():
    text = f"{HEB} V4T 3"
    assert sorted(visual_order(text)) == sorted(text)


def test_an_empty_string_previews_as_empty():
    assert visual_order("") == ""


# -- brackets -----------------------------------------------------------


def test_balanced_brackets_are_fine():
    assert unbalanced_brackets("Pen (3)") == []


def test_a_missing_close_is_found():
    assert unbalanced_brackets("Pen (3") == ["("]


def test_a_stray_close_is_found():
    assert unbalanced_brackets("Pen 3)") == [")"]


def test_a_crossed_pair_is_found():
    # All three are unmatched: the close does not match the open above it, and
    # neither of the two opens ever gets one.
    assert unbalanced_brackets("[Pen (3]") == ["]", "(", "["]


def test_nesting_is_allowed():
    assert unbalanced_brackets("([Pen 3])") == []


def test_an_apostrophe_is_not_a_bracket():
    assert unbalanced_brackets("operator's pen") == []


def test_angle_brackets_are_not_counted():
    # <V1> is a placeholder token in this product, and the placeholders rule
    # already owns it.
    assert unbalanced_brackets("Value <V1") == []


# -- the rule -----------------------------------------------------------


def test_a_mixed_string_with_no_mark_is_reported():
    findings = run(f"{HEB} V4T:")
    assert any("no directional mark" in f.summary for f in findings)


def test_the_detail_shows_what_the_panel_would_draw():
    detail = next(f for f in run(f"{HEB} V4T:")
                  if "no directional mark" in f.summary).detail
    assert "reads as" in detail


def test_the_detail_offers_a_string_that_works():
    detail = next(f for f in run(f"{HEB} V4T:")
                  if "no directional mark" in f.summary).detail
    assert "Try" in detail
    # repr escapes the mark, which is the point of showing the string at all:
    # an invisible character is no use in a report.
    assert "u200f" in detail


def test_a_string_with_a_mark_is_quiet():
    assert run(f"{HEB} V4T:{RLM}") == []


def test_an_unbalanced_bracket_is_an_error():
    findings = run(f"{HEB} (V4T")
    bracket = next(f for f in findings if "pair up" in f.summary)
    assert bracket.severity is Severity.ERROR


def test_one_bracket_reads_singular():
    findings = run(f"{HEB} (V4T{RLM}")
    assert any("1 bracket that does not" in f.summary for f in findings)


def test_two_brackets_read_plural():
    findings = run(f"{HEB} ((V4T{RLM}")
    assert any("brackets that do not" in f.summary for f in findings)


def test_balanced_brackets_report_nothing():
    assert run(f"{HEB} (V4T){RLM}") == []


def test_brackets_are_not_checked_for_a_left_to_right_language():
    # The panel does not mirror anything there, so an unbalanced bracket is a
    # typo like any other and not this rule's business.
    assert not any("pair up" in f.summary for f in run("Pen (3", tag="de-DE"))


def test_a_mark_in_a_left_to_right_language_is_still_an_error():
    findings = run(f"Stift{RLM}", tag="de-DE")
    assert findings[0].severity is Severity.ERROR


def test_an_empty_translation_is_skipped():
    assert run("") == []


@pytest.mark.parametrize("text", ["Pen 3", HEB, "", "V4T"])
def test_unmixed_strings_report_nothing(text):
    assert not any("no directional mark" in f.summary for f in run(text))
