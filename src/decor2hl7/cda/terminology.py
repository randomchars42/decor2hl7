"""CDA terminology and null-flavor conformance helpers.

This module contains only HL7-wide vocabulary mechanics. Transaction-specific
codes, labels, ValueSet identifiers, and template identities remain compiled
data.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..transforms import reviewed_coded_map_binding


NULL_FLAVOR_CODE_SYSTEM = "2.16.840.1.113883.5.1008"
NULL_FLAVORS = frozenset({
    "NI", "INV", "DER", "OTH", "NINF", "PINF", "UNC", "MSK", "NA",
    "UNK", "ASKU", "NAV", "NASK", "TRC",
})

# These null flavors describe an alternate value that can be carried in the
# coded datatype's originalText companion. This is datatype semantics, not a
# transaction-specific fallback table.
NULL_FLAVORS_WITH_ORIGINAL_TEXT = frozenset({"OTH", "UNC"})
ORIGINAL_TEXT_NULL_FLAVOR_PREFERENCE = ("OTH", "UNC")


def null_flavor(value: Any) -> str:
    """Return the HL7 null flavor represented by a normalized CDA value."""
    if not isinstance(value, Mapping):
        return ""
    direct = str(value.get("nullFlavor") or value.get("null_flavor") or "")
    if direct:
        return direct
    system = str(value.get("codeSystem") or value.get("code_system") or "")
    code = str(value.get("code") or "")
    if system == NULL_FLAVOR_CODE_SYSTEM and code in NULL_FLAVORS:
        return code
    return ""


def required_binding_allows_null_flavor(
    target: Mapping[str, Any], flavor: str,
) -> bool:
    """Apply required-binding semantics to one datatype-legal null flavor.

    ART-DECOR's generated vocabulary assertion tests a code against the bound
    ValueSet *or* accepts ``@nullFlavor``. Ordinary no-information flavors do
    not claim an alternate coded member and are therefore not ValueSet
    extensions. OTH and UNC do carry an alternate value through originalText;
    those remain restricted to an explicit binding exception (or the separate
    exact reviewed-map authorization).
    """
    if flavor not in NULL_FLAVORS or not target.get("permits_null_flavor"):
        return False
    if flavor not in NULL_FLAVORS_WITH_ORIGINAL_TEXT:
        return True
    required = list(target.get("required_binding_constraints", []))
    if not required:
        return True
    return flavor in {
        str(value) for value in target.get("null_flavor_exceptions", [])
    }


def complete_required_binding_code(
    value: Any,
    target: Mapping[str, Any],
    terminology_constraints: Mapping[str, Any] | None,
) -> Any:
    """Attach the one code system proven by a required target binding.

    Site and mapping configuration may use a scalar code when the compiled
    target ValueSet proves exactly one formal identity for it. Ambiguous or
    unresolved identities remain untouched and are rejected by conformance.
    """
    if null_flavor(value):
        return value
    required_keys = [
        str(key) for key in target.get("required_binding_constraints", [])
        if str(key)
    ]
    if not required_keys:
        return value
    if isinstance(value, Mapping):
        code = str(value.get("code") or "")
        supplied_system = str(
            value.get("codeSystem") or value.get("code_system") or ""
        )
        if not code or supplied_system:
            return value
    else:
        code = str(value or "")
        if not code:
            return value
    registry = terminology_constraints or {}
    systems = {
        str(member[1])
        for key in required_keys
        for binding in [
            registry.get(key, {}) if isinstance(registry, Mapping) else {}
        ]
        if isinstance(binding, Mapping) and binding.get("resolved")
        for member in binding.get("members", [])
        if str(member[0]) == code and str(member[1])
    }
    if len(systems) != 1:
        return value
    if isinstance(value, Mapping):
        completed = dict(value)
        completed["codeSystem"] = next(iter(systems))
        return completed
    return {"code": code, "codeSystem": next(iter(systems))}


def required_binding_value_error(
    value: Any,
    target: Mapping[str, Any],
    terminology_constraints: Mapping[str, Any] | None,
) -> str | None:
    """Return a required-binding violation for one CDA coded value, if any."""
    value = complete_required_binding_code(
        value, target, terminology_constraints,
    )
    flavor = null_flavor(value)
    required_keys = [
        str(key) for key in target.get("required_binding_constraints", [])
        if str(key)
    ]
    reviewed_binding = reviewed_coded_map_binding(value)
    registry = terminology_constraints or {}
    reviewed_unresolved = bool(
        reviewed_binding
        and set(required_keys) == {reviewed_binding}
        and isinstance(registry, Mapping)
        and isinstance(registry.get(reviewed_binding), Mapping)
        and not registry[reviewed_binding].get("resolved")
    )
    if flavor:
        if flavor not in NULL_FLAVORS:
            return f"invalid HL7 nullFlavor {flavor!r}"
        if not target.get("permits_null_flavor"):
            return f"CDA target does not permit nullFlavor {flavor!r}"
        if reviewed_unresolved and flavor in NULL_FLAVORS_WITH_ORIGINAL_TEXT:
            return None
        if required_keys and not required_binding_allows_null_flavor(target, flavor):
            identities = ", ".join(required_keys)
            return (
                f"nullFlavor {flavor!r} is not an explicit exception of "
                f"required ART-DECOR binding(s) {identities}"
            )
        return None

    if not required_keys:
        return None
    bindings = [
        registry.get(key, {}) if isinstance(registry, Mapping) else {}
        for key in required_keys
    ]
    resolved = [
        binding for binding in bindings
        if isinstance(binding, Mapping) and binding.get("resolved")
    ]
    if not resolved:
        if reviewed_unresolved:
            return None
        return (
            "required ART-DECOR binding membership is unavailable for "
            + ", ".join(required_keys)
        )

    if isinstance(value, Mapping):
        code = str(value.get("code") or "")
        system = str(value.get("codeSystem") or value.get("code_system") or "")
    else:
        code = str(value or "")
        system = ""
    if not code:
        return "required ART-DECOR coded binding needs a code or legal nullFlavor"

    admitted = any(
        any(
            code == str(member[0])
            and (
                not str(member[1])
                or system == str(member[1])
            )
            for member in binding.get("members", [])
        )
        for binding in resolved
    )
    if admitted:
        return None
    identities = ", ".join(
        str(binding.get("id") or key)
        for key, binding in zip(required_keys, bindings)
    )
    rendered = f"code {code!r}"
    if system:
        rendered += f" in code system {system!r}"
    return f"{rendered} is outside required ART-DECOR binding(s) {identities}"


def reviewed_coded_map_rule_errors(
    transform: Mapping[str, Any],
    field: Mapping[str, Any],
    target: Mapping[str, Any],
    targets: Mapping[str, Any],
    terminology_constraints: Mapping[str, Any] | None,
) -> list[str]:
    """Validate one exact, finite reviewed mapping over an unresolved binding.

    This rule does not complete or alias terminology. It admits only the
    explicitly listed source concept identities and output values at one exact
    required target ValueSet revision. If that revision later resolves, normal
    formal membership replaces the temporary reviewed authorization.
    """
    errors: list[str] = []
    logical = field.get("logical_domain", {})
    options = (
        logical.get("options", {}) if isinstance(logical, Mapping) else {}
    )
    expected_options = {
        str(label): str(info.get("concept_id") or "")
        for label, info in options.items()
        if isinstance(info, Mapping) and info.get("concept_id")
    } if isinstance(options, Mapping) else {}
    configured_options = transform.get("source_options", {})
    configured_options = {
        str(label): str(concept_id)
        for label, concept_id in configured_options.items()
    } if isinstance(configured_options, Mapping) else {}
    if not expected_options:
        errors.append(
            "reviewed_coded_map requires a finite logical source domain with "
            "exact concept identities"
        )
    elif configured_options != expected_options:
        errors.append(
            "reviewed_coded_map source_options must equal every executable "
            "logical source option and concept identity"
        )

    binding = transform.get("value_set", {})
    binding = binding if isinstance(binding, Mapping) else {}
    binding_id = str(binding.get("id") or "")
    binding_effective = str(binding.get("effective_date") or "")
    registry = terminology_constraints or {}
    matching: list[tuple[str, Mapping[str, Any]]] = []
    for key in target.get("required_binding_constraints", []):
        key_text = str(key)
        compiled = (
            registry.get(key_text, {}) if isinstance(registry, Mapping) else {}
        )
        if not isinstance(compiled, Mapping):
            continue
        if binding_id and str(compiled.get("id") or "") != binding_id:
            continue
        effective = str(
            compiled.get("resolved_effective_date")
            or compiled.get("effective_date") or ""
        )
        if binding_effective and effective != binding_effective:
            continue
        matching.append((key_text, compiled))
    if len(matching) != 1:
        errors.append(
            "reviewed_coded_map must identify one exact required target ValueSet revision"
        )
        return errors

    _, compiled_binding = matching[0]
    cases = transform.get("map", {})
    cases = cases if isinstance(cases, Mapping) else {}
    outputs = [
        case.get("value")
        for case in cases.values()
        if isinstance(case, Mapping) and isinstance(case.get("value"), Mapping)
    ]
    null_outputs = [
        output for output in outputs
        if str(output.get("nullFlavor") or "")
    ]
    for output in null_outputs:
        flavor = str(output.get("nullFlavor") or "")
        if flavor not in NULL_FLAVORS_WITH_ORIGINAL_TEXT:
            errors.append(
                f"reviewed_coded_map null flavor {flavor!r} cannot retain the "
                "reviewed source wording in originalText"
            )
        elif not target.get("permits_null_flavor"):
            errors.append(
                f"reviewed_coded_map target does not permit nullFlavor {flavor!r}"
            )

    if null_outputs:
        locations = list(target.get("locations", []))
        target_path = str(target.get("path") or "")
        original_text = [
            candidate
            for candidate in targets.values()
            if isinstance(candidate, Mapping)
            and candidate.get("writable")
            and candidate.get("content_role") == "coded_original_text"
            and len(candidate.get("locations", [])) == 1
            and len(locations) == 1
            and str(candidate["locations"][0]).startswith(str(locations[0]) + ".")
            and str(candidate.get("path") or "").rsplit("/", 1)[0]
            == target_path
        ]
        if len(original_text) != 1:
            errors.append(
                "reviewed_coded_map null values require one writable "
                "coded_original_text companion"
            )

    if compiled_binding.get("resolved"):
        for output in outputs:
            binding_error = required_binding_value_error(
                output, target, registry,
            )
            if binding_error:
                errors.append(
                    "reviewed_coded_map output conflicts with the now-resolved "
                    f"target binding: {binding_error}"
                )
    return errors


def coded_fallback_rule_errors(
    transform: Mapping[str, Any],
    target: Mapping[str, Any],
    targets: Mapping[str, Any],
    terminology_constraints: Mapping[str, Any] | None,
) -> list[str]:
    """Validate the complete target-governed open-code fallback contract."""
    errors: list[str] = []
    flavor = str(transform.get("null_flavor") or "")
    if flavor not in NULL_FLAVORS_WITH_ORIGINAL_TEXT:
        errors.append(
            "coded_fallback requires a null flavor that represents an "
            "alternate value with originalText"
        )
    elif not required_binding_allows_null_flavor(target, flavor):
        errors.append(
            f"coded_fallback null flavor {flavor!r} is not an explicit "
            "exception of the target's required binding"
        )

    binding = transform.get("value_set", {})
    binding = binding if isinstance(binding, Mapping) else {}
    binding_id = str(binding.get("id") or "")
    binding_effective = str(binding.get("effective_date") or "")
    registry = terminology_constraints or {}
    matching: list[tuple[str, Mapping[str, Any]]] = []
    for key in target.get("required_binding_constraints", []):
        key_text = str(key)
        compiled = (
            registry.get(key_text, {}) if isinstance(registry, Mapping) else {}
        )
        if not isinstance(compiled, Mapping):
            continue
        if binding_id and str(compiled.get("id") or "") != binding_id:
            continue
        effective = str(
            compiled.get("resolved_effective_date")
            or compiled.get("effective_date") or ""
        )
        if binding_effective and effective != binding_effective:
            continue
        matching.append((key_text, compiled))
    if len(matching) != 1:
        errors.append(
            "coded_fallback must identify one exact required target ValueSet revision"
        )
    elif not matching[0][1].get("resolved"):
        errors.append("coded_fallback target ValueSet membership is unresolved")
    else:
        expected = {
            (str(member[0]), str(member[1]))
            for member in matching[0][1].get("members", [])
            if str(member[0])
            and str(member[1]) != NULL_FLAVOR_CODE_SYSTEM
        }
        configured = {
            (
                str(member.get("code") or ""),
                str(member.get("codeSystem") or ""),
            )
            for member in transform.get("allowed", [])
            if isinstance(member, Mapping)
            and member.get("code") and member.get("codeSystem")
        }
        if configured != expected:
            errors.append(
                "coded_fallback allowed members must equal the exact non-null "
                "members of its required target ValueSet"
            )

    locations = list(target.get("locations", []))
    target_path = str(target.get("path") or "")
    original_text = [
        candidate
        for candidate in targets.values()
        if isinstance(candidate, Mapping)
        and candidate.get("writable")
        and candidate.get("content_role") == "coded_original_text"
        and len(candidate.get("locations", [])) == 1
        and len(locations) == 1
        and str(candidate["locations"][0]).startswith(str(locations[0]) + ".")
        and str(candidate.get("path") or "").rsplit("/", 1)[0] == target_path
    ]
    if len(original_text) != 1:
        errors.append(
            "coded_fallback requires one writable coded_original_text companion"
        )
    return errors
