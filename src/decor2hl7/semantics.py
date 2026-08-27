"""Shared mapping/runtime semantics.

Keep the same direct-write rules in the mapper, configuration validator and
renderer. Formal ART-DECOR evidence may exist even when a value cannot be
written directly without a transform.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

DATATYPE_FAMILIES: dict[str, set[str]] = {
    "quantity": {"PQ", "REAL", "INT"},
    "decimal": {"REAL", "PQ"},
    "integer": {"INT", "REAL", "PQ", "INT.POS"},
    "ordinal": {"INT", "REAL", "PQ", "CO", "CE", "CV", "CD"},
    "datetime": {"TS", "IVL_TS"},
    "date": {"TS", "IVL_TS"},
    "duration": {"PQ"},
    "identifier": {"II"},
    "code": {"CD", "CE", "CV", "CS", "CO", "SC"},
    "boolean": {"BL"},
    "text": {"ST", "ED", "SD.TEXT", "SC"},
}


def accepted_values(field: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the executable domain, with model-v1 compatibility."""
    values = field.get("accepted_values")
    if isinstance(values, Mapping):
        return values
    formal = field.get("formal_terminology")
    if isinstance(formal, Mapping) and isinstance(formal.get("members"), Mapping):
        members = formal.get("members", {})
        if members:
            return members
    legacy = field.get("values")
    return legacy if isinstance(legacy, Mapping) else {}


def logical_values(field: Mapping[str, Any]) -> Mapping[str, Any]:
    domain = field.get("logical_domain")
    if isinstance(domain, Mapping) and isinstance(domain.get("options"), Mapping):
        return domain.get("options", {})
    return accepted_values(field)


def base_datatype(value: Any) -> str:
    return str(value or "").upper().split(".", 1)[0]


def type_match(model_type: str, cda_type: str | None) -> bool:
    if not cda_type:
        return False
    value = str(cda_type).upper()
    return any(
        value == family or value.startswith(family + ".")
        for family in DATATYPE_FAMILIES.get(str(model_type), set())
    )


def payload_match(model_type: str, target: Mapping[str, Any]) -> bool:
    leaf = str(target.get("path") or "").rsplit("/", 1)[-1].replace("cda:", "hl7:")
    if model_type in {"quantity", "decimal", "integer", "ordinal", "code", "duration"}:
        return leaf in {"hl7:value", "hl7:originalText"}
    if model_type == "text":
        return leaf in {"hl7:value", "hl7:originalText", "hl7:text"}
    if model_type == "boolean":
        return leaf in {"hl7:value", "@negationInd"}
    if model_type in {"datetime", "date"}:
        return leaf in {"hl7:effectiveTime", "hl7:time", "hl7:low", "hl7:high", "hl7:value"}
    if model_type == "identifier":
        return leaf.startswith("hl7:id")
    return False


def _unit_key(value: Any) -> str:
    text = str(value or "").strip().casefold().replace(" ", "")
    aliases = {
        "mmhg": "mm[hg]", "mm[hg]": "mm[hg]",
        "°c": "cel", "degc": "cel", "cel": "cel",
        "1/min": "/min", "min-1": "/min",
    }
    return aliases.get(text, text)


