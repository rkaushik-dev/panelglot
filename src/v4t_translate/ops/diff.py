"""What changed between two catalogs.

The question this answers is "what does the translator have to look at this
round", and the honest answer is not "the strings that are new". It is the
strings that are new, plus the ones whose English moved, plus the ones whose
control got smaller, plus the ones that stopped being protected. All four
cost the same amount of somebody's attention and only the first is obvious.

The control getting smaller is the one that surprises people. Nobody edited a
string; a developer dragged a button and the German that fitted last release
does not fit this one. It shows up here and nowhere else until the check runs.

Takes two catalog files rather than reading git, because the interesting
comparison is usually against the copy that was sent to the translator, and
that lives in the delivery folder rather than in a commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.ids import sort_key
from ..catalog.model import Message
from ..catalog.store import Catalog, load_catalog, load_translations
from ..catalog.translations import TranslationSet
from ..config import ProjectConfig
from ..errors import CatalogError
from .stats import count_words

__all__ = [
    "MessageChange",
    "CatalogDiff",
    "diff_catalogs",
    "diff_against",
    "diff_to_json",
]


@dataclass(frozen=True)
class MessageChange:
    """One message that survived but is not the same."""

    key: str
    text: str
    reasons: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.text!r}: {', '.join(self.reasons)}"


@dataclass
class CatalogDiff:
    """Everything that moved between two catalogs."""

    added: list[Message] = field(default_factory=list)
    removed: list[Message] = field(default_factory=list)
    changed: list[MessageChange] = field(default_factory=list)
    unchanged: int = 0

    @property
    def needs_attention(self) -> int:
        return len(self.added) + len(self.changed)

    @property
    def added_words(self) -> int:
        return sum(count_words(m.source_text) for m in self.added)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def summary(self) -> str:
        return (
            f"{len(self.added)} new ({self.added_words} words), "
            f"{len(self.changed)} changed, {len(self.removed)} gone, "
            f"{self.unchanged} untouched"
        )


def diff_catalogs(before: Catalog, after: Catalog) -> CatalogDiff:
    """Compare two catalogs."""
    diff = CatalogDiff()

    for key in sorted(set(after.messages) - set(before.messages), key=sort_key):
        diff.added.append(after.messages[key])

    for key in sorted(set(before.messages) - set(after.messages), key=sort_key):
        diff.removed.append(before.messages[key])

    for key in sorted(set(before.messages) & set(after.messages), key=sort_key):
        reasons = _reasons(before.messages[key], after.messages[key])
        if reasons:
            diff.changed.append(
                MessageChange(key=key, text=after.messages[key].source_text,
                              reasons=tuple(reasons))
            )
        else:
            diff.unchanged += 1

    return diff


def _reasons(before: Message, after: Message) -> list[str]:
    """Why a surviving message is worth another look."""
    reasons: list[str] = []

    if before.max_width_px != after.max_width_px:
        reasons.append(
            f"space changed from {_px(before.max_width_px)} to "
            f"{_px(after.max_width_px)}"
        )

    if before.max_chars != after.max_chars:
        reasons.append(
            f"character budget changed from {before.max_chars} to {after.max_chars}"
        )

    if before.max_lines != after.max_lines:
        reasons.append(f"lines changed from {before.max_lines} to {after.max_lines}")

    if before.protected != after.protected:
        reasons.append(
            "is now protected" if after.protected else "is no longer protected"
        )

    if before.context != after.context:
        reasons.append(f"context changed to {after.context!r}")

    if before.developer_note != after.developer_note:
        reasons.append("the note changed")

    if before.sources != after.sources:
        reasons.append(f"moved to {', '.join(after.sources)}")

    return reasons


def _px(value: int | None) -> str:
    return "unbounded" if value is None else f"{value}px"


def diff_against(config: ProjectConfig, previous: Path | str) -> CatalogDiff:
    """Compare the project's catalog against a saved copy."""
    current = config.catalog_path()
    if not current.exists():
        raise CatalogError(f"{current} does not exist. Run extract first.")
    return diff_catalogs(load_catalog(previous), load_catalog(current))


def diff_to_json(diff: CatalogDiff, *, indent: int = 2) -> str:
    """The diff for something that has to decide rather than read.

    The review bot wants the key list and the counts. It is the same shape as
    the console report and not a reduction of it: a format that drops a field
    is a format somebody works around by parsing the console output, and then
    the console output cannot change.
    """
    import json

    payload = {
        "added": [_message_json(m) for m in diff.added],
        "changed": [
            {"key": c.key, "text": c.text, "reasons": list(c.reasons)}
            for c in diff.changed
        ],
        "removed": [_message_json(m) for m in diff.removed],
        "unchanged": diff.unchanged,
        "needsAttention": diff.needs_attention,
        "addedWords": diff.added_words,
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"


def _message_json(message: Message) -> dict[str, object]:
    return {
        "key": message.key,
        "text": message.source_text,
        "words": count_words(message.source_text),
    }


def outstanding_after(config: ProjectConfig, diff: CatalogDiff,
                      locale: str) -> list[str]:
    """Which of the changed and added keys are still unanswered in ``locale``.

    A message can be new to the catalog and already translated, because the
    memory filled it in. Reporting that as work is how a round gets quoted at
    twice its size.
    """
    entry = config.locale_entry(locale)
    translations: TranslationSet = load_translations(
        config.translations_path(entry.tag)
    )

    keys = [m.key for m in diff.added] + [c.key for c in diff.changed]
    return [key for key in keys if not translations.get(key).state.is_shippable]
