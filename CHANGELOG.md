# Changelog

## 0.4.0

The release the build machines needed. 0.3 could do a round; this one can be
trusted to do it unattended and can prove afterwards what it did.

### Builds you can reproduce and check

- `SOURCE_DATE_EPOCH` pins every timestamp the outputs carry. Set it to the
  commit time and a rebuild of that commit is the archive, byte for byte.
- `build --reproducible` builds twice into memory and fails if the two differ.
- `audit` checks a directory of built files against the manifest that says
  what they are, including files the manifest does not mention.
- `pack-diff` says which strings differ between two `.v4l` packs, and refuses
  to compare two whose signatures disagree instead of producing nonsense.
- Catalog format 2 puts the source paths in one table. Moving a `.rc` used to
  rewrite a line under every message that came out of it.

### Running unattended

- One writer at a time. The operations that read, change and write the catalog
  take a lock, which expires so a killed run does not block the next one.
- `--log-file` appends a JSON object per step, with timings. Field names that
  look like credentials never reach it.
- `--timings` prints where the time went without writing anything.
- Every error carries a remedy, and the exit codes are documented and tested.
  4 means somebody else is writing and is the only one worth retrying.
- The project file rejects a key it does not understand. `glosary` silently
  turned the terminology check off for three languages.

### Getting work in and out

- `adopt` lifts a language's answers out of an already translated `.rc`,
  aligned by position rather than by text.
- XLIFF 1.2 out and back, which is what two of the agencies asked for.
- `export --parts` splits a language across translators without splitting a
  dialog.
- The workbook carries the agreed terms, including the renderings that were
  rejected.
- The reader finds the translation sheet even when the tabs were reordered.

### Checking

- `check --since` reports only what moved, for a review.
- `check --explain` says what a rule is for, in the words of whoever wrote it.
- SARIF output, anchored to the line of the `.rc`.
- Waivers: an accepted finding, with an owner and a date it expires.
- `shortcuts`: the menu hint may translate Ctrl to Strg and may not move the
  key, which is bound in the accelerator table and is not translated.
- Right to left dialogs get `WS_EX_LAYOUTRTL`, and a bidi finding now shows a
  string that would render correctly rather than only saying this one will not.
- `collisions` split into three separately nameable analyses.
- `font coverage` and `font subset`, in both directions.
- `status` says whether the project can ship and what is stopping it.
- `stats --record` keeps the coverage numbers so they can be compared.

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
