"""Resolve model values into CDA target assignments.

Scalar transforms answer "what value?".  Structural bindings answer "which
occurrence?" or "how do several sources share a target?".  Keeping that logic
outside the XML renderer makes the mapping contract executable and reviewable.
"""
from __future__ import annotations

from typing import Any, Mapping

from .data import field_value
from .semantics import identifier_root_for_target, transformed_compatibility
from .cda.model import ValueRepresentationKind
from .cda.terminology import (
    NULL_FLAVORS,
    required_binding_allows_null_flavor,
    required_binding_value_error,
)
from .transforms import (
    OMIT,
    apply_transform,
    cda_target_name,
    mapping_rules,
    validate_transform,
)

FALLBACK_IF_ACTIVE_MARKER = "__fallback_if_active__"
SITE_REQUIREMENT_CHANNELS = frozenset({"values", "fallback_if_active"})


class _CodedOriginalTextAuthorization:
    """In-memory capability for an explicitly reviewed coded composition."""


_CODED_ORIGINAL_TEXT_AUTHORIZATION = _CodedOriginalTextAuthorization()
_CODED_ORIGINAL_TEXT_MARKER = "__decor2hl7_coded_original_text__"


def fallback_if_active_value(value: Any) -> dict[str, Any]:
    """Mark a source fallback that must not activate an optional CDA branch."""
    return {FALLBACK_IF_ACTIVE_MARKER: value}


def is_fallback_if_active(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and FALLBACK_IF_ACTIVE_MARKER in value
    )


def unwrap_fallback_if_active(value: Any) -> Any:
    return (
        value.get(FALLBACK_IF_ACTIVE_MARKER)
        if is_fallback_if_active(value) else value
    )


def authorizes_coded_original_text(value: Any) -> bool:
    """Return whether a runtime-composed coded value authorizes originalText.

    The identity-only marker cannot be supplied through JSON input or site
    configuration.  It is used for an owner-reviewed representation such as
    an uncoded medication name carried by ``code nullFlavor=\"NA\"``.
    """
    return (
        isinstance(value, Mapping)
        and value.get(_CODED_ORIGINAL_TEXT_MARKER)
        is _CODED_ORIGINAL_TEXT_AUTHORIZATION
    )


def _authorize_coded_original_text(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(value),
        _CODED_ORIGINAL_TEXT_MARKER: _CODED_ORIGINAL_TEXT_AUTHORIZATION,
    }


def presence_target_complete(
    cda: Mapping[str, Any], target: Mapping[str, Any],
) -> bool:
    """Return whether presence can activate a fully supplied statement.

    Every required descendant must be supplied by the compiled template or a
    compiler-owned runtime role. This keeps a fixed identifying code from
    hiding an unrelated mandatory, empty clinical value.
    """
    locations = list(target.get("locations", []))
    if len(locations) != 1:
        return False
    nodes = list(cda.get("document", []))
    root: Mapping[str, Any] | None = None
    try:
        for raw_index in str(locations[0]).split("."):
            root = nodes[int(raw_index)]
            nodes = list(root.get("children", []))
    except (IndexError, TypeError, ValueError):
        return False
    if root is None:
        return False

    targets = cda.get("targets", {})

    def complete(node: Mapping[str, Any]) -> bool:
        if str(node.get("conformance") or "").upper() == "NP":
            return True
        codes = list(node.get("codes", []))
        fixed = dict(node.get("fixed", {}))
        representation: Mapping[str, Any] = next((
            targets.get(str(name), {}).get("value_representation")
            for name in node.get("targets", [])
            if targets.get(str(name), {}).get("value_representation")
        ), {})
        represented_attributes = {
            str(name) for name in (
                list(representation.get("attributes", []))
                + [representation.get("attribute")]
                + [representation.get("scalar_attribute")]
            ) if name
        } if isinstance(representation, Mapping) else set()
        scalar_attributes = {
            str(name) for name in (
                [representation.get("attribute")]
                + [representation.get("scalar_attribute")]
            ) if name
        } if isinstance(representation, Mapping) else set()
        representation_kind = (
            str(representation.get("kind") or "")
            if isinstance(representation, Mapping) else ""
        )
        scalar_fixed = bool(
            node.get("fixed_text") is not None
            or len(codes) == 1
            or node.get("system_value")
            or any(name in fixed for name in scalar_attributes)
            or (
                representation_kind == "identifier"
                and any(name in fixed for name in represented_attributes)
            )
        )
        for attribute in node.get("attributes", []):
            if attribute.get("optional") is not False:
                continue
            name = str(attribute.get("name") or "")
            supplied_by_code = bool(
                len(codes) == 1
                and (
                    (name == "code" and codes[0].get("code") is not None)
                    or (
                        name == "codeSystem"
                        and codes[0].get("code_system") is not None
                    )
                )
            )
            if (
                attribute.get("value") is None
                and name not in fixed
                and not supplied_by_code
                and not attribute.get("system_value")
                and not (scalar_fixed and name in represented_attributes)
            ):
                return False

        required_children = [
            child for child in node.get("children", [])
            if str(child.get("conformance") or "").upper() != "NP"
            and (
                child.get("mandatory")
                or int(child.get("min") or 0) >= 1
            )
        ]
        if not all(complete(child) for child in required_children):
            return False

        required = bool(
            node.get("mandatory") or int(node.get("min") or 0) >= 1
        )
        if not required:
            return True
        if representation:
            return scalar_fixed
        return bool(
            fixed or node.get("fixed_text") is not None or required_children
        )

    return complete(root)


