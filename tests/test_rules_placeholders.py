import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.placeholders import PlaceholderRule, find_placeholders
from v4t_translate.rules.result import Severity


@pytest.fixture
def context():
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("tij-800x600"),
        font=monospace(6),
    )


@pytest.fixture
def rule():
    return PlaceholderRule()


def run(rule, context, source, target):
    message = Message(key="k.1", source_text=source)
    translation = Translation(text=target, state=TranslationState.APPROVED)
    return list(rule.check(message, translation, context))


def texts(text):
    return [p.text for p in find_placeholders(text)]


def test_finds_plain_specifiers():
    assert texts("Please input from %.1fV to %.1fV.") == ["%.1f", "%.1f"]


def test_finds_a_bare_specifier():
    assert texts("%s of %d") == ["%s", "%d"]


def test_a_doubled_percent_is_not_a_placeholder():
    assert texts("100%% complete") == []


def test_a_doubled_percent_beside_a_real_one():
    assert texts("%d%% of %s") == ["%d", "%s"]


def test_finds_length_modifiers():
    assert texts("%lld and %hhu") == ["%lld", "%hhu"]


def test_finds_positional_specifiers():
    found = find_placeholders("%1$s at %2$d")
    assert [p.text for p in found] == ["%1$s", "%2$d"]
    assert all(p.positional for p in found)


def test_finds_the_v4t_named_tokens():
    assert texts("Value must be between <V1> and <V2>") == ["<V1>", "<V2>"]


def test_finds_braced_tokens():
    assert texts("Printing {0} of {count}") == ["{0}", "{count}"]


def test_placeholders_come_back_in_source_order():
    assert texts("<V1> then %d then {x}") == ["<V1>", "%d", "{x}"]


def test_order_matters_only_for_unnumbered_printf():
    plain, positional, named = find_placeholders("%s %1$d <V1>")
    assert plain.order_matters
    assert not positional.order_matters
    assert not named.order_matters


def test_normalized_drops_width_and_flags():
    assert find_placeholders("%-08.3f")[0].normalized() == "%f"
    assert find_placeholders("%5d")[0].normalized() == "%d"


def test_normalized_keeps_the_length_modifier():
    assert find_placeholders("%lld")[0].normalized() == "%lld"


def test_a_correct_translation_reports_nothing(rule, context):
    assert run(rule, context,
               "Please input from %.1fV to %.1fV.",
               "Bitte geben Sie %.1fV bis %.1fV ein.") == []


def test_a_string_with_no_placeholders_reports_nothing(rule, context):
    assert run(rule, context, "Print started", "Druck gestartet") == []


def test_an_empty_translation_is_not_this_rules_problem(rule, context):
    assert run(rule, context, "%s failed", "") == []


def test_a_dropped_specifier(rule, context):
    findings = run(rule, context, "Please input from %.1fV to %.1fV.",
                   "Bitte geben Sie einen Wert ein.")
    assert len(findings) == 1
    assert "missing" in findings[0].summary
    assert "%f x2" in findings[0].summary
    assert findings[0].severity is Severity.ERROR


def test_one_of_two_dropped(rule, context):
    findings = run(rule, context, "%.1fV to %.1fV", "%.1fV bis")
    assert len(findings) == 1
    assert "missing %f" in findings[0].summary


def test_an_invented_specifier(rule, context):
    findings = run(rule, context, "Print started", "Druck %s gestartet")
    assert len(findings) == 1
    assert "does not" in findings[0].summary


def test_the_wrong_conversion_is_both_missing_and_extra(rule, context):
    findings = run(rule, context, "Pen %d", "Stift %s")
    assert len(findings) == 2
    assert {"missing" in f.summary for f in findings} == {True, False}


def test_widening_a_field_is_not_a_defect(rule, context):
    assert run(rule, context, "Pen %d", "Stift %3d") == []


def test_changing_the_conversion_length_is_a_defect(rule, context):
    findings = run(rule, context, "Pen %d", "Stift %lld")
    assert findings


def test_reordering_unnumbered_specifiers_is_reported(rule, context):
    findings = run(rule, context, "%d of %s", "%s von %d")
    assert len(findings) == 1
    assert "reordered" in findings[0].summary
    assert "%1$s" in findings[0].detail


def test_reordering_numbered_specifiers_is_fine(rule, context):
    assert run(rule, context, "%1$d of %2$s", "%2$s von %1$d") == []


def test_reordering_named_tokens_is_fine(rule, context):
    assert run(rule, context,
               "Value must be between <V1> and <V2>",
               "Zwischen <V2> und <V1> muss der Wert liegen") == []


def test_a_dropped_named_token_is_reported(rule, context):
    findings = run(rule, context,
                   "Value must be between <V1> and <V2>",
                   "Der Wert muss zwischen <V1> liegen")
    assert len(findings) == 1
    assert "<V2>" in findings[0].summary


def test_the_real_length_limit_string(rule, context):
    assert run(rule, context,
               "The length must be less <V1> chars",
               "Die Länge muss weniger als <V1> Zeichen betragen") == []


def test_reorder_is_not_reported_when_the_set_is_already_wrong(rule, context):
    findings = run(rule, context, "%d of %s", "%s only")
    assert all("reordered" not in f.summary for f in findings)


def test_the_finding_carries_both_texts(rule, context):
    finding = run(rule, context, "Pen %d", "Stift")[0]
    assert finding.source_text == "Pen %d"
    assert finding.translated_text == "Stift"
    assert finding.locale == "de-DE"
    assert finding.rule == "placeholders"
