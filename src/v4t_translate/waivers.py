"""Findings the team has looked at and decided to live with.

Every check that runs in CI grows a set of findings nobody is going to fix.
The Hebrew build has four strings that overflow by two pixels on a panel that
is being retired in March. The Turkish translation of Purge is a word the
distributor insists on and the glossary disagrees. Both are real findings and
both are correct, and neither is going to change.

There are three ways to handle that and two of them are bad. Turning the rule
off loses it everywhere. Lowering it to a warning trains everyone to ignore
warnings. So a waiver names one finding, in one language, and says who decided
and until when.

The date is the part that makes this work. A waiver without an expiry is a
suppression, and a suppression is how a project ends up with two hundred of
them and no idea which are still true. Every waiver here dies on a date, and
the check tells you the week before rather than the morning of.

A waiver that stops matching anything is also reported. That means the finding
was fixed, and the waiver is now a note about a problem that no longer exists,
sitting in a file people read to find out what is wrong.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .errors import ConfigError
from .rules.result import Finding, Report

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

__all__ = [
    "Waiver",
    "WaiverSet",
    "WaiverOutcome",
    "load_waivers",
    "apply_waivers",
    "EXPIRY_WARNING_DAYS",
]

#: How long before a waiver expires the check starts saying so. A week is one
#: working cycle here, which is enough to either fix it or renew it on purpose.
EXPIRY_WARNING_DAYS = 7

_REQUIRED = ("rule", "reason", "until", "owner")


@dataclass(frozen=True)
class Waiver:
    """One accepted finding."""

    rule: str
    reason: str
    until: date
    owner: str

    locale: str | None = None
    """Language this applies to. None means every language, which is rare."""

    key: str | None = None
    """Message key. None means every message the rule fires on."""

    def matches(self, finding: Finding) -> bool:
        if finding.rule != self.rule:
            return False
        if self.locale is not None and finding.locale != self.locale:
            return False
        return not (self.key is not None and finding.key != self.key)

    def expired_on(self, today: date) -> bool:
        return today > self.until

    def expiring_on(self, today: date) -> bool:
        return not self.expired_on(today) and (
            self.until - today <= timedelta(days=EXPIRY_WARNING_DAYS)
        )

    def describe(self) -> str:
        scope = self.rule
        if self.locale:
            scope += f" in {self.locale}"
        if self.key:
            scope += f" on {self.key}"
        return f"{scope}, until {self.until.isoformat()}, {self.owner}"


@dataclass
class WaiverOutcome:
    """What applying a set of waivers to a report did."""

    report: Report
    """The findings that survived. A new report, not the one passed in."""

    waived: list[Finding] = field(default_factory=list)
    expired: list[Waiver] = field(default_factory=list)
    expiring: list[Waiver] = field(default_factory=list)
    unused: list[Waiver] = field(default_factory=list)

    today: date = field(default_factory=date.today)
    """The day this was evaluated against, so the countdown can be reported."""

    @property
    def problems(self) -> list[str]:
        """Things wrong with the waiver file itself, worst first."""
        lines = [
            f"waiver has expired and is no longer suppressing anything: "
            f"{waiver.describe()}"
            for waiver in self.expired
        ]
        lines.extend(
            f"waiver no longer matches any finding, so it can go: {waiver.describe()}"
            for waiver in self.unused
        )
        lines.extend(
            f"waiver expires in {(waiver.until - self.today).days} days: "
            f"{waiver.describe()}"
            for waiver in self.expiring
        )
        return lines

    def summary(self) -> str:
        if not self.waived:
            return "no findings waived"
        rules = sorted({finding.rule for finding in self.waived})
        return f"{len(self.waived)} findings waived across {', '.join(rules)}"


class WaiverSet:
    """The waivers a project has agreed, in file order."""

    def __init__(self, waivers: list[Waiver] | None = None) -> None:
        self.waivers = list(waivers or [])

    def __len__(self) -> int:
        return len(self.waivers)

    def __bool__(self) -> bool:
        return bool(self.waivers)

    def __iter__(self) -> Iterator[Waiver]:
        return iter(self.waivers)

    def matching(self, finding: Finding, *, today: date) -> Waiver | None:
        """The first live waiver covering ``finding``, if there is one."""
        for waiver in self.waivers:
            if waiver.expired_on(today):
                continue
            if waiver.matches(finding):
                return waiver
        return None


def load_waivers(path: Path | str) -> WaiverSet:
    """Read a waiver file. A missing one is an empty set, not an error."""
    path = Path(path)
    if not path.exists():
        return WaiverSet()

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    raw = payload.get("waiver", [])
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: expected a list of [[waiver]] tables")

    waivers = [_waiver_from(entry, path=path, index=index)
               for index, entry in enumerate(raw, start=1)]
    return WaiverSet(waivers)


def _waiver_from(entry: object, *, path: Path, index: int) -> Waiver:
    where = f"{path}: waiver {index}"

    if not isinstance(entry, dict):
        raise ConfigError(f"{where} is not a table")

    missing = [name for name in _REQUIRED if not entry.get(name)]
    if missing:
        raise ConfigError(
            f"{where} is missing {', '.join(missing)}. Every waiver needs a rule, "
            f"a reason, an owner and an until date, or it becomes permanent by "
            f"accident"
        )

    until = entry["until"]
    if not isinstance(until, date):
        raise ConfigError(
            f"{where}: until must be a date like 2025-03-31, not {until!r}"
        )

    return Waiver(
        rule=str(entry["rule"]),
        reason=str(entry["reason"]),
        until=until,
        owner=str(entry["owner"]),
        locale=str(entry["locale"]) if entry.get("locale") else None,
        key=str(entry["key"]) if entry.get("key") else None,
    )


def apply_waivers(report: Report, waivers: WaiverSet, *,
                  today: date | None = None) -> WaiverOutcome:
    """Filter ``report`` through ``waivers`` and say what happened.

    The report that comes back is a new one carrying the same ``checked``
    count, because the number of messages examined does not change when some
    of the answers are accepted.
    """
    today = today or date.today()

    kept = Report(checked=report.checked)
    outcome = WaiverOutcome(report=kept, today=today)
    used: set[int] = set()

    for finding in report.findings:
        matched = waivers.matching(finding, today=today)
        if matched is None:
            kept.add(finding)
            continue
        used.add(id(matched))
        outcome.waived.append(finding)

    for waiver in waivers:
        if waiver.expired_on(today):
            outcome.expired.append(waiver)
        elif id(waiver) not in used:
            outcome.unused.append(waiver)
        elif waiver.expiring_on(today):
            outcome.expiring.append(waiver)

    return outcome
