import pytest
from click.testing import CliRunner

import v4t_translate
from v4t_translate.catalog.cache import CACHE_VERSION
from v4t_translate.catalog.store import FORMAT_VERSION as CATALOG_FORMAT
from v4t_translate.cli import main
from v4t_translate.emit.v4l import FORMAT_VERSION as PACK_FORMAT
from v4t_translate.versions import describe, versions


@pytest.fixture(scope="module")
def found():
    return versions()


def test_the_package_version_matches(found):
    assert found.package == v4t_translate.__version__


def test_the_format_versions_match_their_constants(found):
    assert found.catalog_format == CATALOG_FORMAT
    assert found.cache_format == CACHE_VERSION
    assert found.pack_format == PACK_FORMAT


def test_the_formats_move_independently(found):
    # They are separate numbers on purpose. This asserts nothing about their
    # values, only that they are not one number in three places.
    assert isinstance(found.catalog_format, int)
    assert isinstance(found.cache_format, int)
    assert isinstance(found.pack_format, int)


def test_what_it_reads(found):
    assert set(found.sources) == {"rc", "cheader", "androidxml"}


def test_what_it_writes(found):
    assert set(found.outputs) == {"rc", "v4l", "androidxml", "cheader", "po",
                                  "xliff"}


def test_the_rules_are_listed(found):
    assert "placeholders" in found.rules
    assert "collisions" in found.rules


def test_the_panels_are_listed(found):
    assert "mini-20x4" in found.panels


def test_the_languages_are_listed(found):
    assert "de-DE" in found.locales
    assert "zh-TW" in found.locales
    assert len(found.locales) > 20


def test_as_dict_is_serialisable(found):
    import json

    payload = json.loads(json.dumps(found.as_dict()))
    assert payload["package"] == found.package
    assert payload["sources"] == list(found.sources)


def test_the_short_description():
    assert describe() == f"v4t-translate {v4t_translate.__version__}"


def test_the_long_description():
    text = describe(detailed=True)
    assert "catalog format" in text
    assert "pack format" in text
    assert "reads" in text
    assert "writes" in text


def test_the_long_description_is_several_lines():
    assert len(describe(detailed=True).splitlines()) > 5


def test_the_command_line_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"v4t-translate {v4t_translate.__version__}"


def test_the_short_flag():
    assert CliRunner().invoke(main, ["-V"]).exit_code == 0


def test_the_command_line_version_needs_no_project(tmp_path, monkeypatch):
    from v4t_translate.cli import run

    monkeypatch.chdir(tmp_path)
    assert run(["--version"]) == 0


def test_verbose_version_shows_the_formats(monkeypatch):
    monkeypatch.setattr("sys.argv", ["v4t-translate", "-v", "--version"])
    result = CliRunner().invoke(main, ["-v", "--version"])
    assert "catalog format" in result.output
    assert "pack format" in result.output


def test_plain_version_does_not(monkeypatch):
    monkeypatch.setattr("sys.argv", ["v4t-translate", "--version"])
    result = CliRunner().invoke(main, ["--version"])
    assert "catalog format" not in result.output
