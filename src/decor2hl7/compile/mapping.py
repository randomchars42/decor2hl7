"""Generate terse mapping proposals and detailed human-readable reports."""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..retrieval.xml import child_text, local, parse_file
from .mapping_audit import build_mapping_audit
from .mapping_reports import render_mapping_analysis
from .mapping_decisions import association_request
from ..contracts import MappingAudit
from ..text import normalize_match_text as _norm
from ..i18n import localized
from ..workspace import write_json
from ..domain import accepted_values, logical_values
from ..cda.semantics import (
    base_datatype, direct_compatibility, payload_match, required_value_set_ids,
    target_type_match, transformed_compatibility, type_match,
)
from ..transforms import cda_target_name, mapping_rules
from ..cda.datatypes import classify_datatype
from ..cda.model import ValueRepresentationKind
from ..cda.terminology import NULL_FLAVORS_WITH_ORIGINAL_TEXT
from ..bindings import non_null_requirement_satisfied
from ..cooccurrence import (
    constrained_datatype_components, cooccurrence_problem_message,
    unavoidable_targets_problems,
)
from .structural import (
    boolean_example_discriminator_rules as _boolean_example_discriminator_rules,
    coalesce_rule as _coalesce_rule,
    members_for_target as _members_for_target,
    repeat_by_discriminator_rule as _repeat_by_discriminator_rule,
    for_each_rules as _for_each_rules,
    value_set_members as _value_set_members,
)

FORMAL_ORIGIN_EDGES = {"inherit", "contains", "originalId"}
FORMAL_ORIGIN_REVERSE_EDGES = {
    "inherit^-1", "contains^-1", "originalId^-1",
}
RELATIONSHIP_EDGE_PREFIX = "relationship:"
CONFIDENCE = {"CONTEXT": 0, "WEAK": 1, "MEDIUM": 2, "STRONG": 3}
GENERIC_SHORTNAMES = {
    "zeitpunkt", "zeitraum", "code", "wert", "name", "identifikation",
    "untersuchungsregion", "definitorischer_link", "agens", "status",
    "gultigkeit", "version", "typ", "art",
}

# These nodes carry document plumbing rather than dataset payload.  The list is
# role-based and intentionally stable: frequency is not admissibility evidence
# and would, for example, incorrectly remove the ubiquitous ``hl7:value``.
_CDA_CANDIDATE_INFRASTRUCTURE = {
    "hl7:realmCode", "hl7:typeId", "hl7:templateId", "hl7:languageCode",
    "hl7:setId", "hl7:versionNumber", "hl7:confidentialityCode",
    "hl7:priorityCode", "hl7:reference", "hl7:statusCode", "@nullFlavor",
    "@classCode", "@moodCode", "@typeCode", "@determinerCode",
    "@contextControlCode",
}
_CDA_TARGET_CANDIDATE_POLICY = "cda-target-candidates-v2"


def _names_agree(left: str | None, right: str | None) -> bool:
    a, b = _norm(left or ""), _norm(right or "")
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 10 and (a.startswith(b[:10]) or b.startswith(a[:10])))


def _all_xml(xml_paths: Iterable[Path]) -> Iterable[ET.Element]:
    for path in sorted(set(xml_paths)):
        try:
            root, _ = parse_file(path)
        except ET.ParseError:
            continue
        yield root


def _graph_and_associations(
    xml_paths: Iterable[Path],
) -> tuple[
    dict[str, set[tuple[str, str]]],
    list[dict[str, Any]],
    dict[str, str],
]:
    graph: dict[str, set[tuple[str, str]]] = defaultdict(set)
    associations: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for root in _all_xml(xml_paths):
        parents = {child: parent for parent in root.iter() for child in parent}
        element_code_systems: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for element in root.iter():
            if local(element.tag) != "element" or not element.get("id"):
                continue
            owner = parents.get(element)
            while owner is not None and (
                local(owner.tag) != "template" or not owner.get("id")
            ):
                owner = parents.get(owner)
            if owner is None:
                continue
            key = (
                str(owner.get("id") or ""),
                str(owner.get("effectiveDate") or ""),
                str(element.get("id") or ""),
            )
            element_code_systems[key].update(
                str(child.get("codeSystem") or "")
                for child in list(element)
                if local(child.tag) == "vocabulary" and child.get("codeSystem")
            )

        def add_association(
            concept: str, template_id: str, effective: str,
            element_id: str, kind: str,
        ) -> None:
            systems = set(element_code_systems.get(
                (template_id, effective, element_id), set()
            ))
            if not systems:
                for (tid, _, eid), values in element_code_systems.items():
                    if tid == template_id and eid == element_id:
                        systems.update(values)
            row = {
                "concept": concept,
                "template_id": template_id,
                "effective_date": effective,
                "element_id": element_id,
                "kind": kind,
                "code_systems": sorted(systems),
            }
            if row not in associations:
                associations.append(row)

        for node in root.iter():
            if local(node.tag) == "concept" and node.get("id"):
                source = node.get("id") or ""
                name = child_text(node, "name")
                if name:
                    names.setdefault(source, name)
                for child in list(node):
                    kind = local(child.tag)
                    if kind == "inherit" and child.get("ref"):
                        graph[source].add(("inherit", child.get("ref") or ""))
                        if child.get("originalId"):
                            graph[source].add(("originalId", child.get("originalId") or ""))
                    elif kind == "relationship" and child.get("ref"):
                        graph[source].add((
                            RELATIONSHIP_EDGE_PREFIX
                            + (child.get("type") or "unspecified"),
                            child.get("ref") or "",
                        ))
                    elif kind == "contains" and child.get("ref"):
                        graph[source].add(("contains", child.get("ref") or ""))
                        if child.get("originalId"):
                            graph[source].add((
                                "originalId", child.get("originalId") or "",
                            ))
            elif local(node.tag) == "templateAssociation" and node.get("templateId"):
                template_id = node.get("templateId") or ""
                effective = node.get("effectiveDate") or ""
                for child in list(node):
                    if local(child.tag) == "concept" and child.get("ref") and child.get("elementId"):
                        add_association(
                            child.get("ref") or "", template_id, effective,
                            child.get("elementId") or "", "templateAssociation",
                        )
            elif local(node.tag) == "origconcept" and node.get("ref") and node.get("elementId"):
                add_association(
                    node.get("ref") or "",
                    node.get("templateId") or "",
                    node.get("templateEffectiveDate") or "",
                    node.get("elementId") or "",
                    "staticAssociation",
                )
    reverse: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for source, edges in graph.items():
        for kind, target in edges:
            if kind in FORMAL_ORIGIN_EDGES:
                reverse[target].add((kind + "^-1", source))
    for source, edges in reverse.items():
        graph[source].update(edges)
    return graph, associations, names


