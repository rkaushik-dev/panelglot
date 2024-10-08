import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.protected import ProtectedRule
from v4t_translate.rules.punctuation import PunctuationRule, WhitespaceRule
from v4t_translate.rules.result import Severity


@pytest.fixture
def context():
    return RuleContext(
        locale=resolve("zh-TW"),
        panel=get_panel("tij-800x600"),
        font=monospace(6, ranges=[(0x20, 0x9FFF)]),
    )


def run(rule, context, source, target, *, protected=False,
        state=TranslationState.APPROVED):
    message = Message(key="k.1", source_text=source, protected=protected)
    translation = Translation(text=target, state=state)
    return list(rule.check(message, translation, context))


def summaries(findings):
    return [f.summary for f in findings]


def test_an_unprotected_message_is_not_checked(context):
    assert run(ProtectedRule(), context, "Delete", "刪除") == []


def test_a_protected_message_that_survived(context):
    assert run(ProtectedRule(), context, "mm", "mm", protected=True) == []


def test_a_protected_message_that_was_translated(context):
    findings = run(ProtectedRule(), context, "mm", "毫米", protected=True)
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "protected string has been translated" in findings[0].summary
    assert "'mm'" in findings[0].detail


def test_the_real_date_token_case(context):
    findings = run(ProtectedRule(), context, "YYYY", "年年年年", protected=True)
    assert findings


def test_an_empty_protected_translation_is_not_a_finding(context):
    assert run(ProtectedRule(), context, "mm", "", protected=True) == []


def test_a_deliberate_override_is_information_only(context):
    findings = run(ProtectedRule(), context, "mm", "公釐", protected=True,
                   state=TranslationState.DO_NOT_TRANSLATE)
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO
    assert "overridden" in findings[0].summary


def test_a_matching_dnt_entry_is_silent(context):
    assert run(ProtectedRule(), context, "mm", "mm", protected=True,
               state=TranslationState.DO_NOT_TRANSLATE) == []


def test_punctuation_agreeing_reports_nothing(context):
    assert run(PunctuationRule(), context, "Preview:", "預覽：") == []


def test_a_dropped_colon(context):
    findings = run(PunctuationRule(), context, "Timestamps list:", "時間戳列表")
    assert len(findings) == 1
    assert "drops the trailing colon" in findings[0].summary
    assert "a control follows" in findings[0].detail


def test_an_added_colon(context):
    findings = run(PunctuationRule(), context, "Preview", "預覽：")
    assert "adds a trailing colon" in findings[0].summary


def test_a_full_width_colon_counts_as_a_colon(context):
    assert run(PunctuationRule(), context, "Format:", "格式：") == []


def test_a_dropped_ellipsis(context):
    findings = run(PunctuationRule(), context, "&Open...", "開啟")
    assert any("drops the trailing ellipsis" in s for s in summaries(findings))


def test_the_single_character_ellipsis_counts(context):
    assert run(PunctuationRule(), context, "&Open...", "&開啟…") == []


def test_an_added_ellipsis(context):
    findings = run(PunctuationRule(), context, "Change", "改變...")
    assert any("adds a trailing ellipsis" in s for s in summaries(findings))


def test_trailing_space_does_not_hide_the_punctuation(context):
    assert run(PunctuationRule(), context, "Preview:", "預覽：  ") == []


def test_mnemonic_markers_do_not_hide_the_punctuation(context):
    assert run(PunctuationRule(), context, "&Open...", "&開啟...") == []


def test_an_empty_translation_is_not_punctuated(context):
    assert run(PunctuationRule(), context, "Preview:", "") == []


def test_whitespace_that_matches(context):
    assert run(WhitespaceRule(), context, "Print started", "列印已開始") == []


def test_a_dropped_trailing_space(context):
    findings = run(WhitespaceRule(), context, "Purge offset must be less than ",
                   "清洗偏移必須小於")
    assert any("trailing whitespace changed from 1 to 0" in s for s in summaries(findings))


def test_an_added_leading_space(context):
    findings = run(WhitespaceRule(), context, "Pen", " 筆")
    assert any("leading whitespace changed from 0 to 1" in s for s in summaries(findings))


def test_a_preserved_double_space_is_fine(context):
    assert run(WhitespaceRule(), context, "Add  variable data", "新增  可變數據") == []


def test_an_introduced_double_space_is_information(context):
    findings = run(WhitespaceRule(), context, "Add variable data", "新增  可變數據")
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO


def test_an_introduced_tab_is_an_error(context):
    findings = run(WhitespaceRule(), context, "Exit", "離開\tCtrl+Q")
    assert any(f.severity is Severity.ERROR for f in findings)
    assert any("contains a tab" in s for s in summaries(findings))


def test_a_preserved_tab_is_fine(context):
    assert run(WhitespaceRule(), context, "&New\tCtrl+N", "新增(&N)\tCtrl+N") == []


def test_rule_names():
    assert ProtectedRule.name == "protected"
    assert PunctuationRule.name == "punctuation"
    assert WhitespaceRule.name == "whitespace"
