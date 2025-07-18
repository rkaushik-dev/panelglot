"""Things about the files themselves rather than about what they do.

Every one of these caught something real. A file that went in with CRLF made
its diff the whole file and hid the six lines that had changed. A fixture
that lost its non-ASCII characters to an encoding round trip made two tests
assert on a replacement character without failing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Everything the repository owns. The virtualenv, the caches and the build
#: output are not ours and are not checked.
SOURCE_GLOBS = ("*.py", "*.toml", "*.yml", "*.md", "*.rc", "*.h", "*.xml",
                "*.csv", "*.fmx", "*.bdf", "*.cfg", "*.txt")

SKIP_DIRS = {".venv", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             "__pycache__", "out", "build", "dist", "htmlcov", "reports",
             "Translate"}


def owned_files() -> list[Path]:
    found: list[Path] = []
    for pattern in SOURCE_GLOBS:
        for path in ROOT.rglob(pattern):
            if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            found.append(path)
    return sorted(found)


@pytest.fixture(scope="module")
def files():
    found = owned_files()
    assert len(found) > 80, "the file sweep found almost nothing, check SKIP_DIRS"
    return found


def test_no_file_has_windows_line_endings(files):
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in files
        if b"\r\n" in path.read_bytes()
    ]
    assert offenders == []


def test_every_file_is_valid_utf8(files):
    offenders = []
    for path in files:
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_no_file_carries_a_replacement_character(files):
    # U+FFFD is what survives an encoding round trip that went wrong. It is
    # never something anybody typed. Written as an escape so that this file
    # is not itself an offender, which it was on the first run.
    marker = "\ufffd"
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in files
        if marker in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_file_has_a_byte_order_mark(files):
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in files
        if path.read_bytes().startswith(b"\xef\xbb\xbf")
    ]
    assert offenders == []


def test_every_file_ends_with_exactly_one_newline(files):
    offenders = []
    for path in files:
        data = path.read_bytes()
        if not data:
            continue
        if not data.endswith(b"\n") or data.endswith(b"\n\n"):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_no_trailing_whitespace_in_python(files):
    offenders = []
    for path in files:
        if path.suffix != ".py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line != line.rstrip():
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert offenders == []


def test_no_tabs_in_python(files):
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in files
        if path.suffix == ".py" and "\t" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_gitattributes_pins_line_endings():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "eol=lf" in text
    assert "*.xlsx binary" in text


def test_the_gitignore_keeps_derived_files_out():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for line in (".venv/", "out/", "catalog/.extraction-cache.json"):
        assert line in text


def test_every_package_directory_has_an_init():
    package = ROOT / "src" / "v4t_translate"
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in package.rglob("*")
        if path.is_dir()
        and "__pycache__" not in path.parts
        and not (path / "__init__.py").exists()
    ]
    assert missing == []


def test_every_source_module_has_a_docstring():
    package = ROOT / "src" / "v4t_translate"
    missing = []
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lstrip()
        if not text.startswith('"""'):
            missing.append(path.relative_to(ROOT).as_posix())
    assert missing == []
