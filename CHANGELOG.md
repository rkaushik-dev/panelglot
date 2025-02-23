# Changelog

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
