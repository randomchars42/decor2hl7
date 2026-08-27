"""Compile ART-DECOR CDA templates into a compact executable target model.

The generated ``cda.json`` is the boundary between ART-DECOR and runtime.
ART-DECOR ids remain provenance; runtime assignments use generated target names.

Template ``SPEC`` relationships are compiled as constraint inheritance: the
specialized template overlays the parent constraint tree while still inheriting
constraints that it does not redefine.  ``include`` remains a transparent
constraint group and ``contains`` expands a referenced template below the
containing XML element.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping
import re
import unicodedata
import xml.etree.ElementTree as ET

from ..retrieval.xml import child_text, clean, local, parse_file
from ..assertions import schematron
from ..workspace import write_json

TemplateKey = tuple[str, str]
TEMPLATE_RELATIONS = {"SPEC", "VERSION", "COPY"}


def _key(template: ET.Element) -> TemplateKey:
    return template.get("id") or "", template.get("effectiveDate") or ""


def _ascii_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return value or "Target"


def _segment(value: str) -> str:
    value = value.replace("hl7:", "").replace("cda:", "")
    return _ascii_name(value.lstrip("@"))


def _xml_key(value: str) -> str:
    """Namespace-prefix-insensitive ART-DECOR design name."""
    if value.startswith("@"):
        return "@" + value[1:].split(":", 1)[-1]
    head, sep, tail = value.partition("[")
    return head.split(":", 1)[-1] + (sep + tail if sep else "")


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _maximum(value: str | None) -> int | None | str:
    if value == "*":
        return "*"
    return _int(value)


def _source_key(source: Mapping[str, Any]) -> str:
    template = str(source.get("template_id") or "")
    element_id = source.get("element_id")
    if element_id:
        return f"{template}|ID:{element_id}"
    return f"{template}|PATH:{source.get('path') or ''}"


def collect_templates(
    xml_paths: Iterable[Path],
    fallback_paths: Iterable[Path] = (),
    cutoff: str | None = None,
) -> dict[str, list[ET.Element]]:
    """Collect fetched template definitions; live evidence is never build input."""
    fallback_paths = list(fallback_paths)
    if fallback_paths:
        raise ValueError(
            "fallback template inputs are not allowed; fetch exact build artifacts"
        )
    templates: dict[str, list[ET.Element]] = defaultdict(list)
    seen: set[TemplateKey] = set()

    def ingest(paths: Iterable[Path]) -> None:
        for path in sorted(set(paths)):
            try:
                root, _ = parse_file(path)
            except ET.ParseError:
                continue
            for node in root.iter():
                if local(node.tag) != "template" or not node.get("id"):
                    continue
                if not (node.get("name") or node.get("displayName") or node.get("effectiveDate")):
                    continue
                effective = node.get("effectiveDate") or ""
                key = _key(node)
                if key in seen:
                    continue
                seen.add(key)
                templates[key[0]].append(node)

    ingest(xml_paths)
    for rows in templates.values():
        rows.sort(key=lambda node: node.get("effectiveDate") or "")
    return templates


def select_template(
    templates: dict[str, list[ET.Element]], template_id: str, flexibility: str | None = None
) -> ET.Element | None:
    rows = templates.get(template_id, [])
    if not rows:
        return None
    if flexibility and flexibility != "dynamic":
        exact = [row for row in rows if (row.get("effectiveDate") or "") == flexibility]
        return exact[-1] if exact else None
    return rows[-1]


def _template_relations(template: ET.Element, kinds: set[str] | None = None) -> Iterable[ET.Element]:
    for node in list(template):
        if local(node.tag) != "relationship" or not node.get("template"):
            continue
        if kinds is None or (node.get("type") or "") in kinds:
            yield node


def reachable_templates(
    templates: dict[str, list[ET.Element]],
    start_id: str,
    start_flexibility: str | None = None,
) -> tuple[dict[TemplateKey, ET.Element], list[dict[str, str]]]:
    start = select_template(templates, start_id, start_flexibility)
    if start is None:
        raise ValueError(f"CDA document template {start_id} was not fetched")
    found: dict[TemplateKey, ET.Element] = {}
    missing: dict[tuple[str, str, str], dict[str, str]] = {}
    queue: deque[ET.Element] = deque([start])
    while queue:
        template = queue.popleft()
        key = _key(template)
        if key in found:
            continue
        found[key] = template
        for node in template.iter():
            relation = ""
            reference = ""
            if local(node.tag) == "include" and node.get("ref"):
                relation, reference = "INCLUDE", node.get("ref") or ""
            elif local(node.tag) == "element" and node.get("contains"):
                relation, reference = "CONTAINS", node.get("contains") or ""
            elif (
                local(node.tag) == "relationship"
                and node.get("template")
                and (node.get("type") or "") in TEMPLATE_RELATIONS
            ):
                relation, reference = node.get("type") or "REL", node.get("template") or ""
            if not reference:
                continue
            flexibility = node.get("flexibility") or ""
            target = select_template(templates, reference, flexibility)
            if target is None:
                missing[(relation, reference, flexibility)] = {
                    "relation": relation,
                    "template": reference,
                    "flexibility": flexibility,
                }
            else:
                queue.append(target)
    return found, list(missing.values())


def _constraints(element: ET.Element) -> tuple[list[str], list[tuple[str, str]], dict[str, str], str | None]:
    value_sets: list[str] = []
    codes: list[tuple[str, str]] = []
    fixed: dict[str, str] = {}
    unit: str | None = None
    for node in list(element):
        kind = local(node.tag)
        if kind == "vocabulary":
            if node.get("valueSet"):
                value_sets.append(node.get("valueSet") or "")
            if node.get("code") and node.get("codeSystem"):
                codes.append((node.get("code") or "", node.get("codeSystem") or ""))
        elif kind == "attribute" and node.get("name") and node.get("value"):
            fixed[node.get("name") or ""] = node.get("value") or ""
        elif kind == "property" and node.get("unit"):
            unit = node.get("unit")
    if fixed.get("code") and fixed.get("codeSystem"):
        codes.append((fixed["code"], fixed["codeSystem"]))
    return list(dict.fromkeys(value_sets)), list(dict.fromkeys(codes)), fixed, unit


def _fixed_text(element: ET.Element) -> str | None:
    """Return an ART-DECOR fixed element text constraint, if present."""
    for node in list(element):
        if local(node.tag) != "text":
            continue
        value = "".join(node.itertext()).strip()
        if value:
            return value
    return None


def _description(element: ET.Element) -> str | None:
    for node in list(element):
        if local(node.tag) == "desc":
            value = clean(" ".join("".join(node.itertext()).split()))
            if value:
                return value
    return None



def _raw_targets(reachable: dict[TemplateKey, ET.Element]) -> list[dict[str, Any]]:
    """All addressable constraints used for evidence and provenance.

    Elements without ART-DECOR element ids are intentionally retained.  Their
    template-local path is a perfectly usable generated address.
    """
    rows: list[dict[str, Any]] = []
    for tkey, template in reachable.items():
        template_name = _ascii_name(
            template.get("name") or template.get("displayName") or tkey[0].split(".")[-1]
        )
        display = clean(template.get("displayName") or child_text(template, "name") or template_name)

        def walk(parent: ET.Element, path: tuple[str, ...] = ()) -> None:
            for child in list(parent):
                kind = local(child.tag)
                current = path
                if kind == "element":
                    name = child.get("name") or "element"
                    current = path + (name,)
                    value_sets, codes, fixed, unit = _constraints(child)
                    rows.append({
                        "template_id": tkey[0],
                        "template_effective_date": tkey[1],
                        "template_name": template_name,
                        "template_display_name": display,
                        "kind": "element",
                        "element_id": child.get("id"),
                        "element_name": name,
                        "path": "/".join(current),
                        "datatype": child.get("datatype"),
                        "value_sets": value_sets,
                        "codes": [{"code": c, "code_system": s} for c, s in codes],
                        "fixed": fixed,
                        "fixed_text": _fixed_text(child),
                        "description": _description(child),
                        "conformance": child.get("conformance"),
                        "prohibited": child.get("conformance") == "NP",
                        "unit": unit or fixed.get("unit"),
                        "renderable": False,
                    })
                    # Attributes are writable targets too, even where ART-DECOR
                    # did not assign an element id (e.g. some negation flags).
                    for direct in list(child):
                        if local(direct.tag) != "attribute" or not direct.get("name"):
                            continue
                        aname = "@" + (direct.get("name") or "attribute")
                        rows.append({
                            "template_id": tkey[0],
                            "template_effective_date": tkey[1],
                            "template_name": template_name,
                            "template_display_name": display,
                            "kind": "attribute",
                            "element_id": direct.get("id"),
                            "element_name": aname,
                            "path": "/".join(current + (aname,)),
                            "datatype": direct.get("datatype"),
                            "value_sets": [
                                v.get("valueSet") or "" for v in list(direct)
                                if local(v.tag) == "vocabulary" and v.get("valueSet")
                            ],
                            "codes": [],
                            "fixed": {"value": direct.get("value")} if direct.get("value") else {},
                            "fixed_text": None,
                            "description": None,
                            "conformance": child.get("conformance"),
                            "prohibited": child.get("conformance") == "NP",
                            "unit": None,
                            "renderable": False,
                        })
                walk(child, current)

        walk(template)
    return rows


def _name_targets(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    leaf_bases = [f"{row['template_name']}.{_segment(row['element_name'])}" for row in rows]
    leaf_counts = Counter(leaf_bases)
    candidates: list[str] = []
    for row, base in zip(rows, leaf_bases):
        if leaf_counts[base] == 1:
            candidates.append(base)
        else:
            path = ".".join(_segment(part) for part in row["path"].split("/"))
            candidates.append(f"{row['template_name']}.{path}")
    candidate_counts = Counter(candidates)
    targets: dict[str, dict[str, Any]] = {}
    for row, candidate in zip(rows, candidates):
        if candidate_counts[candidate] > 1:
            # Same constraint name in several reachable revisions.  Effective
            # date is more useful to a human than another OID suffix.
            effective = re.sub(r"[^0-9]", "", str(row.get("template_effective_date") or ""))[:8]
            if effective:
                candidate = f"{candidate}@{effective}"
        if candidate in targets:
            element_tail = str(row.get("element_id") or "target").split(".")[-1]
            candidate = f"{candidate}@{element_tail}"
        serial = dict(row)
        serial["source_key"] = _source_key(row)
        serial["locations"] = []
        targets[candidate] = serial
    return targets


def _source(template: ET.Element, path: str, element_id: str | None) -> dict[str, Any]:
    return {
        "template_id": template.get("id") or "",
        "template_effective_date": template.get("effectiveDate") or "",
        "element_id": element_id,
        "path": path,
    }


def _parse_attribute(attribute: ET.Element, template: ET.Element, path: str) -> dict[str, Any]:
    valuesets = [
        node.get("valueSet") or "" for node in list(attribute)
        if local(node.tag) == "vocabulary" and node.get("valueSet")
    ]
    return {
        "kind": "attribute",
        "name": attribute.get("name") or "attribute",
        "id": attribute.get("id"),
        "datatype": attribute.get("datatype"),
        "value": attribute.get("value"),
        "optional": (
            attribute.get("isOptional") == "true"
            if attribute.get("isOptional") is not None else None
        ),
        "value_sets": valuesets,
        "sources": [_source(template, path, attribute.get("id"))],
        "targets": [],
    }


def _parse_element(element: ET.Element, template: ET.Element, path: tuple[str, ...]) -> dict[str, Any]:
    name = element.get("name") or "hl7:element"
    current = path + (name,)
    current_path = "/".join(current)
    value_sets, codes, fixed, unit = _constraints(element)
    children: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    assertions: list[dict[str, str]] = []
    lets: dict[str, str] = {}
    for child in list(element):
        kind = local(child.tag)
        if kind == "attribute" and child.get("name"):
            attributes.append(_parse_attribute(child, template, current_path + "/@" + (child.get("name") or "attribute")))
        elif kind == "element":
            children.append(_parse_element(child, template, current))
        elif kind == "include" and child.get("ref"):
            children.append(_parse_include(child))
        elif kind == "let" and child.get("name") and child.get("value"):
            lets[child.get("name") or ""] = child.get("value") or ""
        elif kind == "assert" and child.get("test"):
            assertions.append({
                "test": child.get("test") or "",
                "role": child.get("role") or "error",
                "message": "".join(child.itertext()).strip(),
                "template_id": template.get("id") or "",
                "template_effective_date": template.get("effectiveDate") or "",
                "element_id": element.get("id") or "",
                "path": current_path,
            })
    return {
        "kind": "element",
        "name": name,
        "id": element.get("id"),
        "datatype": element.get("datatype"),
        "min": _int(element.get("minimumMultiplicity")),
        "max": _maximum(element.get("maximumMultiplicity")),
        "mandatory": True if element.get("isMandatory") == "true" else None,
        "conformance": element.get("conformance"),
        "fixed": fixed,
        "fixed_text": _fixed_text(element),
        "value_sets": value_sets,
        "codes": [{"code": c, "code_system": s} for c, s in codes],
        "unit": unit,
        "attributes": attributes,
        "children": children,
        "contains": element.get("contains"),
        "contains_flexibility": element.get("flexibility"),
        "origin": _source(template, current_path, element.get("id")),
        "sources": [_source(template, current_path, element.get("id"))],
        "targets": [],
        "asserts": assertions,
        "lets": lets,
    }


def _parse_include(include: ET.Element) -> dict[str, Any]:
    return {
        "kind": "include",
        "ref": include.get("ref") or "",
        "flexibility": include.get("flexibility"),
        "min": _int(include.get("minimumMultiplicity")),
        "max": _maximum(include.get("maximumMultiplicity")),
        "mandatory": True if include.get("isMandatory") == "true" else None,
        "conformance": include.get("conformance"),
        "children": [],
    }


def _direct_template(template: ET.Element) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for child in list(template):
        kind = local(child.tag)
        if kind == "element":
            result.append(_parse_element(child, template, ()))
        elif kind == "include" and child.get("ref"):
            result.append(_parse_include(child))
    return result


def _merge_attribute(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(parent))
    for key in ("id", "datatype", "value", "optional"):
        if child.get(key) is not None:
            result[key] = child.get(key)
    if child.get("value_sets"):
        result["value_sets"] = deepcopy(child.get("value_sets"))
    result["sources"] = _unique_sources(list(parent.get("sources", [])) + list(child.get("sources", [])))
    result["targets"] = []
    return result


def _unique_sources(sources: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source in sources:
        key = (
            str(source.get("template_id") or ""),
            str(source.get("template_effective_date") or ""),
            str(source.get("element_id") or ""),
            str(source.get("path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(source))
    return out


def _sequence_key(node: Mapping[str, Any]) -> tuple[str, str]:
    if node.get("kind") == "element":
        key = _xml_key(str(node.get("name") or ""))
        # Repeated CDA wrappers (component, entry, entryRelationship, ...) are
        # semantically distinguished by the template they contain.  Matching
        # only by sibling position causes constraints from the wrong section or
        # entry to leak across template versions.
        if node.get("contains"):
            key += "|contains:" + str(node.get("contains"))
        return "element", key
    return "include", str(node.get("ref") or "")


def _merge_node(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    if parent.get("kind") != child.get("kind"):
        return deepcopy(dict(child))
    if child.get("kind") == "include":
        result = deepcopy(dict(parent))
        for key in ("ref", "min", "max", "mandatory", "conformance"):
            if child.get(key) is not None:
                result[key] = child.get(key)
        if child.get("ref") is not None:
            result["flexibility"] = child.get("flexibility")
        return result

    result = deepcopy(dict(parent))
    # A specialized constraint wins when it explicitly says something.  The
    # parent supplies only omitted constraints.
    for key in (
        "name", "id", "datatype", "min", "max", "mandatory", "conformance",
        "fixed_text", "unit", "origin",
    ):
        if child.get(key) is not None:
            result[key] = deepcopy(child.get(key))
    if child.get("contains") is not None:
        # A missing flexibility on an explicitly selected containment means
        # dynamic/latest; it must clear a static binding inherited from SPEC.
        result["contains"] = child.get("contains")
        result["contains_flexibility"] = child.get("contains_flexibility")
    result["fixed"] = {**dict(parent.get("fixed", {})), **dict(child.get("fixed", {}))}
    if child.get("value_sets"):
        result["value_sets"] = deepcopy(child.get("value_sets"))
    if child.get("codes"):
        result["codes"] = deepcopy(child.get("codes"))
    merged_asserts: list[dict[str, Any]] = []
    seen_asserts: set[tuple[str, str, str]] = set()
    for assertion in list(parent.get("asserts", [])) + list(child.get("asserts", [])):
        key = (str(assertion.get("test") or ""), str(assertion.get("role") or ""), str(assertion.get("message") or ""))
        if key not in seen_asserts:
            seen_asserts.add(key); merged_asserts.append(deepcopy(dict(assertion)))
    result["asserts"] = merged_asserts
    result["lets"] = {**dict(parent.get("lets", {})), **dict(child.get("lets", {}))}

    parent_attrs = list(parent.get("attributes", []))
    child_attrs = list(child.get("attributes", []))
    by_name: dict[str, list[int]] = defaultdict(list)
    for index, attr in enumerate(parent_attrs):
        by_name[_xml_key("@" + str(attr.get("name") or ""))].append(index)
    attr_counts: Counter[str] = Counter()
    merged_attrs = deepcopy(parent_attrs)
    for attr in child_attrs:
        key = _xml_key("@" + str(attr.get("name") or ""))
        occurrence = attr_counts[key]
        attr_counts[key] += 1
        options = by_name.get(key, [])
        if occurrence < len(options):
            merged_attrs[options[occurrence]] = _merge_attribute(parent_attrs[options[occurrence]], attr)
        else:
            merged_attrs.append(deepcopy(attr))
    result["attributes"] = merged_attrs
    # This merge is used for SPEC refinement.  The specialization selects the
    # child structure at every depth; parent-only prototype choices must not
    # reappear merely because the matching parent element itself was selected.
    result["children"] = _refine_sequence(
        list(parent.get("children", [])), list(child.get("children", []))
    )
    result["sources"] = _unique_sources(list(parent.get("sources", [])) + list(child.get("sources", [])))
    result["targets"] = []
    return result




def _refine_sequence(parent: list[dict[str, Any]], child: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Refine only nodes explicitly selected by a specialization.

    Parent constraints are inherited by matching child nodes, but parent-only
    prototype choices are never materialized.  Reused ART-DECOR element ids
    are stronger structural identity than a sequence key, which is important
    when a specialization replaces ``contains`` while keeping the wrapper id.
    """
    parent_occ: dict[tuple[str, str], list[int]] = defaultdict(list)
    parent_by_id: dict[str, list[int]] = defaultdict(list)
    for index, node in enumerate(parent):
        parent_occ[_sequence_key(node)].append(index)
        if node.get("kind") == "element" and node.get("id"):
            parent_by_id[str(node.get("id"))].append(index)

    used: set[int] = set()
    result: list[dict[str, Any]] = []
    for node in child:
        key = _sequence_key(node)
        # Pair repeated same-name constraints in source order.  Because matched
        # parent indices are removed from consideration, the next unmatched
        # choice is the correct occurrence; applying an additional occurrence
        # offset here would skip every second sibling.
        choices = [index for index in parent_occ.get(key, []) if index not in used]
        match = choices[0] if choices else None
        if match is None and node.get("kind") == "element" and node.get("id"):
            by_id = [index for index in parent_by_id.get(str(node.get("id")), []) if index not in used]
            if by_id:
                match = by_id[0]
        if match is None:
            result.append(deepcopy(node))
        else:
            used.add(match)
            result.append(_merge_node(parent[match], node))
    return result

