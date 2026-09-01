"""Resolve model values into CDA target assignments.

Scalar transforms answer "what value?".  Structural bindings answer "which
occurrence?" or "how do several sources share a target?".  Keeping that logic
outside the XML renderer makes the mapping contract executable and reviewable.
"""
from __future__ import annotations

from typing import Any, Mapping

from .data import field_value
from .semantics import identifier_root_for_target
from .cda.model import ValueRepresentationKind
from .transforms import (
    OMIT,
    apply_transform,
    cda_target_name,
    mapping_rules,
    validate_transform,
)

NULL_FLAVORS = frozenset({
    "NI", "INV", "DER", "OTH", "NINF", "PINF", "UNC", "MSK", "NA",
    "UNK", "ASKU", "NAV", "NASK", "TRC",
})


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


def target_default_values(
    cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    """Resolve reviewed per-target null-flavor defaults to physical targets."""
    errors = validate_target_defaults(cda, mapping)
    if errors:
        raise ValueError("invalid CDA target defaults:\n" + "\n".join(errors))
    raw = mapping.get("target_defaults", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("cda-mapping: target_defaults must be an object")
    result: dict[str, dict[str, str]] = {}
    owners: dict[str, str] = {}
    for configured, rule in raw.items():
        name = str(configured)
        if not isinstance(rule, Mapping):
            raise ValueError(
                f"cda-mapping: target_defaults[{name!r}] must be an object"
            )
        flavor = str(rule.get("nullFlavor") or "")
        if flavor not in NULL_FLAVORS:
            raise ValueError(
                f"cda-mapping: target_defaults[{name!r}] has invalid "
                f"nullFlavor {flavor!r}"
            )
        physical = _physical_default_target(cda, name)
        value = {"nullFlavor": flavor}
        if physical in result and result[physical] != value:
            raise ValueError(
                f"cda-mapping: target defaults {owners[physical]!r} and {name!r} "
                f"resolve to {physical!r} with different values"
            )
        result[physical] = value
        owners[physical] = name
    return result


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
    resolved: dict[str, tuple[str, str]] = {}
    for configured, rule in raw.items():
        name = str(configured)
        prefix = f"cda-mapping: target_defaults[{name!r}]"
        if not isinstance(rule, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        flavor = str(rule.get("nullFlavor") or "")
        if flavor not in NULL_FLAVORS:
            errors.append(f"{prefix} has invalid nullFlavor {flavor!r}")
        reason = rule.get("reason")
        if reason is not None and not isinstance(reason, str):
            errors.append(f"{prefix}.reason must be text")

        physical = _physical_default_target(cda, name)
        target = targets.get(physical)
        if not isinstance(target, Mapping):
            errors.append(f"{prefix} references unknown CDA target {physical!r}")
            continue
        previous = resolved.get(physical)
        if previous and previous[1] != flavor:
            errors.append(
                f"{prefix} conflicts with target_defaults[{previous[0]!r}]; both "
                f"resolve to {physical!r}"
            )
        resolved[physical] = (name, flavor)
        if target.get("kind") != "element":
            errors.append(f"{prefix} cannot apply nullFlavor to an attribute")
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
        if target.get("mandatory") or str(target.get("conformance") or "").upper() == "M":
            errors.append(f"{prefix} target does not permit a nullFlavor default")
        if target.get("has_children"):
            errors.append(
                f"{prefix} targets a complex element; default its required leaf instead"
            )
    return errors


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
        payload = [value for value, _ in active]
        constant_names = {
            str(name) for _, constants in active for name in constants
        }
        constants_out = {
            name: [constants.get(name) for _, constants in active]
            for name in sorted(constant_names)
        }
        return payload, constants_out

    count = max(
        (len(value) if isinstance(value, list) else (1 if _present(value) else 0))
        for value, _ in values
    ) if values else 0
    payload: list[Any] = []
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
        payload.append(child_payload)
        for name in set(constants_by_name) | set(child_constants):
            constants_by_name.setdefault(name, []).append(child_constants.get(name))
    return payload, constants_by_name


def _coalesce(values: list[Any], policy: str, label: str) -> Any:
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
    if policy == "earliest":
        return min(present)
    if policy == "latest":
        return max(present)
    raise ValueError(f"coalesce rule {label!r} has unknown policy {policy!r}")


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
    problems: list[str] = []
    structures = structure_rules(mapping)
    structural_sources: set[str] = set()
    for structure in structures:
        kind = str(structure.get("type") or "")
        if kind in {"fan_out", "repeat_by_discriminator"}:
            structural_sources.update(
                str(branch.get("source")) for branch in structure.get("branches", [])
                if isinstance(branch, Mapping) and branch.get("source")
            )
        elif kind == "coalesce":
            structural_sources.update(str(path) for path in structure.get("sources", []))

    for path, selected in mapping.get("fields", {}).items():
        if selected is None or path in structural_sources:
            continue
        field = model.get("fields", {}).get(path, {})
        value = field_value(record, path, field)
        if not _present(value):
            continue
        for rule in mapping_rules(selected):
            logical_name = str(rule["target"])
            name = _physical_target_name(cda, rule)
            target = targets.get(name)
            if not target or not target.get("writable") or target.get("prohibited"):
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
            transformed = apply_transform(value, rule.get("transform"))
            prepared = _prepare_identifier(name, target, transformed, site)
            prepared = align_for_each_value(
                prepared, field, target, cda, mapping
            )
            if rule.get("mode") == "fallback":
                fallback_assignments.append((name, prepared))
            else:
                _assign(assignments, name, prepared)

    for structure in structures:
        kind = str(structure.get("type") or "")
        rule_id = str(structure.get("id") or kind)
        if kind == "for_each":
            continue
        if kind == "coalesce":
            sources = [str(path) for path in structure.get("sources", [])]
            target_name = str(structure.get("target") or "")
            values = [
                field_value(record, path, model.get("fields", {}).get(path, {}))
                for path in sources
            ]
            value = _coalesce(values, str(structure.get("policy") or "equal_or_error"), rule_id)
            target = targets.get(target_name, {})
            _assign(assignments, target_name, _prepare_identifier(target_name, target, value, site))
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
            target = targets.get(target_name, {})
            _assign(assignments, target_name, _prepare_identifier(target_name, target, payload, site))
            for name, value in constants.items():
                constant_target = targets.get(name, {})
                _assign(assignments, name, _prepare_identifier(name, constant_target, value, site))
            continue
        problems.append(f"unknown structural binding type {kind!r} in {rule_id!r}")
    for name, value in fallback_assignments:
        assignments[name] = _fallback(assignments.get(name), value)
    return assignments, problems


def covered_shared_claims(mapping: Mapping[str, Any]) -> dict[str, set[str]]:
    covered: dict[str, set[str]] = {}
    for rule in structure_rules(mapping):
        kind = str(rule.get("type") or "")
        if kind == "coalesce" and rule.get("target"):
            covered[str(rule["target"])] = {str(path) for path in rule.get("sources", [])}
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
        if kind not in {"for_each", "fan_out", "repeat_by_discriminator", "coalesce"}:
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
        if kind == "coalesce":
            sources = [str(path) for path in rule.get("sources", [])]
            target_name = str(rule.get("target") or "")
            if len(sources) < 2:
                errors.append(f"{prefix} requires at least two sources")
            if str(rule.get("policy") or "equal_or_error") not in {
                "equal_or_error", "prefer_first", "earliest", "latest",
            }:
                errors.append(f"{prefix} has an invalid policy")
            for path in sources:
                if path not in fields:
                    errors.append(f"{prefix} references unknown source field {path!r}")
            target = targets.get(target_name)
            if not target or not target.get("writable") or len(target.get("locations", [])) != 1:
                errors.append(f"{prefix} references non-renderable target {target_name!r}")
            elif target.get("repeat_ancestors"):
                depths = {len(fields.get(path, {}).get("repeat_chain", [])) for path in sources}
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
        depths: set[int] = set()
        for branch in branches:
            path = str(branch.get("source") or "")
            if path not in fields:
                errors.append(f"{prefix} references unknown source field {path!r}")
                continue
            depths.add(len(fields[path].get("repeat_chain", [])))
            for reason in validate_transform(branch.get("transform")):
                errors.append(f"{prefix} branch {path!r}: {reason}")
            constants = branch.get("constants", {})
            if not isinstance(constants, Mapping) or not constants:
                errors.append(f"{prefix} branch {path!r} has no discriminator constants")
            elif target:
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
        elif len(depths) == 1 and len(target.get("repeat_ancestors", [])) != next(iter(depths)) + 1:
            errors.append(f"{prefix} must add exactly one target occurrence level")
        elif len(depths) > 1:
            errors.append(f"{prefix} sources have different repeat depths")

    return errors
