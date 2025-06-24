# Changelog

## 0.3.0

The round, end to end, with the parts that were still manual.

- `init` scaffolds a project. Two products were localised by copying another
  one's config and both copies kept a source pointing at the wrong printer.
- `verify` checks a built `.v4l` against the firmware header that will load
  it, which is what the pack signature was always for.
- `prune` drops translations, memory units and cache entries the catalog no
  longer needs.
- `diff` says what changed between two catalogs, including the controls that
  got smaller without anybody editing a string.
- `font build` makes metrics out of a BDF instead of by hand. Two of the
  hand-written ones were wrong, both in the direction that makes a
  translation look like it fits.
- `TRANSLATORS:` and `CONTEXT:` comments in any of the three source formats.
- Number checking: a value a developer typed into a string, and whether it is
  written the way the target language writes it.
- Right to left checking: a mixed direction string with no directional mark
  draws its punctuation at the far end of the line.
- Machine translation engines are described in config rather than coded in.
  The key comes from the environment and the config refuses to hold one.
- Reports as HTML for people who are not developers, and as JUnit for CI.
- The extraction cache, keyed on content rather than modification time.
- Dutch, Swedish, Danish, Norwegian, Finnish, Hungarian, Romanian and Greek.
- Workbooks carry an instructions sheet, cell comments, and colouring for the
  rows that changed since the last round.

### Changed

- `check` reports the whole-language findings too: mnemonic collisions,
  merged translations and rows left in English.
- `check` no longer skips messages with no translation, so an entry marked
  approved with an empty cell is caught.
- `--version` with `-v` prints the catalog, cache and pack format numbers.
  The question is never what version it is.

## 0.2.0

Everything the old collector did, plus the parts it got wrong.

- Reads Win32 resource scripts, the V4T-Mini generated string table and
  V4T-Mobile's `strings.xml`.
- Catalog that survives a reworded string: the translation is carried across
  and marked for review rather than lost.
- Translator workbooks that round trip, including the two-column sheets
  already delivered.
- Checks: placeholder parity, mnemonics, glyph coverage, codepage
  encodability, fitting, protected strings, punctuation, whitespace, reserved
  transport characters, glossary, and the whole-language ones (mnemonic
  collisions, merged translations, untouched rows).
- Writes localised `.rc` by splicing rather than regenerating, the `.v4l`
  binary language pack, Android `strings.xml`, a localised C header and PO.
- Translation memory, and pseudo-localisation for finding clipped labels
  before anybody has been paid to translate a word.
- `check --format junit` for CI.

### Removed

- `collect_string_from_V4T.py`. Its skip list survives as the default
  protected patterns and there is a test that walks it verbatim.

## 0.1.0

The original collector: parsed `V4T.rc` by splitting on whitespace, called a
translation API once per string, and wrote an xlsx.
