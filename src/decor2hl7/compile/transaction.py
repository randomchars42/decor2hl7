"""Compile the selected transaction into a small, target-neutral data model."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, cast
import xml.etree.ElementTree as ET
import re

from ..retrieval.xml import child_text, clean, local, parse_file
from ..workspace import write_json

NULLFLAVOR_CS = "2.16.840.1.113883.5.1008"
OBJECT_RELATIONSHIP_MEANINGS = {
    "REPL": "replacement",
    "SPEC": "specialization",
    "GEN": "generalization",
    "COPY": "design-copy",
    "ADAPT": "adaptation",
    "EQUIV": "design-equivalence",
    "VERSION": "version",
    "BACKWD": "backward-compatible",
    "DRIV": "model-derived",
}
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

LEADING_OPTION_RANK = re.compile(
    r"^\s*([0-9]+)(?![0-9-])(?:\s*(?:punkte?|score))?\b",
    re.I,
)
EXPLICIT_OPTION_RANK = re.compile(
    r"\b(?:rank(?:in)?|rang|score)\s*[:=#-]?\s*([0-9]+)\b"
    r"|\b([0-9]+)\s*(?:punkte?|score)\b",
    re.I,
)


def _number(raw: str | None) -> int | float | None:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _option_ordinal(label: str, synonyms: Iterable[str]) -> int | None:
    """Return rank evidence without treating unqualified synonyms as ranks."""
    leading = LEADING_OPTION_RANK.match(label)
    if leading:
        return int(leading.group(1))
    for text in [label, *synonyms]:
        explicit = EXPLICIT_OPTION_RANK.search(text)
        if explicit:
            return int(next(
                group for group in explicit.groups() if group is not None
            ))
    return None


def _dominant_code_system(entry: Mapping[str, Any]) -> str | None:
    counts: Counter[str] = Counter(
        cast(str, item["code_system"])
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
                source_system = child.get("id") or ""
                if source_system not in entry["code_systems"]:
                    entry["code_systems"].append(source_system)
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
            if str(child.get("type") or "").upper() == "A":
                continue
            code = child.get("code")
            code_system = child.get("codeSystem")
            if not code or not code_system:
                continue
            label = child_text(child, "name") or clean(child.get("displayName"))
            entry["codes"][code] = {
                "label": label, "code_system": code_system,
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
                    if target == "unit":
                        unit = str(child.get(source) or "").strip()
                        units = node.setdefault("units", [])
                        if unit and unit not in units:
                            units.append(unit)
                        if len(units) == 1:
                            node["unit"] = units[0]
                        else:
                            # Several property rows describe an admitted unit
                            # set.  Treating the final row as one fixed unit
                            # silently rejects every other published member.
                            node.pop("unit", None)
                    else:
                        node[target] = _number(child.get(source))
            if child.get("timeStampPrecision"):
                node["precision"] = child.get("timeStampPrecision")
        elif kind == "conceptList":
            options: list[str] = []
            details: dict[str, dict[str, Any]] = {}
            source_members = [
                item for item in child
                if local(item.tag) in {"concept", "exception"}
            ]
            members = [
                item for item in source_members
                if str(item.get("type") or "").upper() != "A"
            ]
            abstract_members = [
                {
                    "id": str(item.get("id") or ""),
                    "label": child_text(item, "name"),
                    "level": str(item.get("level") or ""),
                }
                for item in source_members
                if str(item.get("type") or "").upper() == "A"
            ]
            references = [
                {
                    "kind": local(item.tag),
                    "ref": item.get("ref") or "",
                    "code": item.get("code") or "",
                    "code_system": item.get("codeSystem") or "",
                    "effective_date": (
                        item.get("effectiveDate")
                        or item.get("flexibility")
                        or ""
                    ),
                }
                for item in child
                if local(item.tag) in {"include", "valueSet"}
            ]
            unrecognized = sorted({
                local(item.tag) for item in child
                if local(item.tag) not in {
                    "concept", "exception", "include", "valueSet",
                }
            })
            # A conceptList is owned by its dataset concept.  Preserve that
            # identity even when it intentionally has no members: an empty
            # owned list is an explicit open coded domain, not a missing
            # standalone ValueSet artifact.
            coded_domain = {
                "kind": "inline_concept_list",
                "id": child.get("id") or "",
                "status": (
                    "enumerated" if members else
                    "referenced" if references else
                    "unresolved" if unrecognized else
                    "unconstrained"
                ),
                "member_count": len(members),
                "references": references,
                "unrecognized_children": unrecognized,
            }
            if abstract_members:
                coded_domain.update({
                    "source_member_count": len(source_members),
                    "abstract_member_count": len(abstract_members),
                    "abstract_members": abstract_members,
                })
            node["coded_domain"] = coded_domain
            for item in child:
                if local(item.tag) not in {"concept", "exception"}:
                    continue
                # ART-DECOR type A is a hierarchy heading, not an instance
                # code that a user or mapping may select.
                if str(item.get("type") or "").upper() == "A":
                    continue
                label = child_text(item, "name")
                if not label:
                    continue
                options.append(label)
                synonyms = [
                    "".join(part.itertext()).strip()
                    for part in list(item) if local(part.tag) == "synonym"
                ]
                info: dict[str, Any] = {
                    "synonyms": [value for value in synonyms if value],
                }
                if item.get("id"):
                    # ``terminologyAssociation/@conceptId`` identifies the
                    # concrete concept-list member, not its mutable label.
                    # Retain that owner identity so formal codification can be
                    # joined without a label or suffix heuristic.
                    info["concept_id"] = str(item.get("id"))
                if (
                    local(item.tag) == "exception"
                    or str(item.get("exception") or "").casefold() == "true"
                ):
                    info["exception"] = True
                # A bare number is ordinal evidence only at the start of the
                # option's label. Unqualified synonyms are commonly codes or
                # taxonomy numbers. An explicit rank/score phrase remains
                # admissible in either the label or a synonym.
                ordinal = _option_ordinal(label, info["synonyms"])
                if ordinal is not None:
                    info["ordinal"] = ordinal
                details[label] = info
            # A score transform must be injective.  Some ordinary coded lists
            # start their labels with numbers (triage bands are a common
            # example); duplicate extracted values prove that those numbers do
            # not form an ordinal scale for this option list.
            ordinals = [
                info["ordinal"] for info in details.values()
                if info.get("ordinal") is not None
            ]
            if len(ordinals) != len(set(ordinals)):
                for info in details.values():
                    info.pop("ordinal", None)
            node["options"] = options
            if details:
                node["option_details"] = details


def _association_scope(
    source_concept: str | None,
    selected_concept: str | None,
    original_concepts: Iterable[str] = (),
) -> str:
    """Classify a direct association without discarding its provenance."""
    source = str(source_concept or "")
    selected = str(selected_concept or "")
    if source and source == selected:
        return "selected-concept"
    # ART-DECOR keeps the original conceptId on associations copied through
    # formal inherit/contains compilation. Require that explicit original:
    # suffix similarity also occurs for option concepts and is not evidence.
    if source and source in {
        str(value) for value in original_concepts if value
    }:
        return "original-concept"
    return "related-concept"


def _reference_metadata(node: ET.Element, *, contains: bool) -> dict[str, str]:
    """Preserve the owner-defined inherit/contains reference attributes."""
    result = {
        "ref": node.get("ref") or "",
        (
            "flexibility" if contains else "effective_date"
        ): (
            node.get("flexibility") if contains
            else node.get("effectiveDate")
        ) or "",
        "prefix": node.get("prefix") or "",
        "dataset_id": node.get("datasetId") or "",
        "dataset_effective_date": node.get("datasetEffectiveDate") or "",
        "original_id": node.get("originalId") or "",
        "original_effective_date": node.get("originalEffectiveDate") or "",
        "original_prefix": node.get("originalPrefix") or "",
        # ``i*`` is the terminology used by the ART-DECOR compiled response
        # for the resolved referenced concept.
        "i_type": node.get("iType") or "",
        "i_effective_date": node.get("iEffectiveDate") or "",
        "i_status_code": node.get("iStatusCode") or "",
    }
    return {key: value for key, value in result.items() if value}


def _relationship_metadata(node: ET.Element) -> dict[str, str]:
    """Retain an ART-DECOR relationship as provenance, never as inheritance."""
    relationship_type = node.get("type") or "REL"
    result = {
        "type": relationship_type,
        "owner_meaning": OBJECT_RELATIONSHIP_MEANINGS.get(
            relationship_type, "relationship"
        ),
        # DECOR.xsd ObjectRelationships: implicit, unchecked reader hints.
        "execution": "hint-only",
        "ref": node.get("ref") or "",
        "flexibility": node.get("flexibility") or "",
        "prefix": node.get("prefix") or "",
        "dataset_id": node.get("datasetId") or "",
        "dataset_effective_date": node.get("datasetEffectiveDate") or "",
        "i_type": node.get("iType") or "",
        "i_effective_date": node.get("iEffectiveDate") or "",
        "i_status_code": node.get("iStatusCode") or "",
    }
    return {key: value for key, value in result.items() if value}


def _formal_original_ids(node: Mapping[str, Any]) -> list[str]:
    """Return only ids from formal inherit/contains original resolution."""
    values: list[str] = []
    for kind in ("inherit", "contains"):
        reference = node.get(kind)
        if not isinstance(reference, Mapping):
            continue
        values.extend((
            str(reference.get("ref") or ""),
            str(reference.get("original_id") or ""),
        ))
    return list(dict.fromkeys(value for value in values if value))


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
        "inherit": None,
        "relationships": [],
        "terminology_associations": [],
        "effective_date": concept.get("effectiveDate") or "",
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
            result["contains"] = _reference_metadata(child, contains=True)
        elif kind == "inherit" and child.get("ref"):
            result["inherit"] = _reference_metadata(child, contains=False)
        elif kind == "relationship" and child.get("ref"):
            result["relationships"].append(_relationship_metadata(child))
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
            _formal_original_ids(result),
        )
        association["scope"] = scope
        if association.get("code") and scope in {"selected-concept", "original-concept"}:
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
                _formal_original_ids(node),
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
            if code and scope in {"selected-concept", "original-concept"}:
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


def _concept_catalog(
    node_sets: Iterable[dict[str, dict[str, Any]]],
) -> dict[str, list[tuple[dict[str, dict[str, Any]], str, dict[str, Any]]]]:
    catalog: dict[
        str, list[tuple[dict[str, dict[str, Any]], str, dict[str, Any]]]
    ] = {}
    for nodes in node_sets:
        for path, node in nodes.items():
            concept = str(node.get("concept") or "")
            if concept:
                catalog.setdefault(concept, []).append((nodes, path, node))
    return catalog


def _select_concept(
    catalog: Mapping[
        str, list[tuple[dict[str, dict[str, Any]], str, dict[str, Any]]]
    ],
    concept_id: str,
    effective_date: str = "",
) -> tuple[dict[str, dict[str, Any]], str, dict[str, Any]] | None:
    rows = list(catalog.get(concept_id, []))
    if effective_date:
        rows = [
            row for row in rows
            if str(row[2].get("effective_date") or "") == effective_date
        ]
    elif len(rows) > 1:
        newest = max(str(row[2].get("effective_date") or "") for row in rows)
        rows = [
            row for row in rows
            if str(row[2].get("effective_date") or "") == newest
        ]
    # An ambiguous concept revision must not be chosen by input order.
    return rows[0] if len(rows) == 1 else None


def _compiled_terminal_original_spec_locator(
    host: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Recognize ART-DECOR's compiled terminal-original SPEC locator.

    ``getFullConcept`` emits this relationship only after it has followed a
    formal inherit/contains chain. Matching the complete contains context keeps
    an ordinary SPEC relationship from becoming a structural reference.
    """
    contains = host.get("contains")
    if not isinstance(contains, Mapping):
        return None
    original_effective = str(contains.get("i_effective_date") or "")
    dataset_id = str(contains.get("dataset_id") or "")
    if not original_effective or not dataset_id:
        return None
    matches: set[tuple[str, str]] = set()
    for relationship in host.get("relationships", []):
        if not isinstance(relationship, Mapping):
            continue
        if str(relationship.get("type") or "") != "SPEC":
            continue
        reference = str(relationship.get("ref") or "")
        flexibility = str(relationship.get("flexibility") or "")
        if not reference or flexibility != original_effective:
            continue
        if str(relationship.get("dataset_id") or "") != dataset_id:
            continue
        for key in ("dataset_effective_date", "prefix", "i_type"):
            expected = str(contains.get(key) or "")
            actual = str(relationship.get(key) or "")
            if expected and actual != expected:
                break
        else:
            related_effective = str(
                relationship.get("i_effective_date") or ""
            )
            if related_effective and related_effective != original_effective:
                continue
            matches.add((reference, flexibility))
    return next(iter(matches)) if len(matches) == 1 else None


