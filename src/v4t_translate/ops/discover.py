"""Finding the files a new project should read.

``init`` takes the sources as arguments, which is fine when somebody already
knows what they are. Nobody setting up a product for the first time does. The
V4T-TIJ tree has forty .h files and one of them is the string table; it has
three .rc files and two of them are property pages that the main one includes.

So this walks a tree and says what it found, with a reason for each, and the
person confirms it. That last part matters: guessing and writing the config
silently is how a project ends up reading the wrong resource.h for a year.

What it looks for, and how it tells the difference:

A ``.rc`` is a resource script. There is usually one that matters and several
that are included by it; the one that matters is the one nothing else includes.

A ``.h`` is only interesting when it holds a string table, which means an
array of string literals indexed by an enum. A ``resource.h`` full of
``#define IDC_STATIC 1000`` is a symbol file, not a source, and it goes in the
``symbols`` key instead. That is told from the Win32 id prefixes and not from
"a file of #define", because a board header full of register addresses is also
a file of #define and saying it belongs in the symbols key is worse than
saying nothing about it.

A ``strings.xml`` is only interesting under a ``values`` directory, because
that is what makes it a resource rather than a file somebody named the same.

Directories that are never sources are skipped by name. A node_modules with
forty thousand files in it takes long enough to walk that people assume the
tool has hung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Found", "Discovery", "discover_sources", "SKIP_DIRECTORIES"]

#: Never walked into. Not because a source cannot be there, but because one
#: never has been and the wait is what people notice.
SKIP_DIRECTORIES = frozenset({
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    "build", "dist", "out", "obj", "bin", "Debug", "Release", ".idea", ".vs",
})

#: How deep to walk. A source tree that buries its resources nine levels down
#: exists, and walking a whole disk because somebody pointed this at C:\ does
#: not need to be possible.
MAX_DEPTH = 8

#: An array of string literals indexed by an enum, which is what the Mini's
#: generated table looks like. Matched loosely: the point is to tell it apart
#: from a resource.h, not to parse it.
_STRING_TABLE = re.compile(
    r"(?:const\s+)?char\s*\*[^=;]*\[\s*[A-Za-z_]\w*\s*\]\s*=\s*\{", re.S
)

#: One include of another resource script, which is how the main .rc is told
#: from the property pages it pulls in.
_RC_INCLUDE = re.compile(r'^\s*#include\s+"([^"]+\.rc)"', re.M | re.I)

#: A resource symbol file. Matched on the Win32 id prefixes rather than on
#: "a file of #define", because a board header full of register addresses is
#: also a file of #define and telling somebody it belongs in the symbols key
#: is worse than saying nothing about it.
_RESOURCE_IDS = re.compile(r"^\s*#define\s+(?:IDD|IDC|IDS|IDR|IDM|IDB)_\w+\s+", re.M)


@dataclass(frozen=True)
class Found:
    """One file worth reading, and why."""

    kind: str
    path: str
    """Relative to the directory that was searched, posix separators."""

    reason: str
    symbols: str = ""
    """A symbol file that belongs with this one, when there is an obvious one."""

    def describe(self) -> str:
        line = f"{self.kind:<11} {self.path}"
        if self.symbols:
            line += f"  (+ {self.symbols})"
        return f"{line}\n              {self.reason}"


@dataclass
class Discovery:
    """Everything one walk turned up."""

    root: Path
    sources: list[Found] = field(default_factory=list)
    included: list[str] = field(default_factory=list)
    """Resource scripts another one includes. Read through it, not directly."""

    skipped: list[str] = field(default_factory=list)
    """Files that looked like candidates and were not."""

    def as_pairs(self) -> list[tuple[str, str]]:
        """``(kind, path)`` for :func:`~.init.init_project`."""
        return [(found.kind, found.path) for found in self.sources]

    def summary(self) -> str:
        if not self.sources:
            return "nothing that looks like a source"
        kinds = ", ".join(sorted({found.kind for found in self.sources}))
        return f"{len(self.sources)} sources ({kinds})"


def discover_sources(root: Path | str, *, max_depth: int = MAX_DEPTH) -> Discovery:
    """Walk ``root`` and report the files a project would read."""
    root = Path(root)
    discovery = Discovery(root=root)

    candidates = sorted(_walk(root, max_depth))
    included = _included_scripts(candidates)
    discovery.included = sorted(included)

    for path in candidates:
        relative = path.relative_to(root).as_posix()

        if path.suffix.lower() == ".rc":
            if path.name.lower() in included:
                continue
            discovery.sources.append(Found(
                kind="rc", path=relative,
                reason="a resource script that nothing else includes",
                symbols=_symbols_beside(path, root),
            ))

        elif path.suffix.lower() == ".h":
            if _holds_a_string_table(path):
                discovery.sources.append(Found(
                    kind="cheader", path=relative,
                    reason="an array of string literals indexed by an enum",
                ))
            elif _is_symbol_file(path):
                discovery.skipped.append(
                    f"{relative}: control ids, not strings. It belongs in the "
                    f"symbols key of a resource script."
                )

        elif path.name.lower() == "strings.xml":
            if path.parent.name.lower().startswith("values"):
                discovery.sources.append(Found(
                    kind="androidxml", path=relative,
                    reason=f"under {path.parent.name}, so the platform reads it",
                ))
            else:
                discovery.skipped.append(
                    f"{relative}: not under a values directory, so Android "
                    f"never reads it."
                )

    return discovery


def _walk(root: Path, max_depth: int) -> list[Path]:
    """Candidate files, skipping the directories that never hold one."""
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return

        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRECTORIES:
                    walk(entry, depth + 1)
            elif entry.suffix.lower() in (".rc", ".h", ".xml"):
                found.append(entry)

    walk(root, 0)
    return found


def _included_scripts(candidates: list[Path]) -> set[str]:
    """Resource script file names that another script includes.

    By name rather than by resolved path, because an ``#include`` in a .rc is
    relative to the including file and the two are almost always siblings.
    Getting this wrong would list a property page as its own source, which
    extracts the same strings twice.
    """
    included: set[str] = set()

    for path in candidates:
        if path.suffix.lower() != ".rc":
            continue
        for name in _RC_INCLUDE.findall(_read(path)):
            included.add(Path(name.replace("\\", "/")).name.lower())

    return included


def _symbols_beside(path: Path, root: Path) -> str:
    """A ``resource.h`` sitting next to a resource script, if there is one."""
    candidate = path.with_name("resource.h")
    if candidate.exists():
        return candidate.relative_to(root).as_posix()
    return ""


def _holds_a_string_table(path: Path) -> bool:
    return bool(_STRING_TABLE.search(_read(path)))


def _is_symbol_file(path: Path) -> bool:
    text = _read(path)
    return bool(_RESOURCE_IDS.search(text)) and not _STRING_TABLE.search(text)


def _read(path: Path) -> str:
    """The file, or an empty string. A file we cannot read is not a source."""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
