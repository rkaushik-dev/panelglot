"""The whole round, once, through the command line.

Every operation has its own tests. This one exists because the failures that
reach people are almost never inside an operation. They are between two of
them: a workbook that exports and then does not import, a catalog that check
reads differently from build, a pack that builds and then fails verify.

So this walks the round a person actually does, in order, and asserts on what
they would see at each step. It is slow by the standards of the rest of the
suite and it has caught three things nothing else would have.
"""

from __future__ import annotations

import shutil

import pytest
from click.testing import CliRunner
from openpyxl import load_workbook

from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.emit.v4l import read_pack

# The Mini's LCD is twenty columns and its font is a 5x7 ASCII subset, so
# the German for it is short and spelled without umlauts. That is what
# actually ships on this panel, and it is exactly the constraint the checks
# are there to enforce.
GERMAN = {
    "Print started": "Druck gestartet",
    "Print stopped": "Druck gestoppt",
    "Purge Settings": "Bereinigung",
    "Firing Voltage": "Zuendspannung",
    "Pen": "Stift",
    "Spacing": "Abstand",
    "Ink low in pen %d": "Stift %d fast leer",
    "Purge all pens?\nPress OK": "Alle spuelen?\nOK",
}

CONFIG = """
[project]
name = "V4T-Mini"
catalog_dir = "catalog"
workbook_dir = "Translate"

[[source]]
kind = "cheader"
path = "firmware/v4t_lang.h"

[protected]
patterns = ["mm"]

[locale."de-DE"]
panel = "mini-20x4"
font = "fonts/mini-5x7.fmx"

[[output]]
kind = "v4l"
path = "out/{locale}.v4l"

[[output]]
kind = "cheader"
path = "out/lng_{language}.h"

[check]
fail_on = "error"
"""


@pytest.fixture
def project(tmp_path, fixtures_dir):
    (tmp_path / "firmware").mkdir()
    shutil.copy(fixtures_dir / "v4t_lang.h", tmp_path / "firmware" / "v4t_lang.h")
    (tmp_path / "fonts").mkdir()
    shutil.copy(fixtures_dir / "fonts" / "mini-5x7.fmx",
                tmp_path / "fonts" / "mini-5x7.fmx")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


@pytest.fixture
def run(project):
    runner = CliRunner()

    def invoke(*args, expect: int | None = 0):
        result = runner.invoke(
            main, ["-c", str(project / "v4t-translate.toml"), *args]
        )
        if expect is not None:
            assert result.exit_code == expect, (
                f"{' '.join(args)} exited {result.exit_code}\n{result.output}"
            )
        return result

    return invoke


def fill_in(path, answers):
    """Do what a translator does: type into the Translation column."""
    book = load_workbook(path)
    sheet = book.active
    filled = 0

    for row in range(2, sheet.max_row + 1):
        source = sheet.cell(row=row, column=2).value
        if source in answers:
            sheet.cell(row=row, column=3, value=answers[source])
            filled += 1

    book.save(path)
    return filled


def test_the_whole_round(project, run):
    # 1. Read the firmware's string table.
    extract = run("extract")
    assert "messages:" in extract.output
    assert (project / "catalog" / "v4t-mini.json").exists()

    # 2. Nothing is translated, so nothing is wrong yet.
    assert "nothing found" in run("check").output

    # 3. Send the translator a workbook.
    run("export")
    workbook = project / "Translate" / "V4T-Mini - German.xlsx"
    assert workbook.exists()

    # 4. They fill some of it in and send it back.
    assert fill_in(workbook, GERMAN) == len(GERMAN)

    imported = run("import", str(workbook), "--strict")
    assert f"{len(GERMAN)} applied" in imported.output

    # 5. What came back is checked.
    assert run("check").exit_code == 0

    # 6. And built.
    build = run("build")
    assert "de-DE v4l:" in build.output

    pack = project / "out" / "de-DE.v4l"
    header = project / "out" / "lng_de.h"
    assert pack.exists()
    assert header.exists()

    # 7. The pack is what the firmware will accept.
    verify = run("verify", str(pack), "-H", str(project / "firmware" / "v4t_lang.h"))
    assert "de-DE, 9 strings" in verify.output

    decoded = read_pack(pack.read_bytes())
    assert decoded.strings[0] == "Druck gestartet"
    assert decoded.tag == "de-DE"

    # 8. And the slot nobody answered fell back to English rather than blank.
    assert "Stift %d fast leer" in decoded.strings
    assert "mm" in decoded.strings


