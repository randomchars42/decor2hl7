"""Render normalized model records using the compiled CDA target model.

Runtime addresses are generated human-readable target names. ART-DECOR element
ids are provenance only; an element does not need an id to be writable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from ..assertions import validate_contexts
from ..bindings import (
    authorizes_coded_original_text,
    build_assignments,
    fallback_if_active_value,
    is_fallback_if_active,
    non_null_requirement_problems,
    required_unmapped_null_flavor,
    resolve_required_unmapped_null_flavor,
    target_default_values,
    unwrap_fallback_if_active,
)
from ..cooccurrence import (
    cooccurrence_problem_message, datatype_cooccurrence_problems,
)
from .semantics import units_equivalent
from .model import ValueRepresentationKind
from .narrative import build_section_narratives
from .terminology import (
    NULL_FLAVOR_CODE_SYSTEM,
    NULL_FLAVORS,
    NULL_FLAVORS_WITH_ORIGINAL_TEXT,
    ORIGINAL_TEXT_NULL_FLAVOR_PREFERENCE,
    complete_required_binding_code,
    null_flavor as coded_null_flavor,
    required_binding_value_error,
)

HL7 = "urn:hl7-org:v3"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("", HL7)
ET.register_namespace("xsi", XSI)


def _qname(name: str, namespace_uri: str | None = None) -> str:
    # ART-DECOR uses XPath-like predicates to distinguish sibling constraint
    # branches (for example ``hl7:id[1]`` or a coded qualifier).  The predicate
    # selects the effective constraint; it is never part of the XML QName.
    name = name.split("[", 1)[0]
    if namespace_uri:
        return f"{{{namespace_uri}}}{name.split(':', 1)[-1]}"
    if name.startswith(("hl7:", "cda:")):
        return f"{{{HL7}}}{name.split(':', 1)[1]}"
    if name.startswith("xsi:"):
        return f"{{{XSI}}}{name.split(':', 1)[1]}"
    if name.startswith("xml:"):
        return f"{{http://www.w3.org/XML/1998/namespace}}{name.split(':', 1)[1]}"
    return name


def _register_compiled_namespaces(document: list[Mapping[str, Any]]) -> None:
    """Register stable prefixes carried by the compiled ART-DECOR QNames."""
    claimed = {
        "": HL7,
        "xsi": XSI,
        "xml": "http://www.w3.org/XML/1998/namespace",
    }
    pairs: set[tuple[str, str]] = set()

    def collect(nodes: list[Mapping[str, Any]]) -> None:
        for node in nodes:
            prefix = str(node.get("namespace_prefix") or "")
            uri = str(node.get("namespace_uri") or "")
            if prefix and uri:
                pairs.add((prefix, uri))
            for attribute in node.get("attributes", []):
                prefix = str(attribute.get("namespace_prefix") or "")
                uri = str(attribute.get("namespace_uri") or "")
                if prefix and uri:
                    pairs.add((prefix, uri))
            collect(list(node.get("children", [])))

    collect(document)
    registered_uris = set(claimed.values())
    ET.register_namespace("", HL7)
    ET.register_namespace("xsi", XSI)
    for preferred, uri in sorted(pairs):
        if uri in registered_uris:
            continue
        prefix = preferred
        suffix = 2
        while prefix in claimed and claimed[prefix] != uri:
            prefix = f"{preferred}{suffix}"
            suffix += 1
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            # Invalid/reserved lexical prefixes do not affect expanded QName
            # correctness; ElementTree will allocate a safe synthetic prefix.
            continue
        claimed[prefix] = uri
        registered_uris.add(uri)


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


def _has_direct_fallback_assignment(
    node: Mapping[str, Any],
    assignments: Mapping[str, Any],
    occurrence: tuple[int, ...],
) -> bool:
    """Return whether this leaf has an activation-scoped completion value."""
    # Attribute completion is consumed only after this element is selected;
    # it must never make an optional element active by itself.
    names = [str(name) for name in node.get("targets", [])]
    return any(
        name in assignments
        and is_fallback_if_active(assignments[name])
        and _at(unwrap_fallback_if_active(assignments[name]), occurrence)
        is not None
        for name in names
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


def _ordered_children(
    node: Mapping[str, Any],
) -> list[tuple[int, Mapping[str, Any]]]:
    """Return source indices in the separately compiled XML render order."""
    return sorted(
        enumerate(node.get("children", [])),
        key=lambda item: (int(item[1].get("render_order", item[0])), item[0]),
    )


def _set_xsi_type(element: ET.Element, representation: Mapping[str, Any]) -> None:
    xsi_type = representation.get("xsi_type")
    if xsi_type:
        element.set(f"{{{XSI}}}type", str(xsi_type))


def _constraint_scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def _fraction_digits(value: Any) -> int | None:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    exponent = decimal.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else None


def _property_hard_match(rule: Mapping[str, Any], value: Any) -> bool:
    scalar = _constraint_scalar(value)
    if rule.get("value") is not None and str(scalar) != str(rule["value"]):
        return False
    for key in ("unit", "currency"):
        if rule.get(key) is not None and (
            not isinstance(value, Mapping)
            or str(value.get(key) or "") != str(rule[key])
        ):
            return False
    length = len(str(scalar)) if scalar is not None else 0
    if rule.get("min_length") is not None and length < int(rule["min_length"]):
        return False
    if rule.get("max_length") is not None and length > int(rule["max_length"]):
        return False
    return True


def _property_advisory_match(rule: Mapping[str, Any], value: Any) -> bool:
    scalar = _constraint_scalar(value)
    try:
        number = Decimal(str(scalar))
    except (InvalidOperation, ValueError):
        return False
    if rule.get("min_include") is not None and number < Decimal(
        str(rule["min_include"])
    ):
        return False
    if rule.get("max_include") is not None and number > Decimal(
        str(rule["max_include"])
    ):
        return False
    raw_digits = str(rule.get("fraction_digits") or "")
    if raw_digits:
        digits = _fraction_digits(scalar)
        if digits is None:
            return False
        wanted = int(re.sub(r"\D", "", raw_digits))
        if raw_digits.endswith("!") and digits != wanted:
            return False
        if raw_digits.endswith(".") and digits > wanted:
            return False
        if not raw_digits.endswith(("!", ".")) and digits < wanted:
            return False
    return True


def _formal_property_companions(
    target: Mapping[str, Any], node: Mapping[str, Any],
) -> dict[str, str]:
    """Return unambiguous output attributes fixed by ART-DECOR properties."""
    raw_properties = node.get("properties")
    if raw_properties is None:
        raw_properties = target.get("properties") or []
    properties = [
        rule for rule in raw_properties if isinstance(rule, Mapping)
    ]
    companions: dict[str, str] = {}
    for name in ("unit", "currency"):
        values = {
            str(rule[name]) for rule in properties
            if rule.get(name) is not None
        }
        if len(values) == 1:
            companions[name] = next(iter(values))
    if node.get("unit") is not None:
        companions.setdefault("unit", str(node["unit"]))
    return companions


def _with_formal_property_companions(
    value: Any, target: Mapping[str, Any], node: Mapping[str, Any],
) -> Any:
    companions = _formal_property_companions(target, node)
    if not companions or isinstance(value, Mapping) and value.get("nullFlavor"):
        return value
    if isinstance(value, Mapping):
        completed = dict(value)
        for name, companion in companions.items():
            supplied = completed.get(name)
            if supplied is None:
                completed[name] = companion
            elif name == "unit" and units_equivalent(supplied, companion):
                # The mapping compatibility rule has already established the
                # semantic equivalence.  Serialize the exact target spelling.
                completed[name] = companion
        return completed
    return {"value": value, **companions}


def _validate_compiled_value(
    value: Any, target: Mapping[str, Any], node: Mapping[str, Any],
    problems: list[str] | None,
    terminology_constraints: Mapping[str, Any] | None = None,
) -> None:
    """Enforce executable ART-DECOR datatype and property constraints."""
    binding_error = required_binding_value_error(
        value, target, terminology_constraints,
    )
    if binding_error:
        identity = str(target.get("path") or node.get("name") or "CDA value")
        raise ValueError(f"CDA target {identity}: {binding_error}")
    if coded_null_flavor(value):
        return
    datatype = str(node.get("datatype") or target.get("datatype") or "").upper()
    scalar = _constraint_scalar(value)
    if datatype == "INT.POS":
        try:
            valid = Decimal(str(scalar)) > 0
        except InvalidOperation:
            valid = False
        if not valid:
            raise ValueError("INT.POS value must be greater than zero")
    elif datatype in {"TS.DATE.MIN", "TS.DATETIME.MIN"}:
        rendered = _cda_timestamp(str(scalar))
        minimum = 8 if datatype == "TS.DATE.MIN" else 14
        if not re.match(rf"^[0-9]{{{minimum}}}", rendered):
            raise ValueError(
                f"{datatype} value must have at least {minimum} timestamp digits"
            )
    elif datatype == "CS.LANG":
        code = value.get("code") if isinstance(value, Mapping) else scalar
        if code and not re.fullmatch(
            r"(?:[a-z]{2,3}(?:-[a-z]{2})?|[ix](?:-[a-z\d]{2,8})+)",
            str(code), re.I,
        ):
            raise ValueError(f"CS.LANG code {code!r} is not an RFC 3066 tag")

    raw_properties = node.get("properties")
    if raw_properties is None:
        raw_properties = target.get("properties") or []
    properties = [
        rule for rule in raw_properties
        if isinstance(rule, Mapping)
    ]
    hard = [
        rule for rule in properties
        if any(rule.get(key) is not None for key in (
            "unit", "currency", "value", "min_length", "max_length",
        ))
    ]
    if hard and not any(_property_hard_match(rule, value) for rule in hard):
        identity = str(target.get("path") or node.get("name") or "CDA value")
        raise ValueError(
            f"CDA target {identity} value {value!r} violates ART-DECOR "
            f"property constraints {hard!r}"
        )
    advisory = [
        rule for rule in properties
        if any(rule.get(key) is not None for key in (
            "min_include", "max_include", "fraction_digits",
        ))
    ]
    if advisory and not any(
        _property_advisory_match(rule, value) for rule in advisory
    ) and problems is not None:
        problems.append(
            "CDA value is outside the ART-DECOR recommended range or fraction digits"
        )


def _write_section_narrative(
    element: ET.Element, value: Mapping[str, Any], target: Mapping[str, Any]
) -> None:
    """Write the portable section-narrative intermediate representation."""
    paragraphs = [
        item for item in value.get("paragraphs", [])
        if isinstance(item, Mapping) and item.get("text") not in (None, "")
    ]
    facts = [
        item for item in value.get("facts", [])
        if isinstance(item, Mapping) and item.get("value") not in (None, "")
    ]
    repeated = [
        item for item in value.get("repeated_facts", [])
        if isinstance(item, Mapping) and item.get("value") not in (None, "")
    ]
    links = [
        item for item in value.get("entry_links", [])
        if isinstance(item, Mapping) and item.get("id")
        and item.get("text") not in (None, "")
    ]
    structured = str(target.get("datatype") or "").upper() == "SD.TEXT"
    if not structured:
        parts = [str(item["text"]) for item in paragraphs]
        parts.extend(f"{item.get('label')}: {item['value']}" for item in facts)
        parts.extend(
            f"{'.'.join(str(int(index) + 1) for index in item.get('occurrence', []))} "
            f"{item.get('label')}: {item['value']}"
            for item in repeated
        )
        parts.extend(str(item["text"]) for item in links)
        element.text = "; ".join(part for part in parts if part) or None
        return

    for item in paragraphs:
        paragraph = ET.SubElement(element, f"{{{HL7}}}paragraph")
        paragraph.text = str(item["text"])

    consumed_links: set[int] = set()

    def value_cell(
        row: ET.Element, item: Mapping[str, Any], occurrence: tuple[int, ...]
    ) -> None:
        cell = ET.SubElement(row, f"{{{HL7}}}td")
        link_index = next((
            index for index, link in enumerate(links)
            if index not in consumed_links
            and tuple(link.get("occurrence", [])) == occurrence
        ), None)
        if link_index is None:
            cell.text = str(item["value"])
            return
        consumed_links.add(link_index)
        content = ET.SubElement(cell, f"{{{HL7}}}content")
        content.set("ID", str(links[link_index]["id"]))
        content.text = str(item["value"])

    if facts:
        table = ET.SubElement(element, f"{{{HL7}}}table")
        head = ET.SubElement(table, f"{{{HL7}}}thead")
        row = ET.SubElement(head, f"{{{HL7}}}tr")
        for heading in ("Merkmal", "Wert"):
            cell = ET.SubElement(row, f"{{{HL7}}}th")
            cell.text = heading
        body = ET.SubElement(table, f"{{{HL7}}}tbody")
        for item in facts:
            row = ET.SubElement(body, f"{{{HL7}}}tr")
            label = ET.SubElement(row, f"{{{HL7}}}td")
            label.text = str(item.get("label") or "Merkmal")
            value_cell(row, item, ())

    repeated_groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for item in repeated:
        repeated_groups.setdefault(
            tuple(str(part) for part in item.get("repeat_chain", [])), []
        ).append(item)
    for repeated_rows in repeated_groups.values():
        table = ET.SubElement(element, f"{{{HL7}}}table")
        head = ET.SubElement(table, f"{{{HL7}}}thead")
        row = ET.SubElement(head, f"{{{HL7}}}tr")
        for heading in ("Vorkommen", "Merkmal", "Wert"):
            cell = ET.SubElement(row, f"{{{HL7}}}th")
            cell.text = heading
        body = ET.SubElement(table, f"{{{HL7}}}tbody")
        ordered_rows = sorted(
            enumerate(repeated_rows),
            key=lambda pair: (tuple(pair[1].get("occurrence", [])), pair[0]),
        )
        for _index, item in ordered_rows:
            occurrence = tuple(int(index) for index in item.get("occurrence", []))
            row = ET.SubElement(body, f"{{{HL7}}}tr")
            ordinal = ET.SubElement(row, f"{{{HL7}}}td")
            ordinal.text = ".".join(str(index + 1) for index in occurrence) or "1"
            label = ET.SubElement(row, f"{{{HL7}}}td")
            label.text = str(item.get("label") or "Merkmal")
            value_cell(row, item, occurrence)

    remaining = [
        item for index, item in enumerate(links) if index not in consumed_links
    ]
    if remaining:
        listing = ET.SubElement(element, f"{{{HL7}}}list")
        for item in remaining:
            list_item = ET.SubElement(listing, f"{{{HL7}}}item")
            content = ET.SubElement(list_item, f"{{{HL7}}}content")
            content.set("ID", str(item["id"]))
            content.text = str(item["text"])


def _write_value(
    element: ET.Element,
    value: Any,
    target: Mapping[str, Any],
    node: Mapping[str, Any],
    problems: list[str] | None = None,
    terminology_constraints: Mapping[str, Any] | None = None,
) -> None:
    representation = target.get("value_representation")
    if not isinstance(representation, Mapping) or not representation.get("kind"):
        raise ValueError(
            f"CDA value target {target.get('path') or node.get('name')} has no compiled value representation"
        )
    value = complete_required_binding_code(
        value, target, terminology_constraints,
    )
    value = _with_formal_property_companions(value, target, node)
    _validate_compiled_value(
        value, target, node, problems, terminology_constraints
    )
    _set_xsi_type(element, representation)
    if (
        isinstance(value, Mapping)
        and str(value.get("codeSystem") or value.get("code_system") or "")
        == NULL_FLAVOR_CODE_SYSTEM
        and str(value.get("code") or "") in NULL_FLAVORS
        and target.get("permits_null_flavor")
    ):
        value = {"nullFlavor": str(value["code"])}
    if isinstance(value, Mapping) and value.get("__section_narrative__"):
        _write_section_narrative(element, value, target)
        return
    if isinstance(value, Mapping) and value.get("nullFlavor"):
        element.set("nullFlavor", str(value["nullFlavor"]))
        return
    if target.get("narrative_link"):
        # The mapped scalar is rendered once in the containing section's
        # structured narrative. This entry text carries only the compiled
        # fragment reference emitted by its required child.
        return
    kind = ValueRepresentationKind(str(representation["kind"]))
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
    for key, item in _formal_property_companions(target, node).items():
        element.set(key, item)


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
    for name, value in assignments.items():
        target = targets.get(name, {})
        if (
            target.get("system_value") == "generated_identifier"
            or is_fallback_if_active(value)
        ):
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


def _activate_fallback_elements(
    cda: Mapping[str, Any],
    assignments: Mapping[str, Any],
    active: set[tuple[int, ...]],
) -> None:
    """Activate a fallback element only below an already active owner.

    Attribute fallbacks are consumed while their owning element renders.  An
    optional element fallback needs its own location activated, but may do so
    only when another assignment has already selected its immediate parent.
    This preserves ``fallback_if_active``'s promise not to create a branch.
    """
    for name, value in assignments.items():
        if not is_fallback_if_active(value):
            continue
        target = cda.get("targets", {}).get(name, {})
        for raw_location in target.get("locations", []):
            try:
                location = tuple(
                    int(part) for part in str(raw_location).split(".")
                )
            except ValueError:
                continue
            if not location or location[-1] >= 100000:
                continue
            if location[:-1] in active:
                active.add(location)


def _narrative_scalars(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for nested in value for item in _narrative_scalars(nested)]
    if isinstance(value, Mapping):
        if any(str(key).startswith("__") for key in value):
            return []
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
    record: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    site: Mapping[str, Any],
) -> None:
    """Complete section roles with checked, mapping-aware presentation."""
    del document, targets
    titles, narratives = build_section_narratives(
        record, model, cda, mapping, assignments, explicit_names, site
    )
    assignments.update(titles)
    assignments.update(narratives)


def _narrative_occurrences(
    value: Any, minimum_depth: int, prefix: tuple[int, ...] = (),
) -> list[tuple[int, ...]]:
    """Return present assignment leaves as renderer occurrence tuples."""
    if isinstance(value, list):
        return [
            occurrence
            for index, item in enumerate(value)
            for occurrence in _narrative_occurrences(
                item, minimum_depth, prefix + (index,)
            )
        ]
    if value is None or (
        isinstance(value, Mapping) and value.get("nullFlavor")
    ):
        return []
    return [prefix + (0,) * max(0, minimum_depth - len(prefix))]


def _target_below_location(
    target: Mapping[str, Any], owner_location: str,
) -> bool:
    return any(
        str(location) == owner_location
        or str(location).startswith(owner_location + ".")
        for location in target.get("locations", [])
    )


def _occurrence_assignment(
    values: Mapping[tuple[int, ...], Any], depth: int,
) -> Any:
    """Build the sparse nested-list shape consumed by ``_nested_at``."""
    if depth == 0:
        return values.get(())

    def build(prefix: tuple[int, ...]) -> Any:
        if len(prefix) == depth:
            return values.get(prefix)
        indices = {
            occurrence[len(prefix)]
            for occurrence in values
            if occurrence[:len(prefix)] == prefix
        }
        if not indices:
            return None
        return [
            build(prefix + (index,))
            for index in range(max(indices) + 1)
        ]

    return build(())


def _merge_section_fragments(
    current: Any,
    fragments: Mapping[tuple[int, ...], list[dict[str, Any]]],
    depth: int,
) -> Any:
    """Merge generated ``content`` nodes into a section-shaped assignment."""
    def merge(prefix: tuple[int, ...], value: Any) -> Any:
        if len(prefix) == depth:
            additions = list(fragments.get(prefix, []))
            if not additions:
                return value
            if isinstance(value, Mapping) and value.get("__section_narrative__"):
                return {
                    **dict(value),
                    "entry_links": list(value.get("entry_links", [])) + additions,
                }
            text = "; ".join(
                dict.fromkeys(item for item in _narrative_scalars(value) if item)
            )
            return {
                "__section_narrative__": True,
                "paragraphs": ([{"text": text}] if text else []),
                "facts": [],
                "repeated_facts": [],
                "entry_links": additions,
            }

        matching = {
            occurrence[len(prefix)]
            for occurrence in fragments
            if occurrence[:len(prefix)] == prefix
        }
        current_items = value if isinstance(value, list) else []
        count = max(
            len(current_items),
            max(matching) + 1 if matching else 0,
        )
        if count == 0:
            return value
        result: list[Any] = []
        for index in range(count):
            if index < len(current_items):
                child = current_items[index]
            elif index == 0 and not isinstance(value, list):
                child = value
            else:
                child = None
            result.append(merge(prefix + (index,), child))
        return result

    return merge((), current)


def _complete_linked_narratives(
    targets: Mapping[str, Mapping[str, Any]],
    assignments: dict[str, Any],
    explicit_names: set[str],
    record_key: Any,
    document_version: int,
) -> None:
    """Generate occurrence-local entry references and section narrative IDs."""
    section_fragments: dict[
        str, dict[tuple[int, ...], list[dict[str, Any]]]
    ] = {}
    section_depths: dict[str, int] = {}

    for source_name in sorted(targets):
        source_target = targets[source_name]
        relation = source_target.get("narrative_link")
        if not isinstance(relation, Mapping):
            continue
        reference_name = str(relation.get("reference_target") or "")
        section_name = str(relation.get("section_narrative_target") or "")
        owner_location = str(relation.get("owner_location") or "")
        occurrence_depth = int(relation.get("occurrence_depth") or 0)
        section_depth = int(relation.get("section_occurrence_depth") or 0)
        if not reference_name or not section_name or not owner_location:
            continue

        owner_assignments = [
            name for name in assignments
            if not targets.get(name, {}).get("system_value")
            and _target_below_location(targets.get(name, {}), owner_location)
        ]
        occurrences = {
            occurrence[:occurrence_depth]
            for name in owner_assignments
            for occurrence in _narrative_occurrences(
                assignments[name], occurrence_depth
            )
        }
        if not occurrences:
            continue

        reference_values: dict[tuple[int, ...], str] = {}
        grouped = section_fragments.setdefault(section_name, {})
        section_depths[section_name] = section_depth
        fallback_names = sorted(set(owner_assignments) & explicit_names)
        for occurrence in sorted(occurrences):
            direct = _nested_at(assignments.get(source_name), occurrence)
            wording = _narrative_scalars(direct)
            if not wording:
                wording = [
                    item
                    for name in fallback_names
                    for item in _narrative_scalars(
                        _nested_at(assignments.get(name), occurrence)
                    )
                ]
            text = "; ".join(dict.fromkeys(item for item in wording if item))
            if not text:
                text = str(
                    source_target.get("template_display_name")
                    or source_target.get("template_name")
                    or "Entry"
                )
            identity = "|".join((
                str(record_key or ""),
                str(document_version),
                source_name,
                ".".join(map(str, occurrence)),
            ))
            fragment_id = "d2h-narrative-" + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()[:20]
            reference_values[occurrence] = "#" + fragment_id
            grouped.setdefault(occurrence[:section_depth], []).append({
                "id": fragment_id,
                "text": text,
                "occurrence": list(occurrence[section_depth:]),
            })
        assignments[reference_name] = _occurrence_assignment(
            reference_values, occurrence_depth
        )

    for section_name, fragments in section_fragments.items():
        assignments[section_name] = _merge_section_fragments(
            assignments.get(section_name),
            fragments,
            section_depths[section_name],
        )


def _coded_original_text(value: Any) -> Any:
    """Preserve occurrence shape while extracting a coded value's wording."""
    if isinstance(value, list):
        return [_coded_original_text(item) for item in value]
    if not isinstance(value, Mapping):
        return None
    flavor = coded_null_flavor(value)
    # Only null flavors whose datatype meaning carries an alternate value may
    # gain originalText. Other flavors describe why no concept is known.
    if (
        flavor
        and flavor not in NULL_FLAVORS_WITH_ORIGINAL_TEXT
        and not authorizes_coded_original_text(value)
    ):
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
        if is_fallback_if_active(value):
            # An activation-scoped fallback may fill an occurrence selected by
            # another value, but it must never create a repeated occurrence.
            continue
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
    target_defaults: Mapping[str, Any],
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
    required = _has_required_content(node) or bool(node.get("transparent_inline"))
    active = location in active_locations and (
        _subtree_has_assignment(node, assignments, occurrence)
        or _has_physical_value_below(location, physical_values)
    )
    if not required and not active:
        return []
    if parent is None and node.get("attributes"):
        raise ValueError(
            "ART-DECOR template-context attributes have no XML owner"
        )
    for attribute in node.get("attributes", []):
        name = str(attribute.get("name") or "")
        value = attribute.get("value")
        if not name:
            continue
        if value is None and attribute.get("optional") is False:
            raise ValueError(
                f"required ART-DECOR context attribute @{name} has no value"
            )
        if value is not None and parent is not None:
            qname = _qname(
                name, str(attribute.get("namespace_uri") or "") or None,
            )
            current = parent.get(qname)
            if current is not None and current != str(value):
                raise ValueError(
                    f"conflicting ART-DECOR context attribute @{name}: "
                    f"{current!r} != {value!r}"
                )
            parent.set(qname, str(value))
    validation_rules = list(node.get("validation_rules", []))
    if validation_rules:
        if parent is None:
            raise ValueError(
                "ART-DECOR template-context validation rule has no XML owner"
            )
        assertion_contexts.append((
            parent, validation_rules, dict(node.get("lets", {}))
        ))
    xsi_type = node.get("xsi_type")
    if xsi_type and parent is not None:
        key = f"{{{XSI}}}type"
        existing = parent.get(key)
        if existing and existing != str(xsi_type):
            raise ValueError(
                f"conflicting compiled datatype choices {existing!r} and "
                f"{xsi_type!r} on {parent.tag}"
            )
        parent.set(key, str(xsi_type))
    maximum = node.get("max")
    repeats_here = maximum is None or (isinstance(maximum, int) and maximum > 1)
    occurrences = [occurrence]
    if repeats_here:
        count = _repeat_count(node, location, occurrence, assignments, cda)
        occurrences = [occurrence + (index,) for index in range(count)]
    result: list[ET.Element] = []
    for current_occurrence in occurrences:
        for index, child in _ordered_children(node):
            result.extend(
                _render_node(
                    child, parent, assignments, target_defaults, active_locations, cda,
                    location + (index,), null_flavor, problems, assertion_contexts,
                    current_occurrence, physical_values,
                )
            )
    return result


