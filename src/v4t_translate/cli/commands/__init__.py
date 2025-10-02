"""One module per command, or per group of closely related ones.

The list below is the order they appear in ``--help``, which is roughly the
order somebody does them in: extract, check, send, receive, build. Click sorts
alphabetically on its own and that put build first, which is the last thing
anybody runs.
"""

from __future__ import annotations

import click

from .build import build
from .check import check
from .extract import extract
from .font import font
from .init import init
from .inspect import diff, doctor, pack_diff, prune, stats, verify
from .status import status
from .sync import adopt, export, import_
from .translate import memory, pretranslate

__all__ = ["COMMANDS", "register"]

#: Commands in the order a person meets them.
COMMANDS: tuple[click.Command, ...] = (
    init,
    status,
    extract,
    adopt,
    check,
    export,
    import_,
    pretranslate,
    build,
    verify,
    pack_diff,
    stats,
    diff,
    doctor,
    prune,
    memory,
    font,
)


def register(group: click.Group) -> None:
    """Attach every command to ``group``."""
    for command in COMMANDS:
        group.add_command(command)
