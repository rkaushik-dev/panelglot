import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.doctor import run_doctor
from v4t_translate.ops.extract import extract_project

CONFIG = """
[project]
name = "V4T-TIJ"
glossary = "glossary/terms.csv"

[[source]]
kind = "rc"
path = "src/V4T.rc"
symbols = "src/resource.h"

[locale."de-DE"]
panel = "tij-800x600"
font = "fonts/tahoma-8.fmx"

[[output]]
kind = "rc"
path = "out/{locale}/V4T.rc"
source = "src/V4T.rc"
"""

GLOSSARY = "term,locale,translation\npen,de-DE,Stift\n"


@pytest.fixture
def project(tmp_path, sample_rc_path, fixtures_dir):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "src" / "resource.h").write_text("#define IDC_X 1\n", encoding="utf-8")
    (tmp_path / "fonts").mkdir()
    shutil.copy(fixtures_dir / "fonts" / "tahoma-8.fmx", tmp_path / "fonts" / "tahoma-8.fmx")
    (tmp_path / "glossary").mkdir()
    (tmp_path / "glossary" / "terms.csv").write_text(GLOSSARY, encoding="utf-8")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return load_config(tmp_path / "v4t-translate.toml")


def named(report, prefix):
    return [f for f in report.findings if f.name.startswith(prefix)]


def test_a_healthy_project_after_extract(project):
    extract_project(project)
    report = run_doctor(project)
    assert report, "\n".join(f.describe() for f in report.problems)
    assert "nothing wrong" in report.summary()


def test_a_project_that_has_not_been_extracted(project):
    report = run_doctor(project)
    assert not report
    catalog = named(report, "catalog")[0]
    assert not catalog.ok
    assert "Run extract" in catalog.remedy


def test_a_stale_catalog_is_reported(project):
    import os
    import time

    extract_project(project)
    later = time.time() + 60
    os.utime(project.root / "src" / "V4T.rc", (later, later))

    catalog = named(run_doctor(project), "catalog")[0]
    assert not catalog.ok
    assert "stale message list" in catalog.remedy


def test_a_missing_source_is_reported(project):
    (project.root / "src" / "V4T.rc").unlink()
    finding = named(run_doctor(project), "source")[0]
    assert not finding.ok
    assert "sibling checkout" in finding.remedy


def test_a_missing_symbols_file_is_reported(project):
    (project.root / "src" / "resource.h").unlink()
    finding = named(run_doctor(project), "symbols")[0]
    assert not finding.ok
    assert "IDC_STATIC" in finding.remedy


def test_a_present_source_reports_its_size(project):
    finding = named(run_doctor(project), "source")[0]
    assert finding.ok
    assert "bytes" in finding.detail


def test_a_missing_font_is_reported(project):
    (project.root / "fonts" / "tahoma-8.fmx").unlink()
    finding = named(run_doctor(project), "locale de-DE")[0]
    assert not finding.ok
    assert "approximate" in finding.remedy


def test_an_unknown_panel_is_reported(project):
    (project.root / "v4t-translate.toml").write_text(
        CONFIG.replace("tij-800x600", "crt"), encoding="utf-8"
    )
    config = load_config(project.root / "v4t-translate.toml")
    finding = named(run_doctor(config), "locale de-DE")[0]
    assert not finding.ok
    assert "mini-20x4" in finding.remedy


def test_a_language_that_cannot_ship_on_its_panel(project):
    text = CONFIG.replace('[locale."de-DE"]', '[locale."zh-TW"]').replace(
        "tij-800x600", "mini-20x4"
    )
    (project.root / "v4t-translate.toml").write_text(text, encoding="utf-8")
    config = load_config(project.root / "v4t-translate.toml")
    problems = [f for f in run_doctor(config).problems if "mini-20x4" in f.name]
    assert problems
    assert "single byte character path" in problems[0].remedy


def test_no_locales_at_all(project, tmp_path):
    text = CONFIG.split('[locale."de-DE"]')[0]
    (project.root / "v4t-translate.toml").write_text(text, encoding="utf-8")
    config = load_config(project.root / "v4t-translate.toml")
    finding = named(run_doctor(config), "locales")[0]
    assert not finding.ok


def test_the_glossary_is_counted(project):
    finding = named(run_doctor(project), "glossary")[0]
    assert finding.ok
    assert "1 terms" in finding.detail


