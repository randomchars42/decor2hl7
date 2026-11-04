"""Shared sparse occurrence trees used by bindings, narrative and rendering."""
from __future__ import annotations
from typing import Any, Mapping
from .transforms import OMIT


def present(value: Any) -> bool:
    if value is None or value is OMIT:
        return False
    return any(present(item) for item in value) if isinstance(value, list) else True


def value_at(value: Any, occurrence: tuple[int, ...]) -> Any:
    current = value
    for depth, index in enumerate(occurrence):
        if isinstance(current, list):
            if index < 0 or index >= len(current):
                return None
            current = current[index]
        else:
            # A scalar in a repeating branch supplies its first occurrence only.
            return current if all(item == 0 for item in occurrence[depth:]) else None
    return current


def pack(values: Mapping[tuple[int, ...], Any], depth: int) -> Any:
    """Pack sparse coordinates without shifting a missing sibling's index."""
    def build(prefix: tuple[int, ...]) -> Any:
        if len(prefix) == depth:
            return values.get(prefix)
        indices = {occurrence[len(prefix)] for occurrence in values if occurrence[:len(prefix)] == prefix}
        return [build(prefix + (index,)) for index in range(max(indices) + 1)] if indices else None
    return build(())
