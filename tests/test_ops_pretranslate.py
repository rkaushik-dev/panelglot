import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError
from v4t_translate.mt.memory import TranslationMemory
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.pretranslate import pretranslate_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[protected]
patterns = ["mm", "YYYY"]

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
def memory():
    with TranslationMemory() as memory:
        memory.remember("de-DE", "Print started", "Druck gestartet")
        memory.remember("de-DE", "Purge offset must be less than the group offset",
                        "Der Versatz muss kleiner als der Gruppenversatz sein")
        yield memory


def entry_for(config, source, tag="de-DE"):
    return load_translations(config.translations_path(tag)).get(message_key(source))


def test_an_exact_hit_lands_as_needs_review(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory)
    assert message_key("Print started") in result.from_memory

    entry = entry_for(project, "Print started")
    assert entry.text == "Druck gestartet"
    assert entry.state is TranslationState.NEEDS_REVIEW
    assert entry.origin == "memory"


def test_trust_memory_lands_it_approved(project, memory):
    pretranslate_project(project, "de-DE", memory=memory, trust_memory=True)
    assert entry_for(project, "Print started").state is TranslationState.APPROVED


def test_a_fuzzy_hit_lands_as_a_draft_with_a_note(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory)
    key = message_key("Purge offset must be less than group offset")
    assert key in result.from_fuzzy

    entry = entry_for(project, "Purge offset must be less than group offset")
    assert entry.state is TranslationState.DRAFT
    assert "% match against" in entry.note


def test_the_fuzzy_threshold_is_honoured(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory, threshold=0.99)
    assert result.from_fuzzy == []


def test_nothing_else_is_filled_without_a_provider(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory)
    assert result.left_empty
    assert result.from_provider == []
    assert entry_for(project, "Bearer thickness").text == ""


def test_a_provider_fills_the_rest(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory, provider="pseudo")
    assert result.from_provider
    assert result.left_empty == []

    entry = entry_for(project, "Bearer thickness")
    assert entry.text.startswith("[")
    assert entry.state is TranslationState.DRAFT
    assert entry.origin == "pseudo"


def test_the_provider_does_not_overwrite_a_memory_hit(project, memory):
    pretranslate_project(project, "de-DE", memory=memory, provider="pseudo")
    assert entry_for(project, "Print started").text == "Druck gestartet"


def test_an_answered_string_is_left_alone(project, memory):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Print started"),
                     Translation(text="Von Hand", state=TranslationState.APPROVED))
    save_translations(path, translations)

    result = pretranslate_project(project, "de-DE", memory=memory)
    assert result.already_answered >= 1
    assert entry_for(project, "Print started").text == "Von Hand"


def test_a_protected_string_is_never_pretranslated(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory, provider="pseudo")
    assert result.protected >= 2
    assert entry_for(project, "mm").text == ""
    assert entry_for(project, "YYYY").text == ""


def test_placeholders_survive_the_provider(project, memory):
    pretranslate_project(project, "de-DE", memory=memory, provider="pseudo")
    entry = entry_for(project, "Please input from %.1fV to %.1fV.")
    assert entry.text.count("%.1f") == 2


def test_dry_run_writes_nothing(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory, dry_run=True)
    assert not result.written
    assert result.from_memory
    assert entry_for(project, "Print started").text == ""


def test_the_summary_reads(project, memory):
    result = pretranslate_project(project, "de-DE", memory=memory, provider="pseudo")
    assert result.summary().startswith("de-DE:")
    assert "exact" in result.summary()


def test_an_unconfigured_locale_is_refused(project, memory):
    from v4t_translate.errors import ConfigError

    with pytest.raises(ConfigError, match="is not configured"):
        pretranslate_project(project, "fr-FR", memory=memory)


def test_before_extract(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError, match="Run extract first"):
        pretranslate_project(config, "de-DE")


def test_a_memory_is_opened_beside_the_catalog_when_none_is_given(project):
    pretranslate_project(project, "de-DE")
    assert (project.root / "catalog" / "memory.sqlite3").exists()


def test_a_provider_that_answers_the_wrong_number_is_dropped(project, memory):
    class Broken:
        name = "broken"

        def translate(self, texts, source, target):
            from v4t_translate.mt.base import ProviderResult

            return ProviderResult(texts=["only one"], provider=self.name)

    result = pretranslate_project(project, "de-DE", memory=memory, provider=Broken())
    assert any("returned 1 answers" in w for w in result.warnings)
    assert result.from_provider == []
    assert result.left_empty


def test_a_provider_that_declines_leaves_the_string_empty(project, memory):
    class Silent:
        name = "silent"

        def translate(self, texts, source, target):
            from v4t_translate.mt.base import ProviderResult

            return ProviderResult(texts=[""] * len(texts), provider=self.name)

    result = pretranslate_project(project, "de-DE", memory=memory, provider=Silent())
    assert result.from_provider == []
    assert result.left_empty


def test_the_command_line(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "pretranslate", "de-DE", "--provider", "pseudo",
    ])
    assert result.exit_code == 0
    assert "de-DE:" in result.output
    assert entry_for(project, "Bearer thickness").text


def test_the_command_line_dry_run(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "pretranslate", "de-DE", "--dry-run",
    ])
    assert "dry run, nothing written" in result.output


def test_the_command_line_rejects_an_unknown_provider(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "pretranslate", "de-DE", "-p", "deepl",
    ])
    assert result.exit_code != 0
