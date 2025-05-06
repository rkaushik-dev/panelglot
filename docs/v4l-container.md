# The .v4l language pack

The Mini and the OLED panel load their translations off the SD card rather
than linking them in, so a distributor can add a language without a firmware
build.

All values little endian.

| offset | size | field |
| --- | --- | --- |
| 0 | 4 | magic, `V4LG` |
| 4 | 2 | format version, currently 1 |
| 6 | 2 | flags |
| 8 | 2 | codepage, 0 when the payload is UTF-16 |
| 10 | 2 | Win32 locale id |
| 12 | 4 | string count |
| 16 | 4 | payload length in bytes |
| 20 | 4 | signature: CRC32 over the id names |
| 24 | 4 | checksum: CRC32 over the offset table and the payload |
| 28 | 16 | locale tag, ASCII, NUL padded |
| 44 | 4×n | offset table, byte offsets into the payload |
| 44+4n | | payload, NUL terminated strings |

Flags:

| bit | meaning |
| --- | --- |
| 0 | payload is UTF-16LE rather than the codepage |
| 1 | right to left |

## The signature

This is the field that matters and the reason the format exists in this shape.

The firmware indexes strings by the `LNG_*` enum, which is a compile time
constant. Insert an id in the middle of that enum, rebuild the firmware, and
forget to rebuild the packs, and every string past that point shifts by one.
Nothing crashes. The purge confirmation appears on the print button and the
printer does what nobody asked for.

So the header carries a CRC32 over the id names, NUL separated, and the
bootloader compares it against its own compiled-in constant before using
anything. A pack that does not match is refused and the panel falls back to
English.

Over the names and not over the count, because a rename is as dangerous as an
insertion and a count catches neither. NUL separated because `AB` + `C` and
`A` + `BC` would otherwise hash the same.

## Size

A pack is refused at build time above 64 KB. The Mini has 48 KB of flash and
maps the pack directly, so finding out at build time is much better than
finding out when the bootloader refuses it in the field.

## Reading one back

`v4t_translate.emit.v4l.read_pack` decodes a pack and is what the tests
compare against. A binary format with no reader is a format nobody can check.