def test_the_second_round_only_asks_about_what_changed(project, run):
    run("extract")
    run("export")
    workbook = project / "Translate" / "V4T-Mini - German.xlsx"
    fill_in(workbook, GERMAN)
    run("import", str(workbook))

    saved = project / "sent-round-1.json"
    shutil.copy(project / "catalog" / "v4t-mini.json", saved)

    # The firmware gains a string.
    header = project / "firmware" / "v4t_lang.h"
    header.write_text(
        header.read_text(encoding="utf-8")
        .replace("    LNG_COUNT", "    LNG_NEW_THING,\n    LNG_COUNT")
        .replace('    [LNG_CONFIRM_PURGE]  = "Purge all pens?\\n"',
                 '    [LNG_NEW_THING]      = "Head temperature",\n'
                 '    [LNG_CONFIRM_PURGE]  = "Purge all pens?\\n"'),
        encoding="utf-8",
    )

    run("extract")

    difference = run("diff", str(saved), "-l", "de-DE")
    assert "new      'Head temperature'" in difference.output
    assert "1 of those are still unanswered" in difference.output

    run("export", "--outstanding")
    follow_up = load_workbook(workbook).active
    sources = [follow_up.cell(row=r, column=2).value
               for r in range(2, follow_up.max_row + 1)]
    assert "Head temperature" in sources
    assert "Print started" not in sources


def test_a_bad_translation_stops_the_build(project, run):
    run("extract")
    run("export")

    workbook = project / "Translate" / "V4T-Mini - German.xlsx"
    fill_in(workbook, {**GERMAN, "Ink low in pen %d": "Wenig Tinte im Stift"})
    run("import", str(workbook))

    check = run("check", expect=None)
    assert check.exit_code != 0
    assert "placeholders" in check.output

    build = run("build", expect=None)
    assert build.exit_code != 0
    assert not (project / "out").exists()

    assert run("build", "--no-check").exit_code == 0


def test_memory_carries_answers_into_a_second_language(project, run):
    run("extract")
    run("export")

    workbook = project / "Translate" / "V4T-Mini - German.xlsx"
    fill_in(workbook, GERMAN)
    run("import", str(workbook))
    run("memory", "absorb")

    # A second product with the same strings.
    (project / "v4t-translate.toml").write_text(
        CONFIG.replace('name = "V4T-Mini"', 'name = "V4T-Mini-2"'), encoding="utf-8"
    )
    config = load_config(project / "v4t-translate.toml")
    run("extract")

    filled = run("pretranslate", "de-DE", "--trust-memory")
    assert "exact" in filled.output

    from v4t_translate.catalog.ids import message_key
    from v4t_translate.catalog.store import load_translations

    entries = load_translations(config.translations_path("de-DE"))
    assert entries.get(message_key("Print started")).text == "Druck gestartet"


def test_doctor_is_happy_at_the_end(project, run):
    run("extract")
    assert "nothing wrong" in run("doctor").output


def test_a_pseudo_round_finds_the_narrow_labels(project, run):
    run("extract")
    run("pretranslate", "de-DE", "--provider", "pseudo")

    check = run("check", "--fail-on", "never")
    # The Mini is a twenty column panel and pseudo is a third longer than the
    # English, which is the whole point of running it.
    assert "fitting" in check.output
