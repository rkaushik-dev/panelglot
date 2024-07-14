"""What every source reader has to look like.

A source turns one file into messages. It is allowed to warn, it is allowed to
find nothing, and it is not allowed to decide anything about translation. The
split matters because the rc reader is by far the most complicated one and it
would happily grow to swallow the whole pipeline if nothing stopped it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..catalog.model import Message

__all__ = ["Extraction", "Source", "SourceOptions", "merge_extractions"]


@dataclass
class SourceOptions:
    """Everything a reader needs beyond the file itself."""

    path: Path
    """File to read, already resolved against the project root."""

    encoding: str = "utf-8-sig"
    """Text encoding. Resource scripts are often cp1252 and rarely say so."""

    root: Path | None = None
    """Project root, used to make origins relative and therefore portable."""

    symbols_path: Path | None = None
    """Companion ``resource.h``, for readers that have one."""

    protected_patterns: tuple[str, ...] = ()
    """Regexes whose matches are marked untranslatable at extraction time."""

    def relative(self, path: Path | None = None) -> str:
        """Path as it should appear in an origin: relative, forward slashes."""
        target = path or self.path
        if self.root is not None:
            try:
                target = target.relative_to(self.root)
            except ValueError:
                pass
        return target.as_posix()


@dataclass
class Extraction:
    """The result of reading one source file."""

    source: str
    """Relative path of the file that was read."""

    messages: list[Message] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)
    """Things worth telling a person about that did not stop the read."""

    stats: dict[str, int] = field(default_factory=dict)
    """Reader-specific counts, printed by ``extract --verbose``."""

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def __len__(self) -> int:
        return len(self.messages)

    def by_key(self) -> dict[str, Message]:
        """Messages keyed, with duplicates inside one file already merged.

        A file can produce the same key twice: "OK" appears on every dialog.
        Merging here rather than in the caller means every reader gets the
        same behaviour without having to remember to ask for it.
        """
        merged: dict[str, Message] = {}
        for message in self.messages:
            existing = merged.get(message.key)
            merged[message.key] = message if existing is None else existing.merged_with(message)
        return merged


@runtime_checkable
class Source(Protocol):
    """A reader for one dialect of string storage."""

    kind: str
    """Short name used in the project config, e.g. ``rc``."""

    def extract(self, options: SourceOptions) -> Extraction:
        """Read ``options.path`` and return what is in it."""
        ...


def merge_extractions(extractions: list[Extraction]) -> dict[str, Message]:
    """Fold several files into one keyed message set.

    Order is the order the files were listed in, so a message that appears in
    both ``V4T.rc`` and ``Config.rc`` keeps the first file as its primary
    origin and reports are stable between runs.
    """
    merged: dict[str, Message] = {}
    for extraction in extractions:
        for key, message in extraction.by_key().items():
            existing = merged.get(key)
            merged[key] = message if existing is None else existing.merged_with(message)
    return merged
