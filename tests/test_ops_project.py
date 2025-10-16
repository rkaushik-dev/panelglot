import shutil
from pathlib import Path

import pytest

from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError, ConfigError
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.project import (
    font_search_path,
    require_catalog,
    selected_locales,
)

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]
"""

#: Every operation that used to carry its own copy of the loader.
CALLERS = ("adopt", "build", "check", "estimate", "pretranslate", "prune",
           "stats", "sync")

OPS = Path(__file__).resolve().parents[1] / "src" / "v4t_translate" / "ops"


@pytest.fixture
def unextracted(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return load_config(tmp_path / "v4t-translate.toml")


@pytest.fixture
def project(unextracted):
    extract_project(unextracted)
    return unextracted


# -- the catalog --------------------------------------------------------


def test_an_existing_catalog_loads(project):
    assert len(require_catalog(project)) > 0


def test_a_missing_catalog_is_refused(unextracted):
    with pytest.raises(CatalogError):
        require_catalog(unextracted)


def test_the_refusal_names_the_file(unextracted):
    with pytest.raises(CatalogError, match=r"\.json"):
        require_catalog(unextracted)


def test_the_refusal_says_what_to_run(unextracted):
    # An operation that refuses because a file is missing has one job beyond
    # refusing, which is to say what to run instead. That goes in the remedy,
    # not in the message: one is an instruction and the other is not.
    with pytest.raises(CatalogError) as caught:
        require_catalog(unextracted)
    assert "Run extract first" in caught.value.remedy


def test_a_reason_is_appended(unextracted):
    with pytest.raises(CatalogError) as caught:
        require_catalog(unextracted, because="because I said so")
    assert caught.value.remedy.endswith("because I said so")


def test_no_reason_leaves_no_trailing_space(unextracted):
    with pytest.raises(CatalogError) as caught:
        require_catalog(unextracted)
    assert not caught.value.remedy.endswith(" ")


# -- the language selection ---------------------------------------------


def test_nothing_named_means_all_of_them(project):
    assert [e.tag for e in selected_locales(project, None)] == ["de-DE", "zh-TW"]


def test_an_empty_list_means_all_of_them(project):
    assert len(selected_locales(project, [])) == 2


def test_one_named_language_comes_back(project):
    assert [e.tag for e in selected_locales(project, ["zh-TW"])] == ["zh-TW"]


def test_the_order_asked_for_is_kept(project):
    asked = ["zh-TW", "de-DE"]
    assert [e.tag for e in selected_locales(project, asked)] == asked


def test_an_unconfigured_language_is_an_error_not_an_empty_run(project):
    with pytest.raises(ConfigError, match="fr-FR"):
        selected_locales(project, ["fr-FR"])


def test_the_error_lists_the_configured_ones(project):
    with pytest.raises(ConfigError, match="de-DE"):
        selected_locales(project, ["fr-FR"])


# -- the font path ------------------------------------------------------


def test_fonts_are_looked_for_beside_the_project_first(project):
    assert font_search_path(project)[0] == project.root / "fonts"


def test_the_project_root_is_the_fallback(project):
    assert font_search_path(project)[-1] == project.root


# -- nobody kept a copy -------------------------------------------------


@pytest.mark.parametrize("name", CALLERS)
def test_no_operation_still_has_its_own_loader(name):
    # Eight copies, seven of which said "Run extract first" and one of which
    # said "Run extract before build". None was wrong and none was worth
    # reading twice.
    text = (OPS / f"{name}.py").read_text(encoding="utf-8")
    assert "def _load_catalog" not in text


@pytest.mark.parametrize("name", CALLERS)
def test_every_operation_uses_the_shared_one(name):
    text = (OPS / f"{name}.py").read_text(encoding="utf-8")
    assert "require_catalog" in text


@pytest.mark.parametrize("name", ("build", "check"))
def test_no_operation_still_has_its_own_selector(name):
    text = (OPS / f"{name}.py").read_text(encoding="utf-8")
    assert "def _select(" not in text


def test_the_font_path_has_one_definition():
    text = (OPS / "check.py").read_text(encoding="utf-8")
    assert "def _font_search_path" not in text
