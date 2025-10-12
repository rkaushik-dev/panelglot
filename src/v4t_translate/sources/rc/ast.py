"""Node types for the part of a resource script we actually read.

Only the constructs that can hold a translatable string get real nodes.
Everything else survives as a :class:`RawBlock`, which keeps its source text
verbatim so the writer can put the file back together without understanding
what it just copied.

Geometry is kept on dialogs and controls because the fitting rule needs it.
The numbers are dialog units, not pixels; converting them needs the dialog
font, which is why :class:`Dialog` carries that too.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

__all__ = [
    "Accelerator",
    "AcceleratorTable",
    "Control",
    "Dialog",
    "MenuItem",
    "Menu",
    "StringEntry",
    "StringTable",
    "VersionValue",
    "VersionInfo",
    "RawBlock",
    "ResourceScript",
]


@dataclass
class Control:
    """One control statement inside a dialog block."""

    statement: str
    """``LTEXT``, ``PUSHBUTTON``, ``CONTROL`` and so on, as written."""

    symbol: str
    """Control id as written: a symbol name, or a bare number."""

    caption: str | None = None
    """Unescaped caption text, or ``None`` for controls that carry no text."""

    window_class: str | None = None
    """Only set for ``CONTROL``, where the class decides what the caption is."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    line: int = 0
    ordinal: int = 0
    """Position within the dialog, counted from zero. Disambiguates IDC_STATIC."""

    caption_span: tuple[int, int] | None = None
    """Offsets of the caption literal, quotes included, for the writer."""

    styles: list[str] = field(default_factory=list)
    """Style tokens as written, ``|`` separated in the source."""

    def has_style(self, name: str) -> bool:
        return name.upper() in {s.upper() for s in self.styles}

    @property
    def is_multiline(self) -> bool:
        """True when the control wraps rather than clipping at one line.

        A static with ``SS_LEFT`` and no ``SS_LEFTNOWORDWRAP`` wraps, and so
        does a button with ``BS_MULTILINE``. Anything else gets one line.
        """
        if self.has_style("SS_LEFTNOWORDWRAP") or self.has_style("SS_PATHELLIPSIS"):
            return False
        if self.has_style("BS_MULTILINE"):
            return True
        return self.statement.upper() in {"LTEXT", "RTEXT", "CTEXT"} and self.height > 12


@dataclass
class Dialog:
    """A ``DIALOG`` or ``DIALOGEX`` block."""

    symbol: str
    statement: str = "DIALOGEX"
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    caption: str | None = None
    caption_span: tuple[int, int] | None = None
    font_size: int = 8
    font_name: str = "MS Shell Dlg"
    font_span: tuple[int, int] | None = None
    """Offsets of the font name literal, so a locale can be given its own."""

    controls: list[Control] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    line: int = 0

    exstyles: list[str] = field(default_factory=list)
    """Extended style tokens, as written. Empty when there is no EXSTYLE line."""

    exstyle_span: tuple[int, int] | None = None
    """Offsets of the whole EXSTYLE line, so a locale can rewrite it."""

    header_end: int = 0
    """Offset just past the header line, where an EXSTYLE would be inserted.

    Kept because a dialog with no EXSTYLE has no span to replace, and a right
    to left build has to put one somewhere. Immediately after the header is
    where the dialog editor puts it.
    """

    def captioned_controls(self) -> Iterator[Control]:
        """Controls that carry text a translator will see."""
        for control in self.controls:
            if control.caption:
                yield control

    def control_by_symbol(self, symbol: str) -> Control | None:
        for control in self.controls:
            if control.symbol == symbol:
                return control
        return None


@dataclass
class StringEntry:
    """One row of a ``STRINGTABLE``."""

    symbol: str
    text: str
    line: int = 0
    span: tuple[int, int] | None = None
    """Offsets of the literal, or of the first and last of a joined run."""


@dataclass
class StringTable:
    """A ``STRINGTABLE`` block. A file may hold several."""

    entries: list[StringEntry] = field(default_factory=list)
    line: int = 0


