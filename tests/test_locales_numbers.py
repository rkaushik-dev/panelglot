import pytest

from v4t_translate.locales import LOCALES, NBSP, resolve


def test_the_language_subtag():
    assert resolve("de-DE").language == "de"
    assert resolve("zh-TW").language == "zh"


def test_every_locale_has_a_decimal_separator():
    for locale in LOCALES:
        assert locale.decimal_separator
        assert len(locale.decimal_separator) == 1


def test_the_group_separator_is_never_the_decimal_one():
    for locale in LOCALES:
        if locale.group_separator:
            assert locale.group_separator != locale.decimal_separator


@pytest.mark.parametrize(
    ("tag", "decimal", "group"),
    [
        ("en-US", ".", ","),
        ("de-DE", ",", "."),
        ("fr-FR", ",", NBSP),
        ("zh-TW", ".", ","),
        ("tr-TR", ",", "."),
        ("ru-RU", ",", NBSP),
        ("sv-SE", ",", NBSP),
        ("nl-NL", ",", "."),
    ],
)
def test_separators(tag, decimal, group):
    locale = resolve(tag)
    assert locale.decimal_separator == decimal
    assert locale.group_separator == group


def test_arabic_uses_the_western_marks():
    # U+066B and U+066C are the Arabic ones and neither is in cp1256, so the
    # 8-bit build cannot carry them.
    locale = resolve("ar-SA")
    assert locale.decimal_separator == "."
    assert locale.group_separator == ","
    with pytest.raises(UnicodeEncodeError):
        "٫".encode("cp1256")


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("en-US", "12.4"),
        ("de-DE", "12,4"),
        ("fr-FR", "12,4"),
        ("zh-TW", "12.4"),
    ],
)
def test_format_a_voltage(tag, expected):
    assert resolve(tag).format_number(12.4) == expected


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("en-US", "1,250"),
        ("de-DE", "1.250"),
        ("fr-FR", f"1{NBSP}250"),
        ("sv-SE", f"1{NBSP}250"),
    ],
)
def test_format_a_grouped_number(tag, expected):
    assert resolve(tag).format_number(1250, decimals=0) == expected


def test_format_a_negative_number():
    assert resolve("de-DE").format_number(-12.4) == "-12,4"


def test_format_with_more_decimals():
    assert resolve("de-DE").format_number(12.456, decimals=3) == "12,456"


def test_format_with_no_decimals_has_no_separator():
    assert resolve("de-DE").format_number(12, decimals=0) == "12"


def test_format_of_a_large_grouped_decimal():
    assert resolve("de-DE").format_number(1234567.8) == "1.234.567,8"


def test_the_group_separator_is_the_non_breaking_space():
    # A plain space would let a number wrap across two lines on a panel that
    # is already too narrow.
    assert NBSP == " "
    assert resolve("fr-FR").group_separator == " "


def test_the_new_languages_are_there():
    tags = {locale.tag for locale in LOCALES}
    assert {"nl-NL", "sv-SE", "da-DK", "nb-NO", "fi-FI", "hu-HU", "ro-RO",
            "el-GR"} <= tags


def test_the_new_languages_resolve_by_name():
    for name, tag in (("Dutch", "nl-NL"), ("Swedish", "sv-SE"), ("Danish", "da-DK"),
                      ("Norwegian", "nb-NO"), ("Finnish", "fi-FI"),
                      ("Hungarian", "hu-HU"), ("Romanian", "ro-RO"),
                      ("Greek", "el-GR")):
        assert resolve(name).tag == tag


def test_the_new_languages_have_a_codepage_that_holds_them():
    for tag, sample in (("sv-SE", "Utskriftsavstånd"), ("da-DK", "Udskrivning"),
                        ("fi-FI", "Tulostusväli"), ("hu-HU", "Nyomtatás"),
                        # Romanian with the cedilla forms, not the comma-below
                        # ones. cp1250 has U+0163 and not U+021B, which is the
                        # oldest complaint in Romanian localisation.
                        ("ro-RO", "Distanţă"), ("el-GR", "Εκτύπωση"),
                        ("nl-NL", "Afdrukken"), ("nb-NO", "Utskrift")):
        locale = resolve(tag)
        assert sample.encode(locale.python_codec)


def test_every_group_separator_survives_its_own_codepage():
    for locale in LOCALES:
        if locale.group_separator:
            locale.group_separator.encode(locale.python_codec)
        locale.decimal_separator.encode(locale.python_codec)
