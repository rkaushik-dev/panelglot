"""Turning a parsed resource script into catalog messages.

The parser answers "what is in this file". This answers "what does a
translator need to see, and how much room does it have". The second question
is the one with all the judgement in it.

Two decisions are worth spelling out.

A control's pixel budget is not its width. A checkbox spends seventeen pixels
on the box before any text is drawn, a group box spends nine on the frame and
the gap, and a push button needs padding at both ends or the caption touches
the border. Charging a translation the full control width would pass strings
that visibly overflow, which is worse than not checking at all.

Menu accelerators are left inside the message. ``&New\\tCtrl+N`` is one string
to the resource compiler, and splitting it would mean reassembling it on the
way out and getting the tab wrong in some locale. The protected-token rule
enforces the suffix instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...catalog.ids import message_key
from ...catalog.model import Message, Origin, OriginKind
from ...errors import SourceError
from ...layout.dlu import base_units_for
from ..base import Extraction, SourceOptions
from ..notes import NoteIndex, collect_notes
from .ast import Control, Dialog, ResourceScript
from .conditions import ConditionMap, collect_conditions
from .parser import parse_resource_script
from .symbols import SymbolTable, load_resource_header

__all__ = ["RcSource", "control_text_budget"]

#: Pixels a control spends on its own decoration before any text is drawn.
#: Measured against the standard themed metrics at 96 DPI.
_CHROME_PX: dict[str, int] = {
    "PUSHBUTTON": 8,
    "DEFPUSHBUTTON": 8,
    "PUSHBOX": 8,
    "CHECKBOX": 17,
    "AUTOCHECKBOX": 17,
    "AUTO3STATE": 17,
    "STATE3": 17,
    "RADIOBUTTON": 17,
    "AUTORADIOBUTTON": 17,
    "GROUPBOX": 15,
    "LTEXT": 0,
    "RTEXT": 0,
    "CTEXT": 0,
}

#: Button styles that put a box in front of the caption. A CONTROL statement
#: carries these instead of naming a checkbox statement.
_BOXED_STYLES = frozenset(
    {"BS_AUTOCHECKBOX", "BS_CHECKBOX", "BS_AUTORADIOBUTTON", "BS_RADIOBUTTON",
     "BS_AUTO3STATE", "BS_3STATE"}
)

#: A caption that is only punctuation or digits is not a translatable string.
#: "4." went through the machine translator and came back as a 4 followed by
#: an ideographic full stop, and it shipped like that.
_NOT_WORDS = re.compile(r"^[\W\d_]*$", re.UNICODE)


class RcSource:
    """Reader for Win32 resource scripts."""

    kind = "rc"

    def __init__(self) -> None:
        self.notes: NoteIndex | None = None
        self.conditions: ConditionMap | None = None
        self.symbols: dict[str, bool] = {}

    def extract(self, options: SourceOptions) -> Extraction:
        source = options.relative()
        extraction = Extraction(source=source)

        text = _read_text(options.path, options.encoding)
        script = parse_resource_script(text, path=source)
        symbols = self._load_symbols(options, extraction)
        protected = [re.compile(pattern) for pattern in options.protected_patterns]
        self.notes = collect_notes(text)
        self.conditions = collect_conditions(text)
        self.symbols = dict(options.symbols)

        for dialog in script.dialogs:
            self._collect_dialog(dialog, source, symbols, protected, extraction)

        self._collect_strings(script, source, protected, extraction)
        self._collect_menus(script, source, protected, extraction)
        self._collect_versions(script, source, protected, extraction)

        extraction.stats = script.counts()
        extraction.stats["notes"] = len(self.notes)
        extraction.stats["messages"] = len(extraction.by_key())
        return extraction

    def _keep(self, line: int) -> bool:
        """Whether a string on this line is in the product being extracted."""
        if self.conditions is None:
            return True
        return self.conditions.is_live(line, self.symbols)

    def _apply_conditions(self, message: Message, line: int) -> Message:
        """Note the conditions a kept string is behind.

        A translator has no other way to know that "Pen 5" only exists on one
        product, and that is exactly the context that stops somebody
        wondering whether it is a mistake.
        """
        if self.conditions is None:
            return message

        named = self.conditions.describe(line)
        if named:
            message.developer_note = " ".join(
                part for part in (
                    message.developer_note, f"Only built when {named}.",
                ) if part
            )
        return message

    def _apply_note(self, message: Message, line: int) -> Message:
        """Attach a developer comment, and re-key if it set a context.

        Re-keying rather than setting the context afterwards, because the key
        is derived from the context and a message whose context arrives late
        would otherwise be filed under the wrong one.
        """
        note = self.notes.for_line(line) if self.notes is not None else None
        if note is None:
            return message

        if note.text:
            message.developer_note = (
                f"{note.text} {message.developer_note}".strip()
                if message.developer_note else note.text
            )

        if note.context:
            message.context = note.context
            message.key = message_key(message.source_text, note.context)

        return message

    # -- pieces ---------------------------------------------------------

    @staticmethod
    def _load_symbols(options: SourceOptions, extraction: Extraction) -> SymbolTable:
        if options.symbols_path is None:
            return SymbolTable()
        if not options.symbols_path.exists():
            extraction.warn(f"symbols file {options.symbols_path} does not exist")
            return SymbolTable()
        return load_resource_header(options.symbols_path)

    def _collect_dialog(self, dialog: Dialog, source: str, symbols: SymbolTable,
                        protected: list[re.Pattern[str]], extraction: Extraction) -> None:
        if dialog.caption and not _is_boilerplate(dialog.caption):
            title = _message(
                dialog.caption,
                Origin(source=source, kind=OriginKind.DIALOG_CAPTION,
                       container=dialog.symbol, symbol=dialog.symbol,
                       line=dialog.line),
                protected=_matches(dialog.caption, protected),
            )
            if self._keep(dialog.line):
                extraction.messages.append(
                    self._apply_conditions(self._apply_note(title, dialog.line),
                                           dialog.line)
                )

        units = base_units_for(dialog.font_name, dialog.font_size)

        for control in dialog.captioned_controls():
            caption = control.caption or ""
            if _is_boilerplate(caption):
                continue

            budget = control_text_budget(control, units.x_to_pixels(control.width))
            if budget <= 0:
                extraction.warn(
                    f"{source}:{control.line}: {control.statement} {control.symbol} "
                    f"is too narrow to hold any text"
                )

            message = _message(
                caption,
                Origin(
                    source=source,
                    kind=OriginKind.DIALOG_CONTROL,
                    container=dialog.symbol,
                    symbol=control.symbol,
                    line=control.line,
                    ordinal=control.ordinal,
                ),
                protected=_matches(caption, protected),
            )
            message.max_width_px = max(budget, 0)
            message.max_lines = _line_budget(control, units.y_to_pixels(control.height))
            if self._keep(control.line):
                extraction.messages.append(
                    self._apply_conditions(self._apply_note(message, control.line),
                                           control.line)
                )

            if symbols.is_anonymous(control.symbol):
                # Nothing wrong with it, but it means the origin cannot be
                # grepped for, so the ordinal is the only way back. Appended
                # rather than used as a fallback, because a developer's own
                # note and this one answer different questions.
                message.developer_note = " ".join(
                    part for part in (
                        message.developer_note,
                        f"Anonymous control, position {control.ordinal} in "
                        f"{dialog.symbol}.",
                    ) if part
                )

    def _collect_strings(self, script: ResourceScript, source: str,
                         protected: list[re.Pattern[str]], extraction: Extraction) -> None:
        for entry in script.string_entries():
            if _is_boilerplate(entry.text):
                continue
            message = _message(
                entry.text,
                Origin(source=source, kind=OriginKind.STRING_TABLE,
                       container="STRINGTABLE", symbol=entry.symbol, line=entry.line),
                protected=_matches(entry.text, protected),
            )
            if self._keep(entry.line):
                extraction.messages.append(
                    self._apply_conditions(self._apply_note(message, entry.line),
                                           entry.line)
                )

    def _collect_versions(self, script: ResourceScript, source: str,
                          protected: list[re.Pattern[str]],
                          extraction: Extraction) -> None:
        """The few version block fields anybody reads.

        FileDescription is what Explorer shows in the details pane, and it is
        the one string in the version block a customer has ever asked about
        being in English. CompanyName and LegalCopyright are legal text and
        are left alone on purpose.
        """
        for version in script.versions:
            for value in version.values:
                if value.name.lower() not in TRANSLATABLE_VERSION_FIELDS:
                    continue
                if _is_boilerplate(value.text):
                    continue

                message = _message(
                    value.text,
                    Origin(source=source, kind=OriginKind.VERSION_INFO,
                           container=version.symbol, symbol=value.name,
                           line=value.line),
                    protected=_matches(value.text, protected),
                )
                message.developer_note = (
                    f"Version block {value.name}. Shown by Explorer, not by the HMI."
                )
                extraction.messages.append(message)

    def _collect_menus(self, script: ResourceScript, source: str,
                       protected: list[re.Pattern[str]], extraction: Extraction) -> None:
        for menu in script.menus:
            for index, item in enumerate(menu.walk()):
                if item.is_separator or not item.text:
                    continue
                if _is_boilerplate(item.text):
                    continue
                kind = OriginKind.MENU_POPUP if item.is_popup else OriginKind.MENU_ITEM
                message = _message(
                    item.text,
                    Origin(source=source, kind=kind, container=menu.symbol,
                           symbol=item.symbol or menu.symbol, line=item.line, ordinal=index),
                    protected=_matches(item.text, protected),
                )
                if "\t" in item.text:
                    message.developer_note = (
                        "Everything after the tab is the accelerator label and must "
                        "stay as it is."
                    )
                if self._keep(item.line):
                    extraction.messages.append(
                        self._apply_conditions(self._apply_note(message, item.line),
                                               item.line)
                    )


#: Version block fields a translator should see. Everything else in there is
#: either a legal string that must not change, a file name, or a number.
TRANSLATABLE_VERSION_FIELDS = frozenset({"filedescription", "productname", "comments"})


def control_text_budget(control: Control, width_px: int) -> int:
    """Pixels actually available for the caption inside ``control``."""
    statement = control.statement.upper()

    chrome = _CHROME_PX.get(statement)
    if chrome is None:
        chrome = 17 if any(style.upper() in _BOXED_STYLES for style in control.styles) else 0

    return width_px - chrome


def _line_budget(control: Control, height_px: int) -> int:
    """How many lines of text the control can show."""
    if not control.is_multiline:
        return 1
    # 13 pixels is one line of the 8pt shell font including leading.
    return max(1, height_px // 13)


def _message(text: str, origin: Origin, *, protected: bool = False) -> Message:
    return Message(
        key=message_key(text),
        source_text=text,
        origins=[origin],
        protected=protected,
    )


def _matches(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.fullmatch(text) for pattern in patterns)


def _is_boilerplate(text: str) -> bool:
    """Strings that are in the resource but are not language."""
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) == 1 and not stripped.isalpha():
        return True
    return bool(_NOT_WORDS.match(stripped))


def _read_text(path: Path, encoding: str) -> str:
    """Read a resource script, falling back the way the resource compiler does."""
    try:
        return path.read_text(encoding=encoding)
    except FileNotFoundError as exc:
        raise SourceError(f"{path} does not exist") from exc
    except UnicodeDecodeError:
        pass

    for fallback in ("utf-16", "cp1252"):
        try:
            return path.read_text(encoding=fallback)
        except (UnicodeDecodeError, UnicodeError):
            continue

    raise SourceError(f"{path} is not readable as {encoding}, UTF-16 or cp1252")
