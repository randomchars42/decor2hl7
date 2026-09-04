"""Compare published ART-DECOR endpoints with the compiled CDA surface."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..retrieval.xml import local
from .compile import collect_templates


_FOLDED_STRUCTURAL_ATTRIBUTES = {
    "classCode", "contextControlCode", "determinerCode", "moodCode", "typeCode",
}


def declared_endpoint_parity(
    template_paths: Iterable[Path],
    cda: Mapping[str, Any],
    selected_template_ids: Iterable[str],
) -> dict[str, Any]:
    """Diff published element/attribute ids against compiled CDA targets.

    ART-DECOR ids are not unique within one template revision, so this is a
    deliberately revisionless *surface* check grouped by template id and
    element id.  Exact physical identity remains represented by CDA target
    provenance and its source index.  The parity check answers the narrower
    standing question: did compilation lose any endpoint the selected IG
    declares?

    Fixed structural attributes are not scalar targets.  The compiler folds
    them into the owning node's ``fixed`` map. Only fixed CDA/RIM structural
    roles are admitted as declared-only records; the reference guide currently
    uses the three value combinations documented by the standing test.
    """
    selected = {str(value) for value in selected_template_ids if value}
    templates = collect_templates(template_paths)
    declarations: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for template_id in sorted(selected):
        for template in templates.get(template_id, []):
            effective_date = str(template.get("effectiveDate") or "")
            for node in template.iter():
                kind = local(node.tag)
                element_id = str(node.get("id") or "")
                if kind not in {"element", "attribute"} or not element_id:
                    continue
                record = {
                    "template_id": template_id,
                    "effective_date": effective_date,
                    "element_id": element_id,
                    "kind": kind,
                    "name": str(node.get("name") or ""),
                    "value": str(node.get("value") or ""),
                }
                if record not in declarations[(template_id, element_id)]:
                    declarations[(template_id, element_id)].append(record)

    targets = cda.get("targets", {})
    compiled: dict[tuple[str, str], list[str]] = defaultdict(list)
    if isinstance(targets, Mapping):
        for target_name, target in targets.items():
            if not isinstance(target, Mapping):
                continue
            template_id = str(target.get("template_id") or "")
            element_id = str(target.get("element_id") or "")
            if template_id not in selected or not element_id:
                continue
            compiled[(template_id, element_id)].append(str(target_name))

    declared_keys = set(declarations)
    compiled_keys = set(compiled)
    missing: list[dict[str, Any]] = []
    fixed_structural_attributes: list[dict[str, Any]] = []
    for key in sorted(declared_keys - compiled_keys):
        records = declarations[key]
        item = {
            "template_id": key[0],
            "element_id": key[1],
            "declarations": sorted(
                records,
                key=lambda row: (
                    row["effective_date"], row["kind"], row["name"], row["value"]
                ),
            ),
        }
        if records and all(
            record["kind"] == "attribute"
            and record["name"] in _FOLDED_STRUCTURAL_ATTRIBUTES
            and bool(record["value"])
            for record in records
        ):
            fixed_structural_attributes.append(item)
        else:
            missing.append(item)

    compiler_only = [
        {
            "template_id": template_id,
            "element_id": element_id,
            "targets": sorted(compiled[(template_id, element_id)]),
        }
        for template_id, element_id in sorted(compiled_keys - declared_keys)
    ]
    return {
        "declared": len(declared_keys),
        "compiled": len(compiled_keys),
        "declared_only": len(declared_keys - compiled_keys),
        "compiler_only": compiler_only,
        "fixed_structural_attributes": fixed_structural_attributes,
        "unexpected_missing": missing,
    }
