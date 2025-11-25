import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "selfcheck.py"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def output():
    """One end-to-end run, shared by every test that reads it.

    Module scoped because it does a real round: extract, export, check twice,
    build twice and an audit. Running that once per assertion would be the
    slowest thing in the suite by an order of magnitude.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        timeout=300,
    )
    return result


# -- it works -----------------------------------------------------------


def test_the_round_completes(output):
    assert output.returncode == 0, output.stdout + output.stderr


def test_it_says_so(output):
    assert output.stdout.strip().endswith("all good")


@pytest.mark.parametrize("stage", [
    "extract", "export", "translate and check", "build",
    "build twice, byte for byte", "audit what was built",
])
def test_every_stage_ran(output, stage):
    assert f"== {stage}" in output.stdout


def test_each_step_says_what_it_did(output):
    # A CI log should show which step stopped, not a traceback fifteen frames
    # deep in click.
    assert "-> 0" in output.stdout


def test_it_reports_the_build_it_used(output):
    assert "catalog format" in output.stdout


def test_the_timestamps_are_pinned_for_the_run(output):
    # Otherwise the two builds it compares would differ on the date alone.
    assert "timestamps          pinned" in output.stdout


def test_it_leaves_nothing_behind(output, tmp_path):
    import tempfile

    leftovers = list(Path(tempfile.gettempdir()).glob("v4t-selfcheck-*"))
    assert leftovers == []


# -- it is the right kind of script -------------------------------------


def test_it_drives_the_command_line_rather_than_importing():
    # The point is to catch what the unit tests cannot: an entry point that
    # was never registered, a module missing from the wheel.
    text = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess.run" in text
    assert "from v4t_translate" not in text


def test_it_does_not_depend_on_pytest():
    # It has to run against an installed wheel with nothing else present.
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import pytest" not in text


def test_it_writes_its_own_source_file():
    assert "DIALOGEX" in SCRIPT.read_text(encoding="utf-8")


def test_it_covers_the_constructs_that_have_broken():
    text = SCRIPT.read_text(encoding="utf-8")
    for construct in ("ACCELERATORS", "STRINGTABLE", "%.1fV", "MENUITEM"):
        assert construct in text


# -- ci runs it ---------------------------------------------------------


def test_the_workflow_runs_it():
    assert "tools/selfcheck.py" in WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_installs_a_wheel_first():
    # Against the checkout it would prove nothing this suite does not.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m build --wheel" in text
    assert "pip install dist/*.whl" in text


def test_the_selfcheck_runs_on_windows_too():
    # The panel build machines are Windows, and the encoding and path handling
    # only ever break there.
    text = WORKFLOW.read_text(encoding="utf-8")
    selfcheck = text.split("selfcheck:", 1)[1]
    assert "windows-latest" in selfcheck
