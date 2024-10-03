import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import load_metrics, monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.fitting import FittingRule
from v4t_translate.rules.result import Severity


@pytest.fixture
def rule():
    return FittingRule()


@pytest.fixture
def context():
    # Six pixels a character, so 60px is exactly ten characters.
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0x2FFF)], name="test"),
    )


@pytest.fixture
def mini_context(fixtures_dir):
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("mini-20x4"),
        font=load_metrics(fixtures_dir / "fonts" / "mini-5x7.fmx"),
    )


def run(rule, context, source, target, **kw):
    message = Message(key="k.1", source_text=source, **kw)
    translation = Translation(text=target, state=TranslationState.APPROVED)
    return list(rule.check(message, translation, context))


def summaries(findings):
    return [f.summary for f in findings]


def test_a_message_with_no_budget_is_not_checked(rule, context):
    assert run(rule, context, "Print Spacing", "Ein sehr langer Druckabstand") == []


def test_a_translation_that_fits(rule, context):
    assert run(rule, context, "Width", "Breite", max_width_px=60) == []


def test_an_empty_translation_is_skipped(rule, context):
    assert run(rule, context, "Width", "", max_width_px=6) == []


def test_an_overflow_reports_the_pixel_count(rule, context):
    findings = run(rule, context, "Width", "Druckerauflösung", max_width_px=60)
    assert len(findings) == 1
    assert findings[0].summary == "overflows its control by 36px"
    assert findings[0].severity is Severity.ERROR


def test_the_detail_gives_both_measurements(rule, context):
    detail = run(rule, context, "Width", "Druckerauflösung", max_width_px=60)[0].detail
    assert "60px available" in detail
    assert "96px needed" in detail
    assert "the English is 30px" in detail
    assert "in test" in detail


def test_a_near_miss_is_a_warning(rule, context):
    # Ten characters exactly fills a 60px budget.
    findings = run(rule, context, "Width", "Breitenmaß", max_width_px=60)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "nothing to spare" in findings[0].summary


def test_a_comfortable_fit_is_silent(rule, context):
    assert run(rule, context, "Width", "Breite", max_width_px=100) == []


def test_a_control_with_no_room_at_all(rule, context):
    findings = run(rule, context, "On", "Ein", max_width_px=0)
    assert len(findings) == 1
    assert "no room for any text" in findings[0].summary


def test_a_negative_budget_is_the_same_case(rule, context):
    assert "no room" in run(rule, context, "On", "Ein", max_width_px=-4)[0].summary


def test_mnemonic_markers_are_not_measured(rule, context):
    # "&Breite" draws as six characters, so it fits a 40px budget.
    assert run(rule, context, "&Width", "&Breite", max_width_px=40) == []


def test_a_wrapping_control_can_take_a_long_string(rule, context):
    assert run(rule, context, "Hint", "Dieser Abstand darf nicht",
               max_width_px=60, max_lines=5) == []


def test_a_wrapping_control_that_needs_too_many_lines(rule, context):
    findings = run(rule, context, "Hint", "Dieser Abstand darf nicht groesser sein",
                   max_width_px=60, max_lines=2)
    assert any("needs 6 lines and the control shows 2" in s for s in summaries(findings))


def test_a_near_miss_is_not_reported_on_a_wrapping_control(rule, context):
    findings = run(rule, context, "Hint", "Abstand ab", max_width_px=60, max_lines=3)
    assert all("nothing to spare" not in s for s in summaries(findings))


def test_the_character_budget_comes_from_the_panel(rule, mini_context):
    findings = run(rule, mini_context, "Print started", "Druck wurde gestartet")
    assert any("21 characters and the panel shows 20" in s for s in summaries(findings))


def test_the_character_budget_passes_when_it_fits(rule, mini_context):
    assert run(rule, mini_context, "Print started", "Druck gestartet") == []


def test_an_explicit_character_budget_beats_the_panel(rule, mini_context):
    findings = run(rule, mini_context, "Print started", "Druck gestartet", max_chars=8)
    assert any("15 characters and the panel shows 8" in s for s in summaries(findings))


def test_the_character_budget_ignores_mnemonic_markers(rule, mini_context):
    assert run(rule, mini_context, "&Print started", "&Druck gestartet") == []


def test_a_graphic_panel_has_no_character_budget(rule, context):
    assert run(rule, context, "Print started", "Ein wirklich sehr langer Text") == []


def test_the_real_german_overflow_case(fixtures_dir, rule):
    tahoma = load_metrics(fixtures_dir / "fonts" / "tahoma-8.fmx")
    context = RuleContext(locale=resolve("de-DE"), panel=get_panel("tij-800x600"),
                          font=tahoma)
    # "Traverse Printing" sits in a 68 unit checkbox, 85px after the box.
    assert run(rule, context, "Traverse Printing", "Querdruck", max_width_px=85) == []
    findings = run(rule, context, "Traverse Printing", "Querdruck im Wechselbetrieb",
                   max_width_px=85)
    assert findings and "overflows" in findings[0].summary
