"""Setting a new project up.

Two of the four products were localised by copying another product's config
and editing it, and both copies kept a `[[source]]` pointing at the product
they were copied from. One of them shipped that way for a release: the German
was fine, it was just the German for a different printer.

So there is a scaffold. It writes a config with the sources it was told
about and nothing else, a catalog directory, a glossary with the header row
in it, and the .gitignore lines that keep the cache and the build output out
of the repository.

It writes nothing over an existing file. A project that already exists is a
project somebody has put work into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import CONFIG_FILENAME
from ..errors import ConfigError
from ..glossary import REQUIRED_COLUMNS
from ..locales import resolve
from ..sources.registry import available_kinds

__all__ = ["InitResult", "init_project", "render_config"]

_GITIGNORE_LINES = [
    "# v4t-translate",
    "catalog/.extraction-cache.json",
    "catalog/memory.sqlite3",
    "out/",
    "~$*.xlsx",
]


@dataclass
class InitResult:
    """What the scaffold wrote."""

    root: Path
    written: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    """Files that were already there and were left alone."""

    def summary(self) -> str:
        return (
            f"{len(self.written)} files written, {len(self.skipped)} already there"
        )


def render_config(name: str, sources: list[tuple[str, str]],
                  locales: list[str]) -> str:
    """The project file for a new project.

    Comments included. The config is the thing people copy, so the comments
    are the closest thing to documentation most of them will read.
    """
    lines = [
        f"# {name} localisation project.",
        "#",
        "# Paths are relative to this file, not to where you run the tool.",
        "",
        "[project]",
        f'name = "{name}"',
        'source_locale = "en-US"',
        'catalog_dir = "catalog"',
        'workbook_dir = "Translate"',
        'output_dir = "out"',
        'glossary = "glossary/terms.csv"',
        "",
    ]

    if sources:
        for kind, path in sources:
            lines.extend([
                "[[source]]",
                f'kind = "{kind}"',
                f'path = "{path}"',
            ])
            if kind == "rc":
                lines.append('# symbols = "../Product/resource.h"')
                lines.append('# encoding = "cp1252"')
            lines.append("")
    else:
        lines.extend([
            "# Nothing to read yet. Add one entry per file:",
            "#",
            "# [[source]]",
            '# kind = "rc"',
            '# path = "../V4T-TIJ/V4T/V4T.rc"',
            '# symbols = "../V4T-TIJ/V4T/resource.h"',
            "",
        ])

    for tag in locales:
        locale = resolve(tag)
        lines.extend([
            f'[locale."{locale.tag}"]  # {locale.english_name}',
            '# panel = "tij-800x600"',
            '# font = "fonts/tahoma-8.fmx"',
            "",
        ])

    lines.extend([
        "# One entry per file the build produces. {locale}, {language},",
        "# {qualifier} and {codepage} are substituted per language.",
        "#",
        "# [[output]]",
        '# kind = "rc"',
        '# path = "out/{locale}/V4T.rc"',
        '# source = "../V4T-TIJ/V4T/V4T.rc"',
        "",
        "[check]",
        'fail_on = "error"',
        "",
    ])

    return "\n".join(lines)


def init_project(root: Path | str, *, name: str,
                 sources: list[tuple[str, str]] | None = None,
                 locales: list[str] | None = None,
                 write_gitignore: bool = True) -> InitResult:
    """Scaffold a project in ``root``."""
    root = Path(root)
    sources = sources or []
    locales = locales or []

    known = set(available_kinds())
    for kind, _ in sources:
        if kind not in known:
            raise ConfigError(
                f"unknown source kind {kind!r}. Known kinds: {', '.join(sorted(known))}"
            )

    for tag in locales:
        resolve(tag)

    result = InitResult(root=root)
    root.mkdir(parents=True, exist_ok=True)

    _write(result, root / CONFIG_FILENAME, render_config(name, sources, locales))
    _write(result, root / "catalog" / ".gitkeep", "")
    _write(
        result,
        root / "glossary" / "terms.csv",
        ",".join([*REQUIRED_COLUMNS, "forbidden", "note"]) + "\n",
    )
    _write(result, root / "fonts" / ".gitkeep", "")

    if write_gitignore:
        _append_gitignore(result, root / ".gitignore")

    return result


def _write(result: InitResult, path: Path, text: str) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    result.written.append(path)


def _append_gitignore(result: InitResult, path: Path) -> None:
    """Add our lines to a .gitignore, leaving whatever is already in it."""
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [line for line in _GITIGNORE_LINES if line not in existing]

    if not missing:
        result.skipped.append(path)
        return

    body = "\n".join(existing)
    if body and not body.endswith("\n"):
        body += "\n"
    if existing:
        body += "\n"

    path.write_text(body + "\n".join(missing) + "\n", encoding="utf-8")
    result.written.append(path)