def _effective_template(
    template: ET.Element,
    templates: dict[str, list[ET.Element]],
    memo: dict[TemplateKey, list[dict[str, Any]]],
    stack: tuple[TemplateKey, ...] = (),
) -> list[dict[str, Any]]:
    key = _key(template)
    if key in memo:
        return deepcopy(memo[key])
    if key in stack:
        return _direct_template(template)
    effective = _direct_template(template)
    for relation in _template_relations(template, {"SPEC"}):
        parent = select_template(
            templates,
            relation.get("template") or "",
            relation.get("flexibility"),
        )
        if parent is None or _key(parent) in stack:
            continue
        parent_nodes = _effective_template(parent, templates, memo, stack + (key,))
        effective = _refine_sequence(parent_nodes, effective)
    memo[key] = deepcopy(effective)
    return effective


def _final_min(value: Any) -> int:
    return int(value) if isinstance(value, int) else 0


def _final_max(value: Any) -> int | None:
    if value == "*":
        return None
    return int(value) if isinstance(value, int) else 1


def _expand_nodes(
    nodes: list[dict[str, Any]],
    templates: dict[str, list[ET.Element]],
    memo: dict[TemplateKey, list[dict[str, Any]]],
    stack: tuple[TemplateKey, ...],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in nodes:
        node = deepcopy(raw)
        if node.get("kind") == "include":
            target = select_template(
                templates, str(node.get("ref") or ""), node.get("flexibility")
            )
            node["min"] = _final_min(node.get("min"))
            node["max"] = _final_max(node.get("max"))
            node["mandatory"] = bool(node.get("mandatory"))
            node["children"] = []
            if target is not None and _key(target) not in stack:
                effective = _effective_template(target, templates, memo)
                node["template_id"] = target.get("id")
                node["template_effective_date"] = target.get("effectiveDate")
                node["children"] = _expand_nodes(
                    effective, templates, memo, stack + (_key(target),)
                )
            out.append(node)
            continue

        node["min"] = _final_min(node.get("min"))
        node["max"] = _final_max(node.get("max"))
        node["mandatory"] = bool(node.get("mandatory"))
        node["children"] = _expand_nodes(
            list(node.get("children", [])), templates, memo, stack
        )
        reference = node.get("contains")
        if reference:
            target = select_template(
                templates,
                str(reference),
                node.get("contains_flexibility"),
            )
            if target is not None and _key(target) not in stack:
                effective = _effective_template(target, templates, memo)
                node["children"].append({
                    "kind": "template",
                    "ref": target.get("id"),
                    "template_id": target.get("id"),
                    "template_effective_date": target.get("effectiveDate"),
                    "min": 0,
                    "max": 1,
                    "mandatory": False,
                    "children": _expand_nodes(
                        effective, templates, memo, stack + (_key(target),)
                    ),
                })
        out.append(node)
    return out


def _target_lookup(targets: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = defaultdict(list)
    for name, target in targets.items():
        lookup[str(target.get("source_key") or "")].append(name)
        # Element-id source resolution is intentionally version tolerant.
        if target.get("element_id"):
            lookup[f"{target.get('template_id')}|ID:{target.get('element_id')}"] .append(name)
    return lookup


def _annotate_targets(
    document: list[dict[str, Any]], targets: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    lookup = _target_lookup(targets)
    source_index: dict[str, list[str]] = defaultdict(list)

    def annotate(
        nodes: list[dict[str, Any]],
        location: tuple[int, ...] = (),
        repeat_ancestors: tuple[tuple[int, ...], ...] = (),
    ) -> None:
        for index, node in enumerate(nodes):
            here = location + (index,)
            maximum = node.get("max")
            repeats_here = maximum is None or (isinstance(maximum, int) and maximum > 1)
            node_repeat_ancestors = repeat_ancestors + ((here,) if repeats_here else ())
            node_repeatable = bool(node_repeat_ancestors)
            if node.get("kind") == "element":
                names: list[str] = []
                own_name: str | None = None
                origin = node.get("origin") or {}
                origin_key = _source_key(origin) if origin else ""
                for source in node.get("sources", []):
                    key = _source_key(source)
                    for name in lookup.get(key, []):
                        if name not in names:
                            names.append(name)
                        if key == origin_key and own_name is None:
                            own_name = name
                if own_name is None and names:
                    own_name = names[0]
                node["targets"] = names
                node["target"] = own_name
                if own_name and own_name in targets:
                    target = targets[own_name]
                    prohibited = str(node.get("conformance") or "").upper() == "NP"
                    target["prohibited"] = prohibited
                    target["conformance"] = node.get("conformance")
                    target["locations"].append(".".join(map(str, here)))
                    # For an element target, repetition of the target element
                    # itself is its cardinality, not an additional enclosing
                    # occurrence dimension. Only repeating *ancestors* must
                    # correspond to dataset repeat_chain levels. Children and
                    # attributes inherit this node as an ancestor below.
                    target["repeatable"] = bool(node_repeatable)
                    target["repeat_ancestors"] = [".".join(map(str, item)) for item in repeat_ancestors]
                    # Fixed element text is a template constraint, not a writable
                    # application slot.  Keep the target for provenance/evidence
                    # but do not allow mappings or site values to override it.
                    target["renderable"] = not prohibited and node.get("fixed_text") is None
                    # The concrete node carries effective SPEC constraints.
                    for key in ("datatype", "value_sets", "codes", "fixed", "fixed_text", "unit"):
                        target[key] = deepcopy(node.get(key))
                if own_name:
                    for source in node.get("sources", []):
                        key = _source_key(source)
                        if own_name not in source_index[key]:
                            source_index[key].append(own_name)
                        if source.get("element_id"):
                            tolerant = f"{source.get('template_id')}|ID:{source.get('element_id')}"
                            if own_name not in source_index[tolerant]:
                                source_index[tolerant].append(own_name)

                for attr_index, attr in enumerate(node.get("attributes", [])):
                    attr_names: list[str] = []
                    attr_origin = (attr.get("sources") or [{}])[-1]
                    attr_origin_key = _source_key(attr_origin)
                    own_attr: str | None = None
                    for source in attr.get("sources", []):
                        key = _source_key(source)
                        for name in lookup.get(key, []):
                            if name not in attr_names:
                                attr_names.append(name)
                            if key == attr_origin_key and own_attr is None:
                                own_attr = name
                    if own_attr is None and attr_names:
                        own_attr = attr_names[0]
                    attr["targets"] = attr_names
                    attr["target"] = own_attr
                    if own_attr and own_attr in targets:
                        target = targets[own_attr]
                        prohibited = str(node.get("conformance") or "").upper() == "NP"
                        target["prohibited"] = prohibited
                        target["conformance"] = node.get("conformance")
                        target["locations"].append(".".join(map(str, here + (100000 + attr_index,))))
                        target["repeatable"] = bool(node_repeatable)
                        target["repeat_ancestors"] = [".".join(map(str, item)) for item in node_repeat_ancestors]
                        fixed_value = attr.get("value")
                        target["renderable"] = not prohibited and fixed_value is None
                        target["datatype"] = attr.get("datatype")
                        target["value_sets"] = deepcopy(attr.get("value_sets", []))
                        target["fixed"] = {"value": fixed_value} if fixed_value is not None else {}
                    if own_attr:
                        for source in attr.get("sources", []):
                            key = _source_key(source)
                            if own_attr not in source_index[key]:
                                source_index[key].append(own_attr)
                            if source.get("element_id"):
                                tolerant = f"{source.get('template_id')}|ID:{source.get('element_id')}"
                                if own_attr not in source_index[tolerant]:
                                    source_index[tolerant].append(own_attr)
            annotate(list(node.get("children", [])), here, node_repeat_ancestors)

    annotate(document)
    return dict(source_index)



def compile_cda(
    xml_paths: Iterable[Path],
    model: dict[str, Any],
    fallback_paths: Iterable[Path] = (),
    cutoff: str | None = None,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    template_id = str(model.get("meta", {}).get("template_id") or "")
    if not template_id:
        raise ValueError("model has no representing CDA template")
    template_effective = str(model.get("meta", {}).get("template_effective_date") or "") or None
    templates = collect_templates(xml_paths, fallback_paths, cutoff)
    reachable, missing = reachable_templates(templates, template_id, template_effective)
    if strict and missing:
        formatted = ", ".join(
            f"{row.get('relation')} {row.get('template')} @ {row.get('flexibility') or 'dynamic'}"
            for row in missing[:10]
        )
        raise ValueError(f"CDA template closure is incomplete: {formatted}")
    targets = _name_targets(_raw_targets(reachable))
    selected = select_template(templates, template_id, template_effective)
    if selected is None:
        raise ValueError(f"document template {template_id} missing")
    memo: dict[TemplateKey, list[dict[str, Any]]] = {}
    effective = _effective_template(selected, templates, memo)
    document = _expand_nodes(effective, templates, memo, (_key(selected),))
    # A document-level template's root is necessarily present even where the
    # design omits explicit multiplicity on the root ClinicalDocument element.
    for node in document:
        if node.get("kind") == "element":
            node["min"] = max(1, int(node.get("min") or 0))
            node["mandatory"] = True
            break
    source_index = _annotate_targets(document, targets)
    assertions: list[dict[str, Any]] = []
    def collect_assertions(nodes: list[Mapping[str, Any]], prefix: tuple[int, ...] = ()) -> None:
        for index, node in enumerate(nodes):
            here = prefix + (index,)
            for assertion in node.get("asserts", []):
                assertions.append({**dict(assertion), "location": ".".join(map(str, here)), "lets": deepcopy(dict(node.get("lets", {})))})
            collect_assertions(list(node.get("children", [])), here)
    collect_assertions(document)
    # A generated target is directly writable only when it resolves to exactly
    # one physical node in the effective document.  Keep ambiguous targets in
    # the registry for evidence/provenance, but make them non-renderable so no
    # caller can accidentally emit the value twice.
    for target in targets.values():
        if len(target.get("locations", [])) != 1:
            target["renderable"] = False
    def constraint_counts(nodes: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
        elements = 0
        attributes = 0
        for node in nodes:
            if node.get("kind") == "attribute":
                attributes += 1
            else:
                elements += 1
            nested_elements, nested_attributes = constraint_counts(
                list(node.get("children", []))
            )
            elements += nested_elements
            attributes += nested_attributes + len(node.get("attributes", []))
        return elements, attributes
    element_count, attribute_count = constraint_counts(document)
    return {
        "version": 2,
        "format": "cda",
        "document_template": {
            "id": template_id,
            "effective_date": selected.get("effectiveDate"),
            "name": selected.get("name"),
            "display_name": selected.get("displayName"),
        },
        "targets": targets,
        "source_index": source_index,
        "assertions": assertions,
        "document": document,
        "unresolved_templates": missing,
        "stats": {
            "reachable_templates": len(reachable),
            "targets": len(targets),
            "renderable_targets": sum(bool(target.get("renderable")) for target in targets.values()),
            "assertions": len(assertions),
            "elements": element_count,
            "attributes": attribute_count,
        },
    }


def write_cda(
    xml_paths: Iterable[Path],
    model_dir: Path,
    model: dict[str, Any],
    fallback_paths: Iterable[Path] = (),
    cutoff: str | None = None,
) -> dict[str, Any]:
    cda = compile_cda(xml_paths, model, fallback_paths, cutoff)
    write_json(model_dir / "cda.json", cda)
    (model_dir / "cda-assertions.sch").write_text(schematron(cda), encoding="utf-8")
    return cda


def compile_cda_model(
    templates: Iterable[Path], model: dict[str, Any],
) -> dict[str, Any]:
    """Compile the exact build-template closure into the CDA target model."""
    return compile_cda(templates, model)


def write_cda_model(
    templates: Iterable[Path], model_dir: Path, model: dict[str, Any],
) -> dict[str, Any]:
    """Write ``cda.json`` and its effective Schematron."""
    return write_cda(templates, model_dir, model)
