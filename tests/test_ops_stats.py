import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key, source_fingerprint
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.stats import count_words, project_stats

CONFIG = """
[project]
name = "V4T-TIJ"

[protected]
patterns = ["mm", "YYYY"]

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


def set_entries(config, tag, entries):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for source, translation in entries.items():
        translations.set(message_key(source), translation)
    save_translations(path, translations)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("Pen", 1),
        ("Print started", 2),
        ("  Print   started  ", 2),
        ("Please input from %.1fV to %.1fV.", 6),
        ("刪除", 2),
        ("時間戳列表", 5),
        ("Print刪除", 3),
        ("刪除Print", 3),
        ("Print 刪除 stopped", 4),
    ],
)
def test_count_words(text, expected):
    assert count_words(text) == expected


def test_a_fresh_project(project):
    stats = project_stats(project)
    assert stats.project == "V4T-TIJ"
    assert stats.messages > 30
    assert stats.source_words > stats.messages
    assert stats.protected == 2
    assert [s.tag for s in stats.locales] == ["de-DE", "zh-TW"]


def test_nothing_translated_yet(project):
    german = project_stats(project).locale("de-DE")
    assert german.translated == 0
    assert german.approved == 0
    assert german.translated_fraction == 0.0
    assert german.outstanding == german.total
    assert german.outstanding_words == german.total_words


def test_translated_and_approved_are_counted_apart(project):
    set_entries(project, "de-DE", {
        "Print started": Translation(text="Druck gestartet",
                                     state=TranslationState.APPROVED),
        "Service restarted": Translation(text="Dienst neu gestartet",
                                         state=TranslationState.DRAFT),
        "Feature is not enabled": Translation(text="Funktion nicht aktiv",
                                              state=TranslationState.NEEDS_REVIEW),
    })
    german = project_stats(project).locale("de-DE")
    assert german.translated == 3
    assert german.approved == 1
    assert german.approved_fraction < german.translated_fraction


def test_do_not_translate_counts_as_shippable(project):
    set_entries(project, "de-DE", {
        "mm": Translation(text="mm", state=TranslationState.DO_NOT_TRANSLATE),
    })
    assert project_stats(project).locale("de-DE").approved == 1


def test_states_are_broken_out(project):
    set_entries(project, "de-DE", {
        "Print started": Translation(text="a", state=TranslationState.APPROVED),
        "Service restarted": Translation(text="b", state=TranslationState.DRAFT),
    })
    by_state = project_stats(project).locale("de-DE").by_state
    assert by_state["approved"] == 1
    assert by_state["draft"] == 1
    assert by_state["empty"] > 0


def test_stale_entries_are_counted(project):
    set_entries(project, "de-DE", {
        "Print started": Translation(
            text="Druck gestartet", state=TranslationState.APPROVED,
            fingerprint=source_fingerprint("Print STARTED"),
        ),
    })
    assert project_stats(project).locale("de-DE").stale == 1


def test_a_current_entry_is_not_stale(project):
    set_entries(project, "de-DE", {
        "Print started": Translation(
            text="Druck gestartet", state=TranslationState.APPROVED,
            fingerprint=source_fingerprint("Print started"),
        ),
    })
    assert project_stats(project).locale("de-DE").stale == 0


def test_outstanding_words_drop_as_work_lands(project):
    before = project_stats(project).locale("de-DE").outstanding_words
    set_entries(project, "de-DE", {
        "This distance cannot be greater than print spacing":
            Translation(text="Zu gross", state=TranslationState.APPROVED),
    })
    after = project_stats(project).locale("de-DE").outstanding_words
    assert after == before - 8


def test_describe_reads(project):
    text = project_stats(project).locale("de-DE").describe()
    assert text.startswith("de-DE:")
    assert "words outstanding" in text


def test_worst_first_orders_by_approval(project):
    set_entries(project, "de-DE", {
        "Print started": Translation(text="a", state=TranslationState.APPROVED),
    })
    ordered = project_stats(project).worst_first()
    assert ordered[0].tag == "zh-TW"


def test_stats_can_be_limited_to_one_locale(project):
    assert [s.tag for s in project_stats(project, locales=["zh-TW"]).locales] == ["zh-TW"]


def test_an_unknown_locale_is_missing(project):
    assert project_stats(project).locale("fr-FR") is None


def test_before_extract(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError) as caught:
        project_stats(config)
    assert "Run extract first" in caught.value.remedy


def test_the_command_line(project):
    runner = CliRunner()
    result = runner.invoke(main, ["-c", str(project.root / "v4t-translate.toml"), "stats"])
    assert result.exit_code == 0
    assert "de-DE:" in result.output
    assert "zh-TW:" in result.output


def test_the_command_line_worst_first(project):
    set_entries(project, "de-DE", {
        "Print started": Translation(text="a", state=TranslationState.APPROVED),
    })
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "stats", "--worst-first",
    ])
    assert result.output.index("zh-TW:") < result.output.index("de-DE:")


def test_the_command_line_verbose_breaks_out_states(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "-v", "stats",
    ])
    assert "empty:" in result.output
    assert "are protected" in result.output
