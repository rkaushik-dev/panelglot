import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import EmitError
from v4t_translate.ops.build import build_project
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.verify import PackDifference, compare_packs

LANG_H = Path(__file__).resolve().parent / "fixtures" / "v4t_lang.h"

CONFIG = """
[project]
name = "V4T-Mini"

[[source]]
kind = "cheader"
path = "src/v4t_lang.h"

[locale."de-DE"]

[locale."zh-TW"]

[[output]]
kind = "v4l"
path = "out/{locale}.v4l"
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    shutil.copy(LANG_H, tmp_path / "src" / "v4t_lang.h")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def translate(config, tag, pairs):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for source, target in pairs.items():
        translations.set(message_key(source),
                         Translation(text=target, state=TranslationState.APPROVED))
    save_translations(path, translations)


def built(config, tag="de-DE"):
    build_project(config, locales=[tag])
    return config.root / "out" / f"{tag}.v4l"


def archive(config, path, name):
    """Keep a copy of a pack the way a release would."""
    copy = config.root / name
    shutil.copy(path, copy)
    return copy


def insert_a_string(config):
    """Add an id in the middle of the enum, the way a developer would.

    This is the failure the signature exists for. Every slot past the insert
    shifts by one, nothing crashes, and the panel starts showing the string
    below the one it meant.
    """
    from v4t_translate.catalog.model import Message, Origin, OriginKind
    from v4t_translate.catalog.store import load_catalog, save_catalog

    catalog = load_catalog(config.catalog_path())
    catalog.add(Message(
        key="brand.new1",
        source_text="Brand New",
        origins=[Origin(source="src/v4t_lang.h", kind=OriginKind.C_STRING_TABLE,
                        container="lng_en", symbol="LNG_BRAND_NEW",
                        line=24, ordinal=1)],
    ))
    save_catalog(config.catalog_path(), catalog)


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), *args,
    ])


# -- the difference type ------------------------------------------------


def test_a_changed_slot_reads_as_changed():
    assert PackDifference(index=4, before="a", after="b").kind == "changed"


def test_an_empty_before_reads_as_filled_in():
    assert PackDifference(index=4, before="", after="b").kind == "filled in"


def test_an_empty_after_reads_as_emptied():
    assert PackDifference(index=4, before="a", after="").kind == "emptied"


def test_each_kind_describes_itself_differently():
    described = {
        PackDifference(4, "a", "b").describe(),
        PackDifference(4, "", "b").describe(),
        PackDifference(4, "a", "").describe(),
    }
    assert len(described) == 3


def test_the_slot_number_is_in_the_description():
    assert "slot 41" in PackDifference(41, "a", "b").describe()


# -- comparing ----------------------------------------------------------


def test_a_pack_matches_itself(project):
    pack = built(project)
    comparison = compare_packs(pack, pack)
    assert comparison.identical
    assert "are the same pack" in comparison.summary()


def test_two_builds_of_the_same_catalog_match(project):
    first = archive(project, built(project), "first.v4l")
    second = built(project)
    assert compare_packs(first, second).identical


def test_a_changed_translation_shows_up(project):
    translate(project, "de-DE", {"Print started": "Balkenhöhe"})
    first = archive(project, built(project), "first.v4l")

    translate(project, "de-DE", {"Print started": "Höhe"})
    comparison = compare_packs(first, built(project))

    assert len(comparison.differences) == 1
    assert comparison.differences[0].kind == "changed"


def test_the_old_and_new_text_both_come_through(project):
    translate(project, "de-DE", {"Print started": "Balkenhöhe"})
    first = archive(project, built(project), "first.v4l")
    translate(project, "de-DE", {"Print started": "Höhe"})

    difference = compare_packs(first, built(project)).differences[0]
    assert difference.before == "Balkenhöhe"
    assert difference.after == "Höhe"


def test_several_changes_are_counted_by_kind(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet",
                                 "Spacing": "Abstand"})
    first = archive(project, built(project), "first.v4l")

    translate(project, "de-DE", {"Print started": "Start", "Pen": "Stift"})
    counts = compare_packs(first, built(project)).by_kind()

    # Both are "changed" and neither is "filled in", because an untranslated
    # slot ships its English rather than an empty string. Nothing in a built
    # pack is ever empty unless the English was.
    assert counts.get("changed") == 2
    assert "filled in" not in counts


def test_the_summary_lists_the_kinds(project):
    translate(project, "de-DE", {"Print started": "Balkenhöhe"})
    first = archive(project, built(project), "first.v4l")
    translate(project, "de-DE", {"Print started": "Höhe"})

    assert "1 changed" in compare_packs(first, built(project)).summary()


def test_a_slot_is_compared_by_index_not_by_text(project):
    # Two different slots holding the same string are still two slots.
    translate(project, "de-DE", {"Print started": "Breite"})
    first = archive(project, built(project), "first.v4l")
    translate(project, "de-DE", {"Print started": "Balkenhöhe"})

    assert compare_packs(first, built(project)).differences[0].index >= 0


# -- when they cannot be compared ---------------------------------------


def test_two_languages_are_refused(project):
    german = archive(project, built(project, "de-DE"), "de.v4l")
    chinese = built(project, "zh-TW")

    comparison = compare_packs(german, chinese)
    assert not comparison.identical
    assert any("de-DE" in problem for problem in comparison.problems)


def test_a_moved_enum_is_refused_rather_than_diffed(project):
    first = archive(project, built(project), "first.v4l")
    insert_a_string(project)

    comparison = compare_packs(first, built(project))
    assert comparison.problems
    assert comparison.differences == []
    assert "signatures differ" in comparison.problems[0]


def test_the_refusal_explains_why_a_diff_would_be_nonsense(project):
    first = archive(project, built(project), "first.v4l")
    insert_a_string(project)
    assert "do not line up" in compare_packs(first, built(project)).problems[0]


def test_a_missing_pack_is_refused(project):
    pack = built(project)
    with pytest.raises(EmitError, match="does not exist"):
        compare_packs(pack, project.root / "nope.v4l")


# -- the command --------------------------------------------------------


def test_the_command_reports_a_change(project):
    translate(project, "de-DE", {"Print started": "Balkenhöhe"})
    first = archive(project, built(project), "first.v4l")
    translate(project, "de-DE", {"Print started": "Höhe"})
    second = built(project)

    output = run(project, "pack-diff", str(first), str(second)).output
    assert "Balkenhöhe" in output
    assert "1 slots differ" in output


def test_the_command_is_quiet_when_they_match(project):
    pack = built(project)
    result = run(project, "pack-diff", str(pack), str(pack))
    assert result.exit_code == 0
    assert "are the same pack" in result.output


def test_the_command_truncates(project):
    translate(project, "de-DE", {"Print started": "a", "Spacing": "b",
                                 "Pen": "c"})
    first = archive(project, built(project), "first.v4l")
    translate(project, "de-DE", {"Print started": "x", "Spacing": "y",
                                 "Pen": "z"})
    second = built(project)

    output = run(project, "pack-diff", str(first), str(second),
                 "--limit", "1").output
    assert "and 2 more" in output


def test_the_limit_can_be_lifted(project):
    translate(project, "de-DE", {"Print started": "a", "Spacing": "b"})
    first = archive(project, built(project), "first.v4l")
    translate(project, "de-DE", {"Print started": "x", "Spacing": "y"})
    second = built(project)

    output = run(project, "pack-diff", str(first), str(second),
                 "--limit", "0").output
    assert "more" not in output


def test_an_incomparable_pair_exits_non_zero(project):
    german = archive(project, built(project, "de-DE"), "de.v4l")
    chinese = built(project, "zh-TW")
    assert run(project, "pack-diff", str(german), str(chinese)).exit_code != 0


def test_the_command_is_registered():
    assert "pack-diff" in CliRunner().invoke(main, ["--help"]).output
