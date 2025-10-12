"""Turning a dialog round for a right to left language.

A translated Hebrew dialog with left to right layout is not a Hebrew dialog.
The text reads right to left inside each control and the controls themselves
are still in English order: the OK button on the left of Cancel, the label to
the left of the field it names, the group box opening on the wrong side. It
looks like a bug to every Hebrew speaker and like a success to everybody else,
which is why it shipped twice.

Windows will do the whole thing itself given two extended styles, and that is
what this produces. ``WS_EX_LAYOUTRTL`` mirrors the coordinate space, so every
control ends up where its mirror image was without a single number changing in
the .rc. ``WS_EX_RTLREADING`` sets the reading order inside the controls.

Doing it with the styles rather than by rewriting coordinates matters. Mirrored
coordinates in the file would have to be maintained forever: every time
somebody drags a control in the English dialog, the mirrored copy has to be
recomputed, and the day it is not, the two drift and nobody notices until a
customer does. The styles are two words that stay correct.

Not everything should mirror. A control showing a barcode preview, a printhead
diagram or a waveform is a picture of a physical thing, and a mirrored picture
of a printhead is wrong in a way the text never is. Those keep
``WS_EX_NOINHERITLAYOUT``, which stops the mirroring at that control.
"""

from __future__ import annotations

from ..sources.rc.ast import Control, Dialog

__all__ = [
    "RTL_EXSTYLES",
    "NO_MIRROR",
    "mirrored_exstyles",
    "render_exstyle",
    "should_mirror_control",
    "unmirrored_controls",
]

#: What a right to left dialog needs. Both, and in this order, because that is
#: the order every Microsoft sample writes them and a diff against one is
#: easier to read than a diff against our own preference.
RTL_EXSTYLES: tuple[str, ...] = ("WS_EX_LAYOUTRTL", "WS_EX_RTLREADING")

#: The style that stops mirroring at one control.
NO_MIRROR = "WS_EX_NOINHERITLAYOUT"

#: Control styles that mean the control is a picture rather than text. A
#: mirrored picture of a printhead is wrong in a way no string ever is.
_PICTURE_STYLES = frozenset(
    {"SS_BITMAP", "SS_ICON", "SS_ENHMETAFILE", "SS_BLACKFRAME", "SS_GRAYFRAME",
     "SS_WHITEFRAME", "SS_BLACKRECT", "SS_GRAYRECT", "SS_WHITERECT",
     "SS_OWNERDRAW"}
)


def mirrored_exstyles(existing: list[str] | None = None) -> list[str]:
    """The extended styles a right to left copy of a dialog needs.

    Existing styles are kept and come first. A dialog that already carries
    ``WS_EX_CONTROLPARENT`` needs it in the Hebrew build as much as in the
    English one, and dropping it because this function only knows about two
    styles would be a quiet regression in tab order.
    """
    out = list(existing or [])
    for style in RTL_EXSTYLES:
        if style not in out:
            out.append(style)
    return out


def render_exstyle(styles: list[str]) -> str:
    """An ``EXSTYLE`` line, as the resource compiler wants it."""
    return "EXSTYLE " + " | ".join(styles)


def should_mirror_control(control: Control) -> bool:
    """Whether this control should follow the dialog's mirroring.

    A control with no caption and a picture style is showing something
    physical. Everything with text on it follows the dialog.
    """
    if control.caption:
        return True
    return not any(control.has_style(style) for style in _PICTURE_STYLES)


def unmirrored_controls(dialog: Dialog) -> list[Control]:
    """The controls in ``dialog`` that should not be turned round."""
    return [control for control in dialog.controls
            if not should_mirror_control(control)]