def test_glossary_terms_for_an_unconfigured_language(project):
    (project.root / "glossary" / "terms.csv").write_text(
        GLOSSARY + "pen,zh-TW,筆\n", encoding="utf-8"
    )
    finding = named(run_doctor(project), "glossary locales")[0]
    assert not finding.ok
    assert "not being enforced" in finding.remedy


def test_a_broken_glossary_is_reported(project):
    (project.root / "glossary" / "terms.csv").write_text(
        "term,locale\npen,de-DE\n", encoding="utf-8"
    )
    finding = named(run_doctor(project), "glossary")[0]
    assert not finding.ok


def test_a_bad_check_section_is_reported(project):
    (project.root / "v4t-translate.toml").write_text(
        CONFIG + '\n[check]\ndisable = ["spelling"]\n', encoding="utf-8"
    )
    config = load_config(project.root / "v4t-translate.toml")
    finding = named(run_doctor(config), "rules")[0]
    assert not finding.ok
    assert "unknown rule" in finding.detail


def test_an_output_template_that_collides_across_languages(project):
    text = CONFIG.replace('path = "out/{locale}/V4T.rc"', 'path = "out/V4T.rc"')
    text += '\n[locale."zh-TW"]\npanel = "tij-800x600"\n'
    (project.root / "v4t-translate.toml").write_text(text, encoding="utf-8")
    config = load_config(project.root / "v4t-translate.toml")

    problems = [f for f in run_doctor(config).problems if f.name.startswith("output")]
    assert problems
    assert "overwrite the other" in problems[0].remedy


def test_an_rc_output_with_no_source(project):
    text = CONFIG.replace('source = "src/V4T.rc"\n', "", 1)
    text = text.replace('kind = "rc"\npath = "out/{locale}/V4T.rc"\n',
                        'kind = "rc"\npath = "out/{locale}/V4T.rc"\n')
    # Remove only the source line belonging to the output block.
    lines = [ln for ln in text.splitlines()
             if ln.strip() != 'source = "src/V4T.rc"']
    (project.root / "v4t-translate.toml").write_text("\n".join(lines), encoding="utf-8")
    config = load_config(project.root / "v4t-translate.toml")

    problems = [f for f in run_doctor(config).problems if f.name.startswith("output")]
    assert problems
    assert "needs a source" in problems[0].detail


def test_an_unknown_output_kind(project):
    (project.root / "v4t-translate.toml").write_text(
        CONFIG.replace('kind = "rc"\npath = "out/{locale}/V4T.rc"',
                       'kind = "pdf"\npath = "out/{locale}/V4T.pdf"'),
        encoding="utf-8",
    )
    config = load_config(project.root / "v4t-translate.toml")
    problems = [f for f in run_doctor(config).problems if f.name.startswith("output")]
    assert problems
    assert "androidxml" in problems[0].remedy


def test_a_project_with_no_outputs(project):
    text = CONFIG.split("[[output]]")[0]
    (project.root / "v4t-translate.toml").write_text(text, encoding="utf-8")
    config = load_config(project.root / "v4t-translate.toml")
    finding = named(run_doctor(config), "outputs")[0]
    assert finding.ok
    assert "build does nothing" in finding.detail


def test_python_is_always_checked(project):
    assert named(run_doctor(project), "python")[0].ok


def test_describe_includes_the_remedy(project):
    (project.root / "src" / "V4T.rc").unlink()
    finding = named(run_doctor(project), "source")[0]
    assert "PROBLEM" in finding.describe()
    assert "cloned?" in finding.describe()


def test_describe_of_a_pass_has_no_remedy(project):
    assert "\n" not in named(run_doctor(project), "python")[0].describe()


def test_the_command_line_passes_on_a_healthy_project(project):
    extract_project(project)
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "doctor",
    ])
    assert result.exit_code == 0
    assert "nothing wrong" in result.output


def test_the_command_line_fails_and_names_the_problem(project):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "doctor",
    ])
    assert result.exit_code != 0
    assert "Run extract" in result.output


def test_the_exit_code_is_the_check_failure_one(project, monkeypatch):
    from v4t_translate.cli import run

    monkeypatch.chdir(project.root)
    assert run(["doctor"]) == 2


def test_the_command_line_hides_passes_by_default(project):
    extract_project(project)
    runner = CliRunner()
    quiet = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "doctor",
    ]).output
    verbose = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "doctor", "--all",
    ]).output
    assert len(verbose) > len(quiet)
    assert "[ok] python" in verbose