def _dereference_contains_descendants(
    base: dict[str, dict[str, Any]],
    extra_sets: Iterable[dict[str, dict[str, Any]]],
) -> int:
    """Attach only a formally contained concept's stored descendants."""
    extras = list(extra_sets)
    catalog = _concept_catalog(extras)
    additions: dict[str, dict[str, Any]] = {}
    for host_path, host in list(base.items()):
        contains = host.get("contains")
        if not isinstance(contains, Mapping):
            continue
        literal = (
            str(contains.get("ref") or ""),
            str(contains.get("flexibility") or ""),
            "contains",
        )
        original = (
            str(contains.get("original_id") or ""),
            str(contains.get("original_effective_date") or ""),
            "originalId",
        )
        terminal = _compiled_terminal_original_spec_locator(host)
        candidates = [literal]
        if original[0]:
            candidates.append(original)
        if terminal is not None:
            candidates.append((*terminal, "terminal-original-SPEC"))
        selected = next(
            (
                (*resolved, resolution)
                for concept_id, effective, resolution in candidates
                if concept_id
                for resolved in [_select_concept(catalog, concept_id, effective)]
                if resolved is not None
            ),
            None,
        )
        if selected is None:
            continue
        source_nodes, source, source_node, resolution = selected
        prefix = source + "."
        host_added = 0
        for old_path, old in source_nodes.items():
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
            host_added += 1
        if host_added:
            host["contains_resolved_to"] = source_node.get("concept")
            host["contains_resolution"] = resolution
    base.update(additions)
    return len(additions)


