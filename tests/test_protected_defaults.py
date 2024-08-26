"""The old collector carried a hand-written skip list.

It was the only thing standing between the machine translator and strings
like YYYY, and it was maintained by whoever last got burned. Those entries are
now DEFAULT_PROTECTED_PATTERNS, and this test is the receipt: every word that
list used to hold still gets protected, and the printf specifiers it never
covered do too.
"""

import re

import pytest

from v4t_translate.config import DEFAULT_PROTECTED_PATTERNS

# Verbatim from skip_resource_words in the script this replaced.
LEGACY_SKIP_LIST = [
    "0 ms",
    "mm",
    "hh:mm",
    "YY",
    "YYYY",
    "MM",
    "MMM",
    "MMMM",
    "DD",
    "DDD",
    "DDDD",
    "hh",
    "HH",
    "SS",
    "tt",
    "WW",
    "JJJ",
    "UU",
]

# Cases the old list did not cover and which reached translators anyway.
NEWLY_COVERED = [
    "%s",
    "%d",
    "%.1fV",
    "%02d",
    "%-8s",
    "%%",
    "<V1>",
    "<V2>",
    "cm",
    "dpi",
    "Hz",
]

# Real strings from the shipped sheets that must stay translatable.
MUST_STAY_TRANSLATABLE = [
    "Print started",
    "Bar Height",
    "Firing Voltage",
    "Please input from %.1fV to %.1fV.",
    "Value must be between <V1> and <V2>",
    "Pen",
    "Purge Settings",
    "Human Readable",
]


@pytest.fixture(scope="module")
def patterns():
    return [re.compile(p) for p in DEFAULT_PROTECTED_PATTERNS]


def is_protected(patterns, text):
    return any(p.fullmatch(text) for p in patterns)


@pytest.mark.parametrize("word", LEGACY_SKIP_LIST)
def test_every_word_the_old_list_held_is_still_protected(patterns, word):
    if word == "0 ms":
        # The old list held the whole rendered string. The pattern covers the
        # unit, and the number is not a word so extraction drops it anyway.
        word = "ms"
    assert is_protected(patterns, word)


@pytest.mark.parametrize("word", NEWLY_COVERED)
def test_the_cases_the_old_list_missed(patterns, word):
    assert is_protected(patterns, word)


@pytest.mark.parametrize("text", MUST_STAY_TRANSLATABLE)
def test_real_strings_are_not_protected_by_accident(patterns, text):
    assert not is_protected(patterns, text)


def test_every_default_pattern_compiles():
    for pattern in DEFAULT_PROTECTED_PATTERNS:
        re.compile(pattern)


def test_no_default_pattern_matches_the_empty_string(patterns):
    # A pattern that matches nothing would protect every string with an
    # empty-width match if anyone ever switched fullmatch for search.
    assert not is_protected(patterns, "")


def test_the_date_pattern_is_case_sensitive(patterns):
    # MM is a month token, mm is millimetres, and both are protected. But
    # "Mm" is neither and should not be.
    assert not is_protected(patterns, "Mm")
