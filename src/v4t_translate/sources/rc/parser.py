"""Parser for the translatable part of a resource script.

Reads dialogs, string tables and menus into the nodes in :mod:`.ast`, and
skips everything else without complaining about it. That last part is not
laziness. ``V4T.rc`` contains a VERSIONINFO block, three TEXTINCLUDE blocks,
an AFX_DIALOG_LAYOUT for every dialog and a toolbar, none of which hold text
anybody translates, and all of which have their own grammar. Reading them
properly would be a lot of code that can only ever cause failures.

Statement boundaries come from line numbers rather than newline tokens. A
control statement runs to the end of its line unless the next line starts with
something that is clearly not a new statement, which is how the dialog editor
wraps a long style list.
"""

from __future__ import annotations

from ...errors import ParseError
from .ast import (
    Control,
    Dialog,
    Menu,
    MenuItem,
    RawBlock,
    ResourceScript,
    StringEntry,
    StringTable,
)
from .lexer import tokenize
from .tokens import (
    CAPTIONED_CONTROLS,
    GENERIC_CONTROL,
    RESOURCE_KEYWORDS,
    UNCAPTIONED_CONTROLS,
    Token,
    TokenKind,
)

__all__ = ["parse_resource_script", "parse"]

#: Everything that can start a statement inside a dialog block.
_CONTROL_STATEMENTS = CAPTIONED_CONTROLS | UNCAPTIONED_CONTROLS | {GENERIC_CONTROL}

#: Dialog attributes that sit between the header line and BEGIN.
_DIALOG_ATTRIBUTES = frozenset(
    {"STYLE", "EXSTYLE", "CAPTION", "FONT", "MENU", "CLASS", "CHARACTERISTICS",
     "VERSION", "LANGUAGE"}
)

#: Window classes a ``CONTROL`` statement can name whose first argument is
#: text rather than a resource id. Anything else is a bitmap or an icon.
_TEXT_BEARING_CLASSES = frozenset({"BUTTON", "STATIC", "MSCTLS_UPDOWN32"})


