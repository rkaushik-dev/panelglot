"""Which emitter handles which output kind."""

from __future__ import annotations

from collections.abc import Callable

from ..errors import ConfigError
from .base import Emitter

__all__ = ["register", "get_emitter", "available_kinds"]

_FACTORIES: dict[str, Callable[[], Emitter]] = {}

_BUILTINS = {
    "rc": ("v4t_translate.emit.rcpack", "RcEmitter"),
    "v4l": ("v4t_translate.emit.v4l", "V4lEmitter"),
    "androidxml": ("v4t_translate.emit.androidxml", "AndroidXmlEmitter"),
    "cheader": ("v4t_translate.emit.cheader", "CHeaderEmitter"),
    "po": ("v4t_translate.emit.po", "PoEmitter"),
}


def register(kind: str, factory: Callable[[], Emitter]) -> None:
    _FACTORIES[kind] = factory


def get_emitter(kind: str) -> Emitter:
    if kind not in _FACTORIES:
        _load_builtin(kind)

    factory = _FACTORIES.get(kind)
    if factory is None:
        raise ConfigError(
            f"no emitter for output kind {kind!r}. Known kinds: "
            f"{', '.join(available_kinds())}"
        )
    return factory()


def available_kinds() -> list[str]:
    return sorted(set(_BUILTINS) | set(_FACTORIES))


def _load_builtin(kind: str) -> None:
    target = _BUILTINS.get(kind)
    if target is None:
        return
    module_name, class_name = target
    try:
        module = __import__(module_name, fromlist=[class_name])
    except ImportError as exc:  # pragma: no cover - only on a broken install
        raise ConfigError(f"emitter for {kind!r} could not be imported: {exc}") from exc
    register(kind, getattr(module, class_name))
