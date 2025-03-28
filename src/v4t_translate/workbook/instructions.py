"""The second sheet, which explains the first one.

Every delivery before this one came back with the same four questions in an
email, and answering them in an email meant the next translator did not get
the answer. They are on a sheet now.

It is written per language, because the answers are not the same everywhere:
a Traditional Chinese translator needs to know the panel font holds no Latin
italics and a German one needs to know the space budget is real. What is
shared is the mechanics, and that part is the same paragraph every time.

Deliberately not a link to a wiki. Half of the people who fill these in are at
a distributor and have never had an account on anything of ours.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from ..catalog.translations import TranslationState
from ..locales import Locale

__all__ = ["SHEET_TITLE", "write_instructions", "lines_for"]

SHEET_TITLE = "How to fill this in"

_HEADING = Font(bold=True, size=12)
_BODY = Font(size=10)

_STATE_MEANINGS = {
    TranslationState.EMPTY: "Nobody has answered this yet. Type the translation.",
    TranslationState.DRAFT: "A machine or a close match filled it in. Read it and "
                            "fix it, then set the status to approved.",
    TranslationState.NEEDS_REVIEW: "Somebody answered it, and then the English "
                                   "changed or a check flagged it. Read it again.",
    TranslationState.APPROVED: "Signed off. This is the only state that ships "
                               "without a warning.",
    TranslationState.DO_NOT_TRANSLATE: "Ships in English on purpose. Leave the "
                                       "cell as it is.",
}

_MECHANICS = [
    ("The Translation column is the only one you type in.",
     "Everything else is locked. The Source column comes from the software and "
     "editing it here does nothing at all."),
    ("Do not sort, insert or delete rows.",
     "You can, and it will still work, because every row carries a Key. But it "
     "makes the sheet much harder to compare with the last round."),
    ("Anything starting with a percent sign is a placeholder.",
     "%s, %d, %.1f and so on are replaced by a number or a name when the printer "
     "runs. Keep every one of them, keep them in the same order, and do not "
     "translate them. Getting this wrong crashes the printer."),
    ("<V1> and <V2> are placeholders too.",
     "These are replaced by name, so you may put them wherever the sentence "
     "needs them. You may not add or remove one."),
    ("A single & marks the keyboard shortcut.",
     "&Print underlines the P and binds Alt+P. Keep one in the translation, on a "
     "letter that appears in it. Two of them, &&, mean a literal ampersand and "
     "bind nothing."),
    ("The Limit column is the space available.",
     "In pixels for the screens, in characters for the printer's own display. "
     "Text past it is not drawn small, it is not drawn at all."),
    ("A trailing colon or ellipsis is not decoration.",
     "A colon means a control follows the label. Three dots mean the command "
     "opens another window. Keep whichever the English has."),
    ("Leading and trailing spaces matter.",
     "Some of these strings are joined together at run time and the space is "
     "what separates them. Keep them exactly."),
]


def lines_for(locale: Locale, project: str) -> list[tuple[str, str]]:
    """The instruction lines for one language, as ``(heading, body)`` pairs."""
    lines: list[tuple[str, str]] = [
        (f"{project}, {locale.english_name}", ""),
        ("", ""),
        ("Statuses", ""),
    ]

    for state, meaning in _STATE_MEANINGS.items():
        lines.append((state.value, meaning))

    lines.extend([("", ""), ("How it works", "")])
    lines.extend(_MECHANICS)

    specific = _language_specific(locale)
    if specific:
        lines.extend([("", ""), (f"Notes for {locale.english_name}", "")])
        lines.extend(specific)

    return lines


def _language_specific(locale: Locale) -> list[tuple[str, str]]:
    notes: list[tuple[str, str]] = []

    if locale.double_byte:
        notes.append((
            "The panel font is a subset.",
            "It holds the characters this product has needed so far. A character "
            "outside it draws as a blank, so if a check says a character is "
            "missing please pick another word rather than assuming it will "
            "render.",
        ))
        notes.append((
            "Full width punctuation is right here.",
            "Use it wherever your language normally would. The checks know the "
            "difference between a full width colon and an ASCII one and accept "
            "either.",
        ))
    else:
        notes.append((
            f"Everything has to fit codepage {locale.codepage}.",
            "The older printer boards still build their text as single bytes. A "
            "character outside that codepage becomes a question mark somewhere "
            "between here and the machine.",
        ))

    if locale.rtl:
        notes.append((
            "Mixed direction strings need a mark.",
            "Where an English word or a number is embedded in your sentence, put "
            "U+200F RIGHT-TO-LEFT MARK at the boundary. Without it the "
            "punctuation is drawn at the far end of the line.",
        ))

    return notes


def write_instructions(book, locale: Locale, project: str) -> None:
    """Add the instructions sheet to a workbook."""
    sheet = book.create_sheet(SHEET_TITLE)

    for row, (heading, body) in enumerate(lines_for(locale, project), start=1):
        left = sheet.cell(row=row, column=1, value=heading)
        left.font = _HEADING if not body else _BODY
        left.alignment = Alignment(vertical="top", wrap_text=True)

        if body:
            right = sheet.cell(row=row, column=2, value=body)
            right.font = _BODY
            right.alignment = Alignment(vertical="top", wrap_text=True)

    sheet.column_dimensions[get_column_letter(1)].width = 46
    sheet.column_dimensions[get_column_letter(2)].width = 86
    sheet.protection.sheet = True
    sheet.protection.enable()
