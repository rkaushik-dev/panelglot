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
from v4t_translate.ops.extract import cache_path, extract_project
from v4t_translate.ops.memory import absorb_catalog, memory_path
from v4t_translate.ops.prune import prune_project

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


def add_orphans(config, tag, count=2):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for index in range(count):
        translations.set(f"gone-{index}.000000",
                         Translation(text="weg", state=TranslationState.APPROVED))
    save_translations(path, translations)


def test_a_clean_project_has_nothing_to_prune(project):
    result = prune_project(project)
    assert not result
    assert result.summary() == "nothing to prune"


def test_orphan_translations_are_dropped(project):
    add_orphans(project, "de-DE", 3)
    result = prune_project(project)

    assert result.orphans["de-DE"] == ["gone-0.000000", "gone-1.000000",
                                       "gone-2.000000"]
    assert result.total_orphans == 3

    translations = load_translations(project.translations_path("de-DE"))
    assert "gone-0.000000" not in translations


def test_real_translations_are_left_alone(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Print started"),
                     Translation(text="Druck gestartet",
                                 state=TranslationState.APPROVED))
    save_translations(path, translations)
    add_orphans(project, "de-DE")

    prune_project(project)
    after = load_translations(path)
    assert after.get(message_key("Print started")).text == "Druck gestartet"


def test_every_language_is_pruned(project):
    add_orphans(project, "de-DE")
    add_orphans(project, "zh-TW")
    result = prune_project(project)
    assert set(result.orphans) == {"de-DE", "zh-TW"}


def test_a_language_with_no_file_yet_is_skipped(project):
    project.translations_path("zh-TW").unlink()
    add_orphans(project, "de-DE")
    result = prune_project(project)
    assert set(result.orphans) == {"de-DE"}


def test_the_summary_counts(project):
    add_orphans(project, "de-DE", 2)
    assert prune_project(project).summary().startswith("removed 2 translations")


def test_dry_run_removes_nothing(project):
    add_orphans(project, "de-DE", 2)
    result = prune_project(project, dry_run=True)

    assert result.total_orphans == 2
    assert result.written == []
    assert "gone-0.000000" in load_translations(project.translations_path("de-DE"))


def test_memory_is_left_alone_by_default(project):
    with TranslationMemory(memory_path(project)) as memory:
        memory.remember("de-DE", "A string that is long gone", "Ein alter Text")

    prune_project(project)

    with TranslationMemory(memory_path(project)) as memory:
        assert memory.recall("de-DE", "A string that is long gone") is not None


def test_memory_can_be_pruned_when_asked(project):
    with TranslationMemory(memory_path(project)) as memory:
        memory.remember("de-DE", "A string that is long gone", "Ein alter Text")
        memory.remember("de-DE", "Print started", "Druck gestartet")

    result = prune_project(project, drop_memory=True)
    assert result.memory_units == 1

    with TranslationMemory(memory_path(project)) as memory:
        assert memory.recall("de-DE", "A string that is long gone") is None
        assert memory.recall("de-DE", "Print started") is not None


def test_memory_pruning_in_a_dry_run(project):
    with TranslationMemory(memory_path(project)) as memory:
        memory.remember("de-DE", "Long gone", "Weg")

    result = prune_project(project, drop_memory=True, dry_run=True)
    assert result.memory_units == 1

    with TranslationMemory(memory_path(project)) as memory:
        assert memory.recall("de-DE", "Long gone") is not None


def test_memory_absorbed_from_the_catalog_survives_a_prune(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Print started"),
                     Translation(text="Druck gestartet",
                                 state=TranslationState.APPROVED))
    save_translations(path, translations)
    absorb_catalog(project)

    assert prune_project(project, drop_memory=True).memory_units == 0


def test_a_project_with_no_memory_file(project):
    assert prune_project(project, drop_memory=True).memory_units == 0


def test_the_cache_can_be_dropped(project):
    assert cache_path(project).exists()
    result = prune_project(project, drop_cache=True)

    assert result.cache_removed
    assert not cache_path(project).exists()
    assert result.freed_bytes > 0


def test_the_cache_is_kept_by_default(project):
    prune_project(project)
    assert cache_path(project).exists()


def test_the_cache_in_a_dry_run(project):
    result = prune_project(project, drop_cache=True, dry_run=True)
    assert result.cache_removed
    assert cache_path(project).exists()


def test_before_extract(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError) as caught:
        prune_project(config)
    assert "Run extract first" in caught.value.remedy


def test_the_command_line(project):
    add_orphans(project, "de-DE", 2)
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "prune",
    ])
    assert result.exit_code == 0
    assert "de-DE: 2 translations with no message" in result.output


def test_the_command_line_lists_the_keys_when_verbose(project):
    add_orphans(project, "de-DE", 1)
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "-v", "prune",
    ])
    assert "gone-0.000000" in result.output


def test_the_command_line_dry_run(project):
    add_orphans(project, "de-DE", 1)
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "prune", "--dry-run",
    ])
    assert "dry run, nothing removed" in result.output
    assert "gone-0.000000" in load_translations(project.translations_path("de-DE"))
