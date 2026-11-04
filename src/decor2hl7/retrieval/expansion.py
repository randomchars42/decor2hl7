"""Validate and normalize frozen ART-DECOR value-set expansions."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from .xml import local, parse_text


def expansion_status(payload: bytes) -> tuple[bool, str]:
    """Return whether an expansion payload is complete and usable.

    ART-DECOR's ``$expand`` response is a ``valueSetExpansionSet`` whose
    ``current`` count can be lower than ``count`` when the server caps the
    response.  Such a prefix is evidence, but it is not safe compiler input.
    Plain extensional ``valueSet`` responses remain accepted for compatible
    repositories and tests.
    """
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return False, "value-set expansion is not valid XML"
    return expansion_root_status(root)


def expansion_root_status(root: ET.Element) -> tuple[bool, str]:
    kind = local(root.tag)
    if kind == "valueSet":
        members = _coded_members(root)
        if members:
            return True, ""
        return False, "value-set expansion contains no coded members"
    if kind != "valueSetExpansionSet":
        return False, "value-set expansion has no valueSetExpansionSet envelope"

    try:
        current = int(str(root.get("current") or ""))
        count = int(str(root.get("count") or ""))
    except ValueError:
        return False, "value-set expansion has no numeric current/count totals"
    if current < count:
        return False, (
            f"partial value-set expansion: returned {current} of {count} members"
        )
    if current > count:
        return False, (
            f"invalid value-set expansion totals: current {current} exceeds count {count}"
        )

    expansion = next(
        (child for child in root if local(child.tag) == "expansion"), None
    )
    members = _coded_members(expansion) if expansion is not None else []
    if count == 0:
        return False, "value-set expansion is complete but contains no coded members"
    if len(members) != current:
        return False, (
            "value-set expansion member count does not match current: "
            f"found {len(members)}, expected {current}"
        )
    if not any(
        local(child.tag) == "valueSet" and child.get("id")
        and child.get("effectiveDate")
        for child in root
    ):
        return False, "value-set expansion has no exact value-set identity"
    return True, ""


def normalized_value_sets(root: ET.Element) -> list[ET.Element]:
    """Return exact extensional value sets from one usable expansion payload."""
    usable, _ = expansion_root_status(root)
    if not usable:
        return []
    if local(root.tag) == "valueSet":
        return [copy.deepcopy(root)]

    expansion = next(
        child for child in root if local(child.tag) == "expansion"
    )
    members = _coded_members(expansion)
    result: list[ET.Element] = []
    for definition in root:
        if (
            local(definition.tag) != "valueSet"
            or not definition.get("id")
            or not definition.get("effectiveDate")
        ):
            continue
        value_set = copy.deepcopy(definition)
        for child in list(value_set):
            if local(child.tag) == "conceptList":
                value_set.remove(child)
        concept_list = ET.SubElement(value_set, "conceptList")
        for item in members:
            concept = copy.deepcopy(item)
            concept.tag = (
                str(item.get("is") or "concept")
                if local(item.tag) == "items" else local(item.tag)
            )
            concept.attrib.pop("is", None)
            concept_list.append(concept)
        result.append(value_set)
    return result


def _coded_members(node: ET.Element | None) -> list[ET.Element]:
    if node is None:
        return []
    return [
        child for child in node.iter()
        if local(child.tag) in {"concept", "exception", "items"}
        and child.get("code")
        and child.get("codeSystem")
        and (
            local(child.tag) != "items"
            or child.get("is") in {None, "concept", "exception"}
        )
    ]
