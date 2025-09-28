import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError, EmitError
from v4t_translate.locales import resolve
from v4t_translate.ops.build import build_project, resolve_output_path
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
kind = "rc"
path = "out/{locale}/V4T.rc"
source = "src/V4T.rc"

[[output]]
kind = "po"
path = "out/po/{locale}.po"

[[output]]
kind = "androidxml"
path = "out/res/values-{qualifier}/strings.xml"
locale = "de-DE"
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


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("out/{locale}/V4T.rc", "out/de-DE/V4T.rc"),
        ("out/{language}.rc", "out/de.rc"),
        ("res/values-{qualifier}/strings.xml", "res/values-de-rDE/strings.xml"),
        ("{project}-{locale}.po", "V4T-TIJ-de-DE.po"),
        ("packs/{locale}-{codepage}.v4l", "packs/de-DE-1252.v4l"),
    ],
)
def test_path_templates(template, expected):
    assert resolve_output_path(template, project="V4T-TIJ",
                               locale=resolve("de-DE")) == expected


def test_outputs_are_read_from_the_config(project):
    assert [o.kind for o in project.outputs] == ["rc", "po", "androidxml"]
    assert project.outputs[2].locales == ("de-DE",)
    assert project.outputs[0].source is not None


def test_output_describe(project):
    assert project.outputs[0].describe() == "rc -> out/{locale}/V4T.rc (all)"
    assert project.outputs[2].describe().endswith("(de-DE)")


def test_a_build_produces_every_output(project):
    result = build_project(project)
    kinds = {(tag, kind) for tag, kind, _ in result.outputs}
    assert ("de-DE", "rc") in kinds
    assert ("zh-TW", "rc") in kinds
    assert ("de-DE", "androidxml") in kinds
    assert ("zh-TW", "androidxml") not in kinds


def test_the_files_land_where_the_template_says(project):
    build_project(project)
    assert (project.root / "out" / "de-DE" / "V4T.rc").exists()
    assert (project.root / "out" / "po" / "zh-TW.po").exists()
    assert (project.root / "out" / "res" / "values-de-rDE" / "strings.xml").exists()


def test_translations_reach_the_output(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    build_project(project)
    text = (project.root / "out" / "de-DE" / "V4T.rc").read_text(encoding="cp1252")
    assert '"Druck gestartet"' in text


def test_no_scratch_files_are_left_behind(project):
    build_project(project)
    leftovers = [p for p in (project.root / "out").rglob("*") if ".building" in p.name]
    assert leftovers == []


def test_dry_run_writes_nothing(project):
    result = build_project(project, dry_run=True)
    assert result.outputs
    assert result.written == []
    assert not (project.root / "out").exists()


def test_a_build_can_be_limited_to_one_locale(project):
    result = build_project(project, locales=["de-DE"])
    assert result.locales() == ["de-DE"]
    assert not (project.root / "out" / "zh-TW").exists()


def test_the_summary_counts(project):
    result = build_project(project)
    assert "outputs across 2 languages" in result.summary()
    assert result.total_bytes > 0


def test_a_project_with_no_outputs_says_so(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(
        CONFIG.split("[[output]]")[0], encoding="utf-8"
    )
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    result = build_project(config)
    assert result.outputs == []
    assert any("nothing to build" in w for w in result.warnings)


def test_build_before_extract(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    with pytest.raises(CatalogError, match="Run extract first"):
        build_project(config)


def test_nothing_is_written_when_one_output_fails(project):
    # Traditional Chinese into a cp950 resource is fine, but a German string
    # holding a Chinese character is not, and it must not leave the earlier
    # outputs on disk.
    translate(project, "de-DE", {"Print started": "列印已開始"})
    with pytest.raises(EmitError):
        build_project(project)
    assert not (project.root / "out").exists()


def test_the_command_line_build(project):
    runner = CliRunner()
    result = runner.invoke(
        main, ["-c", str(project.root / "v4t-translate.toml"), "build"]
    )
    assert result.exit_code == 0
    assert "de-DE rc:" in result.output


def test_the_build_refuses_a_failing_check(project):
    translate(project, "de-DE",
              {"Please input from %.1fV to %.1fV.": "Bitte einen Wert eingeben."})
    runner = CliRunner()
    result = runner.invoke(
        main, ["-c", str(project.root / "v4t-translate.toml"), "build"]
    )
    assert result.exit_code != 0
    assert not (project.root / "out").exists()


def test_no_check_builds_anyway(project):
    translate(project, "de-DE",
              {"Please input from %.1fV to %.1fV.": "Bitte einen Wert eingeben."})
    runner = CliRunner()
    result = runner.invoke(
        main, ["-c", str(project.root / "v4t-translate.toml"), "build", "--no-check"]
    )
    assert result.exit_code == 0
    assert (project.root / "out" / "de-DE" / "V4T.rc").exists()


def test_the_command_line_dry_run(project):
    runner = CliRunner()
    result = runner.invoke(
        main, ["-c", str(project.root / "v4t-translate.toml"), "build", "--dry-run"]
    )
    assert "dry run, nothing written" in result.output
    assert not (project.root / "out").exists()
