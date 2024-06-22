import pytest

from v4t_translate.errors import ConfigError
from v4t_translate.locales import (
    LOCALES,
    canonical_tag,
    known_tags,
    lookup,
    resolve,
)


def test_tags_are_unique():
    tags = [loc.tag for loc in LOCALES]
    assert len(tags) == len(set(tags))


def test_lcids_are_unique():
    lcids = [loc.lcid for loc in LOCALES]
    assert len(lcids) == len(set(lcids))


def test_no_alias_is_claimed_twice():
    seen: dict[str, str] = {}
    for loc in LOCALES:
        for alias in loc.aliases:
            assert alias not in seen, f"{alias!r} claimed by {seen.get(alias)} and {loc.tag}"
            seen[alias] = loc.tag


def test_aliases_are_already_lowercase():
    # lookup() lowercases the needle, so an uppercase alias would be dead weight.
    for loc in LOCALES:
        for alias in loc.aliases:
            assert alias == alias.lower()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zh-TW", "zh-TW"),
        ("zh_tw", "zh-TW"),
        ("ZH-TW", "zh-TW"),
        ("zh tw", "zh-TW"),
        ("de", "de"),
        ("sr-Latn-RS", "sr-Latn-RS"),
        ("  en-us  ", "en-US"),
    ],
)
def test_canonical_tag(raw, expected):
    assert canonical_tag(raw) == expected


def test_canonical_tag_rejects_empty():
    with pytest.raises(ConfigError):
        canonical_tag("   ")


def test_the_heading_actually_used_in_the_taiwan_workbook():
    # The shipped sheet says "Taiwan" in B1. That has to resolve.
    assert lookup("Taiwan").tag == "zh-TW"


def test_the_heading_actually_used_in_the_german_workbook():
    assert lookup("German").tag == "de-DE"


@pytest.mark.parametrize(
    ("name", "tag"),
    [
        ("english", "en-US"),
        ("English", "en-US"),
        ("Chinese (Traditional)", "zh-TW"),
        ("chinese traditional", "zh-TW"),
        ("CHS", "zh-CN"),
        ("ptb", "pt-BR"),
        ("iw", "he-IL"),
    ],
)
def test_lookup_accepts_the_names_people_type(name, tag):
    assert lookup(name).tag == tag


def test_lookup_returns_none_for_nonsense():
    assert lookup("Klingon") is None


def test_resolve_raises_and_names_the_alternatives():
    with pytest.raises(ConfigError) as excinfo:
        resolve("Klingon")
    assert "zh-TW" in str(excinfo.value)


def test_double_byte_locales_are_flagged():
    dbcs = {loc.tag for loc in LOCALES if loc.double_byte}
    assert dbcs == {"zh-TW", "zh-CN", "ko-KR", "ja-JP"}


def test_rtl_locales_are_flagged():
    rtl = {loc.tag for loc in LOCALES if loc.rtl}
    assert rtl == {"ar-SA", "he-IL"}


def test_language_statement_shape():
    assert resolve("zh-TW").language_statement == "LANGUAGE LANG_CHINESE, SUBLANG_CHINESE_TRADITIONAL"
    assert resolve("de-DE").language_statement == "LANGUAGE LANG_GERMAN, SUBLANG_GERMAN"


def test_python_codec_round_trips_a_real_string():
    de = resolve("de-DE")
    assert "Druckerauflösung".encode(de.python_codec).decode(de.python_codec) == "Druckerauflösung"


def test_traditional_chinese_encodes_in_big5():
    zh = resolve("zh-TW")
    assert zh.python_codec == "cp950"
    assert "刪除".encode(zh.python_codec)


def test_known_tags_is_stable_and_nonempty():
    tags = known_tags()
    assert tags[0] == "en-US"
    assert len(tags) == len(LOCALES)