def _render_choice(
    node: Mapping[str, Any],
    parent: ET.Element | None,
    assignments: Mapping[str, Any],
    target_defaults: Mapping[str, Any],
    active_locations: set[tuple[int, ...]],
    cda: Mapping[str, Any],
    location: tuple[int, ...],
    null_flavor: str,
    problems: list[str],
    assertion_contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
    occurrence: tuple[int, ...],
    physical_values: Mapping[tuple[int, ...], tuple[Any, Mapping[str, Any]]],
) -> list[ET.Element]:
    """Render only the selected alternatives of one ART-DECOR choice."""
    children = list(node.get("children", []))
    selected: list[int] = []
    for index, child in enumerate(children):
        child_location = location + (index,)
        if (
            _subtree_has_assignment(child, assignments, occurrence)
            or _has_physical_value_below(child_location, physical_values)
            or any(
                candidate[:len(child_location)] == child_location
                for candidate in active_locations
            )
        ):
            selected.append(index)
    minimum = int(node.get("min") or 0)
    maximum = node.get("max")
    if isinstance(maximum, int) and len(selected) > maximum:
        alternatives = [
            str(
                children[index].get("origin", {}).get("path")
                or children[index].get("path")
                or children[index].get("name")
                or f"alternative {index + 1}"
            )
            for index in selected
        ]
        raise ValueError(
            "generated CDA selects too many ART-DECOR choice alternatives "
            f"at {'.'.join(map(str, location))}: {len(selected)} > {maximum}; "
            f"selected {alternatives!r}"
        )
    if len(selected) < minimum:
        for index in range(len(children)):
            if index not in selected:
                selected.append(index)
            if len(selected) >= minimum:
                break
    if len(selected) < minimum:
        raise ValueError(
            "generated CDA cannot satisfy ART-DECOR choice minimum: "
            f"{len(selected)} < {minimum}"
        )
    result: list[ET.Element] = []
    for index in selected:
        child = children[index]
        # Once the group has selected an alternative, that particle occurs at
        # least once even when its own source multiplicity was omitted/zero.
        # The branch's maximum and repeated-value handling remain unchanged.
        if not _has_required_content(child):
            child = dict(child)
            child["min"] = 1
        result.extend(_render_node(
            child, parent, assignments, target_defaults,
            active_locations, cda, location + (index,), null_flavor,
            problems, assertion_contexts, occurrence, physical_values,
        ))
    return result


