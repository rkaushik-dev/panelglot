"""Producing every configured output.

The build is the only operation that writes outside the project directory, so
it is the one that has to be predictable. Two rules follow from that.

It writes nothing until every output has been produced. A build that stops
half way leaves a German resource script next to a Chinese one from last week,
and the next person to look cannot tell which is which. So everything is
generated into memory, and only then written.

And it refuses to run over a catalog whose check is failing, unless told
otherwise. Shipping a placeholder mismatch is a crash on a customer line, and
the whole point of having the check is that the build respects it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.store import Catalog, load_translations
from ..config import LocaleEntry, OutputEntry, ProjectConfig
from ..emit.androidxml import qualifier_for
from ..emit.base import EmitOptions, EmitResult
from ..emit.registry import get_emitter
from ..errors import EmitError
from ..locales import Locale
from .project import require_catalog, selected_locales

__all__ = [
    "BuildResult",
    "build_project",
    "resolve_output_path",
    "destination_for",
    "is_inside",
    "unreproducible_outputs",
]


@dataclass
class BuildResult:
    """Everything one build produced."""

    outputs: list[tuple[str, str, EmitResult]] = field(default_factory=list)
    """``(locale tag, output kind, result)`` in the order they were produced."""

    warnings: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        if not self.outputs:
            return "nothing to build"
        return f"{len(self.outputs)} outputs across {len(self.locales())} languages"

    def locales(self) -> list[str]:
        seen: list[str] = []
        for tag, _, _ in self.outputs:
            if tag not in seen:
                seen.append(tag)
        return seen

    @property
    def total_bytes(self) -> int:
        return sum(result.bytes_written for _, _, result in self.outputs)


def resolve_output_path(template: str, *, project: str, locale: Locale) -> str:
    """Substitute the placeholders a path template may use."""
    return template.format(
        project=project,
        locale=locale.tag,
        language=locale.tag.split("-")[0],
        qualifier=qualifier_for(locale),
        codepage=locale.codepage,
    )


def is_inside(path: Path, root: Path) -> bool:
    """Whether ``path`` resolves to somewhere under ``root``."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def destination_for(config: ProjectConfig, output: OutputEntry,
                    entry: LocaleEntry) -> Path:
    """Where one output lands, with the path checked before anything is written.

    An output path is a template out of a config file, and this runs on build
    machines. A template with ``..`` in it, or an absolute path somebody
    pasted from their own laptop, would write outside the project, and the
    only sign would be a file appearing somewhere nobody looked.

    A project that genuinely needs to write elsewhere says so with
    ``allow_outside``, which is one word in a config and shows up in review.
    """
    relative = resolve_output_path(output.path, project=config.name,
                                   locale=entry.locale)
    destination = config.root / relative

    if output.allow_outside or is_inside(destination, config.root):
        return destination

    raise EmitError(
        f"output {output.kind} for {entry.tag} resolves to {destination}, which "
        f"is outside {config.root}. Set allow_outside on that output if that is "
        f"deliberate"
    )


def build_project(config: ProjectConfig, *, locales: list[str] | None = None,
                  dry_run: bool = False) -> BuildResult:
    """Produce every configured output for every requested language."""
    catalog = require_catalog(config)
    result = BuildResult()

    if not config.outputs:
        result.warnings.append(
            "no [[output]] entries in the project file, so there is nothing to build"
        )
        return result

    wanted = selected_locales(config, locales)
    staged: list[tuple[Path, bytes]] = []

    for entry in wanted:
        translations = load_translations(config.translations_path(entry.tag))

        for output in config.outputs:
            if not output.applies_to(entry.tag):
                continue

            emitted, path, data = _produce(config, catalog, translations, entry, output)
            result.outputs.append((entry.tag, output.kind, emitted))
            result.warnings.extend(emitted.warnings)
            staged.append((path, data))

    if dry_run:
        return result

    for path, data in staged:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        result.written.append(path)

    return result


def _produce(config: ProjectConfig, catalog: Catalog, translations, entry: LocaleEntry,
             output: OutputEntry) -> tuple[EmitResult, Path, bytes]:
    """Run one emitter into a scratch directory and read the bytes back.

    Emitters write files because that is the honest interface for formats that
    are directories or that need to know their own name. Staging keeps the
    all-or-nothing promise without every emitter having to grow a bytes mode.

    The scratch directory is outside the project, not beside the destination.
    Putting it beside meant a dry run created the whole output tree before
    deciding not to write anything into it.
    """
    destination = destination_for(config, output, entry)
    emitter = get_emitter(output.kind)

    with tempfile.TemporaryDirectory(prefix="v4t-build-") as scratch_dir:
        scratch = Path(scratch_dir) / destination.name
        options = EmitOptions(
            path=scratch,
            locale=entry.locale,
            source_path=(config.root / output.source) if output.source else None,
            encoding=output.encoding,
            fallback_to_source=output.fallback_to_source,
        )
        emitted = emitter.emit(catalog, translations, options)
        data = scratch.read_bytes()

    emitted.path = destination
    return emitted, destination, data




def unreproducible_outputs(config: ProjectConfig, *,
                           locales: list[str] | None = None) -> list[str]:
    """Outputs that come out differently when built twice in a row.

    Builds everything into memory twice and compares the bytes. It costs a
    second build and it is the only check that actually answers the question,
    because an emitter that is right about determinism today is one library
    upgrade away from a dict that iterates in a different order.

    Returns the ones that disagree, named for a report. An empty list is the
    answer everybody wants.
    """
    first = _staged(config, locales)
    second = _staged(config, locales)

    problems: list[str] = []
    for name, data in first.items():
        if second.get(name) != data:
            problems.append(name)

    problems.extend(name for name in second if name not in first)
    return sorted(problems)


def _staged(config: ProjectConfig, locales: list[str] | None) -> dict[str, bytes]:
    """Everything a build would write, keyed by what it would be called."""
    catalog = require_catalog(config)
    produced: dict[str, bytes] = {}

    for entry in selected_locales(config, locales):
        translations = load_translations(config.translations_path(entry.tag))
        for output in config.outputs:
            if not output.applies_to(entry.tag):
                continue
            _, path, data = _produce(config, catalog, translations, entry, output)
            produced[f"{entry.tag} {output.kind} {path.name}"] = data

    return produced


def check_before_build(config: ProjectConfig, *, locales: list[str] | None = None) -> None:
    """Refuse to build a language whose check is failing.

    Imported here rather than at module scope: check pulls in the whole rules
    package, and a build that has been told to skip the check should not pay
    for it.
    """
    from .check import check_project

    result = check_project(config, locales=locales)
    if result.should_fail(config.check.fail_on):
        raise EmitError(
            f"check is failing with {len(result.report.errors)} errors, so the build "
            f"is refused. Run check to see them, or pass --no-check"
        )
