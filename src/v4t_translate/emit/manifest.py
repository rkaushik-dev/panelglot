"""What a build produced, written down.

The question this answers is asked about once a month and is always the same
shape: this panel is showing something odd, which build is on it, and was
that language finished when it went out.

Without a manifest the answer is somebody's memory of a release. With one it
is a file that says which catalog the outputs came from, what fraction of
each language was approved at the time, and the hash of every file, so a
panel's SD card can be compared against it byte for byte.

The catalog hash is the useful field. Two builds from the same catalog
produce the same outputs; two builds that differ are two different catalogs,
and that narrows an investigation from a release to a commit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import ProjectConfig
from ..ops.build import BuildResult
from ..reproducible import build_datetime

__all__ = ["MANIFEST_VERSION", "MANIFEST_NAME", "Manifest", "build_manifest"]

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"

_CHUNK = 64 * 1024


@dataclass
class Manifest:
    """One build, described."""

    project: str
    version: str
    built_at: str
    catalog_hash: str
    outputs: list[dict[str, object]] = field(default_factory=list)
    locales: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "manifest": MANIFEST_VERSION,
            "project": self.project,
            "tool_version": self.version,
            "built_at": self.built_at,
            "catalog": self.catalog_hash,
            "locales": {tag: round(value, 4) for tag, value in self.locales.items()},
            "outputs": self.outputs,
        }

    def write(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def summary(self) -> str:
        return (
            f"{self.project} {self.version}, catalog {self.catalog_hash[:12]}, "
            f"{len(self.outputs)} files"
        )


def file_hash(path: Path) -> str:
    """SHA-256 of a file, truncated. Enough to tell two builds apart."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()[:32]


def build_manifest(config: ProjectConfig, result: BuildResult, *,
                   tool_version: str, now: datetime | None = None) -> Manifest:
    """Describe a finished build.

    Reads the files back off disk rather than hashing what was in memory. The
    manifest is for comparing against what is on an SD card, so it has to
    describe what actually landed, including anything a filesystem did to it.
    """
    stamp = (now or build_datetime()).replace(microsecond=0)

    manifest = Manifest(
        project=config.name,
        version=tool_version,
        built_at=stamp.isoformat(),
        catalog_hash=file_hash(config.catalog_path()),
    )

    for tag, kind, emitted in result.outputs:
        relative = _relative(emitted.path, config.root)
        entry: dict[str, object] = {
            "locale": tag,
            "kind": kind,
            "path": relative,
            "translated": emitted.written,
            "fell_back": len(emitted.fell_back),
            "coverage": round(emitted.coverage, 4),
        }

        if emitted.path.exists():
            entry["bytes"] = emitted.path.stat().st_size
            entry["sha256"] = file_hash(emitted.path)
        else:
            entry["bytes"] = 0
            entry["sha256"] = ""

        manifest.outputs.append(entry)

    for check in result.outputs:
        tag = check[0]
        if tag not in manifest.locales:
            manifest.locales[tag] = check[2].coverage

    return manifest


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
