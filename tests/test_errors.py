import re
import shutil
from pathlib import Path

import pytest

from v4t_translate.cli import run
from v4t_translate.errors import (
    EXIT_CODES,
    CatalogError,
    CheckFailed,
    ConfigError,
    EmitError,
    LockError,
    ParseError,
    SourceError,
    V4TError,
    exit_code_table,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "exit-codes.md"

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""

CLASSES = (V4TError, ConfigError, SourceError, ParseError, CatalogError,
           EmitError, LockError, CheckFailed)


@pytest.fixture
def unextracted(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path / "v4t-translate.toml"


# -- the remedy ---------------------------------------------------------


def test_an_error_can_carry_one():
    assert V4TError("broken", remedy="fix it").remedy == "fix it"


def test_the_remedy_is_not_in_the_message():
    # One is a statement about the past and the other is an instruction, and
    # they get written differently.
    assert str(V4TError("broken", remedy="fix it")) == "broken"


def test_no_remedy_is_an_empty_string():
    assert V4TError("broken").remedy == ""


@pytest.mark.parametrize("cls", CLASSES)
def test_every_class_accepts_one(cls):
    assert cls("broken", remedy="fix it").remedy == "fix it"


def test_a_parse_error_keeps_its_position_and_its_remedy():
    error = ParseError("bad token", path="V4T.rc", line=41, column=7,
                       remedy="check the quotes")
    assert str(error).startswith("V4T.rc:41:7:")
    assert error.remedy == "check the quotes"


def test_a_check_failure_keeps_its_counts_and_its_remedy():
    failure = CheckFailed("4 errors", error_count=4, remedy="fix them")
    assert failure.error_count == 4
    assert failure.remedy == "fix them"


# -- the codes ----------------------------------------------------------


@pytest.mark.parametrize("cls", CLASSES)
def test_every_class_has_a_code_and_a_kind(cls):
    assert isinstance(cls.exit_code, int)
    assert cls.kind


def test_the_check_code_is_two():
    # Every linter in the world uses 2 for "I found things".
    assert CheckFailed.exit_code == 2


def test_the_lock_code_is_its_own():
    # A script that hits one should retry, and it has to tell that apart from
    # everything else, none of which it should retry.
    assert LockError.exit_code == 4
    assert LockError.exit_code not in {
        cls.exit_code for cls in CLASSES if cls is not LockError
    }


def test_the_sysexits_ones_are_what_sysexits_says():
    assert SourceError.exit_code == 65
    assert EmitError.exit_code == 73
    assert ConfigError.exit_code == 78


def test_zero_is_in_the_table():
    # So the table reads as the whole set rather than as the failures.
    assert EXIT_CODES[0] == "everything worked"


@pytest.mark.parametrize("cls", CLASSES)
def test_every_class_code_is_in_the_table(cls):
    assert cls.exit_code in EXIT_CODES


def test_the_table_is_ordered():
    codes = [int(line.split()[0]) for line in exit_code_table().splitlines()]
    assert codes == sorted(codes)


def test_the_table_says_what_each_one_means():
    assert "the check found problems" in exit_code_table()


# -- the documentation ------------------------------------------------


def test_every_code_is_documented():
    text = DOC.read_text(encoding="utf-8")
    documented = {int(m) for m in re.findall(r"^\| (\d+) \|", text, re.M)}
    assert documented == set(EXIT_CODES)


def test_nothing_undocumented_is_claimed():
    text = DOC.read_text(encoding="utf-8")
    for code, meaning in EXIT_CODES.items():
        assert f"| {code} | {meaning} |" in text


def test_the_retry_example_uses_the_lock_code():
    assert f"-eq {LockError.exit_code}" in DOC.read_text(encoding="utf-8")


# -- what the shell sees ------------------------------------------------


def test_a_missing_catalog_exits_with_the_input_code(unextracted, capsys):
    code = run(["-c", str(unextracted), "build"])
    assert code == CatalogError.exit_code


def test_the_remedy_is_printed(unextracted, capsys):
    run(["-c", str(unextracted), "build"])
    assert "try: Run extract first." in capsys.readouterr().err


def test_the_remedy_is_on_its_own_line(unextracted, capsys):
    run(["-c", str(unextracted), "build"])
    lines = capsys.readouterr().err.strip().splitlines()
    assert lines[0].startswith("error:")
    assert lines[1].startswith("  try:")


def test_an_error_without_a_remedy_prints_one_line(tmp_path, capsys):
    missing = tmp_path / "nothing.toml"
    run(["-c", str(missing), "check"])
    assert "  try:" not in capsys.readouterr().err


def test_a_good_run_exits_zero(unextracted):
    assert run(["-c", str(unextracted), "extract"]) == 0
