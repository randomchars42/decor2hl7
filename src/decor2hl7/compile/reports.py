"""Human-readable reports rendered from compiled semantic artifacts."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from ..bindings import required_unmapped_null_flavor
from ..transforms import cda_target_name, mapping_rules


def _comment(value: str) -> ET.Element:
    return ET.Comment(" ".join(value.replace("--", "—").split()))


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
    return str(value or "").split("/")[-1].split(":")[-1].split("[", 1)[0]


def _location(value: Any) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in str(value).split("."))
    except ValueError:
        return None


def _document_index(
    cda: Mapping[str, Any],
) -> tuple[dict[tuple[int, ...], Mapping[str, Any]], dict[tuple[int, ...], tuple[int, ...]]]:
    nodes: dict[tuple[int, ...], Mapping[str, Any]] = {}
    parents: dict[tuple[int, ...], tuple[int, ...]] = {}

    def walk(items: list[Mapping[str, Any]], prefix: tuple[int, ...] = ()) -> None:
        for index, node in enumerate(items):
            here = prefix + (index,)
            nodes[here] = node
            for attribute_index, attribute in enumerate(node.get("attributes", [])):
                attribute_location = here + (100000 + attribute_index,)
                nodes[attribute_location] = attribute
                parents[attribute_location] = here
            for child_index, _ in enumerate(node.get("children", [])):
                parents[here + (child_index,)] = here
            walk(list(node.get("children", [])), here)

    walk(list(cda.get("document", [])))
    return nodes, parents


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


def _dataset_group_labels(rows: list[Mapping[str, Any]], model: Mapping[str, Any]) -> str:
    labels: list[str] = []
    groups = model.get("groups", {})
    for row in rows:
        path = str(row["dataset_path"])
        root = path.split(".", 1)[0]
        label = str(groups.get(root, {}).get("name") or root)
        if label not in labels:
            labels.append(label)
    return ", ".join(labels)


def _mapping_view(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, Any]:
    nodes, parents = _document_index(cda)
    sections = [
        location for location, node in nodes.items()
        if _leaf(node.get("name")) == "section"
    ]
    rows_by_section: dict[tuple[int, ...] | None, list[dict[str, Any]]] = defaultdict(list)
    structures = mapping.get("structures", {})

    for dataset_path, selection in mapping.get("fields", {}).items():
        for rule in mapping_rules(selection):
            physical_name = cda_target_name(rule)
            target = cda.get("targets", {}).get(physical_name, {})
            locations = list(target.get("locations", []))
            if len(locations) != 1 or _location(locations[0]) is None:
                continue
            location = _location(locations[0])
            assert location is not None
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


def _outline_datapoint_lines(
    stem: str,
    row: Mapping[str, Any],
    *,
    last: bool,
    width: int = 96,
) -> list[str]:
    """Render one human datapoint and its logical target without hiding either."""
    branch = "└──" if last else "├──"
    name = str(row["dataset_name"])
    target = f"{{{row['target']}}}"
    inline = f"{stem}{branch} {name} → {target}"
    if len(inline) <= width:
        return [inline]
    target_stem = stem + ("    " if last else "│   ")
    return [f"{stem}{branch} {name}", f"{target_stem}→ {target}"]


def _outline(view: Mapping[str, Any], model: Mapping[str, Any], cda: Mapping[str, Any]) -> list[str]:
    rows_by_section = view["rows"]
    header_entities = _entity_groups(rows_by_section.get(None, []))
    template = view["template"]
    title = str(template.get("display_name") or template.get("name") or "ClinicalDocument")
    lines = ["```text", f"{title} (ClinicalDocument)", "├── Document header"]

    for entity_index, (entity, rows) in enumerate(header_entities):
        entity_last = entity_index == len(header_entities) - 1
        lines.append(f"│   {'└──' if entity_last else '├──'} {entity}")
        stem = "│       " if entity_last else "│   │   "
        for row_index, row in enumerate(rows):
            lines.extend(
                _outline_datapoint_lines(
                    stem, row, last=row_index == len(rows) - 1,
                )
            )

    lines.append("└── Document body (structuredBody)")
    sections = view["sections"]
    for section_index, section in enumerate(sections):
        rows = rows_by_section.get(section, [])
        last_section = section_index == len(sections) - 1
        section_stem = "    " if last_section else "│   "
        suffix = (
            f" — dataset: {_dataset_group_labels(rows, model)}"
            if rows else " — no selected dataset mapping"
        )
        lines.append(
            f"    {'└──' if last_section else '├──'} "
            f"{_section_label(section, view['nodes'], cda)}{suffix}"
        )
        entities = _entity_groups(rows)
        for entity_index, (entity, entity_rows) in enumerate(entities):
            last_entity = entity_index == len(entities) - 1
            lines.append(
                f"    {section_stem}{'└──' if last_entity else '├──'} {entity}"
            )
            entity_stem = section_stem + ("    " if last_entity else "│   ")
            for row_index, row in enumerate(entity_rows):
                lines.extend(
                    _outline_datapoint_lines(
                        f"    {entity_stem}", row,
                        last=row_index == len(entity_rows) - 1,
                    )
                )
    return lines + ["```"]


def _target_label(row: Mapping[str, Any]) -> str:
    target = row["target_model"]
    description = " ".join(str(target.get("description") or "").split())
    node = _leaf(target.get("path") or target.get("element_name"))
    human = description.rstrip(".") if description and len(description) <= 100 else node
    datatype = str(target.get("datatype") or "").strip()
    return f"{human or 'value'}" + (f" (`{datatype}`)" if datatype else "")


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _mapping_status(row: Mapping[str, Any]) -> str:
    rule = row.get("rule", {})
    if isinstance(rule, Mapping) and rule.get("structure"):
        return "Structural rule"
    if isinstance(rule, Mapping) and rule.get("transform"):
        return "Transform"
    return "Mapped" if isinstance(row.get("selection"), str) else "Rule"


def _configuration_instruction(row: Mapping[str, Any]) -> str:
    path = str(row["dataset_path"])
    name = str(row["dataset_name"])
    target = str(row["target"])
    if isinstance(row.get("selection"), str):
        return (
            f"In `cda-mapping.json`, map **{name}** by setting "
            f"`fields[\"{path}\"]` to `\"{target}\"`."
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
        if detail.get("runtime_blocked"):
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
    audited = audit.get("fields", {})
    order = [path for path in model.get("order", []) if path in model_fields]
    order.extend(sorted(path for path in model_fields if path not in order))
    rows: list[dict[str, Any]] = []
    for path in order:
        if not isinstance(configured, Mapping) or configured.get(path) is not None:
            continue
        detail = audited.get(path, {}) if isinstance(audited, Mapping) else {}
        detail = detail if isinstance(detail, Mapping) else {}
        candidates = _candidate_rows(detail)
        if detail.get("runtime_blocked"):
            action = "Define the required repetition or merge rule."
        elif candidates:
            selectable = any(
                row.get("result") in {"selectable after review", "transform required"}
                for row in candidates
            )
            action = (
                "Choose one selectable target in `cda-mapping.json`, or retain `null`."
                if selectable else
                "Use the evidence to find a value-bearing target, or retain `null`."
            )
        else:
            action = "Find a representation manually, or retain `null`."
        rows.append({
            "path": str(path),
            "name": str(model_fields.get(path, {}).get("name") or path),
            "candidates": candidates,
            "action": action,
            "reason": _review_reason(detail, candidates),
        })
    return rows


def _review_reason(
    detail: Mapping[str, Any], candidates: list[Mapping[str, Any]],
) -> str:
    if detail.get("runtime_blocked"):
        return (
            "The best-supported CDA target is shared with another dataset field. "
            "A repetition, fan-out, or merge rule is required before it is executable."
        )
    if any(row.get("result") == "transform required" for row in candidates):
        return (
            "The dataset and CDA represent the same information differently; review "
            "the proposed declarative transform before enabling it."
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
    return "No usable CDA target evidence was found for this dataset datapoint."


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
            if len(locations) != 1 or _location(locations[0]) is None:
                continue
            constant_row = {
                **dict(row), "target": constant_name, "cda_target": constant_name,
                "target_model": constant_target, "location": _location(locations[0]),
            }
            _add_preview_path(tree, constant_row, view, fixed=value)
    lines: list[str] = []
    for root in tree["children"].values():
        lines.extend(_render_preview_node(root))
    return lines


def _candidate_sections(
    review_rows: list[Mapping[str, Any]], view: Mapping[str, Any], cda: Mapping[str, Any],
) -> dict[tuple[int, ...] | None, set[str]]:
    result: dict[tuple[int, ...] | None, set[str]] = defaultdict(set)
    for review in review_rows:
        for candidate in review.get("candidates", []):
            target = cda.get("targets", {}).get(str(candidate.get("target") or ""), {})
            locations = target.get("locations", [])
            if len(locations) != 1 or _location(locations[0]) is None:
                continue
            location = _location(locations[0])
            assert location is not None
            result[_section_of(location, view["nodes"], view["parents"])].add(
                str(review["path"])
            )
    return result


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
                key: transform[key] for key in ("type", "select")
                if transform.get(key) is not None
            }
            values = transform.get("map")
            if isinstance(values, Mapping):
                compact_transform["map"] = (
                    f"{len(values)} configured values; see cda-mapping.json"
                )
            result["transform"] = compact_transform
        return result

    def compact_selection(value: Any) -> Any:
        if isinstance(value, list):
            return [compact_rule(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            return compact_rule(value)
        return value

    fields = {
        str(row["dataset_path"]): compact_selection(
            mapping.get("fields", {}).get(row["dataset_path"])
        )
        for row in rows
    }
    structure_names = {
        str(row["rule"].get("structure")) for row in rows
        if row["rule"].get("structure")
    }
    excerpt: dict[str, Any] = {"fields": fields}
    if structure_names:
        excerpt["structures"] = {}
        for name in sorted(structure_names):
            structure = mapping.get("structures", {}).get(name, {})
            compact_structure = {
                key: structure[key] for key in (
                    "type", "source_group", "target_repeat", "target", "policy", "sources"
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


def render_cda_mapping_markdown(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> str:
    """Render the concise, review-oriented dataset-to-CDA mapping guide."""
    view = _mapping_view(model, cda, mapping)
    rows_by_section = view["rows"]
    all_rows = [row for rows in rows_by_section.values() for row in rows]
    sections = view["sections"]
    template = view["template"]
    summary = audit.get("summary", {})
    lines = [
        "# Dataset-to-CDA mapping",
        "",
        f"Template: **{template.get('display_name') or template.get('name') or 'ClinicalDocument'}** "
        f"(`{template.get('id')}` @ `{template.get('effective_date')}`)",
        "",
        f"Selected dataset fields: **{len({row['dataset_path'] for row in all_rows})}**; "
        f"target assignments: **{len(all_rows)}**; "
        f"unresolved fields: **{summary.get('field_coverage', {}).get('NO', 0)}**.",
        "",
        "Edit `cda-mapping.json`; do not edit the XML examples in this report. The",
        "mapping table explicitly connects the dataset model, the editable JSON",
        "assignment, and the CDA template. XML excerpts are read-only previews of",
        "what the JSON configuration produces.",
        f"A required CDA leaf that remains deliberately unmapped is emitted with "
        f"`nullFlavor=\"{required_unmapped_null_flavor(mapping)}\"`; an unmapped "
        "optional element is omitted.",
        "",
        "## Document outline",
        "",
        "`Dataset name` → `{logical CDA target datapoint}`",
        "",
        *_outline(view, model, cda),
        "",
        "## Sections and entities",
        "",
    ]

    areas: list[tuple[str, list[Mapping[str, Any]]]] = [
        ("Document header", rows_by_section.get(None, []))
    ] + [
        (_section_label(section, view["nodes"], cda), rows_by_section.get(section, []))
        for section in sections
    ]
    review_rows = _review_required(model, mapping, audit)
    candidate_sections = _candidate_sections(review_rows, view, cda)
    example_written = False
    configured_complex_fields: set[str] = set()
    for area_index, (area_name, rows) in enumerate(areas):
        lines += [f"### {area_name}", ""]
        if not rows:
            section = None if area_index == 0 else sections[area_index - 1]
            candidate_count = len(candidate_sections.get(section, set()))
            if candidate_count:
                lines += [
                    "No dataset mapping is selected for this area. "
                    f"**{candidate_count}** unresolved dataset datapoint(s) have CDA "
                    "candidate or contextual evidence in this area; review their candidate "
                    "cards under **Review required**.",
                    "",
                ]
            else:
                lines += [
                    "No dataset mapping is selected for this area, and the analysis found "
                    "no candidate that can be assigned uniquely to it. This can mean that "
                    "the transaction has no corresponding datapoint, or that the available "
                    "evidence is too weak or ambiguous to place here.",
                    "",
                ]
            continue
        for entity, entity_rows in _entity_groups(rows):
            first_target = entity_rows[0]["target_model"]
            identity = (
                f"`{first_target.get('template_id')}` @ "
                f"`{first_target.get('template_effective_date')}`"
            )
            lines += [f"#### {entity}", "", f"Template: {identity}", ""]
            description = next((
                _concise(row["target_model"].get("description"))
                for row in entity_rows if row["target_model"].get("description")
            ), "")
            if description:
                lines += [description, ""]
            lines += [
                "| Name in dataset | `model.json` datapoint | `cda-mapping.json` target | Name in CDA template | Status |",
                "|---|---|---|---|---|",
            ]
            for row in entity_rows:
                lines.append(
                    f"| {_md(row['dataset_name'])} | `{_md(row['dataset_path'])}` | "
                    f"`{_md(row['target'])}` | {_md(_target_label(row))} | "
                    f"{_mapping_status(row)} |"
                )
            lines.append("")

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
                ]
                lines += [
                    "Abridged configuration excerpt — edit the corresponding entry in the full JSON file:",
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
                    "Resulting CDA placement — read-only consequence of the JSON configuration:",
                    "",
                    "Text in `{braces}` names a generated CDA datapoint. It is an explanatory placeholder, not XML to enter manually.",
                    "",
                    "```xml",
                    "<!-- Read-only illustration; do not copy this into cda-mapping.json. -->",
                ]
                lines.extend(_contextual_xml(entity_rows, view, cda))
                lines += ["```", ""]

    lines += ["## Review required", ""]
    if review_rows:
        lines += [
            "These dataset datapoints are explicitly `null` in `cda-mapping.json`.",
            "That does not invalidate the mapping; it records that no executable target has been approved yet.",
            "Each card distinguishes selectable targets from evidence that is useful only "
            "for navigation. Choose at most one selectable target unless the card says that "
            "a transform or structural rule is required.",
            "",
        ]
        for row in review_rows:
            lines += [
                f"### {row['name']}", "", f"Dataset datapoint: `{row['path']}`", "",
                f"**Why review is required:** {row['reason']}", "",
            ]
            candidates = row["candidates"]
            if candidates:
                lines += [
                    "| CDA target | Name / explanation in CDA template | Datatype | Confidence | Evidence | Result |",
                    "|---|---|---|---|---|---|",
                ]
                selectable: list[str] = []
                for candidate in candidates[:5]:
                    name = str(candidate.get("target") or "")
                    target = cda.get("targets", {}).get(name, {})
                    description = _concise(target.get("description"), 100)
                    human = description or _leaf(target.get("path") or target.get("element_name")) or "—"
                    result = str(candidate.get("result") or "evidence only")
                    if result in {"selectable after review", "transform required"}:
                        selectable.append(name)
                    lines.append(
                        f"| `{_md(name)}` | {_md(human)} | "
                        f"`{_md(target.get('datatype') or '—')}` | "
                        f"{_md(candidate.get('confidence') or '—')} | "
                        f"{_md(_evidence(candidate))} | {result} |"
                    )
                lines.append("")
                if selectable:
                    lines += [
                        "Available choices in `cda-mapping.json`:", "",
                        *[f"{index}. `{name}`" for index, name in enumerate(selectable, 1)],
                        "",
                        "To choose one, replace this datapoint's `null` with exactly one target; for example:",
                        "",
                        "```json",
                        json.dumps({"fields": {row["path"]: selectable[0]}}, ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                else:
                    lines += [
                        "None of these rows is directly selectable. Do not copy a context-only "
                        "or evidence-only target into the JSON; use it to investigate the "
                        "template, or leave this datapoint `null`.",
                        "",
                    ]
            else:
                lines += [
                    "No CDA candidates were found. There is therefore no generated target to "
                    "choose from; keep the value `null` unless manual template review identifies "
                    "a suitable representation.",
                    "",
                ]
            lines += [f"**Action:** {row['action']}", ""]
    else:
        lines += ["No dataset datapoints currently require target selection.", ""]

    structures = mapping.get("structures", {})
    if structures:
        lines += [
            "## Structural rules",
            "",
            "These rules create or coordinate CDA occurrences; they are configuration, not XML edits.",
            "",
        ]
        for name, rule in structures.items():
            kind = str(rule.get("type") or "unknown")
            if kind in {"fan_out", "repeat_by_discriminator"}:
                branches = [
                    f"`{branch.get('source')}` → `{{{branch.get('target')}}}`"
                    for branch in rule.get("branches", []) if isinstance(branch, Mapping)
                ]
                explanation = "Create one discriminated CDA occurrence for each present branch: " + "; ".join(branches) + "."
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
            else:
                explanation = "Review this structural rule in `cda-mapping.json`."
            lines += [f"- `{name}`: {explanation}", ""]

    target_defaults = mapping.get("target_defaults", {})
    lines += [
        "## Required CDA completion",
        "",
        f"General rule: an active required leaf without a mapped value receives "
        f"`nullFlavor=\"{required_unmapped_null_flavor(mapping)}\"`. A real mapped "
        "value always takes precedence.",
        "",
    ]
    if isinstance(target_defaults, Mapping) and target_defaults:
        lines += [
            "The following reviewed targets use a more specific default:",
            "",
            "| CDA template value | Default | Reason |",
            "|---|---|---|",
        ]
        for name, rule in target_defaults.items():
            target = cda.get("targets", {}).get(str(name), {})
            label = target.get("template_display_name") or target.get("template_name") or "CDA"
            leaf = _leaf(target.get("path")) or str(name).split(".")[-1]
            flavor = rule.get("nullFlavor") if isinstance(rule, Mapping) else ""
            reason = rule.get("reason") if isinstance(rule, Mapping) else ""
            lines.append(
                f"| {label} → {leaf} `{{{name}}}` | `nullFlavor=\"{flavor}\"` | "
                f"{reason or 'Reviewed target-specific completion rule.'} |"
            )
        lines.append("")
    else:
        lines += ["No target-specific defaults are configured.", ""]

    lines += [
        "## Detailed evidence",
        "",
        "Candidate scores, rejected alternatives, evidence chains and unresolved mappings are",
        "kept in `cda-mapping-details.md` and `mapping-audit.json` so this guide remains concise.",
        "",
    ]
    return "\n".join(lines)


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


def write_readable_cda(
    model_dir: Path,
    cda: Mapping[str, Any],
    mapping_audit: Mapping[str, Any],
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
        "# Expanded CDA template",
        "",
        f"- Template: `{template.get('name') or template.get('display_name') or ''}`",
        f"- Identity: `{template.get('id')}` @ `{template.get('effective_date')}`",
        f"- Reachable template revisions: {stats.get('reachable_templates', 0)}",
        f"- Effective elements: {stats.get('elements', 0)}",
        f"- Effective attributes: {stats.get('attributes', 0)}",
        f"- Named targets: {stats.get('targets', 0)}",
        f"- Writable value targets: {stats.get('writable_value_targets', 0)}",
        f"- Executable dataset mappings: {summary.get('executable_fields', 0)}",
        "",
        "The companion XML is the effective compiled constraint tree. It retains",
        "human-readable descriptions and inserts XML comments at nodes with named",
        "CDA targets, source-template identities, or mapped dataset paths.",
        "",
        "Mapping decisions and alternatives are recorded in `mapping-audit.json`.",
        "",
    ]
    markdown_path = model_dir / "cda-expanded-readable.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return xml_path, markdown_path
