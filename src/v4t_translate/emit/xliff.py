"""XLIFF 1.2 output, and reading the answers back.

Two of the agencies who do this work will not accept a spreadsheet. They want
XLIFF, and they want 1.2 rather than 2.0, because 1.2 is what the tools they
bought in 2013 read. That is the whole reason for the version choice and it is
not going to change soon.

Unlike PO this is a round trip. The file that comes back is the file that went
out with the target elements filled in, so it carries the keys, the notes and
the state, and there is nothing to match up by text. That is worth a reader:
the alternative is asking an agency to copy their own work into a spreadsheet,
which is where transcription errors come from.

What survives the trip:

The key is the ``trans-unit`` id. Not the control id, not the English. An
agency that renames things still cannot lose the mapping.

The state is written as an XLIFF state attribute and read back through the
same table. XLIFF has more states than we do, so the mapping is deliberately
lossy in one direction and safe in the other: anything unrecognised comes back
as needs-review rather than as approved.

``resname`` carries the origin. Some tools show it and it is the only thing
that tells a translator this string is a push button on the purge dialog.
"""

from __future__ import annotations

from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

from ..catalog.store import Catalog
from ..catalog.translations import Translation, TranslationSet, TranslationState
from ..errors import SourceError
from .base import EmitOptions, EmitResult

__all__ = [
    "XliffEmitter",
    "read_xliff",
    "XLIFF_NAMESPACE",
    "state_for",
    "state_from",
]

XLIFF_NAMESPACE = "urn:oasis:names:tc:xliff:document:1.2"

_DATATYPE = "winres"
"""What the source is. XLIFF has a name for Windows resources and this is it."""

#: Ours to theirs. Round trips for everything except do-not-translate, which
#: comes back as approved: XLIFF says that with an attribute on the unit
#: rather than with a state, and the unit is ours to write, not theirs.
_STATE_OUT = {
    TranslationState.EMPTY: "new",
    TranslationState.DRAFT: "needs-translation",
    TranslationState.NEEDS_REVIEW: "needs-review-translation",
    TranslationState.APPROVED: "final",
    TranslationState.DO_NOT_TRANSLATE: "final",
}

#: Theirs to ours. Everything not listed comes back as needs review, which is
#: the safe direction: a state we did not recognise must not become approved.
_STATE_IN = {
    "new": TranslationState.EMPTY,
    "needs-translation": TranslationState.DRAFT,
    "needs-l10n": TranslationState.DRAFT,
    "needs-review-translation": TranslationState.NEEDS_REVIEW,
    "needs-review-l10n": TranslationState.NEEDS_REVIEW,
    "needs-review-adaptation": TranslationState.NEEDS_REVIEW,
    "needs-adaptation": TranslationState.NEEDS_REVIEW,
    "translated": TranslationState.NEEDS_REVIEW,
    "signed-off": TranslationState.APPROVED,
    "final": TranslationState.APPROVED,
}


def state_for(state: TranslationState) -> str:
    """The XLIFF state attribute for one of ours."""
    return _STATE_OUT.get(state, "new")


def state_from(attribute: str | None) -> TranslationState:
    """One of ours for an XLIFF state attribute, safely."""
    if not attribute:
        return TranslationState.NEEDS_REVIEW
    return _STATE_IN.get(attribute.strip().lower(), TranslationState.NEEDS_REVIEW)


