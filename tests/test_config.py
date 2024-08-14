from pathlib import Path

import pytest

from v4t_translate.config import (
    CONFIG_FILENAME,
    DEFAULT_PROTECTED_PATTERNS,
    CheckSettings,
    find_config,
    load_config,
)
from v4t_translate.errors import ConfigError

MINIMAL = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"
"""

FULL = """
[project]
name = "V4T-TIJ"
source_locale = "en-US"
catalog_dir = "cat"
workbook_dir = "sheets"
output_dir = "build"
glossary = "glossary/terms.csv"

[[source]]
kind = "rc"
path = "../V4T-TIJ/V4T/V4T.rc"
symbols = "../V4T-TIJ/V4T/resource.h"
encoding = "cp1252"

[[source]]
kind = "androidxml"
path = "../V4T-Mobile/res/values/strings.xml"

[protected]
patterns = ["SENC", "MCR"]

[locale."zh-TW"]
workbook = "sheets/taiwan.xlsx"
panel = "tij-800x600"
font = "fonts/pmingliu-9.fmx"

[locale."de-DE"]
workbook = "sheets/german.xlsx"

[check]
fail_on = "warning"
disable = ["glossary"]
promote = ["fitting"]
"""


def write(tmp_path: Path, text: str, name: str = CONFIG_FILENAME) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_config(tmp_path):
    config = load_config(write(tmp_path, MINIMAL))
    assert config.name == "V4T-TIJ"
    assert config.root == tmp_path
    assert config.source_locale.tag == "en-US"
    assert len(config.sources) == 1
    assert config.sources[0].kind == "rc"
    assert config.sources[0].path == Path("src/V4T.rc")
    assert config.locales == []


def test_defaults_when_nothing_is_said(tmp_path):
    config = load_config(write(tmp_path, MINIMAL))
    assert config.catalog_dir == Path("catalog")
    assert config.workbook_dir == Path("workbooks")
    assert config.output_dir == Path("out")
    assert config.glossary is None
    assert config.check.fail_on == "error"


def test_full_config_sources(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert [s.kind for s in config.sources] == ["rc", "androidxml"]
    assert config.sources[0].encoding == "cp1252"
    assert config.sources[0].symbols == Path("../V4T-TIJ/V4T/resource.h")
    assert config.sources[1].symbols is None
    assert config.sources[1].encoding == "utf-8-sig"


def test_source_describe(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert config.sources[0].describe() == "rc:../V4T-TIJ/V4T/V4T.rc"


def test_full_config_locales(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert config.target_tags() == ["zh-TW", "de-DE"]
    entry = config.locale_entry("zh-TW")
    assert entry.panel == "tij-800x600"
    assert entry.font == Path("fonts/pmingliu-9.fmx")


def test_locale_lookup_accepts_an_alias(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert config.locale_entry("Taiwan").tag == "zh-TW"


def test_an_unconfigured_locale_names_the_configured_ones(tmp_path):
    config = load_config(write(tmp_path, FULL))
    with pytest.raises(ConfigError) as excinfo:
        config.locale_entry("fr-FR")
    assert "zh-TW" in str(excinfo.value)


def test_catalog_and_translation_paths(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert config.catalog_path() == tmp_path / "cat" / "v4t-tij.json"
    assert config.translations_path("zh-TW") == tmp_path / "cat" / "zh-TW.json"


def test_workbook_path_from_the_locale_entry(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert config.workbook_path("zh-TW") == tmp_path / "sheets" / "taiwan.xlsx"


def test_workbook_path_falls_back_to_a_generated_name(tmp_path):
    config = load_config(write(tmp_path, FULL + '\n[locale."fr-FR"]\n'))
    assert config.workbook_path("fr-FR") == tmp_path / "sheets" / "V4T-TIJ - French.xlsx"


def test_protected_patterns_extend_the_defaults(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert "SENC" in config.protected_patterns
    for pattern in DEFAULT_PROTECTED_PATTERNS:
        assert pattern in config.protected_patterns


def test_protected_patterns_can_replace_the_defaults(tmp_path):
    text = MINIMAL + '\n[protected]\nreplace_defaults = true\npatterns = ["only"]\n'
    config = load_config(write(tmp_path, text))
    assert config.protected_patterns == ("only",)


def test_check_settings(tmp_path):
    config = load_config(write(tmp_path, FULL))
    assert config.check.fail_on == "warning"
    assert config.check.disabled_rules == ("glossary",)
    assert config.check.promoted_rules == ("fitting",)
    assert not config.check.is_enabled("glossary")
    assert config.check.is_enabled("fitting")


def test_check_settings_default_enables_everything():
    assert CheckSettings().is_enabled("anything")


def test_a_bad_fail_on_is_reported(tmp_path):
    text = MINIMAL + '\n[check]\nfail_on = "sometimes"\n'
    with pytest.raises(ConfigError, match="fail_on must be"):
        load_config(write(tmp_path, text))


def test_missing_project_section(tmp_path):
    with pytest.raises(ConfigError, match=r"missing \[project\]"):
        load_config(write(tmp_path, '[[source]]\nkind = "rc"\npath = "a.rc"\n'))


def test_missing_name(tmp_path):
    with pytest.raises(ConfigError, match="non-empty name"):
        load_config(write(tmp_path, '[project]\nname = "  "\n[[source]]\nkind="rc"\npath="a"\n'))


def test_no_sources_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="nothing to read"):
        load_config(write(tmp_path, '[project]\nname = "X"\n'))


def test_a_source_without_a_path_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="needs a 'kind' and a 'path'"):
        load_config(write(tmp_path, '[project]\nname="X"\n[[source]]\nkind="rc"\n'))


def test_an_unknown_locale_is_reported_with_the_file(tmp_path):
    text = MINIMAL + '\n[locale."xx-YY"]\n'
    with pytest.raises(ConfigError) as excinfo:
        load_config(write(tmp_path, text))
    assert CONFIG_FILENAME in str(excinfo.value)


def test_the_same_locale_under_two_names_is_rejected(tmp_path):
    text = MINIMAL + '\n[locale."zh-TW"]\n\n[locale."Taiwan"]\n'
    with pytest.raises(ConfigError, match="configured twice"):
        load_config(write(tmp_path, text))


def test_broken_toml_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write(tmp_path, "[project\nname = 1"))


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "nope.toml")


def test_find_config_walks_up(tmp_path):
    write(tmp_path, MINIMAL)
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert find_config(deep) == tmp_path / CONFIG_FILENAME


def test_find_config_gives_up_with_a_useful_message(tmp_path):
    deep = tmp_path / "a"
    deep.mkdir()
    with pytest.raises(ConfigError, match="or any parent directory"):
        find_config(deep)


def test_the_projects_own_config_file_parses():
    # The one checked in at the root is the worked example, so it has to load.
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / CONFIG_FILENAME)
    assert config.name == "V4T-TIJ"
    assert config.target_tags() == ["zh-TW", "de-DE"]
