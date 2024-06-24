"""Message and origin types.

A message is one piece of English that a translator will be shown once. The
same English can appear in six dialogs; that is still one message, with six
origins. Merging them is not an optimisation, it is the point: "OK" gets
translated once and every OK button on every panel agrees.

The exception is when two identical strings genuinely need different
translations. German splits English "Print" into a noun and a verb, so the
button and the menu item cannot share. That is what :attr:`Message.context`
exists for, and why the key is derived from context as well as text.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class OriginKind(str, Enum):
    """What kind of resource construct a string was found in.

    The value is what gets written into the catalog file, so these strings are
    part of the on-disk format and must not be renamed casually.
    """

    DIALOG_CAPTION = "dialog-caption"
    DIALOG_CONTROL = "dialog-control"
    STRING_TABLE = "string-table"
    MENU_ITEM = "menu-item"
    MENU_POPUP = "menu-popup"
    VERSION_INFO = "version-info"
    C_STRING_TABLE = "c-string-table"
    ANDROID_STRING = "android-string"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True)
class Origin:
    """One place a message was found, precise enough to write the file back."""

    source: str
    """Path of the source file, relative to the project root."""

    kind: OriginKind
    """Which construct held it."""

    container: str
    """The enclosing resource: a dialog id, ``STRINGTABLE``, a menu id."""

    symbol: str
    """The control or string id. ``IDC_STATIC`` repeats, so this is not unique."""

    line: int = 0
    """1-based line in the source file. 0 when the source cannot report one."""

    ordinal: int = 0
    """Position within the container, used to tell repeated symbols apart."""

    def describe(self) -> str:
        """A short human-readable location for reports."""
        where = f"{self.source}:{self.line}" if self.line else self.source
        if self.symbol and self.symbol != self.container:
            return f"{where} ({self.container}/{self.symbol})"
        return f"{where} ({self.container})"


@dataclass
class Message:
    """One translatable unit of source text."""

    key: str
    """Stable identifier. See :mod:`v4t_translate.catalog.ids`."""

    source_text: str
    """The English exactly as it appears in the resource, escapes already resolved."""

    origins: list[Origin] = field(default_factory=list)
    """Every place this text was found. Never empty for an extracted message."""

    context: str | None = None
    """Disambiguator when the same English needs two translations."""

    developer_note: str | None = None
    """Guidance for the translator, written by whoever owns the source."""

    protected: bool = False
    """Set when the string must ship unchanged: unit symbols, format tokens."""

    max_chars: int | None = None
    """Hard character budget, for panels with a fixed character grid."""

    max_width_px: int | None = None
    """Hard pixel budget, derived from the control the string is drawn into."""

    max_lines: int = 1
    """How many lines the control can show before the text is clipped."""

    def add_origin(self, origin: Origin) -> None:
        """Record another place this text appears, keeping the list sorted and unique."""
        if origin in self.origins:
            return
        self.origins.append(origin)
        self.origins.sort()

    @property
    def primary_origin(self) -> Origin | None:
        """The first origin, which is the one reports lead with."""
        return self.origins[0] if self.origins else None

    @property
    def sources(self) -> list[str]:
        """Distinct source files this message came from, in order."""
        seen: list[str] = []
        for origin in self.origins:
            if origin.source not in seen:
                seen.append(origin.source)
        return seen

    def tighten(self, *, max_chars: int | None = None, max_width_px: int | None = None,
                max_lines: int | None = None) -> None:
        """Apply a constraint, keeping whichever limit is stricter.

        A message reachable from two controls has to fit in the smaller one.
        Merging by taking the minimum is the only safe direction, so this
        never relaxes a budget that is already set.
        """
        if max_chars is not None:
            self.max_chars = max_chars if self.max_chars is None else min(self.max_chars, max_chars)
        if max_width_px is not None:
            self.max_width_px = (
                max_width_px if self.max_width_px is None else min(self.max_width_px, max_width_px)
            )
        if max_lines is not None:
            self.max_lines = min(self.max_lines, max_lines) if self.max_lines else max_lines

    def merged_with(self, other: Message) -> Message:
        """Combine two extractions of the same key into one message.

        Used when several sources contribute the same key. The stricter
        constraint wins, notes concatenate, and ``protected`` is sticky because
        one source declaring a string untranslatable settles it.
        """
        if self.key != other.key:
            raise ValueError(f"cannot merge {self.key!r} with {other.key!r}")
        if self.source_text != other.source_text:
            raise ValueError(
                f"key {self.key!r} carries two different source texts: "
                f"{self.source_text!r} and {other.source_text!r}"
            )

        merged = replace(self, origins=list(self.origins))
        for origin in other.origins:
            merged.add_origin(origin)

        merged.protected = self.protected or other.protected
        merged.context = self.context or other.context
        merged.developer_note = _join_notes(self.developer_note, other.developer_note)
        merged.max_chars = _stricter(self.max_chars, other.max_chars)
        merged.max_width_px = _stricter(self.max_width_px, other.max_width_px)
        merged.max_lines = min(self.max_lines, other.max_lines)
        return merged


def _stricter(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _join_notes(left: str | None, right: str | None) -> str | None:
    if not left:
        return right
    if not right or right == left:
        return left
    return f"{left} {right}"
