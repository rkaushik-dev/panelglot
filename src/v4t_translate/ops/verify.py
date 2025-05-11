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

__all__ = ["VerifyResult", "verify_pack", "signature_of_header"]


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
    try:
        data = pack_path.read_bytes()
    except FileNotFoundError as exc:
        raise EmitError(f"{pack_path} does not exist") from exc

    result = VerifyResult(path=pack_path, pack=read_pack(data))

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
