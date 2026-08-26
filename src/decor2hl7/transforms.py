"""Small declarative value transforms for model-to-CDA mappings.

Transforms are intentionally data-only and side-effect free.  Mapping files may
use a direct target name or a rule object::

    {"target": "SomeTarget", "transform": {"type": "enum", "map": {"yes": false}}}

A field may map to several rule objects when one source value controls several
CDA constraints (for example ``negationInd`` plus ``nullFlavor``).
"""
from __future__ import annotations

from typing import Any, Mapping

OMIT = object()


def mapping_rules(value: Any) -> list[dict[str, Any]]:
    """Normalize a mapping value to rule dictionaries.

    Backward-compatible direct strings and lists of strings are accepted.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            out.append({"target": item})
        elif isinstance(item, Mapping) and item.get("target"):
            out.append(dict(item))
    return out


def selected_targets(value: Any) -> list[str]:
    return [str(rule["target"]) for rule in mapping_rules(value)]


def _scalar(value: Any, transform: Mapping[str, Any]) -> Any:
    kind = str(transform.get("type") or "identity")
    if kind == "identity":
        return value
    if kind == "enum":
        table = transform.get("map", {})
        if not isinstance(table, Mapping):
            raise ValueError("enum transform requires an object map")
        key = value
        if isinstance(value, Mapping):
            key = value.get("canonical") or value.get("displayName") or value.get("display_name") or value.get("code")
        if key in table:
            result = table[key]
        elif str(key) in table:
            result = table[str(key)]
        elif "default" in transform:
            result = transform.get("default")
        else:
            return OMIT
        return OMIT if result is None else result
    if kind == "ordinal":
        table = transform.get("map", {})
        key = value
        if isinstance(value, Mapping):
            key = value.get("canonical") or value.get("displayName") or value.get("display_name") or value.get("code")
        if isinstance(table, Mapping) and (key in table or str(key) in table):
            raw = table[key] if key in table else table[str(key)]
            return int(raw) if str(raw).lstrip("+-").isdigit() else float(raw)
        if isinstance(value, (int, float)):
            return value
        raise ValueError(f"ordinal transform has no score for {key!r}")
    if kind == "not":
        if isinstance(value, bool):
            return not value
        raise ValueError("not transform requires a boolean value")
    raise ValueError(f"unknown mapping transform {kind!r}")


def apply_transform(value: Any, transform: Mapping[str, Any] | None) -> Any:
    """Apply a transform recursively while preserving repetition shape."""
    if not transform:
        return value
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            transformed = apply_transform(item, transform) if item is not None else OMIT
            out.append(None if transformed is OMIT else transformed)
        return out
    if value is None:
        return OMIT
    return _scalar(value, transform)


def validate_transform(transform: Any) -> list[str]:
    if transform is None:
        return []
    if not isinstance(transform, Mapping):
        return ["transform must be an object"]
    kind = str(transform.get("type") or "")
    if kind not in {"identity", "enum", "ordinal", "not"}:
        return [f"unknown transform type {kind!r}"]
    if kind in {"enum", "ordinal"} and not isinstance(transform.get("map"), Mapping):
        return [f"{kind} transform requires an object map"]
    return []
