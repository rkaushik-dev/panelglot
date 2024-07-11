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
