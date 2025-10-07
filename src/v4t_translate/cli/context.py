"""State every command shares, and how it talks.

The config is resolved lazily. Several commands are useful without one and
``--help`` on any of them must not go looking for a project file, which is
what happened when the config was loaded in the group callback.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import click

from ..config import ProjectConfig, load_config
from ..diagnostics import Diagnostics
from ..locking import project_lock

__all__ = ["Context", "pass_context"]


class Context:
    """State shared by every command."""

    def __init__(self, config_path: Path | None, verbose: int, quiet: bool,
                 traceback: bool, *, diagnostics: Diagnostics | None = None,
                 timings: bool = False) -> None:
        self.config_path = config_path
        self.verbose = verbose
        self.quiet = quiet
        self.traceback = traceback
        self.timings = timings
        self.diagnostics = diagnostics or Diagnostics()
        self._config: ProjectConfig | None = None

    @property
    def config(self) -> ProjectConfig:
        if self._config is None:
            with self.diagnostics.step("load-config") as fields:
                self._config = load_config(self.config_path)
                fields["project"] = self._config.name
                fields["locales"] = len(self._config.locales)
        return self._config

    def step(self, name: str, **fields: object):
        """Time a block and record it. Sugar for the diagnostics call."""
        return self.diagnostics.step(name, **fields)

    @contextmanager
    def writing(self, operation: str, *, enabled: bool = True):
        """Hold the project lock for a write, and report a stolen one.

        Every operation that reads the catalog, changes it and writes it back
        goes through here. Two of those running at once on a share is how a
        delivery disappears without anything erroring.
        """
        with project_lock(self.config, operation, enabled=enabled) as lock:
            yield lock
            for warning in lock.warnings if lock else []:
                self.warn(warning)

    def finish(self) -> None:
        """Close the log, and print the timings if they were asked for."""
        if self.timings and not self.quiet:
            self._say_timings()
        self.diagnostics.close()

    def _say_timings(self) -> None:
        slowest = self.diagnostics.slowest()
        if not slowest:
            return

        click.echo("")
        click.echo(self.diagnostics.summary())
        for event in slowest:
            click.echo(f"  {(event.seconds or 0) * 1000:8.0f}ms  {event.name}")

    def say(self, message: str, *, level: int = 0) -> None:
        """Print unless quiet, and unless it needs more -v than we were given."""
        if self.quiet or level > self.verbose:
            return
        click.echo(message)

    def warn(self, message: str) -> None:
        # --quiet says only errors, and a warning is not one. Suppressing it
        # here rather than at each call site is what keeps -q honest.
        if self.quiet:
            return
        click.echo(click.style("warning: ", fg="yellow") + message, err=True)


pass_context = click.make_pass_decorator(Context)