def structure_rules(mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = mapping.get("structures", {})
    if isinstance(raw, Mapping):
        return [
            {"id": str(name), **dict(rule)}
            for name, rule in raw.items() if isinstance(rule, Mapping)
        ]
    if isinstance(raw, list):
        return [dict(rule) for rule in raw if isinstance(rule, Mapping)]
    return []


def _structure_sources(rule: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize legacy string and transform-bearing structure sources."""
    result: list[dict[str, Any]] = []
    for item in rule.get("sources", []):
        if isinstance(item, str):
            result.append({"source": item})
        elif isinstance(item, Mapping) and item.get("source"):
            result.append(dict(item))
    return result


def construction_supplied_targets(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    site: Mapping[str, Any] | None = None,
) -> set[str]:
    """Return physical CDA targets that configuration can supply.

    This is deliberately a capability calculation, not a claim that every
    input record contains a value.  It covers scalar field rules, reviewed
    target defaults, declared site requirements, actual site values, and
    constants owned by structural rules.
    """
    datapoints = cda.get("datapoints", {})

    def physical(name: Any) -> str:
        configured = str(name or "")
        logical = (
            datapoints.get(configured, {})
            if isinstance(datapoints, Mapping) else {}
        )
        if isinstance(logical, Mapping) and logical.get("cda_target"):
            return str(logical["cda_target"])
        return configured

    supplied: set[str] = set()
    for selection in mapping.get("fields", {}).values():
        for rule in mapping_rules(selection):
            supplied.add(physical(rule.get("cda_target") or rule.get("target")))
    for name in mapping.get("target_defaults", {}):
        supplied.add(physical(name))
    supplied.update(site_requirement_targets(cda, mapping))
    for rule in structure_rules(mapping):
        for key in ("target", "cda_target", "discriminator"):
            if rule.get(key):
                supplied.add(physical(rule[key]))
        for branch in rule.get("branches", []):
            if not isinstance(branch, Mapping):
                continue
            for key in ("target", "cda_target", "discriminator"):
                if branch.get(key):
                    supplied.add(physical(branch[key]))
            constants = branch.get("constants", {})
            if isinstance(constants, Mapping):
                supplied.update(physical(name) for name in constants)
        constants = rule.get("constants", {})
        if isinstance(constants, Mapping):
            supplied.update(physical(name) for name in constants)
    site_cda = site.get("cda", {}) if isinstance(site, Mapping) else {}
    if isinstance(site_cda, Mapping):
        for key in ("values", "fallback_if_active"):
            values = site_cda.get(key, {})
            if isinstance(values, Mapping):
                supplied.update(physical(name) for name in values)
    return {name for name in supplied if name}


def _construction_activating_targets(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    site: Mapping[str, Any] | None = None,
) -> set[str]:
    """Return capabilities that may select an otherwise optional branch."""
    datapoints = cda.get("datapoints", {})

    def physical(name: Any) -> str:
        configured = str(name or "")
        logical = (
            datapoints.get(configured, {})
            if isinstance(datapoints, Mapping) else {}
        )
        if isinstance(logical, Mapping) and logical.get("cda_target"):
            return str(logical["cda_target"])
        return configured

    activating: set[str] = set()
    for selection in mapping.get("fields", {}).values():
        for rule in mapping_rules(selection):
            if rule.get("mode") != "fallback_if_active":
                activating.add(physical(
                    rule.get("cda_target") or rule.get("target")
                ))
    site_cda = site.get("cda", {}) if isinstance(site, Mapping) else {}
    if isinstance(site_cda, Mapping):
        values = site_cda.get("values", {})
        if isinstance(values, Mapping):
            activating.update(physical(name) for name in values)
    activating.update(site_requirement_targets(
        cda, mapping, channels={"values"},
    ))
    for name, target in cda.get("targets", {}).items():
        if (
            isinstance(target, Mapping) and target.get("system_value")
            and target.get("system_value") != "generated_identifier"
        ):
            activating.add(str(name))
    return {name for name in activating if name}


def _required_construction_gap_details(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    site: Mapping[str, Any] | None = None,
) -> tuple[list[str], set[str]]:
    """Find mandatory active CDA slots with no configured value source.

    The traversal mirrors the owner-defined cardinality and choice rules used
    by the renderer.  It does not manufacture clinical defaults: a mandatory
    leaf is constructible only when the compiled template, document-production
    infrastructure, or explicit mapping/site configuration supplies it.
    """
    targets = cda.get("targets", {})
    supplied = construction_supplied_targets(cda, mapping, site)
    activating = _construction_activating_targets(cda, mapping, site)
    supplied_locations: set[tuple[int, ...]] = set()
    for name in activating:
        target = targets.get(name, {})
        if not isinstance(target, Mapping):
            continue
        for raw in target.get("locations", []):
            try:
                location = tuple(int(part) for part in str(raw).split("."))
            except ValueError:
                continue
            supplied_locations.update(
                location[:depth] for depth in range(1, len(location) + 1)
            )

    gaps: list[str] = []
    gap_targets: set[str] = set()

    def record_gap(message: str, names: Any) -> None:
        gaps.append(message)
        gap_targets.update(
            str(name) for name in names
            if str(name) in targets
        )

    def required(node: Mapping[str, Any]) -> bool:
        return bool(node.get("mandatory")) or int(node.get("min") or 0) >= 1

    def active(location: tuple[int, ...]) -> bool:
        return location in supplied_locations

    def identity(node: Mapping[str, Any], location: tuple[int, ...]) -> str:
        origin = node.get("origin", {})
        label = str(
            origin.get("path") if isinstance(origin, Mapping) else ""
        ) or str(node.get("name") or ".".join(map(str, location)))
        template_id = (
            str(origin.get("template_id") or "")
            if isinstance(origin, Mapping) else ""
        )
        effective = (
            str(origin.get("template_effective_date") or "dynamic")
            if isinstance(origin, Mapping) else "dynamic"
        )
        return f"{label} [{template_id}@{effective}]" if template_id else label

    def has_target_value(node: Mapping[str, Any]) -> bool:
        return any(str(name) in supplied for name in node.get("targets", []))

    def has_compiled_scalar(node: Mapping[str, Any]) -> bool:
        return bool(
            node.get("fixed")
            or node.get("fixed_text") is not None
            or len(node.get("codes") or []) == 1
            or node.get("system_value")
            or node.get("content_role")
            or has_target_value(node)
        )

    def attribute_is_supplied(
        node: Mapping[str, Any], attribute: Mapping[str, Any], node_value: bool,
    ) -> bool:
        name = str(attribute.get("name") or "")
        if (
            attribute.get("value") is not None
            or name in node.get("fixed", {})
            or attribute.get("system_value")
            or any(str(name) in supplied for name in attribute.get("targets", []))
        ):
            return True
        if not node_value:
            return False
        represented_value: Any = next((
            targets.get(str(name), {}).get("value_representation")
            for name in node.get("targets", [])
            if targets.get(str(name), {}).get("value_representation")
        ), {})
        if not isinstance(represented_value, Mapping):
            return False
        represented: Mapping[str, Any] = represented_value
        represented_names = {
            str(name) for name in (
                list(represented.get("attributes") or [])
                + [represented.get("attribute")]
                + [represented.get("scalar_attribute")]
            ) if name
        }
        return name in represented_names

    def visit(
        node: Mapping[str, Any], location: tuple[int, ...], selected: bool = False,
    ) -> bool:
        if str(node.get("conformance") or "").upper() == "NP":
            return False
        kind = str(node.get("kind") or "")
        transparent = kind in {"include", "template", "datatype_choice"}
        occurs = (
            required(node) or selected or active(location)
            or has_target_value(node)
        )
        if transparent:
            occurs = occurs or bool(node.get("transparent_inline"))
        if not occurs:
            return False

        children = list(node.get("children", []))
        rendered_children: list[bool] = []
        if kind == "choice":
            selected_indices = [
                index for index, _child in enumerate(children)
                if active(location + (index,))
            ]
            minimum = int(node.get("min") or 0)
            for index in range(len(children)):
                if len(selected_indices) >= minimum:
                    break
                if index not in selected_indices:
                    selected_indices.append(index)
            for index in selected_indices:
                rendered_children.append(visit(
                    children[index], location + (index,), selected=True,
                ))
            return any(rendered_children)

        node_value = has_compiled_scalar(node)
        attribute_content = False
        for attribute in node.get("attributes", []):
            attribute_supplied = attribute_is_supplied(
                node, attribute, node_value,
            )
            attribute_content = attribute_content or attribute_supplied
            if attribute.get("optional") is False and not attribute_supplied:
                record_gap(
                    f"required CDA attribute @{attribute.get('name')} on "
                    f"{identity(node, location)} has no fixed, mapped, site, "
                    "system, or default value",
                    list(attribute.get("targets", []))
                    + list(node.get("targets", [])),
                )
        for index, child in enumerate(children):
            rendered_children.append(visit(child, location + (index,)))

        if kind != "element":
            return node_value or any(rendered_children)
        if (
            required(node) and not node_value and not attribute_content
            and not any(rendered_children)
        ):
            if node.get("mandatory") or str(
                node.get("conformance") or ""
            ).upper() == "M":
                record_gap(
                    f"mandatory CDA element {identity(node, location)} has no "
                    "fixed, mapped, site, system, child, or default value",
                    node.get("targets", []),
                )
            elif children and not _permits_element_null_flavor_at_node(node):
                record_gap(
                    f"required complex CDA element {identity(node, location)} "
                    "has no fixed, mapped, site, system, child, or default value",
                    node.get("targets", []),
                )
        return (
            node_value or attribute_content or any(rendered_children)
            or required(node)
        )

    for index, root in enumerate(cda.get("document", [])):
        visit(root, (index,))
    return list(dict.fromkeys(gaps)), gap_targets


def required_construction_gaps(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    site: Mapping[str, Any] | None = None,
) -> list[str]:
    """Describe mandatory active CDA slots with no configured value source."""
    gaps, _targets = _required_construction_gap_details(cda, mapping, site)
    return gaps


def required_construction_gap_targets(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    site: Mapping[str, Any] | None = None,
) -> set[str]:
    """Return logical targets for mandatory active CDA slots lacking a source."""
    _gaps, targets = _required_construction_gap_details(cda, mapping, site)
    return targets


def _permits_element_null_flavor_at_node(node: Mapping[str, Any]) -> bool:
    return any(
        str(attribute.get("name") or "").split(":", 1)[-1] == "nullFlavor"
        and attribute.get("optional") is not False
        for attribute in node.get("attributes", [])
    )


def required_unmapped_null_flavor(mapping: Mapping[str, Any]) -> str:
    """Return the mapping-owned completion policy for empty required leaves."""
    defaults = mapping.get("defaults", {})
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, Mapping):
        raise ValueError("cda-mapping: defaults must be an object")
    rule = defaults.get("required_unmapped", {"nullFlavor": "NI"})
    if isinstance(rule, str):
        flavor = rule
    elif isinstance(rule, Mapping):
        flavor = str(rule.get("nullFlavor") or "")
    else:
        raise ValueError(
            "cda-mapping: defaults.required_unmapped must be a nullFlavor object"
        )
    if flavor not in NULL_FLAVORS:
        raise ValueError(
            "cda-mapping: defaults.required_unmapped has invalid nullFlavor "
            f"{flavor!r}"
        )
    return flavor


def _physical_default_target(cda: Mapping[str, Any], configured: str) -> str:
    datapoint = cda.get("datapoints", {}).get(configured, {})
    if isinstance(datapoint, Mapping) and datapoint.get("cda_target"):
        return str(datapoint["cda_target"])
    return configured


def site_requirement_targets(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    *, channels: set[str] | None = None,
) -> set[str]:
    """Return valid physical targets explicitly delegated to site config.

    A declaration is a portable ownership contract, not a value. Invalid or
    incomplete declarations never suppress a construction gap; their detailed
    diagnostics are produced by :func:`validate_site_requirements`.
    """
    raw = mapping.get("site_requirements", {})
    if not isinstance(raw, Mapping):
        return set()
    targets = cda.get("targets", {})
    result: set[str] = set()
    for configured, rule in raw.items():
        if not isinstance(rule, Mapping):
            continue
        channel = str(rule.get("channel") or "")
        reason = rule.get("reason")
        if (
            channel not in SITE_REQUIREMENT_CHANNELS
            or channels is not None and channel not in channels
            or not isinstance(reason, str) or not reason.strip()
        ):
            continue
        physical = _physical_default_target(cda, str(configured))
        target = targets.get(physical)
        if (
            not isinstance(target, Mapping)
            or target.get("prohibited") or not target.get("writable")
            or len(target.get("locations", [])) != 1
            or not (
                target.get("mandatory") or int(target.get("min") or 0) >= 1
            )
        ):
            continue
        result.add(physical)
    return result


def validate_site_requirements(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
    site: Mapping[str, Any] | None = None,
    *, require_configured: bool = True,
) -> list[str]:
    """Validate portable site ownership and, when requested, its realization."""
    errors: list[str] = []
    raw = mapping.get("site_requirements", {})
    if raw is None:
        return errors
    if not isinstance(raw, Mapping):
        return ["cda-mapping: site_requirements must be an object"]

    targets = cda.get("targets", {})
    mapping_without_requirements = dict(mapping)
    mapping_without_requirements.pop("site_requirements", None)
    portable_supplied = construction_supplied_targets(
        cda, mapping_without_requirements,
    )
    resolved: dict[str, str] = {}
    site_cda = site.get("cda", {}) if isinstance(site, Mapping) else {}
    if not isinstance(site_cda, Mapping):
        site_cda = {}

    for configured, rule in raw.items():
        name = str(configured)
        prefix = f"cda-mapping: site_requirements[{name!r}]"
        if not isinstance(rule, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        channel = str(rule.get("channel") or "")
        if channel not in SITE_REQUIREMENT_CHANNELS:
            errors.append(
                f"{prefix}.channel must be one of "
                + ", ".join(sorted(SITE_REQUIREMENT_CHANNELS))
            )
        reason = rule.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{prefix}.reason must be non-empty text")

        physical = _physical_default_target(cda, name)
        target = targets.get(physical)
        if not isinstance(target, Mapping):
            errors.append(f"{prefix} references unknown CDA target {physical!r}")
            continue
        previous = resolved.get(physical)
        if previous is not None and previous != name:
            errors.append(
                f"{prefix} conflicts with site_requirements[{previous!r}]; "
                f"both resolve to {physical!r}"
            )
        resolved[physical] = name
        if target.get("prohibited") or not target.get("writable"):
            errors.append(f"{prefix} references a prohibited/non-renderable target")
        if len(target.get("locations", [])) != 1:
            errors.append(
                f"{prefix} target {physical!r} has "
                f"{len(target.get('locations', []))} physical locations"
            )
        if not (target.get("mandatory") or int(target.get("min") or 0) >= 1):
            errors.append(
                f"{prefix} is optional; site_requirements may delegate only a "
                "required target"
            )
        if physical in portable_supplied:
            errors.append(
                f"{prefix} is already supplied by portable mapping configuration"
            )

        if not require_configured or channel not in SITE_REQUIREMENT_CHANNELS:
            continue
        configured_values = site_cda.get(channel, {})
        configured_values = (
            configured_values if isinstance(configured_values, Mapping) else {}
        )
        configured_key = next(
            (key for key in (name, physical) if key in configured_values), None
        )
        if configured_key is None or configured_values.get(configured_key) in (None, ""):
            other_channel = next(
                (
                    candidate for candidate in SITE_REQUIREMENT_CHANNELS
                    if candidate != channel
                    and isinstance(site_cda.get(candidate), Mapping)
                    and any(
                        key in site_cda[candidate] for key in (name, physical)
                    )
                ),
                None,
            )
            if other_channel:
                errors.append(
                    f"site: cda.{channel}[{name!r}] is required; the value is "
                    f"configured under cda.{other_channel}"
                )
            else:
                errors.append(f"site: cda.{channel}[{name!r}] is required")
            continue
        value = configured_values[configured_key]
        binding_error = required_binding_value_error(
            value, target, cda.get("terminology_constraints", {}),
        )
        if binding_error:
            errors.append(
                f"site: cda.{channel}[{name!r}]: {binding_error}"
            )
    return errors


def _compiled_coded_members(
    target: Mapping[str, Any], value: Any,
) -> dict[tuple[tuple[str, str], ...], dict[str, str]]:
    """Return distinct compiled coding members selected by a scalar value."""
    representation = target.get("value_representation", {})
    if (
        not isinstance(value, str)
        or not isinstance(representation, Mapping)
        or representation.get("kind") != ValueRepresentationKind.CODED.value
    ):
        return {}

    aliases = {
        "codeSystem": ("codeSystem", "code_system"),
        "codeSystemName": ("codeSystemName", "code_system_name"),
        "codeSystemVersion": ("codeSystemVersion", "code_system_version"),
        "displayName": ("displayName", "display_name"),
    }
    matches: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
    for member in target.get("codes", []):
        if not isinstance(member, Mapping) or str(member.get("code")) != value:
            continue
        coding: dict[str, str] = {"code": value}
        for attribute, source_names in aliases.items():
            source = next(
                (
                    member.get(name)
                    for name in source_names if member.get(name) is not None
                ),
                None,
            )
            if source is not None:
                coding[attribute] = str(source)
        matches[tuple(sorted(coding.items()))] = coding
    return matches


def _compiled_coded_default(
    target: Mapping[str, Any], value: Any,
) -> dict[str, str] | None:
    """Return the unique compiled coding selected by a scalar default."""
    matches = _compiled_coded_members(target, value)
    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def target_default_values(
    cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve reviewed per-target completion values to physical targets."""
    errors = validate_target_defaults(cda, mapping)
    if errors:
        raise ValueError("invalid CDA target defaults:\n" + "\n".join(errors))
    raw = mapping.get("target_defaults", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("cda-mapping: target_defaults must be an object")
    result: dict[str, Any] = {}
    owners: dict[str, str] = {}
    for configured, rule in raw.items():
        name = str(configured)
        if not isinstance(rule, Mapping):
            raise ValueError(
                f"cda-mapping: target_defaults[{name!r}] must be an object"
            )
        physical = _physical_default_target(cda, name)
        value = (
            {"nullFlavor": str(rule.get("nullFlavor") or "")}
            if "nullFlavor" in rule else rule.get("value")
        )
        if "value" in rule:
            target = cda.get("targets", {}).get(physical, {})
            compiled_coding = (
                _compiled_coded_default(target, value)
                if isinstance(target, Mapping) else None
            )
            if compiled_coding is not None:
                value = compiled_coding
        if physical in result and result[physical] != value:
            raise ValueError(
                f"cda-mapping: target defaults {owners[physical]!r} and {name!r} "
                f"resolve to {physical!r} with different values"
            )
        result[physical] = value
        owners[physical] = name
    return result


def _validate_scalar_default(
    prefix: str, target: Mapping[str, Any], value: Any,
) -> list[str]:
    """Validate one non-null construction value against its compiled slot."""
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return [f"{prefix}.value must be a non-null JSON scalar"]
    representation = target.get("value_representation", {})
    if not isinstance(representation, Mapping) or not representation.get("kind"):
        return [f"{prefix} target has no scalar value representation"]
    kind = str(representation.get("kind") or "")
    logical_types = {str(item) for item in target.get("logical_types", [])}
    if kind == ValueRepresentationKind.IDENTIFIER.value:
        return [f"{prefix} cannot use a scalar value for an identifier target"]
    if kind == ValueRepresentationKind.BOOLEAN.value or (
        kind == ValueRepresentationKind.XML_ATTRIBUTE.value
        and "boolean" in logical_types
    ):
        if not isinstance(value, bool):
            return [f"{prefix}.value must be boolean for this CDA target"]
    elif kind == ValueRepresentationKind.QUANTITY.value:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return [f"{prefix}.value must be numeric for this CDA target"]
    elif kind == ValueRepresentationKind.CODED.value and not isinstance(value, str):
        return [f"{prefix}.value must be a code string for this CDA target"]
    elif kind == ValueRepresentationKind.TIMESTAMP.value and not isinstance(value, str):
        return [f"{prefix}.value must be a timestamp string for this CDA target"]

    allowed_codes = {
        str(item.get("code"))
        for item in target.get("codes", [])
        if isinstance(item, Mapping) and item.get("code") is not None
    }
    if allowed_codes and str(value) not in allowed_codes:
        return [
            f"{prefix}.value {value!r} is outside the target's compiled code constraint"
        ]
    if kind == ValueRepresentationKind.CODED.value:
        if len(_compiled_coded_members(target, value)) > 1:
            return [
                f"{prefix}.value {value!r} has ambiguous compiled coding companions"
            ]
    return []


def validate_target_defaults(
    cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> list[str]:
    """Validate mapping completion rules without requiring runtime input."""
    errors: list[str] = []
    try:
        required_unmapped_null_flavor(mapping)
    except ValueError as error:
        errors.append(str(error))

    raw = mapping.get("target_defaults", {})
    if raw is None:
        return errors
    if not isinstance(raw, Mapping):
        errors.append("cda-mapping: target_defaults must be an object")
        return errors

    targets = cda.get("targets", {})
    resolved: dict[str, tuple[str, Any]] = {}
    for configured, rule in raw.items():
        name = str(configured)
        prefix = f"cda-mapping: target_defaults[{name!r}]"
        if not isinstance(rule, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        has_null_flavor = "nullFlavor" in rule
        has_value = "value" in rule
        if has_null_flavor == has_value:
            errors.append(
                f"{prefix} must contain exactly one of nullFlavor or value"
            )
        flavor = str(rule.get("nullFlavor") or "")
        if has_null_flavor and flavor not in NULL_FLAVORS:
            errors.append(f"{prefix} has invalid nullFlavor {flavor!r}")
        reason = rule.get("reason")
        if reason is not None and not isinstance(reason, str):
            errors.append(f"{prefix}.reason must be text")
        if has_value and (not isinstance(reason, str) or not reason.strip()):
            errors.append(f"{prefix}.reason must be non-empty text for a value default")

        physical = _physical_default_target(cda, name)
        target = targets.get(physical)
        if not isinstance(target, Mapping):
            errors.append(f"{prefix} references unknown CDA target {physical!r}")
            continue
        resolved_value: Any = (
            {"nullFlavor": flavor} if has_null_flavor else rule.get("value")
        )
        previous = resolved.get(physical)
        if previous and previous[1] != resolved_value:
            errors.append(
                f"{prefix} conflicts with target_defaults[{previous[0]!r}]; both "
                f"resolve to {physical!r}"
            )
        resolved[physical] = (name, resolved_value)
        if target.get("prohibited") or not target.get("writable"):
            errors.append(f"{prefix} references a prohibited/non-renderable target")
        if len(target.get("locations", [])) != 1:
            errors.append(
                f"{prefix} target {physical!r} has "
                f"{len(target.get('locations', []))} physical locations"
            )
        required = bool(target.get("mandatory")) or int(target.get("min") or 0) >= 1
        if not required:
            errors.append(
                f"{prefix} is optional; omit an unmapped optional element instead"
            )
        if has_null_flavor:
            if target.get("kind") != "element":
                errors.append(f"{prefix} cannot apply nullFlavor to an attribute")
            if target.get("mandatory") or str(target.get("conformance") or "").upper() == "M":
                errors.append(f"{prefix} target does not permit a nullFlavor default")
            if (
                target.get("has_children")
                and not _permits_element_null_flavor(cda, target)
            ):
                errors.append(
                    f"{prefix} targets a complex element that does not expose "
                    "an optional nullFlavor"
                )
            if (
                target.get("required_binding_constraints")
                and not required_binding_allows_null_flavor(target, flavor)
            ):
                errors.append(
                    f"{prefix} nullFlavor {flavor!r} is not an explicit "
                    "exception of the target's required binding"
                )
        elif has_value:
            errors.extend(_validate_scalar_default(prefix, target, rule.get("value")))
            if target.get("non_null_requires"):
                errors.append(
                    f"{prefix} target has compound non-null companions and cannot "
                    "use a scalar value default"
                )
    return errors


def _permits_element_null_flavor(
    cda: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    """Return whether a complex target exposes a writable optional nullFlavor."""
    if target.get("permits_null_flavor"):
        return True
    target_path = str(target.get("path") or "").rstrip("/")
    if not target_path:
        return False
    template_id = target.get("template_id")
    effective_date = target.get("template_effective_date")
    expected_path = f"{target_path}/@nullFlavor"
    for candidate in cda.get("targets", {}).values():
        if not isinstance(candidate, Mapping):
            continue
        if (
            candidate.get("kind") == "attribute"
            and candidate.get("template_id") == template_id
            and candidate.get("template_effective_date") == effective_date
            and str(candidate.get("path") or "") == expected_path
            and candidate.get("writable")
            and not candidate.get("prohibited")
            and not candidate.get("conditional_fixed")
            and not candidate.get("mandatory")
            and int(candidate.get("min") or 0) == 0
        ):
            return True
    return False


def _physical_target_name(
    cda: Mapping[str, Any], rule: Mapping[str, Any]
) -> str:
    logical = str(rule.get("target") or "")
    datapoint = cda.get("datapoints", {}).get(logical, {})
    modeled = str(datapoint.get("cda_target") or "") if isinstance(datapoint, Mapping) else ""
    configured = cda_target_name(rule)
    if modeled and configured and modeled != configured:
        raise ValueError(
            f"logical CDA datapoint {logical!r} resolves to {modeled!r}, "
            f"but the mapping specifies {configured!r}"
        )
    return modeled or configured


def _prepare_identifier(
    name: str, target: Mapping[str, Any], value: Any, site: Mapping[str, Any]
) -> Any:
    representation = target.get("value_representation", {})
    if (
        not isinstance(representation, Mapping)
        or representation.get("kind") != ValueRepresentationKind.IDENTIFIER.value
    ):
        return value
    root = identifier_root_for_target(name, target, site)
    if root is None:
        raise ValueError(f"CDA identifier target {name!r} has no fixed/configured root")

    def one(item: Any) -> Any:
        if item is None or (isinstance(item, Mapping) and item.get("nullFlavor")):
            return item
        if isinstance(item, Mapping):
            result = dict(item)
            result.setdefault("root", root)
            return result
        return {"root": root, "extension": str(item)}

    return [one(item) for item in value] if isinstance(value, list) else one(value)


def _present(value: Any) -> bool:
    if value is None or value is OMIT:
        return False
    if isinstance(value, list):
        return any(_present(item) for item in value)
    return True


def _quantity_range_projections(value: Any) -> tuple[Any, Any, Any, bool]:
    """Project mixed scalar/range occurrence trees onto compiled CDA slots."""
    if isinstance(value, list):
        projected = [_quantity_range_projections(item) for item in value]
        return (
            [item[0] for item in projected],
            [item[1] for item in projected],
            [item[2] for item in projected],
            any(item[3] for item in projected),
        )
    if isinstance(value, Mapping) and ("low" in value or "high" in value):
        return None, value.get("low"), value.get("high"), True
    return value, None, None, False


def _expand_quantity_range_assignments(
    assignments: dict[str, Any],
    targets: Mapping[str, Any],
    problems: list[str],
) -> None:
    """Route target-neutral ranges through compiler-selected bound targets."""
    for name, value in list(assignments.items()):
        scalar, low, high, contains_range = _quantity_range_projections(value)
        if not contains_range:
            continue
        target = targets.get(name, {})
        representation = target.get("value_representation", {})
        range_targets = (
            representation.get("range_targets", {})
            if isinstance(representation, Mapping) else {}
        )
        if not isinstance(range_targets, Mapping) or set(range_targets) != {
            "low", "high",
        }:
            assignments.pop(name, None)
            problems.append(
                f"CDA target {name!r} has no compiled low/high quantity targets"
            )
            continue
        assignments.pop(name, None)
        _assign(assignments, name, scalar)
        _assign(assignments, str(range_targets["low"]), low)
        _assign(assignments, str(range_targets["high"]), high)


def non_null_requirement_satisfied(
    cda: Mapping[str, Any], required: str, supplied: set[str],
) -> bool:
    """Return whether a required compound-datatype part can be populated.

    ``required`` names the compiled target for the required element.  A value
    assigned to that element or one of its descendants supplies the part.  A
    part that the template itself requires is also rendered independently of
    optional sibling assignments.
    """
    targets = cda.get("targets", {})
    required_target = targets.get(required, {})
    locations = [str(value) for value in required_target.get("locations", [])]
    if len(locations) != 1:
        return False
    if (
        required_target.get("mandatory")
        or int(required_target.get("min") or 0) >= 1
    ):
        return True
    required_location = locations[0]
    return any(
        any(
            location == required_location
            or location.startswith(required_location + ".")
            for location in map(str, targets.get(name, {}).get("locations", []))
        )
        for name in supplied
    )


def _present_occurrences(
    value: Any, prefix: tuple[int, ...] = (), *, null_flavor_exempt: bool = False,
) -> list[tuple[int, ...]]:
    if isinstance(value, list):
        return [
            occurrence
            for index, item in enumerate(value)
            for occurrence in _present_occurrences(
                item, prefix + (index,), null_flavor_exempt=null_flavor_exempt
            )
        ]
    if (
        null_flavor_exempt
        and isinstance(value, Mapping)
        and value.get("nullFlavor")
    ):
        return []
    return [prefix] if _present(value) else []


def _value_at_occurrence(value: Any, occurrence: tuple[int, ...]) -> Any:
    current = value
    for depth, index in enumerate(occurrence):
        if isinstance(current, list):
            if index >= len(current):
                return None
            current = current[index]
        else:
            # This mirrors CDA rendering: a scalar inside a repeating branch
            # supplies only the first occurrence.
            return current if all(item == 0 for item in occurrence[depth:]) else None
    return current


def non_null_requirement_problems(
    cda: Mapping[str, Any], assignments: Mapping[str, Any],
) -> list[str]:
    """Validate compound-datatype companion values for each occurrence."""
    targets = cda.get("targets", {})
    supplied = set(assignments)
    problems: list[str] = []
    for name, value in assignments.items():
        target = targets.get(name, {})
        for required in map(str, target.get("non_null_requires", [])):
            owners = {
                str(owner) for owner in target.get(
                    "non_null_requirement_owners", {}
                ).get(required, [])
            }
            dependent_occurrences = _present_occurrences(
                value, null_flavor_exempt=name in owners
            )
            if non_null_requirement_satisfied(cda, required, supplied):
                required_target = targets.get(required, {})
                required_locations = list(required_target.get("locations", []))
                if len(required_locations) != 1:
                    companion_values: list[Any] = []
                else:
                    required_location = str(required_locations[0])
                    companion_values = [
                        other_value
                        for other_name, other_value in assignments.items()
                        if any(
                            location == required_location
                            or location.startswith(required_location + ".")
                            for location in map(
                                str, targets.get(other_name, {}).get("locations", [])
                            )
                        )
                    ]
                # A required template child needs no assignment; it is emitted
                # for every active parent occurrence.
                if (
                    required_target.get("mandatory")
                    or int(required_target.get("min") or 0) >= 1
                ):
                    continue
                missing = [
                    occurrence
                    for occurrence in dependent_occurrences
                    if not any(
                        _present(_value_at_occurrence(companion, occurrence))
                        for companion in companion_values
                    )
                ]
            else:
                missing = dependent_occurrences
            for occurrence in missing:
                where = (
                    " at occurrence " + ".".join(map(str, occurrence))
                    if occurrence else ""
                )
                problems.append(
                    f"CDA target {name!r} has a non-null value{where} without "
                    f"required companion {required!r}"
                )
    return problems


def for_each_target_positions(
    field: Mapping[str, Any],
    target: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> list[int] | None:
    """Map each source repeat dimension to an explicit CDA repeat ancestor.

    ``None`` means that no complete explicit alignment exists and callers must
    retain positional compatibility.  A returned list contains, for each source
    repeat level, the index of its bound CDA repeat ancestor.
    """
    chain = list(
        field.get("repeat_chain")
        or ([] if not field.get("repeat") else [field.get("repeat")])
    )
    if not chain:
        return []
    ancestors = [str(value) for value in target.get("repeat_ancestors", [])]
    rules_by_group: dict[str, list[Mapping[str, Any]]] = {}
    for rule in structure_rules(mapping):
        if str(rule.get("type") or "") != "for_each":
            continue
        rules_by_group.setdefault(str(rule.get("source_group") or ""), []).append(rule)
    positions: list[int] = []
    targets = cda.get("targets", {})
    for group in chain:
        rules = rules_by_group.get(str(group), [])
        if len(rules) != 1:
            return None
        anchor_name = str(rules[0].get("target_repeat") or "")
        anchor = targets.get(anchor_name, {})
        locations = list(anchor.get("locations", [])) if isinstance(anchor, Mapping) else []
        location = str(locations[0]) if len(locations) == 1 else anchor_name
        if location not in ancestors:
            return None
        positions.append(ancestors.index(location))
    if positions != sorted(set(positions)):
        return None
    return positions


def _align_for_each_value(
    value: Any, positions: list[int], target_depth: int
) -> Any:
    """Insert singleton CDA containers around source-shaped repeated values."""
    bound = set(positions)

    def align(current: Any, target_index: int) -> Any:
        if target_index >= target_depth:
            return current
        if target_index in bound:
            items = current if isinstance(current, list) else [current]
            return [align(item, target_index + 1) for item in items]
        return [align(current, target_index + 1)]

    return align(value, 0)


def align_for_each_value(
    value: Any,
    field: Mapping[str, Any],
    target: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> Any:
    """Shape a source value according to explicit ``for_each`` bindings."""
    positions = for_each_target_positions(field, target, cda, mapping)
    if positions is None or not positions:
        return value
    return _align_for_each_value(
        value, positions, len(target.get("repeat_ancestors", []))
    )


def _assign(assignments: dict[str, Any], name: str, value: Any) -> None:
    if not _present(value):
        return
    if name in assignments and assignments[name] != value:
        raise ValueError(
            f"multiple model fields assign CDA target {name!r}; "
            "configure an explicit structural rule"
        )
    assignments[name] = value


def _fallback(primary: Any, fallback: Any) -> Any:
    """Fill absent leaves without replacing values in sibling occurrences."""
    if isinstance(primary, list) or isinstance(fallback, list):
        primary_items = primary if isinstance(primary, list) else [primary]
        fallback_items = fallback if isinstance(fallback, list) else [fallback]
        count = max(len(primary_items), len(fallback_items))
        return [
            _fallback(
                primary_items[index] if index < len(primary_items) else None,
                fallback_items[index] if index < len(fallback_items) else None,
            )
            for index in range(count)
        ]
    return primary if _present(primary) else fallback


def _fan_out(
    values: list[tuple[Any, Mapping[str, Any]]], depth: int
) -> tuple[Any, dict[str, Any]]:
    """Add one branch occurrence below ``depth`` existing source repeats."""
    if depth == 0:
        active = [(value, constants) for value, constants in values if _present(value)]
        active_payload = [value for value, _ in active]
        constant_names = {
            str(name) for _, constants in active for name in constants
        }
        constants_out = {
            name: [constants.get(name) for _, constants in active]
            for name in sorted(constant_names)
        }
        return active_payload, constants_out

    count = max(
        (len(value) if isinstance(value, list) else (1 if _present(value) else 0))
        for value, _ in values
    ) if values else 0
    nested_payload: list[Any] = []
    constants_by_name: dict[str, list[Any]] = {}
    for index in range(count):
        nested: list[tuple[Any, Mapping[str, Any]]] = []
        for value, constants in values:
            if isinstance(value, list):
                child = value[index] if index < len(value) else None
            else:
                child = value if index == 0 else None
            nested.append((child, constants))
        child_payload, child_constants = _fan_out(nested, depth - 1)
        nested_payload.append(child_payload)
        for name in set(constants_by_name) | set(child_constants):
            constants_by_name.setdefault(name, []).append(child_constants.get(name))
    return nested_payload, constants_by_name


def _discriminator_identity(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        code = str(value.get("code") or "")
        system = str(value.get("codeSystem") or value.get("code_system") or "")
        if code and system:
            return ("code", code, system)
        flavor = str(value.get("nullFlavor") or value.get("null_flavor") or "")
        if flavor:
            return ("nullFlavor", flavor, str(value.get("raw") or ""))
    return ("value", repr(value))


def _present_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value] if _present(value) else []


def _merge_discriminator_occurrences(
    existing_discriminator: Any,
    existing_payload: Any,
    generated_discriminator: Any,
    generated_payload: Any,
    depth: int,
    label: str,
) -> tuple[Any, Any]:
    """Merge generated occurrences with an equal explicit discriminator.

    At ``depth`` zero, generated values contain the one occurrence level added
    by ``repeat_by_discriminator`` while an explicit discriminator may still be
    scalar.  Higher source repeat levels are traversed positionally first.
    """
    if depth > 0:
        existing_items = _present_items(existing_discriminator)
        existing_payload_items = _present_items(existing_payload)
        generated_items = _present_items(generated_discriminator)
        generated_payload_items = _present_items(generated_payload)
        count = max(len(existing_items), len(generated_items))
        discriminators: list[Any] = []
        payloads: list[Any] = []
        for index in range(count):
            payload, discriminator = _merge_discriminator_occurrences(
                existing_items[index] if index < len(existing_items) else None,
                (
                    existing_payload_items[index]
                    if index < len(existing_payload_items) else None
                ),
                generated_items[index] if index < len(generated_items) else None,
                (
                    generated_payload_items[index]
                    if index < len(generated_payload_items) else None
                ),
                depth - 1,
                f"{label}[{index}]",
            )
            payloads.append(payload)
            discriminators.append(discriminator)
        return payloads, discriminators

    explicit = _present_items(existing_discriminator)
    explicit_payload = _present_items(existing_payload)
    generated = _present_items(generated_discriminator)
    generated_values = _present_items(generated_payload)
    discriminators = list(explicit)
    payloads = [
        explicit_payload[index] if index < len(explicit_payload) else None
        for index in range(len(discriminators))
    ]
    positions = {
        _discriminator_identity(value): index
        for index, value in enumerate(discriminators)
    }
    for index, discriminator in enumerate(generated):
        if not _present(discriminator):
            continue
        payload = generated_values[index] if index < len(generated_values) else None
        identity = _discriminator_identity(discriminator)
        position = positions.get(identity)
        if position is None:
            positions[identity] = len(discriminators)
            discriminators.append(discriminator)
            payloads.append(payload)
            continue
        if (
            _present(payloads[position])
            and _present(payload)
            and payloads[position] != payload
        ):
            raise ValueError(
                f"repeat_by_discriminator rule {label!r} received conflicting "
                f"values for discriminator {identity!r}"
            )
        if _present(payload):
            payloads[position] = payload
    return payloads, discriminators


def _comparable_wording(value: Any) -> str:
    transformed = apply_transform(value, {"type": "narrative"})
    return "" if transformed is OMIT else str(transformed).strip()


def _coalesce(
    values: list[Any], policy: str, label: str,
    problems: list[str] | None = None,
) -> Any:
    if any(isinstance(value, list) for value in values if value is not None):
        count = max(len(value) if isinstance(value, list) else 1 for value in values if value is not None)
        return [
            _coalesce(
                [
                    value[index] if isinstance(value, list) and index < len(value)
                    else value if not isinstance(value, list) and index == 0
                    else None
                    for value in values
                ],
                policy,
                f"{label}[{index}]",
                problems,
            )
            for index in range(count)
        ]
    present = [value for value in values if _present(value)]
    if not present:
        return None
    if policy == "equal_or_error":
        if any(value != present[0] for value in present[1:]):
            raise ValueError(f"coalesce rule {label!r} received differing values: {present!r}")
        return present[0]
    if policy == "prefer_first":
        return present[0]
    if policy == "prefer_first_warn_if_different":
        comparable = [_comparable_wording(value) for value in present]
        if any(value != comparable[0] for value in comparable[1:]):
            if problems is not None:
                problems.append(
                    f"coalesce rule {label!r} received differing values "
                    f"{comparable!r}; used the first source"
                )
        return present[0]
    if policy == "earliest":
        return min(present)
    if policy == "latest":
        return max(present)
    raise ValueError(f"coalesce rule {label!r} has unknown policy {policy!r}")


def _concatenate(values: list[Any], separator: str) -> Any:
    if any(isinstance(value, list) for value in values if value is not None):
        count = max(
            len(value) if isinstance(value, list) else 1
            for value in values if value is not None
        )
        return [
            _concatenate([
                value[index]
                if isinstance(value, list) and index < len(value)
                else value if not isinstance(value, list) and index == 0
                else None
                for value in values
            ], separator)
            for index in range(count)
        ]
    present = [str(value) for value in values if _present(value)]
    return separator.join(present) if present else None


def _compose_coded_value(
    code: Any,
    display_name: Any,
    *,
    null_flavor: str,
) -> Any:
    """Compose a coded datatype from occurrence-aligned code and name values."""
    if isinstance(code, list) or isinstance(display_name, list):
        count = max(
            len(value) if isinstance(value, list) else 1
            for value in (code, display_name)
            if value is not None
        )
        return [
            _compose_coded_value(
                (
                    code[index]
                    if isinstance(code, list) and index < len(code)
                    else code if not isinstance(code, list) and index == 0
                    else None
                ),
                (
                    display_name[index]
                    if isinstance(display_name, list)
                    and index < len(display_name)
                    else (
                        display_name
                        if not isinstance(display_name, list) and index == 0
                        else None
                    )
                ),
                null_flavor=null_flavor,
            )
            for index in range(count)
        ]

    wording = _comparable_wording(display_name)
    if _present(code):
        if not isinstance(code, Mapping):
            raise ValueError(
                "compose_coded requires its code source transform to produce "
                "a coded object"
            )
        result = dict(code)
        if wording:
            result["displayName"] = wording
            result["raw"] = wording
        return result
    if not wording:
        return None
    return _authorize_coded_original_text({
        "nullFlavor": null_flavor,
        "raw": wording,
    })


def build_assignments(
    record: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    site: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    targets = cda.get("targets", {})
    assignments: dict[str, Any] = {}
    fallback_assignments: list[tuple[str, Any]] = []
    active_fallback_assignments: list[tuple[str, Any]] = []
    problems: list[str] = []
    structures = structure_rules(mapping)
    for path, selected in mapping.get("fields", {}).items():
        if selected is None:
            continue
        field = model.get("fields", {}).get(path, {})
        value = field_value(record, path, field)
        if not _present(value):
            continue
        for rule in mapping_rules(selected):
            # A field may have both a structure-owned narrative rule and an
            # independent conditional coded rule. Skip only the former here.
            if rule.get("structure"):
                continue
            logical_name = str(rule["target"])
            name = _physical_target_name(cda, rule)
            target = targets.get(name)
            presence = rule.get("mode") == "presence"
            valid_presence_target = bool(
                presence and target and target.get("renderable")
                and target.get("has_children") and not target.get("prohibited")
                and presence_target_complete(cda, target)
            )
            if (
                not target
                or (not target.get("writable") and not valid_presence_target)
                or target.get("prohibited")
            ):
                problems.append(
                    f"unknown, prohibited or non-renderable CDA target {name!r} "
                    f"for {path} via logical datapoint {logical_name!r}"
                )
                continue
            if len(target.get("locations", [])) != 1:
                raise ValueError(
                    f"CDA target {name!r} for {path} has {len(target.get('locations', []))} "
                    "physical locations; resolve the ambiguity before rendering"
                )
            if presence:
                if bool(value):
                    _assign(assignments, name, {"__presence__": True})
                continue
            transformed = apply_transform(value, rule.get("transform"))
            prepared = _prepare_identifier(name, target, transformed, site)
            prepared = align_for_each_value(
                prepared, field, target, cda, mapping
            )
            if rule.get("mode") == "fallback":
                fallback_assignments.append((name, prepared))
            elif rule.get("mode") == "fallback_if_active":
                active_fallback_assignments.append((name, prepared))
            else:
                _assign(assignments, name, prepared)

    for structure in structures:
        kind = str(structure.get("type") or "")
        rule_id = str(structure.get("id") or kind)
        if kind == "for_each":
            continue
        if kind in {"coalesce", "concatenate"}:
            source_specs = _structure_sources(structure)
            sources = [str(spec["source"]) for spec in source_specs]
            target_name = str(structure.get("target") or "")
            collected_values: list[Any] = []
            for spec in source_specs:
                transformed = apply_transform(
                    field_value(
                        record, str(spec["source"]),
                        model.get("fields", {}).get(str(spec["source"]), {}),
                    ),
                    spec.get("transform"),
                )
                collected_values.append(
                    None if transformed is OMIT else transformed
                )
            if kind == "coalesce":
                value = _coalesce(
                    collected_values,
                    str(structure.get("policy") or "equal_or_error"),
                    rule_id,
                    problems,
                )
            else:
                value = _concatenate(
                    collected_values, str(structure.get("separator") or "; ")
                )
            value = apply_transform(value, structure.get("transform"))
            target = targets.get(target_name, {})
            _assign(assignments, target_name, _prepare_identifier(target_name, target, value, site))
            continue
        if kind == "compose_coded":
            source_specs = _structure_sources(structure)
            by_role = {
                str(spec.get("role") or ""): spec for spec in source_specs
            }
            role_values: dict[str, Any] = {}
            for role in ("code", "display_name"):
                spec = by_role.get(role, {})
                source = str(spec.get("source") or "")
                transformed = apply_transform(
                    field_value(
                        record, source,
                        model.get("fields", {}).get(source, {}),
                    ),
                    spec.get("transform"),
                )
                role_values[role] = (
                    None if transformed is OMIT else transformed
                )
            target_name = str(structure.get("target") or "")
            target = targets.get(target_name, {})
            value = _compose_coded_value(
                role_values["code"],
                role_values["display_name"],
                null_flavor=str(structure.get("null_flavor") or "NA"),
            )
            _assign(
                assignments,
                target_name,
                _prepare_identifier(target_name, target, value, site),
            )
            continue
        if kind in {"fan_out", "repeat_by_discriminator"}:
            branches = [branch for branch in structure.get("branches", []) if isinstance(branch, Mapping)]
            if not branches:
                continue
            target_names = {_physical_target_name(cda, branch) for branch in branches}
            if len(target_names) != 1:
                raise ValueError(
                    f"repeat_by_discriminator rule {rule_id!r} must use one shared CDA target"
                )
            target_name = next(iter(target_names))
            branch_values: list[tuple[Any, Mapping[str, Any]]] = []
            depths: set[int] = set()
            for branch in branches:
                path = str(branch.get("source") or "")
                field = model.get("fields", {}).get(path, {})
                depths.add(len(field.get("repeat_chain", [])))
                value = field_value(record, path, field)
                value = apply_transform(value, branch.get("transform"))
                constants = branch.get("constants", {})
                branch_values.append((value, constants if isinstance(constants, Mapping) else {}))
            if len(depths) != 1:
                raise ValueError(
                    f"repeat_by_discriminator rule {rule_id!r} sources have different repeat depths"
                )
            payload, constants = _fan_out(branch_values, next(iter(depths)))
            if structure.get("coalesce_existing_discriminator"):
                discriminator = structure.get("discriminator", {})
                discriminator_name = str(
                    discriminator.get("target") or ""
                ) if isinstance(discriminator, Mapping) else ""
                if set(constants) != {discriminator_name}:
                    raise ValueError(
                        f"repeat_by_discriminator rule {rule_id!r} can coalesce "
                        "only its one discriminator constant"
                    )
                if _present(constants.get(discriminator_name)):
                    existing_discriminator = assignments.pop(
                        discriminator_name, None
                    )
                    existing_payload = assignments.pop(target_name, None)
                    payload, constants[discriminator_name] = (
                        _merge_discriminator_occurrences(
                            existing_discriminator,
                            existing_payload,
                            constants[discriminator_name],
                            payload,
                            next(iter(depths)),
                            rule_id,
                        )
                    )
            target = targets.get(target_name, {})
            _assign(assignments, target_name, _prepare_identifier(target_name, target, payload, site))
            for name, value in constants.items():
                constant_target = targets.get(name, {})
                _assign(assignments, name, _prepare_identifier(name, constant_target, value, site))
            continue
        problems.append(f"unknown structural binding type {kind!r} in {rule_id!r}")
    for name, value in fallback_assignments:
        assignments[name] = _fallback(assignments.get(name), value)
    for name, value in active_fallback_assignments:
        if not _present(assignments.get(name)) and _present(value):
            assignments[name] = fallback_if_active_value(value)
    _expand_quantity_range_assignments(assignments, targets, problems)
    return assignments, problems


def covered_shared_claims(mapping: Mapping[str, Any]) -> dict[str, set[str]]:
    covered: dict[str, set[str]] = {}
    for rule in structure_rules(mapping):
        kind = str(rule.get("type") or "")
        if kind in {"coalesce", "concatenate", "compose_coded"} and rule.get("target"):
            covered[str(rule["target"])] = {
                str(spec["source"]) for spec in _structure_sources(rule)
            }
        elif kind in {"fan_out", "repeat_by_discriminator"}:
            for branch in rule.get("branches", []):
                if isinstance(branch, Mapping) and branch.get("target") and branch.get("source"):
                    covered.setdefault(cda_target_name(branch), set()).add(str(branch["source"]))
    return covered


def validate_structures(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    fields = model.get("fields", {})
    targets = cda.get("targets", {})
    seen_ids: set[str] = set()
    for_each_sources: dict[str, str] = {}
    for_each_targets: dict[str, str] = {}
    for rule in structure_rules(mapping):
        rule_id = str(rule.get("id") or "")
        kind = str(rule.get("type") or "")
        prefix = f"cda-mapping: structure {rule_id or '<unnamed>'}"
        if rule_id in seen_ids:
            errors.append(f"{prefix} is duplicated")
        seen_ids.add(rule_id)
        if kind not in {
            "for_each", "fan_out", "repeat_by_discriminator", "coalesce",
            "concatenate", "compose_coded",
        }:
            errors.append(f"{prefix} has unknown type {kind!r}")
            continue
        if kind == "for_each":
            source_group = str(rule.get("source_group") or "")
            source = model.get("groups", {}).get(source_group)
            if source is None:
                errors.append(f"{prefix} references unknown source group {source_group!r}")
            elif not source.get("repeating"):
                errors.append(f"{prefix} source group {source_group!r} is not repeating")
            previous_source = for_each_sources.get(source_group)
            if previous_source is not None:
                errors.append(
                    f"{prefix} duplicates source group {source_group!r} from {previous_source!r}"
                )
            for_each_sources[source_group] = rule_id
            target_name = str(rule.get("target_repeat") or "")
            if not target_name:
                errors.append(f"{prefix} has no target_repeat")
                continue
            target = targets.get(target_name)
            if (
                not isinstance(target, Mapping)
                or not target.get("renderable")
                or not target.get("repeatable")
                or len(target.get("locations", [])) != 1
            ):
                errors.append(f"{prefix} references non-renderable target repeat {target_name!r}")
                continue
            maximum = target.get("max")
            if maximum is not None and (not isinstance(maximum, int) or maximum <= 1):
                errors.append(f"{prefix} target {target_name!r} is not repeating")
            location = str(target.get("locations", [""])[0])
            previous_target = for_each_targets.get(location)
            if previous_target is not None:
                errors.append(
                    f"{prefix} duplicates target repeat {target_name!r} from {previous_target!r}"
                )
            for_each_targets[location] = rule_id
            continue
        if kind in {"coalesce", "concatenate", "compose_coded"}:
            source_specs = _structure_sources(rule)
            sources = [str(spec["source"]) for spec in source_specs]
            target_name = str(rule.get("target") or "")
            if kind == "compose_coded" and len(sources) != 2:
                errors.append(f"{prefix} requires exactly two sources")
            elif kind != "compose_coded" and len(sources) < 2:
                errors.append(f"{prefix} requires at least two sources")
            if kind == "coalesce" and str(
                rule.get("policy") or "equal_or_error"
            ) not in {
                "equal_or_error", "prefer_first",
                "prefer_first_warn_if_different", "earliest", "latest",
            }:
                errors.append(f"{prefix} has an invalid policy")
            if kind == "concatenate" and not isinstance(
                rule.get("separator", "; "), str
            ):
                errors.append(f"{prefix} separator must be a string")
            for path in sources:
                if path not in fields:
                    errors.append(f"{prefix} references unknown source field {path!r}")
            for spec in source_specs:
                for reason in validate_transform(spec.get("transform")):
                    errors.append(
                        f"{prefix} source {spec.get('source')!r}: {reason}"
                    )
            for reason in validate_transform(rule.get("transform")):
                errors.append(f"{prefix}: {reason}")
            target = targets.get(target_name)
            if not target or not target.get("writable") or len(target.get("locations", [])) != 1:
                errors.append(f"{prefix} references non-renderable target {target_name!r}")
            elif kind == "compose_coded":
                representation = target.get("value_representation", {})
                if (
                    not isinstance(representation, Mapping)
                    or representation.get("kind")
                    != ValueRepresentationKind.CODED.value
                ):
                    errors.append(f"{prefix} target must be a coded value")
                roles = [str(spec.get("role") or "") for spec in source_specs]
                if sorted(roles) != ["code", "display_name"]:
                    errors.append(
                        f"{prefix} sources must have the distinct roles "
                        "'code' and 'display_name'"
                    )
                by_role = {
                    str(spec.get("role") or ""): spec for spec in source_specs
                }
                code_spec = by_role.get("code", {})
                code_field = fields.get(str(code_spec.get("source") or ""), {})
                compatible, reasons = transformed_compatibility(
                    code_field, target, code_spec.get("transform"),
                )
                if not compatible:
                    errors.append(
                        f"{prefix} code source is not executable: "
                        + "; ".join(reasons)
                    )
                display_spec = by_role.get("display_name", {})
                display_field = fields.get(
                    str(display_spec.get("source") or ""), {}
                )
                display_transform = display_spec.get("transform", {})
                if str(display_field.get("type") or "") not in {"text", "code"}:
                    errors.append(
                        f"{prefix} display_name source must be textual or coded"
                    )
                if (
                    not isinstance(display_transform, Mapping)
                    or display_transform.get("type") != "narrative"
                ):
                    errors.append(
                        f"{prefix} display_name source requires a narrative transform"
                    )
                null_flavor = str(rule.get("null_flavor") or "")
                if null_flavor not in NULL_FLAVORS:
                    errors.append(
                        f"{prefix} has invalid null_flavor {null_flavor!r}"
                    )
                elif not required_binding_allows_null_flavor(
                    target, null_flavor,
                ):
                    errors.append(
                        f"{prefix} null_flavor {null_flavor!r} is not admitted "
                        "by the coded target"
                    )
                review_reason = rule.get("reason")
                if (
                    not isinstance(review_reason, str)
                    or not review_reason.strip()
                ):
                    errors.append(f"{prefix} requires a non-empty review reason")
                locations = list(target.get("locations", []))
                target_path = str(target.get("path") or "")
                companions = [
                    candidate
                    for candidate in targets.values()
                    if isinstance(candidate, Mapping)
                    and candidate.get("writable")
                    and candidate.get("content_role") == "coded_original_text"
                    and len(candidate.get("locations", [])) == 1
                    and len(locations) == 1
                    and str(candidate["locations"][0]).startswith(
                        str(locations[0]) + "."
                    )
                    and str(candidate.get("path") or "").rsplit("/", 1)[0]
                    == target_path
                ]
                if len(companions) != 1:
                    errors.append(
                        f"{prefix} requires one writable coded_original_text "
                        "companion"
                    )
            if isinstance(target, Mapping) and target.get("repeat_ancestors"):
                depths = {
                    len(fields.get(path, {}).get("repeat_chain", []))
                    for path in sources
                }
                if depths != {len(target.get("repeat_ancestors", []))}:
                    errors.append(f"{prefix} source and target repeat depths differ")
            continue
        branches = [branch for branch in rule.get("branches", []) if isinstance(branch, Mapping)]
        if len(branches) < 2:
            errors.append(f"{prefix} requires at least two branches")
        logical_targets = {str(branch.get("target") or "") for branch in branches}
        if len(logical_targets) != len(branches):
            errors.append(f"{prefix} branches must have distinct logical targets")
        value_targets = {cda_target_name(branch) for branch in branches}
        if len(value_targets) != 1:
            errors.append(f"{prefix} branches must share one physical CDA target")
            continue
        target_name = next(iter(value_targets))
        target = targets.get(target_name)
        discriminator = rule.get("discriminator", {})
        discriminator_target = str(
            discriminator.get("target") or ""
        ) if isinstance(discriminator, Mapping) else ""
        allowed_members = {
            (
                str(member.get("code") or ""),
                str(member.get("codeSystem") or member.get("code_system") or ""),
            )
            for member in (
                discriminator.get("members", [])
                if isinstance(discriminator, Mapping) else []
            )
            if isinstance(member, Mapping)
        }
        if kind == "repeat_by_discriminator":
            binding = (
                discriminator.get("value_set", {})
                if isinstance(discriminator, Mapping) else {}
            )
            constant_target = targets.get(discriminator_target, {})
            target_bindings = [
                item for item in (constant_target.get("value_set_bindings") or [])
                if isinstance(item, Mapping)
            ] if isinstance(constant_target, Mapping) else []
            if not discriminator_target or not allowed_members:
                errors.append(f"{prefix} has no bound discriminator definition")
            elif isinstance(binding, Mapping) and target_bindings and not any(
                str(item.get("id") or "") == str(binding.get("id") or "")
                and (
                    not str(item.get("effective_date") or "")
                    or str(item.get("effective_date") or "")
                    == str(binding.get("effective_date") or "")
                )
                for item in target_bindings
            ):
                errors.append(
                    f"{prefix} discriminator ValueSet binding does not match the CDA target"
                )
            if rule.get("coalesce_existing_discriminator"):
                existing_sources = [
                    str(path)
                    for path in rule.get("existing_discriminator_sources", [])
                ]
                if len(existing_sources) != 1:
                    errors.append(
                        f"{prefix} must identify exactly one existing discriminator source"
                    )
                for path in existing_sources:
                    selected = {
                        cda_target_name(selected_rule)
                        for selected_rule in mapping_rules(
                            mapping.get("fields", {}).get(path)
                        )
                    }
                    if discriminator_target not in selected:
                        errors.append(
                            f"{prefix} existing source {path!r} does not map to "
                            f"discriminator {discriminator_target!r}"
                        )
        branch_depths: set[int] = set()
        for branch in branches:
            path = str(branch.get("source") or "")
            if path not in fields:
                errors.append(f"{prefix} references unknown source field {path!r}")
                continue
            branch_depths.add(len(fields[path].get("repeat_chain", [])))
            for reason in validate_transform(branch.get("transform")):
                errors.append(f"{prefix} branch {path!r}: {reason}")
            constants = branch.get("constants", {})
            if not isinstance(constants, Mapping) or not constants:
                errors.append(f"{prefix} branch {path!r} has no discriminator constants")
            elif target:
                if (
                    rule.get("coalesce_existing_discriminator")
                    and set(str(name) for name in constants)
                    != {discriminator_target}
                ):
                    errors.append(
                        f"{prefix} coalescing branches may set only the discriminator"
                    )
                for name, constant in constants.items():
                    constant_target = targets.get(str(name))
                    if not constant_target or not constant_target.get("writable"):
                        errors.append(f"{prefix} references non-renderable constant target {name!r}")
                    elif constant_target.get("repeat_ancestors") != target.get("repeat_ancestors"):
                        errors.append(f"{prefix} constant target {name!r} is in a different occurrence")
                    if kind == "repeat_by_discriminator" and str(name) == discriminator_target:
                        encoded = (
                            str(constant.get("code") or ""),
                            str(
                                constant.get("codeSystem")
                                or constant.get("code_system") or ""
                            ),
                        ) if isinstance(constant, Mapping) else ("", "")
                        if encoded not in allowed_members:
                            errors.append(
                                f"{prefix} branch {path!r} uses discriminator constant "
                                f"{encoded!r} outside the selected bound ValueSet"
                            )
        if not target or not target.get("writable") or len(target.get("locations", [])) != 1:
            errors.append(f"{prefix} references non-renderable target {target_name!r}")
        elif len(branch_depths) == 1 and len(
            target.get("repeat_ancestors", [])
        ) != next(iter(branch_depths)) + 1:
            errors.append(f"{prefix} must add exactly one target occurrence level")
        elif len(branch_depths) > 1:
            errors.append(f"{prefix} sources have different repeat depths")

    return errors
