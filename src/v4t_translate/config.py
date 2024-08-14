"""Project configuration.

One TOML file at the root of a localisation project describes what to read,
what languages exist, and what to write. Everything else in the package takes
its paths from here, so nothing has to guess where a workbook lives or which
panel a language is drawn on.

Paths in the file are relative to the file itself, not to the working
directory. People run this from wherever they happen to be and a config that
only works from one directory is a config that gets copied and edited.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .locales import Locale, resolve

if sys.version_info >= (3, 11):  # pragma: no cover - version split
    import tomllib
else:  # pragma: no cover - version split
    import tomli as tomllib

__all__ = [
    "CONFIG_FILENAME",
    "SourceEntry",
    "LocaleEntry",
    "CheckSettings",
    "ProjectConfig",
    "load_config",
    "find_config",
]

CONFIG_FILENAME = "v4t-translate.toml"

#: Patterns that are untranslatable in every project we have. Kept here rather
#: than in a default config file so a project that writes its own list still
#: gets them; the config adds to this, it does not replace it.
DEFAULT_PROTECTED_PATTERNS: tuple[str, ...] = (
    r"mm",
    r"ms",
    r"cm",
    r"dpi",
    r"V",
    r"Hz",
    r"YY|YYYY|MM|MMM|MMMM|DD|DDD|DDDD|WW|JJJ|UU",
    r"hh|HH|SS|tt",
    r"hh:mm(:ss)?",
    r"%[-+ #0-9.]*[hlL]?[sdfixXeEgGcpu%]",
    r"<V\d>",
)


@dataclass(frozen=True)
class SourceEntry:
    """One file to extract from."""

    kind: str
    path: Path
    encoding: str = "utf-8-sig"
    symbols: Path | None = None

    def describe(self) -> str:
        return f"{self.kind}:{self.path.as_posix()}"


@dataclass(frozen=True)
class LocaleEntry:
    """One target language and where its pieces live."""

    locale: Locale
    workbook: Path | None = None
    panel: str | None = None
    font: Path | None = None

    @property
    def tag(self) -> str:
        return self.locale.tag


@dataclass(frozen=True)
class CheckSettings:
    """What ``check`` treats as a failure."""

    fail_on: str = "error"
    disabled_rules: tuple[str, ...] = ()
    promoted_rules: tuple[str, ...] = ()
    """Rules whose findings become errors even if they normally warn."""

    demoted_rules: tuple[str, ...] = ()
    """Rules whose findings become warnings even if they normally fail."""

    def is_enabled(self, rule: str) -> bool:
        return rule not in self.disabled_rules


@dataclass
class ProjectConfig:
    """Everything one localisation project needs to know about itself."""

    name: str
    root: Path
    source_locale: Locale
    sources: list[SourceEntry] = field(default_factory=list)
    locales: list[LocaleEntry] = field(default_factory=list)
    catalog_dir: Path = Path("catalog")
    workbook_dir: Path = Path("workbooks")
    output_dir: Path = Path("out")
    protected_patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS
    glossary: Path | None = None
    check: CheckSettings = field(default_factory=CheckSettings)

    def catalog_path(self) -> Path:
        """Where the source catalog for this project lives."""
        return self.root / self.catalog_dir / f"{_slug(self.name)}.json"

    def translations_path(self, tag: str) -> Path:
        return self.root / self.catalog_dir / f"{tag}.json"

    def locale_entry(self, tag: str) -> LocaleEntry:
        wanted = resolve(tag)
        for entry in self.locales:
            if entry.locale.tag == wanted.tag:
                return entry
        raise ConfigError(
            f"{wanted.tag} is not configured. Configured: "
            f"{', '.join(e.tag for e in self.locales) or 'none'}"
        )

    def target_tags(self) -> list[str]:
        return [entry.tag for entry in self.locales]

    def workbook_path(self, tag: str) -> Path:
        entry = self.locale_entry(tag)
        if entry.workbook is not None:
            return self.root / entry.workbook
        return self.root / self.workbook_dir / f"{self.name} - {entry.locale.english_name}.xlsx"


def find_config(start: Path | None = None) -> Path:
    """Walk up from ``start`` looking for the project file."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"no {CONFIG_FILENAME} found in {current} or any parent directory"
    )


