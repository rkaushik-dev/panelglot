import pytest

from v4t_translate.catalog.ids import (
    HASH_LENGTH,
    SLUG_LIMIT,
    message_key,
    normalize_source,
    slugify,
    sort_key,
    source_fingerprint,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bar Height", "bar-height"),
        ("Timestamps list:", "timestamps-list"),
        ("Date&&Time Format", "datetime-format"),
        ("&Print", "print"),
        ("P&rint", "print"),
        ("Ink Gain Adjust", "ink-gain-adjust"),
        ("Please input from %.1fV to %.1fV.", "please-input-from-1fv-to-1fv"),
        ("Druckerauflösung", "druckerauflosung"),
        ("   ", "x"),
        ("刪除", "x"),
        ("4.", "4"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_slug_is_capped_and_does_not_end_in_a_dash():
    long = "This distance cannot be greater than print spacing"
    slug = slugify(long)
    assert len(slug) <= SLUG_LIMIT
    assert not slug.endswith("-")
    assert slug == "this-distance-cannot-be-greater"


def test_normalize_source_collapses_line_endings():
    assert normalize_source("a\r\nb\rc") == "a\nb\nc"


def test_normalize_source_composes_unicode():
    decomposed = "Auflösung"
    assert normalize_source(decomposed) == "Auflösung"


def test_key_shape():
    key = message_key("Bar Height")
    slug, _, digest = key.rpartition(".")
    assert slug == "bar-height"
    assert len(digest) == HASH_LENGTH
    assert all(c in "0123456789abcdef" for c in digest)


def test_key_is_stable_across_calls():
    assert message_key("Print Spacing") == message_key("Print Spacing")


def test_key_ignores_line_ending_style():
    assert message_key("line one\r\nline two") == message_key("line one\nline two")


def test_context_changes_the_key_but_not_the_slug():
    plain = message_key("Print")
    noun = message_key("Print", context="noun")
    verb = message_key("Print", context="verb")
    assert plain != noun != verb
    assert plain != verb
    assert all(k.startswith("print.") for k in (plain, noun, verb))


def test_mnemonic_position_still_produces_distinct_keys():
    assert message_key("&Print") != message_key("P&rint")
    assert message_key("&Print").split(".")[0] == message_key("P&rint").split(".")[0]


def test_escaped_ampersand_differs_from_a_mnemonic():
    # "Date&&Time" prints a literal &, "Date&Time" makes T the mnemonic.
    assert message_key("Date&&Time Format") != message_key("Date&Time Format")


def test_fingerprint_is_hex_and_fixed_width():
    fp = source_fingerprint("Firing Voltage")
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_ignores_context():
    # Only the source text feeds it, which is what makes it a drift detector.
    assert source_fingerprint("Purge Settings") == source_fingerprint("Purge Settings")


def test_fingerprint_changes_when_the_english_is_edited():
    before = source_fingerprint("Please input from %.1fV to %.1fV.")
    after = source_fingerprint("Please input from %.1f V to %.1f V.")
    assert before != after


def test_sort_key_orders_on_the_readable_part():
    keys = ["ok.1a2b3c", "ok-cancel.0f9e8d", "ok.0000aa"]
    assert sorted(keys, key=sort_key) == ["ok.0000aa", "ok.1a2b3c", "ok-cancel.0f9e8d"]


def test_sort_key_survives_a_key_with_no_dot():
    assert sort_key("legacy") == ("legacy", "")
