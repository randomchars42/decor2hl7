"""Lazy public entry points for CDA compilation and rendering.

Importing a submodule such as :mod:`decor2hl7.cda.datatypes` must not initialize
the renderer. The renderer depends on runtime bindings, which ultimately use
the target-neutral semantics module and would otherwise form an import cycle.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "collect_templates": (".compile", "collect_templates"),
    "compile_cda": (".compile", "compile_cda"),
    "compile_cda_model": (".compile", "compile_cda_model"),
    "emit": (".render", "emit"),
    "select_template": (".compile", "select_template"),
    "write_cda": (".compile", "write_cda"),
    "write_cda_model": (".compile", "write_cda_model"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load a stable public entry point only when it is first requested."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
