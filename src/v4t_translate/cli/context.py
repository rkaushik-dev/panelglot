"""State every command shares, and how it talks.

The config is resolved lazily. Several commands are useful without one and
``--help`` on any of them must not go looking for a project file, which is
what happened when the config was loaded in the group callback.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..config import ProjectConfig, load_config

__all__ = ["Context", "pass_context"]


class Context:
    """State shared by every command."""

    def __init__(self, config_path: Path | None, verbose: int, quiet: bool,
                 traceback: bool) -> None:
        self.config_path = config_path
        self.verbose = verbose
        self.quiet = quiet
        self.traceback = traceback
        self._config: ProjectConfig | None = None

    @property
    def config(self) -> ProjectConfig:
        if self._config is None:
            self._config = load_config(self.config_path)
        return self._config

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
