"""Render normalized model records using the compiled CDA target model.

Runtime addresses are generated human-readable target names. ART-DECOR element
ids are provenance only; an element does not need an id to be writable.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from ..assertions import validate_contexts
from ..bindings import (
    build_assignments,
    required_unmapped_null_flavor,
    target_default_values,
)
from .model import ValueRepresentationKind

HL7 = "urn:hl7-org:v3"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("", HL7)
ET.register_namespace("xsi", XSI)


def _qname(name: str) -> str:
    # ART-DECOR uses XPath-like predicates to distinguish sibling constraint
    # branches (for example ``hl7:id[1]`` or a coded qualifier).  The predicate
    # selects the effective constraint; it is never part of the XML QName.
    name = name.split("[", 1)[0]
    if name.startswith(("hl7:", "cda:")):
        return f"{{{HL7}}}{name.split(':', 1)[1]}"
    if name.startswith("xml:"):
        return f"{{http://www.w3.org/XML/1998/namespace}}{name.split(':', 1)[1]}"
    return name


def _cda_timestamp(value: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value.replace("-", "")
    value = value.replace("-", "").replace(":", "").replace("T", "")
    return value.replace("Z", "+0000")


def _format_site(value: Any, variables: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        try:
            return value.format(**variables)
        except (KeyError, ValueError):
            return value
    if isinstance(value, dict):
        return {key: _format_site(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_format_site(item, variables) for item in value]
    return value


def _nested_at(value: Any, occurrence: tuple[int, ...]) -> Any:
    current = value
    for depth, index in enumerate(occurrence):
        if isinstance(current, list):
            if index >= len(current):
                return None
            current = current[index]
        else:
            # A scalar inside a repeating CDA branch means one occurrence only.
            return current if all(item == 0 for item in occurrence[depth:]) else None
    return current


def _assigned_at(value: Any, occurrence: tuple[int, ...]) -> bool:
    current = _nested_at(value, occurrence)
    if isinstance(current, list):
        return any(item is not None for item in current)
    return current is not None


def _subtree_has_assignment(
    node: Mapping[str, Any], assignments: Mapping[str, Any], occurrence: tuple[int, ...]
) -> bool:
    for name in node.get("targets", []):
        if name in assignments and _assigned_at(assignments[name], occurrence):
            return True
    for attr in node.get("attributes", []):
        for name in attr.get("targets", []):
            if name in assignments and _assigned_at(assignments[name], occurrence):
                return True
    return any(
        _subtree_has_assignment(child, assignments, occurrence)
        for child in node.get("children", [])
    )


def _has_physical_value_below(
    location: tuple[int, ...],
    physical_values: Mapping[tuple[int, ...], tuple[Any, Mapping[str, Any]]],
) -> bool:
    """Return whether a compiled physical descendant has a runtime value.

    Reusable ART-DECOR includes can expose the same logical target in several
    document contexts.  Such a target is correctly non-writable, but a
    compiler-assigned system role still belongs to one concrete occurrence.
    Physical locations let that role activate only its owning branch.
    """
    return any(here[:len(location)] == location for here in physical_values)

def _set_xsi_type(element: ET.Element, representation: Mapping[str, Any]) -> None:
    xsi_type = representation.get("xsi_type")
    if xsi_type:
        element.set(f"{{{XSI}}}type", str(xsi_type))


def _write_value(
    element: ET.Element,
    value: Any,
    target: Mapping[str, Any],
    node: Mapping[str, Any],
) -> None:
    representation = target.get("value_representation")
    if not isinstance(representation, Mapping) or not representation.get("kind"):
        raise ValueError(
            f"CDA value target {target.get('path') or node.get('name')} has no compiled value representation"
        )
    if isinstance(value, Mapping) and value.get("nullFlavor"):
        element.set("nullFlavor", str(value["nullFlavor"]))
        return
    kind = ValueRepresentationKind(str(representation["kind"]))
    _set_xsi_type(element, representation)
    if kind == ValueRepresentationKind.ELEMENT_TEXT:
        element.text = str(value)
        return
    if kind in {
        ValueRepresentationKind.ATTRIBUTE,
        ValueRepresentationKind.TIMESTAMP,
        ValueRepresentationKind.BOOLEAN,
    }:
        attribute = str(representation.get("attribute") or "value")
        rendered = (
            _cda_timestamp(str(value))
            if kind == ValueRepresentationKind.TIMESTAMP else
            "true" if kind == ValueRepresentationKind.BOOLEAN and bool(value) else
            "false" if kind == ValueRepresentationKind.BOOLEAN else str(value)
        )
        element.set(attribute, rendered)
        return
    attributes = [str(item) for item in representation.get("attributes", [])]
    scalar_attribute = str(
        representation.get("scalar_attribute") or representation.get("attribute") or ""
    )
    if isinstance(value, Mapping):
        for key in attributes:
            item = value.get(key)
            if item is not None:
                element.set(key, str(item))
    elif scalar_attribute:
        element.set(scalar_attribute, str(value))
    else:
        raise ValueError(
            f"compiled representation {kind.value!r} cannot write a scalar value"
        )
    if kind == ValueRepresentationKind.QUANTITY and node.get("unit"):
        element.set("unit", str(node["unit"]))


def _generated_identifier(
    marker: Mapping[str, Any], target_name: str, occurrence: tuple[int, ...]
) -> dict[str, str]:
    identity = "|".join((
        str(marker.get("record_key") or ""),
        target_name,
        str(marker.get("document_version") or 1),
        ".".join(str(item) for item in occurrence),
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    root = str(marker.get("root") or "")
    if root:
        return {"root": root, "extension": digest}
    # UUID-derived OIDs are legal without a locally configured assigning root.
    return {"root": "2.25." + str(int(digest, 16))}


def _active_target_locations(
    cda: Mapping[str, Any], assignments: Mapping[str, Any]
) -> set[tuple[int, ...]]:
    active: set[tuple[int, ...]] = set()
    targets = cda.get("targets", {})
    for name in assignments:
        target = targets.get(name, {})
        if target.get("system_value") == "generated_identifier":
            # Completion values never activate an otherwise unused optional
            # branch; they are consumed only after an explicit descendant has
            # selected that branch.
            continue
        for raw in target.get("locations", []):
            try:
                location = tuple(int(part) for part in str(raw).split("."))
            except ValueError:
                continue
            if location and location[-1] >= 100000:
                location = location[:-1]
            for length in range(1, len(location) + 1):
                active.add(location[:length])
    return active


def _node_target_names(node: Mapping[str, Any]) -> set[str]:
    names = {str(name) for name in node.get("targets", [])}
    for attr in node.get("attributes", []):
        names.update(str(name) for name in attr.get("targets", []))
    for child in node.get("children", []):
        names.update(_node_target_names(child))
    return names


def _narrative_scalars(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for nested in value for item in _narrative_scalars(nested)]
    if isinstance(value, Mapping):
        for key in ("displayName", "display", "value", "code", "extension", "root"):
            if value.get(key) not in (None, ""):
                return [str(value[key])]
        return [item for nested in value.values() for item in _narrative_scalars(nested)]
    if value is None:
        return []
    if isinstance(value, bool):
        return ["true" if value else "false"]
    return [str(value)]


def _complete_content_roles(
    document: list[Mapping[str, Any]],
    targets: Mapping[str, Mapping[str, Any]],
    assignments: dict[str, Any],
    explicit_names: set[str],
) -> None:
    """Complete compiled section roles for explicitly active sections."""
    def assign_role(section: Mapping[str, Any], role: str, value: str) -> None:
        def walk(nodes: list[Mapping[str, Any]]) -> None:
            for node in nodes:
                if node.get("content_role") == role:
                    for raw_name in node.get("targets", []):
                        name = str(raw_name)
                        target = targets.get(name, {})
                        if target.get("writable") and len(target.get("locations", [])) == 1:
                            assignments.setdefault(name, value)
                            return
                walk(list(node.get("children", [])))
        walk(list(section.get("children", [])))

    def visit(nodes: list[Mapping[str, Any]]) -> None:
        for node in nodes:
            local_name = str(node.get("name") or "").split(":", 1)[-1].split("[", 1)[0]
            if node.get("kind") == "element" and local_name == "section":
                names = _node_target_names(node)
                assigned_names = sorted(names & explicit_names)
                if assigned_names:
                    label = next(
                        (
                            str(targets[name].get("template_display_name")
                                or targets[name].get("template_name") or "Section")
                            for name in node.get("targets", [])
                            if name in targets
                        ),
                        "Section",
                    )
                    values: list[str] = []
                    for name in assigned_names:
                        values.extend(_narrative_scalars(assignments.get(name)))
                    narrative = "; ".join(dict.fromkeys(item for item in values if item))
                    assign_role(node, "section_title", label)
                    assign_role(node, "section_narrative", narrative or label)
            visit(list(node.get("children", [])))
    visit(document)


def _coded_original_text(value: Any) -> Any:
    """Preserve occurrence shape while extracting a coded value's wording."""
    if isinstance(value, list):
        return [_coded_original_text(item) for item in value]
    if not isinstance(value, Mapping):
        return None
    for key in ("raw", "canonical", "displayName", "display"):
        if value.get(key) not in (None, ""):
            return value[key]
    return None


