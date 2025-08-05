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
    "OutputEntry",
    "ProviderEntry",
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
    # A bare specifier, optionally with the unit stuck to it: "%d", "%.1fV",
    # "%d mm". A resource string that is only a formatted number and a unit is
    # never translatable, and every one of them reached a translator before.
    r"%[-+ #0-9.]*[hlL]?[sdfixXeEgGcpu%] ?[A-Za-z%°]{0,3}",
    r"<V\d>",
)


@dataclass(frozen=True)
class SourceEntry:
    """One file to extract from."""

    kind: str
    path: Path
    encoding: str = "utf-8-sig"
    symbols: Path | None = None

    defines: tuple[str, ...] = ()
    """Preprocessor symbols this product defines."""

    undefines: tuple[str, ...] = ()
    """Symbols it explicitly does not.

    Separate from simply leaving one out, because the two mean different
    things: a name in neither list is one the reader cannot decide, and it
    keeps the strings behind it.
    """

    def condition_symbols(self) -> dict[str, bool]:
        return {
            **{name: True for name in self.defines},
            **{name: False for name in self.undefines},
        }

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
class OutputEntry:
    """One file the build produces, for one language or for all of them."""

    kind: str
    path: str
    """Template. ``{locale}``, ``{language}``, ``{qualifier}`` and ``{project}``
    are substituted, so one entry covers every language."""

    locales: tuple[str, ...] = ()
    """Restrict to these languages. Empty means every configured one."""

    source: Path | None = None
    """The English file to localise, for emitters that rewrite one."""

    encoding: str | None = None
    fallback_to_source: bool = True

    allow_outside: bool = False
    """Let this output write outside the project directory.

    Off by default. A path template is text out of a config file and the
    build runs on machines nobody is watching, so ``..`` in one has to be
    said out loud rather than discovered.
    """

    def applies_to(self, tag: str) -> bool:
        return not self.locales or tag in self.locales

    def describe(self) -> str:
        where = ",".join(self.locales) if self.locales else "all"
        return f"{self.kind} -> {self.path} ({where})"


@dataclass(frozen=True)
class ProviderEntry:
    """A machine translation engine described in the project file.

    Kept as plain data rather than as an :class:`~v4t_translate.mt.http.
    HttpProviderConfig` so that reading a config does not import the mt
    package, which nothing needs until somebody asks for a pretranslate.
    """

    name: str
    endpoint: str
    settings: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        return f"{self.name} -> {self.endpoint}"


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
    outputs: list[OutputEntry] = field(default_factory=list)
    providers: dict[str, ProviderEntry] = field(default_factory=dict)
    catalog_dir: Path = Path("catalog")
    workbook_dir: Path = Path("workbooks")
    output_dir: Path = Path("out")
    protected_patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS
    glossary: Path | None = None
    waivers: Path = Path("waivers.toml")
    check: CheckSettings = field(default_factory=CheckSettings)

    def catalog_path(self) -> Path:
        """Where the source catalog for this project lives."""
        return self.root / self.catalog_dir / f"{_slug(self.name)}.json"

    def waivers_path(self) -> Path:
        """Where accepted findings are written down.

        Defaulted rather than optional. A project that has never waived
        anything has no file, which loads as an empty set, and the day
        somebody needs one they should not also have to find out that a
        config key exists.
        """
        return self.root / self.waivers

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
        outputs=_outputs(raw, origin),
        providers=_providers(raw, origin),
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

    waivers = project.get("waivers")
    if waivers is not None:
        config.waivers = Path(str(waivers))

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
        defines = tuple(str(name) for name in entry.get("defines", []))
        undefines = tuple(str(name) for name in entry.get("undefines", []))

        clash = set(defines) & set(undefines)
        if clash:
            raise ConfigError(
                f"{origin}: source {index} both defines and undefines "
                f"{', '.join(sorted(clash))}"
            )

        result.append(
            SourceEntry(
                kind=kind,
                path=Path(path),
                encoding=str(entry.get("encoding", "utf-8-sig")),
                symbols=Path(str(symbols)) if symbols else None,
                defines=defines,
                undefines=undefines,
            )
        )

    if not result:
        raise ConfigError(f"{origin}: no [[source]] entries, so there is nothing to read")
    return result


def _outputs(raw: dict[str, Any], origin: str) -> list[OutputEntry]:
    entries = raw.get("output", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise ConfigError(f"{origin}: [[output]] must be a list of tables")

    result: list[OutputEntry] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"{origin}: output {index} is not a table")

        kind = entry.get("kind")
        path = entry.get("path")
        if not isinstance(kind, str) or not isinstance(path, str):
            raise ConfigError(f"{origin}: output {index} needs a 'kind' and a 'path'")

        locales = entry.get("locales", entry.get("locale", []))
        if isinstance(locales, str):
            locales = [locales]

        source = entry.get("source")
        result.append(
            OutputEntry(
                kind=kind,
                path=path,
                locales=tuple(_resolve_locale(t, origin).tag for t in locales),
                source=Path(str(source)) if source else None,
                encoding=entry.get("encoding"),
                fallback_to_source=bool(entry.get("fallback", True)),
                allow_outside=bool(entry.get("allow_outside", False)),
            )
        )

    return result


def _providers(raw: dict[str, Any], origin: str) -> dict[str, ProviderEntry]:
    table = _table(raw, "provider", origin, required=False)
    result: dict[str, ProviderEntry] = {}

    for name, entry in table.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{origin}: [provider.{name}] is not a table")

        endpoint = entry.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise ConfigError(f"{origin}: [provider.{name}] needs an endpoint")

        if "://" not in endpoint:
            raise ConfigError(
                f"{origin}: [provider.{name}] endpoint {endpoint!r} is not a URL"
            )

        for forbidden in ("key", "token", "api_key", "auth", "password"):
            if forbidden in entry:
                raise ConfigError(
                    f"{origin}: [provider.{name}] must not hold a {forbidden}. "
                    f"This file goes in the repository. Name an environment "
                    f"variable with auth_env instead"
                )

        settings = {k: v for k, v in entry.items() if k != "endpoint"}
        result[name] = ProviderEntry(name=name, endpoint=endpoint, settings=settings)

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
