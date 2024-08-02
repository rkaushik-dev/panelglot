"""Reading and writing the catalog files.

The catalog is checked into the same repository as the source it was
extracted from, so the file format is chosen for diffs, not for size. Keys
sort in a stable order, JSON is indented, unicode is written through rather
than escaped, and every file ends with a newline. A run that changes nothing
must produce a byte-identical file or the next person cannot see what a real
change looks like.

Writes go through a temporary file in the same directory and then a rename.
An interrupted run leaving a half-written catalog behind would be an expensive
thing to explain, and the rename is free.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import CatalogError
from .ids import sort_key
from .model import Message, Origin, OriginKind
from .translations import Translation, TranslationSet, TranslationState

__all__ = [
    "FORMAT_VERSION",
    "Catalog",
    "load_catalog",
    "save_catalog",
    "load_translations",
    "save_translations",
]

#: Bumped when a change would make an older reader wrong, not on every change.
FORMAT_VERSION = 1


@dataclass
class Catalog:
    """The source side: every message extracted from a project."""

    project: str
    source_locale: str = "en-US"
    messages: dict[str, Message] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.messages)

    def __contains__(self, key: object) -> bool:
        return key in self.messages

    def get(self, key: str) -> Message | None:
        return self.messages.get(key)

    def add(self, message: Message) -> None:
        """Add or merge a message, keeping the union of origins."""
        existing = self.messages.get(message.key)
        self.messages[message.key] = (
            message if existing is None else existing.merged_with(message)
        )

    def sorted_keys(self) -> list[str]:
        return sorted(self.messages, key=sort_key)

    def sorted_messages(self) -> list[Message]:
        return [self.messages[key] for key in self.sorted_keys()]

    def texts(self) -> dict[str, str]:
        """Key to source text, which is what most callers actually want."""
        return {key: message.source_text for key, message in self.messages.items()}


def save_catalog(path: Path | str, catalog: Catalog) -> None:
    """Write ``catalog`` to ``path``, creating parent directories."""
    payload = {
        "format": FORMAT_VERSION,
        "project": catalog.project,
        "source_locale": catalog.source_locale,
        "messages": [_message_to_json(m) for m in catalog.sorted_messages()],
    }
    _write_json(Path(path), payload)


def load_catalog(path: Path | str) -> Catalog:
    """Read a catalog written by :func:`save_catalog`."""
    payload = _read_json(Path(path))

    catalog = Catalog(
        project=str(payload.get("project", "")),
        source_locale=str(payload.get("source_locale", "en-US")),
    )

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise CatalogError(f"{path}: 'messages' is missing or is not a list")

    for index, raw in enumerate(raw_messages):
        message = _message_from_json(raw, path=str(path), index=index)
        if message.key in catalog.messages:
            raise CatalogError(f"{path}: duplicate message key {message.key!r}")
        catalog.messages[message.key] = message

    return catalog


def save_translations(path: Path | str, translations: TranslationSet) -> None:
    """Write one locale's answers."""
    payload = {
        "format": FORMAT_VERSION,
        "locale": translations.locale,
        "entries": {
            key: _translation_to_json(translations.entries[key])
            for key in sorted(translations.entries, key=sort_key)
        },
    }
    _write_json(Path(path), payload)


def load_translations(path: Path | str) -> TranslationSet:
    """Read one locale's answers. A missing file is an empty set, not an error."""
    path = Path(path)
    if not path.exists():
        return TranslationSet(locale=path.stem)

    payload = _read_json(path)
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise CatalogError(f"{path}: 'entries' is missing or is not an object")

    result = TranslationSet(locale=str(payload.get("locale", path.stem)))
    for key, raw in entries.items():
        result.entries[key] = _translation_from_json(raw, path=str(path), key=key)
    return result


# -- json shapes --------------------------------------------------------


def _message_to_json(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {
        "key": message.key,
        "text": message.source_text,
    }
    if message.context:
        data["context"] = message.context
    if message.developer_note:
        data["note"] = message.developer_note
    if message.protected:
        data["protected"] = True
    if message.max_chars is not None:
        data["max_chars"] = message.max_chars
    if message.max_width_px is not None:
        data["max_width_px"] = message.max_width_px
    if message.max_lines != 1:
        data["max_lines"] = message.max_lines
    data["origins"] = [_origin_to_json(o) for o in message.origins]
    return data


def _message_from_json(raw: Any, *, path: str, index: int) -> Message:
    if not isinstance(raw, dict):
        raise CatalogError(f"{path}: message {index} is not an object")

    key = raw.get("key")
    text = raw.get("text")
    if not isinstance(key, str) or not isinstance(text, str):
        raise CatalogError(f"{path}: message {index} needs a string 'key' and 'text'")

    return Message(
        key=key,
        source_text=text,
        context=raw.get("context"),
        developer_note=raw.get("note"),
        protected=bool(raw.get("protected", False)),
        max_chars=raw.get("max_chars"),
        max_width_px=raw.get("max_width_px"),
        max_lines=int(raw.get("max_lines", 1)),
        origins=[_origin_from_json(o, path=path, key=key) for o in raw.get("origins", [])],
    )


def _origin_to_json(origin: Origin) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source": origin.source,
        "kind": origin.kind.value,
        "container": origin.container,
        "symbol": origin.symbol,
    }
    if origin.line:
        data["line"] = origin.line
    if origin.ordinal:
        data["ordinal"] = origin.ordinal
    return data


def _origin_from_json(raw: Any, *, path: str, key: str) -> Origin:
    if not isinstance(raw, dict):
        raise CatalogError(f"{path}: origin of {key!r} is not an object")
    try:
        kind = OriginKind(raw.get("kind", ""))
    except ValueError as exc:
        raise CatalogError(f"{path}: {key!r} has unknown origin kind {raw.get('kind')!r}") from exc

    return Origin(
        source=str(raw.get("source", "")),
        kind=kind,
        container=str(raw.get("container", "")),
        symbol=str(raw.get("symbol", "")),
        line=int(raw.get("line", 0)),
        ordinal=int(raw.get("ordinal", 0)),
    )


def _translation_to_json(translation: Translation) -> dict[str, Any]:
    data: dict[str, Any] = {
        "text": translation.text,
        "state": translation.state.value,
    }
    if translation.fingerprint:
        data["fingerprint"] = translation.fingerprint
    if translation.note:
        data["note"] = translation.note
    if translation.updated:
        data["updated"] = translation.updated
    if translation.origin:
        data["origin"] = translation.origin
    return data


def _translation_from_json(raw: Any, *, path: str, key: str) -> Translation:
    if not isinstance(raw, dict):
        raise CatalogError(f"{path}: entry {key!r} is not an object")
    try:
        state = TranslationState(raw.get("state", "empty"))
    except ValueError as exc:
        raise CatalogError(f"{path}: {key!r} has unknown state {raw.get('state')!r}") from exc

    return Translation(
        text=str(raw.get("text", "")),
        state=state,
        fingerprint=str(raw.get("fingerprint", "")),
        note=raw.get("note"),
        updated=raw.get("updated"),
        origin=str(raw.get("origin", "")),
    )


# -- file plumbing ------------------------------------------------------


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CatalogError(f"{path} does not exist") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise CatalogError(f"{path} does not contain a JSON object")

    version = payload.get("format", 0)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise CatalogError(
            f"{path} is format {version}, and this build only reads up to {FORMAT_VERSION}"
        )

    return payload