def _complete_value_companions(
    document: list[Mapping[str, Any]],
    targets: Mapping[str, Mapping[str, Any]],
    assignments: dict[str, Any],
) -> None:
    """Complete datatype-defined companion values from mapped parent values.

    The compiler records the relationship as a content role.  Runtime code
    therefore remains independent of CD/CE child names and template identity.
    """
    def visit(nodes: list[Mapping[str, Any]]) -> None:
        for node in nodes:
            parent_value = next(
                (
                    assignments[str(name)]
                    for name in node.get("targets", [])
                    if str(name) in assignments
                ),
                None,
            )
            if parent_value is not None:
                for child in node.get("children", []):
                    if child.get("content_role") != "coded_original_text":
                        continue
                    value = _coded_original_text(parent_value)
                    if value is None:
                        continue
                    for raw_name in child.get("targets", []):
                        name = str(raw_name)
                        target = targets.get(name, {})
                        if (
                            target.get("writable")
                            and len(target.get("locations", [])) == 1
                        ):
                            assignments.setdefault(name, value)
                            break
            visit(list(node.get("children", [])))
    visit(document)


def _nested_count(value: Any, occurrence: tuple[int, ...]) -> int:
    current = _nested_at(value, occurrence)
    if isinstance(current, list):
        return len(current)
    return 1 if current is not None else 0


