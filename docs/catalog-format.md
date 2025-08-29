# The catalog

Two kinds of file, both JSON, both checked in beside the source they came
from. The format is chosen for review, not for size: stable key order,
indented, unicode written through rather than escaped, one trailing newline.
A run that changes nothing produces identical bytes.

## catalog/&lt;project&gt;.json

Every message the sources produce.

```json
{
  "format": 2,
  "project": "V4T-TIJ",
  "source_locale": "en-US",
  "sources": ["src/V4T.rc"],
  "messages": [
    {
      "key": "bar-height.9f2c1a",
      "text": "Bar Height",
      "max_width_px": 54,
      "origins": [
        {
          "src": 0,
          "kind": "dialog-control",
          "container": "IDD_BARCODE_PROPS",
          "symbol": "IDC_STATIC",
          "line": 41,
          "ordinal": 1
        }
      ]
    }
  ]
}
```

Defaults are left out. A message with no context, no note, nothing protected
and one line writes none of those fields.

### The source table

`src` is an index into `sources`, which lists each file once in the order it
was first seen. First seen rather than sorted, so renaming one file does not
reshuffle every other index.

Format 1 wrote the path inline as `source` on every origin. That is still read,
so an older catalog loads without conversion, and a `source` string wins over
an `src` index if a hand-edited file somehow has both.

The reason is diffs rather than size, though it does roughly halve the file.
Moving one `.rc` used to rewrite a line under every message that came from it,
so reviewing a six line change meant reading four thousand lines of noise.

## The version numbers

The catalog and the per-locale files carry separate `format` numbers, and they
move separately. The catalog is at 2 and the translation files are still at 1,
because their shape has not changed and bumping it would stop an older build
reading a file it understands perfectly well.

### The key

`<slug>.<hash>`. The slug is the source text reduced to lowercase ASCII and
capped at 32 characters; the hash is six hex digits of SHA-1 over the context
and the normalised text.

Derived from what the translator sees, deliberately not from the control id or
the file. `IDC_STATIC` numbering churns every time somebody drags a label and a
property page gets moved between rc files about once a release; keying on
either would retire half the catalog for nothing.

The slug is in front so a reviewer can tell which string moved without
decoding a hash.

## catalog/&lt;locale&gt;.json

One language's answers.

```json
{
  "format": 1,
  "locale": "de-DE",
  "entries": {
    "bar-height.9f2c1a": {
      "text": "Balkenhöhe",
      "state": "approved",
      "fingerprint": "0011223344556677",
      "updated": "2025-02-14",
      "origin": "Translation - V4T-TIJ - German.xlsx"
    }
  }
}
```

### States

| state | meaning |
| --- | --- |
| `empty` | nothing supplied |
| `draft` | machine output or a fuzzy match, not shippable |
| `needs-review` | answered, then something changed underneath |
| `approved` | signed off |
| `do-not-translate` | ships in English on purpose |

### The fingerprint

SHA-256 of the normalised English, truncated to 16 hex digits, taken when the
translation was written.

Three situations look identical from outside: nobody has translated it, it is
translated and current, and it is translated against English that has since
been edited. The third ships wrong and looks finished. This is the only thing
that separates them.

## catalog/.extraction-cache.json

Derived. Delete it and the next run is slower and identical.

Keyed on the content hash of each source rather than its modification time,
because a checkout touches every file it restores and a build machine
trusting mtimes would re-parse everything every run.
