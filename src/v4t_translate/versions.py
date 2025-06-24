"""Every version number this build carries, in one place.

There are four and they move independently. The package version is what
people quote. The catalog format decides whether a checkout from another
branch is readable. The cache format decides whether an extraction can be
skipped. The pack format decides whether a bootloader will load what this
built.

They are collected here because the question that gets asked is never "what
version is it", it is "why does this machine behave differently from that
one", and the answer is usually one of the other three.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import __version__
from .catalog.cache import CACHE_VERSION
from .catalog.store import FORMAT_VERSION as CATALOG_FORMAT
from .emit.registry import available_kinds as emit_kinds
from .emit.v4l import FORMAT_VERSION as PACK_FORMAT
from .layout.panels import panel_names
from .locales import known_tags
from .rules.registry import known_rule_names
from .sources.registry import available_kinds as source_kinds

__all__ = ["Versions", "versions", "describe"]


@dataclass(frozen=True)
class Versions:
    """What this build is and what it understands."""

    package: str
    catalog_format: int
    cache_format: int
    pack_format: int

    sources: tuple[str, ...]
    outputs: tuple[str, ...]
    rules: tuple[str, ...]
    panels: tuple[str, ...]
    locales: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "catalog_format": self.catalog_format,
            "cache_format": self.cache_format,
            "pack_format": self.pack_format,
            "sources": list(self.sources),
            "outputs": list(self.outputs),
            "rules": list(self.rules),
            "panels": list(self.panels),
            "locales": list(self.locales),
        }


def versions() -> Versions:
    """Everything worth reporting about this build."""
    return Versions(
        package=__version__,
        catalog_format=CATALOG_FORMAT,
        cache_format=CACHE_VERSION,
        pack_format=PACK_FORMAT,
        sources=tuple(source_kinds()),
        outputs=tuple(emit_kinds()),
        rules=tuple(known_rule_names()),
        panels=tuple(panel_names()),
        locales=tuple(known_tags()),
    )


def describe(detailed: bool = False) -> str:
    """One line, or a block when somebody is trying to work out a difference."""
    found = versions()

    if not detailed:
        return f"v4t-translate {found.package}"

    lines = [
        f"v4t-translate {found.package}",
        f"  catalog format {found.catalog_format}",
        f"  cache format   {found.cache_format}",
        f"  pack format    {found.pack_format}",
        f"  reads          {', '.join(found.sources)}",
        f"  writes         {', '.join(found.outputs)}",
        f"  rules          {len(found.rules)}",
        f"  panels         {', '.join(found.panels)}",
        f"  languages      {len(found.locales)}",
    ]
    return "\n".join(lines)
