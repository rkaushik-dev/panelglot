"""Which reader handles which ``kind``.

Kept separate from the readers so that importing the registry does not drag in
every parser, and so that a reader can be swapped out in a test without
monkeypatching an import.
"""

from __future__ import annotations

from collections.abc import Callable

from ..errors import ConfigError
from .base import Source

__all__ = ["register", "get_source", "available_kinds", "clear_overrides"]

_FACTORIES: dict[str, Callable[[], Source]] = {}
_OVERRIDES: dict[str, Source] = {}


def register(kind: str, factory: Callable[[], Source]) -> None:
    """Record a factory for ``kind``. Registering twice replaces the first."""
    _FACTORIES[kind] = factory


def get_source(kind: str) -> Source:
    """Build the reader for ``kind``.

    Test overrides win, then registered factories, then the built-ins are
    imported on demand. The lazy import is what keeps the rc parser out of the
    process when a project only has Android strings in it.
    """
    if kind in _OVERRIDES:
        return _OVERRIDES[kind]

    if kind not in _FACTORIES:
        _load_builtin(kind)

    factory = _FACTORIES.get(kind)
    if factory is None:
        raise ConfigError(
            f"no reader for source kind {kind!r}. Known kinds: {', '.join(available_kinds())}"
        )
    return factory()


def override(kind: str, source: Source) -> None:
    """Force ``kind`` to resolve to ``source``. Tests only."""
    _OVERRIDES[kind] = source


def clear_overrides() -> None:
    _OVERRIDES.clear()


def available_kinds() -> list[str]:
    return sorted(set(_BUILTINS) | set(_FACTORIES))


_BUILTINS = {
    "rc": ("v4t_translate.sources.rc.extract", "RcSource"),
    "cheader": ("v4t_translate.sources.cheader", "CHeaderSource"),
    "androidxml": ("v4t_translate.sources.androidxml", "AndroidXmlSource"),
}


def _load_builtin(kind: str) -> None:
    target = _BUILTINS.get(kind)
    if target is None:
        return

    module_name, class_name = target
    try:
        module = __import__(module_name, fromlist=[class_name])
    except ImportError as exc:  # pragma: no cover - only on a broken install
        raise ConfigError(f"reader for {kind!r} could not be imported: {exc}") from exc

    register(kind, getattr(module, class_name))
