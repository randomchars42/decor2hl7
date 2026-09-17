"""Conservative use of compiled datatype presence co-occurrence constraints."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .cda.tree import document_index, parse_location


_ASSUMED_NON_NULL = object()
_TRANSPARENT = {"include", "template", "choice", "datatype_choice"}
_STRUCTURAL_TRANSPARENT = {"include", "template", "choice"}


def _required_direct_children(node: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()

    def visit(children: Any) -> None:
        if not isinstance(children, list):
            return
        for child in children:
            if not isinstance(child, Mapping):
                continue
            if child.get("kind") in _STRUCTURAL_TRANSPARENT:
                visit(child.get("children", []))
                continue
            if child.get("kind") != "element":
                continue
            if str(child.get("conformance") or "").upper() == "NP":
                continue
            if child.get("mandatory") or int(child.get("min") or 0) >= 1:
                name = str(child.get("name") or "")
                if name:
                    result.add(name)

    visit(node.get("children", []))
    return result


def _fixed_attributes(node: Mapping[str, Any]) -> set[str]:
    conditional = {
        str(attribute.get("name") or "")
        for attribute in node.get("attributes", [])
        if isinstance(attribute, Mapping) and attribute.get("conditional_fixed")
    }
    result = {
        "@" + str(name).split(":", 1)[-1]
        for name, value in (
            node.get("fixed", {}).items()
            if isinstance(node.get("fixed"), Mapping) else ()
        )
        if value is not None and str(name) not in conditional
    }
    for attribute in node.get("attributes", []):
        if (
            not isinstance(attribute, Mapping)
            or attribute.get("value") is None
            or attribute.get("conditional_fixed")
        ):
            continue
        name = str(attribute.get("name") or "")
        if name:
            result.add("@" + name.split(":", 1)[-1])
    return result


def _representation_presence(
    target: Mapping[str, Any], value: Any,
) -> set[str]:
    if isinstance(value, Mapping) and value.get("__presence__") is True:
        return set()
    if isinstance(value, Mapping) and value.get("nullFlavor"):
        return {"@nullFlavor"}
    representation = target.get("value_representation", {})
    if not isinstance(representation, Mapping):
        return set()
    result: set[str] = set()
    xsi_type = representation.get("xsi_type")
    if xsi_type:
        result.add("@type")
    attribute = str(representation.get("attribute") or "")
    scalar = str(representation.get("scalar_attribute") or "")
    if attribute:
        result.add("@" + attribute.split(":", 1)[-1])
    if value is _ASSUMED_NON_NULL:
        if scalar:
            result.add("@" + scalar.split(":", 1)[-1])
        return result
    if isinstance(value, Mapping):
        allowed = {
            str(item) for item in representation.get("attributes", [])
        }
        for name, item in value.items():
            if item is not None and str(name) in allowed:
                result.add("@" + str(name).split(":", 1)[-1])
    elif scalar:
        result.add("@" + scalar.split(":", 1)[-1])
    return result


def _selected_presence(
    owner: tuple[int, ...], selected: tuple[int, ...],
    index: Mapping[tuple[int, ...], Mapping[str, Any]],
    target: Mapping[str, Any], value: Any,
) -> set[str]:
    if selected == owner:
        return _representation_presence(target, value)
    if selected[:len(owner)] != owner:
        return set()
    for depth in range(len(owner) + 1, len(selected) + 1):
        node = index.get(selected[:depth], {})
        if not isinstance(node, Mapping):
            continue
        if node.get("kind") in _TRANSPARENT:
            continue
        if node.get("kind") == "attribute":
            name = str(node.get("name") or "")
            return {"@" + name.split(":", 1)[-1]} if name else set()
        if node.get("kind") == "element":
            name = str(node.get("name") or "")
            return {name} if name else set()
        return set()
    return set()


def _selector_matches(selector: str, present: set[str]) -> list[str]:
    if selector == "hl7:*":
        return sorted(item for item in present if item.startswith("hl7:"))
    return [selector] if selector in present else []


def _selectors(clause: Mapping[str, Any]) -> list[str]:
    return [str(item) for item in clause.get("selectors", [])]


def datatype_cooccurrence_problems(
    cda: Mapping[str, Any], assignments: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Find violations forced by each assignment and required/fixed siblings.

    Assignments are deliberately assessed one at a time. This proves that a
    violation is unavoidable for that target without assuming optional source
    fields occur together or share a repeated CDA occurrence.
    """
    registry = cda.get("datatype_constraints", {})
    rules = registry.get("rules", {}) if isinstance(registry, Mapping) else {}
    targets = cda.get("targets", {})
    if (
        not isinstance(rules, Mapping) or not rules
        or not isinstance(targets, Mapping)
    ):
        return []
    index, _parents = document_index(cda)
    problems: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for target_name, value in assignments.items():
        target = targets.get(str(target_name), {})
        if not isinstance(target, Mapping):
            continue
        locations = list(target.get("locations", []))
        if len(locations) != 1:
            continue
        selected = parse_location(locations[0])
        if selected is None:
            continue
        for depth in range(1, len(selected) + 1):
            owner = selected[:depth]
            node = index.get(owner, {})
            clauses = rules.get(str(node.get("datatype") or ""), [])
            if (
                node.get("kind") != "element"
                or not isinstance(clauses, list)
                or not clauses
            ):
                continue
            present = _required_direct_children(node) | _fixed_attributes(node)
            present.update(_selected_presence(
                owner, selected, index, target, value,
            ))
            for clause in clauses:
                if not isinstance(clause, Mapping):
                    continue
                selectors = _selectors(clause)
                matches = [
                    _selector_matches(selector, present)
                    for selector in selectors
                ]
                if not selectors or not all(matches):
                    continue
                test = str(clause.get("test") or "")
                key = str(target_name), ".".join(map(str, owner)), test
                if key in seen:
                    continue
                seen.add(key)
                problems.append({
                    "target": str(target_name),
                    "owner_location": key[1],
                    "owner_targets": [
                        str(item) for item in node.get("targets", [])
                    ],
                    "datatype": str(node.get("datatype") or ""),
                    "selectors": selectors,
                    "present": sorted({item for group in matches for item in group}),
                    "test": test,
                    "declared_in": str(clause.get("declared_in") or ""),
                    "source": str(clause.get("source") or ""),
                })
    return problems


