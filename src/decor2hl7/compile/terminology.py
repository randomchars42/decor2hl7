"""Terminology-domain accessors shared by reports and runtime configuration."""

from __future__ import annotations

from typing import Any, Mapping

from ..semantics import accepted_values, logical_values


def formal_members(field: Mapping[str, Any]) -> Mapping[str, Any]:
    formal = field.get("formal_terminology", {})
    if isinstance(formal, Mapping) and isinstance(formal.get("members"), Mapping):
        return formal.get("members", {})
    return accepted_values(field)


def logical_options(field: Mapping[str, Any]) -> Mapping[str, Any]:
    return logical_values(field)


def domain_difference(field: Mapping[str, Any]) -> dict[str, list[str]]:
    formal = set(map(str, formal_members(field)))
    logical = set(map(str, logical_options(field)))
    return {
        "logical_only": sorted(logical - formal),
        "formal_only": sorted(formal - logical),
        "shared": sorted(formal & logical),
    }
