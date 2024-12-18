"""What an emitter looks like.

The shape mirrors the source protocol on purpose. A target that can be read
should be writable by something with the same signature, and two of them
already are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..locales import Locale

__all__ = ["EmitOptions", "EmitResult", "Emitter"]


@dataclass
class EmitOptions:
    """Everything an emitter needs beyond the catalog itself."""

    path: Path
    """Where to write. Parent directories are the emitter's job to create."""

    locale: Locale

    source_path: Path | None = None
    """The file the messages came from, for emitters that rewrite it in place."""

    encoding: str | None = None
    """Override the encoding. ``None`` means the locale's own codepage."""

    fallback_to_source: bool = True
    """Write the English where a translation is missing.

    Off means the string is left out, which on most targets means the panel
    shows an empty label. On is nearly always right: an English label is
    usable and a blank one is not.
    """


@dataclass
class EmitResult:
    """What one emitter run produced."""

    path: Path
    written: int = 0
    """Messages that got a translation."""

    fell_back: list[str] = field(default_factory=list)
    """Keys that shipped their English because there was no translation."""

    skipped: list[str] = field(default_factory=list)
    """Keys left out entirely."""

    warnings: list[str] = field(default_factory=list)
    bytes_written: int = 0

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def coverage(self) -> float:
        total = self.written + len(self.fell_back) + len(self.skipped)
        return self.written / total if total else 0.0

    def summary(self) -> str:
        return (
            f"{self.path.name}: {self.written} translated, "
            f"{len(self.fell_back)} fell back to English, "
            f"{len(self.skipped)} left out ({self.coverage:.0%} covered)"
        )


@runtime_checkable
class Emitter(Protocol):
    """A writer for one output format."""

    kind: str

    def emit(self, catalog: Catalog, translations: TranslationSet,
             options: EmitOptions) -> EmitResult:
        ...
