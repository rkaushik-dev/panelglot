"""One language's answers, and how much we trust each of them.

A translation is not just text. It carries the state of the English it was
made against, which is what lets ``check`` tell three different situations
apart that all look like "there is a string here":

* the translator has not got to it yet;
* the translator answered, and the English has not moved since;
* the translator answered, and then somebody edited the English.

The third one is the dangerous case. It looks finished from the outside and it
is wrong. The source fingerprint stored beside every translation is the only
thing that catches it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .ids import source_fingerprint

__all__ = ["TranslationState", "Translation", "TranslationSet"]


class TranslationState(str, Enum):
    """How far along one translation is.

    Values are written into the catalog file, so they are part of the format.
    """

    EMPTY = "empty"
    """Nothing has been supplied."""

    DRAFT = "draft"
    """Machine output, or a fuzzy match carried over. Not shippable."""

    NEEDS_REVIEW = "needs-review"
    """A human wrote it but something changed underneath, or a rule flagged it."""

    APPROVED = "approved"
    """Signed off. This is the only state that ships without a warning."""

    DO_NOT_TRANSLATE = "do-not-translate"
    """The source ships unchanged in this language, on purpose."""

    def __str__(self) -> str:
        return self.value

    @property
    def is_shippable(self) -> bool:
        return self in (TranslationState.APPROVED, TranslationState.DO_NOT_TRANSLATE)

    @property
    def needs_a_human(self) -> bool:
        return self in (TranslationState.EMPTY, TranslationState.DRAFT,
                        TranslationState.NEEDS_REVIEW)


@dataclass
class Translation:
    """One language's answer for one message."""

    text: str = ""
    state: TranslationState = TranslationState.EMPTY

    fingerprint: str = ""
    """Fingerprint of the English this was made against."""

    note: str | None = None
    """Whatever the translator wrote back in the comment column."""

    updated: str | None = None
    """ISO date of the last change. Kept as a string so the file stays diffable."""

    origin: str = ""
    """Where the text came from: a workbook name, a provider, ``memory``."""

    def is_stale_against(self, source_text: str) -> bool:
        """True when the English has moved since this was written.

        An empty translation is never stale, because there is nothing to
        distrust. Neither is one with no fingerprint at all, which is what a
        hand-written catalog entry looks like.
        """
        if not self.text or not self.fingerprint:
            return False
        return self.fingerprint != source_fingerprint(source_text)

    def with_text(self, text: str, *, source_text: str, state: TranslationState,
                  origin: str = "", note: str | None = None,
                  today: date | None = None) -> Translation:
        """A copy carrying new text, re-fingerprinted against ``source_text``."""
        return Translation(
            text=text,
            state=state,
            fingerprint=source_fingerprint(source_text),
            note=note if note is not None else self.note,
            updated=(today or date.today()).isoformat(),
            origin=origin or self.origin,
        )

    def marked(self, state: TranslationState, *, today: date | None = None) -> Translation:
        """A copy in a different state, keeping everything else."""
        return Translation(
            text=self.text,
            state=state,
            fingerprint=self.fingerprint,
            note=self.note,
            updated=(today or date.today()).isoformat(),
            origin=self.origin,
        )


@dataclass
class TranslationSet:
    """Every translation for one locale, keyed the same way messages are."""

    locale: str
    entries: dict[str, Translation] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, key: object) -> bool:
        return key in self.entries

    def get(self, key: str) -> Translation:
        """The translation for ``key``, or an empty one. Never ``None``.

        Callers ask about keys that have no answer yet constantly, and making
        every one of them handle ``None`` produced exactly the bugs you would
        expect.
        """
        return self.entries.get(key, Translation())

    def set(self, key: str, translation: Translation) -> None:
        self.entries[key] = translation

    def remove(self, key: str) -> bool:
        return self.entries.pop(key, None) is not None

    def keys_in_state(self, *states: TranslationState) -> list[str]:
        wanted = set(states)
        return sorted(key for key, value in self.entries.items() if value.state in wanted)

    def counts(self) -> dict[str, int]:
        """How many entries sit in each state, including the states with none."""
        tally = {state.value: 0 for state in TranslationState}
        for translation in self.entries.values():
            tally[translation.state.value] += 1
        return tally

    def restrict_to(self, keys: Iterable[str]) -> list[str]:
        """Drop entries whose message no longer exists. Returns what went.

        Called after an extraction, so the catalog does not accumulate
        translations for dialogs that were deleted three releases ago.

        Takes any iterable rather than a set. Inside this class the name
        ``set`` is the method below, so a ``set[str]`` annotation resolves to
        that and means nothing.
        """
        gone = sorted(self.entries.keys() - frozenset(keys))
        for key in gone:
            del self.entries[key]
        return gone
