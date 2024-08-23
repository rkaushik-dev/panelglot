"""``python -m v4t_translate`` and the installed console script."""

from __future__ import annotations

import sys

from .cli import run


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