def _apply_terminal_original_semantics(
    base: dict[str, dict[str, Any]], extra_sets: Iterable[dict[str, dict[str, Any]]]
) -> int:
    """Apply semantic properties from the one formal terminal original.

    This mirrors ART-DECOR ``getFullConcept``: the transaction/use concept
    retains identity, short name, and usage cardinality, while the terminal
    original supplies name, description, datatype/value domain, and semantic
    associations. ART-DECOR relationships (SPEC, ADAPT, EQUIV, COPY, VERSION,
    and others) never participate.
    """
    extras = list(extra_sets)
    catalog = _concept_catalog([base, *extras])

    scalar_keys = (
        "name", "description", "type", "unit", "precision", "min_value",
        "max_value", "min_length", "max_length",
    )
    list_keys = (
        "value_sets", "value_set_refs", "codes", "options", "units",
        "terminology_associations",
    )
    changed = 0
    done: set[tuple[str, str]] = set()

    def terminal_original(
        node: dict[str, Any], visiting: set[tuple[str, str]],
    ) -> dict[str, Any] | None:
        identity = (
            str(node.get("concept") or ""),
            str(node.get("effective_date") or ""),
        )
        if identity in visiting:
            return None
        reference = node.get("inherit") or node.get("contains")
        if not isinstance(reference, Mapping):
            return None
        branch = set(visiting)
        branch.add(identity)
        ref = str(reference.get("ref") or "")
        effective = str(
            reference.get("effective_date")
            or reference.get("flexibility")
            or ""
        )
        selected = _select_concept(catalog, ref, effective) if ref else None
        if selected is not None:
            direct = selected[2]
            return terminal_original(direct, branch) or direct
        original_id = str(reference.get("original_id") or "")
        original_effective = str(
            reference.get("original_effective_date") or ""
        )
        selected = (
            _select_concept(catalog, original_id, original_effective)
            if original_id else None
        )
        return selected[2] if selected is not None else None

    def enrich(node: dict[str, Any]) -> bool:
        nonlocal changed
        identity = (
            str(node.get("concept") or ""),
            str(node.get("effective_date") or ""),
        )
        if identity in done:
            return False
        source = terminal_original(node, set())
        copied_any = False
        if source is not None and source is not node:
            copied = False
            for key in scalar_keys:
                if (
                    source.get(key) not in (None, "")
                    and node.get(key) != source.get(key)
                ):
                    node[key] = source.get(key); copied = True
            for key in list_keys:
                if node.get(key) != source.get(key):
                    node[key] = [
                        dict(item) if isinstance(item, Mapping) else item
                        for item in source.get(key, [])
                    ]; copied = True
            if node.get("option_details") != source.get("option_details"):
                node["option_details"] = {
                    str(key): dict(value) if isinstance(value, Mapping) else value
                    for key, value in source.get("option_details", {}).items()
                }; copied = True
            node["original_concept"] = source.get("concept")
            copied_any = copied
        done.add(identity)
        if copied_any:
            changed += 1
        return copied_any

    for rows in catalog.values():
        for _, _, node in rows:
            enrich(node)
    return changed


