"""Resolve model values into CDA target assignments.

Scalar transforms answer "what value?".  Structural bindings answer "which
occurrence?" or "how do several sources share a target?".  Keeping that logic
outside the XML renderer makes the mapping contract executable and reviewable.
"""
from __future__ import annotations

from typing import Any, Mapping

from .data import field_value
from .semantics import identifier_root_for_target
from .transforms import OMIT, apply_transform, mapping_rules, validate_transform


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


def _base_datatype(value: Any) -> str:
    return str(value or "").upper().split(".", 1)[0]


def _prepare_identifier(
    name: str, target: Mapping[str, Any], value: Any, site: Mapping[str, Any]
) -> Any:
    if _base_datatype(target.get("datatype")) != "II":
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
        if kind == "fan_out":
            structural_sources.update(
                str(branch.get("source")) for branch in structure.get("branches", [])
                if isinstance(branch, Mapping) and branch.get("source")
            )
        elif kind == "coalesce":
            structural_sources.update(str(path) for path in structure.get("sources", []))

    for path, selected in mapping.get("fields", {}).items():
        if selected is None or path in structural_sources:
            continue
        value = field_value(record, path, model.get("fields", {}).get(path, {}))
        if not _present(value):
            continue
        for rule in mapping_rules(selected):
            name = str(rule["target"])
            target = targets.get(name)
            if not target or not target.get("renderable") or target.get("prohibited"):
                problems.append(f"unknown, prohibited or non-renderable CDA target {name!r} for {path}")
                continue
            if len(target.get("locations", [])) != 1:
                raise ValueError(
                    f"CDA target {name!r} for {path} has {len(target.get('locations', []))} "
                    "physical locations; resolve the ambiguity before rendering"
                )
            transformed = apply_transform(value, rule.get("transform"))
            prepared = _prepare_identifier(name, target, transformed, site)
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
        if kind == "fan_out":
            branches = [branch for branch in structure.get("branches", []) if isinstance(branch, Mapping)]
            if not branches:
                continue
            target_names = {str(branch.get("target") or "") for branch in branches}
            if len(target_names) != 1:
                raise ValueError(f"fan_out rule {rule_id!r} must use one shared value target")
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
                raise ValueError(f"fan_out rule {rule_id!r} sources have different repeat depths")
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
        elif kind == "fan_out":
            for branch in rule.get("branches", []):
                if isinstance(branch, Mapping) and branch.get("target") and branch.get("source"):
                    covered.setdefault(str(branch["target"]), set()).add(str(branch["source"]))
    return covered


def validate_structures(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    fields = model.get("fields", {})
    targets = cda.get("targets", {})
    seen_ids: set[str] = set()
    for rule in structure_rules(mapping):
        rule_id = str(rule.get("id") or "")
        kind = str(rule.get("type") or "")
        prefix = f"cda-mapping: structure {rule_id or '<unnamed>'}"
        if rule_id in seen_ids:
            errors.append(f"{prefix} is duplicated")
        seen_ids.add(rule_id)
        if kind not in {"for_each", "fan_out", "coalesce"}:
            errors.append(f"{prefix} has unknown type {kind!r}")
            continue
        if kind == "for_each":
            source_group = str(rule.get("source_group") or "")
            if source_group not in model.get("groups", {}):
                errors.append(f"{prefix} references unknown source group {source_group!r}")
            if not rule.get("target_repeat"):
                errors.append(f"{prefix} has no target_repeat")
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
            if not target or not target.get("renderable") or len(target.get("locations", [])) != 1:
                errors.append(f"{prefix} references non-renderable target {target_name!r}")
            elif target.get("repeat_ancestors"):
                depths = {len(fields.get(path, {}).get("repeat_chain", [])) for path in sources}
                if depths != {len(target.get("repeat_ancestors", []))}:
                    errors.append(f"{prefix} source and target repeat depths differ")
            continue
        branches = [branch for branch in rule.get("branches", []) if isinstance(branch, Mapping)]
        if len(branches) < 2:
            errors.append(f"{prefix} requires at least two branches")
        value_targets = {str(branch.get("target") or "") for branch in branches}
        if len(value_targets) != 1:
            errors.append(f"{prefix} branches must share one value target")
            continue
        target_name = next(iter(value_targets))
        target = targets.get(target_name)
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
                for name in constants:
                    constant_target = targets.get(str(name))
                    if not constant_target or not constant_target.get("renderable"):
                        errors.append(f"{prefix} references non-renderable constant target {name!r}")
                    elif constant_target.get("repeat_ancestors") != target.get("repeat_ancestors"):
                        errors.append(f"{prefix} constant target {name!r} is in a different occurrence")
        if not target or not target.get("renderable") or len(target.get("locations", [])) != 1:
            errors.append(f"{prefix} references non-renderable target {target_name!r}")
        elif len(depths) == 1 and len(target.get("repeat_ancestors", [])) != next(iter(depths)) + 1:
            errors.append(f"{prefix} must add exactly one target occurrence level")
        elif len(depths) > 1:
            errors.append(f"{prefix} sources have different repeat depths")

    return errors
