"""Folding a fresh extraction into the catalog that already exists.

Extraction on its own would be enough if the English never changed. It does,
constantly, and mostly in ways that are not really changes: a full stop is
added, "Print Spacing" becomes "Print spacing", a label picks up a colon.
Because keys are derived from the text, every one of those retires a key and
creates a new one, and the translation attached to the old key would be lost.

So a merge does three things. It adds what is new, it retires what is gone,
and in between it looks for pairs where something gone and something new are
obviously the same string reworded. Those get their translation carried over,
marked for review rather than trusted, because "obviously the same string" is
a guess and a guess is not a translation.

The threshold is deliberately high. A wrong carry-over is worse than no
carry-over: an empty cell gets translated, and a plausible-looking wrong one
gets approved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .ids import normalize_source
from .model import Message
from .store import Catalog
from .translations import Translation, TranslationSet, TranslationState

__all__ = ["MergeReport", "REWORD_THRESHOLD", "merge_catalog", "carry_translations"]

#: Similarity two texts need before one is treated as a rewording of the
#: other. Measured against a year of V4T.rc history: 0.86 carried every real
#: rewording and nothing else, 0.80 started pairing "Print Offset" with
#: "Purge Offset".
REWORD_THRESHOLD = 0.86

#: Below this many characters, similarity ratios stop meaning anything. "Pen"
#: and "Pens" score 0.86 and are not the same string.
MIN_REWORD_LENGTH = 8


@dataclass
class MergeReport:
    """What a merge did, in enough detail to print and to test."""

    added: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    rewordings: list[tuple[str, str]] = field(default_factory=list)
    """``(old key, new key)`` pairs judged to be the same string reworded."""

    updated: list[str] = field(default_factory=list)
    """Keys that survived but whose constraints or origins moved."""

    @property
    def carried_keys(self) -> set[str]:
        return {old for old, _ in self.rewordings}

    def summary(self) -> str:
        parts = [
            f"{len(self.added)} new",
            f"{len(self.removed)} retired",
            f"{len(self.rewordings)} reworded",
            f"{len(self.updated)} updated",
            f"{len(self.unchanged)} unchanged",
        ]
        return ", ".join(parts)

    def is_noop(self) -> bool:
        return not (self.added or self.removed or self.rewordings or self.updated)


def merge_catalog(existing: Catalog, extracted: dict[str, Message]) -> tuple[Catalog, MergeReport]:
    """Build the catalog the extraction implies, and say what changed.

    The result contains exactly the extracted messages. Nothing survives from
    ``existing`` that the source no longer produces, because a catalog that
    accumulates dead strings stops being usable as a work list.
    """
    report = MergeReport()
    merged = Catalog(project=existing.project, source_locale=existing.source_locale)

    for key in sorted(extracted):
        message = extracted[key]
        previous = existing.get(key)
        merged.messages[key] = message

        if previous is None:
            report.added.append(key)
        elif _has_moved(previous, message):
            report.updated.append(key)
        else:
            report.unchanged.append(key)

    report.removed = sorted(set(existing.messages) - set(extracted))
    report.rewordings = _find_rewordings(
        [existing.messages[key] for key in report.removed],
        [extracted[key] for key in report.added],
    )

    return merged, report


def carry_translations(
    translations: TranslationSet,
    report: MergeReport,
    *,
    catalog: Catalog,
) -> TranslationSet:
    """Move translations of reworded messages onto their new keys.

    Carried entries land in :attr:`~.TranslationState.NEEDS_REVIEW` and keep
    the fingerprint of the English they were made against, so the staleness
    check keeps flagging them until somebody looks. Approved entries whose
    source moved underneath them get the same treatment.

    Entries for keys that are simply gone are dropped. They are recoverable
    from git, and keeping them turns the file into an attic.
    """
    for old_key, new_key in report.rewordings:
        previous = translations.entries.get(old_key)
        if previous is None or not previous.text:
            continue
        if new_key in translations.entries and translations.entries[new_key].text:
            continue
        translations.set(
            new_key,
            Translation(
                text=previous.text,
                state=TranslationState.NEEDS_REVIEW,
                fingerprint=previous.fingerprint,
                note=previous.note,
                updated=previous.updated,
                origin=previous.origin or "carried",
            ),
        )

    for key, message in catalog.messages.items():
        entry = translations.entries.get(key)
        if entry is None:
            continue
        if entry.state is TranslationState.APPROVED and entry.is_stale_against(
            message.source_text
        ):
            translations.set(key, entry.marked(TranslationState.NEEDS_REVIEW))

    translations.restrict_to(set(catalog.messages))
    return translations


def _has_moved(previous: Message, current: Message) -> bool:
    """True when a surviving message changed in a way worth reporting."""
    return (
        previous.max_width_px != current.max_width_px
        or previous.max_chars != current.max_chars
        or previous.max_lines != current.max_lines
        or previous.protected != current.protected
        or previous.origins != current.origins
    )


def _find_rewordings(removed: list[Message], added: list[Message]) -> list[tuple[str, str]]:
    """Pair retired messages with new ones that are the same string reworded.

    Greedy best-first over the whole cross product, so a retired string is
    only ever claimed by its single closest new string, and a new string is
    only ever claimed once. Doing it greedily rather than optimally is fine
    here: the pairs that matter score far above the threshold and the ones
    that do not are rejected outright.
    """
    candidates: list[tuple[float, str, str]] = []

    for old in removed:
        old_text = normalize_source(old.source_text)
        if len(old_text) < MIN_REWORD_LENGTH:
            continue
        for new in added:
            new_text = normalize_source(new.source_text)
            if len(new_text) < MIN_REWORD_LENGTH:
                continue
            if not _length_plausible(old_text, new_text):
                continue
            ratio = SequenceMatcher(None, old_text, new_text).ratio()
            if ratio >= REWORD_THRESHOLD:
                candidates.append((ratio, old.key, new.key))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    claimed_old: set[str] = set()
    claimed_new: set[str] = set()
    pairs: list[tuple[str, str]] = []

    for _, old_key, new_key in candidates:
        if old_key in claimed_old or new_key in claimed_new:
            continue
        claimed_old.add(old_key)
        claimed_new.add(new_key)
        pairs.append((old_key, new_key))

    pairs.sort()
    return pairs


def _length_plausible(left: str, right: str) -> bool:
    """Cheap reject before paying for a similarity ratio."""
    longer, shorter = max(len(left), len(right)), min(len(left), len(right))
    return shorter / longer >= REWORD_THRESHOLD