def load_config(path: Path | str | None = None) -> ProjectConfig:
    """Read a project file. Without a path, search upward from the cwd."""
    config_path = Path(path) if path is not None else find_config()

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{config_path} does not exist") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path} is not valid TOML: {exc}") from exc

    return _build(raw, root=config_path.parent, origin=str(config_path))


def _build(raw: dict[str, Any], *, root: Path, origin: str) -> ProjectConfig:
    project = _table(raw, "project", origin)
    name = project.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{origin}: [project] needs a non-empty name")

    config = ProjectConfig(
        name=name.strip(),
        root=root,
        source_locale=_resolve_locale(project.get("source_locale", "en-US"), origin),
        sources=_sources(raw, origin),
        locales=_locales(raw, origin),
    )

    for key, attribute in (("catalog_dir", "catalog_dir"),
                           ("workbook_dir", "workbook_dir"),
                           ("output_dir", "output_dir")):
        value = project.get(key)
        if value is not None:
            setattr(config, attribute, Path(str(value)))

    glossary = project.get("glossary")
    if glossary is not None:
        config.glossary = Path(str(glossary))

    protected = _table(raw, "protected", origin, required=False)
    extra = protected.get("patterns", [])
    if not isinstance(extra, list):
        raise ConfigError(f"{origin}: [protected] patterns must be a list")
    if protected.get("replace_defaults", False):
        config.protected_patterns = tuple(str(p) for p in extra)
    else:
        config.protected_patterns = DEFAULT_PROTECTED_PATTERNS + tuple(str(p) for p in extra)

    config.check = _check(raw, origin)
    return config


def _sources(raw: dict[str, Any], origin: str) -> list[SourceEntry]:
    entries = raw.get("source", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise ConfigError(f"{origin}: [[source]] must be a list of tables")

    result: list[SourceEntry] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"{origin}: source {index} is not a table")
        kind = entry.get("kind")
        path = entry.get("path")
        if not isinstance(kind, str) or not isinstance(path, str):
            raise ConfigError(f"{origin}: source {index} needs a 'kind' and a 'path'")
        symbols = entry.get("symbols")
        result.append(
            SourceEntry(
                kind=kind,
                path=Path(path),
                encoding=str(entry.get("encoding", "utf-8-sig")),
                symbols=Path(str(symbols)) if symbols else None,
            )
        )

    if not result:
        raise ConfigError(f"{origin}: no [[source]] entries, so there is nothing to read")
    return result


def _locales(raw: dict[str, Any], origin: str) -> list[LocaleEntry]:
    table = _table(raw, "locale", origin, required=False)
    result: list[LocaleEntry] = []

    for tag, entry in table.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{origin}: [locale.{tag}] is not a table")
        locale = _resolve_locale(tag, origin)
        workbook = entry.get("workbook")
        font = entry.get("font")
        result.append(
            LocaleEntry(
                locale=locale,
                workbook=Path(str(workbook)) if workbook else None,
                panel=entry.get("panel"),
                font=Path(str(font)) if font else None,
            )
        )

    seen = [e.tag for e in result]
    duplicates = {tag for tag in seen if seen.count(tag) > 1}
    if duplicates:
        raise ConfigError(f"{origin}: {', '.join(sorted(duplicates))} configured twice")

    return result


def _check(raw: dict[str, Any], origin: str) -> CheckSettings:
    table = _table(raw, "check", origin, required=False)
    fail_on = str(table.get("fail_on", "error"))
    if fail_on not in ("error", "warning", "never"):
        raise ConfigError(
            f"{origin}: [check] fail_on must be error, warning or never, not {fail_on!r}"
        )
    return CheckSettings(
        fail_on=fail_on,
        disabled_rules=tuple(str(r) for r in table.get("disable", [])),
        promoted_rules=tuple(str(r) for r in table.get("promote", [])),
        demoted_rules=tuple(str(r) for r in table.get("demote", [])),
    )


def _table(raw: dict[str, Any], key: str, origin: str, *, required: bool = True
           ) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        if required:
            raise ConfigError(f"{origin}: missing [{key}] section")
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{origin}: [{key}] must be a table")
    return value


def _resolve_locale(tag: Any, origin: str) -> Locale:
    try:
        return resolve(str(tag))
    except ConfigError as exc:
        raise ConfigError(f"{origin}: {exc}") from exc


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
