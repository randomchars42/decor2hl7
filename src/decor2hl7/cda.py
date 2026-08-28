"""Render normalized model records using the compiled CDA target model.

Runtime addresses are generated human-readable target names. ART-DECOR element
ids are provenance only; an element does not need an id to be writable.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from .assertions import validate_contexts
from .bindings import build_assignments
from .semantics import base_datatype

HL7 = "urn:hl7-org:v3"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("", HL7)
ET.register_namespace("xsi", XSI)


def _qname(name: str) -> str:
    if name.startswith(("hl7:", "cda:")):
        return f"{{{HL7}}}{name.split(':', 1)[1]}"
    if name.startswith("xml:"):
        return f"{{http://www.w3.org/XML/1998/namespace}}{name.split(':', 1)[1]}"
    return name


def _leaf(name: str) -> str:
    return name.split(":", 1)[-1].split("[", 1)[0]


def _base_datatype(value: Any) -> str:
    return base_datatype(value)


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

def _set_xsi_type(element: ET.Element, node: Mapping[str, Any]) -> None:
    if _leaf(str(node.get("name") or "")) != "value":
        return
    datatype = _base_datatype(node.get("datatype"))
    if datatype and datatype not in {"ANY"}:
        element.set(f"{{{XSI}}}type", datatype)


def _write_value(element: ET.Element, value: Any, node: Mapping[str, Any]) -> None:
    if isinstance(value, Mapping) and value.get("nullFlavor"):
        element.set("nullFlavor", str(value["nullFlavor"]))
        return
    if isinstance(value, Mapping):
        if value.get("code") is not None:
            _set_xsi_type(element, node)
            element.set("code", str(value["code"]))
            if value.get("codeSystem"):
                element.set("codeSystem", str(value["codeSystem"]))
            if value.get("displayName"):
                element.set("displayName", str(value["displayName"]))
            return
        for key, item in value.items():
            if item is not None and key not in {"canonical", "raw"}:
                element.set(str(key), str(item))
        return

    datatype = _base_datatype(node.get("datatype"))
    _set_xsi_type(element, node)
    if datatype == "II":
        element.set("extension", str(value))
    elif datatype in {"TS", "IVL_TS"}:
        element.set("value", _cda_timestamp(str(value)))
    elif datatype in {"PQ", "REAL", "INT"}:
        element.set("value", str(value))
        if node.get("unit"):
            element.set("unit", str(node["unit"]))
    elif datatype in {"CD", "CE", "CV", "CS", "CO", "SC"}:
        element.set("code", str(value))
    elif datatype == "BL":
        element.set("value", "true" if bool(value) else "false")
    else:
        element.text = str(value)


def _active_target_locations(
    cda: Mapping[str, Any], assignments: Mapping[str, Any]
) -> set[tuple[int, ...]]:
    active: set[tuple[int, ...]] = set()
    targets = cda.get("targets", {})
    for name in assignments:
        target = targets.get(name, {})
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
        # Compatibility for hand-compiled/older cda.json fixtures that predate
        # repeat_ancestors: a list-valued assignment below this repeating node
        # determines its occurrence count.
        if not ancestors:
            raw_locations = list(target.get("locations", []))
            for raw in raw_locations:
                try:
                    target_location = tuple(int(part) for part in str(raw).split("."))
                except ValueError:
                    continue
                if target_location and target_location[-1] >= 100000:
                    target_location = target_location[:-1]
                if target_location[:len(location)] == location:
                    count = max(count, _nested_count(value, occurrence))
                    break
    if isinstance(maximum, int):
        count = min(count, maximum)
    return count

def _values_at_node(node: Mapping[str, Any], assignments: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for name in node.get("targets", []):
        if name in assignments:
            values.append(assignments[name])
    return values


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


def _render_transparent(
    node: Mapping[str, Any],
    parent: ET.Element | None,
    assignments: Mapping[str, Any],
    active_locations: set[tuple[int, ...]],
    cda: Mapping[str, Any],
    location: tuple[int, ...],
    null_flavor: str,
    problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...],
) -> list[ET.Element]:
    if str(node.get("conformance") or "").upper() == "NP":
        return []
    required = _has_required_content(node)
    active = location in active_locations and _subtree_has_assignment(node, assignments, occurrence)
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
                    child, parent, assignments, active_locations, cda, location + (index,),
                    null_flavor, problems, assertion_contexts, current_occurrence,
                )
            )
    return result


def _render_node(
    node: Mapping[str, Any],
    parent: ET.Element | None,
    assignments: Mapping[str, Any],
    active_locations: set[tuple[int, ...]],
    cda: Mapping[str, Any],
    location: tuple[int, ...],
    null_flavor: str,
    problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...] = (),
) -> list[ET.Element]:
    if node.get("kind") in {"include", "template"}:
        return _render_transparent(
            node, parent, assignments, active_locations, cda, location,
            null_flavor, problems, assertion_contexts, occurrence,
        )

    if str(node.get("conformance") or "").upper() == "NP":
        return []
    required = _has_required_content(node)
    active = location in active_locations and _subtree_has_assignment(node, assignments, occurrence)
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
                    node, parent, assignments, active_locations, cda, location,
                    null_flavor, problems, assertion_contexts, occurrence + (index,),
                )
            )
        return result
    return _render_node_once(
        node, parent, assignments, active_locations, cda, location,
        null_flavor, problems, assertion_contexts, occurrence,
    )


def _render_node_once(
    node: Mapping[str, Any], parent: ET.Element | None, assignments: Mapping[str, Any],
    active_locations: set[tuple[int, ...]], cda: Mapping[str, Any],
    location: tuple[int, ...], null_flavor: str, problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...],
) -> list[ET.Element]:
    required = _has_required_content(node)

    element = (
        ET.Element(_qname(str(node.get("name") or "element")))
        if parent is None
        else ET.SubElement(parent, _qname(str(node.get("name") or "element")))
    )

    if node.get("asserts"):
        assertion_contexts.append((element, list(node.get("asserts", [])), dict(node.get("lets", {}))))

    for key, value in node.get("fixed", {}).items():
        if value is not None:
            element.set(_qname(str(key)), str(value))
    if node.get("fixed_text") is not None:
        element.text = str(node.get("fixed_text"))

    for attr in node.get("attributes", []):
        name = str(attr.get("name") or "")
        if not name:
            continue
        value = attr.get("value")
        assigned, target_name = _value_for_attribute(attr, assignments)
        if target_name is not None:
            value = _at(assigned, occurrence)
        if isinstance(value, Mapping) and value.get("nullFlavor"):
            value = None
        if value is None and attr.get("optional") is False:
            raise ValueError(f"required CDA attribute @{name} on {node.get('name')} has no fixed or assigned value")
        if value is not None:
            if _base_datatype(attr.get("datatype")) == "BL" or name == "negationInd":
                value = "true" if bool(value) else "false"
            element.set(_qname(name), str(value))

    assigned, target_name = _value_for_node(node, assignments)
    if target_name is not None:
        assigned = _at(assigned, occurrence)
    if assigned is not None:
        _write_value(element, assigned, node)
    elif node.get("codes"):
        codes = node.get("codes") or []
        if len(codes) == 1:
            _set_xsi_type(element, node)
            element.set("code", str(codes[0].get("code")))
            if codes[0].get("code_system"):
                element.set("codeSystem", str(codes[0]["code_system"]))

    child_count = 0
    for index, child in enumerate(node.get("children", [])):
        child_count += len(
            _render_node(
                child, element, assignments, active_locations, cda, location + (index,),
                null_flavor, problems, assertion_contexts, occurrence,
            )
        )

    if required and assigned is None and not child_count and not element.attrib and not element.text:
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

    document = cda.get("document", [])
    if not document:
        raise ValueError("compiled CDA model contains no document element")
    active_locations = _active_target_locations(cda, assignments)
    null_flavor = str(site.get("null_flavor", {}).get("missing_required") or "NI")
    roots: list[ET.Element] = []
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]] = []
    for index, node in enumerate(document):
        roots.extend(
            _render_node(
                node, None, assignments, active_locations, cda, (index,),
                null_flavor, problems, assertion_contexts, (),
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
