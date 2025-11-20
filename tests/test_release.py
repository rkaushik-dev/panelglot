import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate import __version__
from v4t_translate.catalog.store import FORMAT_VERSION, TRANSLATIONS_VERSION
from v4t_translate.cli import main
from v4t_translate.emit.manifest import MANIFEST_VERSION
from v4t_translate.reproducible import SOURCE_DATE_EPOCH
from v4t_translate.versions import describe, versions

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"

#: Every number --version --verbose reports. Named here so adding one to the
#: build without adding it to the block that answers "why does this machine
#: behave differently" fails rather than being forgotten.
FORMATS = ("catalog_format", "translations_format", "cache_format",
           "pack_format", "manifest_format")


def headings():
    return re.findall(r"^## (.+)$", CHANGELOG.read_text(encoding="utf-8"), re.M)


# -- the version ---------------------------------------------------------


def test_the_version_is_a_release_number():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_the_changelog_leads_with_it():
    assert headings()[0] == __version__


def test_the_versions_are_in_order():
    def as_numbers(text):
        return tuple(int(part) for part in text.split("."))

    found = [as_numbers(h) for h in headings()]
    assert found == sorted(found, reverse=True)


def test_no_version_is_listed_twice():
    assert len(headings()) == len(set(headings()))


def test_the_release_has_something_in_it():
    body = CHANGELOG.read_text(encoding="utf-8").split(f"## {__version__}", 1)[1]
    entry = body.split("\n## ", 1)[0]
    assert entry.count("\n- ") >= 10


# -- what the build reports ---------------------------------------------


def test_every_format_number_is_reported():
    reported = versions().as_dict()
    for name in FORMATS:
        assert name in reported


def test_the_format_numbers_are_the_real_ones():
    found = versions()
    assert found.catalog_format == FORMAT_VERSION
    assert found.translations_format == TRANSLATIONS_VERSION
    assert found.manifest_format == MANIFEST_VERSION


def test_the_catalog_and_its_translations_moved_apart():
    # Their shapes changed at different times and the numbers say so.
    found = versions()
    assert found.catalog_format != found.translations_format


def test_the_package_version_is_reported():
    assert versions().package == __version__


def test_pinned_timestamps_are_reported(monkeypatch):
    # Two machines producing different bytes from the same input is exactly
    # the question this block exists to answer.
    monkeypatch.setenv(SOURCE_DATE_EPOCH, "1739525400")
    assert versions().reproducible


def test_unpinned_timestamps_are_reported(monkeypatch):
    monkeypatch.delenv(SOURCE_DATE_EPOCH, raising=False)
    assert not versions().reproducible


def test_the_dictionary_is_json_safe():
    import json

    json.dumps(versions().as_dict())


# -- what it prints -----------------------------------------------------


def test_the_short_form_is_one_line():
    assert describe().splitlines() == [f"v4t-translate {__version__}"]


@pytest.mark.parametrize("label", ["catalog format", "translation format",
                                   "cache format", "pack format",
                                   "manifest format"])
def test_the_long_form_names_every_format(label):
    assert label in describe(detailed=True)


def test_the_long_form_says_whether_timestamps_are_pinned(monkeypatch):
    monkeypatch.delenv(SOURCE_DATE_EPOCH, raising=False)
    assert "from the clock" in describe(detailed=True)

    monkeypatch.setenv(SOURCE_DATE_EPOCH, "1739525400")
    assert "pinned" in describe(detailed=True)


def test_the_long_form_lines_up():
    lines = [line for line in describe(detailed=True).splitlines()
             if line.startswith("  ")]
    columns = {line.index(line.strip().split()[-1]) for line in lines
               if len(line.strip().split()) == 2}
    assert len(columns) <= 1


# -- through the command line -------------------------------------------


def test_the_version_flag_prints_it():
    result = CliRunner().invoke(main, ["--version"])
    assert __version__ in result.output


def test_the_readme_does_not_claim_an_older_version():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for heading in headings()[1:]:
        assert f"v4t-translate {heading}" not in readme
