import shutil
from datetime import date, timezone

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.build import build_project, unreproducible_outputs
from v4t_translate.ops.extract import extract_project
from v4t_translate.reproducible import (
    SOURCE_DATE_EPOCH,
    build_date,
    build_datetime,
    is_pinned,
    source_date_epoch,
)

# 2025-02-14 09:30:00 UTC
PINNED = 1739525400

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[[output]]
kind = "po"
path = "out/{locale}.po"

[[output]]
kind = "rc"
path = "out/{locale}/V4T.rc"
source = "src/V4T.rc"
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)

    path = config.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Balkenhöhe", state=TranslationState.APPROVED))
    save_translations(path, translations)
    return config


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), *args,
    ])


# -- reading the environment --------------------------------------------


def test_an_unset_variable_is_none():
    assert source_date_epoch({}) is None


def test_an_empty_variable_is_none():
    assert source_date_epoch({SOURCE_DATE_EPOCH: "   "}) is None


def test_a_number_is_read():
    assert source_date_epoch({SOURCE_DATE_EPOCH: str(PINNED)}) == PINNED


def test_surrounding_space_is_ignored():
    assert source_date_epoch({SOURCE_DATE_EPOCH: f" {PINNED} "}) == PINNED


def test_junk_falls_back_rather_than_failing():
    # A build machine with a mangled environment variable should produce a
    # warning and a build, not no build.
    assert source_date_epoch({SOURCE_DATE_EPOCH: "yesterday"}) is None


def test_a_negative_value_is_junk():
    assert source_date_epoch({SOURCE_DATE_EPOCH: "-1"}) is None


def test_zero_is_allowed():
    assert source_date_epoch({SOURCE_DATE_EPOCH: "0"}) == 0


def test_pinned_says_so():
    assert is_pinned({SOURCE_DATE_EPOCH: str(PINNED)})
    assert not is_pinned({})


# -- the stamp ----------------------------------------------------------


def test_the_pinned_instant_is_used():
    stamped = build_datetime({SOURCE_DATE_EPOCH: str(PINNED)})
    assert stamped.year == 2025
    assert stamped.month == 2
    assert stamped.day == 14


def test_the_stamp_is_utc():
    assert build_datetime({SOURCE_DATE_EPOCH: str(PINNED)}).tzinfo is timezone.utc
    assert build_datetime({}).tzinfo is timezone.utc


def test_the_date_comes_off_the_instant():
    assert build_date({SOURCE_DATE_EPOCH: str(PINNED)}) == date(2025, 2, 14)


def test_without_a_pin_it_is_today():
    assert build_date({}) == build_datetime({}).date()


# -- what it does to the outputs ----------------------------------------


def test_the_po_header_uses_the_pinned_date(project, monkeypatch):
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    build_project(project)
    text = (project.root / "out" / "de-DE.po").read_text(encoding="utf-8")
    assert "PO-Revision-Date: 2025-02-14" in text


def test_two_builds_a_day_apart_match_when_pinned(project, monkeypatch):
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    build_project(project)
    first = (project.root / "out" / "de-DE.po").read_bytes()

    build_project(project)
    assert (project.root / "out" / "de-DE.po").read_bytes() == first


def test_the_manifest_uses_the_pinned_instant(project, monkeypatch):
    from v4t_translate import __version__
    from v4t_translate.emit.manifest import build_manifest

    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    result = build_project(project)
    manifest = build_manifest(project, result, tool_version=__version__)
    assert manifest.built_at.startswith("2025-02-14T09:30")


def test_a_tmx_export_uses_it_too(project, tmp_path, monkeypatch):
    from v4t_translate.mt.memory import TranslationMemory
    from v4t_translate.mt.tmx import write_tmx

    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))

    memory = TranslationMemory(tmp_path / "memory.sqlite3")
    memory.remember("de-DE", "Bar Height", "Balkenhöhe")
    out = tmp_path / "de-DE.tmx"
    write_tmx(out, memory, "de-DE")
    memory.close()

    assert "20250214T000000Z" in out.read_text(encoding="utf-8")


# -- the double build ---------------------------------------------------


def test_a_pinned_build_is_reproducible(project, monkeypatch):
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    assert unreproducible_outputs(project) == []


def test_it_covers_every_output(project, monkeypatch):
    # Nothing is worth reporting here, but the check has to have looked at
    # both kinds or an empty answer means nothing.
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    from v4t_translate.ops.build import _staged

    staged = _staged(project, None)
    assert len(staged) == 2
    assert any("po" in name for name in staged)
    assert any("rc" in name for name in staged)


def test_a_non_deterministic_emitter_is_caught(project, monkeypatch):
    import itertools

    from v4t_translate.emit import po

    counter = itertools.count()
    monkeypatch.setattr(po, "build_date", lambda: date(2025, 1, next(counter) % 28 + 1))
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))

    problems = unreproducible_outputs(project)
    assert any("po" in name for name in problems)


def test_one_language_can_be_checked(project, monkeypatch):
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    assert unreproducible_outputs(project, locales=["de-DE"]) == []


# -- the command --------------------------------------------------------


def test_the_flag_reports_success(project, monkeypatch):
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))
    result = run(project, "build", "--reproducible", "--no-check")
    assert result.exit_code == 0
    assert "byte for byte the same" in result.output


def test_the_flag_warns_when_nothing_is_pinned(project, monkeypatch):
    monkeypatch.delenv(SOURCE_DATE_EPOCH, raising=False)
    result = run(project, "build", "--reproducible", "--no-check")
    assert "SOURCE_DATE_EPOCH is not set" in result.output


def test_a_difference_fails_the_build(project, monkeypatch):
    import itertools

    from v4t_translate.emit import po

    counter = itertools.count()
    monkeypatch.setattr(po, "build_date", lambda: date(2025, 1, next(counter) % 28 + 1))
    monkeypatch.setenv(SOURCE_DATE_EPOCH, str(PINNED))

    result = run(project, "build", "--reproducible", "--no-check")
    assert result.exit_code != 0
    assert "differs between two builds" in result.output


def test_without_the_flag_nothing_is_built_twice(project):
    assert "byte for byte" not in run(project, "build", "--no-check").output
