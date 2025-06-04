# A round

What a localisation round looks like from the command line. The integration
test in `tests/test_workflow.py` walks exactly this, so it is not aspirational.

## Once, at the start

```
v4t-translate init . -n V4T-Mini -s cheader:../V4T-Mini/src/v4t_lang.h -l de-DE
v4t-translate doctor
```

`doctor` before anything else. Most of what goes wrong is a sibling checkout
that is not cloned or font metrics that never reached the build machine, and
both of those produce something that looks like it worked.

## Every round

```
v4t-translate extract
cp catalog/v4t-mini.json sent-round-4.json
v4t-translate pretranslate de-DE
v4t-translate export --outstanding --since sent-round-3.json
```

Keep the copy. `--since` colours the rows that are new or whose control has
shrunk, which is the difference between sending somebody nine hundred rows and
sending them the eleven that changed.

`pretranslate` before `export` so memory has already answered whatever it can.
An exact hit lands as needs-review, which asks the translator to confirm rather
than to type.

## When it comes back

```
v4t-translate import "Translate/V4T-Mini - German.xlsx" --strict
v4t-translate check
v4t-translate memory absorb
```

`--strict` fails on any row that matched nothing. That happens when the
English moved between sending the sheet and getting it back, and it is silent
otherwise: nine hundred rows where sixty matched nothing looks exactly like
nine hundred rows that all landed.

`memory absorb` after the check passes, not before. Memory should only hold
answers somebody has approved.

## Shipping

```
v4t-translate check --format junit -o reports/check.xml
v4t-translate build
v4t-translate verify out/de-DE.v4l -H ../V4T-Mini/src/v4t_lang.h
```

`build` refuses to run over a failing check. `--no-check` exists and should be
used about once a year.

`verify` does on a desk what the bootloader does in the field. Run it in the
build: the failure it catches is somebody inserting an id in the middle of the
enum and not rebuilding the packs, which shifts every string past that point
and crashes nothing.

## Before a translator has been paid for anything

```
v4t-translate pretranslate de-DE --provider pseudo
v4t-translate check --fail-on never
```

Pseudo rewrites English into something still readable but a third longer and
covered in accents, which is roughly what German does to a layout. Running the
whole HMI in it finds every clipped label and every hardcoded string in an
afternoon.

Throw the result away afterwards. It lands as draft, so a real round will
overwrite it and `check` will not let it ship.

## In CI

```
v4t-translate extract
v4t-translate check --format junit -o reports/check.xml
```

`extract` first, because everything downstream reads the catalog and a stale
one produces a clean report about the wrong strings. `doctor` catches that
too, and is cheap enough to run in the same job.
