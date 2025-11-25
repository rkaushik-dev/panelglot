"""One round, start to finish, against a project this script builds.

The unit tests exercise every operation and they all pass on machines where
the installed package is broken, because they import from the source tree. The
things that break at install time are the things they cannot see: an entry
point that was never registered, a data file that is not in the wheel, a
module that imports fine from a checkout and not from site-packages.

So this drives the command line the way a person does, in a scratch directory,
against a printer's worth of resource script that it writes itself. It is
deliberately not pytest: it has to be runnable against an installed wheel with
nothing else present, which is exactly the situation the unit tests cannot
reproduce.

It fails loudly and early. Every step prints what it did, so a CI log shows
which one stopped rather than a traceback fifteen frames deep in click.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: What the scratch project is built from. Small, and covering the constructs
#: that have each broken something at least once: a wrapped control, a string
#: table with a continuation, a menu with an accelerator hint, a format string.
SAMPLE_RC = """\
#include "resource.h"

IDD_SETUP DIALOGEX 0, 0, 200, 120
STYLE DS_SETFONT | WS_POPUP | WS_CAPTION
CAPTION "Printer Setup"
FONT 8, "MS Shell Dlg", 400, 0, 0x1
BEGIN
    LTEXT           "Bar Height",IDC_STATIC,7,7,49,8
    EDITTEXT        IDC_BAR_HEIGHT,60,5,40,14,ES_AUTOHSCROLL
    CONTROL         "Human Readable",IDC_HUMAN,"Button",
                    BS_AUTOCHECKBOX | WS_TABSTOP,7,26,80,10
    DEFPUSHBUTTON   "OK",IDOK,90,100,50,16
    PUSHBUTTON      "Cancel",IDCANCEL,145,100,50,16
END

IDR_MAINFRAME MENU
BEGIN
    POPUP "&File"
    BEGIN
        MENUITEM "&New\\tCtrl+N",   ID_FILE_NEW
        MENUITEM "E&xit",          ID_APP_EXIT
    END
END

IDR_MAINFRAME ACCELERATORS
BEGIN
    "N",  ID_FILE_NEW,  VIRTKEY, CONTROL, NOINVERT
END

STRINGTABLE
BEGIN
    IDS_STARTED     "Print started"
    IDS_RANGE       "Please input from %.1fV to %.1fV."
    IDS_LONG        "This distance cannot be greater than "
                    "the print spacing"
END
"""

CONFIG = """\
[project]
name = "V4T-Selfcheck"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[[output]]
kind = "rc"
path = "out/{locale}/V4T.rc"
source = "src/V4T.rc"

[[output]]
kind = "po"
path = "out/{locale}.po"
"""

#: Where the timestamps come from, so the two builds can be compared.
PINNED = "1739525400"


class Failed(Exception):
    """A step did not do what it said it would."""


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def step(name: str) -> None:
    print(f"\n== {name}", flush=True)


def run(root: Path, *args: str, expect: int = 0) -> str:
    """Run the installed command line and return its output."""
    command = [sys.executable, "-m", "v4t_translate", "-c",
               str(root / "v4t-translate.toml"), *args]

    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", env=_environment())

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != expect:
        raise Failed(
            f"{' '.join(args)} exited {result.returncode}, expected {expect}\n"
            f"{output}"
        )

    say(f"{' '.join(args) or '(no arguments)'} -> {result.returncode}")
    return output


def _environment() -> dict[str, str]:
    import os

    environ = dict(os.environ)
    environ["SOURCE_DATE_EPOCH"] = PINNED
    environ["NO_COLOR"] = "1"
    return environ


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


def build_project(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "V4T.rc").write_text(SAMPLE_RC, encoding="utf-8")
    (root / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")


def translate(root: Path) -> None:
    """Answer every message, the way an import would."""
    catalog = json.loads((root / "catalog" / "v4t-selfcheck.json")
                         .read_text(encoding="utf-8"))

    entries = {}
    for message in catalog["messages"]:
        text = message["text"]
        entries[message["key"]] = {
            "text": text.replace("Print", "Druck").replace("Height", "Hoehe"),
            "state": "approved",
        }

    path = root / "catalog" / "de-DE.json"
    path.write_text(
        json.dumps({"format": 1, "locale": "de-DE", "entries": entries},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    say(f"answered {len(entries)} messages")


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="v4t-selfcheck-"))
    root = scratch / "project"

    try:
        step("the build says what it is")
        print(subprocess.run([sys.executable, "-m", "v4t_translate",
                              "-v", "--version"],
                             capture_output=True, text=True,
                             env=_environment()).stdout)

        step("a project")
        build_project(root)
        # doctor exits with the check-failed code, because it found real
        # problems: there is no catalog yet and no font metrics.
        run(root, "doctor", expect=2)

        step("extract")
        run(root, "extract")
        expect((root / "catalog" / "v4t-selfcheck.json").exists(),
               "extract wrote no catalog")

        step("status before any work")
        output = run(root, "status")
        expect("not shippable" in output, "an empty project claimed to be ready")

        step("export")
        run(root, "export")
        expect(any((root / "workbooks").glob("*.xlsx")), "export wrote no workbook")

        step("the rules explain themselves")
        output = run(root, "check", "--explain", "fitting")
        expect("fitting" in output, "--explain said nothing about fitting")

        step("translate and check")
        translate(root)
        run(root, "check", "--fail-on", "never")
        run(root, "check", "--format", "sarif", "-o",
            str(root / "check.sarif"), "--fail-on", "never")
        expect(json.loads((root / "check.sarif").read_text(encoding="utf-8"))
               ["version"] == "2.1.0", "the sarif is not sarif")

        step("status after")
        output = run(root, "status")
        expect("de-DE" in output, "status forgot the only language")

        step("build")
        run(root, "build", "--no-check", "--manifest")
        expect((root / "out" / "de-DE" / "V4T.rc").exists(), "no resource script")
        expect((root / "out" / "de-DE.po").exists(), "no po file")

        step("build twice, byte for byte")
        run(root, "build", "--no-check", "--reproducible")

        step("audit what was built")
        run(root, "audit", str(root / "out" / "manifest.json"),
            "--extension", ".rc", "--extension", ".po")

        step("coverage was recorded")
        run(root, "stats", "--record")
        expect((root / "catalog" / "coverage.jsonl").exists(),
               "stats --record recorded nothing")

        print("\nall good")
        return 0

    except Failed as failure:
        print(f"\nFAILED: {failure}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
