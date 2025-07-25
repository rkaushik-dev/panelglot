import shutil

import pytest

from v4t_translate.config import load_config
from v4t_translate.errors import EmitError
from v4t_translate.ops.build import build_project, destination_for, is_inside
from v4t_translate.ops.doctor import run_doctor
from v4t_translate.ops.extract import extract_project

HEAD = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""

ESCAPING = HEAD + """
[[output]]
kind = "po"
path = "../elsewhere/{locale}.po"
"""

ESCAPING_ALLOWED = HEAD + """
[[output]]
kind = "po"
path = "../elsewhere/{locale}.po"
allow_outside = true
"""

ABSOLUTE = HEAD + """
[[output]]
kind = "po"
path = "/tmp/v4t/{locale}.po"
"""

SIDEWAYS = HEAD + """
[[output]]
kind = "po"
path = "out/../out/nested/{locale}.po"
"""


def build(tmp_path, sample_rc_path, text):
    (tmp_path / "src").mkdir(exist_ok=True)
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(text, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


@pytest.fixture
def escaping(tmp_path, sample_rc_path):
    return build(tmp_path, sample_rc_path, ESCAPING)


def test_a_path_under_the_root_is_inside(tmp_path):
    assert is_inside(tmp_path / "out" / "de.po", tmp_path)


def test_a_path_that_climbs_out_is_not(tmp_path):
    assert not is_inside(tmp_path / ".." / "de.po", tmp_path)


def test_a_path_that_climbs_and_comes_back_is_inside(tmp_path):
    assert is_inside(tmp_path / "out" / ".." / "out" / "de.po", tmp_path)


def test_the_root_itself_counts_as_inside(tmp_path):
    assert is_inside(tmp_path, tmp_path)


def test_a_sibling_with_a_shared_prefix_is_not_inside(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "project-notes").mkdir()
    assert not is_inside(tmp_path / "project-notes" / "de.po", root)


def test_building_an_escaping_output_is_refused(escaping):
    with pytest.raises(EmitError) as caught:
        build_project(escaping)
    assert "outside" in str(caught.value)


def test_the_refusal_names_the_output_and_the_language(escaping):
    with pytest.raises(EmitError) as caught:
        build_project(escaping)
    message = str(caught.value)
    assert "po" in message
    assert "de-DE" in message
    assert "allow_outside" in message


def test_the_refusal_happens_before_anything_is_written(escaping):
    with pytest.raises(EmitError):
        build_project(escaping)
    assert not (escaping.root.parent / "elsewhere").exists()


def test_a_dry_run_is_refused_too(escaping):
    # A dry run that passes and a real build that does not would be worse than
    # no dry run at all.
    with pytest.raises(EmitError):
        build_project(escaping, dry_run=True)


def test_saying_so_allows_it(tmp_path, sample_rc_path):
    root = tmp_path / "project"
    root.mkdir()
    config = build(root, sample_rc_path, ESCAPING_ALLOWED)
    build_project(config)
    assert (tmp_path / "elsewhere" / "de-DE.po").exists()


def test_an_absolute_path_is_refused(tmp_path, sample_rc_path):
    config = build(tmp_path, sample_rc_path, ABSOLUTE)
    with pytest.raises(EmitError):
        build_project(config)


def test_climbing_and_coming_back_is_fine(tmp_path, sample_rc_path):
    config = build(tmp_path, sample_rc_path, SIDEWAYS)
    build_project(config)
    assert (tmp_path / "out" / "nested" / "de-DE.po").exists()


def test_the_destination_is_the_resolved_path(tmp_path, sample_rc_path):
    config = build(tmp_path, sample_rc_path, SIDEWAYS)
    destination = destination_for(config, config.outputs[0], config.locales[0])
    assert destination.resolve() == (tmp_path / "out" / "nested" / "de-DE.po")


def test_doctor_reports_an_escaping_output(escaping):
    report = run_doctor(escaping)
    assert any("outside the project" in f.detail for f in report.problems)


def test_doctor_says_what_to_do_about_it(escaping):
    report = run_doctor(escaping)
    problem = next(f for f in report.problems if "outside" in f.detail)
    assert "allow_outside" in problem.remedy


def test_doctor_is_quiet_when_it_was_allowed(tmp_path, sample_rc_path):
    root = tmp_path / "project"
    root.mkdir()
    config = build(root, sample_rc_path, ESCAPING_ALLOWED)
    report = run_doctor(config)
    assert not any("outside" in f.detail for f in report.problems)
