"""Structural accessors for normalized scalar quantities and ranges."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


Quantity = tuple[Any, str]


def scalar_quantity(value: Any) -> Quantity | None:
    """Return ``(value, unit)`` for one normalized scalar quantity."""
    if not isinstance(value, Mapping) or value.get("value") is None:
        return None
    return value.get("value"), str(value.get("unit") or "")


def range_quantities(
    value: Any,
) -> tuple[Quantity | None, Quantity | None] | None:
    """Return normalized low/high quantity bounds when this is a range."""
    if not isinstance(value, Mapping) or not ({"low", "high"} & value.keys()):
        return None
    return scalar_quantity(value.get("low")), scalar_quantity(value.get("high"))


def preferred_mapping_value(value: Any, keys: Sequence[str]) -> Any:
    """Return the first non-empty presentation member of a normalized value."""
    if not isinstance(value, Mapping):
        return None
    return next(
        (value.get(key) for key in keys if value.get(key) not in (None, "")),
        None,
    )
