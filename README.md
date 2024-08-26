# V4T-Translate

Localisation toolchain for the V4T thermal inkjet coder family.

The products carry their strings in three different formats and draw them onto
four different panels. This pulls all of it into one catalog, hands that
catalog to a translator as a workbook, checks what comes back against the
physical limits of the panel it will be drawn on, and writes the result back
out in whatever shape each target needs.

## What it reads

| kind | where it comes from |
| --- | --- |
| `rc` | Win32 resource scripts: V4T-TIJ and V4T-TIJ8PEN-Config |
| `cheader` | the generated string table the V4T-Mini panel firmware links |
| `androidxml` | `res/values/strings.xml` from V4T-Mobile |

## Getting started

```
pip install -e ".[dev]"
v4t-translate extract
```

`extract` reads every source named in `v4t-translate.toml`, updates
`catalog/`, and reports what changed. It writes nothing outside the catalog
directory. Add `--dry-run` to write nothing at all.

## Configuration

One `v4t-translate.toml` at the root of the project. Paths in it resolve
against the file, not the working directory. The copy checked in here is the
real V4T-TIJ configuration and doubles as the worked example.

## Why the checks exist

A translation that is correct and does not fit is still a defect. On these
panels it is the most common one:

- `MS Shell Dlg` is an alias, not a font. It resolves to Tahoma on an English
  machine and PMingLiU on a Traditional Chinese one, so every control on the
  dialog changes size when the language does.
- The older TIJ boards still compile their resources as 8-bit. A string that
  does not encode in the target codepage draws as a box, and nothing fails at
  build time.
- The panel fonts are bitmap subsets. A glyph that is not in the subset is not
  a fallback, it is a blank.

## Layout

```
src/v4t_translate/
    catalog/     messages, translations, merge, on-disk format
    sources/     readers, one package per dialect
    layout/      dialog units, fonts, what fits
    ops/         the operations the CLI exposes
tests/
Translate/       the translator workbooks, as delivered
```
