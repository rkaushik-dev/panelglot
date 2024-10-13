"""The agreed term list.

Every distributor who resells these printers has opinions about what a pen is
called, and every one of them is right for their market. What is not
acceptable is the same part being called three things in one panel, which is
what happens when four people translate four dialogs over two years.

So the terms that matter are written down per language and enforced. The file
is a CSV because the people who own it are not developers and a spreadsheet is
what they have.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

__all__ = ["Term", "Glossary", "load_glossary", "REQUIRED_COLUMNS"]

REQUIRED_COLUMNS = ("term", "locale", "translation")


@dataclass(frozen=True)
class Term:
    """One agreed translation of one source term."""

    term: str
    locale: str
    translation: str
    note: str = ""

    @property
    def key(self) -> str:
        """Lowered source term, which is how lookups are keyed."""
        return self.term.lower()


class Glossary:
    """Agreed terms, indexed by locale."""

    def __init__(self, terms: list[Term] | None = None) -> None:
        self._by_locale: dict[str, dict[str, Term]] = {}
        for term in terms or []:
            self.add(term)

    def add(self, term: Term) -> None:
        bucket = self._by_locale.setdefault(term.locale, {})
        existing = bucket.get(term.key)
        if existing is not None and existing.translation != term.translation:
            raise ConfigError(
                f"glossary gives {term.term!r} two translations in {term.locale}: "
                f"{existing.translation!r} and {term.translation!r}"
            )
        bucket[term.key] = term

    def for_locale(self, locale: str) -> dict[str, Term]:
        """Terms agreed for ``locale``, keyed by lowered source term."""
        return dict(self._by_locale.get(locale, {}))

    def locales(self) -> list[str]:
        return sorted(self._by_locale)

    def __len__(self) -> int:
        return sum(len(bucket) for bucket in self._by_locale.values())

    def __bool__(self) -> bool:
        return bool(self._by_locale)


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

            glossary.add(
                Term(
                    term=term,
                    locale=locale,
                    translation=translation,
                    note=(row.get("note") or "").strip(),
                )
            )

    return glossary