def _repeat_count(
    node: Mapping[str, Any], location: tuple[int, ...], occurrence: tuple[int, ...],
    assignments: Mapping[str, Any], cda: Mapping[str, Any],
) -> int:
    maximum = node.get("max")
    repeats_here = maximum is None or (isinstance(maximum, int) and maximum > 1)
    if not repeats_here:
        return 1
    count = int(node.get("min") or 0)
    for name, value in assignments.items():
        target = cda.get("targets", {}).get(name, {})
        # If the assignment addresses this repeated element itself, its own
        # max cardinality does not imply another dataset occurrence level. At
        # an already-selected parent occurrence a scalar means one element; a
        # list means that many values of the repeated leaf.
        for raw_location in target.get("locations", []):
            try:
                target_location = tuple(int(part) for part in str(raw_location).split("."))
            except ValueError:
                continue
            if target_location and target_location[-1] >= 100000:
                target_location = target_location[:-1]
            if target_location == location:
                current = _nested_at(value, occurrence)
                count = max(count, len(current) if isinstance(current, list) else (1 if current is not None else 0))
                break
        ancestors = [
            tuple(int(part) for part in str(raw).split("."))
            for raw in target.get("repeat_ancestors", []) if raw
        ]
        if location in ancestors:
            depth = ancestors.index(location)
            # ``occurrence`` contains one index for each already-entered repeating
            # ancestor, therefore its length should equal this repeat depth.
            prefix = occurrence[:depth]
            count = max(count, _nested_count(value, prefix))
            continue
    if isinstance(maximum, int):
        count = min(count, maximum)
    return count

