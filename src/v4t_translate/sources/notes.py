"""Comments a developer leaves for the translator.

The workbook has a note column and until now nothing could put anything in it
except the tool itself. Everything a translator actually needed to know lived
in somebody's head, and the way it got out was an email thread per round.

Two markers, both in an ordinary comment above the string:

``TRANSLATORS:``
    Free text. Goes into the note column and into the PO as a ``#.`` comment.
    "Shown while the head is warming up, so it has to fit on one line."

``CONTEXT:``
    One word that disambiguates. Two strings with the same English and
    different contexts get different keys, so they can be translated
    differently, which is the whole reason German needs it: Print the button
    and Print the menu heading are one word in English and two in German.

The convention is gettext's and it is deliberately the same one. Half the
people who touch these files have used it somewhere else.

Comments are found by scanning the raw text rather than by keeping them in
the token stream. A comment is not part of the grammar of any of the three
formats and threading it through three parsers to reach one field would be a
lot of change for a note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Note", "NOTE_MARKER", "CONTEXT_MARKER", "collect_notes"]

NOTE_MARKER = "TRANSLATORS:"
CONTEXT_MARKER = "CONTEXT:"

#: Comment openers across the three formats we read. The rc and C files use
#: the C ones; strings.xml uses the XML one.
_COMMENT = re.compile(
    r"""
      //\s*(?P<line>.*?)$
    | /\*\s*(?P<block>.*?)\*/
    | <!--\s*(?P<xml>.*?)-->
    """,
    re.VERBOSE | re.DOTALL | re.MULTILINE,
)

_MARKED = re.compile(
    rf"(?:{NOTE_MARKER}|{CONTEXT_MARKER})",
)


@dataclass
class Note:
    """What a developer said about the strings below this point."""

    text: str = ""
    context: str = ""
    line: int = 0

    def __bool__(self) -> bool:
        return bool(self.text or self.context)


@dataclass
class NoteIndex:
    """Notes by the line they apply to."""

    by_line: dict[int, Note] = field(default_factory=dict)

    def for_line(self, line: int) -> Note | None:
        """The note covering a string on ``line``, if there is one.

        An exact lookup. Which line a comment covers is worked out once when
        the file is scanned, stepping over blank lines and other comments,
        rather than by searching backwards from every string: searching back
        made a note apply to the line after the one it was written for.
        """
        return self.by_line.get(line)

    def __len__(self) -> int:
        return len(self.by_line)


def collect_notes(text: str) -> NoteIndex:
    """Find every marked comment in ``text`` and index it by the line it covers.

    A comment applies to the next line with something on it, not to the line
    the comment is on. That is where people put them, and it is what gettext's
    xgettext does.
    """
    index = NoteIndex()
    lines = text.splitlines()

    for match in _COMMENT.finditer(text):
        body = next(
            (group for group in match.groups() if group is not None), ""
        ).strip()

        if not _MARKED.search(body):
            continue

        note = _parse(body)
        if not note:
            continue

        start = text[: match.start()].count("\n")
        end = text[: match.end()].count("\n")
        note.line = start + 1

        target = _next_content_line(lines, end + 1)
        if target is not None:
            index.by_line[target] = note

    return index


def _parse(body: str) -> Note:
    """Pull the two markers out of a comment body."""
    note = Note()
    parts: list[str] = []

    for raw in body.splitlines():
        line = raw.strip().lstrip("*").strip()

        if CONTEXT_MARKER in line:
            _, _, rest = line.partition(CONTEXT_MARKER)
            word = rest.strip().split()
            if word:
                note.context = word[0].rstrip(".,;")
            continue

        if NOTE_MARKER in line:
            _, _, rest = line.partition(NOTE_MARKER)
            parts.append(rest.strip())
            continue

        if parts:
            # A continuation line of a TRANSLATORS comment.
            parts.append(line)

    note.text = " ".join(part for part in parts if part).strip()
    return note


def _next_content_line(lines: list[str], start: int) -> int | None:
    """The next line with something other than whitespace or a comment on it."""
    for offset in range(start, min(len(lines), start + 6)):
        stripped = lines[offset].strip()
        if not stripped:
            continue
        if stripped.startswith(("//", "/*", "*", "<!--")):
            continue
        return offset + 1
    return None
