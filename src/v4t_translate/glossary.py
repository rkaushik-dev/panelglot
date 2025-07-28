"""The agreed term list.

Every distributor who resells these printers has opinions about what a pen is
called, and every one of them is right for their market. What is not
acceptable is the same part being called three things in one panel, which is
what happens when four people translate four dialogs over two years.

So the terms that matter are written down per language and enforced. The file
is a CSV because the people who own it are not developers and a spreadsheet is
what they have.

A row says one of three things.

It gives the agreed translation, which is the ordinary case. It says ``=``,
meaning leave the term exactly as it is, which is what brand names and part
numbers need. Or it lists renderings that are wrong, in the forbidden column,
which is the only way to write down a decision that was made by rejecting
something. Somebody spent an afternoon settling that a pen is a Stift and not
a Feder, and without the second half of that written down the next translator
reaches for Feder again.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

__all__ = ["Term", "Glossary", "load_glossary", "REQUIRED_COLUMNS", "KEEP_SOURCE"]

REQUIRED_COLUMNS = ("term", "locale", "translation")

KEEP_SOURCE = "="
"""What a translation column says when the term is not to be translated."""

FORBIDDEN_SEPARATOR = ";"


@dataclass(frozen=True)
class Term:
    """One agreed translation of one source term."""

    term: str
    locale: str
    translation: str
    note: str = ""

    forbidden: tuple[str, ...] = field(default_factory=tuple)
    """Renderings that are wrong for this term, lowered.

    These are decisions that were made by rejecting something, and there is
    nowhere else to write one down. The required translation says what to
    reach for; this says what somebody already reached for and was told not
    to use.
    """

    @property
    def key(self) -> str:
        """Lowered source term, which is how lookups are keyed."""
        return self.term.lower()

    @property
    def keep_source(self) -> bool:
        """Whether this term is to be left exactly as the English has it."""
        return self.translation == KEEP_SOURCE

    @property
    def required(self) -> str:
        """The text that has to appear in the target, lowered."""
        return self.term.lower() if self.keep_source else self.translation.lower()

    def merged_with(self, other: Term) -> Term:
        """The same term from a second row, with the forbidden lists joined."""
        combined = list(self.forbidden)
        combined.extend(item for item in other.forbidden if item not in combined)
        return Term(
            term=self.term,
            locale=self.locale,
            translation=self.translation,
            note=self.note or other.note,
            forbidden=tuple(combined),
        )

    def describe(self) -> str:
        if self.keep_source:
            return f"{self.term} is not translated"
        return f"{self.term} is {self.translation}"


class Glossary:
    """Agreed terms, indexed by locale."""

    def __init__(self, terms: list[Term] | None = None) -> None:
        self._by_locale: dict[str, dict[str, Term]] = {}
        for term in terms or []:
            self.add(term)

    def add(self, term: Term) -> None:
        _validate(term)

        bucket = self._by_locale.setdefault(term.locale, {})
        existing = bucket.get(term.key)

        if existing is None:
            bucket[term.key] = term
            return

        if existing.translation != term.translation:
            raise ConfigError(
                f"glossary gives {term.term!r} two translations in {term.locale}: "
                f"{existing.translation!r} and {term.translation!r}"
            )

        # Same decision written twice, which happens when two people add the
        # forbidden renderings they each ran into. Join them rather than
        # picking one, because both were real.
        bucket[term.key] = existing.merged_with(term)

    def for_locale(self, locale: str) -> dict[str, Term]:
        """Terms agreed for ``locale``, keyed by lowered source term."""
        return dict(self._by_locale.get(locale, {}))

    def locales(self) -> list[str]:
        return sorted(self._by_locale)

    def __len__(self) -> int:
        return sum(len(bucket) for bucket in self._by_locale.values())

    def __bool__(self) -> bool:
        return bool(self._by_locale)

    @property
    def forbidden_count(self) -> int:
        return sum(
            len(term.forbidden)
            for bucket in self._by_locale.values()
            for term in bucket.values()
        )


def _validate(term: Term) -> None:
    """Reject a row that contradicts itself.

    A forbidden rendering that is also the required one means somebody edited
    the translation column and forgot the other. Left alone it produces a
    finding on every correct translation of that term, which is the kind of
    noise that gets a whole rule switched off.
    """
    if not term.forbidden:
        return

    required = term.required
    for banned in term.forbidden:
        if banned == required:
            raise ConfigError(
                f"glossary forbids {banned!r} for {term.term!r} in {term.locale}, "
                f"which is also what it requires"
            )
        if not banned:
            raise ConfigError(
                f"glossary has an empty forbidden rendering for {term.term!r} in "
                f"{term.locale}. An empty one matches everything"
            )


def _parse_forbidden(raw: str) -> tuple[str, ...]:
    """Split the forbidden column, lowered, in the order it was written."""
    items: list[str] = []
    for piece in raw.split(FORBIDDEN_SEPARATOR):
        cleaned = piece.strip().lower()
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return tuple(items)


def load_glossary(path: Path | str) -> Glossary:
    """Read a term CSV.

    Missing file is an empty glossary rather than an error: a project that has
    not agreed any terms yet is a normal state, and failing the whole run over
    it would just make people delete the config line.
    """
    path = Path(path)
    if not path.exists():
        return Glossary()

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ConfigError(
                f"{path}: glossary is missing the {', '.join(missing)} column(s). "
                f"Found: {', '.join(reader.fieldnames or ['nothing'])}"
            )

        glossary = Glossary()
        for number, row in enumerate(reader, start=2):
            term = (row.get("term") or "").strip()
            locale = (row.get("locale") or "").strip()
            translation = (row.get("translation") or "").strip()

            if not term and not locale and not translation:
                continue
            if not (term and locale and translation):
                raise ConfigError(
                    f"{path}:{number}: term, locale and translation are all required"
                )

            try:
                glossary.add(
                    Term(
                        term=term,
                        locale=locale,
                        translation=translation,
                        note=(row.get("note") or "").strip(),
                        forbidden=_parse_forbidden(row.get("forbidden") or ""),
                    )
                )
            except ConfigError as exc:
                # The row number is the only thing that makes a glossary error
                # actionable. The file is edited in a spreadsheet by somebody
                # who is not going to search it by hand.
                raise ConfigError(f"{path}:{number}: {exc}") from exc

    return glossary
