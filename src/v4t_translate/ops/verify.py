"""Checking a built language pack against the firmware it will be loaded by.

The pack carries a CRC over the id names it was built from, and the bootloader
compares that against its own compiled-in constant. That is the safety net,
and a safety net nobody tests is a safety net nobody has.

So this does on a desk what the bootloader does in the field: read the enum
out of the firmware's header, compute the signature the same way the writer
does, and say whether the pack would be accepted.

Worth running in the build, because the failure it catches is the one where
somebody inserts an id in the middle of the enum, rebuilds the firmware, and
does not rebuild the packs. Every string past that point shifts by one and
nothing crashes.

It also reports what is in the pack, which is the other thing people want at
two in the morning when a panel is showing the wrong text and nobody is sure
which pack is on the card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..emit.v4l import V4lPack, read_pack, table_signature
from ..errors import EmitError
from ..locales import lookup
from ..sources.cheader import parse_enum

__all__ = [
    "VerifyResult",
    "PackDifference",
    "PackComparison",
    "verify_pack",
    "signature_of_header",
    "compare_packs",
]


@dataclass(frozen=True)
class PackDifference:
    """One slot that does not say the same thing in both packs."""

    index: int
    before: str
    after: str

    @property
    def kind(self) -> str:
        if not self.before:
            return "filled in"
        if not self.after:
            return "emptied"
        return "changed"

    def describe(self) -> str:
        if self.kind == "filled in":
            return f"slot {self.index} was empty and is now {self.after!r}"
        if self.kind == "emptied":
            return f"slot {self.index} was {self.before!r} and is now empty"
        return f"slot {self.index}: {self.before!r} -> {self.after!r}"


@dataclass
class PackComparison:
    """What changed between two builds of the same language."""

    before: Path
    after: Path
    differences: list[PackDifference] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    """Reasons the two are not comparable slot by slot at all."""

    @property
    def identical(self) -> bool:
        return not self.differences and not self.problems

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for difference in self.differences:
            counts[difference.kind] = counts.get(difference.kind, 0) + 1
        return counts

    def summary(self) -> str:
        if self.problems:
            return f"{self.before.name} and {self.after.name}: {self.problems[0]}"
        if not self.differences:
            return f"{self.before.name} and {self.after.name} are the same pack"
        parts = ", ".join(f"{count} {kind}"
                          for kind, count in sorted(self.by_kind().items()))
        return f"{len(self.differences)} slots differ ({parts})"


def compare_packs(before: Path | str, after: Path | str) -> PackComparison:
    """Say what moved between two packs, slot by slot.

    This is the two in the morning question. There is a pack on the card and a
    pack in the archive, the panel is showing something nobody expects, and
    what everybody wants to know is which strings are not the same.

    Comparison is by slot index, not by text, because the slot is what the
    firmware indexes with. Two packs with different signatures are not
    comparable at all and it says so instead of producing a diff of nonsense:
    the enum moved between them, so slot 40 is a different string in each.
    """
    before, after = Path(before), Path(after)
    first = read_pack(_read(before))
    second = read_pack(_read(after))

    comparison = PackComparison(before=before, after=after)

    if first.signature != second.signature:
        comparison.problems.append(
            f"the signatures differ ({first.signature:08X} and "
            f"{second.signature:08X}), so the enum moved between these two "
            f"builds and the slots do not line up"
        )
        return comparison

    if first.tag != second.tag:
        comparison.problems.append(
            f"one is {first.tag} and the other is {second.tag}"
        )
        return comparison

    if len(first) != len(second):
        comparison.problems.append(
            f"one holds {len(first)} strings and the other {len(second)}, "
            f"with the same signature, which should not be possible"
        )
        return comparison

    for index, (old, new) in enumerate(zip(first.strings, second.strings,
                                           strict=True)):
        if old != new:
            comparison.differences.append(
                PackDifference(index=index, before=old, after=new)
            )

    return comparison


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise EmitError(f"{path} does not exist") from exc


@dataclass
class VerifyResult:
    """What one pack looks like, and whether the firmware would take it."""

    path: Path
    pack: V4lPack
    expected_signature: int | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.problems

    def describe(self) -> str:
        parts = [
            f"{self.path.name}: {self.pack.tag}, {len(self.pack)} strings",
            f"codepage {self.pack.codepage or 'none, UTF-16'}",
            f"signature {self.pack.signature:08X}",
        ]
        return ", ".join(parts)

    def summary(self) -> str:
        if self.accepted:
            return f"{self.path.name} would be accepted"
        return f"{self.path.name} would be refused: {self.problems[0]}"


def signature_of_header(path: Path | str) -> int:
    """The signature the firmware in ``path`` will be expecting.

    Computed from the enum, not from the string table, because the enum is
    what the firmware indexes with and the table is what happens to be beside
    it. They are supposed to agree; when they do not, the enum is right.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise EmitError(f"{path} does not exist") from exc
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252")

    names = [name for name in parse_enum(text) if not name.endswith("_COUNT")]
    if not names:
        raise EmitError(f"{path}: no enum to take a signature from")

    return table_signature(names)


def verify_pack(pack_path: Path | str, *, header: Path | str | None = None,
                expect_locale: str | None = None) -> VerifyResult:
    """Read a pack and say whether the firmware would load it."""
    pack_path = Path(pack_path)
    result = VerifyResult(path=pack_path, pack=read_pack(_read(pack_path)))

    if header is not None:
        expected = signature_of_header(header)
        result.expected_signature = expected
        if expected != result.pack.signature:
            result.problems.append(
                f"signature {result.pack.signature:08X} does not match the "
                f"firmware's {expected:08X}. The enum has moved since this pack "
                f"was built, so every string past the change would be shifted"
            )

    if expect_locale is not None:
        wanted = lookup(expect_locale)
        if wanted is None:
            result.problems.append(f"{expect_locale} is not a language this knows")
        elif wanted.tag != result.pack.tag:
            result.problems.append(
                f"the pack is {result.pack.tag} and {wanted.tag} was expected"
            )
        elif wanted.lcid != result.pack.lcid:
            result.problems.append(
                f"the pack says locale id {result.pack.lcid:04X} and {wanted.tag} "
                f"is {wanted.lcid:04X}"
            )

    _add_notes(result)
    return result


def _add_notes(result: VerifyResult) -> None:
    """Things worth saying that are not reasons to refuse the pack."""
    pack = result.pack

    empty = sum(1 for text in pack.strings if not text)
    if empty:
        result.notes.append(
            f"{empty} of {len(pack)} slots are empty and will draw as nothing"
        )

    if pack.is_utf16 and pack.codepage:
        result.notes.append(
            "the pack is UTF-16 and still names a codepage, which the firmware "
            "ignores"
        )

    locale = lookup(pack.tag)
    if locale is not None:
        if locale.rtl and not pack.is_rtl:
            result.notes.append(
                f"{locale.english_name} is right to left and the pack does not "
                f"say so"
            )
        if locale.double_byte and not pack.is_utf16:
            result.notes.append(
                f"{locale.english_name} needs more than one byte a character and "
                f"the pack is 8-bit"
            )
    else:
        result.notes.append(f"{pack.tag} is not a language this build knows")
