"""Every version number this build carries, in one place.

There are six now and they move independently. The package version is what
people quote. The catalog format decides whether a checkout from another
branch is readable, and the translation files have their own because their
shape has not changed with it. The cache format decides whether an extraction
can be skipped. The pack format decides whether a bootloader will load what
this built. The manifest format decides whether an archive from last year can
still be audited.

They are collected here because the question that gets asked is never "what
version is it", it is "why does this machine behave differently from that
one", and the answer is usually one of the other five.

The build also says whether its timestamps are pinned, which is not a version
and belongs here anyway: two machines producing different bytes from the same
input is exactly the question this block exists to answer, and that is the
first thing to check.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import __version__
from .catalog.cache import CACHE_VERSION
from .catalog.store import FORMAT_VERSION as CATALOG_FORMAT
from .catalog.store import TRANSLATIONS_VERSION
from .emit.manifest import MANIFEST_VERSION
from .emit.registry import available_kinds as emit_kinds
from .emit.v4l import FORMAT_VERSION as PACK_FORMAT
from .layout.panels import panel_names
from .locales import known_tags
from .reproducible import is_pinned
from .rules.registry import known_rule_names
from .sources.registry import available_kinds as source_kinds

__all__ = ["Versions", "versions", "describe"]


@dataclass(frozen=True)
class Versions:
    """What this build is and what it understands."""

    package: str
    catalog_format: int
    translations_format: int
    cache_format: int
    pack_format: int
    manifest_format: int

    sources: tuple[str, ...]
    outputs: tuple[str, ...]
    rules: tuple[str, ...]
    panels: tuple[str, ...]
    locales: tuple[str, ...]

    reproducible: bool = False
    """Whether this run's timestamps come from SOURCE_DATE_EPOCH."""

    def as_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "catalog_format": self.catalog_format,
            "translations_format": self.translations_format,
            "cache_format": self.cache_format,
            "pack_format": self.pack_format,
            "manifest_format": self.manifest_format,
            "sources": list(self.sources),
            "outputs": list(self.outputs),
            "rules": list(self.rules),
            "panels": list(self.panels),
            "locales": list(self.locales),
            "reproducible": self.reproducible,
        }


def versions() -> Versions:
    """Everything worth reporting about this build."""
    return Versions(
        package=__version__,
        catalog_format=CATALOG_FORMAT,
        translations_format=TRANSLATIONS_VERSION,
        cache_format=CACHE_VERSION,
        pack_format=PACK_FORMAT,
        manifest_format=MANIFEST_VERSION,
        sources=tuple(source_kinds()),
        outputs=tuple(emit_kinds()),
        rules=tuple(known_rule_names()),
        panels=tuple(panel_names()),
        locales=tuple(known_tags()),
        reproducible=is_pinned(),
    )


def describe(detailed: bool = False) -> str:
    """One line, or a block when somebody is trying to work out a difference."""
    found = versions()

    if not detailed:
        return f"v4t-translate {found.package}"

    lines = [
        f"v4t-translate {found.package}",
        f"  catalog format      {found.catalog_format}",
        f"  translation format  {found.translations_format}",
        f"  cache format        {found.cache_format}",
        f"  pack format         {found.pack_format}",
        f"  manifest format     {found.manifest_format}",
        f"  reads               {', '.join(found.sources)}",
        f"  writes              {', '.join(found.outputs)}",
        f"  rules               {len(found.rules)}",
        f"  panels              {', '.join(found.panels)}",
        f"  languages           {len(found.locales)}",
        f"  timestamps          "
        f"{'pinned' if found.reproducible else 'from the clock'}",
    ]
    return "\n".join(lines)
