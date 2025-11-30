"""How many plural forms a language needs.

English has two and so does German, so the Android resources were written with
two and nobody looked again. Polish needs three, Arabic needs six, and Chinese
needs one. A ``<plurals>`` that carries ``one`` and ``other`` in Polish is not
a translation with a gap in it: the platform picks ``other`` for two, three and
four, and the panel says the Polish equivalent of "5 pens" for two pens.

The categories are CLDR's and the names are the ones Android uses, because
Android is what reads them. Only the languages this product ships are listed.
A full CLDR table would be four hundred lines of data nobody here can check,
and the eleven that matter can be checked by asking the distributor.

``other`` is required everywhere, including in the languages that need nothing
else. Android falls back to it and a resource without one is a resource that
can fail to resolve at run time.
"""

from __future__ import annotations

__all__ = ["CATEGORIES", "categories_for", "missing_categories", "extra_categories"]

#: Every category Android accepts, in the order it writes them.
CATEGORIES: tuple[str, ...] = ("zero", "one", "two", "few", "many", "other")

#: Language subtag to the categories that language actually distinguishes.
#: Keyed on the language rather than the full tag: no product here ships two
#: regions of one language that count differently, and pt-BR against pt-PT is
#: the pair that would, if it ever came up.
_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    # One form. The count is written and the noun does not change.
    "zh": ("other",),
    "ja": ("other",),
    "ko": ("other",),
    "th": ("other",),
    "vi": ("other",),
    "id": ("other",),
    "tr": ("one", "other"),

    # Two, the English pattern.
    "en": ("one", "other"),
    "de": ("one", "other"),
    "nl": ("one", "other"),
    "sv": ("one", "other"),
    "da": ("one", "other"),
    "no": ("one", "other"),
    "fi": ("one", "other"),
    "hu": ("one", "other"),
    "it": ("one", "other"),
    "es": ("one", "other"),
    "el": ("one", "other"),
    "he": ("one", "two", "many", "other"),

    # French counts zero and one together, which is the one that surprises
    # people: "0 stylo" and not "0 stylos".
    "fr": ("one", "many", "other"),
    "pt": ("one", "many", "other"),

    # Slavic.
    "pl": ("one", "few", "many", "other"),
    "ru": ("one", "few", "many", "other"),
    "cs": ("one", "few", "many", "other"),

    # Romanian has a "few" for 0 and for 20 through 99.
    "ro": ("one", "few", "other"),

    # Arabic uses all six.
    "ar": ("zero", "one", "two", "few", "many", "other"),
}

#: What a language nobody has listed gets. Two forms, because that is what the
#: English resources were written with, and because guessing more would put
#: empty items in front of a translator for categories their language may not
#: have.
_DEFAULT: tuple[str, ...] = ("one", "other")


def categories_for(tag: str) -> tuple[str, ...]:
    """The plural categories ``tag`` needs, in Android's order."""
    language = tag.replace("_", "-").split("-")[0].lower()
    return _BY_LANGUAGE.get(language, _DEFAULT)


def missing_categories(tag: str, present: set[str] | list[str]) -> list[str]:
    """Categories this language needs that are not there."""
    have = {name.lower() for name in present}
    return [name for name in categories_for(tag) if name not in have]


def extra_categories(tag: str, present: set[str] | list[str]) -> list[str]:
    """Categories that are there and that this language does not use.

    Reported rather than dropped. An extra item is harmless to the platform,
    which simply never selects it, but it is somebody's paid work sitting in a
    file doing nothing, and they should be told before they translate the next
    one.
    """
    needed = set(categories_for(tag))
    return [name for name in CATEGORIES
            if name in {n.lower() for n in present} and name not in needed]