def unit_match(field: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    if str(field.get("type") or "") not in {"quantity", "duration"}:
        return True
    model_unit = field.get("unit")
    target_unit = target.get("unit")
    if not model_unit or not target_unit:
        return True
    return _unit_key(model_unit) == _unit_key(target_unit)


def direct_compatibility(
    field: Mapping[str, Any], target: Mapping[str, Any], *, explicit_path: bool = False
) -> tuple[bool, list[str]]:
    model_type = str(field.get("type") or "")
    if not model_type:
        return False, ["dataset node has no value datatype"]
    if model_type == "ordinal":
        coded = any(
            isinstance(info, Mapping) and info.get("code")
            for info in accepted_values(field).values()
        )
        target_base = base_datatype(target.get("datatype"))
        allowed = {"CD", "CE", "CV", "CO", "SC"} if coded else {"INT", "REAL", "PQ"}
        if target_base not in allowed:
            return False, [
                f"ordinal representation ({'coded' if coded else 'numeric'}) is incompatible with CDA {target.get('datatype') or 'container'}"
            ]
    elif not type_match(model_type, target.get("datatype")):
        return False, [f"datatype {model_type} is incompatible with CDA {target.get('datatype') or 'container'}"]
    if not explicit_path and not payload_match(model_type, target):
        return False, [f"CDA target {target.get('path') or '?'} is not a direct {model_type} payload"]
    if not unit_match(field, target):
        return False, [f"unit {field.get('unit')} is incompatible with CDA unit {target.get('unit')}"]
    repeat_chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
    target_repeats = list(target.get("repeat_ancestors") or ([] if not target.get("repeatable") else ["*"]))
    if repeat_chain and len(repeat_chain) != len(target_repeats):
        return False, [
            f"dataset has {len(repeat_chain)} repetition level(s) but CDA target has {len(target_repeats)}"
        ]
    return True, []


_OID_RE = re.compile(r"^(?:0|1|2)(?:\.(?:0|[1-9][0-9]*))+$")


def valid_oid(value: Any) -> bool:
    return bool(_OID_RE.fullmatch(str(value or "").strip()))


def identifier_root_for_target(name: str, target: Mapping[str, Any], site: Mapping[str, Any]) -> str | None:
    fixed = target.get("fixed", {})
    if isinstance(fixed, Mapping) and fixed.get("root"):
        return str(fixed["root"])
    identifiers = site.get("identifiers", {})
    explicit = identifiers.get("roots", {}) if isinstance(identifiers, Mapping) else {}
    if isinstance(explicit, Mapping) and explicit.get(name):
        return str(explicit[name])
    if name.startswith("PatientIdentifier."):
        value = identifiers.get("patient_root") if isinstance(identifiers, Mapping) else None
        return str(value) if value else None
    if name.startswith("CDAEncompassingEncounter.id"):
        value = identifiers.get("encounter_root") if isinstance(identifiers, Mapping) else None
        return str(value) if value else None
    return None


def transformed_compatibility(
    field: Mapping[str, Any], target: Mapping[str, Any], transform: Mapping[str, Any] | None
) -> tuple[bool, list[str]]:
    """Validate the output of a declarative transform against a CDA target."""
    if not transform or str(transform.get("type") or "identity") == "identity":
        return direct_compatibility(field, target)
    reasons: list[str] = []
    kind = str(transform.get("type") or "")
    base = base_datatype(target.get("datatype"))
    path = str(target.get("path") or "")
    if kind == "enum":
        table = transform.get("map", {})
        values = [item for item in table.values() if item is not None] if isinstance(table, Mapping) else []
        if path.endswith("/@nullFlavor"):
            if not all(isinstance(item, str) for item in values):
                reasons.append("nullFlavor enum transform must produce strings")
        elif base == "BL" or path.endswith("/@negationInd"):
            if not all(isinstance(item, bool) for item in values):
                reasons.append("boolean CDA target requires boolean enum outputs")
        elif base in {"INT", "REAL", "PQ"}:
            if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
                reasons.append(f"numeric CDA {target.get('datatype')} requires numeric enum outputs")
        elif base in {"CD", "CE", "CV", "CS", "CO", "SC"}:
            if not all(isinstance(item, (str, Mapping)) for item in values):
                reasons.append("coded CDA target requires string/coded enum outputs")
        elif not values:
            reasons.append("enum transform has no non-null output")
    elif kind == "ordinal":
        if base not in {"INT", "REAL", "PQ"}:
            reasons.append(f"ordinal transform requires numeric CDA target, got {target.get('datatype') or 'container'}")
    elif kind == "not":
        if str(field.get("type") or "") != "boolean" or base != "BL":
            reasons.append("not transform requires boolean dataset and CDA values")
    else:
        reasons.append(f"unknown transform type {kind!r}")
    repeat_chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
    target_repeats = list(target.get("repeat_ancestors") or ([] if not target.get("repeatable") else ["*"]))
    if repeat_chain and len(repeat_chain) != len(target_repeats):
        reasons.append(
            f"dataset has {len(repeat_chain)} repetition level(s) but CDA target has {len(target_repeats)}"
        )
    return not reasons, reasons
