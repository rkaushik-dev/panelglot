# Exit codes

The build scripts at two of the sites are shell, and shell can only branch on
a number. "The project file is wrong" and "the translation is wrong" want
different handling: one is a mail to a developer and the other is a mail to a
translator.

| code | meaning | who it is for |
| --- | --- | --- |
| 0 | everything worked | nobody |
| 1 | something went wrong | whoever ran it |
| 2 | the check found problems | the translator |
| 4 | somebody else is writing; retry | the script |
| 65 | an input file is wrong | the developer |
| 73 | an output could not be written | whoever owns the disk |
| 78 | the project file is wrong | the developer |

The numbers other than 2 and 4 are sysexits, which is a convention from 1987
that nothing much honours and that costs nothing to honour.

Check failure is 2 because it is not a crash, and because every linter in the
world uses 2 for "I found things".

A held lock is 4 because a script that hits one should wait and try again, and
it needs to tell that apart from every other failure, none of which it should
retry.

## Retrying

Only 4 is worth retrying. Everything else will fail the same way a second
time.

```sh
for attempt in 1 2 3; do
    v4t-translate import "$delivery" && break
    [ $? -eq 4 ] || exit $?
    sleep 30
done
```

## Remedies

An error prints two lines when there is something to do about it:

```
error: catalog/v4t-tij.json does not exist
  try: Run extract first.
```

The first line says what happened and the second says what to do. They are
separate on purpose. Run together they read as one sentence ending in a
suggestion nobody notices.
