# The checks

Listed worst consequence first, which is the order `check` groups them in.

Every one can be turned off, promoted to an error or demoted to a warning from
the `[check]` section of `v4t-translate.toml`:

```toml
[check]
fail_on = "error"
disable = ["glossary"]
promote = ["fitting"]
demote = ["numbers"]
```

## placeholders

`%s`, `%d`, `%.1f`, `<V1>`, `{0}`.

Every placeholder in the English appears in the translation, and no others.
Plain printf specifiers are positional by order, so reordering them is a
defect: `%d of %s` translated as `%s von %d` compiles, runs and crashes.
Numbered ones (`%1$s`) carry their own position and may be reordered. The
`<V1>` tokens are substituted by name and may be reordered too.

Width and flags are cosmetic. `%5d` for `%d` is not reported. The conversion
and the length modifier are not cosmetic and both are.

## numbers

Numbers a developer typed into the string, as opposed to placeholders.

Dropping or changing one is an error: "Maximum 8 pens" is a specification and
the operator believes it. Writing `12.4` where the language writes `12,4` is a
warning.

Identifiers are skipped. A letter immediately before the digits means V4T or
TIJ8PEN rather than a quantity. Version numbers, years and `RS-232` are
skipped by name.

## protocol

Characters the panel's transport reserves.

The Mini panels share a framed serial link with the print data. STX, ETX and
DEL are the frame markers, so a translation containing one does not draw
wrong, it desynchronises the link and the panel stays blank until the printer
is power cycled.

Other control characters are a warning: not drawn, not stripped, and they
spend bytes out of a string table entry with a hard limit.

## encoding

Whether the target can carry the characters at all.

Three separate failures. The codepage cannot encode a character, and the
8-bit resource build turns it into a question mark somewhere between here and
the board. Or the panel has a single byte character path end to end, in which
case the language cannot ship on that panel and no amount of rewording helps.

## glyphs

Whether the panel font holds the characters.

The fonts are compiled subsets. A character outside the subset draws as a
filled box on the Mini and as nothing at all on the older TIJ boards, which is
worse because it reads as a spacing bug.

## protected

Strings that must ship unchanged: unit symbols, date format tokens, product
names.

Overriding one is allowed, but only by marking the entry `do-not-translate`
first, which makes it deliberate and visible in review.

## shortcuts

The hint after the tab in a menu caption, as in `&New\tCtrl+N`.

The modifiers move with the language and should: German writes Strg. The key
at the end does not, because it is bound in the accelerator table, which is
compiled once and is the same in every build. Changing N to U to match Neu
produces a menu advertising a key that does nothing, and nothing else in the
toolchain notices.

Dropping the tab is also reported. The shortcut still works and the menu stops
mentioning it, so nobody finds it.

## state

The state of a translation rather than its content.

Stale is the expensive one: the English was edited after the translation was
approved, so what ships is a confident answer to a question that changed.
Approved with an empty cell is an error and happens every round.

## fitting

Whether it fits.

Three budgets: pixels from the control width through the dialog font,
characters from a fixed grid panel, and lines. Near misses are warnings,
because the base units are measured and the themed padding moves between
Windows versions.

## mnemonics

The `&` that binds Alt.

Dropping one silently removes a keyboard shortcut. Adding one binds Alt to a
letter nobody chose, which is what happens when German writes `Größe & Form`
and the ampersand goes in unescaped.

## direction

Right to left text with something left to right embedded in it.

Punctuation at the boundary is drawn at the far end of the line unless a
directional mark holds it. A directional mark in a left to right language is
an error: invisible in the sheet, and it spends a column on the Mini.

## punctuation

A trailing colon means a control follows the label. An ellipsis means the
command opens another window. Both conventions run through the whole product,
and the full width forms count as the same mark.

## whitespace

Leading and trailing spaces, because several status lines are joined at run
time and the space is what separates them. An introduced tab is an error: in
a menu caption it starts the accelerator label.

## glossary

Agreed terminology, from `glossary/v4t-terms.csv`.

Whole word in the source so `pen` does not fire on `open`. Substring in the
target because German compounds and `Druckkopfspannung` is the right
translation of `printhead voltage`.

The three below are analyses rather than rules. They need the whole language
at once, so they cannot be rules, which see one message. They are named,
disabled, promoted and demoted exactly like a rule, and they land in the same
report, because that distinction is ours and not the reader's.

## plurals

A plural resource with the forms the target language actually needs.

The English resources were written with `one` and `other`, because English has
two. Polish has three and Arabic has six. A Polish `<plurals>` carrying only
`one` and `other` is not a translation with a gap in it: the platform picks
`other` for two, three and four, so the panel says the Polish for five pens
when there are two, and nothing anywhere reports it.

Extra forms are a warning rather than an error. The platform never selects
them, so they are harmless, and they are also somebody's paid work sitting in
a file doing nothing.

## collisions

Two controls on one dialog claiming the same Alt key.

Alt+D on a dialog with two D-marked buttons presses one of them and nobody can
predict which. Invisible until somebody drives the panel from the keyboard,
which on a production line is most of the time. The English is nearly always
fine, because whoever laid the dialog out could see all of it and a translator
sees one string at a time.

## untranslated

A translation that is character for character the English.

Correct for OK and Barcode, wrong for everything else, and the ratio between
the two is what says whether a delivery was done or whether somebody copied
the source column across. Protected messages are excluded, and so is a short
list of words that genuinely do not move.

## merged

Two different English strings that came back as one.

Sometimes right and often a lost distinction. `Print` the button and `Print`
the menu heading are one word in English and two in German.
