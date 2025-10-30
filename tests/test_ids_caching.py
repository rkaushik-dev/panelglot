import shutil
import time

import pytest

from v4t_translate.catalog.ids import (
    CACHE_LIMIT,
    cache_info,
    clear_caches,
    message_key,
    normalize_source,
    slugify,
    source_fingerprint,
)
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog, save_catalog, save_translations
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.config import load_config
from v4t_translate.ops.check import check_project
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]
"""

#: How many messages the scale test builds. Bigger than the whole product
#: family, so a change that is quadratic in catalog size shows up here rather
#: than on somebody's afternoon.
SCALE = 4000


@pytest.fixture(autouse=True)
def fresh():
    """Every test starts from a known cache state."""
    clear_caches()
    yield
    clear_caches()


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def big_catalog(config, count=SCALE):
    """A catalog the size of a much larger product, with answers for it."""
    catalog = Catalog(project="V4T-TIJ")
    german = TranslationSet(locale="de-DE")
    chinese = TranslationSet(locale="zh-TW")

    for number in range(count):
        text = f"Message number {number} on the offsets page"
        key = message_key(text)
        catalog.add(Message(
            key=key,
            source_text=text,
            max_width_px=200,
            origins=[Origin(source="src/V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                            container=f"IDD_{number // 40}", symbol="IDC_STATIC",
                            line=number, ordinal=number % 40)],
        ))
        german.set(key, Translation().with_text(
            f"Nachricht Nummer {number}", source_text=text,
            state=TranslationState.APPROVED))
        chinese.set(key, Translation().with_text(
            f"Meldung {number}", source_text=text,
            state=TranslationState.APPROVED))

    save_catalog(config.catalog_path(), catalog)
    save_translations(config.translations_path("de-DE"), german)
    save_translations(config.translations_path("zh-TW"), chinese)
    return catalog


# -- the caches ---------------------------------------------------------


def test_the_same_string_is_only_hashed_once():
    message_key("Bar Height")
    message_key("Bar Height")
    assert cache_info()["message_key"] == (1, 1)


def test_a_different_string_is_a_miss():
    message_key("Bar Height")
    message_key("Width")
    assert cache_info()["message_key"][1] == 2


def test_the_context_is_part_of_the_key():
    assert message_key("Print") != message_key("Print", "verb")
    assert cache_info()["message_key"][1] == 2


def test_all_four_functions_are_cached():
    assert set(cache_info()) == {
        "normalize_source", "slugify", "message_key", "source_fingerprint"
    }


def test_clearing_forgets_everything():
    message_key("Bar Height")
    clear_caches()
    assert cache_info()["message_key"] == (0, 0)


def test_the_caches_are_bounded():
    # A pseudo run produces a distinct string per message, and an unbounded
    # cache would hold the whole catalog twice for no benefit.
    for number in range(CACHE_LIMIT + 500):
        message_key(f"string {number}")
    assert message_key.cache_info().currsize <= CACHE_LIMIT


def test_caching_does_not_change_any_answer():
    first = [message_key(t) for t in ("Bar Height", "&Print", "Pen")]
    clear_caches()
    second = [message_key(t) for t in ("Bar Height", "&Print", "Pen")]
    assert first == second


def test_the_normaliser_still_normalises():
    assert normalize_source("a\r\nb") == "a\nb"
    assert normalize_source("a\r\nb") == "a\nb"


def test_the_slugger_still_slugs():
    assert slugify("&Print Settings") == "print-settings"
    assert slugify("&Print Settings") == "print-settings"


def test_the_fingerprint_is_stable_across_a_clear():
    first = source_fingerprint("Bar Height")
    clear_caches()
    assert source_fingerprint("Bar Height") == first


# -- at scale -----------------------------------------------------------


def test_a_large_catalog_extracts_and_checks(project):
    big_catalog(project)
    result = check_project(project, locales=["de-DE"])
    assert result.report.checked == SCALE


def test_the_check_reuses_its_keys(project):
    big_catalog(project)
    clear_caches()
    check_project(project, locales=["de-DE", "zh-TW"])

    hits, misses = cache_info()["source_fingerprint"]
    # Two languages over one catalog: every English string is fingerprinted on
    # the first pass and found on the second. Near zero hits would mean
    # something is building a fresh string each time round.
    assert hits >= misses


def test_a_large_check_finishes_in_a_reasonable_time(project):
    # Not a benchmark, a tripwire. It has ten seconds for four thousand
    # messages across two languages, and the real figure on this machine is
    # well under two. It fires on a change that is quadratic in catalog size,
    # which is the class of mistake that is invisible on the sample and fatal
    # on a real project.
    big_catalog(project)

    started = time.monotonic()
    check_project(project, locales=["de-DE", "zh-TW"])
    assert time.monotonic() - started < 10.0


def test_the_cache_does_not_grow_without_bound_during_a_check(project):
    big_catalog(project)
    clear_caches()
    check_project(project, locales=["de-DE"])
    assert message_key.cache_info().currsize <= CACHE_LIMIT
