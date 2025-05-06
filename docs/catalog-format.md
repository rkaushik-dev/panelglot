# The catalog

Two kinds of file, both JSON, both checked in beside the source they came
from. The format is chosen for review, not for size: stable key order,
indented, unicode written through rather than escaped, one trailing newline.
A run that changes nothing produces identical bytes.

## catalog/&lt;project&gt;.json

Every message the sources produce.

```json
{
  "format": 1,
  "project": "V4T-TIJ",
  "source_locale": "en-US",
  "messages": [
    {
      "key": "bar-height.9f2c1a",
      "text": "Bar Height",
      "max_width_px": 54,
      "origins": [
        {
          "source": "src/V4T.rc",
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
