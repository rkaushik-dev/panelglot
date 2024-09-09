"""The displays this product family draws on.

Five of them, and they disagree about everything: two are Windows machines
with real font rendering, one is a character LCD with a twenty by four grid,
one is a graphic OLED with a compiled bitmap font, and one is an Android
tablet with no constraint worth modelling.

A panel is what turns a message's constraint into a yes or a no. The rc
extractor already knows how wide a control is in pixels; the panel decides
whether pixels are even the right unit, and which font those pixels are
measured in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigError
from .font import FontMetrics, load_metrics, monospace

__all__ = ["Panel", "PANELS", "get_panel", "panel_names", "register_panel"]


@dataclass(frozen=True)
class Panel:
    """One display and what it can show."""

    name: str
    description: str

    width_px: int = 0
    height_px: int = 0

    columns: int = 0
    """Character columns, for fixed-grid displays. Zero for graphic panels."""

    rows: int = 0

    default_font: str = ""
    """Metrics file stem shipped with the firmware for this panel."""

    codepage: int | None = None
    """Codepage the panel's string table is encoded in, if it is 8-bit.

    ``None`` means the panel takes UTF-16 and any character the font holds.
    """

    supports_dbcs: bool = True
    """Whether the panel can show a double byte script at all."""

    forbidden: tuple[str, ...] = field(default_factory=tuple)
    """Characters the transport cannot carry, whatever the font holds."""

    @property
    def is_character_grid(self) -> bool:
        return self.columns > 0

    def char_budget(self) -> int | None:
        """Characters per line, or ``None`` on a graphic panel."""
        return self.columns or None

    def line_budget(self) -> int:
        """Lines available. One when the panel does not say."""
        return self.rows or 1

    def describe(self) -> str:
        if self.is_character_grid:
            return f"{self.name} ({self.columns}x{self.rows} characters)"
        return f"{self.name} ({self.width_px}x{self.height_px} pixels)"


#: The panels the product family actually ships.
PANELS: dict[str, Panel] = {
    "tij-800x600": Panel(
        name="tij-800x600",
        description="V4T-TIJ touchscreen HMI, Windows",
        width_px=800,
        height_px=600,
        default_font="tahoma-8",
        codepage=None,
    ),
    "tij8pen-1024x768": Panel(
        name="tij8pen-1024x768",
        description="V4T-TIJ8PEN configuration tool, Windows",
        width_px=1024,
        height_px=768,
        default_font="tahoma-8",
        codepage=None,
    ),
    "mini-20x4": Panel(
        name="mini-20x4",
        description="V4T-Mini character LCD",
        columns=20,
        rows=4,
        default_font="mini-5x7",
        codepage=1252,
        supports_dbcs=False,
        # The panel is driven over the same framed serial link as the print
        # data, and these three bytes are the frame markers.
        forbidden=("\x02", "\x03", "\x7f"),
    ),
    "mini-oled-128x64": Panel(
        name="mini-oled-128x64",
        description="V4T-Mini graphic OLED",
        width_px=128,
        height_px=64,
        default_font="mini-5x7",
        codepage=1252,
        supports_dbcs=False,
        forbidden=("\x02", "\x03", "\x7f"),
    ),
    "mobile": Panel(
        name="mobile",
        description="V4T-Mobile, Android",
        width_px=0,
        height_px=0,
        default_font="",
        codepage=None,
    ),
}


def register_panel(panel: Panel) -> None:
    """Add or replace a panel definition."""
    PANELS[panel.name] = panel


def get_panel(name: str) -> Panel:
    """Look a panel up by name."""
    panel = PANELS.get(name)
    if panel is None:
        raise ConfigError(
            f"unknown panel {name!r}. Known panels: {', '.join(panel_names())}"
        )
    return panel


def panel_names() -> list[str]:
    return sorted(PANELS)


def font_for(panel: Panel, *, search: list[Path] | None = None,
             explicit: Path | None = None) -> FontMetrics:
    """Load the metrics a panel should be measured with.

    ``explicit`` wins, then the panel's default font is looked for in each
    directory of ``search``. If nothing is found, a fixed-pitch stand-in is
    returned rather than an exception: measuring with a rough font is much
    better than not measuring, and the caller can see the name it got.
    """
    if explicit is not None:
        return load_metrics(explicit)

    for directory in search or []:
        candidate = directory / f"{panel.default_font}.fmx"
        if candidate.is_file():
            return load_metrics(candidate)

    return monospace(6, name=f"{panel.name}-fallback")
