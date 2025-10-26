import json
import shutil
from datetime import date

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.store import load_catalog, load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.history import (
    HISTORY_NAME,
    Snapshot,
    history_path,
    movement_since,
    read_history,
    record,
)
from v4t_translate.ops.stats import project_stats

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


def approve(config, tag, count):
    """Approve the first ``count`` messages, so coverage moves."""
    catalog = load_catalog(config.catalog_path())
    path = config.translations_path(tag)
    translations = load_translations(path)
    for key in list(catalog.sorted_keys())[:count]:
        message = catalog.messages[key]
        translations.set(key, Translation().with_text(
            f"[{message.source_text}]", source_text=message.source_text,
            state=TranslationState.APPROVED))
    save_translations(path, translations)


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), *args,
    ])


# -- the record ---------------------------------------------------------


def test_a_snapshot_round_trips():
    snapshot = Snapshot(day="2025-03-04", locale="de-DE", approved=10,
                        translated=12, total=40, outstanding_words=300)
    assert Snapshot.parse(snapshot.to_json()) == snapshot


def test_a_torn_line_loses_one_day_not_the_file():
    assert Snapshot.parse('{"day": "2025-03-04", "loc') is None


def test_a_line_missing_a_field_is_skipped():
    assert Snapshot.parse('{"day": "2025-03-04"}') is None


def test_a_line_that_is_not_an_object_is_skipped():
    assert Snapshot.parse("[1, 2, 3]") is None


def test_missing_word_counts_default_to_zero():
    line = '{"day":"2025-03-04","locale":"de-DE","approved":1,"translated":1,"total":2}'
    assert Snapshot.parse(line).outstanding_words == 0


def test_the_fraction_is_approved_over_total():
    assert Snapshot(day="d", locale="de-DE", approved=1, translated=1,
                    total=4, outstanding_words=0).fraction == 0.25


def test_a_language_with_nothing_in_it_does_not_divide_by_zero():
    assert Snapshot(day="d", locale="de-DE", approved=0, translated=0,
                    total=0, outstanding_words=0).fraction == 0.0


# -- writing and reading ------------------------------------------------


def test_recording_writes_one_line_per_language(project):
    written = record(project, project_stats(project), day=date(2025, 3, 4))
    assert len(written) == 2
    assert len(read_history(project).copy()) == 2


def test_the_file_sits_beside_the_catalog(project):
    record(project, project_stats(project))
    assert history_path(project).name == HISTORY_NAME
    assert history_path(project).parent == project.catalog_path().parent


def test_recording_appends(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    record(project, project_stats(project), day=date(2025, 3, 11))
    assert len(read_history(project)) == 4


def test_the_day_is_written(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    assert {s.day for s in read_history(project)} == {"2025-03-04"}


def test_no_history_reads_as_nothing(project):
    assert read_history(project) == []


def test_a_bad_line_in_the_middle_is_skipped(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    with history_path(project).open("a", encoding="utf-8") as handle:
        handle.write("not json at all\n")
    record(project, project_stats(project), day=date(2025, 3, 11))

    assert len(read_history(project)) == 4


def test_blank_lines_are_skipped(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    with history_path(project).open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
    assert len(read_history(project)) == 2


def test_the_lines_are_valid_json(project):
    record(project, project_stats(project))
    for line in history_path(project).read_text(encoding="utf-8").splitlines():
        json.loads(line)


# -- movement -----------------------------------------------------------


def test_nothing_recorded_means_no_movement(project):
    assert movement_since(project, project_stats(project)) == []


def test_a_language_that_moved_is_reported(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    approve(project, "de-DE", 5)

    moved = {m.locale: m for m in movement_since(project, project_stats(project),
                                                 day=date(2025, 3, 11))}
    assert moved["de-DE"].approved_change == 5


def test_a_language_that_did_not_move_reports_zero(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    moved = {m.locale: m for m in movement_since(project, project_stats(project),
                                                 day=date(2025, 3, 11))}
    assert moved["zh-TW"].approved_change == 0
    assert "no change" in moved["zh-TW"].describe()


def test_the_span_in_days_is_reported(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    movement = movement_since(project, project_stats(project),
                              day=date(2025, 3, 11))[0]
    assert movement.days == 7
    assert "over 7 days" in movement.describe()


def test_words_outstanding_are_compared(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    approve(project, "de-DE", 5)

    moved = {m.locale: m for m in movement_since(project, project_stats(project),
                                                 day=date(2025, 3, 11))}
    assert moved["de-DE"].words_change < 0


def test_the_comparison_is_against_the_most_recent_older_run(project):
    record(project, project_stats(project), day=date(2025, 1, 1))
    approve(project, "de-DE", 3)
    record(project, project_stats(project), day=date(2025, 3, 4))
    approve(project, "de-DE", 5)

    moved = {m.locale: m for m in movement_since(project, project_stats(project),
                                                 day=date(2025, 3, 11))}
    # Against the March run, which had three, not against January's nothing.
    assert moved["de-DE"].approved_change == 2


def test_a_run_recorded_twice_in_one_day_does_not_compare_against_itself(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    approve(project, "de-DE", 4)
    assert movement_since(project, project_stats(project),
                          day=date(2025, 3, 4)) == []


def test_a_movement_backwards_reads_as_such(project):
    record(project, project_stats(project), day=date(2025, 3, 4))
    approve(project, "de-DE", 4)
    record(project, project_stats(project), day=date(2025, 3, 5))

    # Somebody set four back to needs-review.
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    for key in list(translations.entries)[:4]:
        translations.set(key, translations.get(key).marked(
            TranslationState.NEEDS_REVIEW))
    save_translations(path, translations)

    moved = {m.locale: m for m in movement_since(project, project_stats(project),
                                                 day=date(2025, 3, 11))}
    assert moved["de-DE"].approved_change == -4
    assert "-4 approved" in moved["de-DE"].describe()


def test_an_unreadable_day_gives_no_span():
    before = Snapshot(day="last Tuesday", locale="de-DE", approved=1,
                      translated=1, total=4, outstanding_words=0)
    after = Snapshot(day="2025-03-11", locale="de-DE", approved=2,
                     translated=2, total=4, outstanding_words=0)
    from v4t_translate.ops.history import Movement

    assert Movement(locale="de-DE", before=before, after=after).days == 0


# -- the command --------------------------------------------------------


def test_stats_records_nothing_by_default(project):
    run(project, "stats")
    assert not history_path(project).exists()


def test_the_flag_records(project):
    output = run(project, "stats", "--record").output
    assert history_path(project).exists()
    assert "recorded 2 languages" in output


def test_since_last_says_so_when_there_is_nothing(project):
    assert "nothing recorded before today" in run(project, "stats",
                                                  "--since-last").output


def test_since_last_reports_the_movement(project):
    record(project, project_stats(project), day=date(2020, 1, 1))
    approve(project, "de-DE", 5)
    assert "+5 approved" in run(project, "stats", "--since-last").output


def test_the_two_flags_work_together(project):
    record(project, project_stats(project), day=date(2020, 1, 1))
    result = run(project, "stats", "--since-last", "--record")
    assert "approved" in result.output
    assert len(read_history(project)) == 4
