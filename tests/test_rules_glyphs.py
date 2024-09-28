import pytest

from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import load_metrics, monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.glyphs import EncodingRule, GlyphRule, unencodable


@pytest.fixture
def tahoma(fixtures_dir):
    return load_metrics(fixtures_dir / "fonts" / "tahoma-8.fmx")


@pytest.fixture
def mini_font(fixtures_dir):
    return load_metrics(fixtures_dir / "fonts" / "mini-5x7.fmx")


def context_for(locale, panel, font):
    return RuleContext(locale=resolve(locale), panel=get_panel(panel), font=font)


def run(rule, context, source, target):
    message = Message(key="k.1", source_text=source)
    translation = Translation(text=target, state=TranslationState.APPROVED)
    return list(rule.check(message, translation, context))


def test_unencodable_finds_what_cp1252_drops():
    assert unencodable("Auflösung", 1252) == []
    assert unencodable("Çözünürlük", 1252) == ["ö"] or unencodable("Çözünürlük", 1252) == []


def test_unencodable_on_turkish_in_cp1252():
    # The dotless i is the classic one.
    assert unencodable("Yazıcı", 1252) == ["ı"]


def test_unencodable_on_chinese_in_cp1252():
    assert unencodable("刪除", 1252) == ["刪", "除"]


def test_unencodable_dedupes():
    assert unencodable("刪刪刪", 1252) == ["刪"]


def test_unencodable_in_big5():
    assert unencodable("刪除", 950) == []


def test_an_unknown_codepage_reports_everything():
    assert unencodable("ab", 99999) == ["a", "b"]


def test_glyphs_pass_for_a_covered_string(tahoma):
    context = context_for("de-DE", "tij-800x600", tahoma)
    assert run(GlyphRule(), context, "Resolution", "Druckerauflösung") == []


def test_glyphs_fail_for_an_uncovered_character(mini_font):
    context = context_for("de-DE", "mini-20x4", mini_font)
    findings = run(GlyphRule(), context, "Resolution", "Auflösung")
    assert len(findings) == 1
    assert "'ö' is not in the Mini 5x7 font" in findings[0].summary
    assert "U+00F6" in findings[0].detail


def test_several_uncovered_characters_are_listed(mini_font):
    context = context_for("de-DE", "mini-20x4", mini_font)
    findings = run(GlyphRule(), context, "x", "Größe Prüfung")
    assert "'ö', 'ß', 'ü' are" in findings[0].summary


def test_a_long_run_of_missing_characters_is_summarised(mini_font):
    context = context_for("zh-TW", "mini-20x4", mini_font)
    findings = run(GlyphRule(), context, "x", "條形碼數據列表預覽時間")
    assert "more are" in findings[0].summary


def test_mnemonic_markers_are_not_checked_for_coverage(mini_font):
    # The & is never drawn, so it does not matter whether the font holds it.
    context = context_for("de-DE", "mini-20x4", mini_font)
    assert run(GlyphRule(), context, "&Print", "&Drucken") == []


def test_an_empty_translation_is_skipped(mini_font):
    context = context_for("de-DE", "mini-20x4", mini_font)
    assert run(GlyphRule(), context, "Resolution", "") == []


def test_encoding_passes_on_a_unicode_panel(tahoma):
    context = context_for("zh-TW", "tij-800x600", tahoma)
    assert run(EncodingRule(), context, "Delete", "刪除") == []


def test_encoding_fails_for_a_character_outside_the_codepage():
    context = context_for("tr-TR", "mini-20x4", monospace(6, ranges=[(0x20, 0x2FFF)]))
    findings = run(EncodingRule(), context, "Printer", "Yazıcı")
    assert len(findings) == 1
    assert "codepage 1252" in findings[0].summary
    assert "8-bit" in findings[0].detail


def test_encoding_passes_for_german_in_cp1252():
    context = context_for("de-DE", "mini-20x4", monospace(6, ranges=[(0x20, 0x2FFF)]))
    assert run(EncodingRule(), context, "Resolution", "Auflösung") == []


def test_a_double_byte_language_on_a_single_byte_panel():
    context = context_for("zh-TW", "mini-20x4", monospace(6, ranges=[(0x20, 0x9FFF)]))
    findings = run(EncodingRule(), context, "Delete", "刪除")
    assert len(findings) == 1
    assert "cannot be shown on mini-20x4 at all" in findings[0].summary
    assert "single byte character path" in findings[0].detail


def test_the_dbcs_message_replaces_the_codepage_one():
    # Reporting both would suggest the string can be fixed. It cannot.
    context = context_for("ja-JP", "mini-oled-128x64", monospace(6, ranges=[(0x20, 0x9FFF)]))
    findings = run(EncodingRule(), context, "Delete", "削除")
    assert len(findings) == 1
    assert "cannot be shown" in findings[0].summary


def test_encoding_of_an_empty_translation_is_skipped():
    context = context_for("tr-TR", "mini-20x4", monospace(6))
    assert run(EncodingRule(), context, "Printer", "") == []


def test_rule_names():
    assert GlyphRule.name == "glyphs"
    assert EncodingRule.name == "encoding"
