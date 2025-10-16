"""One writer at a time.

The catalog lives on a share for two of the three sites that use this, and the
operations that write it are read, modify, write. Two imports at once means the
second one loads the catalog before the first one saves it, and the first
delivery is gone. Nothing errors, nothing is logged, and the translator is
told their file did not arrive.

So the writing operations take a lock. It is a file, created exclusively, and
that is deliberate: exclusive create is the one primitive that behaves the
same on Windows, on Linux and on the SMB share in between. Anything richer
would be a lie on at least one of them.

Three things follow from choosing a file.

It has to say who holds it. A lock nobody can attribute is a lock people
delete, and then there are two writers and a lock file.

It has to expire. A run that was killed leaves the file behind, and a tool
that then refuses forever needs a person who knows to delete it. The holder
writes a timestamp and a stale lock is taken over with a warning rather than
being fatal.

And the expiry has to be generous. A pretranslate against a rate limited
engine legitimately runs for twenty minutes, and stealing a lock from a
process that is still working is worse than any deadlock this prevents.
"""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from .errors import LockError

__all__ = ["LockError", "LockInfo", "ProjectLock", "STALE_AFTER", "held"]

#: How long before a lock is treated as abandoned. Twenty minutes, because a
#: pretranslate against a rate limited engine really does take that long, and
#: stealing a lock from a process that is still working is the worse failure.
STALE_AFTER = 20 * 60


@dataclass(frozen=True)
class LockInfo:
    """Who holds a lock and since when."""

    host: str
    pid: int
    operation: str
    taken_at: float

    def age(self, now: float | None = None) -> float:
        return max(0.0, (now if now is not None else time.time()) - self.taken_at)

    def is_stale(self, now: float | None = None, *,
                 stale_after: float = STALE_AFTER) -> bool:
        return self.age(now) > stale_after

    def is_mine(self) -> bool:
        """Whether this process holds it.

        Used to make the lock reentrant within one run rather than to decide
        anything about safety. A second process on the same machine gets a
        different pid.
        """
        return self.host == _hostname() and self.pid == os.getpid()

    def describe(self) -> str:
        return (
            f"{self.operation or 'a run'} on {self.host} (pid {self.pid}), "
            f"started {int(self.age())} seconds ago"
        )

    def serialise(self) -> str:
        return f"{self.host}\n{self.pid}\n{self.operation}\n{self.taken_at:.0f}\n"

    @classmethod
    def parse(cls, text: str) -> LockInfo | None:
        """Read a lock file. Anything unreadable is treated as no lock at all.

        A corrupt lock file is a half-written one, which means the writer died
        mid-create, which means nobody holds it.
        """
        lines = text.splitlines()
        if len(lines) < 4:
            return None
        try:
            return cls(host=lines[0], pid=int(lines[1]), operation=lines[2],
                       taken_at=float(lines[3]))
        except ValueError:
            return None


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:  # pragma: no cover - only on a very broken box
        return "unknown"


def held(path: Path | str) -> LockInfo | None:
    """Who holds the lock at ``path``, or None."""
    path = Path(path)
    try:
        return LockInfo.parse(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None


class ProjectLock:
    """The lock on one project's catalog directory."""

    def __init__(self, path: Path | str, *, operation: str = "",
                 stale_after: float = STALE_AFTER,
                 clock=None) -> None:
        self.path = Path(path)
        self.operation = operation
        self.stale_after = stale_after
        self._clock = clock or time.time
        self._taken = False
        self.warnings: list[str] = []

    def acquire(self) -> LockInfo:
        """Take the lock, or say who has it."""
        info = LockInfo(host=_hostname(), pid=os.getpid(),
                        operation=self.operation, taken_at=self._clock())

        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._create(info)
        except FileExistsError:
            self._take_over_or_refuse(info)

        self._taken = True
        return info

    def release(self) -> None:
        """Give the lock up. Never raises; a lock we cannot delete is stale."""
        if not self._taken:
            return
        with suppress(OSError):
            self.path.unlink(missing_ok=True)
        self._taken = False

    def _create(self, info: LockInfo) -> None:
        # O_EXCL is the whole mechanism. It is the one primitive that means
        # the same thing on Windows, on Linux and on an SMB share.
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(info.serialise())

    def _take_over_or_refuse(self, info: LockInfo) -> None:
        existing = held(self.path)

        if existing is None:
            # Half written, so nobody holds it. Overwrite in place rather than
            # unlink and recreate: the unlink loses a race that the write does
            # not, and either way it was not a lock.
            self.path.write_text(info.serialise(), encoding="utf-8", newline="\n")
            return

        if existing.is_mine():
            return

        if existing.is_stale(self._clock(), stale_after=self.stale_after):
            self.warnings.append(
                f"took over a lock left by {existing.describe()}. That run was "
                f"killed or the machine went away."
            )
            self.path.write_text(info.serialise(), encoding="utf-8", newline="\n")
            return

        raise LockError(
            f"{self.path.name} is held by {existing.describe()}",
            remedy=f"Wait for that run to finish, or delete {self.path} if you "
                   f"are certain it is gone.",
        )

    def __enter__(self) -> ProjectLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


@contextmanager
def project_lock(config, operation: str = "", *, enabled: bool = True):
    """Hold the project's lock for the duration of a write.

    ``enabled`` exists for the operations that take a ``--dry-run``. A run
    that writes nothing has no business making anybody else wait.
    """
    if not enabled:
        yield None
        return

    lock = ProjectLock(config.root / config.catalog_dir / ".lock",
                       operation=operation)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.release()