def unavoidable_targets_problems(
    cda: Mapping[str, Any],
    target_modes: Mapping[str, bool] | Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    """Batch the unavoidable proof while indexing the document only once."""
    modes = (
        target_modes
        if isinstance(target_modes, Mapping)
        else {name: False for name in target_modes}
    )
    assignments = {
        str(name): (
            {"__presence__": True} if presence else _ASSUMED_NON_NULL
        )
        for name, presence in modes.items()
    }
    result: dict[str, list[dict[str, Any]]] = {
        str(name): [] for name in modes
    }
    for problem in datatype_cooccurrence_problems(cda, assignments):
        result.setdefault(str(problem.get("target") or ""), []).append(problem)
    return result


def constrained_datatype_components(cda: Mapping[str, Any]) -> set[str]:
    """Find replacement parts for an unavoidably invalid parent value shape.

    This is the narrow reopening boundary for generic datatype descendants. A
    parent value representation must already conflict with required/fixed
    structure, and another clause must explicitly name a direct datatype child
    beside that same representation selector. Wildcards never turn an entire
    datatype expansion into mapping-review payload.
    """
    registry = cda.get("datatype_constraints", {})
    rules = registry.get("rules", {}) if isinstance(registry, Mapping) else {}
    targets = cda.get("targets", {})
    if (
        not isinstance(rules, Mapping) or not rules
        or not isinstance(targets, Mapping)
    ):
        return set()
    index, _parents = document_index(cda)
    alternatives: dict[tuple[int, ...], set[str]] = {}
    for owner, node in index.items():
        clauses = rules.get(str(node.get("datatype") or ""), [])
        if node.get("kind") != "element" or not isinstance(clauses, list):
            continue
        representations: set[str] = set()
        for target_name in node.get("targets", []):
            target = targets.get(str(target_name), {})
            if not isinstance(target, Mapping) or not target.get("writable"):
                continue
            target_locations = list(target.get("locations", []))
            if (
                len(target_locations) != 1
                or parse_location(target_locations[0]) != owner
            ):
                continue
            representations.update(
                _representation_presence(target, _ASSUMED_NON_NULL)
            )
        if not representations:
            continue
        base = _required_direct_children(node) | _fixed_attributes(node)
        parent_shape = base | representations
        conflict = any(
            _selectors(clause)
            and all(
                _selector_matches(selector, parent_shape)
                for selector in _selectors(clause)
            )
            for clause in clauses if isinstance(clause, Mapping)
        )
        if not conflict:
            continue
        alternatives[owner] = {
            selector
            for clause in clauses if isinstance(clause, Mapping)
            for selectors in [_selectors(clause)]
            if any(selector in representations for selector in selectors)
            for selector in selectors
            if selector.startswith("hl7:") and selector != "hl7:*"
        }

    result: set[str] = set()
    for target_name, target in targets.items():
        if (
            not isinstance(target, Mapping)
            or not target.get("datatype_derived")
            or target.get("kind") != "element"
        ):
            continue
        locations = list(target.get("locations", []))
        selected = parse_location(locations[0]) if len(locations) == 1 else None
        if selected is None:
            continue
        for depth in range(1, len(selected) + 1):
            owner = selected[:depth]
            selectors = alternatives.get(owner)
            if not selectors:
                continue
            presence = _selected_presence(
                owner, selected, index, target, _ASSUMED_NON_NULL,
            )
            element_steps = sum(
                index.get(selected[:depth], {}).get("kind") == "element"
                for depth in range(len(owner) + 1, len(selected) + 1)
            )
            if element_steps == 1 and presence & selectors:
                result.add(str(target_name))
                break
    return result


def cooccurrence_problem_message(problem: Mapping[str, Any]) -> str:
    present = ", ".join(str(item) for item in problem.get("present", []))
    return (
        f"datatype {problem.get('datatype')} assertion "
        f"{problem.get('test')!r} is unavoidably violated"
        + (f" (present: {present})" if present else "")
    )