def _formal_origin_label_index(
    xml_paths: Iterable[Path],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build an undirected formal-origin label graph for contextual matching.

    This graph is intentionally separate from the directed formal-origin graph
    used to prove template associations.  Only ``inherit``, ``contains`` and
    their compiled ``originalId`` locators may contribute labels.  Generic
    relationships are review hints and cannot indirectly create an executable
    mapping through a lexical descendant rule.
    """
    labels: dict[str, set[str]] = defaultdict(set)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for root in _all_xml(xml_paths):
        for node in root.iter():
            if local(node.tag) != "concept" or not node.get("id"):
                continue
            concept_id = node.get("id") or ""
            for child in list(node):
                kind = local(child.tag)
                if kind in {"name", "synonym", "desc"}:
                    value = " ".join("".join(child.itertext()).split())
                    if value:
                        labels[concept_id].add(value)
                reference = ""
                if kind == "inherit":
                    reference = child.get("ref") or ""
                    original = child.get("originalId") or ""
                    if original:
                        neighbours[concept_id].add(original)
                        neighbours[original].add(concept_id)
                elif kind == "contains":
                    reference = child.get("ref") or ""
                if reference:
                    neighbours[concept_id].add(reference)
                    neighbours[reference].add(concept_id)
    return labels, neighbours


def _implementation_paths(
    xml_paths: Iterable[Path],
) -> dict[str, list[dict[str, str]]]:
    """Collect explicit dataset ``implementation/@xpath`` declarations.

    These are rare but stronger than heuristic bridges: the dataset itself
    names the CDA path and usually supplies the owning ``templateLocation``.
    """
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for root in _all_xml(xml_paths):
        for concept in root.iter():
            if local(concept.tag) != "concept" or not concept.get("id"):
                continue
            concept_id = concept.get("id") or ""
            for implementation in list(concept):
                if local(implementation.tag) != "implementation" or not implementation.get("xpath"):
                    continue
                template_id = ""
                effective = ""
                template_xpath = ""
                for child in list(implementation):
                    if local(child.tag) != "templateLocation":
                        continue
                    template_id = child.get("id") or ""
                    effective = child.get("effectiveDate") or ""
                    template_xpath = child.get("xpath") or ""
                    break
                row = {
                    "xpath": implementation.get("xpath") or "",
                    "hl7_type": implementation.get("hl7Type") or "",
                    "template_id": template_id,
                    "effective_date": effective,
                    "template_xpath": template_xpath,
                }
                if row not in result[concept_id]:
                    result[concept_id].append(row)
    return result


def _xpath_shape(value: str) -> str:
    value = re.sub(r"\[[^\]]*\]", "", value or "")
    value = value.replace("cda:", "hl7:").strip("/")
    return re.sub(r"/+", "/", value)


def _implementation_candidates(
    field: Mapping[str, Any],
    implementations: Mapping[str, list[dict[str, str]]],
    cda: Mapping[str, Any],
) -> list[dict[str, Any]]:
    concept_id = str(field.get("concept") or "")
    rows = implementations.get(concept_id, [])
    if not rows:
        return []
    targets = _renderable_targets(cda)
    result: list[dict[str, Any]] = []
    for row in rows:
        full = _xpath_shape(row.get("xpath") or "")
        base = _xpath_shape(row.get("template_xpath") or "")
        relative = full
        if base and (full == base or full.startswith(base + "/")):
            relative = full[len(base):].strip("/")
        tid = row.get("template_id") or ""
        effective = row.get("effective_date") or ""
        matches: list[tuple[str, Mapping[str, Any], bool]] = []
        for name, target in targets.items():
            if tid and str(target.get("template_id") or "") != tid:
                continue
            target_path = _xpath_shape(str(target.get("path") or ""))
            if (
                target_path not in {relative, full}
                and not full.endswith("/" + target_path)
            ):
                continue
            shifted = bool(effective and str(target.get("template_effective_date") or "") != effective)
            matches.append((name, target, shifted))
        exact = [item for item in matches if not item[2]]
        chosen = exact or matches
        for name, target, shifted in chosen:
            compatible, reasons = direct_compatibility(field, target, explicit_path=True)
            result.append(_candidate(
                name, target,
                [f"XPATH{'_VERSION' if shifted else ''}({tid or 'document'})"],
                "MEDIUM" if shifted else "STRONG",
                112 if shifted else 125,
                kind="XPATH",
                actionable=compatible,
                warnings=(reasons if not compatible else []),
            ))
    return result


def _renderable_targets(cda: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(name): target
        for name, target in cda.get("targets", {}).items()
        if target.get("renderable", True)
        and not target.get("prohibited")
        and len(target.get("locations", [])) == 1
    }


def _target_indexes(
    cda: Mapping[str, Any],
) -> tuple[
    dict[str, list[tuple[str, Mapping[str, Any]]]],
    dict[tuple[str, str], list[tuple[str, Mapping[str, Any]]]],
    dict[str, list[tuple[str, Mapping[str, Any]]]],
]:
    by_vs: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    by_code: dict[tuple[str, str], list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    by_template: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for name, target in _renderable_targets(cda).items():
        by_template[str(target.get("template_id") or "")].append((name, target))
        for oid in required_value_set_ids(target):
            by_vs[str(oid)].append((name, target))
        for code in target.get("codes", []):
            if code.get("code") and code.get("code_system"):
                by_code[(str(code["code"]), str(code["code_system"]))].append((name, target))
    return by_vs, by_code, by_template


def _type_match(model_type: str, cda_type: str | None) -> bool:
    return type_match(model_type, cda_type)


def _is_payload(model_type: str, target: Mapping[str, Any]) -> bool:
    return payload_match(model_type, target)


def _direct(
    field: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    cda: Mapping[str, Any] | None = None,
    occurrence_mapping: Mapping[str, Any] | None = None,
    transform: Mapping[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    if not field.get("type"):
        return True, []
    compatible, reasons = (
        transformed_compatibility(field, target, transform)
        if transform else direct_compatibility(field, target)
    )
    if cda is not None and occurrence_mapping is not None:
        # Candidate selection must use the same occurrence contract as runtime
        # validation.  A for_each rule may bind one source repeat below a
        # shared target container, so raw repeat-depth equality is too strict.
        from ..bindings import for_each_target_positions

        if for_each_target_positions(
            field, target, cda, occurrence_mapping
        ) is not None:
            reasons = [
                reason for reason in reasons
                if not reason.startswith("dataset has ")
            ]
            compatible = not reasons
    return compatible, reasons


def _rim_slots(target: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Return XSD structural slots recorded in a target's provenance."""
    target_path = _xpath_shape(str(target.get("path") or ""))
    return {
        (str(item.get("datatype") or ""), str(item.get("datatype_part") or ""))
        for item in target.get("provenance", [])
        if isinstance(item, Mapping)
        and item.get("datatype") and item.get("datatype_part")
        and "cda-rim" in str(item.get("source") or "")
        and _xpath_shape(str(item.get("path") or "")) == target_path
    }


def _association_reference_targets(
    association: Mapping[str, Any], cda: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    template_id = str(association.get("template_id") or "")
    element_id = str(association.get("element_id") or "")
    return [
        target for target in cda.get("targets", {}).values()
        if str(target.get("template_id") or "") == template_id
        and str(target.get("element_id") or "") == element_id
    ]


def _association_slots(
    association: Mapping[str, Any], cda: Mapping[str, Any],
) -> set[tuple[str, str]]:
    """Resolve an associated legacy element to one CDA/RIM base slot.

    Legacy profiles frequently use different element ids from the active
    profile.  Their XML path identifies possible compiled nodes; the actual
    projection key is the XSD-derived owning class + particle, never the leaf
    spelling alone.
    """
    references = _association_reference_targets(association, cda)
    slots = set().union(*(_rim_slots(target) for target in references)) if references else set()
    if slots:
        return slots
    reference_paths = {
        _xpath_shape(str(target.get("path") or ""))
        for target in references if target.get("path")
    }
    reference_types: set[str] = set()
    for target in references:
        if not target.get("datatype"):
            continue
        try:
            reference_types.add(base_datatype(target.get("datatype")))
        except KeyError:
            # Structural CDA/RIM classes are not HL7 V3 scalar datatypes and
            # cannot establish a scalar projection slot on their own.
            continue
    for target in cda.get("targets", {}).values():
        target_path = _xpath_shape(str(target.get("path") or ""))
        if not target_path or not any(
            target_path == path or target_path.endswith("/" + path)
            for path in reference_paths
        ):
            continue
        if reference_types and base_datatype(target.get("datatype")) not in reference_types:
            continue
        slots.update(_rim_slots(target))
    return slots


def _projected_association_targets(
    association: Mapping[str, Any],
    cda: Mapping[str, Any],
    context: Mapping[str, Any] | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    slots = _association_slots(association, cda)
    # More than one structural slot means the legacy element cannot be
    # projected without guessing which CDA/RIM particle it represented.
    if len(slots) != 1:
        return []
    slot = next(iter(slots))
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    result = [
        (str(name), target)
        for name, target in _renderable_targets(cda).items()
        if slot in _rim_slots(target)
        and (
            not context_node
            or _is_descendant_target(target, context_node)
        )
    ]
    if len(result) == 1:
        return result
    if result and context_node:
        context_locations = [
            str(value) for value in context_node.get("locations", [])
        ]
        if len(context_locations) == 1:
            prefix_depth = len(context_locations[0].split("."))
            ranked = sorted(
                (
                    len(str(target.get("locations", [""])[0]).split("."))
                    - prefix_depth,
                    name,
                    target,
                )
                for name, target in result
            )
            if len(ranked) == 1 or ranked[0][0] < ranked[1][0]:
                return [(ranked[0][1], ranked[0][2])]
    return []


def _concept_evidence_paths(
    start: str, graph: Mapping[str, set[tuple[str, str]]], depth: int = 8
) -> list[tuple[str, list[tuple[str, str]]]]:
    result: list[tuple[str, list[tuple[str, str]]]] = [(start, [])]
    queue: deque[tuple[str, list[tuple[str, str]]]] = deque([(start, [])])
    best_depth = {start: 0}
    while queue:
        concept, path = queue.popleft()
        if len(path) >= depth:
            continue
        for edge in sorted(graph.get(concept, set())):
            kind, target = edge
            next_depth = len(path) + 1
            if best_depth.get(target, 999) < next_depth:
                continue
            best_depth[target] = next_depth
            next_path = path + [edge]
            result.append((target, next_path))
            queue.append((target, next_path))
    return result


def _edge_confidence(path: list[tuple[str, str]], version_shift: bool = False) -> str:
    kinds = [edge for edge, _ in path]
    if any(
        edge.startswith(RELATIONSHIP_EDGE_PREFIX)
        or edge not in FORMAL_ORIGIN_EDGES | FORMAL_ORIGIN_REVERSE_EDGES
        for edge in kinds
    ):
        return "WEAK"
    if version_shift or any(
        edge in FORMAL_ORIGIN_REVERSE_EDGES for edge in kinds
    ):
        return "MEDIUM"
    return "STRONG"


def _candidate(
    name: str,
    target: Mapping[str, Any],
    chain: list[str],
    confidence: str,
    score: int,
    *,
    kind: str,
    actionable: bool = True,
    mode: str = "value",
    via: str | None = None,
    via_name: str | None = None,
    warnings: list[str] | None = None,
    mapping: Any = None,
    suggested: bool = False,
) -> dict[str, Any]:
    result = {
        "target": name,
        "node": target,
        "chain": chain,
        "confidence": confidence,
        "score": score,
        "kind": kind,
        "actionable": actionable,
        "mode": mode,
        "via": via,
        "via_name": via_name,
        "warnings": warnings or [],
        "mapping": mapping,
    }
    if suggested:
        result["suggested"] = True
    return result


def _ta_candidates(
    field: Mapping[str, Any],
    graph: Mapping[str, set[tuple[str, str]]],
    associations: list[dict[str, Any]],
    concept_names: Mapping[str, str],
    cda: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    association_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for association in associations:
        association_index[str(association.get("concept") or "")].append(
            association
        )
    concept_id = str(field.get("concept") or "")
    evidence_paths = _concept_evidence_paths(concept_id, graph)
    source_index = cda.get("source_index", {})
    targets = cda.get("targets", {})
    result: list[dict[str, Any]] = []
    for related, path in evidence_paths:
        for association in association_index.get(related, []):
            template_id = str(association.get("template_id") or "")
            effective = str(association.get("effective_date") or "")
            element_id = str(association.get("element_id") or "")
            names = list(source_index.get(f"{template_id}|ID:{element_id}", []))
            if not names:
                names = [
                    name for name, target in targets.items()
                    if str(target.get("template_id") or "") == template_id
                    and str(target.get("element_id") or "") == element_id
                ]
            direct = [
                (str(name), targets.get(name, {})) for name in names
                if targets.get(name, {}).get("renderable", True)
                and not targets.get(name, {}).get("prohibited")
                and len(targets.get(name, {}).get("locations", [])) == 1
            ]
            association_kind = str(association.get("kind") or "")
            context_node = (
                context.get("node", {})
                if isinstance(context, Mapping) else {}
            )
            outside_context: list[tuple[str, Mapping[str, Any]]] = []
            if (
                association_kind == "staticAssociation"
                and context_node
            ):
                outside_context = [
                    item for item in direct
                    if not _is_same_or_descendant_target(item[1], context_node)
                ]
                direct = [
                    item for item in direct
                    if _is_same_or_descendant_target(item[1], context_node)
                ]
            projected = False
            selected = direct
            if not selected:
                selected = _projected_association_targets(
                    association, cda, context
                )
                projected = bool(selected)
            for name, target in selected + outside_context:
                specialization = (
                    projected
                    or str(target.get("template_id") or "") != template_id
                )
                version_shift = (
                    not specialization and bool(effective)
                    and bool(target.get("template_effective_date"))
                    and str(target.get("template_effective_date")) != effective
                )
                confidence = _edge_confidence(path, version_shift or specialization)
                score = 100
                for edge, _ in path:
                    score -= (
                        25
                        if edge.startswith(RELATIONSHIP_EDGE_PREFIX)
                        else 12
                        if edge in FORMAL_ORIGIN_REVERSE_EDGES
                        else 3
                    )
                if version_shift:
                    score -= 8
                if specialization:
                    score -= 6
                chain = [edge for edge, _ in path]
                if association_kind == "staticAssociation":
                    chain.append("STATIC_ASSOC")
                else:
                    chain.append(
                        "TA_SPEC" if specialization else
                        "TA_VERSION" if version_shift else "TA"
                    )
                if projected:
                    slot = next(iter(_rim_slots(target)))
                    chain.append(f"CDA_RIM_SLOT({slot[0]}.{slot[1]})")
                transform = None
                systems = [
                    str(value) for value in association.get("code_systems", [])
                    if value
                ]
                if (
                    str(field.get("type") or "") == "code"
                    and not accepted_values(field)
                    and len(set(systems)) == 1
                ):
                    transform = {
                        "type": "code_system",
                        "code_system": systems[0],
                    }
                    chain.append(f"OPEN_CODE_SYSTEM({systems[0]})")
                actionable, direct_warnings = _direct(
                    field, target, cda=cda,
                    occurrence_mapping=occurrence_mapping,
                    transform=transform,
                )
                warnings: list[str] = list(direct_warnings)
                occurrence_mismatch = (name, target) in outside_context
                if occurrence_mismatch:
                    actionable = False
                    warnings.insert(
                        0,
                        "static association resolves outside the selected "
                        "CDA occurrence; explicit occurrence evidence required",
                    )
                if not actionable:
                    warning = "requires transform or a different CDA payload"
                    if warning not in warnings and not occurrence_mismatch:
                        warnings.insert(0, warning)
                relationship_path = any(
                    edge.startswith(RELATIONSHIP_EDGE_PREFIX)
                    for edge, _ in path
                )
                relationship_name_drift = bool(
                    relationship_path
                    and not _names_agree(
                        str(field.get("name") or ""),
                        concept_names.get(related),
                    )
                )
                if relationship_path:
                    # DECOR.xsd defines object relationships as implicit,
                    # unchecked hints. Their type remains useful provenance,
                    # but a relationship path cannot prove an executable
                    # dataset-to-template association.
                    actionable = False
                    warnings.append(
                        "ART-DECOR relationship is review evidence, not "
                        "formal concept inheritance"
                    )
                if relationship_name_drift:
                    score -= 20
                    warnings.append("relationship name drift")
                mapping = (
                    {"target": name, "transform": transform}
                    if transform is not None else None
                )
                candidate = _candidate(
                    name,
                    target,
                    chain,
                    confidence,
                    score,
                    kind=(
                        "STATIC_ASSOC_SLOT" if projected else
                        "STATIC_ASSOC" if association_kind == "staticAssociation"
                        else "TA"
                    ),
                    actionable=actionable,
                    via=related,
                    via_name=concept_names.get(related),
                    warnings=warnings,
                    mapping=mapping,
                )
                if relationship_path:
                    candidate["semantic_blocked"] = (
                        "relationship_requires_review"
                    )
                if occurrence_mismatch:
                    candidate["occurrence_mismatch"] = True
                result.append(candidate)
    return result


def _template_name_index(cda: Mapping[str, Any]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for target in _renderable_targets(cda).values():
        tid = str(target.get("template_id") or "")
        for value in (target.get("template_name"), target.get("template_display_name")):
            key = _norm(str(value or ""))
            if tid and len(key) >= 6:
                index[key].add(tid)
    return index


def _mapping_indexes(cda: Mapping[str, Any]) -> tuple[
    dict[str, list[tuple[str, Mapping[str, Any]]]],
    dict[tuple[str, str], list[tuple[str, Mapping[str, Any]]]],
    dict[str, list[tuple[str, Mapping[str, Any]]]],
    dict[str, set[str]],
]:
    by_vs, by_code, by_template = _target_indexes(cda)
    return by_vs, by_code, by_template, _template_name_index(cda)


def _principal_target(
    template_id: str,
    field: Mapping[str, Any],
    by_template: Mapping[str, list[tuple[str, Mapping[str, Any]]]],
) -> tuple[str, Mapping[str, Any]] | None:
    candidates = by_template.get(template_id, [])
    if not candidates:
        return None
    model_type = str(field.get("type") or "")
    if not model_type:
        # Dataset groups describe placement/occurrence structure.  A CDA/RIM
        # container may now carry its structural class as ``datatype`` after
        # model expansion, so datatype presence no longer distinguishes a
        # container from a scalar value.  Use the compiled representation
        # instead: explicit, non-writable elements with children are structural
        # candidates; generated datatype descendants and writable endpoints are
        # not.  The template root is the shallowest such candidate.
        containers = [
            item for item in candidates
            if item[1].get("kind") == "element"
            and item[1].get("renderable")
            and not item[1].get("writable")
            and not item[1].get("datatype_derived")
            and item[1].get("has_children")
        ]
        return min(
            containers,
            key=lambda item: len(str(item[1].get("path") or "")),
        ) if containers else None
    typed = [
        item for item in candidates
        if _is_payload(model_type, item[1]) and _type_match(model_type, item[1].get("datatype"))
    ]
    explicit = [item for item in typed if not item[1].get("datatype_derived")]
    if explicit:
        required = [
            item for item in explicit
            if item[1].get("mandatory") or int(item[1].get("min") or 0) >= 1
        ]
        # Template-name evidence locates a template.  When requiredness singles
        # out one compatible payload, prefer it to an optional narrative or
        # auxiliary leaf.  Preserve the established nearest-target behavior if
        # requiredness does not resolve the choice.
        if required:
            required_depth = min(
                str(item[1].get("path") or "").count("/")
                for item in required
            )
            nearest_required = [
                item for item in required
                if str(item[1].get("path") or "").count("/")
                == required_depth
            ]
            if len(nearest_required) == 1:
                return nearest_required[0]
        return min(explicit, key=lambda item: len(str(item[1].get("path") or "")))
    # A wildcard structural class exposes many type-compatible RIM children.
    # Datatype compatibility alone cannot decide that an unconstrained
    # realmCode, statusCode, or another generated slot carries this field.
    if len(typed) == 1:
        return typed[0]
    return None


def _name_candidates(
    path: str,
    field: Mapping[str, Any],
    cda: Mapping[str, Any],
    by_template: Mapping[str, list[tuple[str, Mapping[str, Any]]]],
    name_index: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    short = str(field.get("short_name") or path.rsplit(".", 1)[-1])
    if short.casefold() in GENERIC_SHORTNAMES:
        return []
    key = _norm(short)
    if len(key) < 6:
        return []
    tids: set[str] = set()
    for candidate, owners in name_index.items():
        if key == candidate:
            tids.update(owners)
        elif (
            min(len(key), len(candidate)) >= 7
            and abs(len(key) - len(candidate)) <= 8
            and (candidate.startswith(key) or key.startswith(candidate))
        ):
            tids.update(owners)
    result: list[dict[str, Any]] = []
    for tid in sorted(tids):
        selected = _principal_target(tid, field, by_template)
        if selected is None:
            continue
        name, target = selected
        result.append(_candidate(
            name,
            target,
            ["NAME"],
            "MEDIUM",
            85,
            kind="NAME",
            via=str(field.get("concept") or ""),
            via_name=str(field.get("name") or ""),
        ))
    return result


def _description_candidates(
    field: Mapping[str, Any], cda: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Weak bridge from dataset name to an ART-DECOR element description.

    This is intentionally lower-ranked than formal TA/NAME evidence.  It is
    useful when a newer specialized template retained the semantic description
    but no formal association was carried forward to its new template id.
    """
    wanted = _norm(str(field.get("name") or ""))
    model_type = str(field.get("type") or "")
    if len(wanted) < 6:
        return []
    matches: list[tuple[str, Mapping[str, Any]]] = []
    for name, target in _renderable_targets(cda).items():
        description = _norm(str(target.get("description") or ""))
        if not description or description != wanted:
            continue
        if model_type and (not _type_match(model_type, target.get("datatype")) or not _is_payload(model_type, target)):
            continue
        matches.append((name, target))

    # Description prose is not an identifier.  Only use it as executable
    # evidence when the exact description + datatype/payload constraints select
    # one unique current target.  Generic labels such as ``Zeitpunkt`` occur in
    # many unrelated observations and must remain contextual evidence instead.
    unique = {name: target for name, target in matches}
    if len(unique) != 1:
        return []
    name, target = next(iter(unique.items()))
    return [_candidate(
        name, target, ["DESC"], "WEAK", 65, kind="DESC",
        via=str(field.get("concept") or ""), via_name=str(field.get("name") or ""),
    )]


def _vocabulary_candidates(
    field: Mapping[str, Any],
    by_vs: Mapping[str, list[tuple[str, Mapping[str, Any]]]],
    by_code: Mapping[tuple[str, str], list[tuple[str, Mapping[str, Any]]]],
    by_template: Mapping[str, list[tuple[str, Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    model_type = str(field.get("type") or "")
    formal = field.get("formal_terminology", {})
    source_binding_complete = not (
        isinstance(formal, Mapping)
        and str(formal.get("status") or "") == "unresolved"
    )
    value_sets = {str(value) for value in field.get("value_sets", [])}
    terms = {
        (str(code.get("code")), str(code.get("code_system")))
        for code in field.get("codes", [])
        if code.get("code") and code.get("code_system")
    }

    vs_hits: list[tuple[str, Mapping[str, Any], str]] = []
    for oid in sorted(value_sets):
        for name, target in by_vs.get(oid, []):
            vs_hits.append((name, target, oid))
            actionable, warnings = _direct(field, target)
            if not source_binding_complete:
                actionable = False
                warnings = [
                    *warnings,
                    "source ValueSet membership is unresolved; shared binding identity is review evidence only",
                ]
            result.append(_candidate(
                name, target, [f"VS({oid})"], "WEAK", 55, kind="VS",
                actionable=actionable, warnings=warnings,
            ))

    term_hits: list[tuple[str, Mapping[str, Any], tuple[str, str]]] = []
    term_by_template: dict[str, list[tuple[str, Mapping[str, Any], tuple[str, str]]]] = defaultdict(list)
    for term in sorted(terms):
        for name, target in by_code.get(term, []):
            row = (name, target, term)
            term_hits.append(row)
            term_by_template[str(target.get("template_id") or "")].append(row)

    # Code and value-set evidence in the same template is stronger than either
    # one alone even when they constrain different elements (e.g. code locates
    # the observation while the value set constrains its value).
    for name, target, oid in vs_hits:
        locators = term_by_template.get(str(target.get("template_id") or ""), [])
        if locators:
            labels = ",".join(sorted({term[0] for _, _, term in locators}))
            actionable, warnings = _direct(field, target)
            if not source_binding_complete:
                actionable = False
                warnings = [
                    *warnings,
                    "source ValueSet membership is unresolved; shared binding identity is review evidence only",
                ]
            result.append(_candidate(
                name,
                target,
                [f"TERM({labels})", f"VS({oid})"],
                "MEDIUM",
                80,
                kind="TERM+VS",
                actionable=actionable, warnings=warnings,
            ))

    # Terminology can locate a template; datatype + payload position can then
    # identify the value-bearing element.  This avoids writing a numeric value
    # into hl7:code merely because the observation's code matched.
    for template_id, locators in term_by_template.items():
        locator_names = {name for name, _, _ in locators}
        payloads = [
            (name, target) for name, target in by_template.get(template_id, [])
            if name not in locator_names
            and _type_match(model_type, target.get("datatype"))
            and _is_payload(model_type, target)
        ]
        explicit_payloads = [
            item for item in payloads if not item[1].get("datatype_derived")
        ]
        if explicit_payloads:
            payloads = explicit_payloads
        unique_payloads = {name: target for name, target in payloads}
        if len(unique_payloads) == 1:
            name, target = next(iter(unique_payloads.items()))
            labels = ",".join(sorted({term[0] for _, _, term in locators}))
            result.append(_candidate(
                name,
                target,
                [f"TERM({labels})", f"DT({model_type})"],
                "WEAK",
                60,
                kind="TERM+DT",
            ))

    for name, target, term in term_hits:
        if model_type == "code" and _type_match("code", target.get("datatype")) and _is_payload("code", target):
            result.append(_candidate(
                name, target, [f"TERM({term[0]})"], "WEAK", 50, kind="TERM"
            ))
        elif model_type == "boolean" and _type_match("boolean", target.get("datatype")):
            result.append(_candidate(
                name,
                target,
                [f"TERM({term[0]})"],
                "WEAK",
                50,
                kind="TERM",
                mode="presence",
                warnings=["boolean represented by coded target presence"],
            ))
        else:
            # Keep non-actionable terminology evidence in the report, but do
            # not let it become executable configuration on its own.
            result.append(_candidate(
                name,
                target,
                [f"TERM({term[0]})"],
                "WEAK",
                35,
                kind="TERM",
                actionable=False,
            ))
    return result


def _schematron_constraint_candidates(
    field: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Strengthen an existing bridge with generated structural evidence.

    A Schematron constraint is never a semantic bridge by itself.  It may only
    confirm that an already identified leaf is required or governed by an
    explicit ValueSet, and direct compatibility must still hold.
    """
    result: list[dict[str, Any]] = []
    formal = field.get("formal_terminology", {})
    source_terminology_unresolved = bool(
        isinstance(formal, Mapping)
        and str(formal.get("status") or "") == "unresolved"
    )
    for candidate in candidates:
        confidence = str(candidate.get("confidence") or "")
        if confidence not in {"WEAK", "MEDIUM"}:
            continue
        target = candidate.get("node", {})
        if not isinstance(target, Mapping):
            continue
        supporting = sorted({
            str(item.get("kind") or "")
            for item in target.get("schematron_constraints", [])
            if isinstance(item, Mapping)
            and item.get("kind") in {"required", "value_set"}
        })
        if not supporting:
            continue
        compatible, warnings = _direct(
            field, target, cda=cda, occurrence_mapping=occurrence_mapping,
            transform=(
                candidate.get("mapping", {}).get("transform")
                if isinstance(candidate.get("mapping"), Mapping) else None
            ),
        )
        strengthened = dict(candidate)
        strengthened.update({
            "chain": list(candidate.get("chain", [])) + [
                "SCHEMATRON_CONSTRAINT(" + ",".join(supporting) + ")"
            ],
            "confidence": "MEDIUM" if confidence == "WEAK" else "STRONG",
            "score": int(candidate.get("score") or 0) + 5,
            "kind": "SCHEMATRON_CONSTRAINT",
            "actionable": bool(
                not source_terminology_unresolved
                and not candidate.get("occurrence_mismatch")
                and not candidate.get("semantic_blocked")
                and (candidate.get("actionable") or compatible)
            ),
            "warnings": list(dict.fromkeys(
                list(candidate.get("warnings", []))
                + ([] if candidate.get("actionable") else warnings)
            )),
        })
        result.append(strengthened)
    return result


def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, tuple[str, ...], str], dict[str, Any]] = {}
    for row in candidates:
        key = row["target"], tuple(row["chain"]), str(row.get("mode") or "value")
        old = unique.get(key)
        if old is None or (row["score"], CONFIDENCE[row["confidence"]], row["actionable"]) > (
            old["score"], CONFIDENCE[old["confidence"]], old["actionable"]
        ):
            unique[key] = row
    return sorted(
        unique.values(),
        key=lambda row: (row["actionable"], row["score"], CONFIDENCE[row["confidence"]]),
        reverse=True,
    )


def _unresolved_reason(
    candidates: Iterable[Mapping[str, Any]],
    context: Mapping[str, Any] | None,
) -> str:
    rows = list(candidates)
    nodes = [row.get("node", {}) for row in rows]
    warnings = [
        str(warning)
        for row in rows
        for warning in row.get("warnings", [])
    ]
    if any(len(node.get("locations", [])) != 1 for node in nodes):
        return "ambiguous_value_target"
    if any("incompatible" in warning or warning.startswith("datatype ") for warning in warnings):
        return "incompatible_value_type"
    contextual = context.get("node", {}) if isinstance(context, Mapping) else {}
    if contextual and not contextual.get("writable"):
        if contextual.get("datatype") and contextual.get("has_children"):
            return (
                "structural_container_available"
                if classify_datatype(contextual.get("datatype")) == "structural"
                else "datatype_component_available"
            )
        return "structural_only"
    if nodes and all(not node.get("writable") for node in nodes):
        return "structural_only"
    return "no_semantic_evidence"


def _request_key(kind: str, identity: Mapping[str, Any]) -> str:
    oid = str(
        identity.get("id")
        or identity.get("ref")
        or identity.get("code_system")
        or identity.get("template_id")
        or ""
    )
    effective = str(
        identity.get("effective_date")
        or identity.get("flexibility")
        or identity.get("template_effective_date")
        or ""
    )
    if effective.strip().casefold() == "dynamic":
        effective = ""
    return f"{kind}:{oid}" + (f"@{effective}" if effective else "")


def _gap_classification(
    path: str,
    detail: Mapping[str, Any],
    field: Mapping[str, Any],
    unresolved_templates: list[Mapping[str, Any]],
    cda: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Describe the first gate that prevents a complete field decision.

    A selected field is complete unless its formal terminology is explicitly
    unresolved.  ``unbound`` and logical-only domains are not terminology
    failures for scalar fields that do not claim a formal binding.
    """
    formal = field.get("formal_terminology", {})
    if isinstance(formal, Mapping) and formal.get("status") == "unresolved":
        reopening = [
            _request_key("valueset", item)
            for item in formal.get("missing_value_sets", [])
            if isinstance(item, Mapping)
        ] + [
            _request_key(
                "valueset" if item.get("ref") else "codesystem", item
            )
            for item in formal.get("unresolved_includes", [])
            if isinstance(item, Mapping)
        ]
        return {
            "gate": "terminology",
            "kind": "closure",
            "reopens_with": list(dict.fromkeys(key for key in reopening if key)),
        }

    if detail.get("selected") is not None:
        return None

    blocked = str(detail.get("runtime_blocked") or "")
    primary = detail.get("primary", {})
    primary_target = (
        str(primary.get("target") or "")
        if isinstance(primary, Mapping) else ""
    )
    if blocked.startswith(("SHARED(", "WEAKER_SHARED_TARGET(")):
        fields = [
            str(item) for item in detail.get("shared_target_fields", []) if item
        ]
        weaker = re.fullmatch(r"WEAKER_SHARED_TARGET\((.+)\)", blocked)
        if weaker:
            fields.extend([path, weaker.group(1)])
        reopening = sorted(set(fields))
        if primary_target:
            reopening.append(primary_target)
        return {
            "gate": "semantic", "kind": "shared_target",
            "reopens_with": reopening,
        }
    if blocked.startswith("REQUIRED_COMPANION("):
        return {
            "gate": "semantic", "kind": "missing_companion",
            "reopens_with": [
                str(item) for item in detail.get("required_companions", [])
            ],
        }

    context = detail.get("context", {})
    context_node = (
        context.get("node", {}) if isinstance(context, Mapping) else {}
    )
    context_template = (
        str(context_node.get("template_id") or "")
        if isinstance(context_node, Mapping) else ""
    )
    unresolved = [
        item for item in unresolved_templates
        if str(item.get("template") or "") == context_template
    ]
    if unresolved:
        return {
            "gate": "physical", "kind": "closure",
            "reopens_with": [
                _request_key("template", {
                    "id": item.get("template"),
                    "effective_date": item.get("flexibility"),
                })
                for item in unresolved
            ],
        }

    reason = str(detail.get("unresolved_reason") or "")
    candidates = [
        item for item in [detail.get("primary"), *detail.get("alternatives", [])]
        if isinstance(item, Mapping)
    ]
    candidate_targets = list(dict.fromkeys(
        str(item.get("target") or "") for item in candidates
        if item.get("target")
    ))
    context_target = (
        str(context.get("target") or "") if isinstance(context, Mapping) else ""
    )
    possible_targets = detail.get("possible_targets", {})
    possible_items = (
        possible_targets.get("items", [])
        if isinstance(possible_targets, Mapping) else []
    )

    if reason == "structural_only":
        # DEC-021 requires an exact stranded template as well as an open
        # context.  Openness alone never implies that an attachment exists.
        unlocated_templates = list(dict.fromkeys(
            _request_key("template", node)
            for item in candidates
            for node in [item.get("node", {})]
            if isinstance(node, Mapping)
            and node.get("template_id")
            and not node.get("locations")
        ))
        if (
            isinstance(context_node, Mapping)
            and context_node.get("is_closed") is False
            and unlocated_templates
        ):
            return {
                "gate": "physical", "kind": "containment",
                "reopens_with": unlocated_templates,
            }
        if possible_items:
            return {
                "gate": "semantic", "kind": "no_association",
                "reopens_with": [association_request(path)],
            }
        return {
            "gate": "physical", "kind": "no_writable_leaf",
            "reopens_with": [context_target] if context_target else [],
        }
    if reason == "ambiguous_value_target":
        return {
            "gate": "physical", "kind": "ambiguous_target",
            "reopens_with": candidate_targets,
        }
    if reason in {"datatype_component_available", "structural_container_available"}:
        if reason == "structural_container_available" and possible_items:
            return {
                "gate": "semantic", "kind": "no_association",
                "reopens_with": [association_request(path)],
            }
        components: list[str] = []
        if cda is not None and isinstance(context_node, Mapping):
            rows: list[tuple[str, Mapping[str, Any], int]] = []
            context_locations = [
                str(value) for value in context_node.get("locations", [])
            ]
            if len(context_locations) == 1:
                root = context_locations[0]
                rows = [
                    (
                        str(name), target,
                        len(locations[0].split(".")) - len(root.split(".")),
                    )
                    for name, target in cda.get("targets", {}).items()
                    for locations in [[str(value) for value in target.get("locations", [])]]
                    if target.get("writable")
                    and len(locations) == 1
                    and locations[0].startswith(root + ".")
                    and (
                        reason == "structural_container_available"
                        or len(locations[0].split(".")) == len(root.split(".")) + 1
                    )
                ]
            else:
                root_path = str(context_node.get("path") or "").rstrip("/")
                rows = [
                    (
                        str(name), target,
                        str(target.get("path") or "").count("/")
                        - root_path.count("/"),
                    )
                    for name, target in cda.get("targets", {}).items()
                    if target.get("writable")
                    and str(target.get("path") or "").startswith(root_path + "/")
                    and (
                        reason == "structural_container_available"
                        or str(target.get("path") or "").count("/")
                        == root_path.count("/") + 1
                    )
                ]
            if reason == "structural_container_available":
                rows.sort(key=lambda row: (
                    not _is_payload(str(field.get("type") or ""), row[1]),
                    bool(row[1].get("datatype_derived")), row[2], row[0],
                ))
                rows = rows[:20]
            else:
                rows.sort(key=lambda row: (row[2], row[0]))
            components = [name for name, _, _ in rows]
        return {
            "gate": "physical",
            "kind": (
                "structural_container"
                if reason == "structural_container_available"
                else "datatype_component"
            ),
            "reopens_with": list(dict.fromkeys(
                ([context_target] if context_target else []) + components
            )),
        }
    if reason == "incompatible_value_type":
        target_types = sorted({
            str(value)
            for item in candidates
            for value in item.get("node", {}).get("logical_types", [])
            if isinstance(item.get("node"), Mapping) and value
        })
        return {
            "gate": "semantic", "kind": "lossy_domain",
            "reopens_with": [
                f"source_type:{field.get('type') or 'unknown'}",
                *(f"target_type:{value}" for value in target_types),
            ],
        }
    if reason == "no_semantic_evidence" and context_target:
        return {
            "gate": "semantic", "kind": "no_association",
            "reopens_with": [context_target],
        }
    if not context_target and not candidate_targets:
        return {
            "gate": "blocked_upstream", "kind": "no_candidate",
            "reopens_with": [],
        }
    return {
        "gate": "semantic", "kind": "no_association",
        "reopens_with": [context_target] if context_target else candidate_targets,
    }



def _words(value: str) -> set[str]:
    parts = re.findall(r"[A-Za-zÄÖÜäöüß]+", value or "")
    words: set[str] = set()
    for part in parts:
        norm = _norm(part)
        if len(norm) >= 5:
            words.add(norm)
            words.add(norm[:5])
    return words


def _template_semantic_words(field: Mapping[str, Any]) -> set[str]:
    values = [str(field.get("name") or ""), str(field.get("short_name") or "")]
    for code in field.get("codes", []):
        if isinstance(code, Mapping):
            values.append(str(code.get("display_name") or ""))
    return set().union(*(_words(value) for value in values)) if values else set()


def _template_ids_for_transform(
    field: Mapping[str, Any], candidates: list[dict[str, Any]], cda: Mapping[str, Any]
) -> list[tuple[str, str]]:
    # Existing formal/terminology evidence is the preferred template locator.
    ordered: list[tuple[str, str]] = []
    for candidate in candidates:
        if (
            candidate.get("occurrence_mismatch")
            or candidate.get("semantic_blocked")
            == "relationship_requires_review"
        ):
            continue
        target = candidate.get("node", {})
        tid = str(target.get("template_id") or "")
        if tid and all(item[0] != tid for item in ordered):
            ordered.append((tid, candidate.get("confidence") or "WEAK"))
    if ordered:
        return ordered

    # If no bridge exists, allow a unique semantic template-name match using
    # the field name plus published terminology display names.  This recovers
    # cases such as Tetanusschutz ↔ Immunisierung Clostridium tetani without
    # hard-coding clinical OIDs.
    field_words = _template_semantic_words(field)
    scores: dict[str, tuple[int, str]] = {}
    for target in cda.get("targets", {}).values():
        if not target.get("renderable") or len(target.get("locations", [])) != 1:
            continue
        if not str(target.get("path") or "").endswith("/@negationInd"):
            continue
        tid = str(target.get("template_id") or "")
        label = f"{target.get('template_name') or ''} {target.get('template_display_name') or ''}"
        overlap = len(field_words & _words(label))
        if overlap:
            scores[tid] = max(scores.get(tid, (0, "")), (overlap, label))
    if not scores:
        return []
    best = max(score for score, _ in scores.values())
    winners = [tid for tid, (score, _) in scores.items() if score == best]
    return [(winners[0], "MEDIUM")] if best >= 2 and len(winners) == 1 else []


def _option_class(label: str) -> str:
    text = _norm(label)
    raw = (label or "").casefold()
    if any(token in raw for token in ("unbekannt", "nicht erhebbar", "unknown", "nicht bekannt", "unklar")):
        return "unknown"
    if re.search(r"\b(nicht|kein|keine|keinen|ohne|not|no)\b", raw):
        return "negative"
    return "positive"


def _semantic_transform_candidates(
    field: Mapping[str, Any], candidates: list[dict[str, Any]], cda: Mapping[str, Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    targets = cda.get("targets", {})
    template_ids = _template_ids_for_transform(field, candidates, cda)

    # 1) Coded state represented by CDA negationInd (+ optional nullFlavor).
    options = list(accepted_values(field))
    if options:
        classes = {label: _option_class(str(label)) for label in options}
        polar_states = [
            kind for kind in classes.values() if kind in {"positive", "negative"}
        ]
        # negationInd represents the polarity of one statement.  It cannot
        # carry a multi-valued clinical domain merely because one of its labels
        # happens to contain "not", "none", or "without".  Admit only a
        # binary positive/negative state (plus an optional unknown state).
        if sorted(polar_states) == ["negative", "positive"]:
            for tid, confidence in template_ids:
                negations = [
                    (name, target) for name, target in targets.items()
                    if target.get("renderable") and len(target.get("locations", [])) == 1
                    and str(target.get("template_id") or "") == tid
                    and str(target.get("path") or "").endswith("/@negationInd")
                ]
                explicit_negations = [
                    item for item in negations if not item[1].get("datatype_derived")
                ]
                if explicit_negations:
                    negations = explicit_negations
                if len(negations) != 1:
                    continue
                neg_name, neg_target = negations[0]
                enum_map = {
                    label: (False if kind in {"positive", "unknown"} else True)
                    for label, kind in classes.items()
                }
                rules: list[dict[str, Any]] = [{
                    "target": neg_name,
                    "transform": {"type": "enum", "map": enum_map},
                }]
                unknown = [label for label, kind in classes.items() if kind == "unknown"]
                if unknown:
                    nulls = [
                        (name, target) for name, target in targets.items()
                        if target.get("renderable") and len(target.get("locations", [])) == 1
                        and str(target.get("template_id") or "") == tid
                        and str(target.get("path") or "").endswith("/@nullFlavor")
                    ]
                    explicit_nulls = [
                        item for item in nulls if not item[1].get("datatype_derived")
                    ]
                    if explicit_nulls:
                        nulls = explicit_nulls
                    if len(nulls) == 1:
                        null_map = {label: ("NI" if label in unknown else None) for label in options}
                        rules.append({"target": nulls[0][0], "transform": {"type": "enum", "map": null_map}})
                result.append(_candidate(
                    neg_name, neg_target,
                    ["SEMANTIC_STATE", "TRANSFORM(enum→negationInd)"],
                    # A positive/negative source enumeration plus one formally
                    # located explicit negationInd is stronger payload evidence
                    # than a template-name match to an unrelated generated
                    # coded slot such as statusCode.
                    confidence, 98 if confidence == "MEDIUM" else 72,
                    kind="TRANSFORM", actionable=True, mapping=rules,
                    warnings=["generated from dataset state labels and CDA negation semantics"],
                ))
                break

    # 1b) A boolean dataset field can represent presence/absence of a uniquely
    # located coded act.  The target template supplies the clinical code; CDA
    # negationInd supplies the boolean representation.
    if str(field.get("type") or "") == "boolean":
        from ..bindings import presence_target_complete

        found_negation = False
        for tid, confidence in template_ids:
            negations = [
                (name, target) for name, target in targets.items()
                if target.get("writable") and len(target.get("locations", [])) == 1
                and str(target.get("template_id") or "") == tid
                and str(target.get("path") or "").endswith("/@negationInd")
            ]
            explicit_negations = [
                item for item in negations if not item[1].get("datatype_derived")
            ]
            if explicit_negations:
                negations = explicit_negations
            if len(negations) != 1:
                continue
            name, target = negations[0]
            transform = {"type": "not"}
            compatible, reasons = transformed_compatibility(
                field, target, transform,
            )
            if compatible:
                result.append(_candidate(
                    name, target,
                    ["SEMANTIC_ACT", "TRANSFORM(boolean→negationInd)"],
                    confidence, 97 if confidence == "MEDIUM" else 73,
                    kind="BOOLEAN_PRESENCE", actionable=True,
                    mapping={"target": name, "transform": transform},
                    warnings=[
                        "coded act presence represented by inverse CDA negationInd"
                    ],
                ))
                found_negation = True
                break

        # Some optional statements express a boolean solely through their
        # occurrence: when present, every clinical payload is fixed by the
        # template.  A direct source terminology association may locate that
        # template even though it deliberately exposes no writable value.
        # Keep this as an explicit presence assignment to the structural root;
        # it is not a scalar CDA value target.
        if not found_negation:
            exact_terms = {
                (str(code.get("code") or ""), str(code.get("code_system") or ""))
                for code in field.get("codes", [])
                if isinstance(code, Mapping)
                and str(code.get("equivalence") or "equal") == "equal"
                and code.get("code") and code.get("code_system")
            }
            for tid, _ in template_ids:
                fixed_terms = {
                    (str(code.get("code") or ""), str(code.get("code_system") or ""))
                    for target in targets.values()
                    if str(target.get("template_id") or "") == tid
                    for code in target.get("codes", [])
                    if isinstance(code, Mapping)
                    and code.get("code") and code.get("code_system")
                }
                roots = [
                    (name, target) for name, target in targets.items()
                    if str(target.get("template_id") or "") == tid
                    and target.get("kind") == "element"
                    and target.get("renderable")
                    and target.get("has_children")
                    and len(target.get("locations", [])) == 1
                    and "/" not in str(target.get("path") or "")
                ]
                if not exact_terms & fixed_terms or len(roots) != 1:
                    continue
                name, target = roots[0]
                if not presence_target_complete(cda, target):
                    continue
                result.append(_candidate(
                    name, target,
                    ["TERM(EXACT)", "ARTDECOR_FIXED_STATEMENT", "PRESENCE(boolean)"],
                    "MEDIUM", 96, kind="CONDITIONAL_PRESENCE",
                    actionable=True,
                    mapping={"target": name, "mode": "presence"},
                    warnings=[
                        "boolean true emits the optional fixed statement; false omits it"
                    ],
                ))
                break

    # 2) Coded ordinal represented as PQ/INT/REAL score.
    ordinal_map = {
        str(label): info.get("ordinal")
        for label, info in accepted_values(field).items()
        if isinstance(info, Mapping) and info.get("ordinal") is not None
    }
    if len(ordinal_map) >= 2:
        for tid, locator_confidence in template_ids:
            formally_located = {
                str(candidate.get("target") or ""): candidate.get("node", {})
                for candidate in candidates
                if str(candidate.get("node", {}).get("template_id") or "") == tid
                and candidate.get("node", {}).get("writable")
                and candidate.get("node", {}).get("value_representation", {}).get("kind")
                == ValueRepresentationKind.QUANTITY.value
            }
            numeric = list(formally_located.items()) or [
                (name, target) for name, target in targets.items()
                if target.get("writable") and len(target.get("locations", [])) == 1
                and str(target.get("template_id") or "") == tid
                and target.get("value_representation", {}).get("kind")
                == ValueRepresentationKind.QUANTITY.value
            ]
            explicit_numeric = [
                item for item in numeric if not item[1].get("datatype_derived")
            ]
            if explicit_numeric:
                numeric = explicit_numeric
            if len(numeric) != 1:
                continue
            name, target = numeric[0]
            ordinal_transform: dict[str, Any] = {
                "type": "ordinal", "map": ordinal_map,
            }
            rule = {"target": name, "transform": ordinal_transform}
            compatible, reasons = transformed_compatibility(
                field, target, ordinal_transform
            )
            if compatible:
                result.append(_candidate(
                    name, target,
                    ["TERM/TEMPLATE", "TRANSFORM(ordinal→score)"],
                    "MEDIUM" if locator_confidence in {"MEDIUM", "STRONG"} else "WEAK",
                    76, kind="TRANSFORM", actionable=True, mapping=rule,
                    warnings=[
                        "ordinal score derived from leading option ranks or "
                        "explicit rank/score wording"
                    ]
                ))
                break
    return result


def _candidates(
    path: str,
    field: Mapping[str, Any],
    graph: Mapping[str, set[tuple[str, str]]],
    associations: list[dict[str, Any]],
    concept_names: Mapping[str, str],
    implementations: Mapping[str, list[dict[str, str]]],
    cda: Mapping[str, Any],
    indexes: tuple[
        dict[str, list[tuple[str, Mapping[str, Any]]]],
        dict[tuple[str, str], list[tuple[str, Mapping[str, Any]]]],
        dict[str, list[tuple[str, Mapping[str, Any]]]],
        dict[str, set[str]],
    ],
    context: Mapping[str, Any] | None = None,
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_vs, by_code, by_template, name_index = indexes
    result = _implementation_candidates(field, implementations, cda)
    result.extend(_ta_candidates(
        field, graph, associations, concept_names, cda,
        context, occurrence_mapping,
    ))
    result.extend(_name_candidates(path, field, cda, by_template, name_index))
    result.extend(_description_candidates(field, cda))
    result.extend(_vocabulary_candidates(field, by_vs, by_code, by_template))
    result.extend(_schematron_constraint_candidates(
        field, list(result), cda, occurrence_mapping,
    ))
    result.extend(_semantic_transform_candidates(field, list(result), cda))
    result.extend(_unbridged_writable_candidates(
        field, context, cda, occurrence_mapping,
    ))
    return _deduplicate(result)


def _unbridged_writable_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Resolve one explicit ART-DECOR leaf role below a mapped container.

    A unique exact short-name/leaf match is not global lexical guessing: the
    enclosing dataset group has already selected the target template and the
    target leaf is an explicit ART-DECOR constraint.  Datatype-derived leaves
    remain excluded because names such as ``value`` recur throughout the CDA
    datatype graph.
    """
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if not isinstance(context_node, Mapping) or not context_node:
        return []
    source_name = _norm(str(field.get("short_name") or ""))
    if not source_name:
        return []
    source_words = _semantic_words(str(field.get("name") or ""))
    matches: list[tuple[str, Mapping[str, Any]]] = []
    for name, target in cda.get("targets", {}).items():
        if (
            not target.get("writable")
            or target.get("prohibited")
            or len(target.get("locations", [])) != 1
            or target.get("datatype_derived")
            or not _is_descendant_target(target, context_node)
        ):
            continue
        leaf = str(target.get("path") or target.get("element_name") or "").rsplit("/", 1)[-1]
        leaf = leaf.lstrip("@").split(":", 1)[-1]
        description_words = _semantic_words(str(target.get("description") or ""))
        if (
            source_name != _norm(leaf)
            and not (
                target.get("polymorphic")
                and source_words and source_words <= description_words
            )
        ):
            continue
        compatible, _ = _context_direct(
            field, target, context_node, cda, occurrence_mapping,
        )
        if compatible:
            matches.append((str(name), target))
    if len(matches) != 1:
        return []
    name, target = matches[0]
    return [_candidate(
        name, target,
        _context_chain(context) + [f"ARTDECOR_ROLE({source_name})"],
        "MEDIUM", 74,
        kind="ARTDECOR_ROLE", actionable=True,
        warnings=[
            "selected by a unique explicit ART-DECOR leaf role inside the mapped container"
        ],
    )]


def _context_description_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Project an exact ART-DECOR description through its CDA descendants."""
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if not isinstance(context_node, Mapping) or not context_node:
        return []
    labels = {
        _norm(str(field.get(key) or ""))
        for key in ("name", "description") if field.get(key)
    }
    labels.discard("")
    if not labels:
        return []

    targets = cda.get("targets", {})
    selected: dict[str, tuple[Mapping[str, Any], str, bool]] = {}
    for anchor_name, anchor in targets.items():
        description = _norm(str(anchor.get("description") or ""))
        if (
            not description or description not in labels
            or anchor.get("prohibited")
            or len(anchor.get("locations", [])) != 1
            or not _is_descendant_target(anchor, context_node)
        ):
            continue
        compatible, _ = _context_direct(
            field, anchor, context_node, cda, occurrence_mapping,
        )
        if anchor.get("writable") and compatible:
            selected[str(anchor_name)] = (anchor, str(anchor_name), False)
            continue

        descendants: list[tuple[int, str, Mapping[str, Any]]] = []
        anchor_path = str(anchor.get("path") or "").rstrip("/")
        for name, target in targets.items():
            target_path = str(target.get("path") or "")
            if (
                not anchor_path or not target_path.startswith(anchor_path + "/")
                or not target.get("writable") or target.get("prohibited")
                or target.get("datatype_derived")
                or len(target.get("locations", [])) != 1
                or not _is_descendant_target(target, context_node)
            ):
                continue
            compatible, _ = _context_direct(
                field, target, context_node, cda, occurrence_mapping,
            )
            if compatible:
                descendants.append((target_path.count("/"), str(name), target))
        if not descendants:
            continue
        deepest = max(depth for depth, _, _ in descendants)
        leaves = [(name, target) for depth, name, target in descendants if depth == deepest]
        if len(leaves) == 1:
            name, target = leaves[0]
            selected[name] = (target, str(anchor_name), True)

    if len(selected) != 1:
        return []
    name, (target, anchor_name, projected) = next(iter(selected.items()))
    return [_candidate(
        name, target,
        _context_chain(context) + [
            f"ARTDECOR_DESC({anchor_name})",
            *( ["CDA_DESCENDANT"] if projected else [] ),
        ],
        "MEDIUM", 90 if projected else 93,
        kind="ARTDECOR_DESCENDANT" if projected else "ARTDECOR_DESC",
        actionable=True,
        warnings=[
            "selected by an exact source/ART-DECOR description inside the mapped container"
        ],
    )]


def _section_narrative_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Use the one compiled section narrative for a contextual text field."""
    if str(field.get("type") or "") != "text":
        return []
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if (
        not isinstance(context_node, Mapping)
        or str(context_node.get("path") or "").rsplit("/", 1)[-1].partition("[")[0]
        not in {"hl7:section", "section"}
    ):
        return []
    matches: list[tuple[str, Mapping[str, Any]]] = []
    for name, target in cda.get("targets", {}).items():
        if (
            target.get("content_role") != "section_narrative"
            or not target.get("writable") or target.get("prohibited")
            or len(target.get("locations", [])) != 1
            or not _is_descendant_target(target, context_node)
        ):
            continue
        compatible, _ = _context_direct(
            field, target, context_node, cda, occurrence_mapping,
        )
        if compatible:
            matches.append((str(name), target))
    if len(matches) != 1:
        return []
    name, target = matches[0]
    return [_candidate(
        name, target,
        _context_chain(context) + ["CDA_ROLE(section_narrative)"],
        "MEDIUM", 82, kind="SECTION_NARRATIVE", actionable=True,
        warnings=["selected from the compiled CDA section narrative role"],
    )]


def _context_for_node(
    node: Mapping[str, Any],
    groups: Mapping[str, Mapping[str, Any]],
    group_results: Mapping[str, dict[str, Any]],
) -> dict[str, Any] | None:
    parent = node.get("parent")
    while parent:
        parent_result = group_results.get(str(parent))
        if parent_result:
            selected = parent_result.get("primary") or parent_result.get("context")
            if selected:
                concept = str(
                    groups.get(str(parent), {}).get("concept")
                    or str(parent).rsplit(".", 1)[-1]
                )
                return {
                    "chain": [f"CTX[{concept.rsplit('.', 1)[-1]}]"],
                    "confidence": "CONTEXT",
                    "target": selected["target"],
                    "node": selected.get("node", {}),
                }
        parent = groups.get(str(parent), {}).get("parent")
    return None


def _context_chain(context: Mapping[str, Any] | None) -> list[Any]:
    return list(context.get("chain", [])) if context is not None else []


def _semantic_words(value: str) -> set[str]:
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return {
        word.casefold() for word in re.findall(r"[A-Za-z0-9]+", normalized)
        if len(word) >= 3
    }


def _formal_origin_labels(
    concept_id: str,
    labels: Mapping[str, set[str]],
    neighbours: Mapping[str, set[str]],
    maximum_depth: int = 2,
) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    queue: deque[tuple[str, int]] = deque([(concept_id, 0)])
    seen = {concept_id}
    while queue:
        current, depth = queue.popleft()
        rows.extend((current, depth, label) for label in sorted(labels.get(current, set())))
        if depth >= maximum_depth:
            continue
        for related in sorted(neighbours.get(current, set())):
            if related not in seen:
                seen.add(related)
                queue.append((related, depth + 1))
    return rows


def _is_descendant_target(
    target: Mapping[str, Any], context_node: Mapping[str, Any],
) -> bool:
    context_locations = [str(value) for value in context_node.get("locations", [])]
    target_locations = [str(value) for value in target.get("locations", [])]
    if len(context_locations) == 1 and len(target_locations) == 1:
        root = context_locations[0]
        return target_locations[0].startswith(root + ".")
    root_path = str(context_node.get("path") or "").rstrip("/")
    target_path = str(target.get("path") or "")
    return bool(root_path and target_path.startswith(root_path + "/"))


def _is_same_or_descendant_target(
    target: Mapping[str, Any], context_node: Mapping[str, Any],
) -> bool:
    """Return whether two compiled nodes belong to one selected occurrence."""
    context_locations = [str(value) for value in context_node.get("locations", [])]
    target_locations = [str(value) for value in target.get("locations", [])]
    if len(context_locations) == 1 and len(target_locations) == 1:
        root, location = context_locations[0], target_locations[0]
        return location == root or location.startswith(root + ".")
    root_path = str(context_node.get("path") or "").rstrip("/")
    target_path = str(target.get("path") or "").rstrip("/")
    return bool(
        root_path
        and (target_path == root_path or target_path.startswith(root_path + "/"))
    )


def _candidate_source_roles(target: Mapping[str, Any]) -> set[str]:
    """Return the exact compiler-source roles behind one target."""
    return {
        role.strip()
        for item in target.get("provenance", [])
        if isinstance(item, Mapping)
        for role in str(item.get("source") or "").split("+")
        if role.strip()
    }


def _candidate_target_role(target: Mapping[str, Any]) -> str:
    role = str(target.get("element_name") or "")
    if role:
        return role
    return str(target.get("path") or "").rsplit("/", 1)[-1]


def _location_order(value: Any) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(value or "").split(".") if part)
    except ValueError:
        return ()


def _cda_target_candidate_pool(
    cda: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Return reviewable payload leaves without treating them as evidence.

    Unlike the coverage-headline filter, this inventory retains CDA/RIM
    structural children such as ``associatedEntity/id``. Scalar datatype
    descendants are payload candidates; other datatype plumbing and fixed
    document infrastructure remain excluded.
    """
    result: dict[str, Mapping[str, Any]] = {}
    targets = cda.get("targets", {})
    constrained_components = constrained_datatype_components(cda)
    for name, target in targets.items() if isinstance(targets, Mapping) else ():
        if not isinstance(target, Mapping):
            continue
        source_roles = _candidate_source_roles(target)
        datatype_payload = bool(
            target.get("datatype_derived")
            and target.get("kind") == "element"
            and isinstance(target.get("value_representation"), Mapping)
            and target.get("value_representation", {}).get("kind")
            and str(name) in constrained_components
        )
        payload_source = (
            not target.get("datatype_derived")
            or ("cda-rim" in source_roles and "datatype" not in source_roles)
            or datatype_payload
        )
        if (
            target.get("writable")
            and len(target.get("locations", [])) == 1
            and not target.get("prohibited")
            and not target.get("fixed")
            and not target.get("conditional_fixed")
            and target.get("system_value") is None
            and payload_source
            and _candidate_target_role(target)
            not in _CDA_CANDIDATE_INFRASTRUCTURE
        ):
            result[str(name)] = target
    return result


def _template_occurrence(
    cda: Mapping[str, Any], target: Mapping[str, Any],
) -> tuple[str, str]:
    """Identify the nearest concrete contained-template occurrence."""
    template_id = str(target.get("template_id") or "")
    locations = [str(value) for value in target.get("locations", [])]
    document = cda.get("document", [])
    if len(locations) != 1 or not isinstance(document, list):
        return template_id, ""
    items: list[Any] = document
    current: Mapping[str, Any] | None = None
    occurrence = ""
    prefix: list[str] = []
    for token in locations[0].split("."):
        try:
            index = int(token)
            if index >= 100000:
                attributes = current.get("attributes", []) if current else []
                node = attributes[index - 100000]
            else:
                node = items[index]
        except (IndexError, TypeError, ValueError):
            break
        if not isinstance(node, Mapping):
            break
        current = node
        prefix.append(token)
        if (
            node.get("kind") == "template"
            and str(node.get("template_id") or "") == template_id
        ):
            occurrence = ".".join(prefix)
        children = node.get("children", [])
        items = children if isinstance(children, list) else []
    return template_id, occurrence or "document"


def _possible_target_inventory(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    claimed_by: Mapping[str, list[str]],
    occurrence_claims: Mapping[tuple[str, str], list[tuple[str, str]]],
) -> dict[str, Any] | None:
    """List type-compatible descendants for a human mapping decision."""
    if not isinstance(context, Mapping):
        return None
    context_node = context.get("node", {})
    if (
        not isinstance(context_node, Mapping)
        or len(context_node.get("locations", [])) != 1
    ):
        return None
    model_type = str(field.get("type") or "")
    if not model_type:
        return None
    pool = _cda_target_candidate_pool(cda)
    unavoidable = unavoidable_targets_problems(cda, list(pool))
    items: list[dict[str, Any]] = []
    for name, target in pool.items():
        if (
            not _is_descendant_target(target, context_node)
            or not target_type_match(model_type, target)
        ):
            continue
        occurrence = _template_occurrence(cda, target)
        exact_claims = sorted(set(claimed_by.get(name, [])))
        instance_claims: dict[str, set[str]] = defaultdict(set)
        for claimed_target, field_path in occurrence_claims.get(occurrence, []):
            if claimed_target != name:
                instance_claims[claimed_target].add(field_path)
        value_set_bindings = target.get("value_set_bindings", [])
        source_repeat_depth = len(field.get("repeat_chain", []))
        target_repeats = [
            str(value) for value in target.get("repeat_ancestors", [])
        ]
        conformance_conflicts = [
            {
                **problem,
                "message": cooccurrence_problem_message(problem),
            }
            for problem in unavoidable.get(name, [])
        ]
        items.append({
            "target": name,
            "template": {
                "id": str(target.get("template_id") or ""),
                "effective_date": str(
                    target.get("template_effective_date") or ""
                ),
                "name": str(target.get("template_name") or ""),
                "display_name": str(
                    target.get("template_display_name") or ""
                ),
                "description": str(
                    target.get("template_description") or ""
                ),
                "location": occurrence[1],
            },
            "path": str(target.get("path") or ""),
            "datatype": str(target.get("datatype") or ""),
            "cardinality": {
                "min": target.get("min"), "max": target.get("max"),
            },
            "conformance": str(target.get("conformance") or ""),
            "description": str(target.get("description") or ""),
            "bound_value_sets": list(value_set_bindings),
            "non_null_requires": [
                str(value) for value in target.get("non_null_requires", [])
            ],
            "repeat_ancestors": target_repeats,
            "requires_occurrence_rule": (
                source_repeat_depth != len(target_repeats)
            ),
            "claimed_by": exact_claims,
            "already_claimed": bool(exact_claims),
            "conformance_conflicts": conformance_conflicts,
            "containing_instance_claimed_by": [
                {"target": claimed_target, "fields": sorted(paths)}
                for claimed_target, paths in sorted(instance_claims.items())
            ],
            "available": not exact_claims and not conformance_conflicts,
        })
    items.sort(key=lambda item: (
        _location_order(item["template"].get("location")),
        str(item["template"].get("display_name") or ""),
        str(item["template"].get("id") or ""),
        str(item.get("path") or ""),
        str(item.get("target") or ""),
    ))
    if not items:
        return None
    return {
        "policy": _CDA_TARGET_CANDIDATE_POLICY,
        "context_target": str(context.get("target") or ""),
        "document_pool_size": len(pool),
        "items": items,
    }


def _mapping_target_claims(
    fields: Mapping[str, Any], cda: Mapping[str, Any],
) -> tuple[
    dict[str, list[str]],
    dict[tuple[str, str], list[tuple[str, str]]],
]:
    """Index direct and structured field selections by physical CDA target."""
    claimed_by: dict[str, list[str]] = defaultdict(list)
    occurrence_claims: dict[
        tuple[str, str], list[tuple[str, str]]
    ] = defaultdict(list)
    targets = cda.get("targets", {})
    for field_path, selection in fields.items():
        for rule in mapping_rules(selection):
            target_name = cda_target_name(rule)
            target = (
                targets.get(target_name, {})
                if isinstance(targets, Mapping) else {}
            )
            if not target_name or not isinstance(target, Mapping) or not target:
                continue
            claimed_by[target_name].append(str(field_path))
            occurrence_claims[_template_occurrence(cda, target)].append(
                (target_name, str(field_path))
            )
    return dict(claimed_by), dict(occurrence_claims)


def _context_direct(
    field: Mapping[str, Any],
    target: Mapping[str, Any],
    context_node: Mapping[str, Any],
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Check payload compatibility with one contextual singleton branch.

    A repeated dataset group can be located at a repeatable CDA container
    before its generated ``for_each`` rule exists.  A descendant may add
    optional repeat levels; one source value then activates one singleton
    branch within the already matched contextual occurrence.
    """
    compatible, warnings = _direct(
        field, target, cda=cda, occurrence_mapping=occurrence_mapping,
    )
    repeat_warnings = [
        warning for warning in warnings if warning.startswith("dataset has ")
    ]
    if compatible or len(repeat_warnings) != len(warnings):
        return compatible, warnings
    source_depth = len(field.get("repeat_chain", []))
    context_repeats = list(context_node.get("repeat_ancestors", []))
    target_repeats = list(target.get("repeat_ancestors", []))
    if (
        source_depth == len(context_repeats)
        and target_repeats[:len(context_repeats)] == context_repeats
    ):
        return True, []
    return compatible, warnings


def _choice_branch_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Select a scalar endpoint from one ART-DECOR choice particle.

    Predicates distinguish alternative representations of the same CDA/RIM
    particle.  Prefer a directly compatible atomic branch; otherwise follow
    the selected complex datatype and require one unique compatible child.
    """
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if not isinstance(context_node, Mapping) or not context_node:
        return []
    targets = cda.get("targets", {})
    anchors = [
        (str(name), target)
        for name, target in targets.items()
        if (
            target.get("kind") == "element"
            and not target.get("datatype_derived")
            and "[" in str(target.get("path") or "").rsplit("/", 1)[-1]
            and len(target.get("locations", [])) == 1
            and not target.get("prohibited")
            and _is_descendant_target(target, context_node)
        )
    ]
    direct: list[tuple[str, Mapping[str, Any]]] = []
    for name, target in anchors:
        compatible, _ = _context_direct(
            field, target, context_node, cda, occurrence_mapping,
        )
        if compatible and not target.get("has_children"):
            direct.append((name, target))
    if len(direct) == 1:
        name, target = direct[0]
        return [_candidate(
            name, target,
            _context_chain(context) + ["ARTDECOR_CHOICE(atomic)"],
            "STRONG", 95, kind="ARTDECOR_CHOICE", actionable=True,
        )]

    descendants: dict[str, Mapping[str, Any]] = {}
    for _, anchor in anchors:
        anchor_path = str(anchor.get("path") or "").rstrip("/")
        for name, target in targets.items():
            target_path = str(target.get("path") or "")
            if (
                not anchor_path or not target_path.startswith(anchor_path + "/")
                or not target.get("writable") or target.get("prohibited")
                or len(target.get("locations", [])) != 1
            ):
                continue
            compatible, _ = _context_direct(
                field, target, context_node, cda, occurrence_mapping,
            )
            if compatible:
                descendants[str(name)] = target
    if not descendants:
        return []
    nearest_depth = min(
        str(target.get("path") or "").count("/")
        for target in descendants.values()
    )
    nearest = [
        (name, target) for name, target in descendants.items()
        if str(target.get("path") or "").count("/") == nearest_depth
    ]
    if len(nearest) != 1:
        return []
    name, target = nearest[0]
    return [_candidate(
        name, target,
        _context_chain(context) + [
            "ARTDECOR_CHOICE(complex)", "HL7_DATATYPE_DESCENDANT",
        ],
        "STRONG", 94, kind="ARTDECOR_CHOICE", actionable=True,
    )]


def _repeat_scope_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Resolve a direct group field at its compiled CDA occurrence boundary.

    A ``for_each`` rule establishes one target occurrence for a repeated source
    group.  For a field directly owned by that group, the nearest unique
    compatible writable descendant represents the occurrence-level value,
    rather than a deeper child-statement value.  This is especially useful for
    organizer timestamps and remains independent of clinical class names.
    """
    repeat_chain = [str(value) for value in field.get("repeat_chain", [])]
    if not repeat_chain or str(field.get("parent") or "") != repeat_chain[-1]:
        return []
    structures = (
        occurrence_mapping.get("structures", {})
        if isinstance(occurrence_mapping, Mapping) else {}
    )
    for_each = next((
        rule for rule in structures.values()
        if isinstance(rule, Mapping)
        and rule.get("type") == "for_each"
        and str(rule.get("source_group") or "") == repeat_chain[-1]
    ), None)
    if not isinstance(for_each, Mapping):
        return []
    anchor_name = str(for_each.get("target_repeat") or "")
    anchor = cda.get("targets", {}).get(anchor_name, {})
    anchor_locations = list(anchor.get("locations", []))
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if len(anchor_locations) != 1 or not isinstance(context_node, Mapping):
        return []
    anchor_parts = str(anchor_locations[0]).split(".")
    matches: list[tuple[int, str, Mapping[str, Any]]] = []
    # Reuse the ordinary payload-leaf boundary. Without it, removing an
    # unrelated semantic bridge can expose a nearest document-plumbing leaf
    # such as ``realmCode`` and turn that infrastructure into a false mapping.
    for name, target in _cda_target_candidate_pool(cda).items():
        locations = list(target.get("locations", []))
        if (
            not target.get("writable") or target.get("prohibited")
            or len(locations) != 1
            or not str(locations[0]).startswith(str(anchor_locations[0]) + ".")
            or not _is_descendant_target(target, context_node)
        ):
            continue
        compatible, _ = _context_direct(
            field, target, context_node, cda, occurrence_mapping,
        )
        if compatible:
            distance = len(str(locations[0]).split(".")) - len(anchor_parts)
            matches.append((distance, str(name), target))
    if not matches:
        return []
    nearest = min(distance for distance, _, _ in matches)
    winners = [(name, target) for distance, name, target in matches if distance == nearest]
    if len(winners) != 1:
        return []
    name, target = winners[0]
    return [_candidate(
        name, target,
        _context_chain(context) + [
            f"FOR_EACH({repeat_chain[-1]})", "NEAREST_WRITABLE_DESCENDANT",
        ],
        "STRONG", 94, kind="REPEAT_SCOPE", actionable=True,
        warnings=[
            "selected at the occurrence boundary established by the generated for_each rule"
        ],
    )]


def _context_descendant_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    labels: Mapping[str, set[str]],
    neighbours: Mapping[str, set[str]],
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Resolve one writable descendant inside a formally mapped container."""
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if not isinstance(context_node, Mapping) or not context_node:
        return []
    concept_id = str(field.get("concept") or "")
    evidence = _formal_origin_labels(concept_id, labels, neighbours)
    evidence.append((concept_id, 0, " ".join(
        str(field.get(key) or "") for key in ("name", "short_name", "description")
    )))
    candidates: list[
        tuple[int, int, int, str, Mapping[str, Any], str]
    ] = []
    for name, target in cda.get("targets", {}).items():
        if (
            not target.get("writable")
            or target.get("prohibited")
            or len(target.get("locations", [])) != 1
            or not _is_descendant_target(target, context_node)
        ):
            continue
        compatible, _ = _context_direct(
            field, target, context_node, cda, occurrence_mapping,
        )
        if not compatible:
            continue
        leaf = str(target.get("path") or "").rsplit("/", 1)[-1].lstrip("@")
        leaf = leaf.split(":", 1)[-1]
        target_words = _semantic_words(leaf)
        if not target_words or max(map(len, target_words)) < 5:
            continue
        matches = [
            (len(target_words & _semantic_words(label)), depth, label)
            for _, depth, label in evidence
            if target_words <= _semantic_words(label)
        ]
        if not matches:
            continue
        overlap, depth, label = max(matches, key=lambda row: (row[0], -row[1]))
        target_depth = str(target.get("path") or "").count("/")
        candidates.append((
            overlap, -depth, -target_depth, str(name), target, label,
        ))
    candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    if not candidates:
        return []
    best = candidates[0][:3]
    if sum(row[:3] == best for row in candidates) != 1:
        return []
    _, negative_depth, _, name, target, label = candidates[0]
    return [_candidate(
        name, target,
        _context_chain(context) + [
            f"FORMAL_ORIGIN_LABEL({label})", "CDA_DESCENDANT",
        ],
        "STRONG" if negative_depth == 0 else "MEDIUM",
        92 + negative_depth * 4,
        kind="CONTEXT_DESCENDANT",
        actionable=True,
        via=concept_id,
        via_name=label,
    )]


def _open_coded_domain_candidates(
    field: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    cda: Mapping[str, Any],
    value_sets: Mapping[Any, list[dict[str, Any]]],
    occurrence_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Resolve an explicitly open source code into one safe CDA code slot.

    This is deliberately structural and terminology-driven.  It applies only
    below a formally selected container and only when exactly one compatible
    descendant binds an explicit ``OTH`` exception and exposes the datatype's
    ``coded_original_text`` companion.  No template, class, field, or ValueSet
    identifier is embedded in the rule.
    """
    coded_domain = field.get("coded_domain", {})
    if (
        str(field.get("type") or "") != "code"
        or not isinstance(coded_domain, Mapping)
        or coded_domain.get("status") != "unconstrained"
    ):
        return []
    context_node = context.get("node", {}) if isinstance(context, Mapping) else {}
    if not isinstance(context_node, Mapping) or not context_node:
        return []

    matches: list[
        tuple[
            str, Mapping[str, Any], dict[str, str], list[dict[str, Any]],
            dict[str, Any], str,
        ]
    ] = []
    targets = cda.get("targets", {})
    for name, target in targets.items():
        if (
            not target.get("writable")
            or target.get("prohibited")
            or len(target.get("locations", [])) != 1
            or not _is_descendant_target(target, context_node)
        ):
            continue
        members, binding = _members_for_target(target, value_sets)
        if not members or binding is None:
            continue
        legal_null_flavors = {
            str(value) for value in target.get("null_flavor_exceptions", [])
            if str(value) in NULL_FLAVORS_WITH_ORIGINAL_TEXT
        }
        other = [
            member for member in members
            if str(member.get("kind") or "") == "exception"
            and str(member.get("code") or "") in legal_null_flavors
        ]
        allowed = [
            {
                key: str(member.get(key) or "")
                for key in ("code", "codeSystem", "displayName")
                if member.get(key) not in (None, "")
            }
            for member in members
            if member not in other
        ]
        if len(other) != 1:
            continue
        null_flavor = str(other[0].get("code") or "")
        parent_location = str(target["locations"][0])
        original_text = [
            (str(child_name), child)
            for child_name, child in targets.items()
            if child.get("writable")
            and child.get("content_role") == "coded_original_text"
            and len(child.get("locations", [])) == 1
            and str(child["locations"][0]).startswith(parent_location + ".")
            and str(child.get("path") or "").rsplit("/", 1)[0]
            == str(target.get("path") or "")
        ]
        if len(original_text) != 1:
            continue
        transform = {
            "type": "coded_fallback",
            "allowed": allowed,
            "null_flavor": null_flavor,
            "value_set": dict(binding),
        }
        compatible, _ = _direct(
            field, target, cda=cda,
            occurrence_mapping=occurrence_mapping, transform=transform,
        )
        if compatible:
            matches.append((
                str(name), target, binding, allowed, transform,
                original_text[0][0],
            ))
    if len(matches) != 1:
        return []
    name, target, binding, _, transform, original_text_name = matches[0]
    domain_id = str(coded_domain.get("id") or "owned-inline-list")
    effective = str(binding.get("effective_date") or "latest")
    return [_candidate(
        name, target,
        _context_chain(context) + [
            f"OPEN_CODED_DOMAIN({domain_id})",
            f"VS({binding['id']}@{effective}:{null_flavor})",
            f"CODED_ORIGINAL_TEXT({original_text_name})",
            "UNIQUE_DESCENDANT",
        ],
        "STRONG", 97, kind="OPEN_CODED_DOMAIN", actionable=True,
        mapping={"target": name, "transform": transform},
        warnings=[
            "unrecognized source codes use the target ValueSet's explicit "
            f"{null_flavor} null-flavor exception and preserve their wording "
            "in originalText"
        ],
    )]


def _context(
    path: str,
    model: Mapping[str, Any],
    group_results: Mapping[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return _context_for_node(
        model["fields"][path], model.get("groups", {}), group_results
    )


def _selected_physical_targets(value: Any) -> set[str]:
    return {
        cda_target_name(rule) for rule in mapping_rules(value)
        if cda_target_name(rule)
    }


def _block_unsatisfied_non_null_requirements(
    fields: dict[str, Any],
    details: dict[str, dict[str, Any]],
    cda: Mapping[str, Any],
) -> None:
    """Keep a compound value non-executable until its companion is selected."""
    targets = cda.get("targets", {})
    while True:
        selected = {
            name for value in fields.values()
            for name in _selected_physical_targets(value)
        }
        blocked: list[tuple[str, list[str]]] = []
        for path, value in fields.items():
            if value is None:
                continue
            missing = sorted({
                str(required)
                for name in _selected_physical_targets(value)
                for required in targets.get(name, {}).get(
                    "non_null_requires", []
                )
                if not non_null_requirement_satisfied(cda, str(required), selected)
            })
            if missing:
                blocked.append((path, missing))
        if not blocked:
            return
        for path, missing in blocked:
            fields[path] = None
            details[path]["selected"] = None
            details[path]["runtime_blocked"] = (
                "REQUIRED_COMPANION(" + ",".join(missing) + ")"
            )
            details[path]["required_companions"] = missing


def _certainty_mapping(
    path: str,
    field: Mapping[str, Any],
    cda: Mapping[str, Any],
    value_sets: Mapping[
        str | tuple[str, str], list[dict[str, Any]]
    ],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Recognize a V/A/Z/G diagnosis-certainty field and its CDA qualifier."""
    aliases: dict[str, str] = {}
    for label, info in accepted_values(field).items():
        detail = info if isinstance(info, Mapping) else {}
        aliases_for_label = [str(label)] + [
            str(value) for value in detail.get("synonyms", [])
        ]
        code = next((
            value.upper() for value in aliases_for_label
            if value.upper() in {"V", "A", "Z", "G"}
        ), None)
        if code:
            for value in aliases_for_label:
                aliases[value] = code
    if set(aliases.values()) != {"V", "A", "Z", "G"}:
        return None

    candidates: list[
        tuple[str, Mapping[str, Any], str, dict[str, dict[str, str]]]
    ] = []
    for name, target in cda.get("targets", {}).items():
        if not target.get("renderable") or len(target.get("locations", [])) != 1:
            continue
        for oid in required_value_set_ids(target):
            members = value_sets.get(str(oid), [])
            by_code = {
                str(member.get("code") or "").upper(): dict(member)
                for member in members
            }
            if {"V", "A", "Z", "G"} <= set(by_code):
                candidates.append((str(name), target, str(oid), by_code))
    if len(candidates) != 1:
        return None
    target_name, target, value_set_oid, selected_members = candidates[0]
    repeat_ancestors = target.get("repeat_ancestors", [])
    template_words = _words(
        " ".join(str(field.get(key) or "") for key in ("name", "description", "implementation"))
    ) | {"diagnos", "diagnose"}

    def sibling(suffix: str) -> str | None:
        rows: list[tuple[int, str, bool]] = []
        for name, candidate in cda.get("targets", {}).items():
            if not candidate.get("renderable") or candidate.get("repeat_ancestors", []) != repeat_ancestors:
                continue
            if not str(candidate.get("path") or "").endswith(suffix):
                continue
            label = f"{candidate.get('template_name') or ''} {candidate.get('template_display_name') or ''} {name}"
            rows.append((
                len(template_words & _words(label)), str(name),
                not candidate.get("datatype_derived"),
            ))
        explicit = [row for row in rows if row[2]]
        rows = explicit or rows
        rows.sort(reverse=True)
        return rows[0][1] if rows and (len(rows) == 1 or rows[0][0] > rows[1][0]) else None

    enum_map = {
        alias: selected_members[code] for alias, code in aliases.items()
    }
    rules: list[dict[str, Any]] = [{
        "target": target_name,
        "transform": {"type": "enum", "select": "raw", "map": enum_map},
    }]
    negation = sibling("/@negationInd")
    if negation:
        rules.append({
            "target": negation,
            "transform": {
                "type": "enum", "select": "raw",
                "map": {alias: True for alias, code in aliases.items() if code == "A"},
            },
        })
    target_defaults: dict[str, dict[str, Any]] = {}
    low = sibling("/hl7:effectiveTime/hl7:low")
    low_target = cda.get("targets", {}).get(low, {}) if low else {}
    low_required = bool(low_target.get("mandatory")) or int(low_target.get("min") or 0) >= 1
    low_nullable = (
        not low_target.get("mandatory")
        and str(low_target.get("conformance") or "").upper() != "M"
    )
    if low and low_required and low_nullable and not low_target.get("has_children"):
        target_defaults[low] = {
            "nullFlavor": "UNK",
            "reason": (
                "The transaction contains no diagnosis-onset datapoint; the "
                "required onset therefore exists with an unknown value."
            ),
        }
    primary = _candidate(
        target_name, target,
        ["LOGICAL(V/A/Z/G)", f"VS({value_set_oid})", "TRANSFORM(certainty)"],
        "MEDIUM", 105, kind="TRANSFORM", actionable=True, mapping=rules,
        warnings=["diagnosis certainty is normalized into the formal CDA qualifier vocabulary"],
    )
    return {"mapping": rules, "primary": primary}, {
        "aliases": aliases,
        "target_defaults": target_defaults,
        "site_requirements": {},
    }


def _bound_enum_mapping(
    field: Mapping[str, Any],
    cda: Mapping[str, Any],
    value_sets: Mapping[Any, list[dict[str, Any]]],
    preferred_target: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Map a complete source enumeration to one bound CDA ValueSet.

    Prefer the owner's exact concept-member terminology associations, narrowed
    by the target's required ValueSet. Otherwise every formal source label (or
    a declared synonym) must identify exactly one target member. Exactly one
    writable CDA target must satisfy the complete enumeration. Partial lexical
    similarities are deliberately insufficient.
    """
    source = accepted_values(field)
    logical_source = logical_values(field)
    if max(len(source), len(logical_source)) < 2:
        return None
    matches: list[
        tuple[str, Mapping[str, Any], str, str, dict[str, Any], str]
    ] = []
    for name, target in cda.get("targets", {}).items():
        if (
            not target.get("writable")
            or len(target.get("locations", [])) != 1
            or len(required_value_set_ids(target)) != 1
        ):
            continue
        oid = next(iter(required_value_set_ids(target)))
        members = value_sets.get(oid, [])
        if not members:
            continue

        # The source option may have several exact formal codifications. The
        # target binding is allowed to disambiguate only when exactly one of
        # those code/system pairs is an actual member of its required set.
        exact_table: dict[str, Any] = {}
        exact_members: list[dict[str, Any]] = []
        if len(logical_source) >= 2:
            target_by_pair: dict[
                tuple[str, str], list[dict[str, Any]]
            ] = defaultdict(list)
            for member in members:
                pair = (
                    str(member.get("code") or ""),
                    str(member.get("codeSystem") or ""),
                )
                if pair[0] and pair[1]:
                    target_by_pair[pair].append(dict(member))
            for label, detail in logical_source.items():
                info = detail if isinstance(detail, Mapping) else {}
                associations = info.get("terminology_associations", [])
                associations = (
                    associations if isinstance(associations, list) else []
                )
                association_matches = {
                    (
                        str(member.get("code") or ""),
                        str(member.get("codeSystem") or ""),
                    ): member
                    for association in associations
                    if isinstance(association, Mapping)
                    for member in target_by_pair.get((
                        str(association.get("code") or ""),
                        str(association.get("code_system") or ""),
                    ), [])
                }
                if len(association_matches) != 1:
                    exact_table = {}
                    exact_members = []
                    break
                member = next(iter(association_matches.values()))
                exact_members.append(member)
                for alias in [str(label)] + [
                    str(value) for value in info.get("synonyms", [])
                ]:
                    exact_table[alias] = member
            if exact_table and len({
                (
                    str(item.get("code") or ""),
                    str(item.get("codeSystem") or ""),
                )
                for item in exact_members
            }) == len(logical_source):
                transform = {
                    "type": "enum", "select": "raw", "map": exact_table,
                }
                compatible, _ = transformed_compatibility(
                    field, target, transform,
                )
                if compatible:
                    versions = {
                        str(item.get("valueSetEffectiveDate") or "")
                        for item in exact_members
                    }
                    matches.append((
                        str(name), target, oid,
                        versions.pop() if len(versions) == 1 else "",
                        transform, "EXACT_CONCEPT_ASSOCIATION",
                    ))
                    continue

        if len(source) < 2:
            # The generic lexical rule is defined over the executable formal
            # source enumeration. Logical-only options cannot prove an exact
            # ValueSet mapping, and an empty table is never a transform.
            continue
        table: dict[str, Any] = {}
        selected_members: list[dict[str, Any]] = []
        for label, detail in source.items():
            info = detail if isinstance(detail, Mapping) else {}
            aliases = [str(label)] + [
                str(value) for value in info.get("synonyms", [])
            ]
            normalized = {_norm(value) for value in aliases if _norm(value)}
            ranked: list[tuple[int, dict[str, Any]]] = []
            for member in members:
                member_code = _norm(str(member.get("code") or ""))
                member_labels = {
                    _norm(str(member.get("displayName") or "")),
                    *{
                        _norm(str(item.get("displayName") or ""))
                        for item in member.get("designations", [])
                        if isinstance(item, Mapping)
                    },
                }
                score = 2 if member_code in normalized else (
                    1 if normalized & member_labels else 0
                )
                if score:
                    ranked.append((score, dict(member)))
            best = max((score for score, _ in ranked), default=0)
            lexical_matches = [
                member for score, member in ranked if score == best
            ]
            if len(lexical_matches) != 1:
                break
            selected_members.append(lexical_matches[0])
            for alias in aliases:
                table[alias] = lexical_matches[0]
        else:
            if len({str(item.get("code") or "") for item in selected_members}) != len(source):
                continue
            transform = {"type": "enum", "select": "raw", "map": table}
            compatible, _ = transformed_compatibility(field, target, transform)
            if compatible:
                versions = {
                    str(item.get("valueSetEffectiveDate") or "")
                    for item in selected_members
                }
                matches.append((
                    str(name), target, oid,
                    versions.pop() if len(versions) == 1 else "",
                    transform, "EXACT_ENUM",
                ))
    preferred = [row for row in matches if row[0] == preferred_target]
    if len(preferred) == 1:
        matches = preferred
    if len(matches) != 1:
        return None
    name, target, oid, effective, transform, evidence = matches[0]
    selection = _candidate(
        name, target,
        [f"VS({oid}@{effective or 'latest'})", evidence],
        "STRONG", 96, kind="VALUE_SET_ENUM", actionable=True,
        mapping={"target": name, "transform": transform},
    )
    return {"mapping": selection["mapping"], "primary": selection}, {
        "kind": "bound_value_set_enum",
        "value_set": {"id": oid, "effective_date": effective},
        "evidence_level": evidence,
    }


def _mapping_candidates(
    model: Mapping[str, Any], cda: Mapping[str, Any], xml_paths: list[Path],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str | tuple[str, str], list[dict[str, Any]]]]:
    graph, associations, concept_names = _graph_and_associations(xml_paths)
    semantic_labels, formal_origin_neighbours = _formal_origin_label_index(xml_paths)
    implementations = _implementation_paths(xml_paths)
    indexes = _mapping_indexes(cda)
    details: dict[str, dict[str, Any]] = {}
    group_results: dict[str, dict[str, Any]] = {}
    groups = model.get("groups", {})
    model_fields = model.get("fields", {})

    # Groups are not written to cda-mapping.json, but they are real dataset
    # datapoints and provide structural evidence/context for their descendants.
    # Resolve parents first so a historical static association cannot silently
    # move a child group into a sibling CDA occurrence.
    for group_path in sorted(
        groups, key=lambda value: (value.count("."), value),
    ):
        group = groups[group_path]
        inherited_context = _context_for_node(
            group, groups, group_results,
        )
        group_candidates = _candidates(
            group_path, group, graph, associations, concept_names,
            implementations, cda, indexes, inherited_context,
        )
        actionable = [row for row in group_candidates if row["actionable"]]
        # Dataset groups are navigation/occurrence concepts, not scalar values.
        # A unique structural TA is therefore an executable placement context
        # even though the container itself is correctly non-writable.
        placement = actionable[0] if actionable else next((
            row for row in group_candidates
            if row.get("node", {}).get("renderable")
            and len(row.get("node", {}).get("locations", [])) == 1
            and not row.get("occurrence_mismatch")
        ), None)
        group_results[group_path] = {
            "selected": placement["target"] if placement else None,
            "primary": placement,
            "alternatives": [row for row in group_candidates if row is not placement][:8],
            "context": inherited_context if placement is None else None,
        }

    preliminary_structures = _for_each_rules(
        model, cda, {}, group_results
    )
    occurrence_mapping = {"structures": preliminary_structures}
    value_set_members = _value_set_members(xml_paths)

    fields: dict[str, Any] = {}
    for path, field in model_fields.items():
        inherited_context = _context(path, model, group_results)
        candidates = _candidates(
            path, field, graph, associations, concept_names,
            implementations, cda, indexes,
            inherited_context, occurrence_mapping,
        )
        candidates = _deduplicate(candidates + _context_descendant_candidates(
            field, inherited_context, cda, semantic_labels,
            formal_origin_neighbours, occurrence_mapping,
        ) + _context_description_candidates(
            field, inherited_context, cda, occurrence_mapping,
        ) + _choice_branch_candidates(
            field, inherited_context, cda, occurrence_mapping,
        ) + _repeat_scope_candidates(
            field, inherited_context, cda, occurrence_mapping,
        ) + _section_narrative_candidates(
            field, inherited_context, cda, occurrence_mapping,
        ) + _open_coded_domain_candidates(
            field, inherited_context, cda, value_set_members,
            occurrence_mapping,
        ))
        actionable = [row for row in candidates if row["actionable"]]
        primary = actionable[0] if actionable else None
        fields[path] = (primary.get("mapping") if primary and primary.get("mapping") is not None else primary["target"] if primary else None)
        details[path] = {
            "selected": fields[path],
            "primary": primary,
            "alternatives": [row for row in candidates if row is not primary][:8],
            "context": inherited_context if primary is None else None,
        }

    return fields, details, group_results, value_set_members


def _mapping_admissibility(
    model: Mapping[str, Any], cda: Mapping[str, Any], xml_paths: list[Path],
    fields: dict[str, Any], details: dict[str, dict[str, Any]],
    group_results: dict[str, dict[str, Any]], value_set_members: dict[str | tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    groups, model_fields = model.get("groups", {}), model.get("fields", {})
    target_defaults: dict[str, dict[str, str]] = {}
    for path, field in model_fields.items():
        old_primary = details[path].get("primary")
        semantic = (
            _certainty_mapping(path, field, cda, value_set_members)
            or _bound_enum_mapping(
                field, cda, value_set_members,
                str(old_primary.get("target") or "")
                if isinstance(old_primary, Mapping) else None,
            )
        )
        if semantic is None:
            continue
        selection, metadata = semantic
        if old_primary is not None:
            details[path]["alternatives"] = [old_primary] + list(details[path].get("alternatives", []))
        details[path]["primary"] = selection["primary"]
        details[path]["selected"] = selection["mapping"]
        details[path]["semantic_transform"] = metadata
        fields[path] = selection["mapping"]
        for target_name, default in metadata.get("target_defaults", {}).items():
            existing = target_defaults.get(str(target_name))
            if existing is not None and existing != default:
                raise ValueError(
                    f"conflicting generated defaults for CDA target {target_name!r}"
                )
            target_defaults[str(target_name)] = dict(default)

    for path in model_fields:
        if details[path]["primary"] is None:
            details[path]["unresolved_reason"] = _unresolved_reason(
                details[path].get("alternatives", []),
                details[path].get("context"),
            )

    all_details: dict[str, dict[str, Any]] = {**group_results, **details}
    all_nodes: dict[str, Mapping[str, Any]] = {**groups, **model_fields}

    claims: dict[str, list[str]] = defaultdict(list)
    field_claims: dict[str, list[str]] = defaultdict(list)
    for path, detail in all_details.items():
        primary = detail.get("primary")
        if primary:
            primary_rules = mapping_rules(primary.get("mapping"))
            primary_targets = [
                str(rule["target"]) for rule in primary_rules
                if rule.get("mode") not in {"fallback", "fallback_if_active", "if_active"}
            ] or [primary["target"]]
            for target_name in primary_targets:
                claims[target_name].append(path)
                if path in model_fields:
                    field_claims[target_name].append(path)

    structures: dict[str, dict[str, Any]] = _for_each_rules(model, cda, {}, group_results)

    # Shared targets become executable only when their occurrence semantics are
    # explicit.  ``repeat_by_discriminator`` requires a terminology-backed
    # discriminator; singleton coalescing uses the conservative equal-or-error
    # policy.
    for target_name, paths in field_claims.items():
        if len(paths) <= 1:
            continue
        resolved = _repeat_by_discriminator_rule(
            paths, target_name, model, cda, value_set_members
        )
        if resolved is None:
            resolved = _coalesce_rule(paths, target_name, model, cda)
        if resolved is not None:
            rule_name, rule = resolved
            structures[rule_name] = rule
            branches = {
                str(branch.get("source")): branch
                for branch in rule.get("branches", []) if isinstance(branch, Mapping)
            }
            for path in paths:
                branch = branches.get(path, {})
                fields[path] = {
                    "target": str(branch.get("target") or target_name),
                    "cda_target": str(branch.get("cda_target") or target_name),
                    "structure": rule_name,
                    **({"branch": branch["branch"]} if branch.get("branch") else {}),
                }
                details[path]["selected"] = fields[path]
                details[path]["structural_rule"] = rule_name
            continue

        ranked = sorted(
            paths,
            key=lambda path: (
                CONFIDENCE.get(str(details[path].get("primary", {}).get("confidence") or "CONTEXT"), 0),
                int(details[path].get("primary", {}).get("score") or 0),
            ),
            reverse=True,
        )
        winner = ranked[0]
        winner_rank = (
            CONFIDENCE.get(str(details[winner].get("primary", {}).get("confidence") or "CONTEXT"), 0),
            int(details[winner].get("primary", {}).get("score") or 0),
        )
        runner_rank = (
            CONFIDENCE.get(str(details[ranked[1]].get("primary", {}).get("confidence") or "CONTEXT"), 0),
            int(details[ranked[1]].get("primary", {}).get("score") or 0),
        )
        if winner_rank[0] > runner_rank[0] and winner_rank[0] >= CONFIDENCE["MEDIUM"]:
            for path in paths:
                if path == winner:
                    continue
                fields[path] = None
                details[path]["selected"] = None
                details[path]["runtime_blocked"] = f"WEAKER_SHARED_TARGET({winner})"
                details[path]["shared_target_fields"] = list(paths)
            details[winner]["shared_target_winner"] = True
            continue
        for path in paths:
            fields[path] = None
            details[path]["selected"] = None
            details[path]["runtime_blocked"] = f"SHARED({len(paths)})"
            details[path]["shared_target_fields"] = list(paths)

    structures.update(_for_each_rules(model, cda, fields, group_results))

    # Neutral examples may specify how category booleans materialize repeated
    # coded statements even when the source concept's own terminology denotes
    # a disorder rather than the target discriminator.  Keep this after shared
    # target resolution: the rule must see the final direct discriminator
    # mapping so it can declare an exact-occurrence coalesce when appropriate.
    example_rules = _boolean_example_discriminator_rules(
        model,
        cda,
        xml_paths,
        {path: details[path].get("context") for path in model_fields},
        fields,
        value_set_members,
    )
    for rule_name, generated in example_rules.items():
        rule = generated["rule"]
        selections = generated["selections"]
        structures[rule_name] = rule
        for path, selection in selections.items():
            mapping = selection["mapping"]
            member = selection["member"]
            template = selection["template"]
            binding = selection["binding"]
            primary = _candidate(
                str(mapping["target"]),
                cda.get("targets", {}).get(str(mapping["cda_target"]), {}),
                [
                    *(details[path].get("context", {}).get("chain", [])),
                    (
                        "ART_DECOR_EXAMPLE("
                        f"{template['id']}@{template['effective_date']})"
                    ),
                    (
                        "BOOLEAN_NEGATION("
                        f"example={str(selection['example_negation']).lower()})"
                    ),
                    (
                        f"VS({binding['id']}@"
                        f"{binding.get('effective_date') or 'latest'})"
                    ),
                    (
                        "DISCRIMINATOR("
                        f"{member.get('code')}@{member.get('codeSystem')})"
                    ),
                ],
                "STRONG",
                98,
                kind="ART_DECOR_EXAMPLE_BOOLEAN_DISCRIMINATOR",
                actionable=True,
                mapping=mapping,
                warnings=[
                    "the source boolean is represented as inverse CDA negation; "
                    "the target discriminator comes from the exact neutral example"
                ],
            )
            old_primary = details[path].get("primary")
            if old_primary is not None:
                details[path]["alternatives"] = [old_primary] + list(
                    details[path].get("alternatives", [])
                )
            fields[path] = mapping
            details[path]["selected"] = mapping
            details[path]["primary"] = primary
            details[path]["structural_rule"] = rule_name
            details[path]["semantic_transform"] = {
                "kind": "boolean_example_discriminator",
                "template": dict(template),
                "example_caption": selection["caption"],
                "example_negation": selection["example_negation"],
                "discriminator": {
                    "target": rule["discriminator"]["target"],
                    "member": dict(member),
                    "value_set": dict(binding),
                },
                "evidence_level": "STRONG",
            }
            details[path]["context"] = None
            details[path].pop("unresolved_reason", None)

    # Some occurrence boundaries can only be derived after the first scalar
    # pass has mapped sibling values (the vital-sign organizer is one example).
    # Revisit still-unmapped direct group fields against those final for_each
    # rules; this is intentionally a bounded second pass, not iterative lexical
    # propagation.
    final_occurrence_mapping = {"structures": structures}
    for path, field in model_fields.items():
        if fields.get(path) is not None:
            continue
        inherited_context = details[path].get("context")
        candidates = _repeat_scope_candidates(
            field, inherited_context, cda, final_occurrence_mapping,
        )
        if len(candidates) != 1:
            continue
        primary = candidates[0]
        fields[path] = primary["target"]
        details[path]["selected"] = primary["target"]
        details[path]["primary"] = primary
        details[path]["alternatives"] = [
            row for row in details[path].get("alternatives", [])
            if row.get("target") != primary["target"]
        ][:8]
        details[path]["context"] = None
        details[path].pop("unresolved_reason", None)

    _block_unsatisfied_non_null_requirements(fields, details, cda)

    # Build the human-review inventory from the final executable selections.
    # A claim is not removed from the inventory: keeping it visible, with its
    # claimant, prevents a reviewer from silently reusing one physical leaf.
    claimed_by, occurrence_claims = _mapping_target_claims(fields, cda)
    for path, detail in details.items():
        inventory = None
        if detail.get("selected") is None:
            inventory = _possible_target_inventory(
                model_fields.get(path, {}), detail.get("context"), cda,
                claimed_by, occurrence_claims,
            )
        if inventory is not None:
            detail["possible_targets"] = inventory
        else:
            detail.pop("possible_targets", None)

    # Classify the final decision state only after shared-target, occurrence,
    # and compound-datatype passes have had a chance to change executability.
    unresolved_templates = list(cda.get("unresolved_templates", []))
    for path, detail in all_details.items():
        if detail.get("selected") is None and not detail.get("unresolved_reason"):
            detail["unresolved_reason"] = _unresolved_reason(
                detail.get("alternatives", []), detail.get("context")
            )
        gap = _gap_classification(
            path, detail, all_nodes.get(path, {}), unresolved_templates, cda
        )
        if gap is not None:
            detail["gap"] = gap
        else:
            detail.pop("gap", None)

    proposal: dict[str, Any] = {
        "version": 10,
        "model": {
            "dataset_id": model.get("meta", {}).get("dataset_id"),
            "transaction_id": model.get("meta", {}).get("transaction_id"),
            "effective_date": model.get("meta", {}).get("transaction_effective_date"),
        },
        "target": {
            "format": "cda",
            "template": cda.get("document_template", {}).get("name"),
        },
        "fields": fields,
        "field_reviews": {},
        "narratives": {},
        "structures": structures,
        "defaults": {
            "required_unmapped": {"nullFlavor": "NI"},
        },
        "target_defaults": target_defaults,
    }

    return proposal






@localized
def cda_mapping_audit(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    xml_paths: Iterable[Path],
    *,
    output_language: str = "en",
) -> tuple[dict[str, Any], MappingAudit, str, str]:
    """Return proposal, complete structured audit and both reports."""
    paths = list(xml_paths)
    fields, details, groups, members = _mapping_candidates(model, cda, paths)
    proposal = _mapping_admissibility(model, cda, paths, fields, details, groups, members)
    audit = build_mapping_audit(model, cda, proposal, details, groups)
    report, appendix = render_mapping_analysis(model, cda, proposal, details, groups)
    return proposal, audit, report, appendix


def mapping_field_delta(
    baseline: Mapping[str, Any], current: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare executable mappings across proposals or structured audits."""

    def mapped_fields(document: Mapping[str, Any]) -> set[str]:
        result: set[str] = set()
        fields = document.get("fields", {})
        for path, value in fields.items() if isinstance(fields, Mapping) else ():
            selected = (
                value.get("selected")
                if isinstance(value, Mapping) and "selected" in value
                else value
            )
            if selected is not None:
                result.add(str(path))
        return result

    baseline_fields = mapped_fields(baseline)
    current_fields = mapped_fields(current)
    preserved = sorted(baseline_fields & current_fields)
    lost = sorted(baseline_fields - current_fields)
    gained = sorted(current_fields - baseline_fields)
    return {
        "baseline": len(baseline_fields),
        "current": len(current_fields),
        "preserved": preserved,
        "lost": lost,
        "gained": gained,
    }


def _mapping_configuration_notes(
    proposal: Mapping[str, Any],
    audit: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Describe configured evidence that an executable proposal actually uses."""
    selected_templates: dict[str, list[str]] = defaultdict(list)
    selected_fields: set[str] = set()
    targets = cda.get("targets", {})
    for field, selection in proposal.get("fields", {}).items():
        rules = mapping_rules(selection)
        if rules:
            selected_fields.add(str(field))
        for rule in rules:
            target = (
                targets.get(cda_target_name(rule), {})
                if isinstance(targets, Mapping) else {}
            )
            if isinstance(target, Mapping) and target.get("template_id"):
                selected_templates[str(target["template_id"])].append(str(field))
                anchor_name = str(target.get("occurrence_anchor") or "")
                anchor = (
                    targets.get(anchor_name, {})
                    if anchor_name and isinstance(targets, Mapping) else {}
                )
                if isinstance(anchor, Mapping) and anchor.get("template_id"):
                    selected_templates[str(anchor["template_id"])].append(
                        str(field)
                    )

    notes: list[dict[str, Any]] = []
    reviewed = cda.get("reviewed_extensions", [])
    extension_templates = sorted({
        str(extension.get("template_id"))
        for extension in reviewed if isinstance(extension, Mapping)
        and extension.get("template_id") in selected_templates
    })
    if extension_templates:
        fields = sorted({
            field for template in extension_templates
            for field in selected_templates[template]
        })
        notes.append({
            "generated": True,
            "source": "config/cda-extensions.json",
            "note": (
                "Uses reviewed CDA profile-overlay configuration for "
                f"{len(extension_templates)} template(s) in {len(fields)} mapped field(s)."
            ),
            "templates": extension_templates,
            "fields": fields,
        })

    selected_evidence = " ".join(
        str(detail.get("primary") or "")
        for field, detail in audit.get("fields", {}).items()
        if str(field) in selected_fields
        and isinstance(detail, Mapping)
        and detail.get("selected")
    )
    configured_rules = model.get("meta", {}).get("configured_source_rules", [])
    for rule in configured_rules if isinstance(configured_rules, list) else ():
        if not isinstance(rule, Mapping):
            continue
        identifiers = {
            str(rule.get("requested_id") or ""),
            str(rule.get("resolved_id") or ""),
        } - {""}
        template_use = identifiers & set(selected_templates)
        evidence_use = any(identifier in selected_evidence for identifier in identifiers)
        if not template_use and not evidence_use:
            continue
        rule_name = str(rule.get("rule") or "configured source rule")
        notes.append({
            "generated": True,
            "source": "config/sources.json",
            "note": f"Uses {rule_name} while resolving mapping evidence.",
            "artifact": str(rule.get("request_key") or ""),
        })
    return notes


def cda_datapoints(
    cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Build the logical writable CDA datapoints selected by the mapping.

    A physical template target may be repeatable.  Structural rules turn such
    a schema node into distinct logical datapoints—for example right and left
    pupil values—without pretending that the expanded template contains two
    different physical ``value`` elements.
    """
    targets = cda.get("targets", {})
    structures = mapping.get("structures", {})
    result: dict[str, dict[str, Any]] = {}
    for source, selection in mapping.get("fields", {}).items():
        for rule in mapping_rules(selection):
            name = str(rule.get("target") or "")
            physical_name = cda_target_name(rule)
            target = targets.get(physical_name)
            if not name or not isinstance(target, Mapping):
                continue
            datapoint = result.setdefault(name, {
                "cda_target": physical_name,
                "source_key": target.get("source_key"),
                "revisionless_source_key": _revisionless_target_key(target),
                "template_id": target.get("template_id"),
                "template_effective_date": target.get("template_effective_date"),
                "template_name": target.get("template_name"),
                "template_display_name": target.get("template_display_name"),
                "path": target.get("path"),
                "datatype": target.get("datatype"),
                "repeat_ancestors": list(target.get("repeat_ancestors", [])),
                "dataset_fields": [],
            })
            datapoint["dataset_fields"].append(str(source))

            structure_name = str(rule.get("structure") or "")
            structure = (
                structures.get(structure_name, {})
                if structure_name and isinstance(structures, Mapping) else {}
            )
            if isinstance(structure, Mapping) and structure:
                occurrence: dict[str, Any] = {
                    "structure": structure_name,
                    "type": structure.get("type"),
                }
                if rule.get("branch"):
                    occurrence["branch"] = rule["branch"]
                branch = next((
                    item for item in structure.get("branches", [])
                    if isinstance(item, Mapping)
                    and str(item.get("source") or "") == str(source)
                    and str(item.get("target") or "") == name
                ), None)
                if isinstance(branch, Mapping) and branch.get("constants"):
                    occurrence["constants"] = dict(branch["constants"])
                datapoint["occurrence"] = occurrence
    for name, default in mapping.get("target_defaults", {}).items():
        physical_name = str(name)
        target = targets.get(physical_name)
        if not isinstance(target, Mapping) or not isinstance(default, Mapping):
            continue
        datapoint = result.setdefault(physical_name, {
            "cda_target": physical_name,
            "source_key": target.get("source_key"),
            "revisionless_source_key": _revisionless_target_key(target),
            "template_id": target.get("template_id"),
            "template_effective_date": target.get("template_effective_date"),
            "template_name": target.get("template_name"),
            "template_display_name": target.get("template_display_name"),
            "path": target.get("path"),
            "datatype": target.get("datatype"),
            "repeat_ancestors": list(target.get("repeat_ancestors", [])),
            "dataset_fields": [],
        })
        datapoint["default"] = {
            **(
                {"nullFlavor": default.get("nullFlavor")}
                if "nullFlavor" in default else {"value": default.get("value")}
            ),
            **({"reason": default["reason"]} if default.get("reason") else {}),
        }
    return result


def _revisionless_target_key(target: Mapping[str, Any]) -> str:
    """Return the stable owner identity of one compiled ART-DECOR slot."""
    template_id = str(target.get("template_id") or "")
    element_id = str(target.get("element_id") or "")
    path = str(target.get("path") or "")
    if not template_id or not (element_id or path):
        return ""
    return "|".join((
        template_id,
        f"ID:{element_id}" if element_id else "ID:",
        f"PATH:{path}" if path else "PATH:",
    ))


def mapping_target_identities(
    cda: Mapping[str, Any], mapping: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Record owner identities for every target reference in a mapping.

    Human-readable CDA target names are useful review labels but can change
    when a template revision is recompiled.  The exact and revisionless owner
    keys expose exact owner provenance for review.
    """
    targets = cda.get("targets", {})
    datapoints = cda.get("datapoints", {})
    result: dict[str, dict[str, Any]] = {}

    def remember(configured: Any, physical_hint: Any = None) -> None:
        name = str(configured or "")
        physical = str(physical_hint or name)
        logical = (
            datapoints.get(name, {}) if isinstance(datapoints, Mapping) else {}
        )
        if (
            not physical_hint and isinstance(logical, Mapping)
            and logical.get("cda_target")
        ):
            physical = str(logical["cda_target"])
        target = targets.get(physical, {})
        if not name or not isinstance(target, Mapping) or not target:
            return
        identity = {
            "cda_target": physical,
            "source_key": str(target.get("source_key") or ""),
            "revisionless_source_key": _revisionless_target_key(target),
            "template_id": str(target.get("template_id") or ""),
            "template_effective_date": str(
                target.get("template_effective_date") or ""
            ),
            "element_id": str(target.get("element_id") or ""),
            "path": str(target.get("path") or ""),
        }
        previous = result.get(name)
        if previous is not None and previous != identity:
            raise ValueError(
                f"mapping target {name!r} resolves to multiple owner identities"
            )
        result[name] = identity

    for selection in mapping.get("fields", {}).values():
        for rule in mapping_rules(selection):
            remember(rule.get("target"), rule.get("cda_target"))
    narratives = mapping.get("narratives", {})
    if isinstance(narratives, Mapping):
        for name in narratives:
            remember(name)
    structures = mapping.get("structures", {})
    structure_items = (
        structures.values() if isinstance(structures, Mapping) else structures
        if isinstance(structures, list) else []
    )
    for structure in structure_items:
        if not isinstance(structure, Mapping):
            continue
        for key in ("target", "discriminator"):
            if structure.get(key):
                remember(structure[key], structure.get("cda_target"))
        for branch in structure.get("branches", []):
            if not isinstance(branch, Mapping):
                continue
            for key in ("target", "discriminator"):
                if branch.get(key):
                    remember(branch[key], branch.get("cda_target"))
            constants = branch.get("constants", {})
            if isinstance(constants, Mapping):
                for name in constants:
                    remember(name)
        constants = structure.get("constants", {})
        if isinstance(constants, Mapping):
            for name in constants:
                remember(name)
    for name in mapping.get("target_defaults", {}):
        remember(name)
    for name in mapping.get("site_requirements", {}):
        remember(name)
    return dict(sorted(result.items()))


@localized
def write_cda_mapping(
    xml_paths: Iterable[Path],
    model_dir: Path,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> dict[str, Any]:
    """Write the ART-DECOR/model-to-CDA proposal without inspecting CSV input."""
    cda_proposal, audit, _, cda_details = cda_mapping_audit(
        model, cda, xml_paths, output_language=output_language
    )
    cda_proposal["target_identities"] = mapping_target_identities(
        cda, cda_proposal
    )
    cda_proposal["configuration_notes"] = _mapping_configuration_notes(
        cda_proposal, audit, model, cda
    )
    enriched_cda = dict(cda)
    enriched_cda["datapoints"] = cda_datapoints(cda, cda_proposal)
    enriched_cda["version"] = 6
    enriched_cda["stats"] = {
        **dict(cda.get("stats", {})),
        "datapoints": len(enriched_cda["datapoints"]),
    }
    if isinstance(cda, dict):
        cda.clear()
        cda.update(enriched_cda)
    write_json(model_dir / "cda.json", enriched_cda)
    write_json(model_dir / "cda-mapping.proposed.json", cda_proposal)
    write_json(model_dir / "mapping-audit.json", audit)
    (model_dir / "cda-mapping-details.md").write_text(cda_details, encoding="utf-8")
    from .reports import (
        render_cda_mapping_extended_trees_markdown,
        render_cda_mapping_markdown, render_cda_mapping_trees_markdown,
        write_readable_cda,
    )
    cda_report = render_cda_mapping_markdown(
        model, enriched_cda, cda_proposal, audit,
        output_language=output_language,
    )
    (model_dir / "cda-mapping.proposed.md").write_text(
        cda_report, encoding="utf-8"
    )
    tree_report = render_cda_mapping_trees_markdown(
        model, enriched_cda, cda_proposal, audit,
        output_language=output_language,
    )
    (model_dir / "cda-mapping-trees.md").write_text(
        tree_report, encoding="utf-8"
    )
    extended_tree_report = render_cda_mapping_extended_trees_markdown(
        model, enriched_cda, cda_proposal, audit,
        output_language=output_language,
    )
    (model_dir / "cda-mapping-trees-extended.md").write_text(
        extended_tree_report, encoding="utf-8"
    )
    write_readable_cda(
        model_dir, enriched_cda, audit, output_language=output_language
    )
    return cda_proposal
