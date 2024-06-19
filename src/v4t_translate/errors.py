"""Exception hierarchy.

Everything raised on purpose derives from :class:`V4TError` so the CLI can
catch one type and turn it into an exit code instead of a traceback.
"""

from __future__ import annotations


class V4TError(Exception):
    """Base class for every error this package raises deliberately."""

    #: Process exit code the CLI uses when this escapes to the top level.
    exit_code = 1


class ConfigError(V4TError):
    """The project configuration is missing, malformed or contradictory."""

    exit_code = 78


class SourceError(V4TError):
    """A source file could not be read or understood."""

    exit_code = 65


class ParseError(SourceError):
    """A source file was read but does not parse.

    Carries the position so the CLI can print something a person can act on
    rather than a bare message.
    """

    def __init__(self, message: str, *, path: str | None = None,
                 line: int | None = None, column: int | None = None) -> None:
        self.path = path
        self.line = line
        self.column = column
        super().__init__(message)

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


class WorkbookError(V4TError):
    """A translator workbook does not have the shape we expect."""

    exit_code = 65


class EmitError(V4TError):
    """An output target could not be written."""

    exit_code = 73


class CheckFailed(V4TError):
    """Validation found problems at or above the configured failure level.

    This is not a crash. It is the normal way ``v4t-translate check`` reports
    that a language is not ready to ship.
    """

    exit_code = 2

    def __init__(self, message: str, *, error_count: int = 0, warning_count: int = 0) -> None:
        self.error_count = error_count
        self.warning_count = warning_count
        super().__init__(message)
