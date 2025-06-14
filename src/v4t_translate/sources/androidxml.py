"""V4T-Mobile's ``res/values/strings.xml``.

Android's string resources look simple and are not. The escaping rules are
their own thing, ``translatable="false"`` is load bearing, and plurals and
string arrays hold several strings under one name.

What this reader has to get right:

Apostrophes and quotes are backslash escaped, and a string starting or ending
with a space has to be wrapped in double quotes or Android trims it. Reading
the raw text and handing it to a translator would show them the backslashes.

``translatable="false"`` marks strings the Android build refuses to localise.
Those are protected here for the same reason.

``%1$s`` is the normal placeholder style, which the placeholder rule already
treats as reorderable. Nothing extra needed, but it is why that support
exists.

Plurals and arrays get one message per item, keyed with the quantity or the
index appended to the name, because a translator needs to see them apart.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

from ..catalog.ids import message_key
from ..catalog.model import Message, Origin, OriginKind
from ..errors import ParseError, SourceError
from .base import Extraction, SourceOptions
from .notes import Note, collect_notes

__all__ = ["AndroidXmlSource", "unescape_android", "escape_android"]

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "'": "'",
    '"': '"',
    "\\": "\\",
    "@": "@",
    "?": "?",
}

_NEEDS_ESCAPE = re.compile(r"(['\"\\])")


def unescape_android(text: str) -> str:
    """Resolve Android's escaping and its surrounding-quote convention."""
    stripped = text.strip("\n")

    # A quoted value keeps its whitespace exactly. An unquoted one has its
    # whitespace collapsed, which is what the platform does and what makes a
    # caption the developer wrapped over two source lines come out as one.
    quoted = len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"'
    stripped = stripped[1:-1] if quoted else " ".join(stripped.split())

    out: list[str] = []
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= len(stripped):
            out.append("\\")
            break
        out.append(_ESCAPES.get(stripped[index], stripped[index]))
        index += 1

    return "".join(out)


def escape_android(text: str) -> str:
    """Put a translated string back into the form Android's parser wants."""
    escaped = _NEEDS_ESCAPE.sub(r"\\\1", text)
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
    if escaped != escaped.strip():
        return f'"{escaped}"'
    return escaped


class AndroidXmlSource:
    """Reader for Android string resources."""

    kind = "androidxml"

    def __init__(self) -> None:
        self.notes: dict[str, Note] = {}

    def extract(self, options: SourceOptions) -> Extraction:
        source = options.relative()
        extraction = Extraction(source=source)

        root = self._parse(options.path, source)
        protected = [re.compile(p) for p in options.protected_patterns]

        # ElementTree throws comments away, so the notes come from a second
        # pass over the raw text. The elements do not carry line numbers
        # either, so they are matched by resource name instead: a comment
        # applies to the next <string name="..."> below it.
        self.notes = _notes_by_name(options.path)

        for element in root:
            handler = {
                "string": self._string,
                "plurals": self._plurals,
                "string-array": self._array,
            }.get(element.tag)

            if handler is None:
                continue

            name = element.get("name")
            if not name:
                extraction.warn(f"{source}: a <{element.tag}> with no name, skipped")
                continue

            handler(element, name, source, protected, extraction)

        extraction.stats = {
            "strings": sum(1 for e in root if e.tag == "string"),
            "plurals": sum(1 for e in root if e.tag == "plurals"),
            "arrays": sum(1 for e in root if e.tag == "string-array"),
            "messages": len(extraction.by_key()),
        }
        return extraction

    def _string(self, element, name, source, protected, extraction) -> None:
        self._add(extraction, element, name, name, source, protected)

    def _plurals(self, element, name, source, protected, extraction) -> None:
        for item in element.findall("item"):
            quantity = item.get("quantity", "other")
            self._add(extraction, item, name, f"{name}[{quantity}]", source, protected,
                      parent=element)

    def _array(self, element, name, source, protected, extraction) -> None:
        for index, item in enumerate(element.findall("item")):
            self._add(extraction, item, name, f"{name}[{index}]", source, protected,
                      parent=element)

    def _add(self, extraction, element, container, symbol, source, protected,
             parent=None) -> None:
        text = unescape_android(_inner_text(element))
        if not text:
            return

        owner = parent if parent is not None else element
        untranslatable = owner.get("translatable", "true").lower() == "false"

        note = self.notes.get(container)
        context = note.context if note and note.context else None

        message = Message(
            key=message_key(text, context),
            source_text=text,
            context=context,
            origins=[Origin(source=source, kind=OriginKind.ANDROID_STRING,
                            container=container, symbol=symbol)],
            protected=untranslatable or any(p.fullmatch(text) for p in protected),
        )

        parts = [note.text] if note and note.text else []
        if untranslatable:
            parts.append('Marked translatable="false" in the resource.')
        message.developer_note = " ".join(parts) or None

        extraction.messages.append(message)

    @staticmethod
    def _parse(path: Path, source: str):
        try:
            tree = ElementTree.parse(path)
        except FileNotFoundError as exc:
            raise SourceError(f"{path} does not exist") from exc
        except ElementTree.ParseError as exc:
            line, column = getattr(exc, "position", (0, 0))
            raise ParseError(str(exc), path=source, line=line, column=column) from exc

        root = tree.getroot()
        if root.tag != "resources":
            raise ParseError(
                f"root element is <{root.tag}>, expected <resources>", path=source
            )
        return root


#: The name attribute of a string, plurals or string-array element.
_NAMED = re.compile(r'<(?:string|plurals|string-array)\s[^>]*name="([^"]+)"')


def _notes_by_name(path: Path) -> dict[str, Note]:
    """Marked comments, keyed by the resource they sit above."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    index = collect_notes(text)
    if not index:
        return {}

    lines = text.splitlines()
    found: dict[str, Note] = {}

    for line, note in index.by_line.items():
        match = _NAMED.search(lines[line - 1]) if line <= len(lines) else None
        if match is not None:
            found[match.group(1)] = note

    return found


def _inner_text(element) -> str:
    """Element text including any inline markup, which Android allows."""
    parts = [element.text or ""]
    for child in element:
        parts.append(ElementTree.tostring(child, encoding="unicode"))
    return "".join(parts)
