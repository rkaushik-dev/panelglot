"""Locale identity, and the three different names every language has here.

A language shows up under three names in this pipeline and none of them match:

* the workbook column heading a translator was given, which is whatever the
  person who made the sheet felt like typing ("Taiwan", "German");
* the BCP-47 tag we want to key the catalog on ("zh-TW", "de-DE");
* the Win32 ``LANGUAGE`` statement and codepage the ``.rc`` writer has to emit
  (``LANG_CHINESE, SUBLANG_CHINESE_TRADITIONAL`` at codepage 950).

This module is the one place that knows all three, so nothing else has to
guess. The codepage matters more than it looks: the HMI still compiles its
resources as 8-bit for the older TIJ boards, and a string that will not encode
in the target codepage is a box on the panel, not an exception at build time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ConfigError

__all__ = [
    "Locale",
    "LOCALES",
    "canonical_tag",
    "lookup",
    "resolve",
    "known_tags",
]


@dataclass(frozen=True)
class Locale:
    """Everything the pipeline needs to know about one target language."""

    tag: str
    """BCP-47 tag, canonically cased: ``zh-TW``, ``de-DE``."""

    english_name: str
    """Name used in logs and reports."""

    win32_language: str
    """``LANG_*`` constant for the ``.rc`` ``LANGUAGE`` statement."""

    win32_sublanguage: str
    """``SUBLANG_*`` constant paired with it."""

    lcid: int
    """Win32 locale identifier, used for the ``#pragma code_page`` block id."""

    codepage: int
    """ANSI codepage the legacy 8-bit resource build encodes with."""

    rtl: bool = False
    """Right to left script. Changes control mirroring, not just the text."""

    double_byte: bool = False
    """Needs a DBCS-capable panel font. The 5x7 bitmap fonts cannot serve these."""

    aliases: tuple[str, ...] = field(default_factory=tuple)
    """Column headings and folder names seen in the wild for this language."""

    @property
    def python_codec(self) -> str:
        """Codec name for :func:`str.encode`, derived from the codepage."""
        return f"cp{self.codepage}"

    @property
    def language_statement(self) -> str:
        """The literal line the ``.rc`` writer puts above a localised block."""
        return f"LANGUAGE {self.win32_language}, {self.win32_sublanguage}"


