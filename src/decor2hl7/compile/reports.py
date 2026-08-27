"""Human-readable reports rendered from compiled semantic artifacts."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


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
    sources = node.get("sources", [])
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, Mapping):
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

