"""Human-readable reports rendered from compiled semantic artifacts."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence, cast
from xml.sax.saxutils import escape, quoteattr

from ..bindings import (physical_target_name, required_construction_gap_targets,
                        required_construction_gaps,
                        required_unmapped_null_flavor,
                        resolve_required_unmapped_null_flavor,
                        site_requirement_targets)
from ..cda.narrative import narrative_blocks, narrative_source_rules
from ..cda.tree import document_index, parse_location
from ..i18n import message as _msg, localized
from ..transforms import mapping_rules
from .mapping import gap_reopening_evidence_label


def _comment(value: str) -> ET.Element:
    return cast(
        "ET.Element[str]",
        ET.Comment(" ".join(value.replace("--", "—").split())),
    )


def _audit_targets(audit: Mapping[str, Any]) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = defaultdict(list)
    fields = audit.get("fields", {})
    if not isinstance(fields, Mapping):
        return {}
    for path, detail in fields.items():
        if not isinstance(detail, Mapping):
            continue
        primary = detail.get("primary", {})
        if not isinstance(primary, Mapping):
            continue
        target = str(primary.get("target") or "")
        if target:
            targets[target].append(str(path))
    return dict(targets)


def _leaf(value: Any) -> str:
    segment = str(value or "").split("/")[-1].split("[", 1)[0]
    return segment.split(":")[-1]


def _section_of(
    location: tuple[int, ...],
    nodes: Mapping[tuple[int, ...], Mapping[str, Any]],
    parents: Mapping[tuple[int, ...], tuple[int, ...]],
) -> tuple[int, ...] | None:
    current = location
    while current in parents:
        current = parents[current]
        if _leaf(nodes.get(current, {}).get("name")) == "section":
            return current
    return None


def _template_label(target: Mapping[str, Any]) -> str:
    name = str(target.get("template_name") or "CDA document")
    display = str(target.get("template_display_name") or "").strip()
    return f"{display} ({name})" if display and display != name else name


def _section_label(
    location: tuple[int, ...],
    nodes: Mapping[tuple[int, ...], Mapping[str, Any]],
    cda: Mapping[str, Any],
) -> str:
    target_name = str(nodes.get(location, {}).get("target") or "")
    target = cda.get("targets", {}).get(target_name, {})
    return _template_label(target) if target else "CDA section"


def _mapping_view(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, Any]:
    nodes, parents = document_index(cda)
    sections = [
        location for location, node in nodes.items()
        if _leaf(node.get("name")) == "section"
    ]
    rows_by_section: dict[tuple[int, ...] | None, list[dict[str, Any]]] = defaultdict(list)
    structures = mapping.get("structures", {})

    for dataset_path, selection in mapping.get("fields", {}).items():
        for rule in mapping_rules(selection):
            physical_name = physical_target_name(cda, rule)
            target = cda.get("targets", {}).get(physical_name, {})
            locations = list(target.get("locations", []))
            if len(locations) != 1:
                continue
            location = parse_location(locations[0])
            if location is None:
                continue
            structure_name = str(rule.get("structure") or "")
            structure = structures.get(structure_name, {}) if isinstance(structures, Mapping) else {}
            rows_by_section[_section_of(location, nodes, parents)].append({
                "dataset_path": str(dataset_path),
                "dataset_name": str(
                    model.get("fields", {}).get(dataset_path, {}).get("name")
                    or dataset_path
                ),
                "target": str(rule.get("target") or physical_name),
                "cda_target": physical_name,
                "target_model": target,
                "rule": rule,
                "selection": selection,
                "structure": structure,
                "entity": _template_label(target),
                "entity_name": str(target.get("template_name") or "CDA document"),
                "location": location,
            })

    for block in narrative_blocks(mapping):
        dataset_path = str(block.get("source") or "")
        physical_name = str(block.get("section_target") or "")
        target = cda.get("targets", {}).get(physical_name, {})
        locations = list(target.get("locations", []))
        if not dataset_path or len(locations) != 1:
            continue
        location = parse_location(locations[0])
        if location is None:
            continue
        narrative_rule = {
            "target": physical_name,
            "mode": "narrative",
            "reason": block.get("reason"),
            "decision": block.get("decision"),
            "label": block.get("label"),
            "type": block.get("type"),
        }
        rows_by_section[_section_of(location, nodes, parents)].append({
            "dataset_path": dataset_path,
            "dataset_name": str(
                model.get("fields", {}).get(dataset_path, {}).get("name")
                or dataset_path
            ),
            "target": physical_name,
            "cda_target": physical_name,
            "target_model": target,
            "rule": narrative_rule,
            "selection": block,
            "structure": {},
            "entity": _template_label(target),
            "entity_name": str(target.get("template_name") or "CDA document"),
            "location": location,
            "narrative": True,
        })

    return {
        "nodes": nodes,
        "parents": parents,
        "sections": sections,
        "rows": rows_by_section,
        "template": cda.get("document_template", {}),
    }


def _entity_groups(rows: list[Mapping[str, Any]]) -> list[tuple[str, list[Mapping[str, Any]]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["entity"]), []).append(row)
    return list(grouped.items())


def _ordered_model_paths(model: Mapping[str, Any]) -> list[str]:
    fields = model.get("fields", {})
    order = [str(path) for path in model.get("order", []) if path in fields]
    order.extend(sorted(str(path) for path in fields if path not in order))
    return order


def _selected_targets(selection: Any) -> list[str]:
    return list(dict.fromkeys(
        str(rule.get("target") or "")
        for rule in mapping_rules(selection)
        if rule.get("target") and rule.get("mode") != "fallback"
    ))


def _suggested_targets(
    detail: Mapping[str, Any], cda: Mapping[str, Any],
) -> list[str]:
    """Return unselected candidates that can write one physical CDA leaf."""
    targets: list[str] = []
    for candidate in _candidate_rows(detail):
        name = str(candidate.get("target") or "")
        target = cda.get("targets", {}).get(name, {})
        if (
            name
            and (candidate.get("actionable") or candidate.get("suggested"))
            and target.get("writable")
            and not target.get("prohibited")
            and len(target.get("locations", [])) == 1
            and name not in targets
        ):
            targets.append(name)
    return targets


def _coverage_index(
    model: Mapping[str, Any], cda: Mapping[str, Any],
    mapping: Mapping[str, Any], audit: Mapping[str, Any],
) -> dict[str, Any]:
    configured = mapping.get("fields", {})
    reviews = mapping.get("field_reviews", {})
    narrative_sources = narrative_source_rules(mapping)
    audited = audit.get("fields", {})
    selected: dict[str, list[str]] = {}
    suggested: dict[str, list[str]] = {}
    missing: list[str] = []
    reviewed: dict[str, Mapping[str, Any]] = {}
    for path in _ordered_model_paths(model):
        selection = configured.get(path) if isinstance(configured, Mapping) else None
        review = reviews.get(path) if isinstance(reviews, Mapping) else None
        narrative_targets = list(dict.fromkeys(
            str(rule.get("section_target") or "")
            for rule in narrative_sources.get(path, [])
            if rule.get("section_target")
        ))
        if narrative_targets:
            selected[path] = narrative_targets
            continue
        if (
            selection is None and isinstance(review, Mapping)
            and review.get("status") == "intentionally_unmapped"
        ):
            reviewed[path] = review
            continue
        targets = _selected_targets(selection)
        if targets:
            selected[path] = targets
            continue
        detail = audited.get(path, {}) if isinstance(audited, Mapping) else {}
        candidates = _suggested_targets(
            detail if isinstance(detail, Mapping) else {}, cda,
        )
        if candidates:
            suggested[path] = candidates
        else:
            missing.append(path)
    return {
        "selected": selected, "suggested": suggested, "missing": missing,
        "reviewed": reviewed,
    }


def _dataset_coverage_tree(
    model: Mapping[str, Any], coverage: Mapping[str, Any],
) -> list[str]:
    """Render every dataset field in its source hierarchy."""
    groups = model.get("groups", {})
    fields = model.get("fields", {})
    children: dict[str | None, list[tuple[str, str]]] = defaultdict(list)
    for path, group in groups.items():
        parent = str(group.get("parent") or "") or None
        children[parent].append(("group", str(path)))
    for path in _ordered_model_paths(model):
        field = fields.get(path, {})
        parent = str(field.get("parent") or "") or None
        children[parent].append(("field", path))

    selected = coverage.get("selected", {})
    suggested = coverage.get("suggested", {})
    reviewed = coverage.get("reviewed", {})
    lines = ["```text", "   Dataset model"]

    def render(parent: str | None, stem: str = "") -> None:
        items = children.get(parent, [])
        for index, (kind, path) in enumerate(items):
            last = index == len(items) - 1
            branch = "└──" if last else "├──"
            next_stem = stem + ("    " if last else "│   ")
            if kind == "group":
                name = str(groups.get(path, {}).get("name") or path.rsplit(".", 1)[-1])
                lines.append(f"   {stem}{branch} {name}")
                render(path, next_stem)
                continue
            name = str(fields.get(path, {}).get("name") or path.rsplit(".", 1)[-1])
            if path in selected:
                status = "✓"
                targets = selected[path]
                consequence = " → " + ", ".join(f"{{{target}}}" for target in targets)
            elif path in reviewed:
                status = "="
                review = reviewed[path]
                decision = (
                    f" [{review.get('decision')}]"
                    if isinstance(review, Mapping) and review.get("decision")
                    else ""
                )
                consequence = (' → — ' + _msg('markdown.intentionally_unmapped')) + decision
            elif path in suggested:
                status = "!"
                targets = suggested[path]
                consequence = " → " + ", ".join(f"{{{target}}}" for target in targets)
            else:
                status = "×"
                consequence = (' → — ' + _msg('markdown.no_suitable_writable_cda_leaf'))
            lines.append(f"{status:<3}{stem}{branch} {name}{consequence}")

    render(None)
    return lines + ["```"]


def _plain(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cardinality(model: Mapping[str, Any]) -> str:
    minimum = model.get("min")
    maximum = model.get("max")
    if minimum is None and maximum is None:
        return ""
    return f"{0 if minimum is None else minimum}..{'*' if maximum is None else maximum}"


def _source_trace(path: str, field: Mapping[str, Any]) -> str:
    parts: list[str] = []
    extension = field.get("model_extension")
    if isinstance(extension, Mapping):
        parts.append("reviewed model extension")
    elif field.get("concept"):
        parts.append(f"concept {field['concept']}")
    parts.append(path)
    if field.get("type"):
        parts.append(str(field["type"]))
    cardinality = _cardinality(field)
    if cardinality:
        parts.append(cardinality)
    if isinstance(extension, Mapping) and extension.get("reason"):
        parts.append(_plain(extension["reason"]))
    return " · ".join(parts)


def _template_identity(target: Mapping[str, Any]) -> str:
    template_id = str(target.get("template_id") or "")
    revision = str(target.get("template_effective_date") or "")
    if not template_id:
        return ""
    return template_id + (f" @ {revision}" if revision else "")


def _binding_trace(target: Mapping[str, Any]) -> str:
    bindings: list[str] = []
    for binding in target.get("value_set_bindings", []):
        if not isinstance(binding, Mapping) or not binding.get("id"):
            continue
        identity = str(binding["id"])
        revision = str(binding.get("effective_date") or "")
        if revision:
            identity += f" @ {revision}"
        if identity not in bindings:
            bindings.append(identity)
    return ", ".join(f"ValueSet {value}" for value in bindings)


def _target_trace(
    target: Mapping[str, Any], *, include_template: bool,
) -> str:
    parts: list[str] = []
    if include_template:
        parts.append(_template_label(target))
        identity = _template_identity(target)
        if identity:
            parts.append(identity)
    path = str(target.get("path") or target.get("element_name") or "")
    if path:
        parts.append(f"template-relative {path}")
    shape = " ".join(filter(None, (
        str(target.get("datatype") or ""),
        _cardinality(target),
        str(target.get("conformance") or ""),
    )))
    if shape:
        parts.append(shape)
    binding = _binding_trace(target)
    if binding:
        parts.append(binding)
    return " · ".join(parts) or "compiled CDA target metadata unavailable"


def _annotation_traces(
    location: tuple[int, ...],
    target: Mapping[str, Any],
    nodes: Mapping[tuple[int, ...], Mapping[str, Any]],
    parents: Mapping[tuple[int, ...], tuple[int, ...]],
) -> list[tuple[str, str]]:
    """Return exact owner-template descriptions applying to one physical leaf."""
    template_id = str(target.get("template_id") or "")
    effective_date = str(target.get("template_effective_date") or "")
    if not template_id:
        return []

    traces: list[tuple[str, str]] = []
    current: tuple[int, ...] | None = location
    while current is not None:
        node = nodes.get(current, {})
        origin = node.get("origin", {})
        if not isinstance(origin, Mapping):
            origin = {}
        owner = str(origin.get("template_id") or "")
        revision = str(origin.get("template_effective_date") or "")
        description = " ".join(str(node.get("description") or "").split())
        if (
            description
            and owner == template_id
            and (not effective_date or not revision or revision == effective_date)
        ):
            path = str(origin.get("path") or node.get("name") or "")
            trace = (path, description)
            if trace not in traces:
                traces.append(trace)
        current = parents.get(current)
    return traces


def _scalar_summary(value: Any) -> str:
    if isinstance(value, Mapping):
        preferred = [
            key for key in (
                "code", "codeSystem", "displayName", "nullFlavor", "value",
            ) if value.get(key) not in (None, "")
        ]
        if preferred:
            return ", ".join(f"{key}={value[key]}" for key in preferred)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _structure_trace(
    name: str, structure: Mapping[str, Any], rule: Mapping[str, Any],
    physical: str,
) -> str:
    kind = str(structure.get("type") or "structural rule")
    parts = [f"{kind} ({name})"]
    logical = str(rule.get("target") or "")
    if physical and physical != logical:
        parts.append(f"physical {{{physical}}}")
    if rule.get("branch"):
        parts.append(f"branch {rule['branch']}")
    constants = rule.get("constants", {})
    if not constants and rule.get("branch"):
        branches = structure.get("branches", [])
        if isinstance(branches, Sequence):
            branch = next((
                item for item in branches
                if isinstance(item, Mapping)
                and str(item.get("branch") or "") == str(rule["branch"])
            ), {})
            if isinstance(branch, Mapping):
                constants = branch.get("constants", {})
    if isinstance(constants, Mapping):
        parts.extend(
            f"{target}={_scalar_summary(value)}"
            for target, value in constants.items()
        )
    policy = structure.get("policy")
    if policy:
        parts.append(f"policy {policy}")
    transform = structure.get("transform", {})
    if isinstance(transform, Mapping) and transform.get("type"):
        parts.append(f"transform {transform['type']}")
        if transform.get("null_flavor"):
            parts.append(f"nullFlavor {transform['null_flavor']}")
    reason = _plain(structure.get("reason"))
    if reason:
        parts.append(reason)
    return "; ".join(parts)


def _rule_trace(
    rule: Mapping[str, Any], mapping: Mapping[str, Any], physical: str,
) -> str:
    structure_name = str(rule.get("structure") or "")
    structures = mapping.get("structures", {})
    if structure_name and isinstance(structures, Mapping):
        structure = structures.get(structure_name, {})
        if isinstance(structure, Mapping):
            return _structure_trace(structure_name, structure, rule, physical)
    mode = str(rule.get("mode") or "")
    parts: list[str] = []
    if mode == "narrative":
        kind = str(rule.get("type") or "fact")
        decision = str(rule.get("decision") or "reviewed")
        parts.append(f"reviewed narrative-only {kind} [{decision}]")
    elif mode == "fallback_if_active":
        parts.append("fallback_if_active; fills only an already-active CDA branch")
    elif mode == "if_active":
        parts.append(
            "if_active; writes only when target "
            f"{rule.get('active_if') or '?'} has a mapped value"
        )
    elif mode == "presence":
        parts.append("presence rule")
    elif mode and mode != "value":
        parts.append(f"mode {mode}")
    transform = rule.get("transform")
    if isinstance(transform, Mapping):
        kind = str(transform.get("type") or "transform")
        details = [f"transform {kind}"]
        for key, label in (
            ("select", "select"), ("code_system", "codeSystem"),
            ("null_flavor", "nullFlavor"), ("policy", "policy"),
        ):
            if transform.get(key) not in (None, ""):
                details.append(f"{label} {transform[key]}")
        parts.append(", ".join(details))
    reason = _plain(rule.get("reason"))
    if reason:
        parts.append(reason)
    return "; ".join(parts)


def _gap_trace(detail: Mapping[str, Any]) -> str:
    gap = detail.get("gap", {})
    parts: list[str] = []
    gate = ""
    kind = ""
    inventory_only = False
    possible_targets = detail.get("possible_targets", {})
    possible_items = (
        possible_targets.get("items", [])
        if isinstance(possible_targets, Mapping) else []
    )
    if isinstance(gap, Mapping):
        gate = str(gap.get("gate") or "")
        kind = str(gap.get("kind") or "")
        if gate or kind:
            parts.append(":".join(value for value in (gate, kind) if value))
        inventory_only = (
            gate == "semantic"
            and kind == "no_association"
            and bool(possible_items)
        )
        reopens = gap.get("reopens_with", [])
        if isinstance(reopens, Sequence) and not isinstance(reopens, (str, bytes)):
            evidence = (
                "upstream association or reviewed semantic bridge"
                if inventory_only
                else ", ".join(dict.fromkeys(
                    gap_reopening_evidence_label(value)
                    for value in reopens if value
                ))
            )
            if evidence:
                parts.append(f"reopen with {evidence}")
    reason = _plain(detail.get("unresolved_reason"))
    if inventory_only:
        parts.append(
            "compatible writable targets are unproven inventory, not semantic evidence"
        )
    elif reason and reason not in parts:
        parts.append(reason.replace("_", " "))
    return " · ".join(parts) or "no approved semantic CDA association"


def _extended_dataset_coverage_tree(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any],
    audit: Mapping[str, Any], coverage: Mapping[str, Any],
) -> list[str]:
    """Render source-oriented coverage with stable clinical/CDA traceability."""
    groups = model.get("groups", {})
    fields = model.get("fields", {})
    children: dict[str | None, list[tuple[str, str]]] = defaultdict(list)
    for path, group in groups.items():
        parent = str(group.get("parent") or "") or None
        children[parent].append(("group", str(path)))
    for path in _ordered_model_paths(model):
        field = fields.get(path, {})
        parent = str(field.get("parent") or "") or None
        children[parent].append(("field", path))

    configured = mapping.get("fields", {})
    narrative_by_source = narrative_source_rules(mapping)
    reviewed = coverage.get("reviewed", {})
    audited = audit.get("fields", {})
    lines = ["```text", f"   Dataset model — {len(fields)} datapoints"]

    def annotations(prefix: str, path: str, field: Mapping[str, Any]) -> None:
        lines.append(f"   {prefix}S: {_source_trace(path, field)}")
        selection = configured.get(path) if isinstance(configured, Mapping) else None
        rules = [
            rule for rule in mapping_rules(selection)
            if rule.get("mode") != "fallback"
        ]
        for index, rule in enumerate(rules, 1):
            physical = physical_target_name(cda, rule)
            target = cda.get("targets", {}).get(physical, {})
            label = "T" if len(rules) == 1 else f"T{index}"
            logical = str(rule.get("target") or physical)
            suffix = (
                f" · logical {{{logical}}} uses physical {{{physical}}}"
                if logical != physical else ""
            )
            lines.append(
                f"   {prefix}{label}: {_target_trace(target, include_template=True)}{suffix}"
            )
            trace = _rule_trace(rule, mapping, physical)
            if trace:
                lines.append(f"   {prefix}R: {trace}")
        for block in narrative_by_source.get(path, []):
            target_name = str(block.get("section_target") or "")
            target = cda.get("targets", {}).get(target_name, {})
            lines.append(
                f"   {prefix}T: narrative {_target_trace(target, include_template=True)}"
            )
            reason = _plain(block.get("reason"))
            decision = str(block.get("decision") or "reviewed narrative")
            lines.append(
                f"   {prefix}R: narrative-only {block.get('type')} [{decision}]"
                + (f"; {reason}" if reason else "")
            )
        if path in coverage.get("suggested", {}):
            targets = coverage["suggested"][path]
            for index, target_name in enumerate(targets, 1):
                label = "T" if len(targets) == 1 else f"T{index}"
                target = cda.get("targets", {}).get(target_name, {})
                lines.append(
                    f"   {prefix}{label}: suggested {_target_trace(target, include_template=True)}"
                )
        review = reviewed.get(path)
        if isinstance(review, Mapping):
            decision = str(review.get("decision") or "reviewed null")
            reason = _plain(review.get("reason"))
            lines.append(f"   {prefix}G: {decision}" + (f" · {reason}" if reason else ""))
        elif path in coverage.get("missing", []):
            detail = audited.get(path, {}) if isinstance(audited, Mapping) else {}
            detail = detail if isinstance(detail, Mapping) else {}
            context = detail.get("context", {})
            node = context.get("node", {}) if isinstance(context, Mapping) else {}
            if isinstance(node, Mapping) and node:
                lines.append(
                    f"   {prefix}T-context: {_target_trace(node, include_template=True)}"
                )
            lines.append(f"   {prefix}G: {_gap_trace(detail)}")

    def render(parent: str | None, stem: str = "") -> None:
        items = children.get(parent, [])
        for index, (kind, path) in enumerate(items):
            last = index == len(items) - 1
            branch = "└──" if last else "├──"
            next_stem = stem + ("    " if last else "│   ")
            if kind == "group":
                group = groups.get(path, {})
                name = str(group.get("name") or path.rsplit(".", 1)[-1])
                suffix = (
                    " [repeatable dataset group]"
                    if group.get("repeating") else ""
                )
                lines.append(f"   {stem}{branch} {name}{suffix}")
                render(path, next_stem)
                continue
            field = fields.get(path, {})
            name = str(field.get("name") or path.rsplit(".", 1)[-1])
            if path in coverage.get("selected", {}):
                status = "✓"
                consequence = " → " + ", ".join(
                    f"{{{target}}}" for target in coverage["selected"][path]
                )
            elif path in reviewed:
                status = "="
                decision = str(reviewed[path].get("decision") or "")
                consequence = (' → — ' + _msg('markdown.intentionally_unmapped'))
                if decision:
                    consequence += f" [{decision}]"
            elif path in coverage.get("suggested", {}):
                status = "!"
                consequence = " → " + ", ".join(
                    f"{{{target}}}" for target in coverage["suggested"][path]
                )
            else:
                status = "×"
                consequence = " → — no approved writable CDA target"
            lines.append(f"{status:<3}{stem}{branch} {name}{consequence}")
            annotations(next_stem, path, field)

    render(None)
    return lines + ["```"]


def _reportable_cda_target(target: Mapping[str, Any]) -> bool:
    """Limit inverse coverage to template-level payload leaves.

    Generic datatype descendants, fixed/conditional values and system supplied
    values remain available in cda.json but would swamp a mapping-coverage view.
    """
    return bool(
        target.get("writable")
        and not target.get("prohibited")
        and len(target.get("locations", [])) == 1
        and not target.get("datatype_derived")
        and target.get("system_value") is None
        and not target.get("fixed")
        and not target.get("conditional_fixed")
    )


def _cda_coverage_tree(
    view: Mapping[str, Any], model: Mapping[str, Any], cda: Mapping[str, Any],
    mapping: Mapping[str, Any], coverage: Mapping[str, Any],
) -> tuple[list[str], int]:
    """Render the inverse CDA-leaf-to-dataset coverage tree."""
    fields = model.get("fields", {})
    selected_sources: dict[str, list[str]] = defaultdict(list)
    suggested_sources: dict[str, list[str]] = defaultdict(list)
    for path, targets in coverage.get("selected", {}).items():
        for target in targets:
            selected_sources[str(target)].append(str(path))
    for path, targets in coverage.get("suggested", {}).items():
        for target in targets:
            suggested_sources[str(target)].append(str(path))
    required_gap_targets = required_construction_gap_targets(cda, mapping)
    site_owned_targets = site_requirement_targets(cda, mapping)

    included = {
        str(name) for name, target in cda.get("targets", {}).items()
        if _reportable_cda_target(target)
    }
    included.update(selected_sources)
    included.update(suggested_sources)
    included.update(str(name) for name in mapping.get("target_defaults", {}))
    included.update(site_owned_targets)

    nodes, parents = view["nodes"], view["parents"]
    rows_by_section: dict[tuple[int, ...] | None, list[dict[str, Any]]] = defaultdict(list)
    no_source = 0
    for name in included:
        target = cda.get("targets", {}).get(name, {})
        locations = list(target.get("locations", []))
        if len(locations) != 1:
            continue
        location = parse_location(locations[0])
        if location is None:
            continue
        selected_paths = selected_sources.get(name, [])
        suggested_paths = suggested_sources.get(name, [])
        if not selected_paths and not suggested_paths and _reportable_cda_target(target):
            no_source += 1
        rows_by_section[_section_of(location, nodes, parents)].append({
            "name": name,
            "target": target,
            "location": location,
            "entity": _template_label(target),
            "selected": selected_paths,
            "suggested": suggested_paths,
        })

    for rows in rows_by_section.values():
        rows.sort(key=lambda row: (row["location"], row["name"]))

    template = view["template"]
    title = str(template.get("display_name") or template.get("name") or "ClinicalDocument")
    lines = ["```text", f"   {title} (ClinicalDocument)"]
    areas: list[tuple[str, tuple[int, ...] | None]] = [("Document header", None)] + [
        (_section_label(section, nodes, cda), section) for section in view["sections"]
    ]
    for area_index, (area_name, section) in enumerate(areas):
        rows = rows_by_section.get(section, [])
        if not rows:
            continue
        area_last = area_index == len(areas) - 1
        area_branch = "└──" if area_last else "├──"
        area_stem = "    " if area_last else "│   "
        lines.append(f"   {area_branch} {area_name}")
        entities = _entity_groups([
            {"entity": row["entity"], **row} for row in rows
        ])
        for entity_index, (entity, entity_rows) in enumerate(entities):
            entity_last = entity_index == len(entities) - 1
            entity_branch = "└──" if entity_last else "├──"
            entity_stem = area_stem + ("    " if entity_last else "│   ")
            lines.append(f"   {area_stem}{entity_branch} {entity}")
            for row_index, row in enumerate(entity_rows):
                last = row_index == len(entity_rows) - 1
                branch = "└──" if last else "├──"
                selected_paths = row["selected"]
                suggested_paths = row["suggested"]
                if selected_paths:
                    status = "✓!" if suggested_paths else "✓"
                    source_names = [
                        str(fields.get(path, {}).get("name") or path)
                        for path in selected_paths
                    ]
                    consequence = " ← " + ", ".join(source_names)
                    if suggested_paths:
                        names = [str(fields.get(path, {}).get("name") or path) for path in suggested_paths]
                        consequence += "; suggested: " + ", ".join(names)
                elif suggested_paths:
                    status = "!"
                    names = [str(fields.get(path, {}).get("name") or path) for path in suggested_paths]
                    consequence = " ← " + ", ".join(names)
                else:
                    status = "○"
                    consequence = (' ← ' + _msg('markdown.no_dataset_counterpart'))
                    default = mapping.get("target_defaults", {}).get(row["name"], {})
                    if isinstance(default, Mapping) and default.get("nullFlavor"):
                        consequence += f"; default nullFlavor=\"{default['nullFlavor']}\""
                    elif isinstance(default, Mapping) and "value" in default:
                        consequence += (
                            "; default value="
                            + json.dumps(default["value"], ensure_ascii=False)
                        )
                if row["name"] in required_gap_targets:
                    status += "▲"
                elif row["name"] in site_owned_targets:
                    status += "◆"
                    requirements = mapping.get("site_requirements", {})
                    requirement = (
                        requirements.get(row["name"], {})
                        if isinstance(requirements, Mapping) else {}
                    )
                    channel = (
                        str(requirement.get("channel") or "")
                        if isinstance(requirement, Mapping) else ""
                    )
                    if not selected_paths and not suggested_paths and channel:
                        consequence = (
                            f" ← site configuration via cda.{channel}; {_msg('markdown.no_dataset_counterpart')}"
                        )
                leaf = _leaf(row["target"].get("path") or row["target"].get("element_name"))
                lines.append(
                    f"{status:<3}{area_stem}{entity_stem[len(area_stem):]}{branch} "
                    f"{leaf} {{{row['name']}}}{consequence}"
                )
    return lines + ["```"], no_source


def _extended_cda_coverage_tree(
    view: Mapping[str, Any], model: Mapping[str, Any], cda: Mapping[str, Any],
    mapping: Mapping[str, Any], coverage: Mapping[str, Any],
) -> tuple[list[str], int]:
    """Render physical CDA coverage with logical occurrence traceability."""
    fields = model.get("fields", {})
    configured = mapping.get("fields", {})
    selected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if isinstance(configured, Mapping):
        for path in _ordered_model_paths(model):
            for rule in mapping_rules(configured.get(path)):
                if rule.get("mode") == "fallback":
                    continue
                physical = physical_target_name(cda, rule)
                selected[physical].append({
                    "path": path,
                    "logical": str(rule.get("target") or physical),
                    "rule": rule,
                })
    for block in narrative_blocks(mapping):
        physical = str(block.get("section_target") or "")
        source = str(block.get("source") or "")
        if physical and source:
            selected[physical].append({
                "path": source,
                "logical": physical,
                "rule": {
                    "target": physical,
                    "mode": "narrative",
                    "reason": block.get("reason"),
                    "decision": block.get("decision"),
                    "type": block.get("type"),
                },
            })

    suggested: dict[str, list[str]] = defaultdict(list)
    for path, names in coverage.get("suggested", {}).items():
        for name in names:
            suggested[str(name)].append(str(path))

    def physical_configuration(
        key: str,
    ) -> dict[str, list[tuple[str, Mapping[str, Any]]]]:
        result: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
        configured_values = mapping.get(key, {})
        if not isinstance(configured_values, Mapping):
            return result
        for logical, value in configured_values.items():
            if not isinstance(value, Mapping):
                continue
            physical = physical_target_name(cda, {"target": str(logical)})
            result[physical].append((str(logical), value))
        return result

    defaults = physical_configuration("target_defaults")
    site_requirements = physical_configuration("site_requirements")
    required_gap_targets = required_construction_gap_targets(cda, mapping)
    site_owned_targets = site_requirement_targets(cda, mapping)

    included = {
        str(name) for name, target in cda.get("targets", {}).items()
        if _reportable_cda_target(target)
    }
    included.update(selected)
    included.update(suggested)
    included.update(defaults)
    included.update(site_requirements)

    nodes, parents = view["nodes"], view["parents"]
    rows_by_section: dict[tuple[int, ...] | None, list[dict[str, Any]]] = defaultdict(list)
    no_source = 0
    for name in included:
        target = cda.get("targets", {}).get(name, {})
        locations = list(target.get("locations", []))
        if len(locations) != 1:
            continue
        location = parse_location(locations[0])
        if location is None:
            continue
        selected_rows = selected.get(name, [])
        suggested_paths = suggested.get(name, [])
        if not selected_rows and not suggested_paths and _reportable_cda_target(target):
            no_source += 1
        rows_by_section[_section_of(location, nodes, parents)].append({
            "name": name,
            "target": target,
            "location": location,
            "entity": _template_label(target),
            "selected": selected_rows,
            "suggested": suggested_paths,
        })
    for rows in rows_by_section.values():
        rows.sort(key=lambda row: (row["location"], row["name"]))

    template = view["template"]
    title = str(template.get("display_name") or template.get("name") or "ClinicalDocument")
    lines = ["```text", f"   {title} (ClinicalDocument)"]
    document_identity = str(template.get("id") or "")
    if document_identity:
        revision = str(template.get("effective_date") or "")
        lines.append(
            "   Template: " + document_identity + (f" @ {revision}" if revision else "")
        )
    candidate_areas: list[tuple[str, tuple[int, ...] | None]] = [
        ("Document header", None),
        *[(_section_label(section, nodes, cda), section) for section in view["sections"]],
    ]
    areas = [area for area in candidate_areas if rows_by_section.get(area[1])]
    for area_index, (area_name, section) in enumerate(areas):
        rows = rows_by_section[section]
        area_last = area_index == len(areas) - 1
        area_branch = "└──" if area_last else "├──"
        area_stem = "    " if area_last else "│   "
        lines.append(f"   {area_branch} {area_name}")
        entities = _entity_groups([{"entity": row["entity"], **row} for row in rows])
        for entity_index, (entity, entity_rows) in enumerate(entities):
            entity_last = entity_index == len(entities) - 1
            entity_branch = "└──" if entity_last else "├──"
            entity_stem = area_stem + ("    " if entity_last else "│   ")
            lines.append(f"   {area_stem}{entity_branch} {entity}")
            identity = _template_identity(entity_rows[0]["target"])
            if identity:
                lines.append(f"   {entity_stem}Template: {identity}")
            for row_index, row in enumerate(entity_rows):
                last = row_index == len(entity_rows) - 1
                branch = "└──" if last else "├──"
                leaf_stem = entity_stem + ("    " if last else "│   ")
                selected_rows = row["selected"]
                suggested_paths = row["suggested"]
                if selected_rows:
                    status = "✓!" if suggested_paths else "✓"
                    source_names = [
                        str(fields.get(item["path"], {}).get("name") or item["path"])
                        for item in selected_rows
                    ]
                    consequence = " ← " + ", ".join(dict.fromkeys(source_names))
                    if suggested_paths:
                        names = [
                            str(fields.get(path, {}).get("name") or path)
                            for path in suggested_paths
                        ]
                        consequence += "; suggested: " + ", ".join(names)
                elif suggested_paths:
                    status = "!"
                    names = [
                        str(fields.get(path, {}).get("name") or path)
                        for path in suggested_paths
                    ]
                    consequence = " ← " + ", ".join(names)
                else:
                    status = "○D" if defaults.get(row["name"]) else "○"
                    consequence = (' ← ' + _msg('markdown.no_dataset_counterpart'))
                if row["name"] in required_gap_targets:
                    status += "▲"
                elif row["name"] in site_owned_targets:
                    status += "◆"
                    requirement_rows = site_requirements.get(row["name"], [])
                    if requirement_rows:
                        channel = str(requirement_rows[0][1].get("channel") or "")
                        if not selected_rows and not suggested_paths and channel:
                            consequence = f" ← site configuration via cda.{channel}; {_msg('markdown.no_dataset_counterpart')}"
                leaf = _leaf(row["target"].get("path") or row["target"].get("element_name"))
                lines.append(
                    f"{status:<3}{area_stem}{entity_stem[len(area_stem):]}{branch} "
                    f"{leaf} {{{row['name']}}}{consequence}"
                )
                lines.append(
                    f"   {leaf_stem}T: {_target_trace(row['target'], include_template=False)}"
                )
                annotations = _annotation_traces(
                    row["location"], row["target"], nodes, parents,
                )
                for index, (path, description) in enumerate(annotations, 1):
                    label = "A" if len(annotations) == 1 else f"A{index}"
                    location_note = f"{path} — " if path else ""
                    lines.append(
                        f"   {leaf_stem}{label}: {location_note}{description}"
                    )
                source_rows = selected_rows + [
                    {"path": path, "logical": row["name"], "rule": {}}
                    for path in suggested_paths
                ]
                for index, item in enumerate(source_rows, 1):
                    path = str(item["path"])
                    field = fields.get(path, {})
                    label = "S" if len(source_rows) == 1 else f"S{index}"
                    logical = str(item.get("logical") or row["name"])
                    logical_note = (
                        f" · logical {{{logical}}}" if logical != row["name"] else ""
                    )
                    lines.append(
                        f"   {leaf_stem}{label}: {_source_trace(path, field)}{logical_note}"
                    )
                traces = list(dict.fromkeys(
                    trace for item in selected_rows
                    if (trace := _rule_trace(item["rule"], mapping, row["name"]))
                ))
                for trace in traces:
                    lines.append(f"   {leaf_stem}R: {trace}")
                target = row["target"]
                if (
                    not selected_rows
                    and not suggested_paths
                    and not defaults.get(row["name"])
                    and not site_requirements.get(row["name"])
                    and int(target.get("min") or 0) >= 1
                    and not target.get("mandatory")
                    and target.get("permits_null_flavor")
                ):
                    completion_flavor = resolve_required_unmapped_null_flavor(
                        target, required_unmapped_null_flavor(mapping),
                    )
                    lines.append(
                        f"   {leaf_stem}R: defaults.required_unmapped → "
                        f'nullFlavor="{completion_flavor}"'
                    )
                for logical, default in defaults.get(row["name"], []):
                    value = _scalar_summary(default)
                    reason = _plain(default.get("reason"))
                    lines.append(
                        f"   {leaf_stem}R: exact target default for {{{logical}}}: {value}"
                        + (f"; {reason}" if reason else "")
                    )
                for logical, requirement in site_requirements.get(row["name"], []):
                    channel = str(requirement.get("channel") or "")
                    reason = _plain(requirement.get("reason"))
                    lines.append(
                        f"   {leaf_stem}R: site-owned {{{logical}}} via cda.{channel}"
                        + (f"; {reason}" if reason else "")
                    )
    return lines + ["```"], no_source


def _target_label(row: Mapping[str, Any]) -> str:
    target = row["target_model"]
    description = " ".join(str(target.get("description") or "").split())
    node = _leaf(target.get("path") or target.get("element_name"))
    human = description.rstrip(".") if description and len(description) <= 100 else node
    datatype = str(target.get("datatype") or "").strip()
    return f"{human or 'value'}" + (f" (`{datatype}`)" if datatype else "")


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _counted(count: int, singular: str) -> str:
    plural = {"leaf": "leaves"}.get(singular, singular + "s")
    return f"{count} {singular if count == 1 else plural}"


def coverage_headline_counts(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, int]:
    """Return the stable mapping-coverage headline as comparable counts."""
    coverage = _coverage_index(model, cda, mapping, audit)
    covered_targets = {
        str(target)
        for category in ("selected", "suggested")
        for targets in coverage[category].values()
        for target in targets
    }
    no_source = sum(
        _reportable_cda_target(target)
        and str(name) not in covered_targets
        and parse_location(target.get("locations", [""])[0]) is not None
        for name, target in cda.get("targets", {}).items()
    )
    return {
        "datapoints": len(model.get("fields", {})),
        "mapped_datapoints": len(coverage["selected"]),
        "mapped_leaves": sum(
            len(targets) for targets in coverage["selected"].values()
        ),
        "reviewed_datapoints": len(coverage.get("reviewed", {})),
        "suggested_datapoints": len(coverage["suggested"]),
        "suggested_leaves": sum(
            len(targets) for targets in coverage["suggested"].values()
        ),
        "no_target_datapoints": len(coverage["missing"]),
        "no_source_leaves": no_source,
    }


def format_coverage_headline(
    counts: Mapping[str, int], *, markdown: bool = True,
) -> str:
    """Format persisted coverage counts for Markdown or build logs."""
    marker = "**" if markdown else ""

    def emphasized(value: str) -> str:
        return f"{marker}{value}{marker}"

    mapped = (
        f"{counts['mapped_datapoints']} dp → "
        f"{_counted(counts['mapped_leaves'], 'leaf')}"
    )
    suggested = (
        f"{counts['suggested_datapoints']} dp → "
        f"{_counted(counts['suggested_leaves'], 'leaf')}"
    )
    return (
        f"Model: {emphasized(_counted(counts['datapoints'], 'datapoint'))} · "
        f"✓ mapped {emphasized(mapped)} · "
        f"= reviewed null {emphasized(str(counts.get('reviewed_datapoints', 0)) + ' dp')} · "
        f"! suggested {emphasized(suggested)} · "
        f"× no target {emphasized(str(counts['no_target_datapoints']) + ' dp')} · "
        f"○ no source {emphasized(_counted(counts['no_source_leaves'], 'leaf'))}"
    )


def _mapping_status(row: Mapping[str, Any]) -> str:
    rule = row.get("rule", {})
    if isinstance(rule, Mapping) and rule.get("mode") == "narrative":
        return "Narrative rule"
    if isinstance(rule, Mapping) and rule.get("structure"):
        return "Structural rule"
    if isinstance(rule, Mapping) and rule.get("mode") == "presence":
        return "Presence rule"
    if isinstance(rule, Mapping) and rule.get("mode") == "fallback_if_active":
        return "Active-branch fallback"
    if isinstance(rule, Mapping) and rule.get("mode") == "if_active":
        return "Active-branch value"
    if isinstance(rule, Mapping) and rule.get("transform"):
        return "Transform"
    return "Mapped" if isinstance(row.get("selection"), str) else "Rule"


def _configuration_instruction(row: Mapping[str, Any]) -> str:
    path = str(row["dataset_path"])
    name = str(row["dataset_name"])
    target = str(row["target"])
    rule = row.get("rule", {})
    if isinstance(rule, Mapping) and rule.get("mode") == "narrative":
        return (
            f"In `cda-mapping.json`, review the block for **{name}** in "
            f"`narratives[\"{target}\"].blocks`; it presents the source wording "
            "without asserting a structured CDA value mapping."
        )
    if isinstance(row.get("selection"), str):
        return (
            f"In `cda-mapping.json`, map **{name}** by setting "
            f"`fields[\"{path}\"]` to `\"{target}\"`."
        )
    if isinstance(rule, Mapping) and rule.get("mode") == "presence":
        return (
            f"In `cda-mapping.json`, review the rule stored at "
            f"`fields[\"{path}\"]`; it conditionally activates `\"{target}\"` "
            f"when **{name}** is true."
        )
    if isinstance(rule, Mapping) and rule.get("mode") == "fallback_if_active":
        return (
            f"In `cda-mapping.json`, review the rule stored at "
            f"`fields[\"{path}\"]`; it fills `\"{target}\"` from **{name}** "
            "only when another mapped value has already activated the target branch."
        )
    if isinstance(rule, Mapping) and rule.get("mode") == "if_active":
        return (
            f"In `cda-mapping.json`, review the rule stored at "
            f"`fields[\"{path}\"]`; it writes `\"{target}\"` from **{name}** "
            f"only when `\"{rule.get('active_if') or '?'}\"` has a mapped value."
        )
    return (
        f"In `cda-mapping.json`, review the rule stored at "
        f"`fields[\"{path}\"]`; it writes **{name}** to `\"{target}\"`."
    )


def _candidate_rows(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    primary = detail.get("primary")
    if isinstance(primary, Mapping) and primary.get("target"):
        result = "selectable after review"
        blocked = str(detail.get("runtime_blocked") or "")
        if blocked.startswith("REQUIRED_COMPANION("):
            result = "required companion missing"
        elif blocked:
            result = "rule required"
        elif primary.get("mapping") is not None:
            result = "transform required"
        rows.append({**dict(primary), "result": result, "primary": True})
        seen.add(str(primary["target"]))
    for alternative in detail.get("alternatives", []):
        if not isinstance(alternative, Mapping) or not alternative.get("target"):
            continue
        if str(alternative["target"]) in seen:
            continue
        seen.add(str(alternative["target"]))
        rows.append({
            **dict(alternative),
            "result": (
                "transform required" if alternative.get("mapping") is not None else
                "suggested without formal bridge" if alternative.get("suggested") else
                "selectable after review" if alternative.get("actionable") else
                "evidence only"
            ),
            "primary": False,
        })
    context = detail.get("context")
    if not rows and isinstance(context, Mapping) and context.get("target"):
        rows.append({
            **dict(context), "confidence": "CONTEXT", "result": "context only",
            "primary": False,
        })
    return rows


def _evidence(candidate: Mapping[str, Any]) -> str:
    return " → ".join(str(item) for item in candidate.get("chain", [])) or str(
        candidate.get("kind") or "—"
    )


def _review_required(
    model: Mapping[str, Any], mapping: Mapping[str, Any], audit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    model_fields = model.get("fields", {})
    configured = mapping.get("fields", {})
    reviews = mapping.get("field_reviews", {})
    narrative_sources = set(narrative_source_rules(mapping))
    audited = audit.get("fields", {})
    order = [path for path in model.get("order", []) if path in model_fields]
    order.extend(sorted(path for path in model_fields if path not in order))
    rows: list[dict[str, Any]] = []
    for path in order:
        if not isinstance(configured, Mapping) or configured.get(path) is not None:
            continue
        if path in narrative_sources:
            continue
        review = (
            reviews.get(path, {}) if isinstance(reviews, Mapping) else {}
        )
        review = review if isinstance(review, Mapping) else {}
        if review.get("status") == "intentionally_unmapped":
            continue
        detail = audited.get(path, {}) if isinstance(audited, Mapping) else {}
        detail = detail if isinstance(detail, Mapping) else {}
        candidates = _candidate_rows(detail)
        blocked = str(detail.get("runtime_blocked") or "")
        if blocked.startswith("REQUIRED_COMPANION("):
            companions = ", ".join(
                f"`{item}`" for item in detail.get("required_companions", [])
            )
            action = (
                "Map the required compound-datatype companion"
                + (f" {companions}" if companions else "")
                + " for the same occurrence, or retain `null`."
            )
        elif blocked:
            action = (_msg('markdown.define_the_required_repetition_or_merge_rule'))
        elif candidates:
            selectable = any(
                row.get("result") in {
                    "selectable after review", "suggested without formal bridge",
                    "transform required",
                }
                for row in candidates
            )
            action = (
                (_msg('markdown.choose_one_selectable_target_in_cda_mapping_json'))
                if selectable else
                (_msg('markdown.use_the_evidence_to_find_a_value_bearing'))
            )
        else:
            action = (_msg('markdown.find_a_representation_manually_or_retain_null'))
        rows.append({
            "path": str(path),
            "name": str(model_fields.get(path, {}).get("name") or path),
            "candidates": candidates,
            "detail": detail,
            "action": action,
            "reason": _review_reason(detail, candidates),
            "review": review,
        })
    return rows


def _review_reason(
    detail: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]],
) -> str:
    blocked = str(detail.get("runtime_blocked") or "")
    if blocked.startswith("REQUIRED_COMPANION("):
        companions = ", ".join(
            f"`{item}`" for item in detail.get("required_companions", [])
        )
        return (
            "The candidate is a child of a non-null compound CDA datatype, "
            "which also requires " + (companions or "a companion target")
            + ". No source mapping currently supplies that companion."
        )
    if blocked:
        return (
            "The best-supported CDA target is shared with another dataset field. "
            "An occurrence-alignment, repeat-by-discriminator, or coalescing rule "
            "is required before it is executable."
        )
    if any(row.get("result") == "transform required" for row in candidates):
        return (
            "The dataset and CDA represent the same information differently; review "
            "the proposed declarative transform before enabling it."
        )
    if any(row.get("result") == "suggested without formal bridge" for row in candidates):
        return (
            "A compatible writable CDA leaf has the same semantic name in the mapped "
            "context, but no formal ART-DECOR bridge proves the mapping."
        )
    reason = str(detail.get("unresolved_reason") or "")
    if reason == "ambiguous_value_target":
        return (
            "The evidence reaches more than one physical CDA value target; select "
            "or refine the structural occurrence explicitly."
        )
    if reason == "incompatible_value_type":
        return (
            "The evidence reaches a writable CDA value target, but its compiled "
            "logical value type is incompatible with the dataset value."
        )
    if reason == "datatype_component_available":
        return (
            "The evidence reaches a complex datatype container. Choose one of its "
            "compiled value-bearing datatype components."
        )
    if reason == "structural_container_available":
        return (
            "The evidence reaches a CDA structural container. Review the nearest "
            "compatible writable descendants listed as reopening evidence."
        )
    if reason == "structural_only":
        return (
            "The evidence identifies a CDA container, but not a writable "
            "value-bearing descendant."
        )
    if candidates and all(row.get("result") == "context only" for row in candidates):
        return (
            "The evidence reaches this CDA structure, but not a writable value-bearing "
            "element. The context is shown for navigation only."
        )
    if candidates and all(row.get("result") == "evidence only" for row in candidates):
        return (
            "Related CDA evidence exists, but none of it is safe enough to select as an "
            "executable target automatically."
        )
    if candidates:
        return (
            "More than one interpretation remains possible, or the best evidence still "
            "requires human confirmation."
        )
    return (_msg('markdown.no_usable_cda_target_evidence_for_dataset_datapoint'))


def _concise(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _structure_constants(row: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    structure = row.get("structure", {})
    branches = structure.get("branches", []) if isinstance(structure, Mapping) else []
    branch = next((
        item for item in branches
        if isinstance(item, Mapping)
        and str(item.get("source") or "") == row["dataset_path"]
        and str(item.get("target") or "") == row["target"]
    ), None)
    if not isinstance(branch, Mapping):
        return []
    values: list[tuple[str, Mapping[str, Any]]] = []
    for name, value in branch.get("constants", {}).items():
        if not isinstance(value, Mapping):
            continue
        values.append((str(name), value))
    return values


def _path_nodes(
    row: Mapping[str, Any], view: Mapping[str, Any]
) -> tuple[list[str], dict[int, Mapping[str, Any]]]:
    """Align a template-local target path with its physical compiled ancestors."""
    target = row["target_model"]
    segments = [part for part in str(target.get("path") or "").split("/") if part]
    element_count = len([part for part in segments if not part.startswith("@")])
    location = row["location"]
    if str(target.get("kind")) == "attribute":
        location = view["parents"].get(location, location)
    ancestors: list[tuple[int, ...]] = []
    current = location
    while current in view["nodes"]:
        if str(view["nodes"][current].get("kind") or "element") == "element":
            ancestors.append(current)
        if current not in view["parents"]:
            break
        current = view["parents"][current]
    ancestors.reverse()
    aligned = ancestors[-element_count:]
    # A contained one-leaf template (for example PatientIdentifier.id) has no
    # useful template-local parent. Include up to two named physical ancestors
    # so its preview still explains its placement in the document header.
    if element_count == 1 and aligned:
        earlier = [
            physical for physical in ancestors[:-1]
            if _leaf(view["nodes"][physical].get("name")) not in {"", "ClinicalDocument"}
        ][-2:]
        segments = [str(view["nodes"][physical].get("name")) for physical in earlier] + segments
        aligned = earlier + aligned
    return segments, {
        index: {**dict(view["nodes"][physical]), "_preview_location": physical}
        for index, physical in enumerate(aligned)
    }


def _preview_tree() -> dict[str, Any]:
    return {"children": {}}


def _add_preview_path(
    tree: dict[str, Any], row: Mapping[str, Any], view: Mapping[str, Any],
    *, fixed: Mapping[str, Any] | None = None,
) -> None:
    target = row["target_model"]
    segments, physical = _path_nodes(row, view)
    current = tree
    for index, segment in enumerate(segments):
        if segment.startswith("@"):
            current.setdefault("attrs", {}).setdefault(
                segment[1:], "{" + str(row["target"]) + "}"
            )
            return
        child = current["children"].setdefault(segment, {
            "name": _leaf(segment), "attrs": {}, "children": {}, "text": None,
            "order": physical.get(index, {}).get("_preview_location", (999999,)),
        })
        source = physical.get(index, {})
        for name, value in source.get("fixed", {}).items():
            if value is not None:
                child["attrs"].setdefault(str(name), str(value))
        for attribute in source.get("attributes", []):
            if isinstance(attribute, Mapping) and attribute.get("value") is not None:
                child["attrs"].setdefault(
                    str(attribute.get("name") or "attribute"), str(attribute["value"])
                )
        if source.get("fixed_text") is not None:
            child["text"] = str(source["fixed_text"])
        current = child

    if fixed is not None:
        for name, value in fixed.items():
            if value is not None:
                current["attrs"][str(name)] = str(value)
        return
    placeholder = "{" + str(row["target"]) + "}"
    datatype = str(target.get("datatype") or "").upper().split(".", 1)[0]
    if datatype in {"CD", "CE", "CV", "CS", "CO", "CR", "SC"}:
        if _leaf(target.get("path")) == "value":
            current["attrs"].setdefault("xsi:type", datatype)
        current["attrs"].setdefault("code", placeholder)
    elif datatype in {"ST", "ED", "TEL", "URL"}:
        current["text"] = current["text"] or placeholder
    elif datatype == "II":
        current["attrs"].setdefault("extension", placeholder)
    else:
        current["attrs"].setdefault("value", placeholder)


def _render_preview_node(node: Mapping[str, Any], depth: int = 0) -> list[str]:
    indent = "  " * depth
    attrs = "".join(
        f" {name}={quoteattr(str(value))}"
        for name, value in node.get("attrs", {}).items()
    )
    children = sorted(
        node.get("children", {}).values(), key=lambda child: child.get("order", (999999,))
    )
    text = node.get("text")
    if not children and text is None:
        return [f"{indent}<{node['name']}{attrs}/>"]
    if not children:
        return [
            f"{indent}<{node['name']}{attrs}>{escape(str(text))}</{node['name']}>"
        ]
    lines = [f"{indent}<{node['name']}{attrs}>"]
    if text is not None:
        lines.append(f"{indent}  {escape(str(text))}")
    for child in children:
        lines.extend(_render_preview_node(child, depth + 1))
    lines.append(f"{indent}</{node['name']}>")
    return lines


def _contextual_xml(
    rows: list[Mapping[str, Any]], view: Mapping[str, Any], cda: Mapping[str, Any],
) -> list[str]:
    tree = _preview_tree()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["cda_target"]), str(row["target"]))
        if key not in seen:
            seen.add(key)
            _add_preview_path(tree, row, view)
        for constant_name, value in _structure_constants(row):
            constant_target = cda.get("targets", {}).get(constant_name)
            if not isinstance(constant_target, Mapping):
                continue
            locations = constant_target.get("locations", [])
            if len(locations) != 1:
                continue
            location = parse_location(locations[0])
            if location is None:
                continue
            constant_row = {
                **dict(row), "target": constant_name, "cda_target": constant_name,
                "target_model": constant_target, "location": location,
            }
            _add_preview_path(tree, constant_row, view, fixed=value)
    lines: list[str] = []
    for root in tree["children"].values():
        lines.extend(_render_preview_node(root))
    return lines


def _configuration_excerpt(
    rows: list[Mapping[str, Any]], mapping: Mapping[str, Any]
) -> str:
    def compact_rule(rule: Mapping[str, Any]) -> dict[str, Any]:
        result = {
            key: rule[key] for key in (
                "target", "cda_target", "structure", "branch", "mode"
            ) if rule.get(key) is not None
        }
        transform = rule.get("transform")
        if isinstance(transform, Mapping):
            compact_transform = {
                key: transform[key] for key in (
                    "type", "select", "null_flavor", "value_set", "reason",
                )
                if transform.get(key) is not None
            }
            values = transform.get("map")
            if isinstance(values, Mapping):
                compact_transform["map"] = (
                    f"{len(values)} configured values; see cda-mapping.json"
                )
            allowed = transform.get("allowed")
            if isinstance(allowed, list):
                compact_transform["allowed"] = (
                    f"{len(allowed)} exact code/code-system pairs; see cda-mapping.json"
                )
            source_options = transform.get("source_options")
            if isinstance(source_options, Mapping):
                compact_transform["source_options"] = (
                    f"{len(source_options)} exact source concept identities; "
                    "see cda-mapping.json"
                )
            result["transform"] = compact_transform
        return result

    def compact_selection(value: Any) -> Any:
        if isinstance(value, list):
            return [compact_rule(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            return compact_rule(value)
        return value

    field_rows = [row for row in rows if not row.get("narrative")]
    fields = {
        str(row["dataset_path"]): compact_selection(
            mapping.get("fields", {}).get(row["dataset_path"])
        )
        for row in field_rows
    }
    structure_names = {
        str(row["rule"].get("structure")) for row in field_rows
        if row["rule"].get("structure")
    }
    excerpt: dict[str, Any] = {}
    if fields:
        excerpt["fields"] = fields
    narrative_targets = list(dict.fromkeys(
        str(row["target"]) for row in rows if row.get("narrative")
    ))
    if narrative_targets:
        configured_narratives = mapping.get("narratives", {})
        excerpt["narratives"] = {
            target: configured_narratives.get(target, {})
            for target in narrative_targets
        }
    if structure_names:
        excerpt["structures"] = {}
        for name in sorted(structure_names):
            structure = mapping.get("structures", {}).get(name, {})
            compact_structure = {
                key: structure[key] for key in (
                    "type", "source_group", "target_repeat", "target", "policy",
                    "sources", "separator", "transform", "null_flavor", "reason",
                ) if structure.get(key) is not None
            }
            if structure.get("branches"):
                compact_structure["branches"] = [
                    {
                        key: branch[key] for key in (
                            "source", "target", "cda_target", "branch", "constants"
                        ) if branch.get(key) is not None
                    }
                    for branch in structure["branches"] if isinstance(branch, Mapping)
                ]
            excerpt["structures"][name] = compact_structure
    return json.dumps(excerpt, ensure_ascii=False, indent=2)


def _review_dataset_tree(
    model: Mapping[str, Any], review_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Render only unresolved datapoints and the groups needed for context."""
    groups = model.get("groups", {})
    fields = model.get("fields", {})
    review_by_path = {str(row["path"]): row for row in review_rows}
    included_groups: set[str] = set()
    for path in review_by_path:
        parent = str(fields.get(path, {}).get("parent") or "") or None
        while parent:
            included_groups.add(parent)
            parent = str(groups.get(parent, {}).get("parent") or "") or None

    children: dict[str | None, list[tuple[str, str]]] = defaultdict(list)
    for path, group in groups.items():
        if str(path) not in included_groups:
            continue
        parent = str(group.get("parent") or "") or None
        children[parent].append(("group", str(path)))
    for path in _ordered_model_paths(model):
        if path not in review_by_path:
            continue
        parent = str(fields.get(path, {}).get("parent") or "") or None
        children[parent].append(("field", path))

    lines = ["```text", ('   ' + _msg('markdown.dataset_decisions'))]

    def render(parent: str | None, stem: str = "") -> None:
        items = children.get(parent, [])
        for index, (kind, path) in enumerate(items):
            last = index == len(items) - 1
            branch = "└──" if last else "├──"
            next_stem = stem + ("    " if last else "│   ")
            if kind == "group":
                name = str(groups.get(path, {}).get("name") or path.rsplit(".", 1)[-1])
                lines.append(f"   {stem}{branch} {name}")
                render(path, next_stem)
                continue
            row = review_by_path[path]
            detail = row.get("detail", {})
            detail = detail if isinstance(detail, Mapping) else {}
            gap = detail.get("gap", {})
            gap = gap if isinstance(gap, Mapping) else {}
            status = "!" if (
                row.get("candidates") or detail.get("primary")
                or detail.get("runtime_blocked")
            ) else "×"
            inventory = detail.get("possible_targets", {})
            inventory = inventory if isinstance(inventory, Mapping) else {}
            possible_count = len(inventory.get("items", []))
            gate = ":".join(
                str(gap.get(key) or "") for key in ("gate", "kind")
            ).strip(":")
            notes = [value for value in (
                gate,
                f"{possible_count} possible target{'s' if possible_count != 1 else ''}"
                if possible_count else (_msg('markdown.no_generated_target_inventory')),
            ) if value]
            name = str(fields.get(path, {}).get("name") or path.rsplit(".", 1)[-1])
            lines.append(
                f"{status:<3}{stem}{branch} {name} [{'; '.join(notes)}]"
            )

    render(None)
    return lines + ["```"]


