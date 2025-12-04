import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate.cli import DOCUMENTATION, main
from v4t_translate.cli.commands import COMMANDS

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
README = REPO / "README.md"


def markdown_files():
    return sorted(p.relative_to(REPO).as_posix() for p in DOCS.glob("*.md"))


@pytest.fixture(scope="module")
def help_text():
    return CliRunner().invoke(main, ["--help"]).output


@pytest.fixture(scope="module")
def readme():
    return README.read_text(encoding="utf-8")


# -- nothing is orphaned ------------------------------------------------


@pytest.mark.parametrize("path", markdown_files())
def test_every_document_is_reachable_from_the_help(path):
    # A document nobody links to is a document nobody reads, and this tool has
    # more of them than anybody expects.
    assert path in {entry for entry, _ in DOCUMENTATION}


@pytest.mark.parametrize("path", markdown_files())
def test_every_document_is_linked_from_the_readme(path, readme):
    assert f"]({path})" in readme


@pytest.mark.parametrize("entry", DOCUMENTATION, ids=lambda e: e[0])
def test_every_listed_document_exists(entry):
    assert (REPO / entry[0]).is_file()


@pytest.mark.parametrize("entry", DOCUMENTATION, ids=lambda e: e[0])
def test_every_listed_document_says_what_it_answers(entry):
    assert len(entry[1]) > 15


def test_no_document_is_listed_twice():
    paths = [path for path, _ in DOCUMENTATION]
    assert len(paths) == len(set(paths))


def test_every_document_has_a_heading():
    for path in markdown_files():
        assert (REPO / path).read_text(encoding="utf-8").startswith("# ")


# -- the help ------------------------------------------------------------


def test_the_help_names_the_round(help_text):
    assert "extract, export, import, check, build, audit" in help_text


def test_the_help_lists_the_documentation(help_text):
    for path, _ in DOCUMENTATION:
        assert path in help_text


def test_the_help_points_at_explain(help_text):
    assert "--explain" in help_text


def test_the_help_still_lists_the_commands(help_text):
    for command in COMMANDS:
        assert command.name in help_text


# -- the readme ----------------------------------------------------------


def test_the_readme_shows_the_round(readme):
    block = readme.split("## A round", 1)[1].split("```", 2)[1]
    for command in ("status", "extract", "export", "import", "check", "build",
                    "audit"):
        assert f"v4t-translate {command}" in block


def test_the_readme_mentions_adopt(readme):
    # It is how a real project starts and it is the part nobody writes down.
    assert "adopt" in readme


def test_the_readme_layout_matches_the_package(readme):
    block = readme.split("src/v4t_translate/", 1)[1].split("```", 1)[0]
    packages = {
        p.name for p in (REPO / "src" / "v4t_translate").iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    }
    for name in packages:
        assert f"{name}/" in block


def test_the_readme_names_every_source_kind(readme):
    from v4t_translate.sources.registry import available_kinds

    for kind in available_kinds():
        assert f"`{kind}`" in readme


def test_the_readme_does_not_promise_a_command_that_is_gone(readme):
    known = {command.name for command in COMMANDS}
    promised = set(re.findall(r"v4t-translate ([a-z][a-z-]+)", readme))
    assert promised <= known
