"""The measurement cache, and that it cannot go stale in a way that matters.

A cache that returns a wrong width is worse than no cache: it makes the
fitting check confidently wrong, which is the failure mode the whole layout
package exists to avoid. These tests are about that rather than about speed.
"""

from __future__ import annotations

import pytest

from v4t_translate.layout.font import (
    MEASURE_CACHE_LIMIT,
    FontMetrics,
    load_metrics,
    monospace,
    parse_metrics,
)
from v4t_translate.layout.measure import wrap


@pytest.fixture
def font():
    return monospace(6, ranges=[(0x20, 0x7E)])


def test_the_same_answer_twice(font):
    assert font.measure("Bar Height") == font.measure("Bar Height")


def test_the_second_call_comes_from_the_cache(font):
    font.measure("Bar Height")
    assert "Bar Height" in font._measured


def test_two_fonts_do_not_share_a_cache():
    narrow = monospace(4, ranges=[(0x20, 0x7E)])
    wide = monospace(9, ranges=[(0x20, 0x7E)])

    assert narrow.measure("abc") == 12
    assert wide.measure("abc") == 27


def test_the_cache_is_bounded(font):
    for index in range(MEASURE_CACHE_LIMIT + 10):
        font.measure(f"string number {index}")
    assert len(font._measured) <= MEASURE_CACHE_LIMIT


def test_a_bounded_cache_still_answers_correctly(font):
    for index in range(MEASURE_CACHE_LIMIT + 10):
        font.measure(f"string number {index}")
    assert font.measure("abc") == 18


def test_invalidate_forgets(font):
    font.measure("abc")
    font.invalidate()
    assert font._measured == {}


def test_a_changed_font_gives_the_new_answer_after_invalidate():
    font = parse_metrics("name: X\ndefault_width: 4\n41..5A 4\n")
    assert font.measure("AB") == 8

    font.widths[ord("A")] = 10
    font.invalidate()
    assert font.measure("AB") == 14


def test_the_cache_is_not_part_of_equality():
    first = monospace(6, ranges=[(0x20, 0x7E)])
    second = monospace(6, ranges=[(0x20, 0x7E)])
    first.measure("abc")
    assert first == second


def test_the_cache_is_not_in_the_repr(font):
    font.measure("abc")
    assert "_measured" not in repr(font)


def test_a_freshly_parsed_font_starts_empty():
    assert parse_metrics("name: X\ndefault_width: 4\n41 4\n")._measured == {}


def test_a_loaded_font_starts_empty(fixtures_dir):
    metrics = load_metrics(fixtures_dir / "fonts" / "tahoma-8.fmx")
    assert metrics._measured == {}


def test_wrapping_uses_the_cache(font):
    wrap("Print started now and again", font, 60)
    # Wrapping measures each chunk and each partial line, so the cache holds
    # more than the one whole string.
    assert len(font._measured) > 1


def test_wrapping_is_the_same_with_a_warm_cache(font):
    text = "This distance cannot be greater than print spacing"
    cold = wrap(text, font, 90)

    warm_font = monospace(6, ranges=[(0x20, 0x7E)])
    for word in text.split():
        warm_font.measure(word)

    assert wrap(text, warm_font, 90) == cold


def test_a_default_constructed_font_has_a_cache():
    assert FontMetrics()._measured == {}


def test_measuring_the_empty_string(font):
    assert font.measure("") == 0
    assert font.measure("") == 0


def test_newlines_are_still_ignored_when_cached(font):
    assert font.measure("ab\ncd") == font.measure("abcd")
