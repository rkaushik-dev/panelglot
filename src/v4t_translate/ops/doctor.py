"""Checking that the project is set up before anything relies on it.

Most of what goes wrong with this tool is not a bug in it. It is a sibling
checkout that is not cloned, a font metrics file that was never copied to the
build machine, or an output template that resolves to the same path for two
languages. All of those produce something that looks like it worked.

The last one is the reason this exists. An output path template without
``{locale}`` in it writes German, then writes Chinese over the top, and the
build reports both as successful. Nothing downstream can tell.

Every check answers with a name, a verdict and something to do about it. A
check that says a thing is wrong without saying what to change is a check
people learn to ignore.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date

from ..config import ProjectConfig
from ..emit.registry import available_kinds as emit_kinds
from ..errors import ConfigError
from ..glossary import load_glossary
from ..layout.panels import font_for, get_panel, panel_names
from ..rules.registry import build_rules, known_rule_names
from ..sources.registry import available_kinds as source_kinds
from ..waivers import load_waivers
from .build import is_inside, resolve_output_path

__all__ = ["Finding", "DoctorReport", "run_doctor"]

#: Lowest Python this package supports. Kept here as well as in pyproject
#: because a machine that installed it wrong will not have read pyproject.
MINIMUM_PYTHON = (3, 10)


@dataclass(frozen=True)
class Finding:
    """One thing checked."""

    name: str
    ok: bool
    detail: str
    remedy: str = ""

    def describe(self) -> str:
        mark = "ok" if self.ok else "PROBLEM"
        line = f"[{mark}] {self.name}: {self.detail}"
        return line if self.ok or not self.remedy else f"{line}\n        {self.remedy}"


@dataclass
class DoctorReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, remedy: str = "") -> None:
        self.findings.append(Finding(name=name, ok=ok, detail=detail, remedy=remedy))

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok]

    def __bool__(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        if not self.problems:
            return f"{len(self.findings)} checks, nothing wrong"
        return f"{len(self.findings)} checks, {len(self.problems)} problems"


def run_doctor(config: ProjectConfig) -> DoctorReport:
    """Check everything that can be checked without doing any work."""
    report = DoctorReport()

    _check_python(report)
    _check_sources(config, report)
    _check_locales(config, report)
    _check_glossary(config, report)
    _check_rules(config, report)
    _check_waivers(config, report)
    _check_outputs(config, report)
    _check_providers(config, report)
    _check_catalog(config, report)

    return report


def _check_providers(config: ProjectConfig, report: DoctorReport) -> None:
    """A configured engine that cannot be built, or has no key in the shell."""
    import os

    from .pretranslate import build_provider

    for name, entry in config.providers.items():
        label = f"provider {name}"

        try:
            build_provider(config, name)
        except ConfigError as exc:
            report.add(label, False, str(exc),
                       remedy=f"Fix [provider.{name}] in the project file.")
            continue

        variable = entry.settings.get("auth_env")
        if variable and not os.environ.get(str(variable)):
            report.add(
                label, False, f"{variable} is not set in this shell",
                remedy=f"export {variable}=... before running pretranslate. "
                       f"The key is deliberately not in the config file.",
            )
            continue

        report.add(label, True, entry.describe())


def _check_python(report: DoctorReport) -> None:
    running = sys.version_info[:2]
    report.add(
        "python",
        running >= MINIMUM_PYTHON,
        f"{running[0]}.{running[1]}",
        remedy=f"This package needs {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or later.",
    )


def _check_sources(config: ProjectConfig, report: DoctorReport) -> None:
    known = set(source_kinds())

    for entry in config.sources:
        if entry.kind not in known:
            report.add(
                f"source {entry.path}", False, f"unknown kind {entry.kind!r}",
                remedy=f"Known kinds: {', '.join(sorted(known))}.",
            )
            continue

        path = config.root / entry.path
        if not path.exists():
            report.add(
                f"source {entry.path}", False, "does not exist",
                remedy=f"Expected at {path}. Is the sibling checkout cloned?",
            )
            continue

        report.add(f"source {entry.path}", True, f"{path.stat().st_size} bytes")

        if entry.symbols is not None:
            symbols = config.root / entry.symbols
            report.add(
                f"symbols {entry.symbols}", symbols.exists(),
                "found" if symbols.exists() else "does not exist",
                remedy=f"Expected at {symbols}. Without it every IDC_STATIC "
                       f"looks like a distinct control.",
            )


def _check_locales(config: ProjectConfig, report: DoctorReport) -> None:
    if not config.locales:
        report.add(
            "locales", False, "none configured",
            remedy="Add a [locale.\"de-DE\"] section, or extract has nowhere to "
                   "put translations.",
        )
        return

    for entry in config.locales:
        name = f"locale {entry.tag}"

        if entry.panel is not None:
            try:
                get_panel(entry.panel)
            except ConfigError:
                report.add(
                    name, False, f"unknown panel {entry.panel!r}",
                    remedy=f"Known panels: {', '.join(panel_names())}.",
                )
                continue

        panel = get_panel(entry.panel or "tij-800x600")
        explicit = (config.root / entry.font) if entry.font else None

        if explicit is not None and not explicit.exists():
            report.add(
                name, False, f"font metrics {entry.font} do not exist",
                remedy=f"Expected at {explicit}. Fitting will be measured against "
                       f"a stand-in font and every result will be approximate.",
            )
            continue

        font = font_for(panel, search=[config.root / "fonts", config.root],
                        explicit=explicit)
        fallback = font.name.endswith("-fallback")
        report.add(
            name, not fallback,
            f"{panel.name}, {font.name}",
            remedy="No font metrics found. Fitting findings will be approximate.",
        )

        if entry.locale.double_byte and not panel.supports_dbcs:
            report.add(
                f"{name} on {panel.name}", False,
                f"{entry.locale.english_name} needs a double byte panel",
                remedy=f"{panel.describe()} has a single byte character path. "
                       f"This language cannot ship on it.",
            )


def _check_glossary(config: ProjectConfig, report: DoctorReport) -> None:
    if config.glossary is None:
        return

    path = config.root / config.glossary
    try:
        glossary = load_glossary(path)
    except ConfigError as exc:
        report.add("glossary", False, str(exc),
                   remedy="Fix the CSV, or drop the glossary line from the config.")
        return

    if not glossary:
        report.add("glossary", True, f"{path.name} is empty or missing")
        return

    detail = f"{len(glossary)} terms across {', '.join(glossary.locales())}"
    if glossary.forbidden_count:
        detail += f", {glossary.forbidden_count} forbidden renderings"
    report.add("glossary", True, detail)

    configured = set(config.target_tags())
    orphans = sorted(set(glossary.locales()) - configured)
    if orphans:
        report.add(
            "glossary locales", False,
            f"terms for {', '.join(orphans)}, which are not configured",
            remedy="Either add the language or remove the rows; they are not "
                   "being enforced.",
        )


def _check_rules(config: ProjectConfig, report: DoctorReport) -> None:
    try:
        rules = build_rules(config.check)
    except ConfigError as exc:
        report.add("rules", False, str(exc), remedy="Fix the [check] section.")
        return

    report.add("rules", True, f"{len(rules)} enabled, fail on {config.check.fail_on}")


def _check_waivers(config: ProjectConfig, report: DoctorReport) -> None:
    """The waiver file parses, names real rules, and has not expired."""
    path = config.waivers_path()
    if not path.exists():
        return

    try:
        waivers = load_waivers(path)
    except ConfigError as exc:
        report.add("waivers", False, str(exc), remedy=f"Fix {path.name}.")
        return

    known = set(known_rule_names())
    unknown = sorted({w.rule for w in waivers if w.rule not in known})
    if unknown:
        report.add(
            "waivers", False, f"waives unknown rules: {', '.join(unknown)}",
            remedy=f"Known rules: {', '.join(known_rule_names())}. A waiver on a "
                   f"rule that does not exist suppresses nothing.",
        )
        return

    today = date.today()
    expired = [w for w in waivers if w.expired_on(today)]
    if expired:
        report.add(
            "waivers", False, f"{len(expired)} have expired",
            remedy="Renew them on purpose or delete them. " +
                   "; ".join(w.describe() for w in expired),
        )
        return

    report.add("waivers", True, f"{len(waivers)} accepted findings, none expired")


def _check_outputs(config: ProjectConfig, report: DoctorReport) -> None:
    if not config.outputs:
        report.add("outputs", True, "none configured, so build does nothing")
        return

    known = set(emit_kinds())
    seen: dict[str, tuple[str, str]] = {}

    for output in config.outputs:
        name = f"output {output.kind} {output.path}"

        if output.kind not in known:
            report.add(name, False, f"unknown kind {output.kind!r}",
                       remedy=f"Known kinds: {', '.join(sorted(known))}.")
            continue

        if output.kind == "rc" and output.source is None:
            report.add(name, False, "the rc emitter needs a source",
                       remedy="Add source = the English .rc this localises.")
            continue

        collided = False
        for entry in config.locales:
            if not output.applies_to(entry.tag):
                continue

            resolved = resolve_output_path(output.path, project=config.name,
                                           locale=entry.locale)

            if not output.allow_outside and not is_inside(config.root / resolved,
                                                          config.root):
                report.add(
                    name, False, f"{resolved} is outside the project",
                    remedy="Fix the path, or set allow_outside on that output "
                           "if writing there is deliberate.",
                )
                collided = True
                break

            previous = seen.get(resolved)
            if previous is not None:
                report.add(
                    name, False,
                    f"resolves to {resolved} for both {previous[1]} and {entry.tag}",
                    remedy="Put {locale} or {qualifier} in the path, or one "
                           "language will overwrite the other and the build will "
                           "report both as fine.",
                )
                collided = True
                break
            seen[resolved] = (output.kind, entry.tag)

        if not collided:
            report.add(name, True, "resolves to a distinct path per language")


def _check_catalog(config: ProjectConfig, report: DoctorReport) -> None:
    path = config.catalog_path()
    if not path.exists():
        report.add("catalog", False, f"{path.name} does not exist",
                   remedy="Run extract.")
        return

    newest = _newest_source(config)
    if newest is not None and newest > path.stat().st_mtime:
        report.add(
            "catalog", False, "older than the sources it came from",
            remedy="Run extract. Everything downstream is working from a stale "
                   "message list.",
        )
        return

    report.add("catalog", True, f"{path.name}, {path.stat().st_size} bytes")


def _newest_source(config: ProjectConfig) -> float | None:
    times = [
        (config.root / entry.path).stat().st_mtime
        for entry in config.sources
        if (config.root / entry.path).exists()
    ]
    return max(times) if times else None