def _apply_owner_dataset_composition_rules(
    selected_nodes: dict[str, dict[str, Any]],
    referenced_node_sets: Iterable[dict[str, dict[str, Any]]],
) -> dict[str, int]:
    """Apply the owner mechanisms in their explicit compilation order.

    1. Resolve the terminal original through formal ``inherit``/``contains``
       only and copy its semantic properties.
    2. Dereference the current stored descendants named by ``contains`` until
       the selected model is closed.
    3. Leave every ObjectRelationships record (ADAPT, SPEC, EQUIV, COPY,
       VERSION, and the other enum values) as an unchecked reader hint.

    Referenced node sets are parsed before this function, so their own formal
    origins are resolved in step 1 before any descendants are copied in step 2.
    """
    referenced = list(referenced_node_sets)
    enriched = _apply_terminal_original_semantics(selected_nodes, referenced)
    contained = 0
    rounds = 0
    while True:
        added = _dereference_contains_descendants(selected_nodes, referenced)
        if not added:
            break
        contained += added
        rounds += 1
    return {
        "terminal_original_concepts": enriched,
        "contains_descendants": contained,
        "contains_rounds": rounds,
    }

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
    # ``dynamic`` is a request policy, not an effective-date identity.  The
    # compiled terminology index contains only frozen revisions, so resolve a
    # dynamic request exactly like an undated request and retain the newest
    # available frozen revision.
    frozen = "" if effective.strip().casefold() == "dynamic" else effective
    exact = value_sets.get(_value_set_key(oid, frozen)) if frozen else None
    if exact is not None:
        return exact
    rows = [value for value in value_sets.values() if str(value.get("id") or "") == oid]
    if not rows or frozen:
        return {}
    rows.sort(key=lambda value: str(value.get("effective_date") or ""))
    return rows[-1]


