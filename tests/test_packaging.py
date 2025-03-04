"""The package metadata and the CLI surface the CI workflow depends on.

Every command named in .github/workflows/ci.yml is asserted here. A workflow
that runs a command which was renamed fails on the runner and takes twenty
minutes to find out about; this fails in a second on the machine that renamed
it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import v4t_translate
from v4t_translate.cli import main

ROOT = Path(__file__).resolve().parents[1]

#: Must match the "for command in ..." line in the selfcheck job.
CI_COMMANDS = [
    "extract", "check", "export", "import", "build", "pretranslate", "stats", "doctor",
]


@pytest.fixture(scope="module")
def pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow():
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_the_version_has_exactly_one_home(pyproject):
    # It was declared in pyproject and in __init__ and they drifted within a
    # week, so pyproject reads it from the module now.
    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == (
        "src/v4t_translate/__init__.py"
    )


def test_the_version_looks_like_one():
    parts = v4t_translate.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_the_console_script_points_somewhere_real(pyproject):
    target = pyproject["project"]["scripts"]["v4t-translate"]
    module_name, _, attribute = target.partition(":")
    module = __import__(module_name, fromlist=[attribute])
    assert callable(getattr(module, attribute))


def test_the_declared_python_floor_is_the_one_we_run_on(pyproject):
    floor = pyproject["project"]["requires-python"]
    assert floor == ">=3.10"
    assert sys.version_info >= (3, 10)


def test_every_dependency_is_pinned(pyproject):
    for requirement in pyproject["project"]["dependencies"]:
        assert "==" in requirement, requirement


def test_every_dev_dependency_is_pinned(pyproject):
    for requirement in pyproject["project"]["optional-dependencies"]["dev"]:
        assert "==" in requirement, requirement


@pytest.mark.parametrize("command", CI_COMMANDS)
def test_the_command_exists(command):
    result = CliRunner().invoke(main, [command, "--help"])
    assert result.exit_code == 0
    assert command in result.output


def test_the_workflow_runs_every_command_this_test_knows_about(workflow):
    line = next(line for line in workflow.splitlines() if "for command in" in line)
    named = line.split("for command in", 1)[1].strip().rstrip(";do ").split()
    assert named == CI_COMMANDS


def test_the_workflow_tests_every_supported_python(workflow, pyproject):
    for version in ("3.10", "3.11", "3.12"):
        assert f'"{version}"' in workflow


def test_the_workflow_tests_on_windows(workflow):
    # The panel build machines are Windows and that is where the encoding
    # and path handling break.
    assert "windows-latest" in workflow


def test_the_workflow_runs_ruff_and_mypy(workflow):
    assert "ruff check" in workflow
    assert "mypy src/v4t_translate" in workflow


def test_the_workflow_uploads_reports_even_on_failure(workflow):
    assert "if: always()" in workflow
    assert "upload-artifact" in workflow


def test_the_help_lists_every_command():
    output = CliRunner().invoke(main, ["--help"]).output
    for command in CI_COMMANDS:
        assert command in output


def test_no_command_is_missing_from_the_ci_list():
    output = CliRunner().invoke(main, ["--help"]).output
    body = output.split("Commands:", 1)[1]
    listed = [line.split()[0] for line in body.splitlines() if line.strip()]
    assert sorted(listed) == sorted(CI_COMMANDS)
