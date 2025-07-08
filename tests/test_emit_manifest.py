import json
import shutil
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.emit.manifest import (
    MANIFEST_NAME,
    MANIFEST_VERSION,
    build_manifest,
    file_hash,
)
from v4t_translate.ops.build import build_project
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"
output_dir = "out"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]

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
    return config


def translate(config, tag, pairs):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for source, target in pairs.items():
        translations.set(message_key(source),
                         Translation(text=target, state=TranslationState.APPROVED))
    save_translations(path, translations)


@pytest.fixture
def manifest(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    result = build_project(project)
    return build_manifest(project, result, tool_version="0.3.0",
                          now=datetime(2025, 7, 8, 9, 30, tzinfo=timezone.utc))


def test_file_hash_is_stable(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"hello")
    assert file_hash(path) == file_hash(path)


def test_file_hash_changes_with_content(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"hello")
    before = file_hash(path)
    path.write_bytes(b"hello there")
    assert file_hash(path) != before


def test_the_header(manifest):
    payload = manifest.as_dict()
    assert payload["manifest"] == MANIFEST_VERSION
    assert payload["project"] == "V4T-TIJ"
    assert payload["tool_version"] == "0.3.0"
    assert payload["built_at"] == "2025-07-08T09:30:00+00:00"


def test_the_catalog_hash_is_recorded(project, manifest):
    assert manifest.catalog_hash == file_hash(project.catalog_path())


def test_two_builds_from_one_catalog_agree(project):
    first = build_manifest(project, build_project(project), tool_version="0.3.0")
    second = build_manifest(project, build_project(project), tool_version="0.3.0")
    assert first.catalog_hash == second.catalog_hash
    assert [o["sha256"] for o in first.outputs] == [o["sha256"] for o in second.outputs]


def test_a_changed_catalog_shows_up(project):
    before = build_manifest(project, build_project(project), tool_version="0.3.0")

    source = project.root / "src" / "V4T.rc"
    source.write_text(
        source.read_text(encoding="utf-8").replace("Module size", "Module width"),
        encoding="utf-8",
    )
    extract_project(project)

    after = build_manifest(project, build_project(project), tool_version="0.3.0")
    assert after.catalog_hash != before.catalog_hash


def test_every_output_is_listed(manifest):
    kinds = {(entry["locale"], entry["kind"]) for entry in manifest.outputs}
    assert ("de-DE", "po") in kinds
    assert ("zh-TW", "rc") in kinds
    assert len(manifest.outputs) == 4


def test_an_output_carries_its_hash_and_size(manifest):
    entry = next(e for e in manifest.outputs if e["kind"] == "po")
    assert len(entry["sha256"]) == 32
    assert entry["bytes"] > 0


def test_the_path_is_relative_to_the_project(manifest):
    assert all(not str(e["path"]).startswith("/") for e in manifest.outputs)
    assert any(e["path"] == "out/de-DE.po" for e in manifest.outputs)


def test_coverage_is_recorded_per_output(manifest):
    entry = next(e for e in manifest.outputs
                 if e["locale"] == "de-DE" and e["kind"] == "po")
    assert entry["translated"] == 1
    assert 0 < entry["coverage"] < 1


def test_an_untranslated_language_is_zero(manifest):
    entry = next(e for e in manifest.outputs
                 if e["locale"] == "zh-TW" and e["kind"] == "po")
    assert entry["translated"] == 0
    assert entry["coverage"] == 0


def test_the_per_language_summary(manifest):
    assert set(manifest.locales) == {"de-DE", "zh-TW"}


def test_it_writes_valid_json(tmp_path, manifest):
    path = manifest.write(tmp_path / "out" / MANIFEST_NAME)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["project"] == "V4T-TIJ"


def test_it_creates_the_directory(tmp_path, manifest):
    path = manifest.write(tmp_path / "deep" / "deeper" / MANIFEST_NAME)
    assert path.exists()


def test_the_summary_reads(manifest):
    text = manifest.summary()
    assert text.startswith("V4T-TIJ 0.3.0")
    assert "4 files" in text


def test_the_command_line_writes_one(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "build", "--manifest",
    ])
    assert result.exit_code == 0

    path = project.root / "out" / MANIFEST_NAME
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["project"] == "V4T-TIJ"


def test_the_command_line_takes_a_path(project, tmp_path):
    out = tmp_path / "release" / "what-shipped.json"
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "build", "--manifest", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()


def test_no_manifest_by_default(project):
    runner = CliRunner()
    runner.invoke(main, ["-c", str(project.root / "v4t-translate.toml"), "build"])
    assert not (project.root / "out" / MANIFEST_NAME).exists()


def test_a_dry_run_writes_no_manifest(project):
    runner = CliRunner()
    runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "build", "--dry-run", "--manifest",
    ])
    assert not (project.root / "out" / MANIFEST_NAME).exists()
