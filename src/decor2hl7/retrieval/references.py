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
    alias_of: str
    source_hint_origin: str
    alias_requested_key: str
    alias_reason: str
    alias_source_hint_origin: str
    dataset: str
    dataset_effective_date: str
    role: str
    analysis_only: str


KINDS = {"dataset", "concept", "template", "valueset", "codesystem"}
TEMPLATE_PROTOTYPE_RELATIONSHIP = "SPEC"
KIND_ORDER = {
    "dataset": 0,
    "template": 1,
    "valueset": 2,
    "codesystem": 3,
    "concept": 4,
}


def collect_references(
    root: ET.Element,
    *,
    soft: bool,
    original_only: bool = False,
    selected_concepts: set[str] | None = None,
) -> list[Want]:
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
        analysis_only: bool = False,
    ) -> None:
        if not ident or kind not in KINDS:
            return
        want: Want = {
            "kind": kind,
            "id": ident,
            "effective_date": "" if effective in (None, "dynamic") else str(effective),
            "project": project or project_context,
            "role": role or (
                "formal-origin"
                if original_only else "mapping-evidence"
                if soft else "structure"
            ),
        }
        if dataset:
            want["dataset"] = dataset
        if dataset_effective_date:
            want["dataset_effective_date"] = dataset_effective_date
        if analysis_only:
            want["analysis_only"] = "true"
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

    stack: list[
        tuple[
            ET.Element, tuple[str, ...], ET.Element | None,
            ET.Element | None, str,
        ]
    ] = [
        (root, (), None, None, "")
    ]
    while stack:
        (
            node, ancestors, enclosing_value_domain, enclosing_member_scope,
            enclosing_concept,
        ) = stack.pop()
        tag = local(node.tag)
        parent_tag = ancestors[-1] if ancestors else ""
        project_context = reference_project(node)
        child_value_domain = node if tag == "valueDomain" else enclosing_value_domain
        child_member_scope = (
            node
            if tag in {"conceptList", "valueDomain"}
            else enclosing_member_scope
        )
        child_concept = (
            (node.get("id") or "") if tag == "concept" else enclosing_concept
        )
        for child in node:
            stack.append((
                child,
                ancestors + (tag,),
                child_value_domain,
                child_member_scope,
                child_concept,
            ))

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
                # Object relationships are implicit, unchecked hints in the
                # DECOR contract. Even SPEC is an editor prototype rather than
                # part of the executable include/contains closure.
                continue
            if tag == "element":
                add("template", node.get("contains"), node.get("flexibility"))
            elif tag == "representingTemplate":
                add("template", node.get("ref"), node.get("flexibility"))
                add(
                    "dataset",
                    node.get("sourceDataset"),
                    node.get("sourceDatasetEffectiveDate")
                    or node.get("sourceDatasetFlexibility"),
                    node.get("sourceDatasetPrefix")
                    or node.get("prefix")
                    or node.get("ident")
                    or node.get("templateIdent"),
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
                value_domain_type = (
                    enclosing_value_domain.get("type")
                    if enclosing_value_domain is not None else ""
                ) or ""
                has_inline_members = bool(
                    enclosing_member_scope is not None
                    and any(
                        local(member.tag) in {"concept", "exception"}
                        and member.get("code")
                        and member.get("codeSystem")
                        for member in enclosing_member_scope.iter()
                    )
                )
                has_intensional_selector = bool(
                    node.get("code") or node.get("op")
                )
                add(
                    "codesystem",
                    node.get("codeSystem"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                    role=(
                        "display-evidence"
                        if (value_domain_type and value_domain_type != "code")
                        or (has_inline_members and not has_intensional_selector)
                        else "expansion-support"
                    ),
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

        # Mapping evidence is fetched directly. The caller may subsequently
        # close only formal inherit/contains origins through
        # ``original_references``. Generic relationships never become origin.
        original_selected = (
            not original_only
            or not selected_concepts
            or enclosing_concept in selected_concepts
        )
        if tag in {"inherit", "contains"} and original_selected:
            add(
                "concept",
                node.get("ref"),
                node.get("effectiveDate") or node.get("flexibility"),
                node.get("prefix"),
                node.get("datasetId"),
                node.get("datasetEffectiveDate"),
                analysis_only=original_only,
            )
            add(
                "concept",
                node.get("originalId"),
                node.get("originalEffectiveDate"),
                node.get("originalPrefix"),
                analysis_only=original_only,
            )
        elif tag == "relationship":
            if (
                node.get("ref")
                and parent_tag == "concept"
                and not original_only
            ):
                add(
                    "concept",
                    node.get("ref"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                    node.get("datasetId"),
                    node.get("datasetEffectiveDate"),
                )
            if not original_only and node.get("template"):
                add(
                    "template",
                    node.get("template"),
                    node.get("flexibility"),
                    node.get("prefix"),
                    role=(
                        "template-prototype"
                        if (node.get("type") or "")
                        == TEMPLATE_PROTOTYPE_RELATIONSHIP
                        else "mapping-evidence"
                    ),
                )
        elif not original_only and tag == "origconcept":
            # Association evidence needs the exact endpoint and its formal
            # origin, not every sibling in its containing dataset. Keeping
            # this request concept-scoped bounds both the crawl and the graph
            # later indexed by the mapping compiler.
            add(
                "concept",
                node.get("ref"),
                node.get("effectiveDate") or node.get("flexibility"),
                node.get("ident") or node.get("prefix"),
                node.get("datasetId"),
                node.get("datasetEffectiveDate"),
                role="association-endpoint",
                analysis_only=True,
            )
        elif (
            not original_only
            and tag == "concept"
            and parent_tag == "templateAssociation"
        ):
            add(
                "concept",
                node.get("ref"),
                node.get("effectiveDate") or node.get("flexibility"),
                node.get("prefix"),
                node.get("datasetId"),
                node.get("datasetEffectiveDate"),
                role="association-endpoint",
                analysis_only=True,
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
    """Direct semantic-evidence and association-endpoint references."""
    return collect_references(root, soft=True)


def original_references(
    root: ET.Element, selected_concepts: set[str] | None = None,
) -> list[Want]:
    """Formal inherit/contains origins safe for transitive closure."""
    return collect_references(
        root, soft=True, original_only=True,
        selected_concepts=selected_concepts,
    )


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