def _value_for_node(node: Mapping[str, Any], assignments: Mapping[str, Any]) -> tuple[Any, str | None]:
    for name in node.get("targets", []):
        if name in assignments:
            return assignments[name], str(name)
    return None, None


def _value_for_attribute(attr: Mapping[str, Any], assignments: Mapping[str, Any]) -> tuple[Any, str | None]:
    for name in attr.get("targets", []):
        if name in assignments:
            return assignments[name], str(name)
    return None, None


def _at(value: Any, occurrence: tuple[int, ...]) -> Any:
    return _nested_at(value, occurrence)

def _has_required_content(node: Mapping[str, Any]) -> bool:
    if str(node.get("conformance") or "").upper() == "NP":
        return False
    if bool(node.get("mandatory")) or int(node.get("min") or 0) >= 1:
        return True
    return False


def _permits_null_flavor(node: Mapping[str, Any]) -> bool:
    """Return whether the compiled representation exposes legal nullFlavor."""
    if node.get("mandatory") or str(node.get("conformance") or "").upper() == "M":
        return False
    return any(
        str(attr.get("name") or "").split(":", 1)[-1] == "nullFlavor"
        and attr.get("optional") is not False
        for attr in node.get("attributes", [])
    )


def _render_transparent(
    node: Mapping[str, Any],
    parent: ET.Element | None,
    assignments: Mapping[str, Any],
    target_defaults: Mapping[str, Mapping[str, str]],
    active_locations: set[tuple[int, ...]],
    cda: Mapping[str, Any],
    location: tuple[int, ...],
    null_flavor: str,
    problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...],
    physical_values: Mapping[tuple[int, ...], tuple[Any, Mapping[str, Any]]],
) -> list[ET.Element]:
    if str(node.get("conformance") or "").upper() == "NP":
        return []
    required = _has_required_content(node)
    active = location in active_locations and (
        _subtree_has_assignment(node, assignments, occurrence)
        or _has_physical_value_below(location, physical_values)
    )
    if not required and not active:
        return []
    maximum = node.get("max")
    repeats_here = maximum is None or (isinstance(maximum, int) and maximum > 1)
    occurrences = [occurrence]
    if repeats_here:
        count = _repeat_count(node, location, occurrence, assignments, cda)
        occurrences = [occurrence + (index,) for index in range(count)]
    result: list[ET.Element] = []
    for current_occurrence in occurrences:
        for index, child in enumerate(node.get("children", [])):
            result.extend(
                _render_node(
                    child, parent, assignments, target_defaults, active_locations, cda,
                    location + (index,), null_flavor, problems, assertion_contexts,
                    current_occurrence, physical_values,
                )
            )
    return result


def _render_node(
    node: Mapping[str, Any],
    parent: ET.Element | None,
    assignments: Mapping[str, Any],
    target_defaults: Mapping[str, Mapping[str, str]],
    active_locations: set[tuple[int, ...]],
    cda: Mapping[str, Any],
    location: tuple[int, ...],
    null_flavor: str,
    problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...] = (),
    physical_values: Mapping[
        tuple[int, ...], tuple[Any, Mapping[str, Any]]
    ] | None = None,
) -> list[ET.Element]:
    physical_values = physical_values or {}
    if node.get("kind") in {"include", "template"}:
        return _render_transparent(
            node, parent, assignments, target_defaults, active_locations, cda, location,
            null_flavor, problems, assertion_contexts, occurrence,
            physical_values,
        )

    if str(node.get("conformance") or "").upper() == "NP":
        return []
    required = _has_required_content(node)
    active = location in active_locations and (
        _subtree_has_assignment(node, assignments, occurrence)
        or _has_physical_value_below(location, physical_values)
    )
    if not required and not active:
        return []

    maximum = node.get("max")
    repeats_here = maximum is None or (isinstance(maximum, int) and maximum > 1)
    if repeats_here:
        count = _repeat_count(node, location, occurrence, assignments, cda)
        result: list[ET.Element] = []
        for index in range(count):
            result.extend(
                _render_node_once(
                    node, parent, assignments, target_defaults, active_locations, cda, location,
                    null_flavor, problems, assertion_contexts, occurrence + (index,),
                    physical_values,
                )
            )
        return result
    return _render_node_once(
        node, parent, assignments, target_defaults, active_locations, cda, location,
        null_flavor, problems, assertion_contexts, occurrence,
        physical_values,
    )


