import json
import os
import shutil
import time
from datetime import date

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.status import Readiness, project_status

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


def approve_everything(config, tag, *, state=TranslationState.APPROVED):
    from v4t_translate.catalog.store import load_catalog

    catalog = load_catalog(config.catalog_path())
    path = config.translations_path(tag)
    translations = load_translations(path)
    for key, message in catalog.messages.items():
        translations.set(
            key,
            Translation().with_text(f"[{message.source_text}]",
                                    source_text=message.source_text, state=state),
        )
    save_translations(path, translations)


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), "status", *args,
    ])


# -- the verdict --------------------------------------------------------


def test_a_fresh_project_is_not_shippable(project):
    result = project_status(project)
    assert not result.can_ship
    assert "not shippable" in result.verdict()


def test_a_language_with_nothing_approved_is_unstarted(project):
    entry = project_status(project).locales[0]
    assert entry.readiness is Readiness.UNSTARTED


def test_unstarted_languages_are_named_apart_from_blocked_ones(project):
    # Both stop a release. They are separated because who you go and talk to
    # is different: one is a translator running late, the other is a language
    # nobody has commissioned yet.
    result = project_status(project)
    assert result.blocked == []
    assert "not started" in result.verdict()


def test_a_partly_done_language_is_blocked(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Balkenhöhe", state=TranslationState.APPROVED))
    save_translations(path, translations)

    entry = next(e for e in project_status(project).locales if e.tag == "de-DE")
    assert entry.readiness is Readiness.BLOCKED


def test_a_finished_language_is_ready(project):
    approve_everything(project, "de-DE")
    entry = next(e for e in project_status(project).locales if e.tag == "de-DE")
    assert entry.readiness is Readiness.READY
    assert entry.blocking == 0


def test_everything_approved_is_shippable(project):
    approve_everything(project, "de-DE")
    approve_everything(project, "zh-TW")
    result = project_status(project)
    assert result.can_ship
    assert result.verdict() == "shippable: all 2 languages approved"


def test_a_stale_translation_blocks(project):
    from v4t_translate.catalog.store import load_catalog, save_catalog

    approve_everything(project, "de-DE")
    approve_everything(project, "zh-TW")

    # Edit the English underneath one approved translation.
    catalog = load_catalog(project.catalog_path())
    key = next(iter(catalog.messages))
    catalog.messages[key].source_text += " now"
    save_catalog(project.catalog_path(), catalog)

    entry = next(e for e in project_status(project).locales if e.tag == "de-DE")
    assert entry.readiness is Readiness.STALE
    assert entry.stale == 1


def test_the_verdict_names_the_blocked_languages(project):
    approve_everything(project, "de-DE")
    path = project.translations_path("zh-TW")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="條碼高度", state=TranslationState.APPROVED))
    save_translations(path, translations)

    verdict = project_status(project).verdict()
    assert "zh-TW" in verdict
    assert "de-DE" not in verdict


def test_a_project_with_no_catalog_says_so(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")

    result = project_status(config)
    assert not result.can_ship
    assert any("Run extract" in note for note in result.notes)
    assert result.locales == []


# -- freshness ----------------------------------------------------------


def test_a_source_edited_after_extract_is_named(project):
    source = project.root / "src" / "V4T.rc"
    stamp = time.time() + 10
    os.utime(source, (stamp, stamp))

    result = project_status(project)
    assert result.catalog_is_stale
    assert result.stale_sources == ["src/V4T.rc"]
    assert "src/V4T.rc" in result.verdict()


def test_a_stale_catalog_is_never_shippable(project):
    approve_everything(project, "de-DE")
    approve_everything(project, "zh-TW")
    stamp = time.time() + 10
    os.utime(project.root / "src" / "V4T.rc", (stamp, stamp))
    assert not project_status(project).can_ship


def test_a_current_catalog_is_quiet(project):
    result = project_status(project)
    assert not result.catalog_is_stale
    assert result.stale_sources == []


# -- counting -----------------------------------------------------------


def test_the_message_and_word_counts_are_reported(project):
    result = project_status(project)
    assert result.messages > 0
    assert result.source_words > result.messages


def test_state_counts_come_through(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="x", state=TranslationState.DRAFT))
    translations.set(message_key("Print started"),
                     Translation(text="y", state=TranslationState.NEEDS_REVIEW))
    save_translations(path, translations)

    entry = next(e for e in project_status(project).locales if e.tag == "de-DE")
    assert entry.drafts == 1
    assert entry.needs_review == 1
    assert entry.empty == entry.stats.total - 2