class _Parser:
    def __init__(self, tokens: list[Token], path: str, text: str = "") -> None:
        self.tokens = tokens
        self.path = path
        self.index = 0
        self.script = ResourceScript(path=path, text=text)

    # -- cursor ---------------------------------------------------------

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> Token:
        index = min(self.index + offset, len(self.tokens) - 1)
        return self.tokens[index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        if token.kind is not TokenKind.EOF:
            self.index += 1
        return token

    def at_end(self) -> bool:
        return self.current.kind is TokenKind.EOF

    def expect(self, kind: TokenKind) -> Token:
        if self.current.kind is not kind:
            raise self.fail(f"expected {kind}, found {self.current.kind}")
        return self.advance()

    def fail(self, message: str) -> ParseError:
        token = self.current
        return ParseError(message, path=self.path, line=token.line, column=token.column)

    # -- top level ------------------------------------------------------

    def parse(self) -> ResourceScript:
        while not self.at_end():
            token = self.current

            if token.kind is TokenKind.DIRECTIVE:
                self.script.directives.append(self.advance().text)
                continue

            if token.is_ident("LANGUAGE"):
                self.parse_language()
                continue

            if token.is_ident("STRINGTABLE"):
                self.script.string_tables.append(self.parse_string_table())
                continue

            self.parse_named_resource()

        return self.script

    def parse_language(self) -> None:
        start = self.advance()
        parts: list[str] = [start.text.upper()]
        end = start.end
        while self.current.line == start.line and not self.at_end():
            token = self.advance()
            parts.append(token.text)
            end = token.end
        # Rejoin so the result matches Locale.language_statement exactly, which
        # is what the writer compares against when it swaps the language line.
        self.script.language = " ".join(parts).replace(" ,", ",")
        self.script.language_span = (start.start, end)

    def parse_named_resource(self) -> None:
        """Handle ``<name> <STATEMENT> ...``, the shape of every other resource."""
        name_token = self.advance()
        if name_token.kind not in (TokenKind.IDENT, TokenKind.NUMBER):
            raise ParseError(
                f"expected a resource name, found {name_token.kind}",
                path=self.path,
                line=name_token.line,
                column=name_token.column,
            )

        if self.current.kind is not TokenKind.IDENT:
            raise self.fail(f"expected a resource type after {name_token.text}")

        statement = self.advance()
        upper = statement.text.upper()

        if upper in ("DIALOG", "DIALOGEX"):
            self.script.dialogs.append(self.parse_dialog(name_token.text, statement))
        elif upper in ("MENU", "MENUEX"):
            self.script.menus.append(self.parse_menu(name_token.text, statement))
        else:
            self.script.raw_blocks.append(self.skip_resource(name_token.text, statement))

    def skip_resource(self, name: str, statement: Token) -> RawBlock:
        """Consume a resource we do not read, keeping a note of what it was.

        The end is wherever the next top-level resource starts, which is the
        only boundary that holds for every construct here. A VERSIONINFO puts
        four attribute lines before its ``BEGIN`` and an ICON has no body at
        all, so neither "one line" nor "always a block" is right.
        """
        pieces: list[str] = [name, statement.text]
        line = statement.line

        while not self.at_end():
            token = self.current
            if token.kind is TokenKind.BEGIN:
                pieces.append(self.skip_block())
                break
            if token.line != line and self.starts_top_level_resource(token):
                break
            pieces.append(self.advance().text)
            line = token.line

        return RawBlock(symbol=name, statement=statement.text, text=" ".join(pieces),
                        line=statement.line)

    def starts_top_level_resource(self, token: Token) -> bool:
        """True when ``token`` opens a new top-level resource declaration."""
        if token.kind is TokenKind.DIRECTIVE:
            return True
        if token.is_ident("LANGUAGE", "STRINGTABLE"):
            return True
        if token.kind not in (TokenKind.IDENT, TokenKind.NUMBER):
            return False
        following = self.peek(1)
        return (
            following.kind is TokenKind.IDENT
            and following.text.upper() in RESOURCE_KEYWORDS
        )

    def skip_block(self) -> str:
        """Consume a balanced ``BEGIN``/``END`` pair, returning its text."""
        depth = 0
        pieces: list[str] = []
        while not self.at_end():
            token = self.advance()
            pieces.append(token.text)
            if token.kind is TokenKind.BEGIN:
                depth += 1
            elif token.kind is TokenKind.END:
                depth -= 1
                if depth == 0:
                    return " ".join(pieces)
        raise self.fail("unterminated BEGIN block")

    # -- string tables --------------------------------------------------

    def parse_string_table(self) -> StringTable:
        start = self.advance()
        table = StringTable(line=start.line)

        # STRINGTABLE may carry DISCARDABLE and a CHARACTERISTICS line.
        while not self.at_end() and self.current.kind is not TokenKind.BEGIN:
            if self.current.kind is TokenKind.EOF:
                raise self.fail("STRINGTABLE without a body")
            self.advance()

        self.expect(TokenKind.BEGIN)

        while self.current.kind is not TokenKind.END:
            if self.at_end():
                raise self.fail("unterminated STRINGTABLE")

            symbol_token = self.advance()
            if symbol_token.kind not in (TokenKind.IDENT, TokenKind.NUMBER):
                raise ParseError(
                    f"expected a string id, found {symbol_token.kind}",
                    path=self.path,
                    line=symbol_token.line,
                    column=symbol_token.column,
                )

            if self.current.kind is TokenKind.COMMA:
                self.advance()

            text, span = self.read_joined_string()
            table.entries.append(
                StringEntry(symbol=symbol_token.text, text=text,
                            line=symbol_token.line, span=span)
            )

        self.expect(TokenKind.END)
        return table

    def read_joined_string(self) -> tuple[str, tuple[int, int]]:
        """Read one or more adjacent string literals as a single value.

        Long messages are written across several lines in the source and the
        resource compiler concatenates them. Doing it here means the catalog
        never sees the line breaks the author used for readability.

        The span runs from the first quote to the last, so rewriting it
        replaces the whole run with one literal. The wrapping the author chose
        is lost, which is the right trade: it was chosen for the English.
        """
        if self.current.kind is not TokenKind.STRING:
            raise self.fail(f"expected a string, found {self.current.kind}")

        parts: list[str] = []
        start = self.current.start
        end = self.current.end
        while self.current.kind is TokenKind.STRING:
            token = self.advance()
            parts.append(str(token.value))
            end = token.end
        return "".join(parts), (start, end)

    # -- dialogs --------------------------------------------------------

    def parse_dialog(self, name: str, statement: Token) -> Dialog:
        dialog = Dialog(symbol=name, statement=statement.text.upper(), line=statement.line)

        geometry = self.read_line_numbers(statement.line)
        for attribute, value in zip(("x", "y", "width", "height"), geometry, strict=False):
            setattr(dialog, attribute, value)

        while (self.current.kind is TokenKind.IDENT
               and self.current.text.upper() in _DIALOG_ATTRIBUTES):
            self.parse_dialog_attribute(dialog)

        self.expect(TokenKind.BEGIN)

        ordinal = 0
        while self.current.kind is not TokenKind.END:
            if self.at_end():
                raise self.fail(f"unterminated dialog {name}")
            control = self.parse_control(ordinal)
            if control is not None:
                dialog.controls.append(control)
                ordinal += 1

        self.expect(TokenKind.END)
        return dialog

    def parse_dialog_attribute(self, dialog: Dialog) -> None:
        keyword = self.advance()
        upper = keyword.text.upper()
        arguments = self.read_statement_arguments(keyword.line)

        if upper == "CAPTION" and arguments and arguments[0].kind is TokenKind.STRING:
            dialog.caption = str(arguments[0].value)
            dialog.caption_span = arguments[0].span
        elif upper == "FONT":
            self.apply_font(dialog, arguments)
        elif upper == "STYLE":
            dialog.styles = [t.text for t in arguments if t.kind is TokenKind.IDENT]

    @staticmethod
    def apply_font(dialog: Dialog, arguments: list[Token]) -> None:
        """``FONT 8, "MS Shell Dlg", 400, 0, 0x1``. Only the first two matter."""
        for token in arguments:
            if token.kind is TokenKind.NUMBER and isinstance(token.value, int):
                dialog.font_size = token.value
                break
        for token in arguments:
            if token.kind is TokenKind.STRING:
                dialog.font_name = str(token.value)
                dialog.font_span = token.span
                break

    def parse_control(self, ordinal: int) -> Control | None:
        keyword = self.advance()
        if keyword.kind is not TokenKind.IDENT:
            raise ParseError(
                f"expected a control statement, found {keyword.kind}",
                path=self.path,
                line=keyword.line,
                column=keyword.column,
            )

        statement = keyword.text.upper()
        groups = self.split_arguments(self.read_statement_arguments(keyword.line))

        if statement in CAPTIONED_CONTROLS:
            return self.build_captioned(keyword, statement, groups, ordinal)
        if statement == GENERIC_CONTROL:
            return self.build_generic(keyword, statement, groups, ordinal)
        return self.build_plain(keyword, statement, groups, ordinal)

    def build_captioned(self, keyword: Token, statement: str,
                        groups: list[list[Token]], ordinal: int) -> Control:
        """``LTEXT "text", id, x, y, cx, cy [, style [, exstyle]]``."""
        caption = _string_of(groups, 0)
        if caption is None:
            raise ParseError(
                f"{statement} without a caption",
                path=self.path,
                line=keyword.line,
                column=keyword.column,
            )
        control = Control(
            statement=keyword.text,
            symbol=_text_of(groups, 1),
            caption=caption,
            caption_span=_span_of(groups, 0),
            line=keyword.line,
            ordinal=ordinal,
        )
        _apply_geometry(control, groups, first=2)
        control.styles = _styles_from(groups, 6)
        return control

    def build_generic(self, keyword: Token, statement: str,
                      groups: list[list[Token]], ordinal: int) -> Control:
        """``CONTROL "text", id, "class", style, x, y, cx, cy [, exstyle]``."""
        window_class = _string_of(groups, 2)
        caption = _string_of(groups, 0)
        if window_class and window_class.upper() not in _TEXT_BEARING_CLASSES:
            # A CONTROL over SysListView32 or a bitmap carries an id here,
            # not a caption, and translating it would corrupt the resource.
            caption = None
        control = Control(
            statement=keyword.text,
            symbol=_text_of(groups, 1),
            caption=caption,
            caption_span=_span_of(groups, 0) if caption is not None else None,
            window_class=window_class,
            line=keyword.line,
            ordinal=ordinal,
        )
        control.styles = _styles_from(groups, 3, single_group=True)
        _apply_geometry(control, groups, first=4)
        return control

    def build_plain(self, keyword: Token, statement: str,
                    groups: list[list[Token]], ordinal: int) -> Control:
        """``EDITTEXT id, x, y, cx, cy [, style]`` and the other textless ones."""
        control = Control(
            statement=keyword.text,
            symbol=_text_of(groups, 0),
            line=keyword.line,
            ordinal=ordinal,
        )
        _apply_geometry(control, groups, first=1)
        control.styles = _styles_from(groups, 5)
        return control

    # -- menus ----------------------------------------------------------

    def parse_menu(self, name: str, statement: Token) -> Menu:
        menu = Menu(symbol=name, line=statement.line)
        while not self.at_end() and self.current.line == statement.line:
            self.advance()
        self.expect(TokenKind.BEGIN)
        menu.items = self.parse_menu_body()
        self.expect(TokenKind.END)
        return menu

    def parse_menu_body(self) -> list[MenuItem]:
        items: list[MenuItem] = []
        while self.current.kind is not TokenKind.END:
            if self.at_end():
                raise self.fail("unterminated menu")
            items.append(self.parse_menu_item())
        return items

    def parse_menu_item(self) -> MenuItem:
        keyword = self.advance()

        if keyword.is_ident("POPUP"):
            text, span = self.read_joined_string()
            self.read_statement_arguments(keyword.line)
            item = MenuItem(text=text, is_popup=True, line=keyword.line, span=span)
            self.expect(TokenKind.BEGIN)
            item.children = self.parse_menu_body()
            self.expect(TokenKind.END)
            return item

        if not keyword.is_ident("MENUITEM"):
            raise ParseError(
                f"expected MENUITEM or POPUP, found {keyword.text!r}",
                path=self.path,
                line=keyword.line,
                column=keyword.column,
            )

        if self.current.is_ident("SEPARATOR"):
            self.advance()
            return MenuItem(text=None, is_separator=True, line=keyword.line)

        text, span = self.read_joined_string()
        groups = self.split_arguments(self.read_statement_arguments(keyword.line))
        symbol = _text_of(groups, 0) or None
        return MenuItem(text=text, symbol=symbol, line=keyword.line, span=span)

    # -- statement helpers ----------------------------------------------

    def read_line_numbers(self, line: int) -> list[int]:
        """Read the integers on the rest of a header line."""
        values: list[int] = []
        for token in self.read_statement_arguments(line):
            if token.kind is TokenKind.NUMBER and isinstance(token.value, int):
                values.append(token.value)
        return values

    def read_statement_arguments(self, line: int) -> list[Token]:
        """Read the tokens belonging to a statement that started on ``line``.

        A statement normally ends at the end of its line. It continues onto
        the next when the line ends mid-list, which the dialog editor does for
        long style expressions, so continuation is detected by looking at what
        the next line starts with rather than by counting lines.
        """
        arguments: list[Token] = []
        while not self.at_end():
            token = self.current
            if token.kind in (TokenKind.BEGIN, TokenKind.END, TokenKind.DIRECTIVE):
                break
            if token.line != line and self.starts_new_statement(token, arguments):
                break
            arguments.append(self.advance())
            line = token.line
        return arguments

    def starts_new_statement(self, token: Token, collected: list[Token]) -> bool:
        """Decide whether ``token`` on a fresh line belongs to the next statement."""
        if collected and collected[-1].kind in (TokenKind.COMMA, TokenKind.PIPE):
            return False
        if token.kind is not TokenKind.IDENT:
            return True
        # Anything else is a bare identifier on its own line inside a dialog,
        # which is a style token that wrapped, so keep reading.
        upper = token.text.upper()
        return (
            upper in _CONTROL_STATEMENTS
            or upper in _DIALOG_ATTRIBUTES
            or upper in ("MENUITEM", "POPUP", "STRINGTABLE")
        )

    @staticmethod
    def split_arguments(tokens: list[Token]) -> list[list[Token]]:
        """Split an argument token list on top-level commas."""
        groups: list[list[Token]] = []
        current: list[Token] = []
        depth = 0
        for token in tokens:
            if token.kind is TokenKind.LPAREN:
                depth += 1
            elif token.kind is TokenKind.RPAREN:
                depth -= 1
            if token.kind is TokenKind.COMMA and depth == 0:
                groups.append(current)
                current = []
                continue
            current.append(token)
        groups.append(current)
        return [g for g in groups if g] if any(groups) else []


def _string_of(groups: list[list[Token]], index: int) -> str | None:
    if index >= len(groups):
        return None
    group = groups[index]
    if group and group[0].kind is TokenKind.STRING:
        return "".join(str(t.value) for t in group if t.kind is TokenKind.STRING)
    return None


def _span_of(groups: list[list[Token]], index: int) -> tuple[int, int] | None:
    """Offsets covering the string literals of one argument group."""
    if index >= len(groups):
        return None
    literals = [t for t in groups[index] if t.kind is TokenKind.STRING]
    if not literals:
        return None
    return (literals[0].start, literals[-1].end)


def _text_of(groups: list[list[Token]], index: int) -> str:
    if index >= len(groups):
        return ""
    return "".join(t.text for t in groups[index])


def _int_of(groups: list[list[Token]], index: int) -> int:
    if index >= len(groups):
        return 0
    total = 0
    sign = 1
    for token in groups[index]:
        if token.kind is TokenKind.MINUS:
            sign = -1
        elif token.kind is TokenKind.NUMBER and isinstance(token.value, int):
            total += sign * token.value
            sign = 1
    return total


def _apply_geometry(control: Control, groups: list[list[Token]], *, first: int) -> None:
    control.x = _int_of(groups, first)
    control.y = _int_of(groups, first + 1)
    control.width = _int_of(groups, first + 2)
    control.height = _int_of(groups, first + 3)


def _styles_from(groups: list[list[Token]], index: int, *, single_group: bool = False) -> list[str]:
    if index >= len(groups):
        return []
    selected = groups[index : index + 1] if single_group else groups[index:]
    styles: list[str] = []
    for group in selected:
        for token in group:
            if token.kind is TokenKind.IDENT:
                styles.append(token.text)
    return styles


def parse_resource_script(text: str, *, path: str = "<string>") -> ResourceScript:
    """Parse resource script text into a :class:`~.ast.ResourceScript`."""
    return _Parser(tokenize(text, path=path), path, text).parse()


#: Short alias used by the source registry.
parse = parse_resource_script
