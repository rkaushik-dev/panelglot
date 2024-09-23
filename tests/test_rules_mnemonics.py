import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.mnemonics import MnemonicRule, count_markers
from v4t_translate.rules.result import Severity


@pytest.fixture
def rule():
    return MnemonicRule()


@pytest.fixture
def context():
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("tij8pen-1024x768"),
        font=monospace(6, ranges=[(0x20, 0x7E), (0xC0, 0xFF)]),
    )


@pytest.fixture
def ascii_context():
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("mini-20x4"),
        font=monospace(6, ranges=[(0x20, 0x7E)], name="mini"),
    )


def run(rule, context, source, target):
    message = Message(key="k.1", source_text=source)
    translation = Translation(text=target, state=TranslationState.APPROVED)
    return list(rule.check(message, translation, context))


def summaries(findings):
    return [f.summary for f in findings]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("&Print", 1),
        ("P&rint", 1),
        ("Print", 0),
        ("Date&&Time", 0),
        ("&Date&&Time", 1),
        ("&A and &B", 2),
        ("&&&x", 1),
        ("trailing&", 1),
    ],
)
def test_count_markers(text, expected):
    assert count_markers(text) == expected


def test_a_matching_pair_reports_nothing(rule, context):
    assert run(rule, context, "&Print", "&Drucken") == []


def test_no_mnemonic_either_side_reports_nothing(rule, context):
    assert run(rule, context, "Print Spacing", "Druckabstand") == []


def test_an_empty_translation_is_not_checked(rule, context):
    assert run(rule, context, "&Print", "") == []


def test_a_dropped_mnemonic_is_a_warning(rule, context):
    findings = run(rule, context, "&Print", "Drucken")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "drops the keyboard mnemonic" in findings[0].summary
    assert "'P'" in findings[0].detail


def test_an_added_mnemonic_is_an_error(rule, context):
    findings = run(rule, context, "Size and Shape", "Größe &und Form")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "adds a mnemonic" in findings[0].summary


def test_an_unescaped_ampersand_is_reported_once_and_precisely(rule, context):
    # "Größe & Form" is both an added mnemonic and a marker that binds
    # nothing. Saying it twice helps nobody.
    findings = run(rule, context, "Size and Shape", "Größe & Form")
    assert len(findings) == 1
    assert "followed by a space" in findings[0].summary
    assert "&&" in findings[0].detail


def test_the_escaped_form_is_accepted(rule, context):
    assert run(rule, context, "Size and Shape", "Größe && Form") == []


def test_the_real_escaped_ampersand_string(rule, context):
    assert run(rule, context, "Date&&Time Format", "Datums&&Zeitformat") == []


def test_two_markers_is_an_error(rule, context):
    findings = run(rule, context, "&Print", "&Drucken und &Prüfen")
    assert any("2 mnemonic markers" in s for s in summaries(findings))
    assert any(f.severity is Severity.ERROR for f in findings)


def test_a_trailing_marker_is_an_error(rule, context):
    findings = run(rule, context, "Print", "Drucken&")
    assert any("ends with a mnemonic marker" in s for s in summaries(findings))


def test_a_marker_before_a_space_is_an_error(rule, context):
    findings = run(rule, context, "Print now", "Drucken & jetzt")
    assert any("followed by a space" in s for s in summaries(findings))


def test_only_the_first_bad_marker_position_is_reported(rule, context):
    findings = run(rule, context, "&Print", "&Drucken & jetzt")
    assert len(findings) == 1
    assert "followed by a space" in findings[0].summary


def test_a_double_ampersand_before_a_space_is_fine(rule, context):
    # This is the case that made the marker walk step one character at a time
    # and report the second half of an escaped pair.
    assert run(rule, context, "Size and Shape", "Größe && Form") == []


def test_a_mnemonic_the_font_cannot_draw(rule, ascii_context):
    findings = run(rule, ascii_context, "&Print", "&Ändern")
    assert any("not in the mini font" in s for s in summaries(findings))


def test_a_mnemonic_the_font_can_draw(rule, context):
    assert run(rule, context, "&Print", "&Ändern") == []


def test_the_mnemonic_glyph_check_is_skipped_when_there_is_no_marker(rule, ascii_context):
    findings = run(rule, ascii_context, "Print", "Ändern")
    assert all("not in the" not in s for s in summaries(findings))


def test_findings_carry_the_rule_name(rule, context):
    assert run(rule, context, "&Print", "Drucken")[0].rule == "mnemonics"
