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

## A round

```
v4t-translate status                 where the project is, and what is stopping it
v4t-translate extract                read the sources into the catalog
v4t-translate export                 write the workbook a translator gets sent
v4t-translate import <delivery>      read a workbook or an XLIFF back in
v4t-translate check                  run every rule over what came back
v4t-translate build                  write the localised outputs
v4t-translate audit out/manifest.json   prove the outputs are what shipped
```

`v4t-translate check --explain <rule>` says what any rule is for. `--explain
all` lists them.

For a product that is already translated and has no catalog, `adopt` lifts the
answers out of the existing localised files.

## Documentation

| what | where |
| --- | --- |
| every rule and analysis, and why it exists | [docs/rules.md](docs/rules.md) |
| the catalog and translation file formats | [docs/catalog-format.md](docs/catalog-format.md) |
| the `.v4l` language pack container | [docs/v4l-container.md](docs/v4l-container.md) |
| how a round actually runs | [docs/workflow.md](docs/workflow.md) |
| accepting a finding, with a date on it | [docs/waivers.md](docs/waivers.md) |
| what each exit code means, and which to retry | [docs/exit-codes.md](docs/exit-codes.md) |

## Builds you can reproduce

Set `SOURCE_DATE_EPOCH` to the commit time and a rebuild of that commit is the
archive, byte for byte. `build --reproducible` builds twice and fails if the
two differ; `audit` checks a directory against the manifest that says what is
in it.

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
    layout/      dialog units, fonts, mirroring, what fits
    rules/       the checks that see one message
    analyses/    the checks that need the whole language
    emit/        writers, one per output format
    mt/          translation memory and machine translation
    report/      console, JSON, JUnit, SARIF, HTML
    workbook/    the spreadsheet a translator gets
    ops/         the operations the CLI exposes
    cli/         one module per command
tests/
tools/           selfcheck.py, one round against a built wheel
Translate/       the translator workbooks, as delivered
```

## Running it unattended

The operations that change the catalog take a lock, so two people importing at
once cannot lose a delivery. `--log-file` appends a JSON object per step with
timings, and never writes a field whose name looks like a credential. Exit
code 4 means somebody else is writing and is the only one worth retrying.