def _render_node(
    node: Mapping[str, Any],
    parent: ET.Element | None,
    assignments: Mapping[str, Any],
    target_defaults: Mapping[str, Any],
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
    if node.get("kind") == "choice":
        return _render_choice(
            node, parent, assignments, target_defaults, active_locations, cda,
            location, null_flavor, problems, assertion_contexts, occurrence,
            physical_values,
        )
    if node.get("kind") in {"include", "template", "datatype_choice"}:
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
    if parent is not None and _has_direct_fallback_assignment(
        node, assignments, occurrence
    ):
        # Reaching this call means the owning XML element already exists.
        # A direct completion value may fill its leaf without selecting an
        # otherwise absent ancestor branch.
        active = True
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
    target_defaults: Mapping[str, Any],
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
        ET.Element(_qname(
            str(node.get("name") or "element"),
            str(node.get("namespace_uri") or "") or None,
        ))
        if parent is None
        else ET.SubElement(parent, _qname(
            str(node.get("name") or "element"),
            str(node.get("namespace_uri") or "") or None,
        ))
    )
    if node.get("xsi_type"):
        element.set(f"{{{XSI}}}type", str(node["xsi_type"]))

    validation_rules = list(node.get("validation_rules", []))
    if validation_rules:
        assertion_contexts.append((
            element, validation_rules, dict(node.get("lets", {}))
        ))

    conditional_fixed_attributes = {
        str(attr.get("name") or "")
        for attr in node.get("attributes", [])
        if attr.get("conditional_fixed")
    }
    attribute_namespaces = {
        str(attr.get("name") or ""): str(attr.get("namespace_uri") or "")
        for attr in node.get("attributes", [])
    }
    for key, value in node.get("fixed", {}).items():
        if str(key) in conditional_fixed_attributes:
            continue
        if value is not None:
            element.set(
                _qname(
                    str(key), attribute_namespaces.get(str(key)) or None,
                ),
                str(value),
            )
    if node.get("fixed_text") is not None:
        element.text = str(node.get("fixed_text"))

    node_representation: Mapping[str, Any] = next(
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
            value = _at(unwrap_fallback_if_active(assigned), occurrence)
        if value is None:
            for target in attr.get("targets", []):
                if str(target) in target_defaults:
                    value = target_defaults[str(target)]
                    target_name = str(target)
                    break
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
            element.set(
                _qname(
                    name, str(attr.get("namespace_uri") or "") or None,
                ),
                str(value),
            )

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
            assigned = _at(
                unwrap_fallback_if_active(assigned), occurrence
            )
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
        _write_value(
            element, assigned, target, node, problems,
            cda.get("terminology_constraints", {}),
        )
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
                **(
                    {"displayName": codes[0].get("display_name")}
                    if codes[0].get("display_name") else {}
                ),
            },
            target,
            node,
            problems,
            cda.get("terminology_constraints", {}),
        )
    elif default is not None:
        default_name = next(
            (str(name) for name in node.get("targets", []) if str(name) in target_defaults),
            "",
        )
        _write_value(
            element, default, cda.get("targets", {}).get(default_name, {}),
            node, problems,
            cda.get("terminology_constraints", {}),
        )
    for attr in node.get("attributes", []):
        name = str(attr.get("name") or "")
        if (
            name and attr.get("optional") is False
            and _qname(
                name, str(attr.get("namespace_uri") or "") or None,
            ) not in element.attrib
        ):
            raise ValueError(
                f"required CDA attribute @{name} on {node_identity} has no "
                "fixed or assigned value"
            )

    child_count = 0
    for index, child in _ordered_children(node):
        child_count += len(
            _render_node(
                child, element, assignments, target_defaults, active_locations, cda,
                location + (index,), null_flavor, problems, assertion_contexts,
                occurrence, physical_values,
            )
        )

    completion_target = next(
        (
            cda.get("targets", {}).get(str(name), {})
            for name in node.get("targets", [])
            if cda.get("targets", {}).get(str(name), {}).get(
                "value_representation"
            )
        ),
        None,
    )
    if (
        required
        and assigned is None
        and default is None
        and len(node.get("codes") or []) != 1
        and child_count
        and completion_target is not None
        and completion_target.get("permits_null_flavor")
    ):
        legal = {
            str(value)
            for value in completion_target.get("null_flavor_exceptions", [])
            if str(value) in NULL_FLAVORS
        }
        # OTH and UNC are the nullFlavors whose datatype rules can retain
        # originalText-like payload. Prefer OTH because it denotes locally
        # described content; never invent a payload-bearing fallback unless
        # the bound profile explicitly admits it.
        compatible = next(
            (
                value for value in ORIGINAL_TEXT_NULL_FLAVOR_PREFERENCE
                if value in legal
            ),
            None,
        )
        if compatible is not None:
            _write_value(
                element,
                {"nullFlavor": compatible},
                completion_target,
                node,
                problems,
                cda.get("terminology_constraints", {}),
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
        target = completion_target
        if target is not None:
            selected_flavor = resolve_required_unmapped_null_flavor(
                target, null_flavor,
            )
            _write_value(
                element, {"nullFlavor": selected_flavor}, target, node,
                problems,
                cda.get("terminology_constraints", {}),
            )
        else:
            element.set("nullFlavor", null_flavor)
    return [element]


def _inject_document_replacement(
    root: ET.Element,
    document: list[Mapping[str, Any]],
    previous: Mapping[str, Any],
    current_set_id: Mapping[str, Any],
    document_version: int,
) -> None:
    """Render CDA RPLC lineage through the compiled, owner-admitted slot."""
    if len(document) != 1:
        raise ValueError("compiled CDA model has no unique document root")
    def root_particles(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        result: list[Mapping[str, Any]] = []
        for _, child in _ordered_children(node):
            if child.get("kind") in {"include", "template", "datatype_choice", "choice"}:
                result.extend(root_particles(child))
            else:
                result.append(child)
        return result

    children = root_particles(document[0])
    slots = [
        node for node in children
        if (
            node.get("content_role") == "document_replacement"
            or str(node.get("name") or "").split(":", 1)[-1].split("[", 1)[0]
            == "relatedDocument"
        )
    ]
    if len(slots) != 1 or slots[0].get("max") == 0:
        raise ValueError(
            "compiled CDA model does not admit one relatedDocument replacement slot"
        )
    previous_document = previous.get("document_id", {})
    previous_set = previous.get("set_id", {})
    if not isinstance(previous_document, Mapping) or not isinstance(previous_set, Mapping):
        raise ValueError("previous CDA identity is incomplete")
    required = (
        previous_document.get("root"), previous_document.get("extension"),
        previous_set.get("root"), previous_set.get("extension"),
    )
    if not all(str(value or "") for value in required):
        raise ValueError("previous CDA identity is incomplete")
    if int(previous.get("version") or 0) + 1 != document_version:
        raise ValueError("previous CDA version is not the direct predecessor")
    if (
        str(previous_set.get("root")) != str(current_set_id.get("root"))
        or str(previous_set.get("extension")) != str(current_set_id.get("extension"))
    ):
        raise ValueError("previous CDA setId differs from the current document setId")

    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    def tag(name: str) -> str:
        return f"{{{namespace}}}{name}" if namespace else name

    related = ET.Element(tag("relatedDocument"), {"typeCode": "RPLC"})
    parent = ET.SubElement(related, tag("parentDocument"))
    ET.SubElement(parent, tag("id"), {
        "root": str(previous_document["root"]),
        "extension": str(previous_document["extension"]),
    })
    ET.SubElement(parent, tag("setId"), {
        "root": str(previous_set["root"]),
        "extension": str(previous_set["extension"]),
    })
    ET.SubElement(parent, tag("versionNumber"), {
        "value": str(previous["version"]),
    })
    def local_name(value: str) -> str:
        return value.rsplit("}", 1)[-1].split(":", 1)[-1].split("[", 1)[0]

    following_names = {
        local_name(str(node.get("name") or ""))
        for node in children[children.index(slots[0]) + 1:]
    }
    insertion = next(
        (index for index, child in enumerate(root) if local_name(child.tag) in following_names),
        len(root),
    )
    root.insert(insertion, related)


def emit(
    record: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    site: Mapping[str, Any],
    *,
    document_version: int = 1,
    previous_document: Mapping[str, Any] | None = None,
) -> tuple[bytes, list[str]]:
    targets = cda.get("targets", {})
    assignments, problems = build_assignments(record, model, cda, mapping, site)
    target_defaults = target_default_values(cda, mapping)
    explicit_assignment_names = set(assignments)

    generation_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    organization = site.get("organization", {})
    document_root = site.get("identifiers", {}).get("document_root")
    system_values = {
        "document_generation_time": generation_time,
        "document_identifier": {
            "root": document_root or "",
            "extension": f"{record.get('key')}-{document_version}",
        },
        "document_set_identifier": {
            "root": document_root or "", "extension": str(record.get("key")),
        },
        "document_version_number": document_version,
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

    for name, value in site.get("cda", {}).get("values", {}).items():
        if name in targets and targets[name].get("renderable") and len(targets[name].get("locations", [])) == 1:
            assignments.setdefault(name, _format_site(value, variables))
        else:
            problems.append(f"site configuration references unknown, prohibited or ambiguous CDA target {name!r}")

    for name, value in site.get("cda", {}).get(
        "fallback_if_active", {}
    ).items():
        if (
            name in targets and targets[name].get("renderable")
            and len(targets[name].get("locations", [])) == 1
        ):
            assignments.setdefault(
                name,
                fallback_if_active_value(_format_site(value, variables)),
            )
        else:
            problems.append(
                "site configuration references unknown, prohibited or "
                f"ambiguous CDA fallback target {name!r}"
            )

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
    _register_compiled_namespaces(list(document))

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
                representation_target: Mapping[str, Any] = next(
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
        list(document), targets, assignments, explicit_assignment_names,
        record, model, cda, mapping, site,
    )
    _complete_linked_narratives(
        targets, assignments, explicit_assignment_names,
        record.get("key"), document_version,
    )
    compound_problems = non_null_requirement_problems(cda, assignments)
    if compound_problems:
        raise ValueError(
            "generated CDA violates compound datatype requirements:\n"
            + "\n".join(compound_problems)
        )
    datatype_problems = datatype_cooccurrence_problems(
        cda, {**target_defaults, **assignments},
    )
    if datatype_problems:
        raise ValueError(
            "generated CDA violates datatype co-occurrence requirements:\n"
            + "\n".join(
                f"{problem.get('target')}: "
                + cooccurrence_problem_message(problem)
                for problem in datatype_problems
            )
        )
    active_locations = _active_target_locations(cda, assignments)
    for location in physical_values:
        active_locations.update(
            location[:depth] for depth in range(1, len(location) + 1)
        )
    _activate_fallback_elements(cda, assignments, active_locations)
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
    if previous_document is not None:
        current_set_id = system_values["document_set_identifier"]
        if not isinstance(current_set_id, Mapping):
            raise ValueError("current CDA setId is incomplete")
        _inject_document_replacement(
            roots[0], list(document), previous_document,
            current_set_id, document_version,
        )
    assertion_errors, assertion_warnings = validate_contexts(roots[0], assertion_contexts)
    problems.extend(assertion_warnings)
    if assertion_errors:
        raise ValueError("generated CDA violates ART-DECOR assertions:\n" + "\n".join(assertion_errors))
    ET.indent(roots[0], space="  ")
    return ET.tostring(roots[0], encoding="utf-8", xml_declaration=True), problems
