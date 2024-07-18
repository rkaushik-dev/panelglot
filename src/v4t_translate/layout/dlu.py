"""Dialog units to pixels.

A resource script lays out controls in dialog units, and a dialog unit is not
a length. It is a fraction of the average character size of the dialog's own
font: four horizontal units to one average character width, eight vertical
units to one character height. Change the font and every control on the dialog
changes size, which is the entire reason a dialog that is comfortable in
English is too small in German.

The trap this module exists for is ``MS Shell Dlg``. It is not a font. It is a
alias the system resolves to whatever the *current UI language* uses, so the
same resource is laid out with Tahoma on an English machine and PMingLiU on a
Traditional Chinese one. Those have different base units. A control that is
100 units wide is 150 pixels in one case and 175 in the other, and the string
inside it grew as well.

Numbers here are measured at 96 DPI against the fonts actually installed on
the panel PCs, not computed. GetDialogBaseUnits rounds in a way that is easier
to look up than to reproduce.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DialogBaseUnits",
    "SHELL_DLG_ALIASES",
    "base_units_for",
    "resolve_shell_font",
]


@dataclass(frozen=True)
class DialogBaseUnits:
    """Average character cell of a dialog font, in pixels."""

    x: int
    """Average character width. Four dialog units."""

    y: int
    """Character height. Eight dialog units."""

    def x_to_pixels(self, dlu: int) -> int:
        """Horizontal dialog units to pixels, rounding the way USER32 does."""
        return (dlu * self.x + 2) // 4

    def y_to_pixels(self, dlu: int) -> int:
        """Vertical dialog units to pixels."""
        return (dlu * self.y + 4) // 8

    def pixels_to_x(self, pixels: int) -> int:
        """Pixels back to horizontal dialog units, rounding down.

        Rounding down is deliberate: this is used to answer "how many units
        would I need", and a budget that rounds up is a budget that overflows.
        """
        return (pixels * 4) // self.x

    def pixels_to_y(self, pixels: int) -> int:
        return (pixels * 8) // self.y


#: What ``MS Shell Dlg`` and ``MS Shell Dlg 2`` actually resolve to, per
#: locale. Keyed on the language part of the tag because the script decides
#: this, not the region.
SHELL_DLG_ALIASES: dict[str, str] = {
    "en": "Tahoma",
    "de": "Tahoma",
    "fr": "Tahoma",
    "es": "Tahoma",
    "it": "Tahoma",
    "pt": "Tahoma",
    "pl": "Tahoma",
    "cs": "Tahoma",
    "tr": "Tahoma",
    "ru": "Tahoma",
    "vi": "Tahoma",
    "th": "Tahoma",
    "ar": "Tahoma",
    "he": "Tahoma",
    "zh-TW": "PMingLiU",
    "zh-HK": "PMingLiU",
    "zh-CN": "SimSun",
    "ja": "MS UI Gothic",
    "ko": "Gulim",
}

#: Measured base units at 96 DPI. Key is ``(font name lowered, point size)``.
_MEASURED: dict[tuple[str, int], DialogBaseUnits] = {
    ("system", 0): DialogBaseUnits(8, 16),
    ("ms sans serif", 8): DialogBaseUnits(6, 13),
    ("ms sans serif", 10): DialogBaseUnits(8, 16),
    ("tahoma", 8): DialogBaseUnits(6, 13),
    ("tahoma", 9): DialogBaseUnits(7, 15),
    ("tahoma", 10): DialogBaseUnits(8, 16),
    ("segoe ui", 9): DialogBaseUnits(7, 15),
    ("segoe ui", 10): DialogBaseUnits(8, 17),
    ("pmingliu", 8): DialogBaseUnits(7, 15),
    ("pmingliu", 9): DialogBaseUnits(7, 16),
    ("simsun", 8): DialogBaseUnits(7, 15),
    ("simsun", 9): DialogBaseUnits(7, 16),
    ("gulim", 9): DialogBaseUnits(7, 16),
    ("ms ui gothic", 9): DialogBaseUnits(7, 16),
    ("courier new", 8): DialogBaseUnits(6, 13),
    ("fixedsys", 9): DialogBaseUnits(8, 15),
}

#: Used when the font is not in the table at all.
_FALLBACK = DialogBaseUnits(6, 13)


def resolve_shell_font(font_name: str, locale_tag: str | None) -> str:
    """Turn ``MS Shell Dlg`` into the font the target locale will really use.

    Any other font name is returned unchanged, because a resource that names a
    real font gets that font on every machine.
    """
    normalized = font_name.strip().lower()
    if normalized not in ("ms shell dlg", "ms shell dlg 2"):
        return font_name

    if not locale_tag:
        return SHELL_DLG_ALIASES["en"]

    if locale_tag in SHELL_DLG_ALIASES:
        return SHELL_DLG_ALIASES[locale_tag]

    language = locale_tag.split("-")[0]
    return SHELL_DLG_ALIASES.get(language, SHELL_DLG_ALIASES["en"])


def base_units_for(font_name: str, point_size: int, *, locale_tag: str | None = None
                   ) -> DialogBaseUnits:
    """Base units for a dialog drawn in ``font_name`` at ``point_size``.

    ``locale_tag`` only matters for the shell alias. Pass it whenever you know
    it: leaving it out silently measures the English layout, which is the
    layout that was never the problem.
    """
    resolved = resolve_shell_font(font_name, locale_tag).strip().lower()

    exact = _MEASURED.get((resolved, point_size))
    if exact is not None:
        return exact

    nearest = _nearest_size(resolved, point_size)
    if nearest is not None:
        return nearest

    return _scaled_fallback(point_size)


def _nearest_size(font: str, point_size: int) -> DialogBaseUnits | None:
    """Closest measured size for a font we know, scaled to the size asked for."""
    sizes = [size for (name, size) in _MEASURED if name == font and size > 0]
    if not sizes:
        return None

    closest = min(sizes, key=lambda size: (abs(size - point_size), size))
    measured = _MEASURED[(font, closest)]
    if closest == point_size:
        return measured

    return DialogBaseUnits(
        x=max(1, round(measured.x * point_size / closest)),
        y=max(1, round(measured.y * point_size / closest)),
    )


def _scaled_fallback(point_size: int) -> DialogBaseUnits:
    if point_size <= 0:
        return _FALLBACK
    return DialogBaseUnits(
        x=max(1, round(_FALLBACK.x * point_size / 8)),
        y=max(1, round(_FALLBACK.y * point_size / 8)),
    )
