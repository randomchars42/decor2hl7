"""Compile the selected transaction into a small, target-neutral data model."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET
import re

from ..retrieval.xml import child_text, clean, local, parse_file
from ..workspace import write_json

NULLFLAVOR_CS = "2.16.840.1.113883.5.1008"
TYPE_NAMES = {
    "string": "text",
    "text": "text",
    "identifier": "identifier",
    "datetime": "datetime",
    "date": "date",
    "boolean": "boolean",
    "code": "code",
    "quantity": "quantity",
    "decimal": "decimal",
    "integer": "integer",
    "count": "integer",
    "ordinal": "ordinal",
    "duration": "duration",
}


def _number(raw: str | None) -> int | float | None:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _dominant_code_system(entry: Mapping[str, Any]) -> str | None:
    counts = Counter(
        item["code_system"]
        for code, item in entry.get("codes", {}).items()
        if item.get("code_system") and item.get("code_system") != NULLFLAVOR_CS
        and code not in entry.get("exceptions", [])
    )
    if counts:
        return counts.most_common(1)[0][0]
    for system in entry.get("code_systems", []):
        if system != NULLFLAVOR_CS:
            return str(system)
    return None


def _value_set_key(oid: str, effective: str | None) -> str:
    return f"{oid}@{effective or ''}"


def _parse_value_sets(root: ET.Element) -> dict[str, dict[str, Any]]:
    """Parse value-set revisions without merging different effective dates."""
    out: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if local(node.tag) != "valueSet" or not node.get("id"):
            continue
        oid = node.get("id") or ""
        effective = node.get("effectiveDate") or ""
        key = _value_set_key(oid, effective)
        entry = out.setdefault(key, {
            "id": oid, "effective_date": effective,
            "name": clean(node.get("displayName") or node.get("name")),
            "code_systems": [], "codes": {}, "labels": {}, "exceptions": [],
            "includes": [], "unresolved_includes": [],
        })
        for child in node:
            if local(child.tag) == "sourceCodeSystem" and child.get("id"):
                system = child.get("id") or ""
                if system not in entry["code_systems"]:
                    entry["code_systems"].append(system)
        for child in node.iter():
            kind = local(child.tag)
            if kind == "include":
                include = {
                    "ref": child.get("ref") or "",
                    "effective_date": child.get("effectiveDate") or child.get("flexibility") or "",
                    "code": child.get("code") or "",
                    "code_system": child.get("codeSystem") or "",
                    "op": child.get("op") or "",
                }
                if any(include.values()) and include not in entry["includes"]:
                    entry["includes"].append(include)
                continue
            if kind not in {"concept", "exception"}:
                continue
            code, system = child.get("code"), child.get("codeSystem")
            if not code or not system:
                continue
            label = child_text(child, "name") or clean(child.get("displayName"))
            entry["codes"][code] = {
                "label": label, "code_system": system,
                "display_name": child.get("displayName") or label,
            }
            if label:
                entry["labels"].setdefault(label, code)
            if kind == "exception":
                entry["exceptions"].append(code)
    for entry in out.values():
        entry["code_system"] = _dominant_code_system(entry)
    return out


def _merge_value_set_entry(current: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    """Merge two definitions of the same value-set revision only."""
    merged = dict(current)
    merged["codes"] = {**dict(current.get("codes", {})), **dict(entry.get("codes", {}))}
    merged["labels"] = {**dict(current.get("labels", {})), **dict(entry.get("labels", {}))}
    merged["exceptions"] = list(dict.fromkeys(
        list(current.get("exceptions", [])) + list(entry.get("exceptions", []))
    ))
    merged["code_systems"] = list(dict.fromkeys(
        list(current.get("code_systems", [])) + list(entry.get("code_systems", []))
    ))
    includes = [dict(item) for item in current.get("includes", [])]
    for include in entry.get("includes", []):
        if include not in includes:
            includes.append(dict(include))
    merged["includes"] = includes
    for name in ("name", "code_system"):
        if entry.get(name):
            merged[name] = entry.get(name)
    return merged


def _parse_code_systems(root: ET.Element) -> dict[str, dict[str, Any]]:
    """Parse local DECOR code systems used to expand composed value sets."""
    out: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if local(node.tag) != "codeSystem" or not node.get("id"):
            continue
        oid = node.get("id") or ""
        effective = node.get("effectiveDate") or ""
        key = _value_set_key(oid, effective)
        entry = out.setdefault(key, {
            "id": oid, "effective_date": effective, "codes": {},
        })
        for concept in node.iter():
            if local(concept.tag) != "codedConcept" or not concept.get("code"):
                continue
            code = concept.get("code") or ""
            preferred = ""
            fallback = ""
            for designation in concept:
                if local(designation.tag) != "designation" or not designation.get("displayName"):
                    continue
                label = designation.get("displayName") or ""
                if not fallback:
                    fallback = label
                if designation.get("language") == "de-DE" and designation.get("type") == "preferred":
                    preferred = label
                    break
                if not preferred and designation.get("type") == "preferred":
                    preferred = label
            parents = [
                child.get("code") or "" for child in concept
                if local(child.tag) == "parent" and child.get("code")
            ]
            entry["codes"][code] = {
                "label": preferred or fallback or code,
                "display_name": preferred or fallback or code,
                "parents": list(dict.fromkeys(parents)),
            }
    return out


def _resolve_revision(
    oid: str, effective: str, revisions: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any]:
    exact = revisions.get(_value_set_key(oid, effective)) if effective else None
    if exact is not None:
        return exact
    rows = [value for value in revisions.values() if str(value.get("id") or "") == oid]
    if not rows:
        return {}
    if effective:
        return {}
    rows.sort(key=lambda value: str(value.get("effective_date") or ""))
    return rows[-1]


def _descendants(code_system: Mapping[str, Any], anchor: str, include_anchor: bool) -> set[str]:
    codes = code_system.get("codes", {})
    selected: set[str] = {anchor} if include_anchor and anchor in codes else set()
    frontier = {anchor}
    while frontier:
        next_frontier: set[str] = set()
        for code, item in codes.items():
            if code in selected:
                continue
            if any(parent in frontier for parent in item.get("parents", [])):
                selected.add(str(code)); next_frontier.add(str(code))
        frontier = next_frontier
    if not include_anchor:
        selected.discard(anchor)
    return selected


def _expand_value_sets(
    value_sets: dict[str, dict[str, Any]], code_systems: Mapping[str, Mapping[str, Any]]
) -> None:
    """Expand local value-set includes without consulting live terminology.

    Supported DECOR compositions are value-set ``include/@ref`` and local
    code-system includes using direct code, ``is-a`` or ``descendent-of``.
    Unresolvable external/composed inclusions stay explicit in the model.
    """
    visiting: set[str] = set()
    done: set[str] = set()

    def add_code(entry: dict[str, Any], code: str, system: str, item: Mapping[str, Any]) -> None:
        label = str(item.get("label") or item.get("display_name") or code)
        entry["codes"].setdefault(code, {
            "label": label, "code_system": system,
            "display_name": item.get("display_name") or label,
        })
        if label:
            entry["labels"].setdefault(label, code)
        if system and system not in entry["code_systems"]:
            entry["code_systems"].append(system)

    def expand(key: str) -> None:
        if key in done or key in visiting or key not in value_sets:
            return
        visiting.add(key)
        entry = value_sets[key]
        unresolved: list[dict[str, str]] = []
        for include in entry.get("includes", []):
            ref = str(include.get("ref") or "")
            if ref:
                referred = _resolve_revision(
                    ref, str(include.get("effective_date") or ""), value_sets
                )
                if not referred:
                    unresolved.append(dict(include)); continue
                referred_key = _value_set_key(
                    str(referred.get("id") or ""), str(referred.get("effective_date") or "")
                )
                expand(referred_key)
                for code, item in referred.get("codes", {}).items():
                    add_code(entry, str(code), str(item.get("code_system") or ""), item)
                continue

            code = str(include.get("code") or "")
            system = str(include.get("code_system") or "")
            if not code or not system:
                unresolved.append(dict(include)); continue
            code_system = _resolve_revision(
                system, str(include.get("effective_date") or ""), code_systems
            )
            if not code_system:
                unresolved.append(dict(include)); continue
            op = str(include.get("op") or "").casefold()
            if op in {"descendent-of", "descendant-of"}:
                selected = _descendants(code_system, code, False)
            elif op in {"is-a", "isa"}:
                selected = _descendants(code_system, code, True)
            elif op in {"", "equal", "="}:
                selected = {code} if code in code_system.get("codes", {}) else set()
            else:
                unresolved.append(dict(include)); continue
            if not selected:
                unresolved.append(dict(include)); continue
            for selected_code in selected:
                item = code_system.get("codes", {}).get(selected_code, {})
                add_code(entry, selected_code, system, item)
        entry["unresolved_includes"] = unresolved
        entry["code_system"] = _dominant_code_system(entry)
        visiting.remove(key); done.add(key)

    for key in list(value_sets):
        expand(key)

def _value_domain(domain: ET.Element, node: dict[str, Any]) -> None:
    for child in domain:
        kind = local(child.tag)
        if kind == "property":
            for source, target in (
                ("unit", "unit"),
                ("minInclude", "min_value"),
                ("maxInclude", "max_value"),
                ("minLength", "min_length"),
                ("maxLength", "max_length"),
            ):
                if child.get(source) is not None:
                    node[target] = child.get(source) if target == "unit" else _number(child.get(source))
            if child.get("timeStampPrecision"):
                node["precision"] = child.get("timeStampPrecision")
        elif kind == "conceptList":
            options: list[str] = []
            details: dict[str, dict[str, Any]] = {}
            for item in child:
                if local(item.tag) not in {"concept", "exception"}:
                    continue
                label = child_text(item, "name")
                if not label:
                    continue
                options.append(label)
                synonyms = [
                    "".join(part.itertext()).strip()
                    for part in list(item) if local(part.tag) == "synonym"
                ]
                info: dict[str, Any] = {"synonyms": [value for value in synonyms if value]}
                ordinal = None
                for text in info["synonyms"] + [label]:
                    match = re.search(r"(?:^|\b)(?:rankin\s*)?([0-9]+)(?:\s*(?:punkt|score))?(?:\b|$)", text, re.I)
                    if match:
                        ordinal = int(match.group(1)); break
                if ordinal is not None:
                    info["ordinal"] = ordinal
                details[label] = info
            node["options"] = options
            if details:
                node["option_details"] = details


def _association_scope(
    source_concept: str | None,
    selected_concept: str | None,
    identity_refs: Iterable[str] = (),
) -> str:
    """Classify a direct association without discarding its provenance."""
    source = str(source_concept or "")
    selected = str(selected_concept or "")
    if source and source == selected:
        return "selected-concept"
    # ART-DECOR keeps the predecessor conceptId on associations copied through
    # inheritance. Require the explicit identity edge: suffix similarity alone
    # also occurs for option concepts and is not semantic evidence.
    if source and source in {str(value) for value in identity_refs if value}:
        return "lineage-concept"
    return "related-concept"


def _concept_node(concept: ET.Element, path: str, parent: str | None) -> dict[str, Any]:
    minimum = concept.get("minimumMultiplicity") or "0"
    maximum = concept.get("maximumMultiplicity") or "1"
    result: dict[str, Any] = {
        "path": path,
        "parent": parent,
        "name": child_text(concept, "name"),
        "description": child_text(concept, "desc"),
        "comment": child_text(concept, "comment"),
        "concept": concept.get("id"),
        "short_name": concept.get("shortName"),
        "kind": concept.get("type") or "item",
        "min": int(minimum) if minimum.isdigit() else 0,
        "max": None if maximum == "*" else (int(maximum) if maximum.isdigit() else 1),
        "repeating": maximum == "*",
        "required": concept.get("isMandatory") == "true" or (minimum.isdigit() and int(minimum) >= 1),
        "type": None,
        "value_sets": [],
        "value_set_refs": [],
        "codes": [],
        "contains": None,
        "external_refs": [],
        "identity_refs": [],
        "terminology_associations": [],
    }
    for child in concept:
        kind = local(child.tag)
        if kind == "implementation":
            result["implementation"] = clean(child.get("markdown"))
        if kind == "valueDomain":
            raw_type = child.get("type") or ""
            result["type"] = TYPE_NAMES.get(raw_type, raw_type or None)
            _value_domain(child, result)
        elif kind == "valueSet" and child.get("id"):
            oid = child.get("id") or ""
            result["value_sets"].append(oid)
            result["value_set_refs"].append({
                "id": oid,
                "effective_date": child.get("effectiveDate") or child.get("flexibility") or "",
            })
        elif kind == "contains" and child.get("ref"):
            result["contains"] = child.get("ref")
        elif kind == "inherit" and child.get("ref"):
            result["external_refs"].append(child.get("ref"))
            result["identity_refs"].append(child.get("ref"))
            if child.get("originalId"):
                result["external_refs"].append(child.get("originalId"))
                result["identity_refs"].append(child.get("originalId"))
        elif kind == "relationship" and child.get("ref"):
            result["external_refs"].append(child.get("ref"))
            if (child.get("type") or "") in {"SPEC", "INHERIT", "ORIGINAL", "EQUIV", "COPY", "VERSION"}:
                result["identity_refs"].append(child.get("ref"))
        elif kind == "terminologyAssociation":
            association = {
                "source_concept_id": child.get("conceptId") or concept.get("id"),
                "selected_concept_id": concept.get("id"),
                "code": child.get("code"),
                "code_system": child.get("codeSystem"),
                "display_name": child.get("displayName"),
                "value_set": child.get("valueSet"),
                "effective_date": child.get("effectiveDate"),
                "flexibility": child.get("flexibility"),
                "equivalence": child.get("equivalence"),
                "form": "analysis",
                "direct": True,
                "scope": "unclassified",
            }
            result["terminology_associations"].append(association)
            if child.get("valueSet"):
                oid = child.get("valueSet") or ""
                result["value_sets"].append(oid)
                result["value_set_refs"].append({
                    "id": oid,
                    "effective_date": child.get("flexibility") or "",
                })
    for association in result["terminology_associations"]:
        scope = _association_scope(
            association.get("source_concept_id"),
            concept.get("id"),
            result["identity_refs"],
        )
        association["scope"] = scope
        if association.get("code") and scope in {"selected-concept", "lineage-concept"}:
            result["codes"].append({
                "code": association.get("code"),
                "code_system": association.get("code_system"),
                "display_name": association.get("display_name"),
                "equivalence": association.get("equivalence"),
                "source_concept_id": association.get("source_concept_id"),
                "scope": scope,
                "applies_to_selected_concept": True,
                "form": "analysis",
            })
    result["external_refs"] = list(dict.fromkeys(result["external_refs"]))
    result["identity_refs"] = list(dict.fromkeys(result["identity_refs"]))
    result["value_sets"] = list(dict.fromkeys(result["value_sets"]))
    seen_refs: set[tuple[str, str]] = set()
    refs: list[dict[str, str]] = []
    for ref in result["value_set_refs"]:
        key = (str(ref.get("id") or ""), str(ref.get("effective_date") or ""))
        if key not in seen_refs:
            seen_refs.add(key)
            refs.append({"id": key[0], "effective_date": key[1]})
    result["value_set_refs"] = refs
    return result


def _source_selections(root: ET.Element) -> dict[str, dict[str, Any]]:
    """Parse the authoritative transaction selection and its direct evidence."""
    selections: dict[str, dict[str, Any]] = {}
    for concept in root.iter():
        if local(concept.tag) != "concept" or not concept.get("ref"):
            continue
        reference = concept.get("ref") or ""
        row = selections.setdefault(reference, {
            "minimum": concept.get("minimumMultiplicity"),
            "maximum": concept.get("maximumMultiplicity"),
            "conformance": concept.get("conformance"),
            "associations": [],
        })
        for child in concept:
            if local(child.tag) != "terminologyAssociation":
                continue
            row["associations"].append({
                "source_concept_id": child.get("conceptId") or reference,
                "selected_concept_id": reference,
                "code": child.get("code"),
                "code_system": child.get("codeSystem"),
                "display_name": child.get("displayName"),
                "value_set": child.get("valueSet"),
                "effective_date": child.get("effectiveDate"),
                "flexibility": child.get("flexibility"),
                "equivalence": child.get("equivalence"),
                "form": "source",
                "direct": True,
            "scope": _association_scope(child.get("conceptId"), reference),
            })
    return selections


def _apply_source_selections(
    nodes: dict[str, dict[str, Any]], selections: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    by_concept = {
        str(node.get("concept") or ""): node
        for node in nodes.values() if node.get("concept")
    }
    unresolved: list[str] = []
    for concept_id, selection in selections.items():
        node = by_concept.get(concept_id)
        if node is None:
            unresolved.append(concept_id)
            continue
        minimum = str(selection.get("minimum") or "")
        maximum = str(selection.get("maximum") or "")
        if minimum.isdigit():
            node["min"] = int(minimum)
            node["required"] = int(minimum) >= 1
        if maximum:
            node["max"] = None if maximum == "*" else (
                int(maximum) if maximum.isdigit() else node.get("max")
            )
            node["repeating"] = maximum == "*"
        associations = list(selection.get("associations", []))
        for association in associations:
            applied = dict(association)
            applied["scope"] = _association_scope(
                applied.get("source_concept_id"),
                node.get("concept"),
                node.get("identity_refs", []),
            )
            if applied not in node["terminology_associations"]:
                node["terminology_associations"].append(applied)
            value_set = str(applied.get("value_set") or "")
            if value_set:
                node["value_sets"].append(value_set)
                node["value_set_refs"].append({
                    "id": value_set,
                    "effective_date": str(applied.get("flexibility") or ""),
                })
            code = str(applied.get("code") or "")
            scope = str(applied.get("scope") or "related-concept")
            if code and scope in {"selected-concept", "lineage-concept"}:
                candidate = {
                    "code": code,
                    "code_system": applied.get("code_system"),
                    "display_name": applied.get("display_name"),
                    "equivalence": applied.get("equivalence"),
                    "source_concept_id": applied.get("source_concept_id"),
                    "scope": scope,
                    "applies_to_selected_concept": True,
                    "form": "source",
                }
                if candidate not in node["codes"]:
                    node["codes"].append(candidate)
        node["value_sets"] = list(dict.fromkeys(node["value_sets"]))
        seen_refs: set[tuple[str, str]] = set()
        unique_refs: list[dict[str, str]] = []
        for ref in node["value_set_refs"]:
            key = (
                str(ref.get("id") or ""),
                str(ref.get("effective_date") or ""),
            )
            if key in seen_refs:
                continue
            seen_refs.add(key)
            unique_refs.append({"id": key[0], "effective_date": key[1]})
        node["value_set_refs"] = unique_refs
    return unresolved


def _parse_nodes(root: ET.Element) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}

    def visit(parent: ET.Element, prefix: list[str]) -> None:
        for child in parent:
            if local(child.tag) != "concept" or not child.get("shortName"):
                continue
            parts = prefix + [child.get("shortName") or ""]
            path = ".".join(parts)
            nodes[path] = _concept_node(child, path, ".".join(prefix) or None)
            visit(child, parts)

    visit(root, [])
    return nodes


def _graft(base: dict[str, dict[str, Any]], extra: dict[str, dict[str, Any]]) -> int:
    by_concept = {node.get("concept"): path for path, node in extra.items() if node.get("concept")}
    additions: dict[str, dict[str, Any]] = {}
    for host_path, host in list(base.items()):
        reference = host.get("contains")
        if not reference:
            continue
        candidates = [reference] + list(host.get("external_refs") or [])
        source = next((by_concept[item] for item in candidates if item in by_concept), None)
        if not source:
            continue
        prefix = source + "."
        for old_path, old in extra.items():
            if not old_path.startswith(prefix):
                continue
            suffix = old_path[len(prefix):]
            new_path = host_path + "." + suffix
            if new_path in base or new_path in additions:
                continue
            copied = dict(old)
            copied["path"] = new_path
            parent = old.get("parent")
            copied["parent"] = host_path if parent == source else host_path + "." + str(parent)[len(prefix):]
            copied["merged_from"] = old.get("concept")
            additions[new_path] = copied
        if additions:
            host["contains_merged"] = reference
    base.update(additions)
    return len(additions)


def _enrich_identity(
    base: dict[str, dict[str, Any]], extra_sets: Iterable[dict[str, dict[str, Any]]]
) -> int:
    """Fill omitted value-domain metadata through identity lineage transitively.

    Cardinality/requiredness are deliberately *not* inherited: those belong to
    the dataset context in which the concept is used.  ADAPT/DRIV/GEN are not
    present in ``identity_refs`` and therefore never participate.
    """
    catalog: dict[str, dict[str, Any]] = {}
    for node in base.values():
        concept = str(node.get("concept") or "")
        if concept:
            catalog[concept] = node
    for nodes in extra_sets:
        for node in nodes.values():
            concept = str(node.get("concept") or "")
            if concept and concept not in catalog:
                catalog[concept] = node

    scalar_keys = ("type", "unit", "precision", "min_value", "max_value", "min_length", "max_length")
    list_keys = (
        "value_sets", "value_set_refs", "codes", "options",
        "terminology_associations",
    )
    changed = 0
    done: set[str] = set()

    def enrich(node: dict[str, Any], visiting: set[str]) -> bool:
        nonlocal changed
        cid = str(node.get("concept") or "")
        if cid and cid in done:
            return False
        if cid and cid in visiting:
            return False
        branch = set(visiting)
        if cid:
            branch.add(cid)
        copied_any = False
        inherited_from: list[str] = list(node.get("identity_inherited_from", []))
        for raw_ref in node.get("identity_refs", []):
            ref = str(raw_ref or "")
            source = catalog.get(ref)
            if source is None or source is node:
                continue
            enrich(source, branch)
            copied = False
            for key in scalar_keys:
                if node.get(key) in (None, "") and source.get(key) not in (None, ""):
                    node[key] = source.get(key); copied = True
            for key in list_keys:
                if not node.get(key) and source.get(key):
                    node[key] = [
                        dict(item) if isinstance(item, Mapping) else item
                        for item in source.get(key, [])
                    ]; copied = True
            if not node.get("option_details") and source.get("option_details"):
                node["option_details"] = {
                    str(key): dict(value) if isinstance(value, Mapping) else value
                    for key, value in source.get("option_details", {}).items()
                }; copied = True
            if copied:
                copied_any = True
                if ref not in inherited_from:
                    inherited_from.append(ref)
        if inherited_from:
            node["identity_inherited_from"] = inherited_from
        if cid:
            done.add(cid)
        if copied_any:
            changed += 1
        return copied_any

    for node in catalog.values():
        enrich(node, set())
    return changed

def _repeat_chain_for(path: str, nodes: Mapping[str, Mapping[str, Any]]) -> list[str]:
    chain: list[str] = []
    current = nodes[path].get("parent")
    while current:
        node = nodes[str(current)]
        if node.get("repeating"):
            chain.append(str(current))
        current = node.get("parent")
    chain.reverse()
    return chain


def _repeat_for(path: str, nodes: Mapping[str, Mapping[str, Any]]) -> str | None:
    chain = _repeat_chain_for(path, nodes)
    return chain[-1] if chain else None


def _resolve_value_set(oid: str, effective: str, value_sets: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    exact = value_sets.get(_value_set_key(oid, effective)) if effective else None
    if exact is not None:
        return exact
    rows = [value for value in value_sets.values() if str(value.get("id") or "") == oid]
    if not rows or effective:
        return {}
    rows.sort(key=lambda value: str(value.get("effective_date") or ""))
    return rows[-1]


def _formal_values(
    field: Mapping[str, Any], value_sets: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    refs = list(field.get("value_set_refs", [])) or [
        {"id": oid, "effective_date": ""} for oid in field.get("value_sets", [])
    ]
    for ref in refs:
        oid = str(ref.get("id") or ""); effective = str(ref.get("effective_date") or "")
        value_set = _resolve_value_set(oid, effective, value_sets)
        for code, item in value_set.get("codes", {}).items():
            label = str(item.get("label") or item.get("display_name") or code)
            key = label if label not in values or values[label].get("code") == code else str(code)
            values[key] = {
                "code": code, "code_system": item.get("code_system"),
                "display_name": item.get("display_name") or label, "value_set": oid,
                "value_set_effective_date": value_set.get("effective_date"),
            }
    return values


def _formal_domain_status(
    field: Mapping[str, Any], value_sets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    refs = list(field.get("value_set_refs", [])) or [
        {"id": oid, "effective_date": ""} for oid in field.get("value_sets", [])
    ]
    missing: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for ref in refs:
        oid = str(ref.get("id") or "")
        effective = str(ref.get("effective_date") or "")
        value_set = _resolve_value_set(oid, effective, value_sets)
        if not value_set or not value_set.get("codes"):
            missing.append({"id": oid, "effective_date": effective})
        if value_set:
            unresolved.extend(
                dict(include) for include in value_set.get("unresolved_includes", [])
            )
    return {
        "bound": bool(refs),
        "complete": bool(refs) and not missing and not unresolved,
        "missing_value_sets": missing,
        "unresolved_includes": unresolved,
    }


def _logical_values(field: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    option_details = (
        field.get("option_details", {})
        if isinstance(field.get("option_details"), Mapping) else {}
    )
    for label in field.get("options", []):
        info = {"display_name": label}
        detail = option_details.get(str(label), {}) if isinstance(option_details, Mapping) else {}
        if isinstance(detail, Mapping) and detail.get("synonyms"):
            info["synonyms"] = list(detail.get("synonyms", []))
        if isinstance(detail, Mapping) and detail.get("ordinal") is not None:
            info["ordinal"] = detail.get("ordinal")
        values.setdefault(str(label), info)
    return values


def compile_model(
    transaction: Path,
    resource_paths: Iterable[Path] = (),
    terminology_paths: Iterable[Path] = (),
    transaction_source: Path | None = None,
) -> dict[str, Any]:
    if not transaction.exists():
        raise FileNotFoundError(f"missing {transaction}")
    root, repairs = parse_file(transaction)
    nodes = _parse_nodes(root)
    selected_concepts: dict[str, dict[str, Any]] = {}
    source_repairs: list[str] = []
    unresolved_selections: list[str] = []
    if transaction_source is not None:
        source_root, source_repairs = parse_file(transaction_source)
        source_id = source_root.get("id") or ""
        source_effective = source_root.get("effectiveDate") or ""
        analysis_id = root.get("transactionId") or root.get("id") or ""
        analysis_effective = (
            root.get("transactionEffectiveDate") or root.get("effectiveDate") or ""
        )
        if source_id and analysis_id and source_id != analysis_id:
            raise ValueError(
                f"transaction source id {source_id} does not match analysis id {analysis_id}"
            )
        if source_effective and analysis_effective and source_effective != analysis_effective:
            raise ValueError(
                "transaction source effectiveDate "
                f"{source_effective} does not match analysis {analysis_effective}"
            )
        selected_concepts = _source_selections(source_root)
        unresolved_selections = _apply_source_selections(nodes, selected_concepts)
        if unresolved_selections:
            raise ValueError(
                "transaction analysis does not resolve selected concept(s): "
                + ", ".join(unresolved_selections[:10])
            )
    value_sets = _parse_value_sets(root)
    code_systems = _parse_code_systems(root)

    extras: list[tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]] = []
    for path in sorted(set(resource_paths)):
        try:
            extra_root, _ = parse_file(path)
        except ET.ParseError:
            continue
        extra_nodes = _parse_nodes(extra_root)
        extra_sets = _parse_value_sets(extra_root)
        code_systems.update(_parse_code_systems(extra_root))
        extras.append((extra_nodes, extra_sets))
        for set_key, entry in extra_sets.items():
            current = value_sets.get(set_key)
            if current is None:
                value_sets[set_key] = entry
                continue
            # A transaction often contains only a valueSet reference/stub.
            # Standalone fetched definitions must enrich that stub rather than
            # being discarded by setdefault(). Different revisions have
            # different keys and are never merged here.
            value_sets[set_key] = _merge_value_set_entry(current, entry)

    for path in sorted(set(terminology_paths)):
        try:
            terminology_root, _ = parse_file(path)
        except (ET.ParseError, OSError):
            continue
        for key, entry in _parse_value_sets(terminology_root).items():
            # Transaction/downloaded terminology remains authoritative. The
            # pinned project may enrich an exact stub/composition of the same
            # revision, but never merges across effective dates.
            current = value_sets.get(key)
            value_sets[key] = entry if current is None else _merge_value_set_entry(current, entry)
        for key, entry in _parse_code_systems(terminology_root).items():
            code_systems.setdefault(key, entry)

    _expand_value_sets(value_sets, code_systems)

    _enrich_identity(nodes, [extra_nodes for extra_nodes, _ in extras])

    changed = True
    while changed:
        changed = False
        for extra_nodes, _ in extras:
            if _graft(nodes, extra_nodes):
                changed = True

    groups: dict[str, dict[str, Any]] = {}
    fields: dict[str, dict[str, Any]] = {}
    for path, node in nodes.items():
        common = {
            "name": node.get("name"),
            "description": node.get("description"),
            "comment": node.get("comment"),
            "implementation": node.get("implementation"),
            "short_name": node.get("short_name"),
            "concept": node.get("concept"),
            "parent": node.get("parent"),
            "min": node.get("min"),
            "max": node.get("max"),
            "required": bool(node.get("required")),
            "repeat": _repeat_for(path, nodes),
            "repeat_chain": _repeat_chain_for(path, nodes),
        }
        if node.get("kind") == "group":
            groups[path] = {**common, "repeating": bool(node.get("repeating")), "contains": node.get("contains")}
            continue
        field = {
            **common,
            "type": node.get("type") or "text",
            "value_sets": node.get("value_sets", []),
            "value_set_refs": node.get("value_set_refs", []),
            "codes": node.get("codes", []),
            "terminology_associations": node.get("terminology_associations", []),
        }
        for name in ("unit", "precision", "min_value", "max_value", "min_length", "max_length"):
            if name in node:
                field[name] = node[name]
        formal_values = _formal_values(node, value_sets)
        formal_status = _formal_domain_status(node, value_sets)
        logical_values = _logical_values(node)
        field["logical_domain"] = {
            "options": logical_values,
            "source": "dataset-analysis",
        }
        field["formal_terminology"] = {
            "value_sets": list(node.get("value_set_refs", [])),
            "members": formal_values,
            "source": "transaction-binding",
            "complete": formal_status["complete"],
            "missing_value_sets": formal_status["missing_value_sets"],
            "unresolved_includes": formal_status["unresolved_includes"],
        }
        # Runtime/configuration defaults use the formal transaction binding
        # whenever it is available. Dataset logical options remain reviewable
        # evidence and are not silently promoted to formal codes.
        accepted_values = formal_values if formal_status["bound"] else logical_values
        if accepted_values:
            field["accepted_values"] = accepted_values
        fields[path] = field

    meta = {
        "dataset_id": root.get("id"),
        "transaction_id": root.get("transactionId"),
        "transaction_effective_date": root.get("transactionEffectiveDate"),
        "version_label": root.get("transactionVersionLabel") or root.get("versionLabel"),
        "template_id": root.get("templateId"),
        "template_effective_date": root.get("templateEffectiveDate"),
        "name": child_text(root, "name"),
        "namespace_repairs": repairs,
        "source_namespace_repairs": source_repairs,
        "selected_concepts": len(selected_concepts) if transaction_source else None,
        "contained_concepts": max(0, len(nodes) - len(selected_concepts)) if transaction_source else None,
    }
    return {
        "version": 2,
        "meta": meta,
        "order": list(nodes),
        "groups": groups,
        "fields": fields,
        "value_sets": value_sets,
    }


def write_model(
    transaction: Path,
    resource_paths: Iterable[Path],
    model_dir: Path,
    terminology_paths: Iterable[Path] = (),
    transaction_source: Path | None = None,
) -> dict[str, Any]:
    model = compile_model(
        transaction, resource_paths, terminology_paths,
        transaction_source=transaction_source,
    )
    write_json(model_dir / "model.json", model)
    return model


def compile_transaction(
    source: Path,
    analysis: Path,
    resources: Iterable[Path] = (),
    terminology: Iterable[Path] = (),
) -> dict[str, Any]:
    """Compile the authoritative transaction source/analysis pair."""
    return compile_model(
        analysis, resources, terminology, transaction_source=source,
    )


def write_transaction_model(
    source: Path,
    analysis: Path,
    resources: Iterable[Path],
    terminology: Iterable[Path],
    model_dir: Path,
) -> dict[str, Any]:
    """Write ``model.json`` from the authoritative source/analysis pair."""
    return write_model(
        analysis, resources, model_dir, terminology,
        transaction_source=source,
    )
