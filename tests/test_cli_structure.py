"""The shape of the command line, as opposed to what any one command does.

Each command's behaviour is tested next to the operation it calls. This is
about the group: that every command is attached, that the help reads in the
order somebody works in, and that --help never goes looking for a project
file, which it did until the config was made lazy.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from v4t_translate.cli import Context, main, run
from v4t_translate.cli.commands import COMMANDS, register


@pytest.fixture
def runner():
    return CliRunner()


def listed(output: str) -> list[str]:
    body = output.split("Commands:", 1)[1]
    return [line.split()[0] for line in body.splitlines() if line.strip()]


def test_every_command_is_attached():
    assert set(main.commands) == {command.name for command in COMMANDS}


def test_the_help_lists_them_in_working_order(runner):
    order = listed(runner.invoke(main, ["--help"]).output)
    assert order == [command.name for command in COMMANDS]


def test_extract_comes_first_and_build_does_not(runner):
    order = listed(runner.invoke(main, ["--help"]).output)
    assert order[0] == "extract"
    assert order.index("build") > order.index("check")


def test_the_order_is_not_alphabetical(runner):
    order = listed(runner.invoke(main, ["--help"]).output)
    assert order != sorted(order)


@pytest.mark.parametrize("command", [c.name for c in COMMANDS])
def test_every_command_has_help(runner, command):
    result = runner.invoke(main, [command, "--help"])
    assert result.exit_code == 0
    assert result.output.strip()


@pytest.mark.parametrize("command", [c.name for c in COMMANDS])
def test_help_does_not_need_a_project(runner, command, tmp_path, monkeypatch):
    # There is no config anywhere above tmp_path. --help must still work.
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(main, [command, "--help"]).exit_code == 0


def test_the_group_help_does_not_need_a_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(["--help"]) == 0


def test_the_version_does_not_need_a_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(["--version"]) == 0


def test_a_command_that_does_need_one_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(["extract"]) == 78


def test_register_is_idempotent_enough_to_call_twice():
    group = click.Group("scratch")
    register(group)
    register(group)
    assert len(group.commands) == len(COMMANDS)


def test_the_context_is_lazy_about_the_config():
    context = Context(config_path=None, verbose=0, quiet=False, traceback=False)
    assert context._config is None


def spoken(context: Context, *calls) -> str:
    """Whatever ``context`` printed for the given say() calls."""
    runner = CliRunner()
    with runner.isolation() as streams:
        for message, level in calls:
            context.say(message, level=level)
        return streams[0].getvalue().decode()


def test_say_respects_quiet():
    context = Context(config_path=None, verbose=0, quiet=True, traceback=False)
    assert spoken(context, ("nothing to see", 0)) == ""


def test_say_respects_the_verbosity_level():
    context = Context(config_path=None, verbose=1, quiet=False, traceback=False)
    output = spoken(context, ("shown", 1), ("hidden", 2))
    assert "shown" in output
    assert "hidden" not in output


def test_say_prints_at_level_zero_by_default():
    context = Context(config_path=None, verbose=0, quiet=False, traceback=False)
    assert "plain" in spoken(context, ("plain", 0))


def test_an_unknown_command_is_a_usage_error(runner):
    assert runner.invoke(main, ["translate-everything"]).exit_code == 2


def test_the_module_entry_point_still_works():
    from v4t_translate.__main__ import main as module_main

    assert callable(module_main)
