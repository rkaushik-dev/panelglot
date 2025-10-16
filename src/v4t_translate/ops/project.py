"""The three things every operation starts by doing.

Load the catalog and refuse politely if there is not one. Work out which
languages were asked for. Find the fonts. Eight modules had their own copy of
the first, two had the second, and the copies had drifted: seven of them said
"Run extract first" and one said "Run extract before build", which is the same
sentence with a worse ending.

That drift is the argument for this module. None of the copies was wrong and
none of them was worth reading twice, and the day somebody improves one of
those messages they will improve one of eight.

The remedy line is the part worth keeping consistent. An operation that
refuses because a file is missing has one job beyond refusing, which is to say
what to run instead.
"""

from __future__ import annotations

from pathlib import Path

from ..catalog.store import Catalog, load_catalog
from ..config import LocaleEntry, ProjectConfig
from ..errors import CatalogError

__all__ = ["require_catalog", "selected_locales", "font_search_path"]


def require_catalog(config: ProjectConfig, *, because: str = "") -> Catalog:
    """The project's catalog, or a refusal that says what to run.

    ``because`` adds a sentence for the operations where the reason is not
    obvious. Adopting against a catalog that does not exist is the one that
    needs it: the file that is missing is not the file the person was
    thinking about.
    """
    path = config.catalog_path()
    if path.exists():
        return load_catalog(path)

    remedy = "Run extract first."
    if because:
        remedy = f"{remedy} {because}"
    raise CatalogError(f"{path} does not exist", remedy=remedy)


def selected_locales(config: ProjectConfig,
                     locales: list[str] | None) -> list[LocaleEntry]:
    """The languages an operation was asked for, or all of them.

    Named languages are resolved through the config rather than filtered from
    it, so asking for one that is not configured is an error with a list of
    the ones that are, and not a silent empty run.
    """
    if not locales:
        return list(config.locales)
    return [config.locale_entry(tag) for tag in locales]


def font_search_path(config: ProjectConfig) -> list[Path]:
    """Where to look for panel font metrics, in order.

    A fonts directory beside the project file, then the project directory
    itself. The second is for the projects that predate the convention and
    have three .fmx files loose in the root.
    """
    return [config.root / "fonts", config.root]
