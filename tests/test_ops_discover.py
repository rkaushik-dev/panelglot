import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.discover import SKIP_DIRECTORIES, discover_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"

RESOURCE_H = """\
#define IDC_STATIC              -1
#define IDD_BARCODE_PROPS       101
#define IDC_BAR_HEIGHT          1001
"""

INCLUDING_RC = """\
#include "resource.h"
#include "pages.rc"

IDD_MAIN DIALOGEX 0, 0, 100, 100
BEGIN
    LTEXT "Bar Height",IDC_STATIC,7,7,49,8
END
"""

INCLUDED_RC = """\
IDD_PAGE DIALOGEX 0, 0, 100, 100
BEGIN
    LTEXT "Width",IDC_STATIC,7,7,49,8
END
"""

STRINGS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">V4T Mobile</string>
</resources>
"""


@pytest.fixture
def tree(tmp_path):
    """A source tree shaped like the real one."""
    product = tmp_path / "V4T-TIJ" / "V4T"
    product.mkdir(parents=True)
    (product / "V4T.rc").write_text(INCLUDING_RC, encoding="utf-8")
    (product / "pages.rc").write_text(INCLUDED_RC, encoding="utf-8")
    (product / "resource.h").write_text(RESOURCE_H, encoding="utf-8")

    mini = tmp_path / "V4T-Mini" / "src"
    mini.mkdir(parents=True)
    shutil.copy(FIXTURES / "v4t_lang.h", mini / "v4t_lang.h")
    (mini / "board.h").write_text("#define PORT_A 0x40\n", encoding="utf-8")

    mobile = tmp_path / "V4T-Mobile" / "res" / "values"
    mobile.mkdir(parents=True)
    (mobile / "strings.xml").write_text(STRINGS_XML, encoding="utf-8")

    return tmp_path


def kinds(found):
    return {entry.kind for entry in found.sources}


def paths(found):
    return {entry.path for entry in found.sources}


# -- what it finds ------------------------------------------------------


def test_all_three_kinds_are_found(tree):
    assert kinds(discover_sources(tree)) == {"rc", "cheader", "androidxml"}


def test_the_main_resource_script_is_a_source(tree):
    assert "V4T-TIJ/V4T/V4T.rc" in paths(discover_sources(tree))


def test_a_script_another_one_includes_is_not(tree):
    # Listing a property page as its own source extracts the same strings
    # twice.
    found = discover_sources(tree)
    assert "V4T-TIJ/V4T/pages.rc" not in paths(found)
    assert "pages.rc" in found.included


def test_the_string_table_header_is_a_source(tree):
    assert "V4T-Mini/src/v4t_lang.h" in paths(discover_sources(tree))


def test_a_header_of_defines_is_not(tree):
    found = discover_sources(tree)
    assert "V4T-TIJ/V4T/resource.h" not in paths(found)
    assert any("symbols key" in note for note in found.skipped)


def test_a_header_of_neither_is_ignored(tree):
    found = discover_sources(tree)
    assert "V4T-Mini/src/board.h" not in paths(found)
    assert not any("board.h" in note for note in found.skipped)


def test_the_android_strings_are_a_source(tree):
    assert "V4T-Mobile/res/values/strings.xml" in paths(discover_sources(tree))


def test_a_strings_xml_outside_values_is_not(tree):
    stray = tree / "notes"
    stray.mkdir()
    (stray / "strings.xml").write_text(STRINGS_XML, encoding="utf-8")

    found = discover_sources(tree)
    assert "notes/strings.xml" not in paths(found)
    assert any("values directory" in note for note in found.skipped)


def test_a_symbol_file_beside_a_script_is_noted(tree):
    entry = next(e for e in discover_sources(tree).sources if e.kind == "rc")
    assert entry.symbols == "V4T-TIJ/V4T/resource.h"


def test_each_source_says_why_it_is_one(tree):
    for entry in discover_sources(tree).sources:
        assert len(entry.reason) > 15


def test_the_description_carries_the_symbols(tree):
    entry = next(e for e in discover_sources(tree).sources if e.kind == "rc")
    assert "resource.h" in entry.describe()


# -- what it does not walk into -----------------------------------------


def test_the_usual_directories_are_skipped(tree):
    junk = tree / "node_modules" / "thing"
    junk.mkdir(parents=True)
    (junk / "strings.xml").write_text(STRINGS_XML, encoding="utf-8")

    assert "node_modules/thing/strings.xml" not in paths(discover_sources(tree))


def test_a_build_directory_is_skipped(tree):
    build = tree / "V4T-TIJ" / "Release"
    build.mkdir()
    (build / "V4T.rc").write_text(INCLUDING_RC, encoding="utf-8")

    assert "V4T-TIJ/Release/V4T.rc" not in paths(discover_sources(tree))


def test_the_skip_list_has_the_ones_that_hurt():
    assert {".git", "node_modules", "out"} <= SKIP_DIRECTORIES


def test_the_walk_has_a_depth_limit(tree):
    deep = tree
    for number in range(12):
        deep = deep / f"level{number}"
    deep.mkdir(parents=True)
    (deep / "V4T.rc").write_text(INCLUDING_RC, encoding="utf-8")

    assert not any("level11" in path for path in paths(discover_sources(tree)))


def test_an_empty_tree_finds_nothing(tmp_path):
    found = discover_sources(tmp_path)
    assert found.sources == []
    assert "nothing that looks like" in found.summary()


def test_a_file_that_cannot_be_read_is_not_a_source(tree):
    # Directories named like a header turn up in generated trees.
    (tree / "broken.h").mkdir()
    assert "broken.h" not in paths(discover_sources(tree))


# -- handing it to init -------------------------------------------------


def test_the_pairs_are_what_init_wants(tree):
    pairs = discover_sources(tree).as_pairs()
    assert ("rc", "V4T-TIJ/V4T/V4T.rc") in pairs


def test_the_summary_counts_them(tree):
    assert "3 sources" in discover_sources(tree).summary()


# -- the command --------------------------------------------------------


def run(*args, answer=None):
    return CliRunner().invoke(main, ["init", *args], input=answer)


def test_init_from_scaffolds_a_working_config(tree, tmp_path):
    project = tmp_path / "loc"
    result = run(str(project), "--name", "V4T-TIJ", "--from", str(tree),
                 "--locale", "de-DE", "--yes")

    assert result.exit_code == 0
    config = load_config(project / "v4t-translate.toml")
    assert len(config.sources) == 3


def test_the_paths_are_relative_to_the_project(tree, tmp_path):
    project = tmp_path / "loc"
    run(str(project), "--name", "V4T-TIJ", "--from", str(tree), "--yes")

    text = (project / "v4t-translate.toml").read_text(encoding="utf-8")
    assert "../V4T-TIJ/V4T/V4T.rc" in text


def test_it_says_what_it_found(tree, tmp_path):
    output = run(str(tmp_path / "loc"), "--name", "V4T-TIJ",
                 "--from", str(tree), "--yes").output
    assert "V4T.rc" in output
    assert "nothing else includes" in output


def test_it_asks_first(tree, tmp_path):
    output = run(str(tmp_path / "loc"), "--name", "V4T-TIJ",
                 "--from", str(tree), answer="y\n").output
    assert "Use these?" in output


def test_saying_no_leaves_the_config_empty(tree, tmp_path):
    project = tmp_path / "loc"
    run(str(project), "--name", "V4T-TIJ", "--from", str(tree), answer="n\n")

    text = (project / "v4t-translate.toml").read_text(encoding="utf-8")
    assert "Nothing to read yet" in text


def test_named_sources_still_work_alongside_it(tree, tmp_path):
    project = tmp_path / "loc"
    run(str(project), "--name", "V4T-TIJ", "--from", str(tree),
        "--source", "rc:../elsewhere/other.rc", "--yes")

    text = (project / "v4t-translate.toml").read_text(encoding="utf-8")
    assert "../elsewhere/other.rc" in text
    assert "V4T.rc" in text


def test_without_the_flag_nothing_is_searched(tmp_path):
    project = tmp_path / "loc"
    run(str(project), "--name", "V4T-TIJ")
    text = (project / "v4t-translate.toml").read_text(encoding="utf-8")
    assert "Nothing to read yet" in text