class XliffEmitter:
    """Writes an XLIFF 1.2 file, one file element, one body."""

    kind = "xliff"

    def emit(self, catalog: Catalog, translations: TranslationSet,
             options: EmitOptions) -> EmitResult:
        result = EmitResult(path=options.path)
        original = options.source_path.name if options.source_path else "catalog"

        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<xliff version="1.2" xmlns={quoteattr(XLIFF_NAMESPACE)}>',
            f"  <file original={quoteattr(original)} "
            f"datatype={quoteattr(_DATATYPE)} "
            f"source-language={quoteattr(catalog.source_locale)} "
            f"target-language={quoteattr(options.locale.tag)}>",
            "    <header>",
            f"      <tool tool-id=\"v4t-translate\" "
            f"tool-name={quoteattr(catalog.project)}/>",
            "    </header>",
            "    <body>",
        ]

        for key in catalog.sorted_keys():
            message = catalog.messages[key]
            translation = translations.get(key)
            lines.extend(self._unit(key, message, translation))

            if translation.text:
                result.written += 1
            else:
                result.skipped.append(key)

        lines.extend(["    </body>", "  </file>", "</xliff>"])

        options.path.parent.mkdir(parents=True, exist_ok=True)
        data = ("\n".join(lines) + "\n").encode("utf-8")
        options.path.write_bytes(data)
        result.bytes_written = len(data)
        return result

    def _unit(self, key: str, message, translation: Translation) -> list[str]:
        origin = message.primary_origin
        attributes = [f"id={quoteattr(key)}"]
        if origin is not None:
            attributes.append(f"resname={quoteattr(origin.describe())}")
        if message.protected:
            # translate="no" is the one attribute every tool honours. It grays
            # the row out, which is worth more than any note.
            attributes.append('translate="no"')
        if message.max_chars:
            attributes.append(f"maxwidth={quoteattr(str(message.max_chars))}")
            attributes.append('size-unit="char"')

        lines = [f"      <trans-unit {' '.join(attributes)}>"]
        lines.append(f"        <source>{escape(message.source_text)}</source>")
        lines.append(
            f"        <target state={quoteattr(state_for(translation.state))}>"
            f"{escape(translation.text)}</target>"
        )

        for note in self._notes(message, translation):
            lines.append(f"        <note>{escape(note)}</note>")

        lines.append("      </trans-unit>")
        return lines

    @staticmethod
    def _notes(message, translation: Translation) -> list[str]:
        notes: list[str] = []
        if message.developer_note:
            notes.append(message.developer_note)
        if message.context:
            notes.append(f"Context: {message.context}")
        if message.max_width_px:
            span = (f" over {message.max_lines} lines"
                    if message.max_lines > 1 else "")
            notes.append(f"Fits in {message.max_width_px} pixels{span}.")
        if translation.note:
            notes.append(translation.note)
        return notes


def read_xliff(text: str, *, path: str = "<xliff>") -> TranslationSet:
    """Read an XLIFF file an agency sent back.

    Only the target elements are read. The source elements in the returned
    file are theirs to have mangled, and comparing them against the catalog
    would turn every tool that normalises whitespace into a false alarm.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise SourceError(f"{path} is not valid XML: {exc}") from exc

    if _strip(root.tag) != "xliff":
        raise SourceError(f"{path}: root element is {_strip(root.tag)}, not xliff")

    files = [child for child in root if _strip(child.tag) == "file"]
    if not files:
        raise SourceError(f"{path}: no file element")

    tag = files[0].get("target-language") or ""
    result = TranslationSet(locale=tag)
    seen: set[str] = set()

    for unit in files[0].iter():
        if _strip(unit.tag) != "trans-unit":
            continue

        key = unit.get("id")
        if not key:
            raise SourceError(f"{path}: a trans-unit has no id")
        if key in seen:
            raise SourceError(f"{path}: duplicate trans-unit id {key!r}")
        seen.add(key)

        target = next((c for c in unit if _strip(c.tag) == "target"), None)
        if target is None:
            continue

        result.set(
            key,
            Translation(
                text=_text_of(target),
                state=state_from(target.get("state")),
                origin="xliff",
            ),
        )

    return result


def _strip(tag: str) -> str:
    """A tag without its namespace, because 1.2 files disagree about it."""
    return tag.rsplit("}", 1)[-1]


def _text_of(element) -> str:
    """The text of a target, ignoring inline markup.

    A tool that turned a placeholder into a ``<ph>`` element leaves the text
    around it, and dropping the element rather than the text is the least
    wrong thing available. The placeholders rule catches what that loses.
    """
    return "".join(element.itertext())
