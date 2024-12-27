"""The ``.v4l`` language pack the firmware loads.

The Mini and the OLED panel do not link their translations in. A language pack
sits on the SD card and the bootloader maps it, so a distributor can add a
language without a firmware build. That is the whole point of the format and
it is also its one real danger.

The firmware indexes strings by the ``LNG_*`` enum, which is a compile time
constant. If somebody inserts an id in the middle of the enum, rebuilds the
firmware and does not rebuild the language packs, every string from that point
shifts by one. Nothing crashes. The purge confirmation appears on the print
button and the printer does what the operator did not ask for.

So the pack carries a signature over the id names it was built against, and
the firmware compares it against its own compiled-in constant before using
anything. A mismatched pack is refused and the panel falls back to English,
which is a bad day rather than a recall.

Layout, all little endian::

    0   4   magic "V4LG"
    4   2   format version
    6   2   flags
    8   2   codepage, 0 when the payload is UTF-16
    10  2   Win32 locale id
    12  4   string count
    16  4   payload length in bytes
    20  4   signature: CRC32 over the id names, NUL separated
    24  4   checksum: CRC32 over the offset table and the payload
    28  16  locale tag, ASCII, NUL padded
    44  4*n offset table, byte offsets into the payload
    ..  ..  payload, NUL terminated strings
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.model import Origin, OriginKind
from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..errors import EmitError
from .base import EmitOptions, EmitResult

__all__ = [
    "MAGIC",
    "FORMAT_VERSION",
    "HEADER_SIZE",
    "FLAG_UTF16",
    "FLAG_RTL",
    "V4lPack",
    "V4lEmitter",
    "build_pack",
    "read_pack",
    "table_signature",
]

MAGIC = b"V4LG"
FORMAT_VERSION = 1
HEADER_SIZE = 44

FLAG_UTF16 = 0x0001
FLAG_RTL = 0x0002

_HEADER = struct.Struct("<4sHHHHIIII16s")

#: The pack is mapped straight out of flash on the Mini, which has 48K. A pack
#: larger than this is a mistake somewhere, and finding out at build time is
#: much better than finding out when the bootloader refuses it.
MAX_PACK_BYTES = 64 * 1024


@dataclass
class V4lPack:
    """A decoded language pack. Used by the reader and by the tests."""

    version: int
    flags: int
    codepage: int
    lcid: int
    tag: str
    signature: int
    strings: list[str] = field(default_factory=list)

    @property
    def is_utf16(self) -> bool:
        return bool(self.flags & FLAG_UTF16)

    @property
    def is_rtl(self) -> bool:
        return bool(self.flags & FLAG_RTL)

    def __len__(self) -> int:
        return len(self.strings)


def table_signature(symbols: list[str]) -> int:
    """CRC32 over the id names the pack was built against.

    Over the names and not the count, because a rename is as dangerous as an
    insertion and a count catches neither. NUL separated so that ``AB`` and
    ``A``+``B`` cannot collide.
    """
    joined = b"\x00".join(symbol.encode("ascii", "replace") for symbol in symbols)
    return zlib.crc32(joined) & 0xFFFFFFFF


def build_pack(strings: list[str], symbols: list[str], *, tag: str, lcid: int,
               codepage: int | None, rtl: bool = False) -> bytes:
    """Assemble a pack. ``codepage`` of ``None`` means a UTF-16LE payload."""
    if len(strings) != len(symbols):
        raise EmitError(
            f"{len(strings)} strings and {len(symbols)} ids, which cannot be paired"
        )

    flags = 0
    if codepage is None:
        flags |= FLAG_UTF16
    if rtl:
        flags |= FLAG_RTL

    payload = bytearray()
    offsets: list[int] = []

    for index, text in enumerate(strings):
        offsets.append(len(payload))
        payload += _encode(text, codepage, symbols[index])
        payload += b"\x00\x00" if codepage is None else b"\x00"

    table = b"".join(struct.pack("<I", offset) for offset in offsets)
    body = table + bytes(payload)

    header = _HEADER.pack(
        MAGIC,
        FORMAT_VERSION,
        flags,
        0 if codepage is None else codepage,
        lcid,
        len(strings),
        len(payload),
        table_signature(symbols),
        zlib.crc32(body) & 0xFFFFFFFF,
        tag.encode("ascii", "replace")[:16].ljust(16, b"\x00"),
    )

    pack = header + body
    if len(pack) > MAX_PACK_BYTES:
        raise EmitError(
            f"the pack is {len(pack)} bytes and the panel can map "
            f"{MAX_PACK_BYTES}. Shorten the strings or split the language"
        )
    return pack


def read_pack(data: bytes) -> V4lPack:
    """Decode a pack. The reader exists so the writer can be trusted."""
    if len(data) < HEADER_SIZE:
        raise EmitError(f"a pack is at least {HEADER_SIZE} bytes and this is {len(data)}")

    (magic, version, flags, codepage, lcid, count, payload_length,
     signature, checksum, raw_tag) = _HEADER.unpack(data[:HEADER_SIZE])

    if magic != MAGIC:
        raise EmitError(f"not a language pack: magic is {magic!r}")
    if version > FORMAT_VERSION:
        raise EmitError(f"pack is format {version} and this build reads {FORMAT_VERSION}")

    body = data[HEADER_SIZE:]
    expected = count * 4 + payload_length
    if len(body) != expected:
        raise EmitError(f"pack says {expected} bytes of body and carries {len(body)}")

    if zlib.crc32(body) & 0xFFFFFFFF != checksum:
        raise EmitError("pack checksum does not match, the file is damaged")

    table = body[: count * 4]
    payload = body[count * 4 :]
    offsets = [struct.unpack_from("<I", table, i * 4)[0] for i in range(count)]

    encoding = "utf-16-le" if flags & FLAG_UTF16 else f"cp{codepage}"
    terminator = b"\x00\x00" if flags & FLAG_UTF16 else b"\x00"
    step = 2 if flags & FLAG_UTF16 else 1

    strings: list[str] = []
    for offset in offsets:
        end = offset
        while end + step <= len(payload) and payload[end : end + step] != terminator:
            end += step
        strings.append(payload[offset:end].decode(encoding))

    return V4lPack(
        version=version,
        flags=flags,
        codepage=codepage,
        lcid=lcid,
        tag=raw_tag.rstrip(b"\x00").decode("ascii"),
        signature=signature,
        strings=strings,
    )


class V4lEmitter:
    """Writes the binary language pack for the Mini and the OLED panel."""

    kind = "v4l"

    #: Origin container the slot order is taken from. The extractor walks the
    #: generated table in order, so ordering origins by line reproduces the
    #: enum order the firmware indexes with.
    container = "lng_en"

    def __init__(self, container: str | None = None) -> None:
        if container:
            self.container = container

    def emit(self, catalog: Catalog, translations: TranslationSet,
             options: EmitOptions) -> EmitResult:
        result = EmitResult(path=options.path)

        slots = self._slots(catalog, result)
        if not slots:
            raise EmitError(
                f"no messages came from a {self.container!r} table, so there is no "
                f"slot order to build a pack from"
            )

        strings: list[str] = []
        symbols: list[str] = []

        for key, origin in slots:
            message = catalog.messages[key]
            translation = translations.get(key)
            symbols.append(origin.symbol)

            if translation.text:
                strings.append(translation.text)
                result.written += 1
            elif options.fallback_to_source:
                strings.append(message.source_text)
                result.fell_back.append(key)
            else:
                strings.append("")
                result.skipped.append(key)

        data = build_pack(
            strings,
            symbols,
            tag=options.locale.tag,
            lcid=options.locale.lcid,
            codepage=None if options.encoding == "utf-16" else options.locale.codepage,
            rtl=options.locale.rtl,
        )

        options.path.parent.mkdir(parents=True, exist_ok=True)
        options.path.write_bytes(data)
        result.bytes_written = len(data)
        return result

    def _slots(self, catalog: Catalog, result: EmitResult) -> list[tuple[str, Origin]]:
        """Message keys in firmware index order, with the origin that fixed it."""
        found: list[tuple[int, str, str, Origin]] = []

        for key, message in catalog.messages.items():
            for origin in message.origins:
                if origin.kind is not OriginKind.C_STRING_TABLE:
                    continue
                if origin.container != self.container:
                    continue
                found.append((origin.line, origin.source, key, origin))

        found.sort()

        seen: set[str] = set()
        slots: list[tuple[str, Origin]] = []
        for _, _, key, origin in found:
            if origin.symbol in seen:
                result.warn(
                    f"{origin.symbol} appears twice in {self.container}, the second "
                    f"one is ignored"
                )
                continue
            seen.add(origin.symbol)
            slots.append((key, origin))

        return slots


def _encode(text: str, codepage: int | None, symbol: str) -> bytes:
    encoding = "utf-16-le" if codepage is None else f"cp{codepage}"
    try:
        return text.encode(encoding)
    except (UnicodeEncodeError, LookupError) as exc:
        raise EmitError(
            f"{symbol}: {text!r} cannot be encoded in {encoding}. The encoding rule "
            f"should have caught this before the build"
        ) from exc


def write_pack(path: Path | str, data: bytes) -> int:
    """Write raw pack bytes. Separate so a test can build without writing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)
