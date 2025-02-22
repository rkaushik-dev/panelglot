"""Sending workbooks out and taking them back in.

The import is where a delivery either lands or quietly does not, so the
report it produces is the whole point of the operation. Four things can
happen to a row and only one of them is success:

it matched a message and changed the translation;
it matched and said the same thing, so nothing happened;
it matched nothing, because the English moved after the sheet was sent;
or it matched several messages, because the sheet has no key column and the
same English exists twice with different contexts.

The last two are the ones that lose work, and they are silent unless
something counts them. A delivery of nine hundred rows where sixty matched
nothing looks exactly like a delivery where all nine hundred landed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..catalog.ids import normalize_source
from ..catalog.store import Catalog, load_catalog, load_translations, save_translations
from ..catalog.translations import TranslationSet, TranslationState
from ..config import ProjectConfig
from ..errors import CatalogError, WorkbookError
from ..locales import Locale
from ..workbook.reader import WorkbookRead, WorkbookRow, read_workbook
from ..workbook.writer import write_workbook

__all__ = ["ExportResult", "ImportResult", "export_workbooks", "import_workbook"]


@dataclass
class ExportResult:
    """Workbooks written."""

    written: list[tuple[str, Path, int]] = field(default_factory=list)
    """``(locale tag, path, row count)`` for each sheet."""

    def summary(self) -> str:
        if not self.written:
            return "nothing to export"
        return ", ".join(f"{tag} {rows} rows" for tag, _, rows in self.written)


@dataclass
class ImportResult:
    """What one workbook did to the catalog."""

    locale: str
    path: str
    applied: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    unmatched: list[WorkbookRow] = field(default_factory=list)
    ambiguous: list[tuple[WorkbookRow, list[str]]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    written: Path | None = None

    @property
    def rows(self) -> int:
        return (len(self.applied) + len(self.unchanged) + len(self.unmatched)
                + len(self.ambiguous))

    def summary(self) -> str:
        return (
            f"{self.rows} rows: {len(self.applied)} applied, "
            f"{len(self.unchanged)} unchanged, {len(self.unmatched)} unmatched, "
            f"{len(self.ambiguous)} ambiguous"
        )

    def is_clean(self) -> bool:
        return not (self.unmatched or self.ambiguous)


def export_workbooks(
    config: ProjectConfig,
    *,
    locales: list[str] | None = None,
    only_outstanding: bool = False,
) -> ExportResult:
    """Write one workbook per language."""
    catalog = _load_catalog(config)
    result = ExportResult()

    for tag in locales or config.target_tags():
        entry = config.locale_entry(tag)
        translations = load_translations(config.translations_path(entry.tag))
        path = config.workbook_path(entry.tag)
        rows = write_workbook(
            path, catalog, translations, entry.locale,
            only_outstanding=only_outstanding,
        )
        result.written.append((entry.tag, path, rows))

    return result


def import_workbook(
    config: ProjectConfig,
    path: Path | str,
    *,
    locale: str | None = None,
    sheet: str | None = None,
    dry_run: bool = False,
    approve: bool = True,
    today: date | None = None,
) -> ImportResult:
    """Read a delivered workbook and update one language.

    ``approve`` says what to do with a row whose status column is missing or
    unreadable, which is every row of a legacy sheet. Approving is the honest
    default: somebody was paid to produce that column and treating it as a
    draft means it never ships.
    """
    catalog = _load_catalog(config)
    read = read_workbook(path, sheet=sheet)
    target = _resolve_locale(config, read, locale)

    entry = config.locale_entry(target.tag)
    translations = load_translations(config.translations_path(entry.tag))

    result = ImportResult(locale=entry.tag, path=str(path), warnings=list(read.warnings))
    index = _source_index(catalog)

    for row in read.rows:
        keys = _match(row, catalog, index)

        if not keys:
            result.unmatched.append(row)
            continue
        if len(keys) > 1:
            result.ambiguous.append((row, keys))
            continue

        key = keys[0]
        _apply(result, translations, catalog, key, row, approve=approve, today=today)

    if not dry_run:
        destination = config.translations_path(entry.tag)
        save_translations(destination, translations)
        result.written = destination

    return result


def _apply(result: ImportResult, translations: TranslationSet, catalog: Catalog,
           key: str, row: WorkbookRow, *, approve: bool, today: date | None) -> None:
    existing = translations.get(key)
    state = _state_for(row, approve=approve, fallback=existing.state)

    if existing.text == row.target and existing.state is state:
        result.unchanged.append(key)
        return

    if not row.target:
        # An emptied cell is a real signal, but it is more often a sheet that
        # was sent for a subset and came back with the rest blank.
        if existing.text:
            result.warnings.append(
                f"row {row.row}: {key} was {existing.text!r} and the sheet is blank, "
                f"keeping the existing translation"
            )
            result.unchanged.append(key)
            return
        result.unchanged.append(key)
        return

    message = catalog.messages[key]
    translations.set(
        key,
        existing.with_text(
            row.target,
            source_text=message.source_text,
            state=state,
            origin=Path(result.path).name,
            note=row.note or None,
            today=today,
        ),
    )
    result.applied.append(key)


def _state_for(row: WorkbookRow, *, approve: bool,
               fallback: TranslationState) -> TranslationState:
    """Work out what state a delivered row is in.

    The status column is only believed when it does not contradict the cell
    next to it. A row that carries a translation and still says "empty" is the
    normal case, not an odd one: the sheet went out with every status set to
    empty, the translator filled in the translation column, and nobody touches
    a dropdown they were not asked about.
    """
    if not row.target:
        return TranslationState.EMPTY

    if row.status:
        try:
            declared = TranslationState(row.status.strip().lower())
        except ValueError:
            declared = None
        if declared is not None and declared is not TranslationState.EMPTY:
            return declared

    if approve:
        return TranslationState.APPROVED
    return TranslationState.DRAFT if fallback is TranslationState.EMPTY else fallback


def _source_index(catalog: Catalog) -> dict[str, list[str]]:
    """Normalised source text to the keys carrying it.

    Several keys can share one source text when contexts differ, and that is
    exactly the case a legacy sheet cannot resolve.
    """
    index: dict[str, list[str]] = {}
    for key, message in catalog.messages.items():
        index.setdefault(normalize_source(message.source_text), []).append(key)
    for keys in index.values():
        keys.sort()
    return index


def _match(row: WorkbookRow, catalog: Catalog, index: dict[str, list[str]]) -> list[str]:
    if row.key and row.key in catalog.messages:
        return [row.key]
    if row.key:
        # A key that no longer exists. Fall through to the text, which often
        # still matches because only the key derivation changed.
        pass
    return index.get(normalize_source(row.source), [])


def _resolve_locale(config: ProjectConfig, read: WorkbookRead,
                    requested: str | None) -> Locale:
    if requested is None:
        return read.locale

    wanted = config.locale_entry(requested).locale
    if wanted.tag != read.locale.tag:
        raise WorkbookError(
            f"{read.path} is headed {read.schema.target_heading!r}, which is "
            f"{read.locale.tag}, but {wanted.tag} was asked for"
        )
    return wanted


def _load_catalog(config: ProjectConfig) -> Catalog:
    path = config.catalog_path()
    if not path.exists():
        raise CatalogError(f"{path} does not exist. Run extract first.")
    return load_catalog(path)
