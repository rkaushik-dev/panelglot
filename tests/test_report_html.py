import shutil
from datetime import date
from xml.etree import ElementTree

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.check import check_project
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.stats import project_stats
from v4t_translate.report.html import render_report

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]
"""


@pytest.fixture
def project(tmp_path, sample_rc_path, fixtures_dir):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "fonts").mkdir()
    shutil.copy(fixtures_dir / "fonts" / "tahoma-8.fmx", tmp_path / "fonts" / "tahoma-8.fmx")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def translate(config, tag, pairs, state=TranslationState.APPROVED):
    path = config.translations_path(tag)
    translations = load_translations(path)
    for source, target in pairs.items():
        translations.set(message_key(source), Translation(text=target, state=state))
    save_translations(path, translations)


def render(config, **kw):
    return render_report(check_project(config), project_stats(config), **kw)


def test_it_is_well_formed_html(project):
    html = render(project)
    # Parsing as XML is stricter than a browser and catches an unclosed tag.
    ElementTree.fromstring(html.split("<!doctype html>", 1)[1].strip())


def test_it_names_the_project_and_the_date(project):
    html = render(project, today=date(2025, 4, 7))
    assert "<h1>V4T-TIJ</h1>" in html
    assert "2025-04-07" in html


def test_it_carries_its_own_styling(project):
    html = render(project)
    assert "<style>" in html
    assert "http" not in html.split("<style>")[1].split("</style>")[0]


def test_there_is_no_javascript(project):
    assert "<script" not in render(project).lower()


def test_every_language_gets_a_row(project):
    html = render(project)
    assert "<td>de-DE</td>" in html
    assert "<td>zh-TW</td>" in html


def test_the_panel_is_named(project):
    assert "tij-800x600" in render(project)


def test_a_clean_project_says_so(project):
    assert "Nothing found across" in render(project)


def test_findings_are_grouped_by_rule(project):
    translate(project, "de-DE",
              {"Please input from %.1fV to %.1fV.": "Bitte einen Wert eingeben."})
    html = render(project)
    assert "<h3>placeholders" in html
    assert "worst error" in html


def test_a_finding_shows_both_texts(project):
    translate(project, "de-DE", {"Bar Height": "Balkenhöhe des Barcodes im Feld"})
    html = render(project)
    assert "Bar Height" in html
    assert "Balkenhöhe des Barcodes im Feld" in html


def test_markup_in_a_translation_is_escaped(project):
    translate(project, "de-DE", {"Bar Height": "<b>Balkenhöhe & mehr im Feld</b>"})
    html = render(project)
    assert "&lt;b&gt;" in html
    assert "&amp;" in html


def test_the_coverage_bar_reflects_progress(project):
    translate(project, "de-DE", {"Print started": "Druck gestartet"})
    html = render(project)
    assert "width:" in html
    assert "class='bar'" in html


def test_the_font_fallback_is_called_out(project):
    shutil.rmtree(project.root / "fonts")
    assert "approximate" in render(project)
    assert "de-DE" in render(project).split("approximate")[0].rsplit("<p", 1)[1]


def test_a_font_that_was_found_is_not_called_out(project):
    assert "approximate" not in render(project)


def test_the_limit_truncates(project):
    translate(project, "de-DE", {
        text: "x" * 200
        for text in ("Bar Height", "Width", "Pen", "Spacing", "Print Offset")
    })
    html = render_report(check_project(project), project_stats(project), limit=2)
    assert "and 3 more" in html


def test_a_limit_of_zero_shows_everything(project):
    translate(project, "de-DE", {
        text: "x" * 200
        for text in ("Bar Height", "Width", "Pen", "Spacing", "Print Offset")
    })
    html = render_report(check_project(project), project_stats(project), limit=0)
    assert "more</p>" not in html


def test_stats_are_optional(project):
    html = render_report(check_project(project))
    assert "<td>de-DE</td>" in html


def test_the_command_line(project, tmp_path):
    out = tmp_path / "report.html"
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "check", "--format", "html", "-o", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()
    assert "<h1>V4T-TIJ</h1>" in out.read_text(encoding="utf-8")


def test_the_command_line_to_stdout(project):
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"), "check", "--format", "html",
    ])
    assert result.stdout.startswith("<!doctype html>")