def _render_node_once(
    node: Mapping[str, Any], parent: ET.Element | None, assignments: Mapping[str, Any],
    target_defaults: Mapping[str, Mapping[str, str]],
    active_locations: set[tuple[int, ...]], cda: Mapping[str, Any],
    location: tuple[int, ...], null_flavor: str, problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...],
    physical_values: Mapping[tuple[int, ...], tuple[Any, Mapping[str, Any]]],
) -> list[ET.Element]:
    required = _has_required_content(node)
    source = node.get("origin", {})
    node_identity = str(
        source.get("path") or node.get("name") or "CDA element"
    )
    if source.get("template_id"):
        node_identity += f" [{source.get('template_id')}@{source.get('template_effective_date') or 'dynamic'}]"

    element = (
        ET.Element(_qname(str(node.get("name") or "element")))
        if parent is None
        else ET.SubElement(parent, _qname(str(node.get("name") or "element")))
    )

    if node.get("asserts"):
        assertion_contexts.append((element, list(node.get("asserts", [])), dict(node.get("lets", {}))))

    conditional_fixed_attributes = {
        str(attr.get("name") or "")
        for attr in node.get("attributes", [])
        if attr.get("conditional_fixed")
    }
    for key, value in node.get("fixed", {}).items():
        if str(key) in conditional_fixed_attributes:
            continue
        if value is not None:
            element.set(_qname(str(key)), str(value))
    if node.get("fixed_text") is not None:
        element.text = str(node.get("fixed_text"))

    node_representation = next(
        (
            cda.get("targets", {}).get(str(name), {}).get("value_representation")
            for name in node.get("targets", [])
            if cda.get("targets", {}).get(str(name), {}).get(
                "value_representation"
            )
        ),
        {},
    )
    represented_attributes = {
        str(name)
        for name in (
            list(node_representation.get("attributes", []))
            + [node_representation.get("attribute")]
            + [node_representation.get("scalar_attribute")]
        )
        if name
    }
    for attr in node.get("attributes", []):
        name = str(attr.get("name") or "")
        if not name:
            continue
        fixed_value = attr.get("value")
        value = None if attr.get("conditional_fixed") else fixed_value
        assigned, target_name = _value_for_attribute(attr, assignments)
        if target_name is not None:
            value = _at(assigned, occurrence)
        if isinstance(value, Mapping) and value.get("nullFlavor"):
            value = None
        if (
            value is not None
            and attr.get("conditional_fixed")
            and str(value) != str(fixed_value)
        ):
            raise ValueError(
                f"CDA attribute @{name} on {node.get('name')} is fixed to "
                f"{fixed_value!r}, not {value!r}"
            )
        if value is None and attr.get("optional") is False:
            # Composite representations write their own scalar/metadata
            # attributes after this loop.  Defer those checks until the
            # representation, fixed code, or compiled fallback has executed.
            if name not in represented_attributes:
                raise ValueError(
                    f"required CDA attribute @{name} on {node_identity} has no "
                    "fixed or assigned value"
                )
        if value is not None:
            representation = None
            if target_name is not None:
                representation = cda.get("targets", {}).get(target_name, {}).get(
                    "value_representation"
                )
            if (
                isinstance(representation, Mapping)
                and representation.get("kind") == ValueRepresentationKind.XML_ATTRIBUTE.value
                and "boolean" in representation.get("logical_types", [])
            ):
                value = "true" if bool(value) else "false"
            element.set(_qname(name), str(value))

    assigned, target_name = _value_for_node(node, assignments)
    physical_target: Mapping[str, Any] | None = None
    if target_name is None and location in physical_values:
        assigned, physical_target = physical_values[location]
    if target_name is not None:
        target = cda.get("targets", {}).get(str(target_name), {})
        if (
            target.get("system_value") == "generated_identifier"
            and isinstance(assigned, Mapping)
            and assigned.get("__generated_identifier__")
        ):
            assigned = _generated_identifier(assigned, str(target_name), occurrence)
        else:
            assigned = _at(assigned, occurrence)
    if isinstance(assigned, Mapping) and assigned.get("__presence__") is True:
        # Presence-mode assignments activate an optional, fully constrained
        # structural statement.  Its fixed descendants carry the CDA payload;
        # the container itself is intentionally not a scalar writable target.
        assigned = None
        target_name = None
    default = next(
        (
            target_defaults[str(name)]
            for name in node.get("targets", [])
            if str(name) in target_defaults
        ),
        None,
    )
    if assigned is not None:
        target = physical_target or cda.get("targets", {}).get(str(target_name), {})
        _write_value(element, assigned, target, node)
    elif len(node.get("codes") or []) == 1:
        codes = node.get("codes") or []
        target = next(
            (
                cda.get("targets", {}).get(str(name), {})
                for name in node.get("targets", [])
                if cda.get("targets", {}).get(str(name), {}).get("value_representation")
            ),
            {},
        )
        _write_value(
            element,
            {
                "code": codes[0].get("code"),
                **(
                    {"codeSystem": codes[0].get("code_system")}
                    if codes[0].get("code_system") else {}
                ),
            },
            target,
            node,
        )
    elif default is not None:
        default_name = next(
            (str(name) for name in node.get("targets", []) if str(name) in target_defaults),
            "",
        )
        _write_value(
            element, default, cda.get("targets", {}).get(default_name, {}), node
        )
    elif isinstance(node.get("compiled_default"), Mapping):
        compiled_default = node.get("compiled_default", {})
        target = next(
            (
                cda.get("targets", {}).get(str(name), {})
                for name in node.get("targets", [])
                if cda.get("targets", {}).get(str(name), {}).get(
                    "value_representation"
                )
            ),
            {},
        )
        _write_value(element, compiled_default.get("value"), target, node)

    for attr in node.get("attributes", []):
        name = str(attr.get("name") or "")
        if (
            name and attr.get("optional") is False
            and _qname(name) not in element.attrib
        ):
            raise ValueError(
                f"required CDA attribute @{name} on {node_identity} has no "
                "fixed or assigned value"
            )

    child_count = 0
    for index, child in enumerate(node.get("children", [])):
        child_count += len(
            _render_node(
                child, element, assignments, target_defaults, active_locations, cda,
                location + (index,), null_flavor, problems, assertion_contexts,
                occurrence, physical_values,
            )
        )

    if (
        required and assigned is None and default is None
        and not child_count and not element.attrib and not element.text
    ):
        if node.get("mandatory") or str(node.get("conformance") or "").upper() == "M":
            raise ValueError(
                f"mandatory CDA element {node_identity} has no fixed, mapped, "
                "or default value and cannot use nullFlavor"
            )
        if node.get("children") and not _permits_null_flavor(node):
            raise ValueError(
                f"required complex CDA element {node_identity} has no fixed, "
                "mapped, or child value; configure a required leaf instead"
            )
        # Scalar CDA values have always used the configured required-value
        # nullFlavor fallback.  A complex structural value is stricter: its
        # compiled datatype/model expansion must expose @nullFlavor before the
        # renderer may use it in place of required child content.
        element.set("nullFlavor", null_flavor)
    return [element]


