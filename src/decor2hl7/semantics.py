"""Shared mapping/runtime semantics.

Keep the same direct-write rules in the mapper, configuration validator and
renderer. Formal ART-DECOR evidence may exist even when a value cannot be
written directly without a transform.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .cda.datatypes import base_datatype as _catalogue_base_datatype
from .cda.datatypes import value_representation
from .cda.model import ValueRepresentationKind
from .cda.terminology import (
    NULL_FLAVORS_WITH_ORIGINAL_TEXT,
    required_binding_allows_null_flavor,
)


def binding_strength(binding: Mapping[str, Any]) -> str:
    """Return the canonical ART-DECOR coding-strength name."""
    raw = str(binding.get("strength") or "required").casefold()
    return {"cne": "required", "cwe": "extensible"}.get(raw, raw)


def required_value_set_ids(target: Mapping[str, Any]) -> set[str]:
    """Return only bindings that constrain instance conformance."""
    bindings = target.get("value_set_bindings", [])
    if isinstance(bindings, list) and bindings:
        return {
            str(item.get("id") or "")
            for item in bindings if isinstance(item, Mapping)
            and binding_strength(item) == "required" and item.get("id")
        }
    # Compatibility with models compiled before strength was retained. The
    # ART-DECOR schema default is required.
    return {str(value) for value in target.get("value_sets", []) if value}


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
    if not value:
        return ""
    return _catalogue_base_datatype(str(value))


def type_match(model_type: str, cda_type: str | None) -> bool:
    representation = value_representation(cda_type)
    return bool(representation and model_type in representation.logical_types)


def target_type_match(model_type: str, target: Mapping[str, Any]) -> bool:
    return model_type in {
        str(item) for item in target.get("logical_types", [])
    }


def payload_match(model_type: str, target: Mapping[str, Any]) -> bool:
    return bool(target.get("writable")) and target_type_match(model_type, target)


def _value_set_ids(value: Any) -> set[str]:
    items = value if isinstance(value, (list, tuple, set)) else [value]
    result: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            oid = item.get("id") or item.get("value_set")
        else:
            oid = item
        if oid:
            result.add(str(oid))
    return result


def _shared_coded_element_payload(
    field: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    """Allow a code element only when formal terminology proves the payload."""
    if str(field.get("type") or "") != "code":
        return False
    representation = target.get("value_representation", {})
    if (
        not isinstance(representation, Mapping)
        or representation.get("kind") != ValueRepresentationKind.CODED.value
    ):
        return False
    if target.get("fixed") or target.get("fixed_text") or target.get("codes"):
        return False

    field_sets = _value_set_ids(field.get("value_sets"))
    field_sets.update(_value_set_ids(field.get("value_set_refs")))
    formal = field.get("formal_terminology")
    if isinstance(formal, Mapping):
        field_sets.update(_value_set_ids(formal.get("value_sets")))
    target_sets = required_value_set_ids(target)
    return bool(field_sets & target_sets)


def _unit_key(value: Any) -> str:
    text = str(value or "").strip().casefold().replace(" ", "")
    aliases = {
        "mmhg": "mm[hg]", "mm[hg]": "mm[hg]",
        "°c": "cel", "degc": "cel", "cel": "cel",
        "1/min": "/min", "min-1": "/min",
        "stunde": "h", "stunden": "h",
    }
    return aliases.get(text, text)


def units_equivalent(left: Any, right: Any) -> bool:
    """Compare source and CDA units using the reviewed spelling aliases."""
    return _unit_key(left) == _unit_key(right)


def unit_match(field: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    if str(field.get("type") or "") not in {"quantity", "duration"}:
        return True
    model_unit = field.get("unit")
    target_unit = target.get("unit")
    if not model_unit or not target_unit:
        return True
    return units_equivalent(model_unit, target_unit)


def direct_compatibility(
    field: Mapping[str, Any], target: Mapping[str, Any], *, explicit_path: bool = False
) -> tuple[bool, list[str]]:
    model_type = str(field.get("type") or "")
    if not model_type:
        return False, ["dataset node has no value datatype"]
    ordinal_payload = False
    if model_type == "ordinal":
        coded = any(
            isinstance(info, Mapping) and info.get("code")
            for info in accepted_values(field).values()
        )
        representation = target.get("value_representation", {})
        kind = representation.get("kind") if isinstance(representation, Mapping) else None
        allowed = {ValueRepresentationKind.CODED.value} if coded else {ValueRepresentationKind.QUANTITY.value}
        if kind not in allowed:
            return False, [
                f"ordinal representation ({'coded' if coded else 'numeric'}) is incompatible with CDA {target.get('datatype') or 'container'}"
            ]
        ordinal_payload = True
    elif not target_type_match(model_type, target):
        return False, [f"datatype {model_type} is incompatible with CDA {target.get('datatype') or 'container'}"]
    if not target.get("writable"):
        return False, [f"CDA target {target.get('path') or '?'} is structural, fixed, prohibited, or ambiguous"]
    if (
        not explicit_path
        and not ordinal_payload
        and not payload_match(model_type, target)
        and not _shared_coded_element_payload(field, target)
    ):
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
    representation = target.get("value_representation", {})
    kind_value = representation.get("kind") if isinstance(representation, Mapping) else None
    logical_types = set(target.get("logical_types", []))
    attribute = representation.get("attribute") if isinstance(representation, Mapping) else None
    if kind == "enum":
        table = transform.get("map", {})
        values = [item for item in table.values() if item is not None] if isinstance(table, Mapping) else []
        if attribute == "nullFlavor":
            if not all(isinstance(item, str) for item in values):
                reasons.append("nullFlavor enum transform must produce strings")
        elif kind_value == ValueRepresentationKind.XML_ATTRIBUTE.value and "boolean" in logical_types:
            if not all(isinstance(item, bool) for item in values):
                reasons.append("boolean CDA target requires boolean enum outputs")
        elif kind_value == ValueRepresentationKind.QUANTITY.value:
            if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
                reasons.append(f"numeric CDA {target.get('datatype')} requires numeric enum outputs")
        elif kind_value == ValueRepresentationKind.CODED.value:
            if not all(isinstance(item, (str, Mapping)) for item in values):
                reasons.append("coded CDA target requires string/coded enum outputs")
        elif not values:
            reasons.append("enum transform has no non-null output")
    elif kind == "ordinal":
        if kind_value != ValueRepresentationKind.QUANTITY.value:
            reasons.append(f"ordinal transform requires numeric CDA target, got {target.get('datatype') or 'container'}")
    elif kind == "not":
        if str(field.get("type") or "") != "boolean" or "boolean" not in logical_types:
            reasons.append("not transform requires boolean dataset and CDA values")
    elif kind == "code_system":
        if (
            str(field.get("type") or "") != "code"
            or kind_value != ValueRepresentationKind.CODED.value
            or not str(transform.get("code_system") or "")
        ):
            reasons.append(
                "code_system transform requires a coded dataset field, a coded CDA target, and one code system"
            )
    elif kind == "coded_fallback":
        allowed = transform.get("allowed", [])
        if (
            str(field.get("type") or "") != "code"
            or kind_value != ValueRepresentationKind.CODED.value
            or not isinstance(allowed, list)
            or not all(
                isinstance(item, Mapping)
                and item.get("code")
                and item.get("codeSystem")
                for item in allowed
            )
            or not str(transform.get("null_flavor") or "")
        ):
            reasons.append(
                "coded_fallback transform requires a coded dataset field, a coded CDA target, allowed target members, and a null flavor"
            )
        null_flavor = str(transform.get("null_flavor") or "")
        if null_flavor not in NULL_FLAVORS_WITH_ORIGINAL_TEXT:
            reasons.append(
                "coded_fallback null flavor cannot retain an alternate value in originalText"
            )
        elif not required_binding_allows_null_flavor(target, null_flavor):
            reasons.append(
                "coded_fallback null flavor is not admitted by the target's required binding"
            )
    elif kind == "coded_only":
        if (
            str(field.get("type") or "") != "code"
            or kind_value != ValueRepresentationKind.CODED.value
        ):
            reasons.append(
                "coded_only requires a coded dataset field and coded CDA target"
            )
    elif kind == "coded_or_original_text":
        null_flavor = str(transform.get("null_flavor") or "")
        if kind_value != ValueRepresentationKind.CODED.value:
            reasons.append("coded_or_original_text requires a coded CDA target")
        if null_flavor not in NULL_FLAVORS_WITH_ORIGINAL_TEXT:
            reasons.append(
                "coded_or_original_text null flavor cannot retain originalText"
            )
        elif not target.get("permits_null_flavor"):
            reasons.append(
                "coded_or_original_text target does not permit nullFlavor"
            )
        elif required_value_set_ids(target) and not required_binding_allows_null_flavor(
            target, null_flavor
        ):
            reasons.append(
                "coded_or_original_text null flavor is not admitted by the "
                "target's required binding"
            )
    elif kind == "narrative":
        if "text" not in logical_types:
            reasons.append("narrative transform requires a textual CDA target")
    elif kind == "reviewed_coded_map":
        cases = transform.get("map", {})
        outputs = [
            case.get("value")
            for case in cases.values()
            if isinstance(case, Mapping)
        ] if isinstance(cases, Mapping) else []
        if (
            str(field.get("type") or "") != "code"
            or kind_value != ValueRepresentationKind.CODED.value
            or not outputs
            or not all(isinstance(output, Mapping) for output in outputs)
        ):
            reasons.append(
                "reviewed_coded_map requires a finite coded dataset field, "
                "a coded CDA target, and reviewed coded outputs"
            )
        elif any(
            output.get("nullFlavor") and not target.get("permits_null_flavor")
            for output in outputs
        ):
            reasons.append(
                "reviewed_coded_map target does not permit its configured null flavor"
            )
    else:
        reasons.append(f"unknown transform type {kind!r}")
    repeat_chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
    target_repeats = list(target.get("repeat_ancestors") or ([] if not target.get("repeatable") else ["*"]))
    if repeat_chain and len(repeat_chain) != len(target_repeats):
        reasons.append(
            f"dataset has {len(repeat_chain)} repetition level(s) but CDA target has {len(target_repeats)}"
        )
    return not reasons, reasons
