import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.config import CheckSettings
from v4t_translate.errors import ConfigError
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import Rule, RuleContext
from v4t_translate.rules.protocol import ProtocolRule, control_characters
from v4t_translate.rules.registry import (
    ALL_RULES,
    SeverityOverride,
    build_rules,
    rule_names,
)
from v4t_translate.rules.result import Severity


@pytest.fixture
def mini_context():
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("mini-20x4"),
        font=monospace(6, ranges=[(0x00, 0x2FFF)]),
    )


@pytest.fixture
def windows_context():
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x00, 0x2FFF)]),
    )


def run(rule, context, source, target):
    message = Message(key="k.1", source_text=source)
    translation = Translation(text=target, state=TranslationState.APPROVED)
    return list(rule.check(message, translation, context))


def test_control_characters_finds_the_real_ones():
    assert control_characters("a\x02b\x03") == ["\x02", "\x03"]


def test_control_characters_allows_tab_and_newline():
    assert control_characters("a\tb\nc") == []


def test_control_characters_dedupes():
    assert control_characters("\x01\x01\x01") == ["\x01"]


def test_control_characters_finds_a_zero_width_joiner():
    assert control_characters("a‍b") == ["‍"]


def test_a_clean_string_passes(mini_context):
    assert run(ProtocolRule(), mini_context, "Print started", "Druck gestartet") == []


def test_a_frame_marker_is_an_error(mini_context):
    findings = run(ProtocolRule(), mini_context, "Print started", "Druck\x03gestartet")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "U+0003" in findings[0].summary
    assert "desynchronises" in findings[0].detail


def test_a_stray_control_character_is_a_warning(mini_context):
    findings = run(ProtocolRule(), mini_context, "Print started", "Druck\x01gestartet")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_a_reserved_character_is_not_reported_twice(mini_context):
    findings = run(ProtocolRule(), mini_context, "x", "a\x02b")
    assert len(findings) == 1


def test_a_windows_panel_reserves_nothing_but_still_warns(windows_context):
    findings = run(ProtocolRule(), windows_context, "x", "a\x02b")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_an_empty_translation_is_skipped(mini_context):
    assert run(ProtocolRule(), mini_context, "x", "") == []


def test_every_rule_has_a_unique_name():
    names = rule_names()
    assert len(names) == len(set(names)) == len(ALL_RULES)


def test_the_order_puts_the_worst_consequence_first():
    assert rule_names()[0] == "placeholders"
    assert rule_names()[-1] == "glossary"


def test_every_rule_satisfies_the_protocol():
    for rule in build_rules():
        assert isinstance(rule, Rule)


def test_build_returns_everything_by_default():
    assert [r.name for r in build_rules()] == rule_names()


def test_build_with_no_settings_at_all():
    assert len(build_rules(None)) == len(ALL_RULES)


def test_disabling_a_rule():
    built = build_rules(CheckSettings(disabled_rules=("glossary", "whitespace")))
    names = [r.name for r in built]
    assert "glossary" not in names
    assert "whitespace" not in names
    assert "fitting" in names


def test_promoting_a_rule_changes_its_findings(mini_context):
    built = build_rules(CheckSettings(promoted_rules=("whitespace",)))
    rule = next(r for r in built if r.name == "whitespace")
    findings = run(rule, mini_context, "Pen", " Stift")
    assert findings and all(f.severity is Severity.ERROR for f in findings)


def test_demoting_a_rule_changes_its_findings(mini_context):
    built = build_rules(CheckSettings(demoted_rules=("protocol",)))
    rule = next(r for r in built if r.name == "protocol")
    findings = run(rule, mini_context, "x", "a\x03b")
    assert findings and all(f.severity is Severity.WARNING for f in findings)


def test_an_override_keeps_everything_else_about_the_finding(mini_context):
    plain = run(ProtocolRule(), mini_context, "x", "a\x03b")[0]
    wrapped = run(SeverityOverride(ProtocolRule(), Severity.INFO), mini_context,
                  "x", "a\x03b")[0]
    assert wrapped.summary == plain.summary
    assert wrapped.detail == plain.detail
    assert wrapped.rule == plain.rule
    assert wrapped.severity is Severity.INFO


def test_an_override_reports_the_new_default_severity():
    wrapped = SeverityOverride(ProtocolRule(), Severity.WARNING)
    assert wrapped.default_severity is Severity.WARNING
    assert wrapped.name == "protocol"


def test_an_unknown_rule_name_is_rejected():
    with pytest.raises(ConfigError, match="unknown rule 'spelling'"):
        build_rules(CheckSettings(disabled_rules=("spelling",)))


def test_the_error_lists_the_real_names():
    with pytest.raises(ConfigError) as excinfo:
        build_rules(CheckSettings(promoted_rules=("nope",)))
    assert "placeholders" in str(excinfo.value)


def test_promoting_and_demoting_the_same_rule_is_rejected():
    with pytest.raises(ConfigError, match="both promoted and demoted"):
        build_rules(CheckSettings(promoted_rules=("fitting",), demoted_rules=("fitting",)))