def _review_target_rows(
    review_rows: Sequence[Mapping[str, Any]], cda: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Combine evidence candidates and unproven inventory rows for one tree."""
    combined: dict[str, dict[str, Any]] = {}
    targets = cda.get("targets", {})
    for review in review_rows:
        field_path = str(review.get("path") or "")
        field_name = str(review.get("name") or field_path)
        for candidate in review.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            name = str(candidate.get("target") or "")
            target = targets.get(name, {}) if isinstance(targets, Mapping) else {}
            if (
                not name or not isinstance(target, Mapping)
                or not target.get("writable")
                or len(target.get("locations", [])) != 1
            ):
                continue
            row = combined.setdefault(name, {
                "name": name, "target": target, "fields": [],
                "evidence": False, "possible": False, "claimed": False,
                "same_instance_claimed": False,
            })
            row["evidence"] = True
            row["fields"].append((field_path, field_name))
        detail = review.get("detail", {})
        detail = detail if isinstance(detail, Mapping) else {}
        inventory = detail.get("possible_targets", {})
        inventory = inventory if isinstance(inventory, Mapping) else {}
        for item in inventory.get("items", []):
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("target") or "")
            target = targets.get(name, {}) if isinstance(targets, Mapping) else {}
            if not name or not isinstance(target, Mapping):
                continue
            row = combined.setdefault(name, {
                "name": name, "target": target, "fields": [],
                "evidence": False, "possible": False, "claimed": False,
                "same_instance_claimed": False,
            })
            row["possible"] = True
            row["claimed"] = bool(row["claimed"] or item.get("already_claimed"))
            row["same_instance_claimed"] = bool(
                row["same_instance_claimed"]
                or item.get("containing_instance_claimed_by")
            )
            row["fields"].append((field_path, field_name))
    for row in combined.values():
        row["fields"] = list(dict.fromkeys(row["fields"]))
    return sorted(combined.values(), key=lambda row: (
        parse_location(row["target"].get("locations", [""])[0]) or (999999,),
        str(row["name"]),
    ))


def _review_cda_tree(
    view: Mapping[str, Any], cda: Mapping[str, Any],
    review_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Render the pruned CDA hierarchy containing only reviewable leaves."""
    rows = _review_target_rows(review_rows, cda)
    by_section: dict[tuple[int, ...] | None, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        location = parse_location(row["target"].get("locations", [""])[0])
        if location is None:
            continue
        row["location"] = location
        by_section[_section_of(location, view["nodes"], view["parents"])].append(row)

    template = view["template"]
    title = str(template.get("display_name") or template.get("name") or "ClinicalDocument")
    lines = ["```text", f"   {title} (review candidate surface)"]
    all_areas: list[tuple[str, tuple[int, ...] | None]] = [
        ("Document header", None)
    ] + [
        (_section_label(section, view["nodes"], cda), section)
        for section in view["sections"]
    ]
    areas = [(label, section) for label, section in all_areas if by_section.get(section)]
    for area_index, (area_label, section) in enumerate(areas):
        area_last = area_index == len(areas) - 1
        area_branch = "└──" if area_last else "├──"
        area_stem = "    " if area_last else "│   "
        lines.append(f"   {area_branch} {area_label}")
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in by_section[section]:
            target = row["target"]
            key = (
                str(target.get("template_display_name") or target.get("template_name") or "CDA template"),
                str(target.get("template_id") or ""),
                str(target.get("template_effective_date") or ""),
            )
            grouped.setdefault(key, []).append(row)
        template_groups = list(grouped.items())
        for group_index, ((display, template_id, effective), group_rows) in enumerate(template_groups):
            group_last = group_index == len(template_groups) - 1
            group_branch = "└──" if group_last else "├──"
            group_stem = area_stem + ("    " if group_last else "│   ")
            lines.append(
                f"   {area_stem}{group_branch} {display} · "
                f"{template_id or 'unknown'} @ {effective or 'dynamic'}"
            )
            trie: dict[str, Any] = {"children": {}, "rows": []}
            for row in group_rows:
                node = trie
                for segment in str(row["target"].get("path") or "value").split("/"):
                    if not segment:
                        continue
                    node = node["children"].setdefault(
                        segment, {"children": {}, "rows": []}
                    )
                node["rows"].append(row)

            def render_trie(node: Mapping[str, Any], stem: str) -> None:
                items = list(node.get("children", {}).items())
                for item_index, (segment, child) in enumerate(items):
                    last = item_index == len(items) - 1
                    branch = "└──" if last else "├──"
                    next_stem = stem + ("    " if last else "│   ")
                    leaf_rows = child.get("rows", [])
                    if leaf_rows:
                        status = "!" if any(row["evidence"] for row in leaf_rows) else "?"
                        target_names = ", ".join(
                            "{" + str(row["name"]) + "}" for row in leaf_rows
                        )
                        target = leaf_rows[0]["target"]
                        maximum = target.get("max")
                        card = f"{target.get('min', 0)}..{maximum if maximum is not None else '*'}"
                        meta = " ".join(value for value in (
                            str(target.get("datatype") or ""), card,
                            str(target.get("conformance") or ""),
                        ) if value)
                        fields = ", ".join(
                            name for row in leaf_rows for _, name in row["fields"]
                        )
                        flags = []
                        if any(row["claimed"] for row in leaf_rows):
                            flags.append("already claimed")
                        if any(row["same_instance_claimed"] for row in leaf_rows):
                            flags.append("same occurrence in use")
                        suffix = f"; {'; '.join(flags)}" if flags else ""
                        lines.append(
                            f"{status:<3}{stem}{branch} {_leaf(segment)} {target_names} "
                            f"[{meta}] ← {fields}{suffix}"
                        )
                    else:
                        lines.append(f"   {stem}{branch} {_leaf(segment)}")
                    render_trie(child, next_stem)

            render_trie(trie, group_stem)
    return lines + ["```"]


def _binding_label(binding: Any) -> str:
    if not isinstance(binding, Mapping):
        return str(binding or "")
    name = str(binding.get("display_name") or binding.get("name") or "")
    identity = str(binding.get("id") or "")
    revision = str(
        binding.get("effective_date") or binding.get("flexibility") or ""
    )
    exact = identity + (f"@{revision}" if revision else "")
    return f"{name} ({exact})" if name and exact else name or exact


def _possible_target_groups(
    detail: Mapping[str, Any],
) -> list[tuple[tuple[str, str, str, str, str], list[Mapping[str, Any]]]]:
    inventory = detail.get("possible_targets", {})
    items = inventory.get("items", []) if isinstance(inventory, Mapping) else []
    grouped: dict[
        tuple[str, str, str, str, str], list[Mapping[str, Any]]
    ] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        template = item.get("template", {})
        template = template if isinstance(template, Mapping) else {}
        key = (
            str(template.get("display_name") or template.get("name") or "Unnamed template"),
            str(template.get("id") or ""),
            str(template.get("effective_date") or ""),
            str(template.get("location") or ""),
            str(template.get("description") or ""),
        )
        grouped.setdefault(key, []).append(item)
    return list(grouped.items())


def _comment_text(value: Any) -> str:
    return " ".join(str(value or "").replace("--", "—").split())


def _annotated_template_excerpt(
    group_key: tuple[str, str, str, str, str],
    candidate_items: Sequence[Mapping[str, Any]],
    cda: Mapping[str, Any],
) -> list[str]:
    """Render a compact constraint skeleton for one candidate template group."""
    display, template_id, effective, occurrence, template_description = group_key
    candidate_names = {
        str(item.get("target") or "") for item in candidate_items
        if item.get("target")
    }
    candidate_paths = {
        str(item.get("path") or "") for item in candidate_items if item.get("path")
    }
    candidate_by_name = {
        str(item.get("target") or ""): item for item in candidate_items
        if item.get("target")
    }
    context: list[tuple[str, Mapping[str, Any]]] = []
    targets = cda.get("targets", {})
    for name, target in targets.items() if isinstance(targets, Mapping) else ():
        if not isinstance(target, Mapping):
            continue
        locations = [str(value) for value in target.get("locations", [])]
        if (
            str(target.get("template_id") or "") != template_id
            or len(locations) != 1
            or (
                occurrence and occurrence != "document"
                and not locations[0].startswith(occurrence + ".")
            )
        ):
            continue
        path = str(target.get("path") or "")
        declared = bool(target.get("element_id")) and not target.get("datatype_derived")
        candidate_ancestor = any(
            candidate_path == path or candidate_path.startswith(path.rstrip("/") + "/")
            for candidate_path in candidate_paths
        )
        informative = bool(
            target.get("mandatory") or int(target.get("min") or 0) >= 1
            or target.get("fixed") or target.get("codes")
        )
        if str(name) in candidate_names or candidate_ancestor or (declared and informative):
            context.append((str(name), target))

    trie: dict[str, Any] = {"children": {}, "rows": [], "attributes": []}
    for name, target in sorted(context, key=lambda row: (
        str(row[1].get("path") or ""), row[0],
    )):
        node = trie
        parts = [part for part in str(target.get("path") or "").split("/") if part]
        for index, part in enumerate(parts):
            if part.startswith("@") and index == len(parts) - 1:
                node["attributes"].append((name, target))
                break
            node = node["children"].setdefault(
                part, {"children": {}, "rows": [], "attributes": []}
            )
            if index == len(parts) - 1:
                node["rows"].append((name, target))

    lines = [
        "```xml",
        f"<!-- Template: {_comment_text(display)} -->",
        f"<!-- OID/revision: {_comment_text(template_id)} @ {_comment_text(effective or 'dynamic')} -->",
    ]
    if template_description:
        lines.append(f"<!-- Description: {_comment_text(template_description)} -->")
    lines.append(f"<!-- Contained-template occurrence: {_comment_text(occurrence or 'document')} -->")
    lines.append("<!-- Read-only constraint skeleton generated from cda.json; edit cda-mapping.json. -->")

    def render_node(part: str, node: Mapping[str, Any], depth: int) -> None:
        indent = "  " * depth
        rows = list(node.get("rows", []))
        names = [name for name, _ in rows if name in candidate_names]
        primary = next(
            (target for name, target in rows if name in candidate_names),
            rows[0][1] if rows else {},
        )
        item = candidate_by_name.get(names[0], {}) if names else {}
        if names:
            lines.append(f"{indent}<!-- Possible target (unproven): {_comment_text(', '.join(names))} -->")
        description = str(primary.get("description") or "")
        if description:
            lines.append(f"{indent}<!-- Name/description: {_comment_text(description)} -->")
        datatype = str(primary.get("datatype") or "")
        if primary:
            maximum = primary.get("max")
            cardinality = f"{primary.get('min', 0)}..{maximum if maximum is not None else '*'}"
            conformance = str(primary.get("conformance") or "—")
            lines.append(
                f"{indent}<!-- Datatype: {_comment_text(datatype or '—')}; "
                f"cardinality: {cardinality}; conformance: {_comment_text(conformance)} -->"
            )
        for binding in primary.get("value_set_bindings", []) if primary else []:
            lines.append(
                f"{indent}<!-- Bound ValueSet: {_comment_text(_binding_label(binding))} -->"
            )
        if item:
            if item.get("claimed_by"):
                lines.append(
                    f"{indent}<!-- Already claimed by: "
                    f"{_comment_text(', '.join(str(value) for value in item['claimed_by']))} -->"
                )
            instance_claims = item.get("containing_instance_claimed_by", [])
            if instance_claims:
                claimed = "; ".join(
                    f"{claim.get('target')} ← {', '.join(str(value) for value in claim.get('fields', []))}"
                    for claim in instance_claims if isinstance(claim, Mapping)
                )
                lines.append(
                    f"{indent}<!-- Same template occurrence already carries: {_comment_text(claimed)} -->"
                )
            if item.get("requires_occurrence_rule"):
                lines.append(f"{indent}<!-- An explicit occurrence rule is required. -->")
            if item.get("non_null_requires"):
                lines.append(
                    f"{indent}<!-- Non-null value also requires: "
                    f"{_comment_text(', '.join(str(value) for value in item['non_null_requires']))} -->"
                )

        for attribute_name, attribute in node.get("attributes", []):
            if attribute_name not in candidate_names:
                continue
            attribute_item = candidate_by_name.get(attribute_name, {})
            lines.append(
                f"{indent}<!-- Possible attribute target (unproven): "
                f"{_comment_text(attribute_name)} -->"
            )
            attribute_description = str(attribute.get("description") or "")
            if attribute_description:
                lines.append(
                    f"{indent}<!-- Name/description: "
                    f"{_comment_text(attribute_description)} -->"
                )
            maximum = attribute.get("max")
            cardinality = (
                f"{attribute.get('min', 0)}.."
                f"{maximum if maximum is not None else '*'}"
            )
            lines.append(
                f"{indent}<!-- Datatype: "
                f"{_comment_text(attribute.get('datatype') or '—')}; "
                f"cardinality: {cardinality}; conformance: "
                f"{_comment_text(attribute.get('conformance') or '—')} -->"
            )
            for binding in attribute.get("value_set_bindings", []):
                lines.append(
                    f"{indent}<!-- Bound ValueSet: "
                    f"{_comment_text(_binding_label(binding))} -->"
                )
            if attribute_item.get("claimed_by"):
                lines.append(
                    f"{indent}<!-- Already claimed by: "
                    f"{_comment_text(', '.join(str(value) for value in attribute_item['claimed_by']))} -->"
                )
            attribute_instance_claims = attribute_item.get(
                "containing_instance_claimed_by", []
            )
            if attribute_instance_claims:
                claimed = "; ".join(
                    f"{claim.get('target')} ← "
                    f"{', '.join(str(value) for value in claim.get('fields', []))}"
                    for claim in attribute_instance_claims
                    if isinstance(claim, Mapping)
                )
                lines.append(
                    f"{indent}<!-- Same template occurrence already carries: "
                    f"{_comment_text(claimed)} -->"
                )
            if attribute_item.get("requires_occurrence_rule"):
                lines.append(
                    f"{indent}<!-- An explicit occurrence rule is required. -->"
                )
            if attribute_item.get("non_null_requires"):
                lines.append(
                    f"{indent}<!-- Non-null value also requires: "
                    f"{_comment_text(', '.join(str(value) for value in attribute_item['non_null_requires']))} -->"
                )

        attrs: dict[str, str] = {
            str(key): str(value) for key, value in primary.get("fixed", {}).items()
            if value is not None
        } if primary else {}
        codes = primary.get("codes", []) if primary else []
        if len(codes) == 1 and isinstance(codes[0], Mapping):
            code = codes[0]
            if code.get("code"):
                attrs.setdefault("code", str(code["code"]))
            if code.get("code_system"):
                attrs.setdefault("codeSystem", str(code["code_system"]))
            if code.get("display_name"):
                attrs.setdefault("displayName", str(code["display_name"]))
        for attribute_name, attribute in node.get("attributes", []):
            attr = str(attribute.get("element_name") or attribute.get("path") or "attribute")
            attr = _leaf(attr).lstrip("@")
            fixed = attribute.get("fixed", {})
            if isinstance(fixed, Mapping) and fixed.get("value") is not None:
                attrs[attr] = str(fixed["value"])
            elif attribute_name in candidate_names:
                attrs[attr] = "{" + attribute_name + "}"
        if names and not primary.get("has_children"):
            representation = primary.get("value_representation", {})
            representation = representation if isinstance(representation, Mapping) else {}
            kind = str(representation.get("kind") or "")
            placeholder = "{" + names[0] + "}"
            if kind == "coded":
                attrs.setdefault("code", placeholder)
            elif kind == "identifier":
                attrs.setdefault("extension", placeholder)
            elif kind not in {"element_text", ""}:
                attrs.setdefault(str(representation.get("scalar_attribute") or "value"), placeholder)
        attr_text = "".join(
            f" {key}={quoteattr(value)}" for key, value in attrs.items()
        )
        children = list(node.get("children", {}).items())
        text_value = "{" + names[0] + "}" if names and (
            primary.get("value_representation", {}).get("kind") == "element_text"
            if isinstance(primary.get("value_representation"), Mapping) else False
        ) else str(primary.get("fixed_text") or "")
        tag = _leaf(part)
        if not children and not text_value:
            lines.append(f"{indent}<{tag}{attr_text}/>")
            return
        lines.append(f"{indent}<{tag}{attr_text}>")
        if text_value:
            lines.append(f"{indent}  {escape(text_value)}")
        for child_part, child in children:
            render_node(str(child_part), child, depth + 1)
        lines.append(f"{indent}</{tag}>")

    for part, node in trie["children"].items():
        render_node(str(part), node, 0)
    lines += ["```", ""]
    return lines


def _possible_target_lines(
    detail: Mapping[str, Any], cda: Mapping[str, Any],
) -> list[str]:
    groups = _possible_target_groups(detail)
    if not groups:
        return []
    out = [
        (_msg('markdown.possible_targets_unproven')),
        "",
        (_msg('markdown.these_type_compatible_writable_descendants_are_an_admissibility')),
        "",
    ]
    for key, rows in groups:
        display, template_id, effective, location, template_description = key
        out += [
            f"##### {display}",
            "",
            f"Contained template: `{template_id}` @ `{effective or 'dynamic'}`; "
            f"occurrence `{location or 'document'}`",
            "",
        ]
        if template_description:
            out += [template_description, ""]
        out += [
            "| Target / CDA path | Datatype | Cardinality | Conformance | Description | Bound value sets | Decision constraints |",
            "|---|---|---|---|---|---|---|",
        ]
        for item in rows:
            cardinality = item.get("cardinality", {})
            cardinality = cardinality if isinstance(cardinality, Mapping) else {}
            minimum = cardinality.get("min")
            maximum = cardinality.get("max")
            card = f"{minimum if minimum is not None else 0}..{maximum if maximum is not None else '*'}"
            constraints: list[str] = []
            if item.get("claimed_by"):
                constraints.append(
                    "already claimed by "
                    + ", ".join(str(value) for value in item["claimed_by"])
                )
            instance_claims = item.get("containing_instance_claimed_by", [])
            if instance_claims:
                constraints.append(
                    "same occurrence: " + "; ".join(
                        f"{claim.get('target')} ← "
                        + ", ".join(str(value) for value in claim.get("fields", []))
                        for claim in instance_claims if isinstance(claim, Mapping)
                    )
                )
            if item.get("requires_occurrence_rule"):
                constraints.append("occurrence rule required")
            if item.get("repeat_ancestors"):
                constraints.append(
                    "repeatable ancestors: "
                    + ", ".join(
                        str(value) for value in item["repeat_ancestors"]
                    )
                )
            if item.get("non_null_requires"):
                constraints.append(
                    "non-null requires "
                    + ", ".join(str(value) for value in item["non_null_requires"])
                )
            for conflict in item.get("conformance_conflicts", []):
                if isinstance(conflict, Mapping):
                    constraints.append(
                        "unavailable: " + str(
                            conflict.get("message") or "datatype constraint conflict"
                        )
                    )
            target_text = f"`{item.get('target')}`<br>`{item.get('path') or '—'}`"
            bindings = ", ".join(
                _binding_label(binding) for binding in item.get("bound_value_sets", [])
            )
            out.append(
                "| " + " | ".join([
                    _md(target_text), _md(item.get("datatype") or "—"),
                    _md(card), _md(item.get("conformance") or "—"),
                    _md(item.get("description") or "—"), _md(bindings or "—"),
                    _md("; ".join(constraints) or "available; semantics unproven"),
                ]) + " |"
            )
        out += ["", (_msg('markdown.annotated_template_skeleton')), ""]
        out.extend(_annotated_template_excerpt(key, rows, cda))
    return out


def _structural_and_completion_lines(
    mapping: Mapping[str, Any], cda: Mapping[str, Any],
) -> list[str]:
    lines: list[str] = []
    structures = mapping.get("structures", {})
    if isinstance(structures, Mapping) and structures:
        lines += [
            (_msg('markdown.accepted_structural_rules')),
            "",
            (_msg('markdown.these_rules_create_or_coordinate_cda_occurrences_they')),
            "",
        ]
        for name, rule in structures.items():
            if not isinstance(rule, Mapping):
                continue
            kind = str(rule.get("type") or "unknown")
            if kind == "repeat_by_discriminator":
                branches = [
                    f"`{branch.get('source')}` → `{{{branch.get('target')}}}`"
                    for branch in rule.get("branches", []) if isinstance(branch, Mapping)
                ]
                explanation = (
                    "Create one discriminated CDA occurrence for each present "
                    "branch: " + "; ".join(branches) + "."
                )
                if rule.get("coalesce_existing_discriminator"):
                    explanation += (
                        " Merge a branch with an existing occurrence when their "
                        "coded discriminators are equal."
                    )
            elif kind == "for_each":
                explanation = (
                    f"Create one `{rule.get('target_repeat')}` occurrence for every "
                    f"`{rule.get('source_group')}` occurrence."
                )
            elif kind == "coalesce":
                explanation = (
                    f"Assign `{rule.get('target')}` from the configured sources using "
                    f"`{rule.get('policy')}`."
                )
            elif kind == "concatenate":
                sources = [
                    str(item.get("source") or "")
                    if isinstance(item, Mapping) else str(item)
                    for item in rule.get("sources", [])
                ]
                explanation = (
                    f"Join present values from {', '.join(f'`{item}`' for item in sources)} "
                    f"with `{rule.get('separator', '; ')}` and assign "
                    f"`{rule.get('target')}`."
                )
            elif kind == "compose_coded":
                source_roles = {
                    str(item.get("role") or ""): str(item.get("source") or "")
                    for item in rule.get("sources", [])
                    if isinstance(item, Mapping)
                }
                explanation = (
                    f"Compose `{rule.get('target')}` from code "
                    f"`{source_roles.get('code', '')}` and display name "
                    f"`{source_roles.get('display_name', '')}`. If only the name is "
                    f"present, write `nullFlavor=\"{rule.get('null_flavor', 'NA')}\"` "
                    "and preserve that wording in `originalText`."
                )
            else:
                explanation = "Review this structural rule in `cda-mapping.json`."
            lines += [f"- `{name}`: {explanation}", ""]

    narratives = mapping.get("narratives", {})
    if isinstance(narratives, Mapping) and narratives:
        lines += [
            (_msg('markdown.accepted_narrative_only_rules')),
            "",
            (_msg('markdown.these_reviewed_rules_preserve_source_wording_in_a')),
            "",
        ]
        for block in narrative_blocks(mapping):
            decision = f" [{block.get('decision')}]" if block.get("decision") else ""
            lines.append(
                f"- `{block.get('source')}` → `{{{block.get('section_target')}}}` as "
                f"**{block.get('label')}** (`{block.get('type')}`){decision}: "
                f"{block.get('reason') or 'Reviewed narrative presentation.'}"
            )
        lines.append("")

    field_reviews = mapping.get("field_reviews", {})
    if isinstance(field_reviews, Mapping) and field_reviews:
        lines += [
            (_msg('markdown.reviewed_intentional_non_mappings')),
            "",
            (_msg('markdown.these_dataset_fields_remain_explicit_null_selections_by')),
            "",
        ]
        for path, review in field_reviews.items():
            if not isinstance(review, Mapping):
                continue
            decision = (
                f" ({review.get('decision')})" if review.get("decision") else ""
            )
            lines.append(
                f"- `{path}` — {review.get('reason') or 'No reason recorded'}{decision}"
            )
        lines.append("")

    target_defaults = mapping.get("target_defaults", {})
    lines += [
        (_msg('markdown.accepted_required_cda_completion')),
        "",
        _msg("markdown.general_rule_an_active_required_nullable_leaf_without", null_flavor=required_unmapped_null_flavor(mapping)),
        "",
    ]
    if isinstance(target_defaults, Mapping) and target_defaults:
        lines += [
            (_msg('markdown.the_following_reviewed_targets_use_a_more_specific')),
            "",
            "| CDA template value | Default | Reason |",
            "|---|---|---|",
        ]
        targets = cda.get("targets", {})
        for name, rule in target_defaults.items():
            target = targets.get(str(name), {}) if isinstance(targets, Mapping) else {}
            label = target.get("template_display_name") or target.get("template_name") or "CDA"
            leaf = _leaf(target.get("path")) or str(name).split(".")[-1]
            if isinstance(rule, Mapping) and "nullFlavor" in rule:
                rendered_default = f'nullFlavor="{rule.get("nullFlavor") or ""}"'
            elif isinstance(rule, Mapping) and "value" in rule:
                rendered_default = (
                    "value=" + json.dumps(rule.get("value"), ensure_ascii=False)
                )
            else:
                rendered_default = "invalid default"
            reason = rule.get("reason") if isinstance(rule, Mapping) else ""
            lines.append(
                f"| {label} → {leaf} `{{{name}}}` | `{rendered_default}` | "
                f"{reason or 'Reviewed target-specific completion rule.'} |"
            )
        lines.append("")
    else:
        lines += [(_msg('markdown.no_target_specific_defaults_are_configured')), ""]
    site_requirements = mapping.get("site_requirements", {})
    if isinstance(site_requirements, Mapping) and site_requirements:
        lines += [
            (_msg('markdown.required_site_configuration')),
            "",
            "These portable declarations assign ownership but contain no site "
            "value. `check-cda-mapping` validates the association; site/input "
            "validation requires the configured value:",
            "",
            (_msg('markdown.cda_target_site_configuration_reason')),
            "|---|---|---|",
        ]
        for name, rule in sorted(site_requirements.items()):
            channel = (
                str(rule.get("channel") or "?")
                if isinstance(rule, Mapping) else "?"
            )
            reason = (
                str(rule.get("reason") or "")
                if isinstance(rule, Mapping) else "Invalid declaration."
            )
            lines.append(
                f"| `{{{name}}}` | `site.cda.{channel}` | "
                f"{reason or 'A site value is required.'} |"
            )
        lines.append("")
    else:
        lines += [(_msg('markdown.no_cda_values_are_explicitly_delegated_to_site')), ""]
    gaps = required_construction_gaps(cda, mapping)
    if gaps:
        lines += [
            (_msg('markdown.configuration_still_required')),
            "",
            "The generated proposal cannot yet construct every active mandatory "
            "CDA slot. Supply each value through a reviewed mapping, site value, "
            "structural constant, or target default that the compiled target "
            "legally permits:",
            "",
        ]
        lines.extend(f"- {problem}" for problem in gaps)
        lines.append("")
    else:
        lines += [
            (_msg('markdown.all_active_mandatory_cda_slots_have_a_configured')), "",
        ]
    return lines


@localized
def render_accepted_cda_mappings_markdown(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any],
    *, output_language: str = "en",
) -> str:
    """Render the accepted mappings in the former concise-guide presentation."""
    view = _mapping_view(model, cda, mapping)
    rows_by_section = view["rows"]
    areas: list[tuple[str, list[Mapping[str, Any]]]] = [
        ("Document header", rows_by_section.get(None, []))
    ] + [
        (_section_label(section, view["nodes"], cda), rows_by_section.get(section, []))
        for section in view["sections"]
    ]
    mapped_datapoints = {
        str(row["dataset_path"])
        for rows in rows_by_section.values() for row in rows
    }
    mapped_leaves = sum(len(rows) for rows in rows_by_section.values())
    lines = [
        (_msg('markdown.accepted_mappings')),
        "",
        f"{_msg('markdown.this_section_records')}{len(mapped_datapoints)}**{_msg('markdown.executable_dataset_datapoints_writing')}{mapped_leaves}**{_msg('markdown.logical_cda_leaves_edit_cda_mapping_json_the')}",
        "",
        (_msg('markdown.sections_and_entities')),
        "",
    ]
    example_written = False
    configured_complex_fields: set[str] = set()
    for area_name, rows in areas:
        if not rows:
            continue
        lines += [f"### {area_name}", ""]
        for entity, entity_rows in _entity_groups(rows):
            first_target = entity_rows[0]["target_model"]
            identity = (
                f"`{first_target.get('template_id')}` @ "
                f"`{first_target.get('template_effective_date')}`"
            )
            lines += [f"#### {entity}", "", f"Template: {identity}", ""]
            template_description = str(first_target.get("template_description") or "")
            if template_description:
                lines += [_concise(template_description), ""]
            descriptions = [
                _concise(row["target_model"].get("description"))
                for row in entity_rows if row["target_model"].get("description")
            ]
            if descriptions:
                lines += [descriptions[0], ""]
            lines += [
                (_msg('markdown.name_in_dataset_model_json_datapoint_cda_mapping')),
                "|---|---|---|---|---|",
            ]
            for row in entity_rows:
                lines.append(
                    f"| {_md(row['dataset_name'])} | `{_md(row['dataset_path'])}` | "
                    f"`{_md(row['target'])}` | {_md(_target_label(row))} | "
                    f"{_mapping_status(row)} |"
                )
            lines.append("")

            coded_fallbacks = [
                row for row in entity_rows
                if isinstance(row.get("rule"), Mapping)
                and isinstance(row["rule"].get("transform"), Mapping)
                and row["rule"]["transform"].get("type") == "coded_fallback"
            ]
            if coded_fallbacks:
                lines += [
                    "Target-governed coded fallback: an exact admitted code/code-system "
                    "pair is written as that code. Any other source value is written as "
                    "`nullFlavor=\"OTH\"`, and its wording is preserved in the compiled "
                    "coded datatype's `originalText` child.",
                    "",
                ]

            reviewed_coded_maps = [
                row for row in entity_rows
                if isinstance(row.get("rule"), Mapping)
                and isinstance(row["rule"].get("transform"), Mapping)
                and row["rule"]["transform"].get("type")
                == "reviewed_coded_map"
            ]
            if reviewed_coded_maps:
                lines += [
                    "Reviewed finite coded map: every executable source option is "
                    "pinned to its exact owner concept identity and converted only "
                    "to the explicitly reviewed value for this exact target "
                    "ValueSet revision. This does not complete the unresolved "
                    "upstream terminology. Reviewed OTH/UNC cases preserve the "
                    "source wording in the compiled coded datatype's "
                    "`originalText` child.",
                    "",
                ]

            complex_mapping = any(
                not isinstance(row["selection"], str) for row in entity_rows
            )
            excerpt_rows = [
                row for row in entity_rows
                if str(row["dataset_path"]) not in configured_complex_fields
            ]
            show_example = (complex_mapping and bool(excerpt_rows)) or not example_written
            if show_example:
                lines += [
                    *[_configuration_instruction(row) for row in excerpt_rows or entity_rows],
                    "",
                    (_msg('markdown.abridged_configuration_excerpt_edit_the_corresponding_entry_in')),
                    "",
                    "```json",
                    _configuration_excerpt(excerpt_rows or entity_rows, mapping),
                    "```",
                    "",
                ]
                example_written = True
                if complex_mapping:
                    configured_complex_fields.update(
                        str(row["dataset_path"]) for row in excerpt_rows
                    )
            if show_example or complex_mapping:
                lines += [
                    (_msg('markdown.resulting_cda_placement_read_only_consequence_of_the')),
                    "",
                    _msg("markdown.text_in_braces_names_a_generated_cda_datapoint"),
                    "",
                    "```xml",
                    "<!-- Read-only illustration; do not copy this into cda-mapping.json. -->",
                ]
                lines.extend(_contextual_xml(entity_rows, view, cda))
                lines += ["```", ""]
    lines.extend(_structural_and_completion_lines(mapping, cda))
    return ("\n".join(lines).rstrip() + "\n")


@localized
def render_cda_mapping_markdown(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> str:
    """Render the human review workbench for unresolved mappings only."""
    view = _mapping_view(model, cda, mapping)
    review_rows = _review_required(model, mapping, audit)
    headline_counts = coverage_headline_counts(model, cda, mapping, audit)
    template = view["template"]
    lines = [
        (_msg('markdown.dataset_to_cda_mapping_decisions')),
        "",
        f"Template: **{template.get('display_name') or template.get('name') or 'ClinicalDocument'}** "
        f"(`{template.get('id')}` @ `{template.get('effective_date')}`)",
        "",
        format_coverage_headline(headline_counts),
        "",
        (_msg('markdown.this_file_is_the_manual_decision_workbench_it')),
        "",
        (_msg('markdown.evidence_candidate_related_evidence_exists_but_no_executable')),
        (_msg('markdown.possible_target_unproven_type_compatible_and_reachable_but')),
        (_msg('markdown.no_generated_target_manual_template_review_has_not')),
        "",
        (_msg('markdown.reviewed_mappings_narrative_only_decisions_and_intentional_nulls')),
        "",
        (_msg('markdown.nothing_in_a_candidate_list_is_selected_automatically')),
        "",
        (_msg('markdown.unresolved_dataset_tree')),
        "",
        *_review_dataset_tree(model, review_rows),
        "",
        (_msg('markdown.cda_review_tree')),
        "",
    ]
    cda_review_tree = _review_cda_tree(view, cda, review_rows)
    lines += cda_review_tree if len(cda_review_tree) > 3 else [
        (_msg('markdown.no_unresolved_datapoint_currently_has_a_generated_cda'))
    ]
    lines += ["", (_msg('markdown.decisions')), ""]
    if not review_rows:
        lines += [(_msg('markdown.no_dataset_datapoints_currently_require_target_selection')), ""]
        return ("\n".join(lines).rstrip() + "\n")

    lines += [
        (_msg('markdown.every_card_corresponds_to_an_explicit_null_entry')),
        "",
    ]
    for row in review_rows:
        detail = row.get("detail", {})
        detail = detail if isinstance(detail, Mapping) else {}
        gap = detail.get("gap", {})
        gap = gap if isinstance(gap, Mapping) else {}
        lines += [
            f"### {row['name']}",
            "",
            f"{_msg('markdown.dataset_datapoint')} `{row['path']}`",
            "",
            f"{_msg('markdown.why_review_is_required')} {row['reason']}",
            "",
        ]
        if gap:
            lines += [
                f"**Gap:** `{gap.get('gate')}:{gap.get('kind')}`",
                "",
            ]
        candidates = row.get("candidates", [])
        selectable: list[str] = []
        if candidates:
            lines += [
                (_msg('markdown.evidence_candidates')),
                "",
                "| CDA target | Name / explanation in CDA template | Datatype | Confidence | Evidence | Result |",
                "|---|---|---|---|---|---|",
            ]
            for candidate in candidates:
                name = str(candidate.get("target") or "")
                target = cda.get("targets", {}).get(name, {})
                target = target if isinstance(target, Mapping) else {}
                description = _concise(target.get("description"), 100)
                human = description or _leaf(
                    target.get("path") or target.get("element_name")
                ) or "—"
                result = str(candidate.get("result") or "evidence only")
                if result in {
                    "selectable after review", "suggested without formal bridge",
                    "transform required",
                }:
                    selectable.append(name)
                lines.append(
                    f"| `{_md(name)}` | {_md(human)} | "
                    f"`{_md(target.get('datatype') or '—')}` | "
                    f"{_md(candidate.get('confidence') or '—')} | "
                    f"{_md(_evidence(candidate))} | {_md(result)} |"
                )
            lines.append("")
        else:
            lines += [(_msg('markdown.no_semantic_evidence_candidate_was_generated')), ""]

        lines.extend(_possible_target_lines(detail, cda))
        lines += [f"{_msg('markdown.action')} {row['action']}", ""]
        if selectable:
            lines += [
                (_msg('markdown.selectable_values_established_by_the_mapping_evidence')),
                "",
                *[f"{index}. `{name}`" for index, name in enumerate(selectable, 1)],
                "",
                (_msg('markdown.example_edit_choose_only_after_review')),
                "",
                "```json",
                json.dumps(
                    {"fields": {row["path"]: selectable[0]}},
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        else:
            lines += [
                (_msg('markdown.current_editable_state')),
                "",
                "```json",
                json.dumps(
                    {"fields": {row["path"]: None}},
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
    return ("\n".join(lines).rstrip() + "\n")


@localized
def render_cda_mapping_trees_markdown(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> str:
    """Render the exhaustive dataset and reportable CDA coverage trees."""
    view = _mapping_view(model, cda, mapping)
    coverage = _coverage_index(model, cda, mapping, audit)
    cda_tree, no_source_count = _cda_coverage_tree(
        view, model, cda, mapping, coverage,
    )
    headline_counts = coverage_headline_counts(model, cda, mapping, audit)
    if headline_counts["no_source_leaves"] != no_source_count:
        raise ValueError("coverage headline and CDA coverage tree disagree")
    template = view["template"]
    lines = [
        (_msg('markdown.dataset_to_cda_coverage_trees')),
        "",
        f"Template: **{template.get('display_name') or template.get('name') or 'ClinicalDocument'}** "
        f"(`{template.get('id')}` @ `{template.get('effective_date')}`)",
        "",
        format_coverage_headline(headline_counts),
        "",
        (_msg('markdown.this_report_is_exhaustive_the_status_gutter_is')),
        "",
        (_msg('markdown.mapped_selected_executable_mapping')),
        (_msg('markdown.suggested_a_writable_cda_leaf_exists_but_no')),
        (_msg('markdown.no_target_no_suitable_writable_cda_leaf_was')),
        (_msg('markdown.intentionally_unmapped_the_field_remains_null_by_an')),
        (_msg('markdown.no_source_a_reportable_writable_cda_leaf_has')),
        (_msg('markdown.required_gap_an_active_owner_required_cda_value')),
        (_msg('markdown.site_owned_requirement_an_active_owner_required_cda')),
        (_msg('markdown.mapped_and_suggested_one_datapoint_is_selected_and')),
        "",
        (_msg('markdown.the_cda_tree_excludes_generic_datatype_expansion_plumbing')),
        (_msg('markdown.the_required_gap_and_site_ownership_markers_evaluate')),
        "",
        (_msg('markdown.complete_dataset_tree')),
        "",
        "`Dataset datapoint` → `{logical CDA target}`",
        "",
        *_dataset_coverage_tree(model, coverage),
        "",
        (_msg('markdown.complete_cda_coverage_tree')),
        "",
        "`Logical CDA target` ← `dataset datapoint`",
        "",
        *cda_tree,
        "",
    ]
    return ("\n".join(lines).rstrip() + "\n")


@localized
def render_cda_mapping_extended_trees_markdown(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> str:
    """Render reviewer-facing coverage trees with stable traceability evidence."""
    view = _mapping_view(model, cda, mapping)
    coverage = _coverage_index(model, cda, mapping, audit)
    cda_tree, physical_no_source = _extended_cda_coverage_tree(
        view, model, cda, mapping, coverage,
    )
    headline_counts = coverage_headline_counts(model, cda, mapping, audit)
    # The compact report retains its historical logical-target count. This
    # report resolves discriminator occurrences to the shared physical leaf.
    headline_counts["no_source_leaves"] = physical_no_source
    template = view["template"]
    lines = [
        (_msg('markdown.extended_dataset_to_cda_coverage_trees')),
        "",
        (_msg('markdown.edit_cda_mapping_json_not_this_report')),
        "",
        f"Document template: **{template.get('display_name') or template.get('name') or 'ClinicalDocument'}** "
        f"(`{template.get('id')}` @ `{template.get('effective_date')}`)",
        "",
        format_coverage_headline(headline_counts),
        "",
        (_msg('markdown.the_primary_tree_line_is_kept_compact_indented')),
        "",
        (_msg('markdown.s_source_concept_oid_stable_dataset_path_logical')),
        (_msg('markdown.t_owning_template_revision_template_relative_xpath_cda')),
        (_msg('markdown.art_decor_description_evidence')),
        (_msg('markdown.r_executable_transform_structural_rule_reviewed_default_or')),
        (_msg('markdown.g_reviewed_non_transmission_or_unresolved_evidence_gate')),
        "",
        (_msg('markdown.status_mapped_suggested_but_not_selected_no_approved')),
        "",
        (_msg('markdown.logical_targets_identify_separately_reviewable_occurrences_when_several')),
        "",
        (_msg('markdown.the_cda_tree_excludes_generic_datatype_expansion_plumbing')),
        "",
        (_msg('markdown.complete_dataset_tree')),
        "",
        "`Dataset datapoint` → `{logical CDA target}`",
        "",
        *_extended_dataset_coverage_tree(model, cda, mapping, audit, coverage),
        "",
        (_msg('markdown.complete_physical_cda_coverage_tree')),
        "",
        "`{physical CDA target}` ← `dataset datapoint` (with logical occurrence where distinct)",
        "",
        *cda_tree,
        "",
    ]
    return ("\n".join(lines).rstrip() + "\n")


def _constraint_xml(
    node: Mapping[str, Any], mappings: Mapping[str, list[str]],
) -> ET.Element:
    kind = str(node.get("kind") or "element")
    tag = "attribute" if kind == "attribute" else "element"
    attributes = {
        "name": str(node.get("name") or ""),
        "id": str(node.get("id") or ""),
        "datatype": str(node.get("datatype") or ""),
        "minimumMultiplicity": str(node.get("min") if node.get("min") is not None else ""),
        "maximumMultiplicity": str(node.get("max") if node.get("max") is not None else "*"),
    }
    element = ET.Element(tag, {key: value for key, value in attributes.items() if value})
    description = str(node.get("description") or "").strip()
    if description:
        ET.SubElement(element, "description").text = description
    targets = [str(value) for value in node.get("targets", []) if value]
    if node.get("target") and str(node.get("target")) not in targets:
        targets.append(str(node.get("target")))
    if targets:
        element.append(_comment("CDA target(s): " + ", ".join(targets)))
    mapped = sorted({path for target in targets for path in mappings.get(target, [])})
    if mapped:
        element.append(_comment("Mapped dataset path(s): " + ", ".join(mapped)))
    sources = node.get("provenance") or node.get("sources", [])
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            source_kind = str(source.get("source") or "template")
            if source_kind in {"datatype", "template + datatype"}:
                datatype = str(source.get("datatype") or node.get("datatype") or "")
                part = str(source.get("datatype_part") or node.get("name") or "")
                element.append(_comment(
                    f"HL7 datatype {datatype} part {part}"
                    + (" refined by ART-DECOR" if source_kind == "template + datatype" else "")
                ))
                if source_kind == "datatype":
                    continue
            template = str(source.get("template_id") or "")
            effective = str(source.get("template_effective_date") or "dynamic")
            element_id = str(source.get("element_id") or "")
            if template:
                element.append(_comment(
                    f"ART-DECOR {template} @ {effective}"
                    + (f", element {element_id}" if element_id else "")
                ))
    for attribute in node.get("attributes", []):
        if isinstance(attribute, Mapping):
            element.append(_constraint_xml(attribute, mappings))
    for child in node.get("children", []):
        if isinstance(child, Mapping):
            element.append(_constraint_xml(child, mappings))
    return element


@localized
def write_readable_cda(
    model_dir: Path,
    cda: Mapping[str, Any],
    mapping_audit: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> tuple[Path, Path]:
    """Write an annotated effective template in XML and concise Markdown."""
    template = cda.get("document_template", {})
    root = ET.Element("expandedCdaTemplate", {
        "id": str(template.get("id") or ""),
        "effectiveDate": str(template.get("effective_date") or ""),
        "name": str(template.get("name") or ""),
        "displayName": str(template.get("display_name") or ""),
    })
    root.append(_comment(
        "Effective compiled constraints. Comments link physical CDA nodes to "
        "human-readable target names and dataset paths from mapping-audit.json."
    ))
    mappings = _audit_targets(mapping_audit)
    for node in cda.get("document", []):
        if isinstance(node, Mapping):
            root.append(_constraint_xml(node, mappings))
    ET.indent(root, space="  ")
    xml_path = model_dir / "cda-expanded-readable.xml"
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

    stats = cda.get("stats", {})
    summary = mapping_audit.get("summary", {})
    lines = [
        (_msg('markdown.expanded_cda_template')),
        "",
        f"- Template: `{template.get('name') or template.get('display_name') or ''}`",
        f"- Identity: `{template.get('id')}` @ `{template.get('effective_date')}`",
        f"- {_msg('markdown.reachable_template_revisions')} {stats.get('reachable_templates', 0)}",
        f"- {_msg('markdown.effective_elements')} {stats.get('elements', 0)}",
        f"- {_msg('markdown.effective_attributes')} {stats.get('attributes', 0)}",
        f"- {_msg('markdown.named_targets')} {stats.get('targets', 0)}",
        f"- {_msg('markdown.writable_value_targets')} {stats.get('writable_value_targets', 0)}",
        f"- {_msg('markdown.executable_dataset_mappings')} {summary.get('executable_fields', 0)}",
        "",
        _msg('markdown.the_companion_xml_is_the_effective_compiled_constraint'),
        "",
        (_msg('markdown.mapping_decisions_and_alternatives_are_recorded_in_mapping')),
        "",
    ]
    markdown_path = model_dir / "cda-expanded-readable.md"
    markdown_path.write_text(
        ("\n".join(lines)),
        encoding="utf-8",
    )
    return xml_path, markdown_path
