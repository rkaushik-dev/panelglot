import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.config import CONFIG_FILENAME, load_config
from v4t_translate.errors import ConfigError
from v4t_translate.ops.init import init_project, render_config


def test_a_bare_scaffold(tmp_path):
    result = init_project(tmp_path, name="V4T-Mini")

    assert (tmp_path / CONFIG_FILENAME).exists()
    assert (tmp_path / "catalog" / ".gitkeep").exists()
    assert (tmp_path / "glossary" / "terms.csv").exists()
    assert (tmp_path / "fonts" / ".gitkeep").exists()
    assert (tmp_path / ".gitignore").exists()
    assert len(result.written) == 5
    assert result.skipped == []


def test_the_glossary_has_its_header_row(tmp_path):
    init_project(tmp_path, name="V4T-Mini")
    header = (tmp_path / "glossary" / "terms.csv").read_text(encoding="utf-8")
    assert header.strip() == "term,locale,translation,note"


def test_the_gitignore_lines(tmp_path):
    init_project(tmp_path, name="V4T-Mini")
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "catalog/.extraction-cache.json" in text
    assert "catalog/memory.sqlite3" in text
    assert "out/" in text


def test_an_existing_gitignore_is_added_to_not_replaced(tmp_path):
    (tmp_path / ".gitignore").write_text(".idea/\n*.pyc\n", encoding="utf-8")
    init_project(tmp_path, name="V4T-Mini")

    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".idea/" in text
    assert "out/" in text


def test_a_gitignore_that_already_has_the_lines_is_left_alone(tmp_path):
    init_project(tmp_path, name="V4T-Mini")
    before = (tmp_path / ".gitignore").read_text(encoding="utf-8")

    result = init_project(tmp_path, name="V4T-Mini")
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == before
    assert (tmp_path / ".gitignore") in result.skipped


def test_the_gitignore_can_be_left_out(tmp_path):
    init_project(tmp_path, name="V4T-Mini", write_gitignore=False)
    assert not (tmp_path / ".gitignore").exists()


def test_nothing_is_written_over(tmp_path):
    (tmp_path / CONFIG_FILENAME).write_text("# mine\n", encoding="utf-8")
    result = init_project(tmp_path, name="V4T-Mini")

    assert (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8") == "# mine\n"
    assert (tmp_path / CONFIG_FILENAME) in result.skipped


def test_the_scaffolded_config_loads(tmp_path):
    init_project(tmp_path, name="V4T-Mini",
                 sources=[("cheader", "../V4T-Mini/src/v4t_lang.h")],
                 locales=["de-DE", "zh-TW"])

    config = load_config(tmp_path / CONFIG_FILENAME)
    assert config.name == "V4T-Mini"
    assert config.sources[0].kind == "cheader"
    assert config.target_tags() == ["de-DE", "zh-TW"]


def test_a_scaffold_with_no_sources_does_not_load_yet(tmp_path):
    init_project(tmp_path, name="V4T-Mini")
    with pytest.raises(ConfigError, match="nothing to read"):
        load_config(tmp_path / CONFIG_FILENAME)


def test_the_config_does_not_carry_another_product_s_source(tmp_path):
    # The bug this exists to stop: a config copied from another product and
    # only half edited.
    init_project(tmp_path, name="V4T-Mini")
    text = (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8")
    live = [line for line in text.splitlines()
            if line.startswith("path =")]
    assert live == []


def test_the_config_carries_the_comments_people_read():
    text = render_config("V4T-TIJ", [("rc", "../V4T-TIJ/V4T/V4T.rc")], ["de-DE"])
    assert "relative to this file" in text
    assert "{locale}" in text
    assert "German" in text


def test_locale_names_are_resolved(tmp_path):
    init_project(tmp_path, name="V4T-Mini", locales=["Taiwan"])
    assert 'locale."zh-TW"' in (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8")


def test_an_unknown_locale_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="unknown locale"):
        init_project(tmp_path, name="V4T-Mini", locales=["Klingon"])


def test_an_unknown_source_kind_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="unknown source kind"):
        init_project(tmp_path, name="V4T-Mini", sources=[("cobol", "a.cbl")])


def test_nothing_is_written_when_a_source_kind_is_wrong(tmp_path):
    with pytest.raises(ConfigError):
        init_project(tmp_path, name="V4T-Mini", sources=[("cobol", "a.cbl")])
    assert not (tmp_path / CONFIG_FILENAME).exists()


def test_a_directory_that_does_not_exist_yet(tmp_path):
    target = tmp_path / "new" / "project"
    init_project(target, name="V4T-Mini")
    assert (target / CONFIG_FILENAME).exists()


def test_the_command_line(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, [
        "init", str(tmp_path), "-n", "V4T-Mini",
        "-s", "cheader:../V4T-Mini/src/v4t_lang.h",
        "-l", "de-DE",
    ])
    assert result.exit_code == 0
    assert "wrote" in result.output
    assert load_config(tmp_path / CONFIG_FILENAME).name == "V4T-Mini"


def test_the_command_line_says_what_to_do_next(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["init", str(tmp_path), "-n", "V4T-Mini"])
    assert "then run extract" in result.output


def test_the_command_line_rejects_a_malformed_source(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, [
        "init", str(tmp_path), "-n", "V4T-Mini", "-s", "no-colon-here",
    ])
    assert result.exit_code == 2
    assert "rc:../V4T-TIJ" in result.output


def test_the_command_line_needs_a_name(tmp_path):
    runner = CliRunner()
    assert runner.invoke(main, ["init", str(tmp_path)]).exit_code == 2


def test_init_does_not_need_an_existing_project(tmp_path, monkeypatch):
    # Every other command resolves the config. This one is what creates it.
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(main, ["init", ".", "-n", "V4T-Mini"]).exit_code == 0