def _formal_value_set_refs(
    field: Mapping[str, Any], value_sets: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Return the effective bindings used by formal members and status.

    ART-DECOR analysis can expose both an embedded dated definition and a
    dynamic terminology association for the same OID.  Those are two views of
    one binding, not permission to union revisions.  The dynamic association
    therefore wins for that OID and is frozen to the newest compiled revision;
    explicit-only bindings remain exact and never fall back.
    """
    raw = list(field.get("value_set_refs", [])) or [
        {"id": oid, "effective_date": ""} for oid in field.get("value_sets", [])
    ]
    dynamic_oids = {
        str(ref.get("id") or "")
        for ref in raw
        if str(ref.get("effective_date") or "").strip().casefold() == "dynamic"
    }
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ref in raw:
        oid = str(ref.get("id") or "")
        effective = str(ref.get("effective_date") or "")
        if oid in dynamic_oids and effective.strip().casefold() != "dynamic":
            continue
        value_set = _resolve_value_set(oid, effective, value_sets)
        frozen = str(value_set.get("effective_date") or effective)
        key = (oid, frozen)
        if key in seen:
            continue
        seen.add(key)
        result.append({"id": oid, "effective_date": frozen})
    return result


def _formal_values(
    field: Mapping[str, Any], value_sets: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    refs = _formal_value_set_refs(field, value_sets)
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
    refs = _formal_value_set_refs(field, value_sets)
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
    coded_domain = field.get("coded_domain", {})
    inline_status = (
        str(coded_domain.get("status") or "")
        if isinstance(coded_domain, Mapping) else ""
    )
    if refs:
        status = "unresolved" if missing or unresolved else "bound"
        complete = not missing and not unresolved
    elif inline_status == "unconstrained":
        status = "unconstrained"
        complete = True
    elif inline_status == "enumerated":
        status = "logical"
        complete = False
    elif inline_status in {"referenced", "unresolved"}:
        status = "unresolved"
        complete = False
    else:
        status = "unbound"
        complete = False
    return {
        "bound": bool(refs),
        "status": status,
        "complete": complete,
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
        if isinstance(detail, Mapping):
            for key in ("concept_id", "exception"):
                if detail.get(key) is not None:
                    info[key] = detail.get(key)
            if detail.get("synonyms"):
                info["synonyms"] = list(detail.get("synonyms", []))
            if detail.get("ordinal") is not None:
                info["ordinal"] = detail.get("ordinal")
        values.setdefault(str(label), info)
    return values


def _associate_logical_options_with_formal_members(
    field: Mapping[str, Any],
    logical_values: dict[str, dict[str, Any]],
    formal_values: Mapping[str, Mapping[str, Any]],
    formal_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Join owner-defined concept-list members to their formal codifications.

    The ART-DECOR join key is the exact concept identity carried by
    ``conceptList/concept/@id`` and ``terminologyAssociation/@conceptId``.
    Labels, identifier suffixes, relationship neighbours, and code-only
    matches are deliberately insufficient.  The associated code/system pair
    must also be one exact member of the selected complete formal binding.
    """
    if not formal_status.get("bound") or not formal_status.get("complete"):
        return []

    formal_by_pair: dict[tuple[str, str], set[str]] = {}
    for canonical, raw_info in formal_values.items():
        info = raw_info if isinstance(raw_info, Mapping) else {}
        code = str(info.get("code") or "")
        system = str(info.get("code_system") or "")
        if code and system:
            formal_by_pair.setdefault((code, system), set()).add(str(canonical))

    associations_by_concept: dict[str, list[Mapping[str, Any]]] = {}
    for association in field.get("terminology_associations", []):
        if not isinstance(association, Mapping):
            continue
        concept_id = str(association.get("source_concept_id") or "")
        if concept_id:
            associations_by_concept.setdefault(concept_id, []).append(association)

    diagnostics: list[dict[str, Any]] = []
    for label, option in logical_values.items():
        concept_id = str(option.get("concept_id") or "")
        if not concept_id:
            continue
        rows = associations_by_concept.get(concept_id, [])
        declared_pairs = {
            (
                str(row.get("code") or ""),
                str(row.get("code_system") or ""),
            )
            for row in rows
            if row.get("code") or row.get("code_system")
        }
        admitted = {
            canonical
            for pair in declared_pairs
            if pair[0] and pair[1]
            for canonical in formal_by_pair.get(pair, set())
        }
        associated_members = [
            {
                "canonical": canonical,
                "concept_id": concept_id,
                "code": str(formal_values[canonical].get("code") or ""),
                "code_system": str(
                    formal_values[canonical].get("code_system") or ""
                ),
                **(
                    {
                        "display_name": str(
                            formal_values[canonical].get("display_name")
                        )
                    }
                    if formal_values[canonical].get("display_name") else {}
                ),
                **(
                    {
                        "value_set": str(
                            formal_values[canonical].get("value_set")
                        )
                    }
                    if formal_values[canonical].get("value_set") else {}
                ),
                **(
                    {
                        "value_set_effective_date": str(
                            formal_values[canonical].get(
                                "value_set_effective_date"
                            )
                        )
                    }
                    if formal_values[canonical].get(
                        "value_set_effective_date"
                    ) else {}
                ),
            }
            for canonical in sorted(admitted)
        ]
        if associated_members:
            # Preserve every exact admitted association. A source-side alias
            # requires one member, while a later CDA target binding may
            # legitimately disambiguate several members by ValueSet.
            option["terminology_associations"] = associated_members
        if len(admitted) == 1:
            option["terminology_association"] = dict(associated_members[0])
            continue
        if declared_pairs:
            diagnostics.append({
                "kind": (
                    "ambiguous-formal-member"
                    if len(admitted) > 1 else "outside-formal-domain"
                ),
                "label": label,
                "concept_id": concept_id,
                "declared": [
                    {"code": code, "code_system": system}
                    for code, system in sorted(declared_pairs)
                ],
                "admitted_canonical_values": sorted(admitted),
            })
    return diagnostics


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
    for resource_path in sorted(set(resource_paths)):
        try:
            extra_root, _ = parse_file(resource_path)
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

    for terminology_path in sorted(set(terminology_paths)):
        try:
            terminology_root, _ = parse_file(terminology_path)
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

    extra_node_sets = [extra_nodes for extra_nodes, _ in extras]
    dataset_composition = _apply_owner_dataset_composition_rules(
        nodes, extra_node_sets
    )

    groups: dict[str, dict[str, Any]] = {}
    fields: dict[str, dict[str, Any]] = {}
    for model_path, node in nodes.items():
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
            "repeat": _repeat_for(model_path, nodes),
            "repeat_chain": _repeat_chain_for(model_path, nodes),
            "formal_origin": {
                key: dict(value) if isinstance(value, Mapping) else value
                for key, value in {
                    "inherit": node.get("inherit"),
                    "contains": node.get("contains"),
                    "terminal_original": node.get("original_concept"),
                }.items()
                if value
            },
            "relationships": [
                dict(relationship)
                for relationship in node.get("relationships", [])
            ],
        }
        if node.get("kind") == "group":
            contains = node.get("contains")
            groups[model_path] = {
                **common,
                "repeating": bool(node.get("repeating")),
                "contains": (
                    contains.get("ref")
                    if isinstance(contains, Mapping) else None
                ),
                **(
                    {
                        "contains_resolved_to": node["contains_resolved_to"],
                        "contains_resolution": node["contains_resolution"],
                    }
                    if node.get("contains_resolved_to") else {}
                ),
            }
            continue
        field = {
            **common,
            "type": node.get("type") or "text",
            "value_sets": node.get("value_sets", []),
            "value_set_refs": node.get("value_set_refs", []),
            "codes": node.get("codes", []),
            "terminology_associations": node.get("terminology_associations", []),
        }
        if node.get("coded_domain"):
            field["coded_domain"] = node["coded_domain"]
        for name in (
            "unit", "units", "precision", "min_value", "max_value",
            "min_length", "max_length",
        ):
            if name in node:
                field[name] = node[name]
        formal_values = _formal_values(node, value_sets)
        formal_status = _formal_domain_status(node, value_sets)
        logical_values = _logical_values(node)
        option_association_diagnostics = (
            _associate_logical_options_with_formal_members(
                node, logical_values, formal_values, formal_status,
            )
        )
        field["logical_domain"] = {
            "options": logical_values,
            "source": "dataset-analysis",
            **(
                {"terminology_association_diagnostics": option_association_diagnostics}
                if option_association_diagnostics else {}
            ),
        }
        field["formal_terminology"] = {
            "value_sets": _formal_value_set_refs(node, value_sets),
            "members": formal_values,
            "source": "transaction-binding",
            "status": formal_status["status"],
            "bound": formal_status["bound"],
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
        fields[model_path] = field

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
        "dataset_rule_pipeline": [
            {
                "rule": "transaction-concept-selection",
                "effect": "usage-cardinality-and-direct-associations",
                "selected_concepts": len(selected_concepts),
            },
            {
                "rule": "inherit-or-contains-terminal-original",
                "effect": "semantic-properties",
                "resolved_concepts": dataset_composition[
                    "terminal_original_concepts"
                ],
            },
            {
                "rule": "contains-current-stored-descendants",
                "effect": "structure-dereference",
                "added_concepts": dataset_composition["contains_descendants"],
                "rounds": dataset_composition["contains_rounds"],
            },
            {
                "rule": "object-relationships",
                "effect": "hint-only-provenance",
                "executable": False,
            },
            {
                "rule": "formal-terminology-binding",
                "effect": "accepted-values-and-domain-status",
            },
        ],
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
