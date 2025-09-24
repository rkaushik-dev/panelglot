"""Taking a product that was already translated and putting it under the tool.

This is how a real project starts, and it is the part nobody writes down. The
V4T family has shipped in eleven languages for years. There is no catalog and
there never was: there is one resource script per language, each a copy of the
English one with the strings replaced, diverging quietly since 2016.

Throwing that away and starting from an empty catalog would mean paying for
eleven languages of translation that already exist. So this reads the copies
and lifts the answers back out.

The alignment is the whole problem, and there are two ways to do it.

By text is the obvious one and it is wrong. The German file's English is gone,
so there is nothing to match on, and matching a German string to an English
one by similarity gets Feder next to Pen and calls it a hit.

By position is the right one. A localised .rc is a copy of the English with
the strings replaced, so the control at ordinal 4 of IDD_BARCODE_PROPS is the
same control in both files. That holds until somebody edits one copy and not
the other, which is exactly the thing this reports rather than papers over.

Nothing lands as approved. Every string that comes out of here was written
against an English that may have moved since, by somebody who is no longer
here, and the fingerprint is taken against today's English, so marking it
approved would tell the check that all of it is current when none of it is
known to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.store import Catalog, load_catalog, load_translations, save_translations
from ..catalog.translations import TranslationState
from ..config import ProjectConfig
from ..errors import CatalogError, SourceError
from ..sources.base import SourceOptions
from ..sources.registry import get_source

__all__ = ["AdoptResult", "adopt_locale", "adopt_translations", "alignment_key"]

#: What a message is identified by when two copies of the same file are being
#: lined up. The source path is left out on purpose: the whole point is that
#: the two files have different names.
AlignmentKey = tuple[str, str, str, int]


def alignment_key(origin) -> AlignmentKey:
    """Where a string sits, independent of which copy of the file it is in."""
    return (str(origin.kind), origin.container, origin.symbol, origin.ordinal)


@dataclass
class AdoptResult:
    """What one language's existing resource script gave up."""

    locale: str
    path: str

    adopted: list[str] = field(default_factory=list)
    """Keys that got a translation out of the localised file."""

    unchanged: list[str] = field(default_factory=list)
    """Positions whose text is identical to the English. Left alone."""

    already_answered: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    """Positions in the localised file with nothing at the same place in the
    English one. The two copies have diverged and somebody has to look."""

    missing: list[str] = field(default_factory=list)
    """Positions in the English with nothing at the same place in the copy."""

    warnings: list[str] = field(default_factory=list)
    written: Path | None = None

    @property
    def divergence(self) -> int:
        return len(self.orphans) + len(self.missing)

    def summary(self) -> str:
        return (
            f"{self.locale}: {len(self.adopted)} adopted, "
            f"{len(self.unchanged)} identical to the English, "
            f"{len(self.already_answered)} already answered, "
            f"{self.divergence} positions that do not line up"
        )


def adopt_locale(config: ProjectConfig, tag: str, localised: Path | str, *,
                 kind: str = "rc", encoding: str | None = None,
                 overwrite: bool = False, dry_run: bool = False) -> AdoptResult:
    """Lift one language's answers out of a translated copy of a source file.

    ``overwrite`` decides what happens to a message that already has a
    translation. Off by default, because the usual case is a second run over
    the same file and the catalog is now the better copy: somebody has been
    through it since.
    """
    entry = config.locale_entry(tag)
    catalog = _load_catalog(config)
    translations = load_translations(config.translations_path(entry.tag))

    result = AdoptResult(locale=entry.tag, path=str(localised))

    english = _positions(catalog)
    foreign = _read_positions(localised, kind=kind, encoding=encoding)

    for position, text in foreign.items():
        key = english.get(position)

        if key is None:
            result.orphans.append(_describe(position))
            continue

        message = catalog.messages[key]

        if text == message.source_text:
            # Either it was never translated or it genuinely does not change.
            # Both are cases for the untranslated analysis, not for this.
            result.unchanged.append(key)
            continue

        existing = translations.get(key)
        if existing.text and not overwrite:
            result.already_answered.append(key)
            continue

        translations.set(
            key,
            existing.with_text(
                text,
                source_text=message.source_text,
                state=TranslationState.NEEDS_REVIEW,
                origin=Path(localised).name,
            ),
        )
        result.adopted.append(key)

    result.missing = sorted(
        _describe(position) for position in english if position not in foreign
    )

    if result.divergence:
        result.warnings.append(
            f"{result.divergence} positions do not line up between the English "
            f"and {Path(localised).name}. The two copies have been edited apart, "
            f"and those strings need a person."
        )

    if not dry_run:
        destination = config.translations_path(entry.tag)
        save_translations(destination, translations)
        result.written = destination

    return result


def _positions(catalog: Catalog) -> dict[AlignmentKey, str]:
    """Every position in the English, mapped to the message that holds it.

    A message with several origins occupies several positions, which is right:
    OK appears on six dialogs and the localised file has six copies of it.
    """
    found: dict[AlignmentKey, str] = {}
    for key in catalog.sorted_keys():
        for origin in catalog.messages[key].origins:
            found.setdefault(alignment_key(origin), key)
    return found


def _read_positions(path: Path | str, *, kind: str,
                    encoding: str | None) -> dict[AlignmentKey, str]:
    """Every string in a localised file, by where it sits."""
    path = Path(path)
    if not path.exists():
        raise SourceError(f"{path} does not exist")

    reader = get_source(kind)
    options = SourceOptions(path=path)
    if encoding:
        options.encoding = encoding

    extraction = reader.extract(options)

    found: dict[AlignmentKey, str] = {}
    for message in extraction.messages:
        for origin in message.origins:
            found.setdefault(alignment_key(origin), message.source_text)
    return found


def _describe(position: AlignmentKey) -> str:
    kind, container, symbol, ordinal = position
    where = f"{container}/{symbol}" if symbol and symbol != container else container
    return f"{kind} {where}#{ordinal}"


def _load_catalog(config: ProjectConfig) -> Catalog:
    path = config.catalog_path()
    if not path.exists():
        raise CatalogError(
            f"{path} does not exist. Extract the English first: adopting is "
            f"lining a translated copy up against a catalog, and there is no "
            f"catalog yet."
        )
    return load_catalog(path)


def adopt_translations(config: ProjectConfig,
                       pairs: list[tuple[str, Path]], *,
                       kind: str = "rc", overwrite: bool = False,
                       dry_run: bool = False) -> list[AdoptResult]:
    """Adopt several languages in one go."""
    return [
        adopt_locale(config, tag, path, kind=kind, overwrite=overwrite,
                     dry_run=dry_run)
        for tag, path in pairs
    ]
