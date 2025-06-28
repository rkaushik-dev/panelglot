"""TMX, which is how agencies hand memory back and forth.

Two of the three agencies that have worked on this product asked for a TMX
before they would quote, and one of them sent one back at the end of the job.
It is the only interchange format anybody in this chain has ever asked for by
name.

The subset that is read and written is small on purpose: ``<tu>`` with two
``<tuv>``, source and target, text only. TMX has segmentation rules, inline
markup, sub-flows, notes and properties, and a reader that tries to honour
all of that on files from three different tools is a project. A reader that
takes the pairs and ignores the rest is fifty lines and does not lie about
what it understood.

Inline markup is the one thing that cannot simply be ignored. A ``<ph>`` in a
segment is a placeholder the other tool substituted, and dropping the element
while keeping its text would silently change the string. Segments carrying
inline elements are skipped and counted, so the number shows up rather than
the damage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from ..errors import SourceError
from ..locales import Locale, lookup
from .memory import TranslationMemory

__all__ = ["TmxRead", "read_tmx", "write_tmx", "INLINE_TAGS"]

#: Elements inside a segment that stand for something that is not text.
INLINE_TAGS = frozenset({"bpt", "ept", "ph", "it", "hi", "ut", "sub"})

_HEADER = (
    '<header creationtool="v4t-translate" creationtoolversion="{version}" '
    'segtype="sentence" o-tmf="v4t" adminlang="en-us" srclang="{source}" '
    'datatype="plaintext" creationdate="{stamp}"/>'
)


@dataclass
class TmxRead:
    """What came out of a TMX file."""

    source_language: str = ""
    pairs: list[tuple[str, str]] = field(default_factory=list)
    skipped_inline: int = 0
    skipped_incomplete: int = 0
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.pairs)

    def summary(self) -> str:
        return (
            f"{len(self.pairs)} pairs, {self.skipped_inline} with inline markup, "
            f"{self.skipped_incomplete} incomplete"
        )


def read_tmx(path: Path | str, target: str) -> TmxRead:
    """Read the source and target segments for one language out of a TMX."""
    path = Path(path)
    wanted = lookup(target)
    if wanted is None:
        raise SourceError(f"{target} is not a language this build knows")

    try:
        tree = ElementTree.parse(path)
    except FileNotFoundError as exc:
        raise SourceError(f"{path} does not exist") from exc
    except ElementTree.ParseError as exc:
        raise SourceError(f"{path} is not readable XML: {exc}") from exc

    root = tree.getroot()
    if root.tag != "tmx":
        raise SourceError(f"{path}: root element is <{root.tag}>, expected <tmx>")

    read = TmxRead()

    header = root.find("header")
    if header is not None:
        read.source_language = header.get("srclang", "")

    for unit in root.iter("tu"):
        pair = _pair_from(unit, wanted, read)
        if pair is not None:
            read.pairs.append(pair)

    return read


def _pair_from(unit, target: Locale, read: TmxRead) -> tuple[str, str] | None:
    source_text = ""
    target_text = ""
    inline = False

    for variant in unit.findall("tuv"):
        language = _language_of(variant)
        segment = variant.find("seg")
        if segment is None:
            continue

        if _has_inline(segment):
            inline = True
            continue

        text = "".join(segment.itertext()).strip()
        if _matches(language, target):
            target_text = text
        elif language.lower().startswith("en"):
            source_text = text

    if inline:
        read.skipped_inline += 1
        return None

    if not source_text or not target_text:
        read.skipped_incomplete += 1
        return None

    return (source_text, target_text)


def _language_of(variant) -> str:
    """The language of a tuv, from either spelling of the attribute."""
    return (
        variant.get("{http://www.w3.org/XML/1998/namespace}lang")
        or variant.get("lang")
        or variant.get("xml:lang")
        or ""
    )


def _matches(language: str, target: Locale) -> bool:
    """Whether a TMX language code means the language we asked for.

    Tools write ``de``, ``de-DE``, ``DE-de`` and ``de_DE`` for the same thing,
    and one of them writes ``ZH-TW`` where another writes ``zh-Hant``. Match
    on the language subtag, and on the region only when both carry one.
    """
    found = lookup(language.replace("_", "-"))
    if found is not None:
        return found.tag == target.tag

    parts = language.replace("_", "-").lower().split("-")
    return bool(parts) and parts[0] == target.language.lower()


def _has_inline(segment) -> bool:
    return any(child.tag in INLINE_TAGS for child in segment.iter()
               if child is not segment)


def write_tmx(path: Path | str, memory: TranslationMemory, target: str, *,
              source_language: str = "en-US", version: str = "0",
              today: date | None = None) -> int:
    """Write one language out of memory as a TMX. Returns the pair count."""
    wanted = lookup(target)
    if wanted is None:
        raise SourceError(f"{target} is not a language this build knows")

    stamp = (today or date.today()).strftime("%Y%m%dT000000Z")
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<tmx version="1.4">',
        _HEADER.format(version=version, source=source_language, stamp=stamp),
        "<body>",
    ]

    written = 0
    for text in memory.sources_for(wanted.tag):
        match = memory.recall(wanted.tag, text)
        if match is None:
            continue
        lines.append("  <tu>")
        lines.append(_variant(source_language, text))
        lines.append(_variant(wanted.tag, match.target))
        lines.append("  </tu>")
        written += 1

    lines.extend(["</body>", "</tmx>", ""])

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return written


def _variant(language: str, text: str) -> str:
    return (
        f'    <tuv xml:lang="{language}"><seg>{escape(text)}</seg></tuv>'
    )
