import shutil
from datetime import date
from xml.etree import ElementTree

import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import SourceError
from v4t_translate.mt.memory import TranslationMemory
from v4t_translate.mt.tmx import read_tmx, write_tmx
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.memory import absorb_tmx, export_tmx, memory_path

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""

TMX = """<?xml version="1.0" encoding="utf-8"?>
<tmx version="1.4">
  <header srclang="en-US" datatype="plaintext"/>
  <body>
    <tu>
      <tuv xml:lang="en-US"><seg>Print started</seg></tuv>
      <tuv xml:lang="de-DE"><seg>Druck gestartet</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="EN"><seg>Firing Voltage</seg></tuv>
      <tuv xml:lang="DE"><seg>Zündspannung</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en-US"><seg>Only English here</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en-US"><seg>Pen <ph>{1}</ph> is empty</seg></tuv>
      <tuv xml:lang="de-DE"><seg>Stift <ph>{1}</ph> ist leer</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en-US"><seg>Purge Settings</seg></tuv>
      <tuv xml:lang="fr-FR"><seg>Reglages de purge</seg></tuv>
    </tu>
  </body>
</tmx>
"""


@pytest.fixture
def tmx_path(tmp_path):
    path = tmp_path / "agency.tmx"
    path.write_text(TMX, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def test_the_pairs_are_read(tmx_path):
    read = read_tmx(tmx_path, "de-DE")
    assert ("Print started", "Druck gestartet") in read.pairs
    assert ("Firing Voltage", "Zündspannung") in read.pairs


def test_the_source_language_is_reported(tmx_path):
    assert read_tmx(tmx_path, "de-DE").source_language == "en-US"


def test_a_bare_language_code_matches(tmx_path):
    # One tool writes de-DE and another writes DE for the same thing.
    read = read_tmx(tmx_path, "de-DE")
    assert any(pair[1] == "Zündspannung" for pair in read.pairs)


def test_a_segment_with_no_target_is_counted_not_dropped_silently(tmx_path):
    read = read_tmx(tmx_path, "de-DE")
    assert read.skipped_incomplete == 2
    assert all(pair[0] != "Only English here" for pair in read.pairs)


def test_inline_markup_is_skipped_and_counted(tmx_path):
    # Dropping a <ph> and keeping its text would change the string silently.
    read = read_tmx(tmx_path, "de-DE")
    assert read.skipped_inline == 1
    assert all("Pen" not in pair[0] for pair in read.pairs)


def test_another_language_is_not_read(tmx_path):
    read = read_tmx(tmx_path, "de-DE")
    assert all("purge" not in pair[1].lower() for pair in read.pairs)


def test_the_summary_reads(tmx_path):
    assert read_tmx(tmx_path, "de-DE").summary() == (
        "2 pairs, 1 with inline markup, 2 incomplete"
    )


def test_an_underscore_language_code(tmp_path):
    path = tmp_path / "u.tmx"
    path.write_text(
        '<tmx version="1.4"><body><tu>'
        '<tuv xml:lang="en_US"><seg>Pen</seg></tuv>'
        '<tuv xml:lang="de_DE"><seg>Stift</seg></tuv>'
        "</tu></body></tmx>",
        encoding="utf-8",
    )
    assert read_tmx(path, "de-DE").pairs == [("Pen", "Stift")]


def test_a_plain_lang_attribute(tmp_path):
    path = tmp_path / "u.tmx"
    path.write_text(
        '<tmx version="1.4"><body><tu>'
        '<tuv lang="en-US"><seg>Pen</seg></tuv>'
        '<tuv lang="de-DE"><seg>Stift</seg></tuv>'
        "</tu></body></tmx>",
        encoding="utf-8",
    )
    assert read_tmx(path, "de-DE").pairs == [("Pen", "Stift")]


def test_a_file_that_is_not_a_tmx(tmp_path):
    path = tmp_path / "x.tmx"
    path.write_text("<resources/>", encoding="utf-8")
    with pytest.raises(SourceError, match="expected <tmx>"):
        read_tmx(path, "de-DE")


def test_a_file_that_is_not_xml(tmp_path):
    path = tmp_path / "x.tmx"
    path.write_text("not xml at all", encoding="utf-8")
    with pytest.raises(SourceError, match="not readable XML"):
        read_tmx(path, "de-DE")


def test_a_missing_file(tmp_path):
    with pytest.raises(SourceError, match="does not exist"):
        read_tmx(tmp_path / "nope.tmx", "de-DE")


def test_an_unknown_language(tmx_path):
    with pytest.raises(SourceError, match="not a language this build knows"):
        read_tmx(tmx_path, "Klingon")


def test_writing_a_tmx(tmp_path):
    path = tmp_path / "out.tmx"
    with TranslationMemory() as memory:
        memory.remember("de-DE", "Print started", "Druck gestartet")
        memory.remember("de-DE", "Firing Voltage", "Zündspannung")
        memory.remember("zh-TW", "Print started", "列印已開始")

        assert write_tmx(path, memory, "de-DE", today=date(2025, 7, 1)) == 2

    root = ElementTree.parse(path).getroot()
    assert root.tag == "tmx"
    assert len(root.findall(".//tu")) == 2


def test_the_written_header(tmp_path):
    path = tmp_path / "out.tmx"
    with TranslationMemory() as memory:
        memory.remember("de-DE", "Pen", "Stift")
        write_tmx(path, memory, "de-DE", version="0.3.0", today=date(2025, 7, 1))

    header = ElementTree.parse(path).getroot().find("header")
    assert header.get("creationtool") == "v4t-translate"
    assert header.get("creationtoolversion") == "0.3.0"
    assert header.get("srclang") == "en-US"
    assert header.get("creationdate").startswith("20250701")


def test_markup_in_a_translation_is_escaped(tmp_path):
    path = tmp_path / "out.tmx"
    with TranslationMemory() as memory:
        memory.remember("de-DE", "Tap <b>Purge</b>", "Tippe <b>Reinigen</b> & warte")
        write_tmx(path, memory, "de-DE")

    text = path.read_text(encoding="utf-8")
    assert "&lt;b&gt;" in text
    assert "&amp;" in text
    ElementTree.parse(path)


def test_a_round_trip(tmp_path):
    path = tmp_path / "out.tmx"
    with TranslationMemory() as memory:
        memory.remember("de-DE", "Print started", "Druck gestartet")
        memory.remember("de-DE", "Firing Voltage", "Zündspannung")
        write_tmx(path, memory, "de-DE")

    read = read_tmx(path, "de-DE")
    assert dict(read.pairs) == {
        "Print started": "Druck gestartet",
        "Firing Voltage": "Zündspannung",
    }


def test_writing_an_unknown_language(tmp_path):
    with TranslationMemory() as memory, pytest.raises(SourceError):
        write_tmx(tmp_path / "x.tmx", memory, "Klingon")


def test_absorb_into_a_project(project, tmx_path):
    report = absorb_tmx(project, tmx_path, "de-DE")
    assert report.added == 2
    assert report.locales == ["de-DE"]
    assert any("inline markup" in w for w in report.warnings)
    assert any("no de-DE side" in w for w in report.warnings)

    with TranslationMemory(memory_path(project)) as memory:
        match = memory.recall("de-DE", "Print started")
        assert match.target == "Druck gestartet"
        assert match.origin == "agency.tmx"


def test_export_from_a_project(project, tmp_path):
    with TranslationMemory(memory_path(project)) as memory:
        memory.remember("de-DE", "Print started", "Druck gestartet")

    path = tmp_path / "for-agency.tmx"
    assert export_tmx(project, path, "de-DE") == 1
    assert "Druck gestartet" in path.read_text(encoding="utf-8")


def test_the_command_line_import(project, tmx_path):
    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "memory", "import-tmx", str(tmx_path), "de-DE",
    ])
    assert result.exit_code == 0
    assert "2 units from de-DE" in result.output
    assert "inline markup" in result.output


def test_the_command_line_export(project, tmp_path):
    runner = CliRunner()
    config_arg = ["-c", str(project.root / "v4t-translate.toml")]
    runner.invoke(main, [*config_arg, "memory", "import-tmx",
                         str(tmp_path / "agency.tmx"), "de-DE"], catch_exceptions=True)

    with TranslationMemory(memory_path(project)) as memory:
        memory.remember("de-DE", "Pen", "Stift")

    out = tmp_path / "out.tmx"
    result = runner.invoke(main, [*config_arg, "memory", "export-tmx",
                                  str(out), "de-DE"])
    assert result.exit_code == 0
    assert "pairs ->" in result.output
    assert out.exists()