def test_the_last_touched_date_is_the_newest(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="x", state=TranslationState.DRAFT,
                                 updated="2025-01-04"))
    translations.set(message_key("Print started"),
                     Translation(text="y", state=TranslationState.DRAFT,
                                 updated="2025-03-11"))
    save_translations(path, translations)

    entry = next(e for e in project_status(project).locales if e.tag == "de-DE")
    assert entry.last_touched == date(2025, 3, 11)


def test_an_unparseable_date_does_not_take_the_command_down(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="x", state=TranslationState.DRAFT,
                                 updated="last Tuesday"))
    save_translations(path, translations)

    entry = next(e for e in project_status(project).locales if e.tag == "de-DE")
    assert entry.last_touched is None


def test_a_language_nobody_has_touched_has_no_date(project):
    assert project_status(project).locales[0].last_touched is None


def test_worst_first_puts_the_most_blocked_first(project):
    approve_everything(project, "de-DE")
    ordered = project_status(project).worst_first()
    assert ordered[0].tag == "zh-TW"


def test_outstanding_words_are_summed_across_languages(project):
    result = project_status(project)
    assert result.total_outstanding_words() == sum(
        e.stats.outstanding_words for e in result.locales
    )


def test_only_the_named_language_is_reported(project):
    result = project_status(project, locales=["de-DE"])
    assert [e.tag for e in result.locales] == ["de-DE"]


# -- waivers ------------------------------------------------------------


def test_waivers_are_counted(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")
    assert project_status(project).waivers == 1


def test_an_expired_waiver_becomes_a_note(project):
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "fitting"
reason = "accepted"
owner = "ming"
until = 2001-01-01
""", encoding="utf-8")
    result = project_status(project)
    assert result.expired_waivers == 1
    assert any("suppressing nothing" in note for note in result.notes)


def test_a_broken_waiver_file_is_a_note_not_a_crash(project):
    (project.root / "waivers.toml").write_text("[[waiver]\n", encoding="utf-8")
    assert any("could not be read" in n for n in project_status(project).notes)


# -- the command --------------------------------------------------------


def test_the_command_prints_the_verdict(project):
    assert "not shippable" in run(project).output


def test_the_command_lists_every_language(project):
    output = run(project).output
    assert "de-DE" in output
    assert "zh-TW" in output


def test_the_command_warns_about_a_stale_catalog(project):
    stamp = time.time() + 10
    os.utime(project.root / "src" / "V4T.rc", (stamp, stamp))
    assert "measured against a stale message list" in run(project).output


def test_the_json_output_parses(project):
    payload = json.loads(run(project, "--json").output)
    assert payload["project"] == "V4T-TIJ"
    assert payload["canShip"] is False
    assert len(payload["locales"]) == 2


def test_the_json_readiness_is_a_plain_string(project):
    payload = json.loads(run(project, "--json").output)
    assert payload["locales"][0]["readiness"] in {
        "ready", "blocked", "unstarted", "stale"
    }


def test_the_exit_code_flag_fails_when_blocked(project):
    assert run(project, "--exit-code").exit_code == 1


def test_the_exit_code_flag_passes_when_ready(project):
    approve_everything(project, "de-DE")
    approve_everything(project, "zh-TW")
    assert run(project, "--exit-code").exit_code == 0


def test_without_the_flag_it_always_exits_zero(project):
    assert run(project).exit_code == 0


def test_the_command_is_registered():
    result = CliRunner().invoke(main, ["--help"])
    assert "status" in result.output