@dataclass
class MenuItem:
    """A ``MENUITEM`` or ``POPUP``. Popups nest, menu items do not."""

    text: str | None
    symbol: str | None = None
    children: list[MenuItem] = field(default_factory=list)
    is_popup: bool = False
    is_separator: bool = False
    line: int = 0
    span: tuple[int, int] | None = None

    def walk(self) -> Iterator[MenuItem]:
        """This item and every item beneath it, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def shortcut(self) -> str | None:
        """The hint after the tab, if this item advertises a shortcut.

        ``MENUITEM "&New\\tCtrl+N", ID_FILE_NEW`` draws Ctrl+N right aligned
        in the menu. The hint is only text. The key that actually works comes
        from the accelerator table, which is not translated, so the two can
        disagree and nothing in the build notices.
        """
        if not self.text or "\t" not in self.text:
            return None
        return self.text.split("\t", 1)[1] or None


@dataclass
class Accelerator:
    """One row of an ``ACCELERATORS`` table."""

    key: str
    """The key as written: ``"^N"``, ``"N"`` or a ``VK_`` name."""

    symbol: str
    """The command id this fires, which is what ties it to a menu item."""

    flags: list[str] = field(default_factory=list)
    """``VIRTKEY``, ``CONTROL``, ``SHIFT``, ``ALT``, ``ASCII``, ``NOINVERT``."""

    quoted: bool = False
    """Whether the key was a string literal rather than a ``VK_`` name."""

    line: int = 0

    def has_flag(self, name: str) -> bool:
        return name.upper() in {flag.upper() for flag in self.flags}

    def describe(self) -> str:
        """The shortcut as a person would write it, for a translator note.

        This is what the menu hint is supposed to say, so producing it here
        is what lets the two be compared at all.
        """
        parts: list[str] = []
        key = self.key

        if self.quoted and key.startswith("^"):
            # The old ASCII form. ^N is control-N whatever the flags say.
            parts.append("Ctrl")
            key = key[1:]
        else:
            if self.has_flag("CONTROL"):
                parts.append("Ctrl")
            if self.has_flag("ALT"):
                parts.append("Alt")
            if self.has_flag("SHIFT"):
                parts.append("Shift")

        parts.append(_key_name(key))
        return "+".join(parts)


def _key_name(key: str) -> str:
    """Turn a raw key into what a menu hint would show."""
    if key.startswith("VK_"):
        name = key[3:]
        return _VIRTUAL_KEY_NAMES.get(name, name.title() if len(name) > 1 else name)
    return key.upper() if len(key) == 1 else key


#: Only the ones whose menu spelling is not just the name title cased.
_VIRTUAL_KEY_NAMES = {
    "PRIOR": "PgUp",
    "NEXT": "PgDn",
    "RETURN": "Enter",
    "ESCAPE": "Esc",
    "OEM_PLUS": "+",
    "OEM_MINUS": "-",
}


@dataclass
class AcceleratorTable:
    """An ``ACCELERATORS`` resource.

    Kept because the keys in it are the ones that work, and none of them are
    translated. A German build whose Neu menu item says Strg+N while the
    table still fires on N is right. One that says Strg+U is a shortcut that
    does nothing, and it ships.
    """

    symbol: str
    entries: list[Accelerator] = field(default_factory=list)
    line: int = 0

    def for_command(self, symbol: str) -> Accelerator | None:
        for entry in self.entries:
            if entry.symbol == symbol:
                return entry
        return None


@dataclass
class Menu:
    """A ``MENU`` or ``MENUEX`` block."""

    symbol: str
    items: list[MenuItem] = field(default_factory=list)
    line: int = 0

    def walk(self) -> Iterator[MenuItem]:
        for item in self.items:
            yield from item.walk()


@dataclass
class VersionValue:
    """One ``VALUE "name", "text"`` inside a version block."""

    name: str
    text: str
    line: int = 0
    span: tuple[int, int] | None = None


@dataclass
class VersionInfo:
    """A ``VERSIONINFO`` resource, reduced to its string values.

    The numeric fields are left in the raw text. Only ``StringFileInfo``
    carries anything a person reads, and only some of that: the company name
    and the copyright are legal text that a translator must not touch, while
    the file description is what Explorer shows in the details pane and is
    the one string in here anybody has ever complained about being English.
    """

    symbol: str
    values: list[VersionValue] = field(default_factory=list)
    line: int = 0

    def value(self, name: str) -> VersionValue | None:
        for entry in self.values:
            if entry.name.lower() == name.lower():
                return entry
        return None


@dataclass
class RawBlock:
    """A resource we do not read, kept verbatim.

    Bitmaps, icons, version blocks and toolbars all land here. Keeping the
    source text rather than dropping it means the writer can reproduce a file
    it only partly understands.
    """

    symbol: str
    statement: str
    text: str
    line: int = 0


@dataclass
class ResourceScript:
    """Everything read out of one ``.rc`` file, in source order."""

    path: str
    dialogs: list[Dialog] = field(default_factory=list)
    string_tables: list[StringTable] = field(default_factory=list)
    menus: list[Menu] = field(default_factory=list)
    accelerators: list[AcceleratorTable] = field(default_factory=list)
    versions: list[VersionInfo] = field(default_factory=list)
    raw_blocks: list[RawBlock] = field(default_factory=list)
    directives: list[str] = field(default_factory=list)
    language: str | None = None
    """The last ``LANGUAGE`` statement seen, as written."""

    language_span: tuple[int, int] | None = None
    """Offsets of that statement, so a localised copy can carry its own."""

    text: str = ""
    """The source text this was parsed from. The writer rewrites spans of it."""

    def dialog(self, symbol: str) -> Dialog | None:
        for dialog in self.dialogs:
            if dialog.symbol == symbol:
                return dialog
        return None

    def string_entries(self) -> Iterator[StringEntry]:
        """Every string table row across every table in the file."""
        for table in self.string_tables:
            yield from table.entries

    def menu_items(self) -> Iterator[MenuItem]:
        for menu in self.menus:
            yield from menu.walk()

    def counts(self) -> dict[str, int]:
        """Summary used by ``extract --verbose`` and by the tests."""
        return {
            "dialogs": len(self.dialogs),
            "controls": sum(len(d.controls) for d in self.dialogs),
            "string_tables": len(self.string_tables),
            "strings": sum(len(t.entries) for t in self.string_tables),
            "menus": len(self.menus),
            "menu_items": sum(1 for _ in self.menu_items()),
            "accelerators": sum(len(t.entries) for t in self.accelerators),
            "version_values": sum(len(v.values) for v in self.versions),
            "raw_blocks": len(self.raw_blocks),
        }

    def version_values(self) -> Iterator[VersionValue]:
        for version in self.versions:
            yield from version.values

    def accelerator_for(self, symbol: str) -> Accelerator | None:
        """The shortcut bound to a command id, across every table in the file.

        Tables are searched in source order and the first hit wins, which is
        also what the resource compiler does when a command appears twice.
        """
        for table in self.accelerators:
            found = table.for_command(symbol)
            if found is not None:
                return found
        return None
