import json
import shutil

import pytest
from click.testing import CliRunner

from v4t_translate import __version__
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.emit.manifest import MANIFEST_NAME, build_manifest
from v4t_translate.errors import EmitError
from v4t_translate.ops.audit import audit_against, read_manifest
from v4t_translate.ops.build import build_project
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]

[[output]]
kind = "po"
path = "out/{locale}.po"
"""


@pytest.fixture
def released(tmp_path, sample_rc_path):
    """A built output directory with its manifest beside it."""
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")

    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    result = build_project(config)

    manifest = build_manifest(config, result, tool_version=__version__)
    manifest.write(tmp_path / "out" / MANIFEST_NAME)

    return config


def manifest_path(config):
    return config.root / "out" / MANIFEST_NAME


def out(config):
    return config.root / "out"


def run(config, *args):
    return CliRunner().invoke(main, [
        "-c", str(config.root / "v4t-translate.toml"), "audit", *args,
    ])


# -- reading the manifest -----------------------------------------------


def test_a_manifest_reads(released):
    assert read_manifest(manifest_path(released))["project"] == "V4T-TIJ"


def test_a_missing_manifest_is_refused(tmp_path):
    with pytest.raises(EmitError, match="does not exist"):
        read_manifest(tmp_path / "nowhere.json")


def test_broken_json_is_refused(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(EmitError, match="not valid JSON"):
        read_manifest(path)


def test_something_that_is_not_a_manifest_is_refused(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(EmitError, match="does not hold a manifest"):
        read_manifest(path)


def test_a_newer_format_is_refused(released):
    payload = read_manifest(manifest_path(released))
    payload["manifest"] = 99
    manifest_path(released).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EmitError, match="reads up to"):
        read_manifest(manifest_path(released))


# -- a build that matches -----------------------------------------------


def test_a_fresh_build_matches_its_manifest(released):
    result = audit_against(manifest_path(released), released.root)
    assert result.matches
    assert result.problems == []


def test_every_output_is_checked(released):
    result = audit_against(manifest_path(released), released.root)
    assert len(result.files) == 2


def test_the_summary_names_the_project(released):
    result = audit_against(manifest_path(released), released.root)
    assert "V4T-TIJ" in result.summary()


def test_the_manifest_is_never_unexpected(released):
    # It usually sits in the directory it describes.
    result = audit_against(manifest_path(released), released.root)
    assert MANIFEST_NAME not in result.unexpected


def test_the_root_defaults_are_the_callers_business(released):
    # Passing a different root finds nothing, which is the honest answer.
    result = audit_against(manifest_path(released), released.root / "src")
    assert all(v.state == "missing" for v in result.files)


# -- a build that does not ----------------------------------------------


def test_a_missing_file_is_found(released):
    (out(released) / "de-DE.po").unlink()

    result = audit_against(manifest_path(released), released.root)
    assert not result.matches
    assert [v.state for v in result.problems] == ["missing"]
    assert "is not there" in result.problems[0].describe()


def test_a_truncated_file_reads_as_resized(released):
    # Checked before the hash, because the size is free and it is the one that
    # says the file was truncated rather than edited.
    path = out(released) / "de-DE.po"
    path.write_bytes(path.read_bytes()[:20])

    result = audit_against(manifest_path(released), released.root)
    assert result.problems[0].state == "resized"
    assert "bytes" in result.problems[0].describe()


def test_an_edited_file_of_the_same_size_reads_as_changed(released):
    path = out(released) / "de-DE.po"
    data = bytearray(path.read_bytes())
    data[-2] = ord("X")
    path.write_bytes(bytes(data))

    result = audit_against(manifest_path(released), released.root)
    assert result.problems[0].state == "changed"
    assert "hashes" in result.problems[0].describe()


def test_a_rebuild_of_one_language_is_caught(released):
    # Somebody fixes one string, rebuilds one language, and the archive is now
    # half from each run.
    path = out(released) / "zh-TW.po"
    path.write_text(path.read_text(encoding="utf-8") + "\n# rebuilt\n",
                    encoding="utf-8")

    result = audit_against(manifest_path(released), released.root)
    assert [v.path for v in result.problems] == ["out/zh-TW.po"]


# -- files nobody expected ----------------------------------------------


def test_an_extra_file_is_reported(released):
    # An extra .v4l on a card is how a panel loads a pack from the previous
    # release, and nothing else looks for it.
    (out(released) / "fr-FR.po").write_text("stray", encoding="utf-8")

    result = audit_against(manifest_path(released), released.root)
    assert result.unexpected == ["out/fr-FR.po"]
    assert not result.matches


def test_extensions_narrow_what_counts(released):
    (out(released) / "build.log").write_text("noise", encoding="utf-8")

    result = audit_against(manifest_path(released), released.root,
                           extensions=(".po",))
    assert result.unexpected == []


def test_without_the_filter_everything_counts(released):
    (out(released) / "build.log").write_text("noise", encoding="utf-8")
    assert audit_against(manifest_path(released), released.root).unexpected


def test_a_nested_extra_file_is_found(released):
    (out(released) / "old").mkdir()
    (out(released) / "old" / "de-DE.po").write_text("last release",
                                                    encoding="utf-8")
    result = audit_against(manifest_path(released), released.root)
    assert "out/old/de-DE.po" in result.unexpected


# -- the command --------------------------------------------------------


def test_the_command_passes_a_good_build(released):
    result = run(released, str(manifest_path(released)))
    assert result.exit_code == 0
    assert "match the manifest" in result.output


def test_the_command_fails_a_changed_one(released):
    (out(released) / "de-DE.po").unlink()
    result = run(released, str(manifest_path(released)))
    assert result.exit_code != 0
    assert "is not there" in result.output


def test_the_command_defaults_to_the_manifests_directory(released):
    assert run(released, str(manifest_path(released))).exit_code == 0


def test_the_command_takes_a_root(released):
    result = run(released, str(manifest_path(released)), "--root", str(released.root))
    assert result.exit_code == 0


def test_the_command_filters_extensions(released):
    (out(released) / "build.log").write_text("noise", encoding="utf-8")
    assert run(released, str(manifest_path(released)), "--extension", ".po").exit_code == 0


def test_the_command_is_registered():
    assert "audit" in CliRunner().invoke(main, ["--help"]).output
