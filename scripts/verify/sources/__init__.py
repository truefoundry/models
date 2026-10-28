"""Source adapters. Each module in this package registers one adapter factory by name:

    from . import SOURCES
    SOURCES["openrouter"] = OpenRouter      # a callable returning a `verify.types.Source`

`load_sources()` imports every module here, then instantiates the registered adapters (all, or
only the names asked for). A module that fails to import is recorded in IMPORT_ERRORS and its
adapter is simply absent: the core then reports the provider as `verify:partial`.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable

from ..types import Source

SOURCES: dict[str, Callable[[], Source]] = {}
IMPORT_ERRORS: dict[str, str] = {}


def _import_adapters() -> None:
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_") or f"{__name__}.{mod.name}" in IMPORT_ERRORS:
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as e:  # noqa: BLE001 - one broken adapter must not stop the run
            IMPORT_ERRORS[f"{__name__}.{mod.name}"] = f"{type(e).__name__}: {e}"


def load_sources(only: Iterable[str] | None = None) -> list[Source]:
    """Instantiated adapters; `only` limits it to those names. [] when no adapter is registered.
    An adapter whose factory raises is skipped (and listed in IMPORT_ERRORS)."""
    _import_adapters()
    wanted = None if only is None else set(only)
    out: list[Source] = []
    for name in sorted(SOURCES):
        if wanted is not None and name not in wanted:
            continue
        try:
            out.append(SOURCES[name]())
        except Exception as e:  # noqa: BLE001
            IMPORT_ERRORS[f"{__name__}.{name}"] = f"{type(e).__name__}: {e}"
    return out
