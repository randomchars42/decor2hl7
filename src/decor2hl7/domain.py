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


def admitted_logical_values(field: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep logical choices only when the complete formal domain admits them.

    Multi-coded owner choices may retain their canonical wording until a target
    disambiguates them, but an unrelated logical option cannot extend a complete
    bound domain. Raw logical evidence remains available through logical_values.
    """
    logical = logical_values(field)
    formal = field.get("formal_terminology", {})
    if not isinstance(formal, Mapping) or not formal.get("complete"):
        return logical
    values = accepted_values(field)
    pairs = {
        (str(info.get("code") or ""), str(info.get("code_system") or ""))
        for info in values.values() if isinstance(info, Mapping) and info.get("code")
    }
    return {
        label: info for label, info in logical.items()
        if label in values or (
            isinstance(info, Mapping) and any(
                isinstance(association, Mapping) and (
                    str(association.get("code") or ""),
                    str(association.get("code_system") or ""),
                ) in pairs
                for association in info.get("terminology_associations", [])
            )
        )
    }
