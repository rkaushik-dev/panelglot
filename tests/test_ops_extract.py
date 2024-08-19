import shutil

import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_catalog, load_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.config import load_config
from v4t_translate.errors import SourceError
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"
catalog_dir = "catalog"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."zh-TW"]

[locale."de-DE"]
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return load_config(tmp_path / "v4t-translate.toml")


def test_a_first_run_writes_the_catalog(project):
    result = extract_project(project)
    assert project.catalog_path().exists()
    assert result.message_count > 30
    assert result.report.removed == []
    assert len(result.report.added) == result.message_count


def test_a_first_run_writes_a_file_per_locale(project):
    result = extract_project(project)
    assert project.translations_path("zh-TW").exists()
    assert project.translations_path("de-DE").exists()
    assert len(result.written) == 3


def test_the_catalog_reloads(project):
    extract_project(project)
    catalog = load_catalog(project.catalog_path())
    assert catalog.project == "V4T-TIJ"
    assert catalog.get(message_key("Bar Height")).max_width_px == 54


def test_a_second_run_changes_nothing(project):
    extract_project(project)
    before = project.catalog_path().read_bytes()
    result = extract_project(project)
    assert result.report.is_noop()
    assert project.catalog_path().read_bytes() == before


def test_dry_run_writes_nothing(project):
    result = extract_project(project, dry_run=True)
    assert result.written == []
    assert not project.catalog_path().exists()
    assert result.message_count > 30


def test_dry_run_still_reports_what_would_change(project):
    extract_project(project)
    _edit_source(project, "Bar Height", "Bar height")
    result = extract_project(project, dry_run=True)
    assert message_key("Bar height") in result.report.added
    assert message_key("Bar Height") in result.report.removed


def test_editing_the_english_carries_the_translation(project):
    extract_project(project)

    translations = load_translations(project.translations_path("de-DE"))
    translations.set(message_key("This distance cannot be greater than print spacing"),
                     Translation(text="Dieser Abstand darf nicht groesser sein",
                                 state=TranslationState.APPROVED))
    from v4t_translate.catalog.store import save_translations
    save_translations(project.translations_path("de-DE"), translations)

    _edit_source(
        project,
        "This distance cannot be greater than print spacing",
        "This distance cannot be greater than the print spacing",
    )
    extract_project(project)

    after = load_translations(project.translations_path("de-DE"))
    carried = after.get(message_key("This distance cannot be greater than the print spacing"))
    assert carried.text.startswith("Dieser Abstand")
    assert carried.state is TranslationState.NEEDS_REVIEW


def test_a_missing_source_raises_by_default(project):
    (project.root / "src" / "V4T.rc").unlink()
    with pytest.raises(SourceError):
        extract_project(project)


def test_keep_going_records_the_skip(project):
    (project.root / "src" / "V4T.rc").unlink()
    result = extract_project(project, keep_going=True, dry_run=True)
    assert result.skipped and "src/V4T.rc" in result.skipped[0]
    assert result.message_count == 0


def test_warnings_are_collected_from_every_source(project):
    (project.root / "src" / "V4T.rc").write_text(
        'IDD_X DIALOGEX 0,0,100,50\nBEGIN\n  AUTOCHECKBOX "On",IDC_ON,1,1,4,10\nEND\n',
        encoding="utf-8",
    )
    result = extract_project(project, dry_run=True)
    assert any("too narrow" in w for w in result.warnings)


def test_stats_are_reported_per_source(project):
    result = extract_project(project, dry_run=True)
    stats = result.stats_by_source()
    assert list(stats) == ["src/V4T.rc"]
    assert stats["src/V4T.rc"]["dialogs"] == 2


def test_two_sources_merge_into_one_catalog(project, sample_rc_path):
    second = project.root / "src" / "Config.rc"
    second.write_text(
        'STRINGTABLE\nBEGIN\n'
        '  IDS_PRINT_STARTED "Print started"\n'
        '  IDS_ONLY_HERE     "Group Combination"\n'
        'END\n',
        encoding="utf-8",
    )
    (project.root / "v4t-translate.toml").write_text(
        CONFIG + '\n[[source]]\nkind = "rc"\npath = "src/Config.rc"\n', encoding="utf-8"
    )
    config = load_config(project.root / "v4t-translate.toml")

    result = extract_project(config)
    shared = result.catalog.get(message_key("Print started"))
    assert shared.sources == ["src/Config.rc", "src/V4T.rc"]
    assert message_key("Group Combination") in result.catalog


def _edit_source(project, old, new):
    path = project.root / "src" / "V4T.rc"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
