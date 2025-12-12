from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def sample_rc_text() -> str:
    return (FIXTURES / "v4t_sample.rc").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sample_rc_path() -> Path:
    return FIXTURES / "v4t_sample.rc"


@pytest.fixture(scope="session")
def help_commands() -> list[str]:
    """Command names as ``--help`` lists them, in the order it lists them.

    Here rather than in whichever test module wanted it first, because two of
    them want it. The version of this that lived in one module and was
    imported by the other passed locally and failed on all four CI runners:
    ``python -m pytest`` puts the working directory on ``sys.path`` and the
    ``pytest`` console script does not, so ``from tests.x import y`` only
    resolves under the first. A fixture is the sharing mechanism that does
    not depend on how pytest was started.
    """
    from click.testing import CliRunner

    from v4t_translate.cli import main

    body = CliRunner().invoke(main, ["--help"]).output.split("Commands:", 1)[1]

    names: list[str] = []
    for line in body.splitlines():
        if not line.strip():
            # The epilog follows the list after a blank line, and its lines
            # look enough like command entries to be counted as some.
            if names:
                break
            continue
        names.append(line.split()[0])

    return names