def emit(
    record: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    site: Mapping[str, Any],
    *,
    document_version: int = 1,
) -> tuple[bytes, list[str]]:
    targets = cda.get("targets", {})
    assignments, problems = build_assignments(record, model, cda, mapping, site)
    target_defaults = target_default_values(cda, mapping)
    explicit_assignment_names = set(assignments)

    generation_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    organization = site.get("organization", {})
    system_values = {
        "document_generation_time": generation_time,
        "custodian_organization_identifier": (
            {"root": organization.get("oid")}
            if isinstance(organization, Mapping) and organization.get("oid") else None
        ),
        "custodian_organization_name": (
            organization.get("name") if isinstance(organization, Mapping) else None
        ),
    }
    for name, target in targets.items():
        role = str(target.get("system_value") or "")
        value = system_values.get(role)
        if (
            value is not None
            and target.get("writable")
            and len(target.get("locations", [])) == 1
        ):
            assignments.setdefault(str(name), value)

    variables = {"key": record.get("key"), "document_version": document_version}
    document_root = site.get("identifiers", {}).get("document_root")
    if document_root:
        standard_values = {
            "CDAid.id": {"root": document_root, "extension": f"{record.get('key')}-{document_version}"},
            "CDAsetIdversionNumber.setId": {"root": document_root, "extension": str(record.get("key"))},
            "CDAsetIdversionNumber.versionNumber": document_version,
        }
        for name, value in standard_values.items():
            if name in targets and targets[name].get("renderable") and len(targets[name].get("locations", [])) == 1:
                assignments.setdefault(name, value)

    for name, value in site.get("cda", {}).get("values", {}).items():
        if name in targets and targets[name].get("renderable") and len(targets[name].get("locations", [])) == 1:
            assignments.setdefault(name, _format_site(value, variables))
        else:
            problems.append(f"site configuration references unknown, prohibited or ambiguous CDA target {name!r}")

    identifier_root = str(
        site.get("identifiers", {}).get("document_root") or ""
    )
    for name, target in targets.items():
        if (
            target.get("system_value") == "generated_identifier"
            and target.get("writable")
            and len(target.get("locations", [])) == 1
        ):
            assignments.setdefault(str(name), {
                "__generated_identifier__": True,
                "root": identifier_root,
                "record_key": record.get("key"),
                "document_version": document_version,
            })

    document = cda.get("document", [])
    if not document:
        raise ValueError("compiled CDA model contains no document element")

    physical_values: dict[
        tuple[int, ...], tuple[Any, Mapping[str, Any]]
    ] = {}

    def collect_physical_values(
        nodes: list[Mapping[str, Any]], location: tuple[int, ...] = (),
    ) -> None:
        for index, node in enumerate(nodes):
            here = location + (index,)
            role = str(node.get("system_value") or "")
            value = system_values.get(role)
            if node.get("kind") == "element" and role and value is not None:
                representation_target = next(
                    (
                        targets.get(str(name), {})
                        for name in node.get("targets", [])
                        if targets.get(str(name), {}).get("value_representation")
                    ),
                    {},
                )
                physical_values[here] = (value, representation_target)
            collect_physical_values(list(node.get("children", [])), here)

    collect_physical_values(list(document))
    _complete_value_companions(list(document), targets, assignments)
    _complete_content_roles(
        list(document), targets, assignments, explicit_assignment_names
    )
    active_locations = _active_target_locations(cda, assignments)
    for location in physical_values:
        active_locations.update(
            location[:depth] for depth in range(1, len(location) + 1)
        )
    null_flavor = required_unmapped_null_flavor(mapping)
    roots: list[ET.Element] = []
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]] = []
    for index, node in enumerate(document):
        roots.extend(
            _render_node(
                node, None, assignments, target_defaults, active_locations, cda, (index,),
                null_flavor, problems, assertion_contexts, (), physical_values,
            )
        )
    if len(roots) != 1:
        raise ValueError(f"compiled CDA model rendered {len(roots)} root elements, expected one")
    assertion_errors, assertion_warnings = validate_contexts(roots[0], assertion_contexts)
    problems.extend(assertion_warnings)
    if assertion_errors:
        raise ValueError("generated CDA violates ART-DECOR assertions:\n" + "\n".join(assertion_errors))
    ET.indent(roots[0], space="  ")
    return ET.tostring(roots[0], encoding="utf-8", xml_declaration=True), problems
