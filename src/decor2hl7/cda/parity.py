"""Compare published ART-DECOR endpoints with the compiled CDA surface."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from ..retrieval.xml import local, parse_file
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
    uses the value combinations documented by the standing test. Reviewed
    ``select_spec_branch`` overlays likewise leave the replaced SPEC choice in
    the published declaration surface while intentionally removing that host
    from the compiled document. Both cases are reported explicitly rather than
    counted as unexpected loss.
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
                    "contains": str(node.get("contains") or ""),
                    "flexibility": str(
                        node.get("flexibility")
                        or node.get("tmeffectiveDate")
                        or ""
                    ),
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
    reviewed_branch_replacements: list[dict[str, Any]] = []
    reviewed_replaced_branches = {
        (
            str(extension.get("parent_template_id") or ""),
            str(extension.get("parent_template_effective_date") or ""),
            str(extension.get("element_name") or ""),
            str(extension.get("replaces_template_id") or ""),
            str(extension.get("replaces_template_effective_date") or ""),
        )
        for extension in cda.get("reviewed_extensions", [])
        if isinstance(extension, Mapping)
        and extension.get("operation") == "select_spec_branch"
    }
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
        elif records and any(
            (
                key[0], record["effective_date"], record["name"],
                record["contains"], record["flexibility"],
            )
            in reviewed_replaced_branches
            for record in records
        ):
            reviewed_branch_replacements.append(item)
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
        "reviewed_branch_replacements": reviewed_branch_replacements,
        "unexpected_missing": missing,
    }


def endpoint_parity_errors(parity: Mapping[str, Any]) -> list[str]:
    """Render unexpected declared endpoint losses as check errors."""
    errors: list[str] = []
    missing = parity.get("unexpected_missing", [])
    for item in missing if isinstance(missing, list) else ():
        if not isinstance(item, Mapping):
            continue
        errors.append(
            "source parity: declared endpoint "
            f"{item.get('template_id') or '?'}:{item.get('element_id') or '?'} "
            "is missing from the compiled CDA surface"
        )
    return errors


def verify_compiled_against_artdecor(
    cda: Mapping[str, Any], xml_paths: Iterable[Path],
) -> list[str]:
    """Check explicit ART-DECOR constraints against the compiled CDA model.

    This is a setup-time source check.  It intentionally lives beside the
    endpoint parity logic so the runtime validation module never needs to
    import ART-DECOR parsing helpers.
    """
    source_by_id: dict[tuple[str, str, str, str], ET.Element[str]] = {}
    source_rules: dict[
        tuple[str, str, str, str, str, str, str], dict[str, str]
    ] = {}
    templates: set[tuple[str, str]] = set()
    for path in sorted(set(xml_paths)):
        try:
            root, _ = parse_file(path)
        except (ET.ParseError, OSError):
            continue
        for template in root.iter():
            if local(template.tag) != "template" or not template.get("id"):
                continue
            tid = template.get("id") or ""
            effective = template.get("effectiveDate") or ""
            templates.add((tid, effective))

            def collect(
                parent: ET.Element[str], parent_path: tuple[str, ...] = (),
            ) -> None:
                for node in list(parent):
                    kind = local(node.tag)
                    current_path = parent_path
                    if kind == "element":
                        current_path = parent_path + (
                            node.get("name") or "element",
                        )
                    elif kind == "attribute" and node.get("name"):
                        current_path = parent_path + (
                            "@" + (node.get("name") or "attribute"),
                        )
                    physical_path = "/".join(current_path)
                    if kind in {"element", "attribute"} and node.get("id"):
                        source_by_id[
                            (tid, effective, node.get("id") or "", physical_path)
                        ] = node
                    if kind == "element":
                        lets = {
                            child.get("name") or "": child.get("value") or ""
                            for child in list(node)
                            if local(child.tag) == "let"
                            and child.get("name")
                            and child.get("value")
                        }
                        for rule in list(node):
                            rule_kind = local(rule.tag)
                            if (
                                rule_kind not in {"assert", "report"}
                                or not rule.get("test")
                            ):
                                continue
                            key = (
                                tid,
                                effective,
                                node.get("id") or "",
                                physical_path,
                                rule_kind,
                                rule.get("test") or "",
                                rule.get("role") or "error",
                            )
                            source_rules[key] = lets
                    collect(node, current_path)

            collect(template)

    errors: list[str] = []
    document = cda.get("document_template", {})
    document_key = (
        str(document.get("id") or ""),
        str(document.get("effective_date") or ""),
    )
    if document_key not in templates:
        errors.append(
            "source verification: document template "
            f"{document_key[0]}@{document_key[1]} not found"
        )
    targets = cda.get("targets", {})
    for name, target in targets.items() if isinstance(targets, Mapping) else ():
        if not isinstance(target, Mapping):
            continue
        element_id = str(target.get("element_id") or "")
        if not element_id:
            continue
        key = (
            str(target.get("template_id") or ""),
            str(target.get("template_effective_date") or ""),
            element_id,
            str(target.get("path") or ""),
        )
        source = source_by_id.get(key)
        if source is None:
            continue
        explicit_type = source.get("datatype")
        target_type = str(target.get("datatype") or "")
        typed_alternative = bool(
            target.get("polymorphic")
            and str(target.get("declared_datatype") or "") == explicit_type
            and any(
                item.get("source") == "hl7-datatype-choice"
                and str(item.get("datatype") or "") == explicit_type
                and str(item.get("datatype_part") or "") == target_type
                for item in target.get("provenance", [])
                if isinstance(item, Mapping)
            )
        )
        if explicit_type and target_type != explicit_type and not typed_alternative:
            errors.append(
                f"source verification: {name} datatype "
                f"{target.get('datatype')!r} != explicit {explicit_type!r}"
            )
        if local(source.tag) == "element":
            if source.get("conformance") == "NP" and not target.get("prohibited"):
                errors.append(
                    f"source verification: {name} ignores explicit NP conformance"
                )
            fixed_text = None
            fixed: dict[str, str] = {}
            for child in list(source):
                if local(child.tag) == "text":
                    text = "".join(child.itertext()).strip()
                    if text:
                        fixed_text = text
                elif (
                    local(child.tag) == "attribute"
                    and child.get("name")
                    and child.get("value")
                ):
                    fixed[child.get("name") or ""] = child.get("value") or ""
            if fixed_text is not None and target.get("fixed_text") != fixed_text:
                errors.append(
                    f"source verification: {name} lost explicit fixed text "
                    f"{fixed_text!r}"
                )
            target_fixed = target.get("fixed", {})
            target_fixed = target_fixed if isinstance(target_fixed, Mapping) else {}
            for attribute_name, attribute_value in fixed.items():
                if str(target_fixed.get(attribute_name) or "") != attribute_value:
                    errors.append(
                        f"source verification: {name} lost fixed "
                        f"@{attribute_name}={attribute_value!r}"
                    )
        elif local(source.tag) == "attribute":
            source_value = source.get("value")
            if source_value is None:
                codes = {
                    str(node.get("code"))
                    for node in list(source)
                    if local(node.tag) == "vocabulary"
                    and node.get("code") is not None
                }
                source_value = next(iter(codes)) if len(codes) == 1 else None
            target_fixed = target.get("fixed", {})
            target_fixed = target_fixed if isinstance(target_fixed, Mapping) else {}
            if (
                source_value is not None
                and str(target_fixed.get("value") or "") != str(source_value)
            ):
                errors.append(
                    f"source verification: {name} lost fixed attribute value "
                    f"{source_value!r}"
                )

    compiled_by_source: dict[
        tuple[str, str, str, str], list[Mapping[str, Any]]
    ] = defaultdict(list)

    def structural(nodes: list[Mapping[str, Any]]) -> None:
        for node in nodes:
            for source in node.get("sources", []):
                if not isinstance(source, Mapping):
                    continue
                source_key = (
                    str(source.get("template_id") or ""),
                    str(source.get("template_effective_date") or ""),
                    str(source.get("element_id") or ""),
                    str(source.get("path") or ""),
                )
                if source_key[2]:
                    compiled_by_source[source_key].append(node)
            structural([
                child for child in node.get("children", [])
                if isinstance(child, Mapping)
            ])

    structural([
        node for node in cda.get("document", []) if isinstance(node, Mapping)
    ])
    for rule_key, source_lets in source_rules.items():
        source_key = rule_key[:4]
        compiled_nodes = compiled_by_source.get(source_key, [])
        if not compiled_nodes:
            continue
        match = next((
            node
            for node in compiled_nodes
            if any(
                str(item.get("kind") or "assert") == rule_key[4]
                and str(item.get("test") or "") == rule_key[5]
                and str(item.get("role") or "error") == rule_key[6]
                for item in node.get("validation_rules", [])
                if isinstance(item, Mapping)
            )
        ), None)
        if match is None:
            errors.append(
                f"source verification: lost ART-DECOR {rule_key[4]} "
                f"{rule_key[5]!r} from {rule_key[0]}@"
                f"{rule_key[1]}:{rule_key[2]}"
            )
            continue
        compiled_lets = match.get("lets", {})
        compiled_lets = compiled_lets if isinstance(compiled_lets, Mapping) else {}
        for let_name, let_value in source_lets.items():
            if str(compiled_lets.get(let_name) or "") != let_value:
                errors.append(
                    "source verification: ART-DECOR assert "
                    f"{rule_key[5]!r} lost let ${let_name}={let_value!r}"
                )
    return errors
