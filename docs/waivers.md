# Waivers

A waiver is a finding the team has looked at and decided to accept. It lives
in `waivers.toml` beside the project file, and `check` filters its report
through it.

There is a full example in [waivers.example.toml](waivers.example.toml).

## Why not just turn the rule off

Because the rule is right. The Hebrew build really does overflow by two
pixels, and the Turkish translation of purge really does disagree with the
glossary. Disabling `fitting` to get past the first one loses every fitting
finding in every language, including the ones that matter. Demoting it to a
warning teaches everybody that warnings are noise.

A waiver names one rule, optionally one language and one message, and nothing
else changes.

## Fields

| field | required | what it does |
| --- | --- | --- |
| `rule` | yes | Which rule's findings this covers. |
| `reason` | yes | Why this is acceptable. Written for whoever finds it in six months. |
| `owner` | yes | Who decided. |
| `until` | yes | A bare date. After it, the waiver stops suppressing. |
| `locale` | no | One language. Leaving it out covers all of them, which is rare and usually wrong. |
| `key` | no | One message key. Leaving it out covers every message the rule fires on. |

## The date

`until` is the whole point of the file.

A suppression with no expiry survives the person who added it, the reason it
was added, and the problem it was added for. What is left is a line that
nobody dares delete because nobody knows what it does.

So `check` says something in three situations:

- the week before a waiver expires, so there is time to renew it deliberately
- the day after it expires, when it has stopped suppressing anything
- when it no longer matches any finding, which means the problem was fixed and
  the waiver is now a note about something that does not happen

All three come out as warnings on the run, not as findings, because a stale
waiver is not a translation problem and should not itself be waivable.

## What a waiver does not do

It does not hide the finding from the count. `check` prints the number of
waived findings after the summary, because a clean report with four waived
findings behind it is not a clean report.

`check --no-waivers` ignores the file entirely. That is what to run before a
release, and what `doctor` reports on.
