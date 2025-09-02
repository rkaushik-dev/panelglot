import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.mt.memory import TranslationMemory
from v4t_translate.ops.estimate import billable_length, estimate_project
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


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


@pytest.fixture
def memory(tmp_path):
    store = TranslationMemory(tmp_path / "memory.sqlite3")
    yield store
    store.close()


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), "pretranslate", *args,
    ])


def german(config):
    return next(e for e in estimate_project(config).locales if e.tag == "de-DE")


# -- what an engine bills for -------------------------------------------


def test_plain_text_bills_its_own_length():
    assert billable_length("Bar Height") == len("Bar Height")


def test_a_format_string_bills_what_is_posted():
    from v4t_translate.mt.base import protect_placeholders

    text = "Please input from %.1fV to %.1fV."
    protected, _ = protect_placeholders(text)
    assert billable_length(text) == len(protected)


def test_short_placeholders_bill_more_than_the_english():
    # A token is five characters and %s is two, so counting the raw English
    # would undercount the bill on a catalog full of them.
    assert billable_length("%s of %s") > len("%s of %s")


def test_an_empty_string_bills_nothing():
    assert billable_length("") == 0


# -- counting -----------------------------------------------------------


def test_everything_outstanding_is_billable_with_an_empty_memory(project):
    entry = german(project)
    assert entry.outstanding > 0
    assert entry.billable_messages == entry.outstanding
    assert entry.from_memory == 0


def test_an_answered_message_is_not_outstanding(project):
    before = german(project).outstanding

    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Balkenhöhe", state=TranslationState.APPROVED))
    save_translations(path, translations)

    after = german(project)
    assert after.outstanding == before - 1
    assert after.already_answered == 1


def test_a_protected_message_is_never_posted(project):
    assert german(project).protected > 0


def test_a_memory_hit_is_free(project, memory):
    memory.remember("de-DE", "Bar Height", "Balkenhöhe")

    entry = next(e for e in estimate_project(project, memory=memory).locales
                 if e.tag == "de-DE")
    assert entry.from_memory == 1
    assert entry.billable_messages == entry.outstanding - 1


def test_the_saved_fraction(project, memory):
    entry = german(project)
    memory.remember("de-DE", "Bar Height", "Balkenhöhe")
    with_memory = next(e for e in estimate_project(project, memory=memory).locales
                       if e.tag == "de-DE")
    assert with_memory.saved_by_memory == pytest.approx(1 / entry.outstanding)


def test_nothing_outstanding_saves_nothing_and_does_not_divide_by_zero(project):
    from v4t_translate.catalog.store import load_catalog

    catalog = load_catalog(project.catalog_path())
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    for key in catalog.messages:
        translations.set(key, Translation(text="x", state=TranslationState.APPROVED))
    save_translations(path, translations)

    entry = german(project)
    assert entry.outstanding == 0
    assert entry.saved_by_memory == 0.0


def test_characters_are_counted_not_messages(project):
    entry = german(project)
    assert entry.billable_characters > entry.billable_messages


def test_requests_are_batches_rounded_up(project):
    entry = german(project)
    assert entry.requests(1) == entry.billable_messages
    assert entry.requests(1000) == 1


def test_a_batch_size_of_zero_does_not_divide_by_zero(project):
    assert german(project).requests(0) == german(project).billable_messages


def test_every_language_is_counted(project):
    result = estimate_project(project)
    assert {e.tag for e in result.locales} == {"de-DE", "zh-TW"}


def test_one_language_can_be_asked_for(project):
    result = estimate_project(project, locales=["de-DE"])
    assert [e.tag for e in result.locales] == ["de-DE"]


def test_the_totals_add_up(project):
    result = estimate_project(project)
    assert result.billable_characters == sum(
        e.billable_characters for e in result.locales
    )
    assert result.requests == sum(e.requests(result.batch_size)
                                  for e in result.locales)


# -- money --------------------------------------------------------------


def test_the_cost_is_characters_over_a_million(project):
    result = estimate_project(project)
    assert result.cost(20.0) == pytest.approx(
        result.billable_characters / 1_000_000 * 20.0
    )


def test_a_rate_of_zero_costs_nothing(project):
    assert estimate_project(project).cost(0.0) == 0.0


# -- the command --------------------------------------------------------


def test_estimate_reports_every_language(project):
    output = run(project, "--estimate").output
    assert "de-DE" in output
    assert "zh-TW" in output


def test_estimate_names_the_characters(project):
    assert "characters" in run(project, "--estimate").output


def test_estimate_takes_one_language(project):
    output = run(project, "de-DE", "--estimate").output
    assert "de-DE" in output
    assert "zh-TW" not in output


def test_estimate_writes_nothing(project):
    before = project.translations_path("de-DE").read_bytes()
    run(project, "--estimate")
    assert project.translations_path("de-DE").read_bytes() == before


def test_a_rate_turns_it_into_money(project):
    assert "per million characters" in run(project, "--estimate",
                                           "--rate", "20").output


def test_no_rate_means_no_money(project):
    assert "per million" not in run(project, "--estimate").output


def test_pretranslate_still_needs_a_language(project):
    result = run(project)
    assert result.exit_code != 0
    assert "which language" in result.output


def test_pretranslate_with_a_language_still_runs(project):
    result = run(project, "de-DE", "--dry-run")
    assert result.exit_code == 0
    assert "de-DE:" in result.output
