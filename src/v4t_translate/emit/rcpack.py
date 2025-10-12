"""Writing a localised resource script.

The output is the English file with the translated strings spliced in and
every other byte left exactly as it was. That is deliberate and it costs
something to keep.

Regenerating the file from the parse tree would be easier and would be wrong.
The parser understands the constructs that hold text and treats the rest as
opaque, so a regenerated file would lose the version block, the toolbar, the
dialog layout resources and every comment. Splicing means the diff between the
English file and the German one is exactly the strings, which is what the
person reviewing it wants to see, and it means the parts we do not understand
cannot be damaged by the parts we do.

Two things do get rewritten beyond the strings. The LANGUAGE statement,
because the resource compiler keys the localised block on it. And the dialog
font, because a Traditional Chinese dialog laid out in Tahoma renders in a
fallback font at the wrong size.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..catalog.ids import message_key
from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..errors import EmitError
from ..layout.dlu import resolve_shell_font
from ..layout.mirror import mirrored_exstyles, render_exstyle
from ..sources.rc.ast import ResourceScript
from ..sources.rc.lexer import quote_rc_string
from ..sources.rc.parser import parse_resource_script
from .base import EmitOptions, EmitResult

__all__ = ["RcEmitter", "splice"]


@dataclass(order=True)
class _Replacement:
    """One span of the source to swap out."""

    start: int
    end: int
    text: str


def splice(source: str, replacements: list[_Replacement]) -> str:
    """Apply replacements to ``source``, right to left.

    Right to left so earlier offsets stay valid. Overlapping replacements are
    an error rather than a last-one-wins, because an overlap means the parse
    produced two spans for one piece of text and the output would be silently
    mangled.
    """
    ordered = sorted(replacements, reverse=True)

    previous_start = len(source) + 1
    for item in ordered:
        if item.end > previous_start:
            raise EmitError(
                f"replacements overlap at offset {item.start}, which means the "
                f"parse produced two spans for one string"
            )
        previous_start = item.start

    out = source
    for item in ordered:
        out = out[: item.start] + item.text + out[item.end :]
    return out


class RcEmitter:
    """Writes a localised copy of a resource script."""

    kind = "rc"

    def emit(self, catalog: Catalog, translations: TranslationSet,
             options: EmitOptions) -> EmitResult:
        if options.source_path is None:
            raise EmitError("the rc emitter needs source_path, the English .rc to localise")

        result = EmitResult(path=options.path)
        script = self._parse(options.source_path)

        replacements: list[_Replacement] = []
        self._collect(script, catalog, translations, options, result, replacements)
        self._retarget(script, catalog, options, replacements)

        text = splice(script.text, replacements)
        self._write(text, options, result)
        return result

    # -- collecting -----------------------------------------------------

    def _collect(self, script: ResourceScript, catalog: Catalog,
                 translations: TranslationSet, options: EmitOptions,
                 result: EmitResult, out: list[_Replacement]) -> None:
        for dialog in script.dialogs:
            if dialog.caption and dialog.caption_span:
                self._one(dialog.caption, dialog.caption_span, catalog, translations,
                          options, result, out)
            for control in dialog.controls:
                if control.caption and control.caption_span:
                    self._one(control.caption, control.caption_span, catalog,
                              translations, options, result, out)

        for entry in script.string_entries():
            if entry.span:
                self._one(entry.text, entry.span, catalog, translations, options,
                          result, out)

        for item in script.menu_items():
            if item.text and item.span:
                self._one(item.text, item.span, catalog, translations, options,
                          result, out)

        for value in script.version_values():
            if value.text and value.span:
                self._one(value.text, value.span, catalog, translations, options,
                          result, out)

    def _one(self, source_text: str, span: tuple[int, int], catalog: Catalog,
             translations: TranslationSet, options: EmitOptions, result: EmitResult,
             out: list[_Replacement]) -> None:
        key = message_key(source_text)

        if key not in catalog.messages:
            # In the source but not in the catalog, which means extraction
            # dropped it: a caption that is only punctuation, usually.
            result.skipped.append(key)
            return

        translation = translations.get(key)

        if translation.text:
            out.append(_Replacement(span[0], span[1], quote_rc_string(translation.text)))
            result.written += 1
            return

        result.fell_back.append(key)
        if not options.fallback_to_source:
            out.append(_Replacement(span[0], span[1], '""'))

    def _retarget(self, script: ResourceScript, catalog: Catalog, options: EmitOptions,
                  out: list[_Replacement]) -> None:
        """Swap the LANGUAGE statement and the dialog font for this locale.

        The font is only pinned when the shell alias would resolve to a
        different family than it does for the source language. German gets
        Tahoma from ``MS Shell Dlg`` exactly as English does, so writing
        Tahoma into the German file changes nothing and adds a line to every
        dialog in the diff. Traditional Chinese gets PMingLiU, which is a real
        difference and worth pinning.
        """
        if script.language_span:
            out.append(
                _Replacement(script.language_span[0], script.language_span[1],
                             options.locale.language_statement)
            )

        if options.locale.rtl:
            self._mirror(script, out)

        for dialog in script.dialogs:
            if not dialog.font_span:
                continue
            source_font = resolve_shell_font(dialog.font_name, catalog.source_locale)
            target_font = resolve_shell_font(dialog.font_name, options.locale.tag)
            if target_font == source_font:
                continue
            out.append(
                _Replacement(dialog.font_span[0], dialog.font_span[1],
                             quote_rc_string(target_font))
            )

    @staticmethod
    def _mirror(script: ResourceScript, out: list[_Replacement]) -> None:
        """Turn every dialog round for a right to left language.

        Two extended styles rather than mirrored coordinates. Coordinates in
        the file would have to be recomputed every time somebody drags a
        control in the English dialog, and the day that is forgotten the two
        drift apart quietly. These two words stay correct.

        A dialog with an EXSTYLE already has its line rewritten, keeping what
        was there. A dialog with none gets one inserted just after its header,
        which is where the dialog editor puts it.
        """
        for dialog in script.dialogs:
            line = render_exstyle(mirrored_exstyles(dialog.exstyles))

            if dialog.exstyle_span is not None:
                out.append(_Replacement(dialog.exstyle_span[0],
                                        dialog.exstyle_span[1], line))
            elif dialog.header_end:
                out.append(_Replacement(dialog.header_end, dialog.header_end,
                                        "\n" + line))

    # -- files ----------------------------------------------------------

    @staticmethod
    def _parse(path: Path) -> ResourceScript:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as exc:
            raise EmitError(f"{path} does not exist") from exc
        except UnicodeDecodeError:
            text = path.read_text(encoding="cp1252")
        return parse_resource_script(text, path=str(path))

    @staticmethod
    def _write(text: str, options: EmitOptions, result: EmitResult) -> None:
        encoding = options.encoding or options.locale.python_codec

        try:
            data = text.encode(encoding)
        except UnicodeEncodeError as exc:
            bad = text[exc.start : exc.end]
            raise EmitError(
                f"{options.path}: {bad!r} cannot be written in {encoding}. "
                f"The encoding rule should have caught this before the build"
            ) from exc

        options.path.parent.mkdir(parents=True, exist_ok=True)
        options.path.write_bytes(data)
        result.bytes_written = len(data)
