"""Exception hierarchy, and what the shell gets told.

Everything raised on purpose derives from :class:`V4TError` so the CLI can
catch one type and turn it into an exit code instead of a traceback.

The codes follow sysexits, which is a convention from 1987 that nothing much
honours and that costs nothing to honour. It matters here for one reason: the
build scripts at two of the sites are shell, and shell can only branch on a
number. "The config is wrong" and "the translation is wrong" want different
handling, and 78 against 2 is the difference between a mail to the developer
and a mail to the translator.

Two codes are ours rather than sysexits'. Check failure is 2, because it is
not a crash and every linter in the world uses 2 for "I found things". A held
lock is 4, because a build script that hits one should retry rather than give
up, and it needs to tell that apart from everything else.

Errors carry a remedy as well as a message. A message says what happened and a
remedy says what to do, and the two get written differently: one is a
statement about the past and the other is an instruction. Squeezing both into
one sentence produces the kind of error text that ends in "please check your
configuration".
"""

from __future__ import annotations

__all__ = [
    "V4TError",
    "ConfigError",
    "SourceError",
    "ParseError",
    "CatalogError",
    "WorkbookError",
    "EmitError",
    "CheckFailed",
    "LockError",
    "EXIT_CODES",
    "exit_code_table",
]


class V4TError(Exception):
    """Base class for every error this package raises deliberately."""

    #: Process exit code the CLI uses when this escapes to the top level.
    exit_code = 1

    #: One line describing the class of problem, for the exit code table.
    kind = "something went wrong"

    def __init__(self, message: str, *, remedy: str = "") -> None:
        self.remedy = remedy
        super().__init__(message)


class ConfigError(V4TError):
    """The project configuration is missing, malformed or contradictory."""

    exit_code = 78
    kind = "the project file is wrong"


class SourceError(V4TError):
    """A source file could not be read or understood."""

    exit_code = 65
    kind = "an input file is wrong"


class ParseError(SourceError):
    """A source file was read but does not parse.

    Carries the position so the CLI can print something a person can act on
    rather than a bare message.
    """

    def __init__(self, message: str, *, path: str | None = None,
                 line: int | None = None, column: int | None = None,
                 remedy: str = "") -> None:
        self.path = path
        self.line = line
        self.column = column
        super().__init__(message, remedy=remedy)

    def __str__(self) -> str:
        where = self.location()
        base = super().__str__()
        return f"{where}: {base}" if where else base

    def location(self) -> str:
        """Return a ``path:line:col`` prefix, skipping the parts we do not know."""
        parts: list[str] = []
        if self.path:
            parts.append(self.path)
        if self.line is not None:
            parts.append(str(self.line))
            if self.column is not None:
                parts.append(str(self.column))
        return ":".join(parts)


class CatalogError(V4TError):
    """The catalog on disk is unusable."""

    exit_code = 65
    kind = "an input file is wrong"


class WorkbookError(V4TError):
    """A translator workbook does not have the shape we expect."""

    exit_code = 65
    kind = "an input file is wrong"


class EmitError(V4TError):
    """An output target could not be written."""

    exit_code = 73
    kind = "an output could not be written"


class LockError(V4TError):
    """Somebody else is writing.

    Its own code because a build script that hits one should wait and try
    again, and it has to tell that apart from every other failure, which it
    should not retry.
    """

    exit_code = 4
    kind = "somebody else is writing; retry"


class CheckFailed(V4TError):
    """Validation found problems at or above the configured failure level.

    This is not a crash. It is the normal way ``v4t-translate check`` reports
    that a language is not ready to ship.
    """

    exit_code = 2
    kind = "the check found problems"

    def __init__(self, message: str, *, error_count: int = 0,
                 warning_count: int = 0, remedy: str = "") -> None:
        self.error_count = error_count
        self.warning_count = warning_count
        super().__init__(message, remedy=remedy)


#: Every code this tool exits with, and what it means. 0 is here so the table
#: reads as the whole set rather than as the failures.
EXIT_CODES: dict[int, str] = {
    0: "everything worked",
    1: V4TError.kind,
    CheckFailed.exit_code: CheckFailed.kind,
    LockError.exit_code: LockError.kind,
    SourceError.exit_code: SourceError.kind,
    EmitError.exit_code: EmitError.kind,
    ConfigError.exit_code: ConfigError.kind,
}


def exit_code_table() -> str:
    """The codes as a table, for ``--help`` and for the docs."""
    return "\n".join(f"{code:>3}  {meaning}"
                     for code, meaning in sorted(EXIT_CODES.items()))
