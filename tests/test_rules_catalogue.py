import pytest
from click.testing import CliRunner

from v4t_translate.analyses.registry import analysis_names
from v4t_translate.cli import main
from v4t_translate.errors import ConfigError
from v4t_translate.rules.catalogue import (
    DOC_URL,
    describe_rule,
    every_rule,
    rule_listing,
)
from v4t_translate.rules.registry import known_rule_names, rule_names
from v4t_translate.rules.result import Severity


def run(*args):
    return CliRunner().invoke(main, ["check", *args])


# -- the catalogue ------------------------------------------------------


def test_everything_nameable_is_described():
    assert {entry.name for entry in every_rule()} == set(known_rule_names())


def test_the_rules_come_before_the_analyses():
    names = [entry.name for entry in every_rule()]
    assert names == [*rule_names(), *analysis_names()]


def test_the_analyses_are_marked_as_such():
    analyses = {e.name for e in every_rule() if e.is_analysis}
    assert analyses == set(analysis_names())


@pytest.mark.parametrize("entry", every_rule(), ids=lambda e: e.name)
def test_every_entry_has_a_real_summary(entry):
    # The module docstrings are the best explanations in this repository,
    # because they were written while somebody still remembered the bug. Some
    # first lines are two words, which is fine: that is a title and the
    # argument is underneath it.
    assert entry.summary != "No description."
    assert entry.summary.endswith(".")


@pytest.mark.parametrize("entry", every_rule(), ids=lambda e: e.name)
def test_the_summary_is_one_line(entry):
    assert "\n" not in entry.summary


@pytest.mark.parametrize("entry", every_rule(), ids=lambda e: e.name)
def test_every_entry_has_a_body(entry):
    assert entry.body


@pytest.mark.parametrize("entry", every_rule(), ids=lambda e: e.name)
def test_every_entry_has_a_severity(entry):
    assert isinstance(entry.severity, Severity)


def test_the_severities_match_the_rules():
    from v4t_translate.rules.registry import ALL_RULES

    declared = {cls.name: cls.default_severity for cls in ALL_RULES}
    for entry in every_rule():
        if entry.name in declared:
            assert entry.severity is declared[entry.name]


def test_each_entry_points_at_its_section():
    entry = describe_rule("fitting")
    assert entry.where == f"{DOC_URL}#fitting"


# -- one at a time ------------------------------------------------------


def test_a_rule_can_be_looked_up():
    assert describe_rule("placeholders").name == "placeholders"


def test_an_analysis_can_be_looked_up_the_same_way():
    assert describe_rule("collisions").is_analysis


def test_an_unknown_name_is_refused():
    with pytest.raises(ConfigError, match="no rule called"):
        describe_rule("spelling")


def test_the_refusal_lists_what_there_is():
    with pytest.raises(ConfigError) as caught:
        describe_rule("spelling")
    assert "fitting" in caught.value.remedy


def test_the_explanation_names_the_severity():
    assert "error by default" in describe_rule("placeholders").explain()


def test_the_explanation_says_which_kind_it_is():
    assert "an analysis" in describe_rule("collisions").explain()
    assert "a rule" in describe_rule("fitting").explain()


def test_the_explanation_carries_the_argument():
    text = describe_rule("fitting").explain()
    assert len(text.splitlines()) > 5


def test_the_explanation_points_at_the_documentation():
    assert DOC_URL in describe_rule("fitting").explain()


# -- the listing --------------------------------------------------------


def test_the_listing_has_a_line_per_rule():
    assert len(rule_listing().splitlines()) == len(known_rule_names())


def test_the_listing_names_the_severity():
    line = next(line for line in rule_listing().splitlines()
                if line.startswith("placeholders"))
    assert "error" in line


def test_the_listing_is_not_wide_enough_to_wrap():
    assert all(len(line) < 200 for line in rule_listing().splitlines())


# -- the command --------------------------------------------------------


def test_explain_prints_one_rule():
    result = run("--explain", "fitting")
    assert result.exit_code == 0
    assert result.output.startswith("fitting (")


def test_explain_all_lists_them():
    output = run("--explain", "all").output
    for name in known_rule_names():
        assert name in output


def test_explain_needs_no_project():
    # Asking what the fitting rule is for is a reasonable thing to do from a
    # directory with no project in it.
    assert run("--explain", "fitting").exit_code == 0


def test_an_unknown_rule_fails():
    result = run("--explain", "spelling")
    assert result.exit_code != 0


def test_explain_runs_no_check(tmp_path):
    # It returns before anything reads a catalog, so there is nothing to fail.
    result = run("--explain", "glossary")
    assert "messages checked" not in result.output


def test_the_option_is_in_the_help():
    assert "--explain" in run("--help").output
