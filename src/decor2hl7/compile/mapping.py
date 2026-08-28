"""Generate terse mapping proposals and detailed human-readable reports."""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..retrieval.xml import child_text, local, parse_file
from ..workspace import write_json
from ..semantics import (
    accepted_values, direct_compatibility, payload_match,
    transformed_compatibility, type_match,
)
from ..transforms import mapping_rules
from .structural import (
    coalesce_rule as _coalesce_rule,
    fanout_rule as _fanout_rule,
    for_each_rules as _for_each_rules,
    value_set_members as _value_set_members,
)

STRONG_EDGES = {"SPEC", "INHERIT", "ORIGINAL", "EQUIV", "VERSION", "COPY"}
REVERSE_EDGES = {"INHERIT^-1", "ORIGINAL^-1", "SPEC^-1"}
WEAK_EDGES = {"ADAPT", "DRIV", "GEN", "CONTAINS", "REL"}
CONFIDENCE = {"CONTEXT": 0, "WEAK": 1, "MEDIUM": 2, "STRONG": 3}
GENERIC_SHORTNAMES = {
    "zeitpunkt", "zeitraum", "code", "wert", "name", "identifikation",
    "untersuchungsregion", "definitorischer_link", "agens", "status",
    "gultigkeit", "version", "typ", "art",
}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


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
    list[tuple[str, str, str, str]],
    dict[str, str],
]:
    graph: dict[str, set[tuple[str, str]]] = defaultdict(set)
    associations: list[tuple[str, str, str, str]] = []
    names: dict[str, str] = {}
    for root in _all_xml(xml_paths):
        for node in root.iter():
            if local(node.tag) == "concept" and node.get("id"):
                source = node.get("id") or ""
                name = child_text(node, "name")
                if name:
                    names.setdefault(source, name)
                for child in list(node):
                    kind = local(child.tag)
                    if kind == "inherit" and child.get("ref"):
                        graph[source].add(("INHERIT", child.get("ref") or ""))
                        if child.get("originalId"):
                            graph[source].add(("ORIGINAL", child.get("originalId") or ""))
                    elif kind == "relationship" and child.get("ref"):
                        graph[source].add((child.get("type") or "REL", child.get("ref") or ""))
                    elif kind == "contains" and child.get("ref"):
                        graph[source].add(("CONTAINS", child.get("ref") or ""))
            elif local(node.tag) == "templateAssociation" and node.get("templateId"):
                template_id = node.get("templateId") or ""
                effective = node.get("effectiveDate") or ""
                for child in list(node):
                    if local(child.tag) == "concept" and child.get("ref") and child.get("elementId"):
                        associations.append((
                            child.get("ref") or "",
                            template_id,
                            effective,
                            child.get("elementId") or "",
                        ))
    reverse: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for source, edges in graph.items():
        for kind, target in edges:
            if kind in {"INHERIT", "ORIGINAL", "SPEC"}:
                reverse[target].add((kind + "^-1", source))
    for source, edges in reverse.items():
        graph[source].update(edges)
    return graph, associations, names


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
                template_id = ""; effective = ""; template_xpath = ""
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
            if target_path != relative and not full.endswith("/" + target_path):
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
        for oid in target.get("value_sets", []):
            by_vs[str(oid)].append((name, target))
        for code in target.get("codes", []):
            if code.get("code") and code.get("code_system"):
                by_code[(str(code["code"]), str(code["code_system"]))].append((name, target))
    return by_vs, by_code, by_template


def _type_match(model_type: str, cda_type: str | None) -> bool:
    return type_match(model_type, cda_type)


def _is_payload(model_type: str, target: Mapping[str, Any]) -> bool:
    return payload_match(model_type, target)


