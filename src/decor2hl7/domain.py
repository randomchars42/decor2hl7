"""Target-neutral accessors for compiled dataset value domains."""

from __future__ import annotations

from typing import Any, Mapping, cast


def accepted_values(field: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the field's executable value domain."""
    values = field.get("accepted_values")
    return cast(Mapping[str, Any], values) if isinstance(values, Mapping) else {}


def logical_values(field: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return owner concept-list options before formal-domain restriction."""
    domain = field.get("logical_domain")
    options = domain.get("options") if isinstance(domain, Mapping) else None
    if isinstance(options, Mapping):
        return cast(Mapping[str, Any], options)
    return accepted_values(field)
