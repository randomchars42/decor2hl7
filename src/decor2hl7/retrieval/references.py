"""Extract typed artifact dependencies and explain why they are needed."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TypedDict

from .artifacts import REQUIRED_ROLES
from .resolution import reference_project
from .xml import local


class Want(TypedDict, total=False):
    kind: str
    id: str
    effective_date: str
    project: str
    api_base: str
    publication_url: str
    source_hint: str
    mode: str
    artifact: str
    source_url: str
    source_version: str
    completeness: str
    license: str
    sha256: str
    reason: str
    dataset: str
    dataset_effective_date: str
    role: str


KINDS = {"dataset", "concept", "template", "valueset", "codesystem"}
KIND_ORDER = {
    "dataset": 0,
    "template": 1,
    "valueset": 2,
    "codesystem": 3,
    "concept": 4,
}


def collect_references(root: ET.Element, *, soft: bool) -> list[Want]:
    """Extract recursive dependencies or direct mapping-evidence references."""
    found: dict[tuple[str, str, str, str, str, str], Want] = {}
    project_context = ""

    def add(
        kind: str,
        ident: str | None,
        effective: str | None = None,
        project: str | None = None,
        dataset: str | None = None,
        dataset_effective_date: str | None = None,
        role: str | None = None,
    ) -> None:
        if not ident or kind not in KINDS:
            return
        want: Want = {
            "kind": kind,
            "id": ident,
            "effective_date": "" if effective in (None, "dynamic") else str(effective),
            "project": project or project_context,
            "role": role or ("mapping-evidence" if soft else "structure"),
        }
        if dataset:
            want["dataset"] = dataset
        if dataset_effective_date:
            want["dataset_effective_date"] = dataset_effective_date
        identity = (
            kind,
            ident,
            want["effective_date"],
            want["project"],
            want.get("dataset", ""),
            want.get("dataset_effective_date", ""),
        )
        current = found.get(identity)
        if (
            current is not None
            and current.get("role") in REQUIRED_ROLES
            and want.get("role") not in REQUIRED_ROLES
        ):
            return
        found[identity] = want

    stack: list[tuple[ET.Element, tuple[str, ...]]] = [(root, ())]
    while stack:
        node, ancestors = stack.pop()
        tag = local(node.tag)
        parent_tag = ancestors[-1] if ancestors else ""
        project_context = reference_project(node)
        for child in node:
            stack.append((child, ancestors + (tag,)))

        if not soft:
            if tag == "include" and node.get("ref"):
                in_valueset = any(
                    item in {"valueSet", "conceptList", "questionnaire"}
                    for item in ancestors[-4:]
                )
                add(
                    "valueset" if in_valueset else "template",
                    node.get("ref"),
                    node.get("flexibility"),
                    role="formal-terminology" if in_valueset else "structure",
                )
                continue
            if tag == "answerValueSet":
                add(
                    "valueset",
                    node.get("ref"),
                    node.get("flexibility"),
                    role="formal-terminology",
                )
                continue
            if tag == "contains":
                dataset = node.get("datasetId")
                if dataset:
                    add(
                        "dataset",
                        dataset,
                        node.get("datasetEffectiveDate"),
                        node.get("prefix"),
                    )
                elif node.get("ref"):
                    add(
                        "concept",
                        node.get("ref"),
                        node.get("effectiveDate") or node.get("flexibility"),
                        node.get("prefix"),
                    )
                continue
            if tag == "relationship" and node.get("template"):
                if (node.get("type") or "") in {"SPEC", "VERSION", "COPY"}:
                    add(
                        "template",
                        node.get("template"),
                        node.get("flexibility"),
                        node.get("prefix"),
                    )
                continue
            if tag == "element":
                add("template", node.get("contains"), node.get("flexibility"))
            elif tag == "representingTemplate":
                add("template", node.get("ref"), node.get("flexibility"))
                add(
                    "dataset",
                    node.get("sourceDataset"),
                    node.get("sourceDatasetFlexibility"),
                )
            elif tag == "valueSet":
                if node.get("ref"):
                    add(
                        "valueset",
                        node.get("ref"),
                        node.get("flexibility"),
                        role="formal-terminology",
                    )
                elif node.get("id"):
                    add(
                        "valueset",
                        node.get("id"),
                        node.get("effectiveDate"),
                        role="formal-terminology",
                    )
            elif tag == "vocabulary":
                add(
                    "valueset",
                    node.get("valueSet"),
                    node.get("flexibility"),
                    role="formal-terminology",
                )
                add(
                    "codesystem",
                    node.get("codeSystem"),
                    node.get("codeSystemEffectiveDate"),
                    node.get("prefix"),
                    role="display-evidence",
                )
            elif tag == "sourceCodeSystem":
                add(
                    "codesystem",
                    node.get("id"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                    role="display-evidence",
                )
            elif tag == "include" and node.get("codeSystem"):
                add(
                    "codesystem",
                    node.get("codeSystem"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                    role="expansion-support",
                )
            elif tag in {"concept", "exception"} and node.get("codeSystem"):
                add(
                    "codesystem",
                    node.get("codeSystem"),
                    node.get("codeSystemEffectiveDate"),
                    node.get("prefix"),
                    role="display-evidence",
                )
            if node.get("templateId") and tag in {"dataset", "transaction"}:
                add(
                    "template",
                    node.get("templateId"),
                    node.get("templateEffectiveDate"),
                )
            continue

        # Mapping evidence is fetched directly and never recursively closed.
        if tag == "inherit":
            add(
                "concept",
                node.get("ref"),
                node.get("effectiveDate") or node.get("flexibility"),
                node.get("prefix"),
                node.get("datasetId"),
                node.get("datasetEffectiveDate"),
            )
            add(
                "concept",
                node.get("originalId"),
                node.get("originalEffectiveDate"),
                node.get("originalPrefix"),
            )
        elif tag == "relationship":
            if node.get("ref") and parent_tag == "concept":
                add(
                    "concept",
                    node.get("ref"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                    node.get("datasetId"),
                    node.get("datasetEffectiveDate"),
                )
            if (
                node.get("template")
                and (node.get("type") or "") not in {"SPEC", "VERSION", "COPY"}
            ):
                add(
                    "template",
                    node.get("template"),
                    node.get("flexibility"),
                    node.get("prefix"),
                )

    rows = list(found.values())
    dated_code_systems = {
        (item["id"], item.get("project", ""))
        for item in rows
        if item["kind"] == "codesystem" and item.get("effective_date")
    }
    return [
        item
        for item in rows
        if not (
            item["kind"] == "codesystem"
            and not item.get("effective_date")
            and (item["id"], item.get("project", "")) in dated_code_systems
        )
    ]


def hard_references(root: ET.Element) -> list[Want]:
    """Resources recursively required to build the selected specification."""
    return [
        want
        for want in collect_references(root, soft=False)
        if want.get("role") in REQUIRED_ROLES
    ]


def soft_references(root: ET.Element) -> list[Want]:
    """Direct, non-recursive semantic evidence references."""
    return collect_references(root, soft=True)


def display_references(root: ET.Element) -> list[Want]:
    """Display/provenance references that must not trigger HTTP."""
    return [
        want
        for want in collect_references(root, soft=False)
        if want.get("role") == "display-evidence"
    ]


def references(root: ET.Element) -> list[Want]:
    """Compatibility name for recursive/build dependencies."""
    return hard_references(root)