def _direct(field: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[bool, list[str]]:
    if not field.get("type"):
        return True, []
    return direct_compatibility(field, target)


def _lineage(
    start: str, graph: Mapping[str, set[tuple[str, str]]], depth: int = 8
) -> list[tuple[str, list[tuple[str, str]]]]:
    result = [(start, [])]
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
    if any(edge in WEAK_EDGES or edge not in STRONG_EDGES | REVERSE_EDGES | WEAK_EDGES for edge in kinds):
        return "WEAK"
    if version_shift or any(edge in REVERSE_EDGES for edge in kinds):
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
) -> dict[str, Any]:
    return {
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


def _ta_candidates(
    field: Mapping[str, Any],
    graph: Mapping[str, set[tuple[str, str]]],
    associations: list[tuple[str, str, str, str]],
    concept_names: Mapping[str, str],
    cda: Mapping[str, Any],
) -> list[dict[str, Any]]:
    association_index: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for concept, template_id, effective, element_id in associations:
        association_index[concept].append((template_id, effective, element_id))
    source_index = cda.get("source_index", {})
    targets = cda.get("targets", {})
    concept_id = str(field.get("concept") or "")
    result: list[dict[str, Any]] = []
    for related, path in _lineage(concept_id, graph):
        for template_id, effective, element_id in association_index.get(related, []):
            names = list(source_index.get(f"{template_id}|ID:{element_id}", []))
            if not names:
                names = [
                    name for name, target in targets.items()
                    if target.get("renderable", True)
                    and str(target.get("template_id") or "") == template_id
                    and str(target.get("element_id") or "") == element_id
                ]
            for name in names:
                target = targets.get(name, {})
                if (not target or not target.get("renderable", True) or target.get("prohibited")
                        or len(target.get("locations", [])) != 1):
                    continue
                specialization = str(target.get("template_id") or "") != template_id
                version_shift = (
                    not specialization and bool(effective)
                    and bool(target.get("template_effective_date"))
                    and str(target.get("template_effective_date")) != effective
                )
                confidence = _edge_confidence(path, version_shift or specialization)
                score = 100
                for edge, _ in path:
                    score -= 25 if edge in WEAK_EDGES else 12 if edge in REVERSE_EDGES else 3
                if version_shift:
                    score -= 8
                if specialization:
                    score -= 6
                chain = [edge for edge, _ in path]
                chain.append("TA_SPEC" if specialization else "TA_VERSION" if version_shift else "TA")
                actionable, direct_warnings = _direct(field, target)
                warnings: list[str] = list(direct_warnings)
                if not actionable:
                    warnings.insert(0, "requires transform or a different CDA payload")
                if any(edge in WEAK_EDGES for edge, _ in path) and not _names_agree(
                    str(field.get("name") or ""), concept_names.get(related)
                ):
                    # Keep the weak mapping (user preference), but make semantic
                    # drift visible and lower its rank.
                    score -= 20
                    warnings.append("lineage name drift")
                result.append(_candidate(
                    name,
                    target,
                    chain,
                    confidence,
                    score,
                    kind="TA",
                    actionable=actionable,
                    via=related,
                    via_name=concept_names.get(related),
                    warnings=warnings,
                ))
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
        containers = [
            item for item in candidates
            if not item[1].get("datatype")
            and re.search(
                r"(section|observation|act|procedure|organizer|substanceAdministration|supply|encounter)$",
                str(item[1].get("path") or ""),
            )
        ]
        pool = containers or [item for item in candidates if not item[1].get("datatype")]
        return min(pool, key=lambda item: len(str(item[1].get("path") or ""))) if pool else None
    typed = [
        item for item in candidates
        if _is_payload(model_type, item[1]) and _type_match(model_type, item[1].get("datatype"))
    ]
    if typed:
        return min(typed, key=lambda item: len(str(item[1].get("path") or "")))
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
    value_sets = {str(value) for value in field.get("value_sets", [])}
    terms = {
        (str(code.get("code")), str(code.get("code_system")))
        for code in field.get("codes", [])
        if code.get("code") and code.get("code_system")
    }

    vs_hits: list[tuple[str, Mapping[str, Any], str]] = []
    for oid in value_sets:
        for name, target in by_vs.get(oid, []):
            vs_hits.append((name, target, oid))
            actionable, warnings = _direct(field, target)
            result.append(_candidate(
                name, target, [f"VS({oid})"], "WEAK", 55, kind="VS",
                actionable=actionable, warnings=warnings,
            ))

    term_hits: list[tuple[str, Mapping[str, Any], tuple[str, str]]] = []
    term_by_template: dict[str, list[tuple[str, Mapping[str, Any], tuple[str, str]]]] = defaultdict(list)
    for term in terms:
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
        if "positive" in classes.values() and "negative" in classes.values():
            for tid, confidence in template_ids:
                negations = [
                    (name, target) for name, target in targets.items()
                    if target.get("renderable") and len(target.get("locations", [])) == 1
                    and str(target.get("template_id") or "") == tid
                    and str(target.get("path") or "").endswith("/@negationInd")
                ]
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
                        name for name, target in targets.items()
                        if target.get("renderable") and len(target.get("locations", [])) == 1
                        and str(target.get("template_id") or "") == tid
                        and str(target.get("path") or "").endswith("/@nullFlavor")
                    ]
                    if len(nulls) == 1:
                        null_map = {label: ("NI" if label in unknown else None) for label in options}
                        rules.append({"target": nulls[0], "transform": {"type": "enum", "map": null_map}})
                result.append(_candidate(
                    neg_name, neg_target,
                    ["SEMANTIC_STATE", "TRANSFORM(enum→negationInd)"],
                    confidence, 78 if confidence == "MEDIUM" else 62,
                    kind="TRANSFORM", actionable=True, mapping=rules,
                    warnings=["generated from dataset state labels and CDA negation semantics"],
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
            numeric = [
                (name, target) for name, target in targets.items()
                if target.get("renderable") and len(target.get("locations", [])) == 1
                and str(target.get("template_id") or "") == tid
                and str(target.get("path") or "").endswith("/hl7:value")
                and str(target.get("datatype") or "").upper().split(".", 1)[0] in {"PQ", "INT", "REAL"}
            ]
            if len(numeric) != 1:
                continue
            name, target = numeric[0]
            rule = {"target": name, "transform": {"type": "ordinal", "map": ordinal_map}}
            compatible, reasons = transformed_compatibility(field, target, rule["transform"])
            if compatible:
                result.append(_candidate(
                    name, target,
                    ["TERM/TEMPLATE", "TRANSFORM(ordinal→score)"],
                    "MEDIUM" if locator_confidence in {"MEDIUM", "STRONG"} else "WEAK",
                    76, kind="TRANSFORM", actionable=True, mapping=rule,
                    warnings=["ordinal score derived from dataset option synonyms"]
                ))
                break
    return result


def _candidates(
    path: str,
    field: Mapping[str, Any],
    graph: Mapping[str, set[tuple[str, str]]],
    associations: list[tuple[str, str, str, str]],
    concept_names: Mapping[str, str],
    implementations: Mapping[str, list[dict[str, str]]],
    cda: Mapping[str, Any],
    indexes: tuple[
        dict[str, list[tuple[str, Mapping[str, Any]]]],
        dict[tuple[str, str], list[tuple[str, Mapping[str, Any]]]],
        dict[str, list[tuple[str, Mapping[str, Any]]]],
        dict[str, set[str]],
    ],
) -> list[dict[str, Any]]:
    by_vs, by_code, by_template, name_index = indexes
    result = _implementation_candidates(field, implementations, cda)
    result.extend(_ta_candidates(field, graph, associations, concept_names, cda))
    result.extend(_name_candidates(path, field, cda, by_template, name_index))
    result.extend(_description_candidates(field, cda))
    result.extend(_vocabulary_candidates(field, by_vs, by_code, by_template))
    result.extend(_semantic_transform_candidates(field, list(result), cda))
    return _deduplicate(result)


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
                }
        parent = groups.get(str(parent), {}).get("parent")
    return None


def _context(
    path: str,
    model: Mapping[str, Any],
    group_results: Mapping[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return _context_for_node(
        model["fields"][path], model.get("groups", {}), group_results
    )


def _certainty_mapping(
    path: str,
    field: Mapping[str, Any],
    cda: Mapping[str, Any],
    value_sets: Mapping[str, list[dict[str, str]]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Recognize a V/A/Z/G diagnosis-certainty field and its CDA qualifier."""
    aliases: dict[str, str] = {}
    for label, info in accepted_values(field).items():
        detail = info if isinstance(info, Mapping) else {}
        candidates = [str(label)] + [str(value) for value in detail.get("synonyms", [])]
        code = next((value.upper() for value in candidates if value.upper() in {"V", "A", "Z", "G"}), None)
        if code:
            for value in candidates:
                aliases[value] = code
    if set(aliases.values()) != {"V", "A", "Z", "G"}:
        return None

    candidates: list[
        tuple[str, Mapping[str, Any], str, dict[str, dict[str, str]]]
    ] = []
    for name, target in cda.get("targets", {}).items():
        if not target.get("renderable") or len(target.get("locations", [])) != 1:
            continue
        for oid in target.get("value_sets", []):
            members = value_sets.get(str(oid), [])
            by_code = {
                str(member.get("code") or "").upper(): dict(member)
                for member in members
            }
            if {"V", "A", "Z", "G"} <= set(by_code):
                candidates.append((str(name), target, str(oid), by_code))
    if len(candidates) != 1:
        return None
    target_name, target, value_set_oid, members = candidates[0]
    repeat_ancestors = target.get("repeat_ancestors", [])
    template_words = _words(
        " ".join(str(field.get(key) or "") for key in ("name", "description", "implementation"))
    ) | {"diagnos", "diagnose"}

    def sibling(suffix: str) -> str | None:
        rows: list[tuple[int, str]] = []
        for name, candidate in cda.get("targets", {}).items():
            if not candidate.get("renderable") or candidate.get("repeat_ancestors", []) != repeat_ancestors:
                continue
            if not str(candidate.get("path") or "").endswith(suffix):
                continue
            label = f"{candidate.get('template_name') or ''} {candidate.get('template_display_name') or ''} {name}"
            rows.append((len(template_words & _words(label)), str(name)))
        rows.sort(reverse=True)
        return rows[0][1] if rows and (len(rows) == 1 or rows[0][0] > rows[1][0]) else None

    enum_map = {alias: members[code] for alias, code in aliases.items()}
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
    high = sibling("/hl7:effectiveTime/hl7:high")
    if high:
        rules.append({
            "target": high,
            "mode": "fallback",
            "transform": {
                "type": "enum", "select": "raw",
                "map": {alias: {"nullFlavor": "UNK"} for alias, code in aliases.items() if code == "Z"},
            },
        })
    primary = _candidate(
        target_name, target,
        ["LOGICAL(V/A/Z/G)", f"VS({value_set_oid})", "TRANSFORM(certainty)"],
        "MEDIUM", 105, kind="TRANSFORM", actionable=True, mapping=rules,
        warnings=["diagnosis certainty is normalized into the formal CDA qualifier vocabulary"],
    )
    return {"mapping": rules, "primary": primary}, {"aliases": aliases}


def _cda_mapping_analysis(
    model: Mapping[str, Any], cda: Mapping[str, Any], xml_paths: Iterable[Path]
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    xml_paths = list(xml_paths)
    graph, associations, concept_names = _graph_and_associations(xml_paths)
    implementations = _implementation_paths(xml_paths)
    indexes = _mapping_indexes(cda)
    details: dict[str, dict[str, Any]] = {}
    group_results: dict[str, dict[str, Any]] = {}
    groups = model.get("groups", {})
    model_fields = model.get("fields", {})

    # Groups are not written to cda-mapping.json, but they are real dataset
    # datapoints and provide structural evidence/context for their descendants.
    for group_path, group in groups.items():
        group_candidates = _candidates(
            group_path, group, graph, associations, concept_names, implementations, cda, indexes
        )
        actionable = [row for row in group_candidates if row["actionable"]]
        group_results[group_path] = {
            "selected": actionable[0]["target"] if actionable else None,
            "primary": actionable[0] if actionable else None,
            "alternatives": [row for row in group_candidates if not actionable or row is not actionable[0]][:8],
            "context": None,
        }

    # Context is inherited structurally from the nearest mapped group.  Process
    # shallow groups first so a child may use its parent's contextual placement.
    for group_path in sorted(groups, key=lambda value: value.count(".")):
        result = group_results[group_path]
        if result["primary"] is None:
            result["context"] = _context_for_node(groups[group_path], groups, group_results)

    fields: dict[str, Any] = {}
    for path, field in model_fields.items():
        candidates = _candidates(path, field, graph, associations, concept_names, implementations, cda, indexes)
        actionable = [row for row in candidates if row["actionable"]]
        primary = actionable[0] if actionable else None
        fields[path] = (primary.get("mapping") if primary and primary.get("mapping") is not None else primary["target"] if primary else None)
        details[path] = {
            "selected": fields[path],
            "primary": primary,
            "alternatives": [row for row in candidates if row is not primary][:8],
            "context": None,
        }

    value_set_members = _value_set_members(xml_paths)
    for path, field in model_fields.items():
        certainty = _certainty_mapping(path, field, cda, value_set_members)
        if certainty is None:
            continue
        selection, metadata = certainty
        old_primary = details[path].get("primary")
        if old_primary is not None:
            details[path]["alternatives"] = [old_primary] + list(details[path].get("alternatives", []))
        details[path]["primary"] = selection["primary"]
        details[path]["selected"] = selection["mapping"]
        details[path]["semantic_transform"] = metadata
        fields[path] = selection["mapping"]

    for path in model_fields:
        if details[path]["primary"] is None:
            details[path]["context"] = _context(path, model, group_results)

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
                if rule.get("mode") != "fallback"
            ] or [primary["target"]]
            for target_name in primary_targets:
                claims[target_name].append(path)
                if path in model_fields:
                    field_claims[target_name].append(path)

    structures: dict[str, dict[str, Any]] = {}

    # Shared targets become executable only when their occurrence semantics are
    # explicit.  Repeat fan-out requires a terminology-backed discriminator;
    # singleton coalescing uses the conservative equal-or-error policy.
    for target_name, paths in field_claims.items():
        if len(paths) <= 1:
            continue
        resolved = _fanout_rule(paths, target_name, model, cda, value_set_members)
        if resolved is None:
            resolved = _coalesce_rule(paths, target_name, model, cda)
        if resolved is not None:
            rule_name, rule = resolved
            structures[rule_name] = rule
            branch_names = {
                str(branch.get("source")): str(branch.get("branch") or "")
                for branch in rule.get("branches", []) if isinstance(branch, Mapping)
            }
            for path in paths:
                fields[path] = {
                    "target": target_name,
                    "structure": rule_name,
                    **({"branch": branch_names[path]} if path in branch_names else {}),
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
            details[winner]["shared_target_winner"] = True
            continue
        for path in paths:
            fields[path] = None
            details[path]["selected"] = None
            details[path]["runtime_blocked"] = f"SHARED({len(paths)})"

    structures.update(_for_each_rules(model, cda, fields))

    proposal = {
        "version": 3,
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
        "structures": structures,
    }

    def coverage(detail: Mapping[str, Any]) -> str:
        if detail.get("primary"):
            return "YES"
        if detail.get("context"):
            return "PARTIAL"
        return "NO"

    def mapping_qualification(
        detail: Mapping[str, Any], primary: Mapping[str, Any]
    ) -> str:
        close = {
            alt["target"] for alt in detail.get("alternatives", [])
            if alt.get("actionable") and alt["target"] != primary["target"]
            and alt["score"] >= primary["score"] - 5
        }
        if close:
            return f"MULTIPLE({len(close) + 1})"
        indirect_tokens = {
            "INHERIT^-1", "ORIGINAL^-1", "SPEC^-1", "TA_VERSION", "TA_SPEC"
        }
        if primary.get("confidence") == "STRONG" and not any(
            token in indirect_tokens for token in primary.get("chain", [])
        ):
            return "EXACT"
        return "INDIRECT"

    def target_datatype(name: str) -> str:
        return str(cda.get("targets", {}).get(name, {}).get("datatype") or "—")

    def evidence(candidate: Mapping[str, Any]) -> str:
        return " → ".join(str(item) for item in candidate.get("chain", [])) or str(candidate.get("kind") or "—")

    def reason_for(path: str, detail: Mapping[str, Any]) -> str:
        primary = detail.get("primary")
        if primary:
            blocked = detail.get("runtime_blocked")
            if blocked:
                return (
                    "The best CDA target is supported by mapping evidence, but it is shared "
                    "with another dataset field and therefore needs an explicit rule before execution."
                )
            if detail.get("structural_rule"):
                return (
                    "The CDA target is supported by mapping evidence and the shared occurrence "
                    f"semantics are made explicit by structural rule `{detail['structural_rule']}`."
                )
            if primary.get("mapping") is not None:
                return (
                    "The datapoint and CDA target represent the same information with different "
                    "representations, so a declarative transform is required."
                )
            kind = str(primary.get("kind") or "")
            reasons = {
                "XPATH": "An explicit ART-DECOR implementation XPath identifies this CDA target.",
                "TA": "A formal template association connects the datapoint lineage to this CDA element.",
                "TERM+VS": "Terminology locates the CDA template and compatible value-set evidence identifies the target.",
                "TERM+DT": "Terminology locates the CDA template and datatype compatibility identifies its unique payload.",
                "TERM": "Compatible terminology provides an indirect bridge to this CDA target.",
                "NAME": "A unique semantic template-name match provides the bridge to this CDA target.",
                "DESC": "Published descriptions provide a semantic bridge to this CDA target.",
                "TRANSFORM": "CDA semantics match, but the dataset value must be transformed before rendering.",
            }
            text = reasons.get(kind, "The available ART-DECOR evidence identifies this as the best CDA target.")
            if primary.get("confidence") == "WEAK":
                text += " The evidence is indirect, so the selection should be reviewed."
            qualification = mapping_qualification(detail, primary)
            if qualification.startswith("MULTIPLE("):
                text += " Another actionable target has a comparable score."
            if primary.get("warnings"):
                text += " Warning: " + "; ".join(str(item) for item in primary["warnings"]) + "."
            return text
        if detail.get("context"):
            return (
                "No executable CDA element could be established; the nearest mapped structural "
                "group supplies only contextual placement."
            )
        if detail.get("alternatives"):
            return "Candidate evidence exists, but none is safe enough to become an executable mapping automatically."
        return "No usable CDA target evidence was found for this datapoint."

    def status_for(path: str, detail: Mapping[str, Any]) -> str:
        primary = detail.get("primary")
        if not primary:
            return "PARTIAL · CONTEXT · NOT EXECUTABLE" if detail.get("context") else "NO · NOT EXECUTABLE"
        qualification = mapping_qualification(detail, primary)
        if detail.get("runtime_blocked"):
            execution = "REQUIRES RULE"
        elif primary.get("mapping") is not None:
            execution = "TRANSFORM"
        elif path in model_fields and fields.get(path) is not None:
            execution = "EXECUTABLE"
        else:
            execution = "EVIDENCE ONLY"
        return f"YES · {primary.get('confidence')} · {qualification} · {execution}"

    def candidate_rows(path: str, detail: Mapping[str, Any], limit: int) -> list[tuple[Mapping[str, Any], str]]:
        rows: list[tuple[Mapping[str, Any], str]] = []
        primary = detail.get("primary")
        if primary:
            result = "SELECTED"
            if detail.get("runtime_blocked"):
                result = "SELECTED / REQUIRES RULE"
            elif primary.get("mapping") is not None:
                result = "SELECTED / TRANSFORM"
            rows.append((primary, result))
        for alt in detail.get("alternatives", []):
            if len(rows) >= limit:
                break
            rows.append((alt, "alternative" if alt.get("actionable") else "evidence only"))
        if not rows and detail.get("context"):
            context = detail["context"]
            rows.append(({
                "target": context.get("target"), "confidence": "CONTEXT",
                "chain": context.get("chain", []), "actionable": False, "score": 0,
                "warnings": [],
            }, "context only"))
        return rows

    def field_section(path: str, *, detailed: bool) -> list[str]:
        field = model_fields[path]
        detail = details[path]
        primary = detail.get("primary")
        short = str(field.get("concept") or "").rsplit(".", 1)[-1]
        heading = f"## {field.get('name') or path}" + (f" [{short}]" if short else "")
        out = [heading, "", f"`{path}`", "", f"**{status_for(path, detail)}**", ""]
        if primary:
            selected = detail.get("selected")
            if selected is None:
                selected = primary.get("mapping") if primary.get("mapping") is not None else primary.get("target")
            if primary.get("mapping") is not None:
                out += ["**Selected:**", "", f"`{primary.get('target')}` `[{target_datatype(str(primary.get('target')))}]` with declarative transform", ""]
            else:
                out += ["**Selected:**", "", f"`{primary.get('target')}` `[{target_datatype(str(primary.get('target')))}]`", ""]
            if detail.get("structural_rule"):
                out += ["**Structural rule:**", "", f"`{detail['structural_rule']}`", ""]
        elif detail.get("context"):
            out += ["**Context:**", "", f"`{detail['context'].get('target')}`", ""]
        else:
            out += ["**Selected:** none", ""]

        out += ["**Reason:**", "", reason_for(path, detail), ""]

        rows = candidate_rows(path, detail, 8 if detailed else 5)
        if rows:
            if detailed:
                out += ["### Candidates", "", "| Target | Datatype | Confidence | Evidence | Score | Result |", "|---|---|---|---|---:|---|"]
            else:
                out += ["**Candidates:**", "", "| Target | Datatype | Confidence | Evidence | Result |", "|---|---|---|---|---|"]
            for candidate, result in rows:
                name = str(candidate.get("target") or "—").replace("|", "\\|")
                confidence_text = str(candidate.get("confidence") or "—")
                evidence_text = evidence(candidate).replace("|", "\\|")
                dtype = target_datatype(str(candidate.get("target") or ""))
                if detailed:
                    out.append(f"| `{name}` | `{dtype}` | {confidence_text} | {evidence_text} | {candidate.get('score', 0)} | {result} |")
                else:
                    out.append(f"| `{name}` | `{dtype}` | {confidence_text} | {evidence_text} | {result} |")
            out.append("")

        if detailed and primary:
            target = cda.get("targets", {}).get(primary.get("target"), {})
            out += ["### Evidence chain", ""]
            concept = str(field.get("concept") or "")
            if concept:
                out.append(f"- Dataset concept: `{concept}`")
            out.append(f"- Bridge: `{evidence(primary)}`")
            if primary.get("via") and str(primary.get("via")) != concept:
                via_name = f" — {primary.get('via_name')}" if primary.get("via_name") else ""
                out.append(f"- Via concept: `{primary.get('via')}`{via_name}")
            if target.get("template_id"):
                out.append(
                    f"- Template: `{target.get('template_name') or ''}` — `{target.get('template_id')}` "
                    f"@ `{target.get('template_effective_date') or 'dynamic'}`"
                )
            if target.get("element_id") or target.get("element_name"):
                out.append(f"- Element: `{target.get('element_name') or ''}` — `{target.get('element_id') or ''}`")
            if target.get("path"):
                out.append(f"- CDA path: `{target.get('path')}`")
            if target.get("datatype"):
                out.append(f"- CDA datatype: `{target.get('datatype')}`")
            if primary.get("warnings"):
                out.append("- Warnings: " + "; ".join(str(item) for item in primary["warnings"]))
            out.append("")

        qualification = mapping_qualification(detail, primary) if primary else ""
        suggestions: list[str] = []
        if not primary:
            if detail.get("alternatives"):
                suggestions.append("Review the candidates and set the intended target in `cda-mapping.json`, or leave the field explicitly `null`.")
            elif detail.get("context"):
                suggestions.append("Use the contextual target to navigate the CDA structure, then choose an actual value-bearing element or leave the field unmapped.")
            else:
                suggestions.append("Find the intended CDA representation manually or leave the field explicitly `null`.")
        else:
            if detail.get("runtime_blocked"):
                suggestions.append("Define an explicit merge/repetition rule before enabling this mapping.")
            if primary.get("confidence") == "WEAK":
                suggestions.append("Verify the selected target because the evidence is indirect.")
            if qualification.startswith("MULTIPLE("):
                suggestions.append("Compare the similarly ranked candidates before accepting the selection.")
            if primary.get("mapping") is not None:
                suggestions.append("Verify the generated transform and its value mapping before use.")
        if suggestions:
            out += ["**Suggested action:**", "", " ".join(suggestions), ""]
        return out

    all_coverage = Counter(coverage(detail) for detail in all_details.values())
    item_coverage = Counter(coverage(detail) for detail in details.values())
    group_coverage = Counter(coverage(detail) for detail in group_results.values())
    required_paths = [path for path, field in model_fields.items() if field.get("required")]
    required_coverage = Counter(coverage(details[path]) for path in required_paths)
    qualifications = Counter()
    location_ambiguities = 0
    for detail in all_details.values():
        primary = detail.get("primary")
        if primary:
            qualifications[mapping_qualification(detail, primary)] += 1
            target = cda.get("targets", {}).get(primary["target"], {})
            if len(target.get("locations", [])) > 1:
                location_ambiguities += 1
        elif detail.get("context"):
            qualifications["PARTIAL"] += 1
        else:
            qualifications["NO_CDA"] += 1

    confidence = Counter(
        detail["primary"]["confidence"] if detail.get("primary") else "NO"
        for detail in all_details.values()
    )
    bridge = Counter(
        detail["primary"]["kind"] if detail.get("primary") else "NONE"
        for detail in all_details.values()
    )

    report_lines = [
        "# CDA Mapping",
        "",
        "This is the working report for completing `cda-mapping.json`. It shows the selected target,",
        "why it was selected, and the strongest alternatives. Full provenance is in",
        "`cda-mapping-details.md`.",
        "",
        "**Legend:** `YES` = concrete CDA evidence; `PARTIAL` = structural context only;",
        "`STRONG`/`MEDIUM`/`WEAK` describe evidence confidence independently from executability.",
        "",
    ]
    field_order = [path for path in model.get("order", []) if path in model_fields]
    if not field_order:
        field_order = sorted(model_fields)
    for path in field_order:
        report_lines.extend(field_section(path, detailed=False))

    detail_lines = [
        "# CDA Mapping Details",
        "",
        f"Target CDA template: `{cda.get('document_template', {}).get('id')}` @ "
        f"`{cda.get('document_template', {}).get('effective_date')}`",
        f"Transaction: `{model.get('meta', {}).get('transaction_id')}` "
        f"({model.get('meta', {}).get('name') or ''})",
        "",
        "```text",
        f"Dataset datapoints:  {len(all_details):>4}",
        f"CDA covered:         {all_coverage['YES']:>4}",
        f"Partial:             {all_coverage['PARTIAL']:>4}",
        f"Not covered:         {all_coverage['NO']:>4}",
        "",
        f"Items:      YES {item_coverage['YES']}, PARTIAL {item_coverage['PARTIAL']}, NO {item_coverage['NO']}",
        f"Groups:     YES {group_coverage['YES']}, PARTIAL {group_coverage['PARTIAL']}, NO {group_coverage['NO']}",
        f"Required items: YES {required_coverage['YES']}, PARTIAL {required_coverage['PARTIAL']}, NO {required_coverage['NO']}",
        "",
        f"Reachable templates:  {cda.get('stats', {}).get('reachable_templates', 0):>4}",
        f"Named CDA targets:    {cda.get('stats', {}).get('targets', 0):>4}",
        f"Renderable targets:   {cda.get('stats', {}).get('renderable_targets', 0):>4}",
        f"Evidence-linked items:{sum(bool(details[path].get('primary') or details[path].get('alternatives')) for path in model_fields):>5}",
        f"Executable proposal:  {sum(value is not None for value in fields.values()):>4}",
        f"Unresolved templates: {len(cda.get('unresolved_templates', [])):>4}",
        "```",
        "",
        "## Summary by evidence",
        "",
        "### Qualification",
        "",
    ]
    for key in ("EXACT", "INDIRECT", "PARTIAL", "NO_CDA"):
        if qualifications[key]:
            detail_lines.append(f"- {key}: {qualifications[key]}")
    for key in sorted(k for k in qualifications if k.startswith("MULTIPLE(")):
        detail_lines.append(f"- {key}: {qualifications[key]}")
    if location_ambiguities:
        detail_lines.append(f"- LOCATION_AMBIGUITY: {location_ambiguities}")
    detail_lines += ["", "### Primary evidence", ""]
    for key, count in bridge.most_common():
        detail_lines.append(f"- {key}: {count}")
    detail_lines += ["", "### Confidence", ""]
    for key in ("STRONG", "MEDIUM", "WEAK", "NO"):
        if confidence[key]:
            detail_lines.append(f"- {key}: {confidence[key]}")
    detail_lines.append("")

    if structures:
        detail_lines += ["## Executable structural rules", ""]
        for name, rule in structures.items():
            detail_lines.append(f"- `{name}` — `{rule.get('type')}`")
            for item in rule.get("evidence", []):
                detail_lines.append(f"  - {item}")
        detail_lines.append("")

    if cda.get("unresolved_templates"):
        detail_lines += ["## Unresolved template references", ""]
        for unresolved in cda.get("unresolved_templates", []):
            relation = unresolved.get("relation") or "REF"
            template = unresolved.get("template") or ""
            flexibility = unresolved.get("flexibility") or "dynamic"
            detail_lines.append(f"- `{relation}` → `{template}` @ `{flexibility}`")
        detail_lines.append("")

    detail_lines += ["# Datapoint analysis", ""]
    for path in field_order:
        detail_lines.extend(field_section(path, detailed=True))

    if group_results:
        detail_lines += ["# Structural group context", ""]
        group_order = [path for path in model.get("order", []) if path in group_results]
        if not group_order:
            group_order = sorted(group_results)
        for path in group_order:
            group = groups[path]
            detail = group_results[path]
            short = str(group.get("concept") or "").rsplit(".", 1)[-1]
            detail_lines += [
                f"## {group.get('name') or path}" + (f" [{short}]" if short else ""),
                "",
                f"`{path}`",
                "",
            ]
            if detail.get("primary"):
                primary = detail["primary"]
                detail_lines += [
                    f"**YES · {primary.get('confidence')} · {mapping_qualification(detail, primary)}**",
                    "",
                    f"→ `{primary.get('target')}`",
                    "",
                    f"Evidence: `{evidence(primary)}`",
                    "",
                ]
            elif detail.get("context"):
                detail_lines += ["**PARTIAL · CONTEXT**", "", f"→ `{detail['context'].get('target')}`", ""]
            else:
                detail_lines += ["**NO**", ""]

    def audit_candidate(
        candidate: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if candidate is None:
            return None
        # ``node`` is an internal XML element used while matching. It is not
        # serializable and the persisted evidence already contains its stable
        # identity and path.
        return {str(key): value for key, value in candidate.items() if key != "node"}

    def audit_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "selected": detail.get("selected"),
            "primary": audit_candidate(detail.get("primary")),
            "alternatives": [
                audit_candidate(candidate)
                for candidate in detail.get("alternatives", [])
            ],
            "context": detail.get("context"),
            **(
                {"runtime_blocked": detail["runtime_blocked"]}
                if detail.get("runtime_blocked") else {}
            ),
            **(
                {"structural_rule": detail["structural_rule"]}
                if detail.get("structural_rule") else {}
            ),
            **(
                {"shared_target_winner": True}
                if detail.get("shared_target_winner") else {}
            ),
        }

    audit = {
        "version": 1,
        "model": dict(proposal["model"]),
        "target": dict(proposal["target"]),
        "fields": {
            path: audit_detail(detail) for path, detail in details.items()
        },
        "groups": {
            path: audit_detail(detail) for path, detail in group_results.items()
        },
        "structures": structures,
        "unresolved_templates": list(cda.get("unresolved_templates", [])),
        "summary": {
            "datapoints": len(all_details),
            "coverage": dict(all_coverage),
            "field_coverage": dict(item_coverage),
            "group_coverage": dict(group_coverage),
            "confidence": dict(confidence),
            "primary_evidence": dict(bridge),
            "executable_fields": sum(value is not None for value in fields.values()),
            "shared_target_blocks": sum(
                bool(detail.get("runtime_blocked")) for detail in details.values()
            ),
            "structural_rules": Counter(
                str(rule.get("type") or "unknown") for rule in structures.values()
            ),
        },
    }
    return (
        proposal,
        audit,
        "\n".join(report_lines) + "\n",
        "\n".join(detail_lines) + "\n",
    )


def cda_mapping_reports(
    model: Mapping[str, Any], cda: Mapping[str, Any], xml_paths: Iterable[Path]
) -> tuple[dict[str, Any], str, str]:
    """Return the editable proposal and both human-readable reports."""
    proposal, _, report, details = _cda_mapping_analysis(model, cda, xml_paths)
    return proposal, report, details


def cda_mapping_audit(
    model: Mapping[str, Any], cda: Mapping[str, Any], xml_paths: Iterable[Path]
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Return proposal, complete structured audit and both reports."""
    return _cda_mapping_analysis(model, cda, xml_paths)


def cda_mapping_proposal(
    model: Mapping[str, Any], cda: Mapping[str, Any], xml_paths: Iterable[Path]
) -> tuple[dict[str, Any], str]:
    """Backward-compatible proposal API returning the user-facing report."""
    proposal, report, _ = cda_mapping_reports(model, cda, xml_paths)
    return proposal, report


def _headers(input_dir: Path | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if input_dir is None or not input_dir.exists():
        return out
    for path in sorted(input_dir.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(handle, dialect)
            out[path.stem] = next(reader, [])
    return out


def _best_column(path: str, field: Mapping[str, Any], headers: Mapping[str, list[str]]) -> tuple[str | None, float, list[tuple[float, str]]]:
    needles = {_norm(path.rsplit(".", 1)[-1]), _norm(str(field.get("name") or ""))}
    scored: list[tuple[float, str]] = []
    for source, columns in headers.items():
        for column in columns:
            norm = _norm(column)
            if not norm:
                continue
            score = max(difflib.SequenceMatcher(None, needle, norm).ratio() for needle in needles if needle)
            if norm in needles:
                score = 1.0
            scored.append((score, f"{source}:{column}"))
    scored.sort(reverse=True)
    if not scored:
        return None, 0.0, []
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    selected = best[1] if best[0] >= 0.78 and (best[0] - second >= 0.05 or best[0] == 1.0) else None
    return selected, best[0], scored[:5]


def csv_mapping_proposal(model: Mapping[str, Any], input_dir: Path | None, join_column: str) -> tuple[dict[str, Any], str]:
    headers = _headers(input_dir)
    fields: dict[str, Any] = {}
    detail: dict[str, tuple[float, list[tuple[float, str]]]] = {}
    for path, field in model.get("fields", {}).items():
        selected, score, candidates = _best_column(path, field, headers)
        value: Any = selected
        semantic_text = " ".join(str(field.get(key) or "") for key in (
            "name", "short_name", "description", "comment", "implementation",
        )).casefold()
        boolean_rank = (
            selected is not None
            and str(field.get("type") or "") == "integer"
            and (field.get("min_value") is None or float(field.get("min_value")) >= 1)
            and ("führende" in semantic_text or "fuehrende" in semantic_text or "hauptdiagnose" in semantic_text)
            and ("sequenz" in semantic_text or "rank" in semantic_text or "führende" in semantic_text)
        )
        if boolean_rank and selected:
            observed = {item.casefold() for item in _read_column_values(input_dir, selected) if item.strip()}
            boolean_literals = {"0", "1", "true", "false", "yes", "no", "ja", "nein", "j", "n"}
            if observed and observed <= boolean_literals:
                source, column = selected.split(":", 1)
                value = {
                    "source": source,
                    "column": column,
                    "parse_as": "boolean",
                    "transform": {
                        "type": "enum",
                        "select": "value",
                        "map": {"true": 1, "false": None},
                    },
                }
        fields[path] = value
        detail[path] = score, candidates
    proposal = {
        "version": 2,
        "model": {
            "dataset_id": model.get("meta", {}).get("dataset_id"),
            "transaction_id": model.get("meta", {}).get("transaction_id"),
            "effective_date": model.get("meta", {}).get("transaction_effective_date"),
        },
        "join": {"column": join_column},
        "fields": fields,
    }
    lines = ["# CSV-to-model mapping", "", f"Mapped: {sum(value is not None for value in fields.values())}/{len(fields)}", "", "## Mapping", ""]
    for path, field in model.get("fields", {}).items():
        value = fields[path]
        if value:
            display = (
                f"{value.get('source')}:{value.get('column')} + {value.get('parse_as')}→rank"
                if isinstance(value, Mapping) else str(value)
            )
            lines.append(f"{field.get('name') or path} | YES | `{path}` ← `{display}` | PROPOSED ({detail[path][0]:.2f})")
        else:
            alternatives = ", ".join(f"{name} ({score:.2f})" for score, name in detail[path][1][:3]) or "none"
            lines.append(f"{field.get('name') or path} | NO | `{path}` | candidates: {alternatives}")
    return proposal, "\n".join(lines) + "\n"


def _read_column_values(input_dir: Path | None, locator: str) -> set[str]:
    source, column = locator.split(":", 1)
    if input_dir is None:
        return set()
    path = input_dir / f"{source}.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return {str(row.get(column, "")).strip() for row in csv.DictReader(handle, dialect=dialect) if str(row.get(column, "")).strip()}


def _code_mapping_defaults_for_field(field: Mapping[str, Any]) -> dict[str, str]:
    """Return model-derived raw aliases for one coded field.

    The mapping file is user-facing configuration, so it should be useful before
    any CSV has been inspected.  Every canonical model value is accepted as
    itself; terminology codes and differing display names are aliases for that
    canonical value.  Direct ``field["codes"]`` associations are deliberately
    ignored here because those describe the data element itself, not one of its
    permitted values.
    """
    values = accepted_values(field)
    defaults: dict[str, str] = {}

    for canonical, raw_info in values.items():
        canonical_text = str(canonical)
        info = raw_info if isinstance(raw_info, Mapping) else {}
        defaults.setdefault(canonical_text, canonical_text)

        code = str(info.get("code") or "").strip()
        if code:
            defaults.setdefault(code, canonical_text)

        display = str(info.get("display_name") or "").strip()
        if display and display != canonical_text:
            defaults.setdefault(display, canonical_text)
        for synonym in info.get("synonyms", []):
            synonym_text = str(synonym).strip()
            if synonym_text:
                defaults.setdefault(synonym_text, canonical_text)

    # Keep compatibility with hand-built/minimal models where concept-list
    # options have not yet been folded into ``values``.
    for option in field.get("options", []):
        option_text = str(option).strip()
        if option_text:
            defaults.setdefault(option_text, option_text)

    return defaults


def code_mapping_defaults(model: Mapping[str, Any]) -> dict[str, Any]:
    """Build the input-independent code mapping scaffold from the model."""
    fields: dict[str, dict[str, str]] = {}
    for path, field in model.get("fields", {}).items():
        values = accepted_values(field)
        options = [str(value) for value in field.get("options", []) if str(value)]
        has_terminology_codes = any(
            isinstance(info, Mapping) and bool(info.get("code"))
            for info in values.values()
        )
        if field.get("type") not in {"code", "ordinal"} and not has_terminology_codes:
            continue
        if not values and not options:
            continue
        fields[path] = _code_mapping_defaults_for_field(field)
    return {"version": 1, "fields": fields}


def codes_mapping_proposal(model: Mapping[str, Any], csv_mapping: Mapping[str, Any], input_dir: Path | None) -> tuple[dict[str, Any], str]:
    proposal = code_mapping_defaults(model)
    fields: dict[str, dict[str, str | None]] = {
        path: dict(values) for path, values in proposal["fields"].items()
    }
    lines = ["# Raw-code-to-dataset-value mapping", ""]

    for path, translations in fields.items():
        field = model.get("fields", {}).get(path, {})
        values = accepted_values(field)
        locator = csv_mapping.get("fields", {}).get(path)
        if isinstance(locator, Mapping) and locator.get("source") and locator.get("column"):
            locator_text = f"{locator['source']}:{locator['column']}"
        else:
            locator_text = locator if isinstance(locator, str) else None
        raw_values = _read_column_values(input_dir, locator_text) if locator_text else set()

        by_norm: dict[str, str] = {}
        by_code: dict[str, str] = {}
        for canonical, raw_info in values.items():
            canonical_text = str(canonical)
            info = raw_info if isinstance(raw_info, Mapping) else {}
            by_norm.setdefault(_norm(canonical_text), canonical_text)
            display = str(info.get("display_name") or "").strip()
            if display:
                by_norm.setdefault(_norm(display), canonical_text)
            code = str(info.get("code") or "").strip()
            if code:
                by_code.setdefault(code, canonical_text)

        default_count = len(translations)
        for raw in sorted(raw_values):
            translations.setdefault(raw, by_code.get(raw) or by_norm.get(_norm(raw)))

        observed_mapped = sum(translations.get(raw) is not None for raw in raw_values)
        lines.append(f"## {field.get('name') or path}")
        lines.append("")
        lines.append(
            f"`{path}` — {default_count} model defaults; "
            f"{observed_mapped}/{len(raw_values)} observed raw values mapped"
        )
        lines.append("")
        for raw, canonical in translations.items():
            lines.append(f"- `{raw}` → `{canonical}`" if canonical else f"- `{raw}` → **UNMAPPED → nullFlavor OTH**")
        lines.append("")

    return {"version": 1, "fields": fields}, "\n".join(lines) + "\n"


def write_code_mapping(model_dir: Path, model: Mapping[str, Any]) -> dict[str, Any]:
    """Write the model-derived code mapping before any CSV inspection."""
    proposal, report = codes_mapping_proposal(model, {"fields": {}}, None)
    write_json(model_dir / "codes-mapping.proposed.json", proposal)
    (model_dir / "codes-mapping.md").write_text(report, encoding="utf-8")
    return proposal


def write_input_mappings(
    model_dir: Path,
    input_dir: Path,
    model: Mapping[str, Any],
    *,
    join_column: str = "patient_id",
) -> dict[str, Any]:
    """Inspect one CSV snapshot and write only input-side mapping proposals."""
    csv_proposal, csv_report = csv_mapping_proposal(model, input_dir, join_column)
    code_proposal, code_report = codes_mapping_proposal(model, csv_proposal, input_dir)
    write_json(model_dir / "csv-mapping.proposed.json", csv_proposal)
    write_json(model_dir / "codes-mapping.proposed.json", code_proposal)
    (model_dir / "csv-mapping.md").write_text(csv_report, encoding="utf-8")
    (model_dir / "codes-mapping.md").write_text(code_report, encoding="utf-8")
    return {"csv": csv_proposal, "codes": code_proposal}


def write_cda_mapping(
    xml_paths: Iterable[Path],
    model_dir: Path,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
) -> dict[str, Any]:
    """Write the ART-DECOR/model-to-CDA proposal without inspecting CSV input."""
    cda_proposal, audit, cda_report, cda_details = cda_mapping_audit(
        model, cda, xml_paths
    )
    write_json(model_dir / "cda-mapping.proposed.json", cda_proposal)
    write_json(model_dir / "mapping-audit.json", audit)
    (model_dir / "cda-mapping.md").write_text(cda_report, encoding="utf-8")
    (model_dir / "cda-mapping-details.md").write_text(cda_details, encoding="utf-8")
    from .reports import write_readable_cda
    write_readable_cda(model_dir, cda, audit)
    return cda_proposal


def write_mapping_model(
    evidence: Iterable[Path],
    model_dir: Path,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
) -> dict[str, Any]:
    """Compiler-boundary name for writing mapping artifacts."""
    return write_cda_mapping(evidence, model_dir, model, cda)
