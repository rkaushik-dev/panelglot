import json
import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import (
    load_catalog,
    load_translations,
    save_catalog,
    save_translations,
)
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.check import changed_keys, check_project
from v4t_translate.ops.diff import diff_against, diff_to_json
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
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
def saved(project, tmp_path):
    """A copy of the catalog as it was, before anything moved."""
    path = tmp_path / "sent.json"
    save_catalog(path, load_catalog(project.catalog_path()))
    return path


def break_two(project):
    """Two translations with a placeholder error each."""
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    for source in ("Please input from %.1fV to %.1fV.",
                   "The length must be less <V1> chars"):
        translations.set(message_key(source),
                         Translation(text="kaputt", state=TranslationState.APPROVED))
    save_translations(path, translations)


def resize_one(project, source="Bar Height"):
    """Shrink the control one message sits in, and return its key.

    A resize rather than a reworded English, because a reworded English is a
    different key: the key is derived from the text. Editing the text produces
    one added message and one removed one, and the interesting third case is
    the message that survived and still needs another look.
    """
    catalog = load_catalog(project.catalog_path())
    key = message_key(source)
    catalog.messages[key].max_width_px = 12
    save_catalog(project.catalog_path(), catalog)
    return key


def run(config, *args, verbose=False):
    before = ["-c", str(config.root / "v4t-translate.toml")]
    if verbose:
        before.append("-v")
    return CliRunner().invoke(main, [*before, *args])


# -- the changed set ----------------------------------------------------


def test_nothing_moved_means_nothing_changed(project, saved):
    assert changed_keys(project, saved) == set()


def test_a_resized_message_shows_up(project, saved):
    key = resize_one(project)
    assert changed_keys(project, saved) == {key}


def test_a_new_message_shows_up(project, saved):
    from v4t_translate.catalog.model import Message

    catalog = load_catalog(project.catalog_path())
    catalog.add(Message(key="brand.new1", source_text="Brand New"))
    save_catalog(project.catalog_path(), catalog)

    assert "brand.new1" in changed_keys(project, saved)


def test_a_removed_message_does_not(project, saved):
    # Nothing to check on a message that is gone.
    catalog = load_catalog(project.catalog_path())
    key = next(iter(catalog.messages))
    del catalog.messages[key]
    save_catalog(project.catalog_path(), catalog)

    assert key not in changed_keys(project, saved)


def test_a_reworded_english_shows_up_as_a_new_key(project, saved):
    # The key is derived from the text, so a reworded string is a new message
    # and the old one is gone. Both are true, and only the new one is work.
    catalog = load_catalog(project.catalog_path())
    old = message_key("Bar Height")
    message = catalog.messages.pop(old)
    message.source_text = "Bar Height (mm)"
    message.key = message_key(message.source_text)
    catalog.add(message)
    save_catalog(project.catalog_path(), catalog)

    keys = changed_keys(project, saved)
    assert message.key in keys
    assert old not in keys


# -- the filtered check -------------------------------------------------


def test_the_whole_check_reports_everything(project):
    break_two(project)
    assert len(check_project(project).report) >= 2


def test_an_empty_change_set_reports_only_analyses(project):
    break_two(project)
    result = check_project(project, only_keys=set())
    assert all(f.rule in ("collisions", "merged", "untranslated")
               for f in result.report.findings)


def test_only_the_named_key_is_checked(project):
    break_two(project)
    key = message_key("Please input from %.1fV to %.1fV.")
    result = check_project(project, only_keys={key})
    rule_findings = [f for f in result.report.findings if f.rule == "placeholders"]
    assert {f.key for f in rule_findings} == {key}


def test_the_coverage_count_is_not_filtered(project):
    # The line says how much of the language is done. That number must not
    # move because somebody asked to see a subset of the findings.
    break_two(project)
    whole = check_project(project).locales[0].translated
    part = check_project(project, only_keys=set()).locales[0].translated
    assert whole == part


def test_analyses_are_not_filtered(project):
    # A collision between a string somebody changed and one they did not is
    # exactly the regression this mode is for, and it is anchored on whichever
    # key sorted first.
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Bar Height", state=TranslationState.APPROVED))
    save_translations(path, translations)

    result = check_project(project, only_keys=set())
    assert any(f.rule == "untranslated" for f in result.report.findings)


def test_waivers_still_apply_to_a_filtered_run(project):
    break_two(project)
    (project.root / "waivers.toml").write_text("""
[[waiver]]
rule = "placeholders"
reason = "accepted"
owner = "ming"
until = 2099-01-01
""", encoding="utf-8")

    key = message_key("Please input from %.1fV to %.1fV.")
    result = check_project(project, only_keys={key})
    assert not [f for f in result.report.findings if f.rule == "placeholders"]


# -- the command --------------------------------------------------------


def test_since_narrows_the_report(project, saved):
    break_two(project)

    whole = run(project, "check", "--fail-on", "never", "--limit", "0")
    narrowed = run(project, "check", "--fail-on", "never", "--limit", "0",
                   "--since", str(saved))
    assert "placeholders" in whole.output
    assert "placeholders" not in narrowed.output


def test_since_reports_the_size_of_the_change(project, saved):
    resize_one(project)
    output = run(project, "check", "--fail-on", "never", "--since", str(saved),
                 verbose=True).output
    assert "1 messages are new or different" in output


def test_since_keeps_a_finding_on_a_changed_message(project, saved):
    break_two(project)
    resize_one(project, "Please input from %.1fV to %.1fV.")

    output = run(project, "check", "--fail-on", "never", "--limit", "0",
                 "--since", str(saved)).output
    assert "placeholders" in output


def test_a_missing_since_file_is_refused(project):
    result = run(project, "check", "--since", "nowhere.json")
    assert result.exit_code != 0


# -- diff as json -------------------------------------------------------


def test_the_diff_json_parses(project, saved):
    resize_one(project)
    payload = json.loads(diff_to_json(diff_against(project, saved)))
    assert payload["changed"]
    assert payload["needsAttention"] == 1


def test_the_diff_json_carries_the_reasons(project, saved):
    resize_one(project)
    payload = json.loads(diff_to_json(diff_against(project, saved)))
    assert payload["changed"][0]["reasons"]


def test_the_diff_json_counts_words(project, saved):
    from v4t_translate.catalog.model import Message

    catalog = load_catalog(project.catalog_path())
    catalog.add(Message(key="brand.new1", source_text="Three whole words"))
    save_catalog(project.catalog_path(), catalog)

    payload = json.loads(diff_to_json(diff_against(project, saved)))
    assert payload["addedWords"] == 3
    assert payload["added"][0]["words"] == 3


def test_an_empty_diff_still_parses(project, saved):
    payload = json.loads(diff_to_json(diff_against(project, saved)))
    assert payload["added"] == []
    assert payload["unchanged"] > 0


def test_the_diff_command_can_emit_json(project, saved):
    resize_one(project)
    output = run(project, "diff", str(saved), "--json").output
    assert json.loads(output)["needsAttention"] == 1


def test_the_diff_command_still_prints_prose(project, saved):
    resize_one(project)
    assert "changed" in run(project, "diff", str(saved)).output
