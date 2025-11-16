"""Checking a set of files against the manifest that says what they are.

The manifest is written by the build and archived with the release. This reads
it back and asks the only question anybody asks of it: is what is on this SD
card what we shipped.

That question comes up in three places, and they want the same answer.

Before a release goes out, against the build directory, to catch a file that
was rebuilt after the manifest was written. It happens: somebody fixes one
string, rebuilds one language, and the archive is now half from each run.

At a customer site, against a card somebody posted back, when a panel is
showing something that is not in any version we can find.

And in the build, against the directory it just wrote, which sounds circular
and is not: it catches a filesystem that truncated a file, a build that raced
with an antivirus scanner, and a path template that pointed two languages at
one file. The third one has its own check now, and this found it first.

Files not in the manifest are reported as well as files missing from it. An
extra .v4l on a card is how a panel ends up loading a pack from the previous
release, and nothing else looks for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..emit.manifest import MANIFEST_VERSION, file_hash
from ..errors import EmitError

__all__ = ["FileVerdict", "AuditResult", "read_manifest", "audit_against"]


@dataclass(frozen=True)
class FileVerdict:
    """One file the manifest names."""

    path: str
    state: str
    """``ok``, ``missing``, ``changed`` or ``resized``."""

    expected: str = ""
    found: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    def describe(self) -> str:
        if self.state == "missing":
            return f"{self.path} is not there"
        if self.state == "resized":
            return f"{self.path} is {self.found} bytes and should be {self.expected}"
        if self.state == "changed":
            return (
                f"{self.path} hashes {self.found[:12]} and the manifest says "
                f"{self.expected[:12]}"
            )
        return f"{self.path} is as built"


@dataclass
class AuditResult:
    """What one directory looks like against one manifest."""

    manifest: str
    root: Path
    project: str = ""
    built_at: str = ""
    files: list[FileVerdict] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    """Files under the root that the manifest does not mention."""

    @property
    def problems(self) -> list[FileVerdict]:
        return [entry for entry in self.files if not entry.ok]

    @property
    def matches(self) -> bool:
        return not self.problems and not self.unexpected

    def summary(self) -> str:
        if self.matches:
            return (
                f"{len(self.files)} files match the manifest for {self.project} "
                f"built {self.built_at}"
            )
        parts = []
        if self.problems:
            parts.append(f"{len(self.problems)} do not match")
        if self.unexpected:
            parts.append(f"{len(self.unexpected)} are not in the manifest")
        return f"{len(self.files)} files checked, {', '.join(parts)}"


def read_manifest(path: Path | str) -> dict:
    """Read a manifest, refusing one this build cannot understand."""
    path = Path(path)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EmitError(f"{path} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise EmitError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise EmitError(f"{path} does not hold a manifest")

    version = payload.get("manifest", 0)
    if not isinstance(version, int) or version > MANIFEST_VERSION:
        raise EmitError(
            f"{path} is manifest format {version} and this build reads up to "
            f"{MANIFEST_VERSION}"
        )

    return payload


def audit_against(manifest_path: Path | str, root: Path | str, *,
                  extensions: tuple[str, ...] = ()) -> AuditResult:
    """Compare what is under ``root`` against what ``manifest_path`` says.

    ``root`` is the project directory, not the output directory, because the
    manifest records paths relative to the project. It is worth saying because
    the manifest itself usually sits in the output directory, and pointing
    this at that directory reports every file as missing, which is technically
    correct and completely unhelpful.

    ``extensions`` limits which files count as unexpected. Without it, a build
    directory holding a log or an editor backup would be reported, and a check
    that cries about a .bak is a check people stop running.
    """
    manifest_path = Path(manifest_path)
    root = Path(root)

    payload = read_manifest(manifest_path)
    result = AuditResult(
        manifest=str(manifest_path),
        root=root,
        project=str(payload.get("project", "")),
        built_at=str(payload.get("built_at", "")),
    )

    named: set[Path] = set()

    for entry in payload.get("outputs", []):
        if not isinstance(entry, dict):
            continue
        verdict, path = _verdict(entry, root)
        result.files.append(verdict)
        if path is not None:
            named.add(path)

    result.unexpected = _unexpected(root, named, manifest_path, extensions)
    return result


def _verdict(entry: dict, root: Path) -> tuple[FileVerdict, Path | None]:
    relative = str(entry.get("path", ""))
    if not relative:
        return (FileVerdict(path="(unnamed)", state="missing"), None)

    path = root / relative

    if not path.exists():
        return (FileVerdict(path=relative, state="missing"), path)

    size = path.stat().st_size
    expected_size = entry.get("bytes")
    if isinstance(expected_size, int) and expected_size and size != expected_size:
        # Checked before the hash because the size is free and it is the one
        # that tells you the file was truncated rather than edited.
        return (
            FileVerdict(path=relative, state="resized",
                        expected=str(expected_size), found=str(size)),
            path,
        )

    expected_hash = str(entry.get("sha256", ""))
    if expected_hash:
        found = file_hash(path)
        if found != expected_hash:
            return (
                FileVerdict(path=relative, state="changed",
                            expected=expected_hash, found=found),
                path,
            )

    return (FileVerdict(path=relative, state="ok"), path)


def _unexpected(root: Path, named: set[Path], manifest_path: Path,
                extensions: tuple[str, ...]) -> list[str]:
    """Files the manifest does not mention, in the directories it writes to.

    Only those directories, not the whole project. Scanning from the project
    root would report the sources, the catalog and the config file, none of
    which a build produced, and a check that reports forty files nobody asked
    about is a check nobody reads.

    The manifest itself is never unexpected, which is worth saying because it
    usually sits in the directory it describes.
    """
    found: list[str] = []
    seen: set[Path] = set()

    for directory in sorted({path.parent for path in named}):
        if not directory.is_dir():
            continue

        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path in named or path in seen:
                continue
            if path.resolve() == manifest_path.resolve():
                continue
            if extensions and path.suffix.lower() not in extensions:
                continue

            seen.add(path)
            found.append(_relative_to(path, root))

    return sorted(found)


def _relative_to(path: Path, root: Path) -> str:
    """A path for a report: relative where it can be, absolute where it cannot."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
