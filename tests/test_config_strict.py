from pathlib import Path

import pytest

from v4t_translate.config import KNOWN_KEYS, KNOWN_TABLES, load_config
from v4t_translate.errors import ConfigError

REPO = Path(__file__).resolve().parents[1]

BASE = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def write(tmp_path, text):
    path = tmp_path / "v4t-translate.toml"
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path, text):
    return load_config(write(tmp_path, text))


# -- the sets themselves ------------------------------------------------


def test_every_documented_table_is_known():
    assert "project" in KNOWN_TABLES
    assert "provider" in KNOWN_TABLES


def test_every_table_with_keys_is_a_known_table():
    assert set(KNOWN_KEYS) <= KNOWN_TABLES


def test_the_project_keys_cover_the_paths():
    assert {"catalog_dir", "workbook_dir", "output_dir"} <= KNOWN_KEYS["project"]


def test_the_output_keys_use_the_file_spelling():
    # The file says "fallback" for a field called fallback_to_source, and one
    # of the two names is for people.
    assert "fallback" in KNOWN_KEYS["output"]
    assert "fallback_to_source" not in KNOWN_KEYS["output"]


# -- rejecting a typo ---------------------------------------------------


def test_a_good_file_still_loads(tmp_path):
    assert load(tmp_path, BASE).name == "V4T-TIJ"


def test_an_unknown_top_level_table_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="'sources'"):
        load(tmp_path, BASE + "\n[sources]\nkind = 'rc'\n")


def test_an_unknown_project_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="'glosary'"):
        load(tmp_path, BASE.replace('name = "V4T-TIJ"',
                                    'name = "V4T-TIJ"\nglosary = "g.csv"'))


def test_an_unknown_source_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="source 1"):
        load(tmp_path, BASE + '\n[[source]]\nkind = "rc"\npath = "b.rc"\n'
                              'encodings = "utf-8"\n')


def test_an_unknown_output_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="output 0"):
        load(tmp_path, BASE + '\n[[output]]\nkind = "po"\npath = "o.po"\n'
                              'fallbck = true\n')


def test_an_unknown_locale_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"\[locale\.de-DE\]"):
        load(tmp_path, BASE + 'fnt = "x.fmx"\n')


def test_an_unknown_check_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"\[check\]"):
        load(tmp_path, BASE + '\n[check]\nfail_at = "error"\n')


def test_an_unknown_protected_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"\[protected\]"):
        load(tmp_path, BASE + '\n[protected]\npatern = []\n')


# -- what it says -------------------------------------------------------


def test_the_refusal_lists_what_the_table_takes(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, BASE.replace('name = "V4T-TIJ"',
                                    'name = "V4T-TIJ"\nglosary = "g.csv"'))
    assert "catalog_dir" in caught.value.remedy


def test_a_close_typo_gets_a_suggestion(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, BASE.replace('name = "V4T-TIJ"',
                                    'name = "V4T-TIJ"\nglosary = "g.csv"'))
    assert "Did you mean 'glossary'?" in caught.value.remedy


def test_something_unlike_anything_gets_no_suggestion(tmp_path):
    # A suggestion that is wrong sends somebody off to try it.
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, BASE.replace('name = "V4T-TIJ"',
                                    'name = "V4T-TIJ"\nzzzz = 1'))
    assert "Did you mean" not in caught.value.remedy


def test_the_message_names_the_file(tmp_path):
    with pytest.raises(ConfigError, match="v4t-translate.toml"):
        load(tmp_path, BASE + "\n[sources]\nkind = 'rc'\n")


def test_two_typos_are_both_named(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, BASE.replace(
            'name = "V4T-TIJ"', 'name = "V4T-TIJ"\nglosary = "g"\nwaiver = "w"'))
    assert "'glosary'" in str(caught.value)
    assert "'waiver'" in str(caught.value)


# -- the files that ship ------------------------------------------------


def test_the_worked_example_still_loads():
    # It is the one config in the repository somebody copies from.
    assert load_config(REPO / "v4t-translate.toml").name


def test_a_generated_project_still_loads(tmp_path):
    from v4t_translate.ops.init import init_project

    init_project(tmp_path, name="V4T-Mini", locales=["de-DE"],
                 sources=[("rc", "src/V4T.rc")])
    assert load_config(tmp_path / "v4t-translate.toml").name == "V4T-Mini"


def test_every_key_the_generator_writes_is_known(tmp_path):
    from v4t_translate.ops.init import init_project

    init_project(tmp_path, name="V4T-Mini", locales=["de-DE"],
                 sources=[("rc", "src/V4T.rc")])
    load_config(tmp_path / "v4t-translate.toml")