LOCALES: tuple[Locale, ...] = (
    Locale(
        tag="en-US",
        english_name="English (United States)",
        win32_language="LANG_ENGLISH",
        win32_sublanguage="SUBLANG_ENGLISH_US",
        lcid=0x0409,
        codepage=1252,
        aliases=("english", "en", "eng", "source"),
    ),
    Locale(
        tag="de-DE",
        english_name="German",
        win32_language="LANG_GERMAN",
        win32_sublanguage="SUBLANG_GERMAN",
        lcid=0x0407,
        codepage=1252,
        aliases=("german", "de", "deu", "ger", "deutsch"),
    ),
    Locale(
        tag="zh-TW",
        english_name="Chinese (Traditional)",
        win32_language="LANG_CHINESE",
        win32_sublanguage="SUBLANG_CHINESE_TRADITIONAL",
        lcid=0x0404,
        codepage=950,
        double_byte=True,
        aliases=("taiwan", "traditional chinese", "chinese traditional", "zh-tw", "cht", "big5"),
    ),
    Locale(
        tag="zh-CN",
        english_name="Chinese (Simplified)",
        win32_language="LANG_CHINESE",
        win32_sublanguage="SUBLANG_CHINESE_SIMPLIFIED",
        lcid=0x0804,
        codepage=936,
        double_byte=True,
        aliases=("china", "simplified chinese", "chinese simplified", "zh-cn", "chs", "gbk"),
    ),
    Locale(
        tag="fr-FR",
        english_name="French",
        win32_language="LANG_FRENCH",
        win32_sublanguage="SUBLANG_FRENCH",
        lcid=0x040C,
        codepage=1252,
        aliases=("french", "fr", "fra", "francais"),
    ),
    Locale(
        tag="es-ES",
        english_name="Spanish",
        win32_language="LANG_SPANISH",
        win32_sublanguage="SUBLANG_SPANISH_MODERN",
        lcid=0x0C0A,
        codepage=1252,
        aliases=("spanish", "es", "esp", "espanol"),
    ),
    Locale(
        tag="it-IT",
        english_name="Italian",
        win32_language="LANG_ITALIAN",
        win32_sublanguage="SUBLANG_ITALIAN",
        lcid=0x0410,
        codepage=1252,
        aliases=("italian", "it", "ita"),
    ),
    Locale(
        tag="pt-BR",
        english_name="Portuguese (Brazil)",
        win32_language="LANG_PORTUGUESE",
        win32_sublanguage="SUBLANG_PORTUGUESE_BRAZILIAN",
        lcid=0x0416,
        codepage=1252,
        aliases=("portuguese", "brazil", "pt", "pt-br", "ptb"),
    ),
    Locale(
        tag="ru-RU",
        english_name="Russian",
        win32_language="LANG_RUSSIAN",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x0419,
        codepage=1251,
        aliases=("russian", "ru", "rus"),
    ),
    Locale(
        tag="tr-TR",
        english_name="Turkish",
        win32_language="LANG_TURKISH",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x041F,
        codepage=1254,
        aliases=("turkish", "tr", "tur"),
    ),
    Locale(
        tag="pl-PL",
        english_name="Polish",
        win32_language="LANG_POLISH",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x0415,
        codepage=1250,
        aliases=("polish", "pl", "pol"),
    ),
    Locale(
        tag="cs-CZ",
        english_name="Czech",
        win32_language="LANG_CZECH",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x0405,
        codepage=1250,
        aliases=("czech", "cs", "cze", "ces"),
    ),
    Locale(
        tag="ko-KR",
        english_name="Korean",
        win32_language="LANG_KOREAN",
        win32_sublanguage="SUBLANG_KOREAN",
        lcid=0x0412,
        codepage=949,
        double_byte=True,
        aliases=("korean", "korea", "ko", "kor"),
    ),
    Locale(
        tag="ja-JP",
        english_name="Japanese",
        win32_language="LANG_JAPANESE",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x0411,
        codepage=932,
        double_byte=True,
        aliases=("japanese", "japan", "ja", "jpn"),
    ),
    Locale(
        tag="th-TH",
        english_name="Thai",
        win32_language="LANG_THAI",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x041E,
        codepage=874,
        aliases=("thai", "th", "tha"),
    ),
    Locale(
        tag="vi-VN",
        english_name="Vietnamese",
        win32_language="LANG_VIETNAMESE",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x042A,
        codepage=1258,
        aliases=("vietnamese", "vietnam", "vi", "vie"),
    ),
    Locale(
        tag="ar-SA",
        english_name="Arabic (Saudi Arabia)",
        win32_language="LANG_ARABIC",
        win32_sublanguage="SUBLANG_ARABIC_SAUDI_ARABIA",
        lcid=0x0401,
        codepage=1256,
        rtl=True,
        aliases=("arabic", "ar", "ara"),
    ),
    Locale(
        tag="he-IL",
        english_name="Hebrew",
        win32_language="LANG_HEBREW",
        win32_sublanguage="SUBLANG_DEFAULT",
        lcid=0x040D,
        codepage=1255,
        rtl=True,
        aliases=("hebrew", "he", "heb", "iw"),
    ),
)


_BY_TAG: dict[str, Locale] = {}
_BY_ALIAS: dict[str, Locale] = {}

for _locale in LOCALES:
    _BY_TAG[_locale.tag.lower()] = _locale
    _BY_ALIAS[_locale.tag.lower()] = _locale
    _BY_ALIAS[_locale.english_name.lower()] = _locale
    for _alias in _locale.aliases:
        _BY_ALIAS[_alias.lower()] = _locale

del _locale


def canonical_tag(text: str) -> str:
    """Normalise ``zh_tw`` / ``ZH-TW`` / ``zh tw`` to ``zh-TW``.

    Does not check the tag is one we know about, only that it is shaped like a
    tag. Region subtags go upper, script subtags go title, everything else
    goes lower, which is what BCP-47 asks for.
    """
    parts = [p for p in text.strip().replace("_", "-").replace(" ", "-").split("-") if p]
    if not parts:
        raise ConfigError("empty locale tag")

    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4:
            out.append(part.title())
        elif len(part) in (2, 3):
            out.append(part.upper())
        else:
            out.append(part.lower())
    return "-".join(out)


def lookup(name: str) -> Locale | None:
    """Find a locale by tag, English name or any known alias. ``None`` if unknown."""
    key = name.strip().lower().replace("_", "-")
    hit = _BY_ALIAS.get(key)
    if hit is not None:
        return hit
    # "Chinese (Traditional)" and "chinese traditional" should both land.
    squashed = key.replace("(", " ").replace(")", " ")
    squashed = " ".join(squashed.split())
    return _BY_ALIAS.get(squashed)


def resolve(name: str) -> Locale:
    """Like :func:`lookup` but raises :class:`ConfigError` instead of returning ``None``."""
    hit = lookup(name)
    if hit is None:
        raise ConfigError(
            f"unknown locale {name!r}. Known tags: {', '.join(known_tags())}"
        )
    return hit


def known_tags() -> list[str]:
    """Every tag this build understands, in declaration order."""
    return [loc.tag for loc in LOCALES]
