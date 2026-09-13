"""Lossless classification of ART-DECOR template design constructs.

The compiler must never acquire semantics by omission.  This module provides
the source boundary: every direct child in the template-design grammar is
classified before composition as executable structure, executable validation,
non-executable prose/example material, analysis metadata, or unsupported.

The classification deliberately stops below prose and example fragments.  XML
inside those nodes is instance/documentation content, not another template
rule.  Likewise, children expanded below an analysis-form ``include`` are
evidence supplied by ART-DECOR and must not be compiled a second time.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Literal, Mapping, TypedDict
import xml.etree.ElementTree as ET

from ..retrieval.xml import local


ConstructDisposition = Literal[
    "structure",
    "validation",
    "prose",
    "example",
    "metadata",
    "analysis-expansion",
    "unsupported",
]


class ConstructCoverage(TypedDict):
    """Serializable accounting for one selected template closure."""

    version: int
    constructs: dict[str, int]
    dispositions: dict[str, int]
    attributes: dict[str, int]
    unsupported: list[dict[str, str]]


STRUCTURE_CONSTRUCTS = frozenset({
    "element", "attribute", "choice", "include", "context",
})
VALIDATION_CONSTRUCTS = frozenset({
    "property", "vocabulary", "text", "let", "defineVariable", "assert",
    "report",
})
PROSE_CONSTRUCTS = frozenset({
    "constraint", "desc", "item", "purpose", "copyright",
})
EXAMPLE_CONSTRUCTS = frozenset({"example"})
METADATA_CONSTRUCTS = frozenset({
    "classification", "relationship", "publishingAuthority", "ref", "uses",
    "staticAssociations", "representingTemplate", "fhir",
})

# Child constructs admitted by the owner template grammar.  Analysis responses
# add ``ref``, ``uses``, ``staticAssociations`` and ``representingTemplate``;
# those are retained as metadata but are not executable design children.
_CHILDREN: dict[str, frozenset[str]] = {
    "template": frozenset({
        "desc", "classification", "relationship", "publishingAuthority",
        "purpose", "copyright", "context", "item", "example", "attribute",
        "choice", "element", "include", "let", "assert", "report",
        "defineVariable", "constraint", "ref", "uses", "staticAssociations",
        "representingTemplate", "fhir",
    }),
    "element": frozenset({
        "desc", "item", "example", "vocabulary", "property", "text", "fhir",
        "attribute", "let", "assert", "report", "defineVariable", "element",
        "include", "choice", "constraint",
    }),
    "choice": frozenset({
        "desc", "item", "example", "fhir", "element", "include", "choice",
        "constraint",
    }),
    "include": frozenset({
        "desc", "item", "example", "constraint", "attribute", "element",
        "choice", "include", "staticAssociations",
    }),
    "attribute": frozenset({
        "desc", "item", "example", "vocabulary", "constraint",
    }),
    "property": frozenset({"item"}),
}

# Attribute names that carry executable structure or validation semantics.  All
# other known owner/analysis attributes are still counted, but as metadata.
SEMANTIC_ATTRIBUTES = frozenset({
    "id", "name", "effectiveDate", "statusCode", "isClosed", "context",
    "path", "minimumMultiplicity", "maximumMultiplicity", "conformance",
    "isMandatory", "contains", "ref", "flexibility", "datatype", "strength",
    "isOptional", "prohibited", "value", "unit", "currency", "minInclude",
    "maxInclude", "fractionDigits", "minLength", "maxLength", "test", "role",
    "flag", "see", "useWhere", "type", "level", "exception", "ordinal",
})


def _disposition(kind: str) -> ConstructDisposition:
    if kind in STRUCTURE_CONSTRUCTS:
        return "structure"
    if kind in VALIDATION_CONSTRUCTS:
        return "validation"
    if kind in PROSE_CONSTRUCTS:
        return "prose"
    if kind in EXAMPLE_CONSTRUCTS:
        return "example"
    if kind in METADATA_CONSTRUCTS:
        return "metadata"
    return "unsupported"


def inspect_template_constructs(
    templates: Iterable[ET.Element],
) -> ConstructCoverage:
    """Classify every design child and attribute in selected templates.

    Unsupported grammar children are returned with an exact template/path and
    are intended to fail compilation.  Metadata/prose/example descendants are
    opaque by design: their internal XML is not template grammar.
    """

    constructs: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    attributes: Counter[str] = Counter()
    unsupported: list[dict[str, str]] = []

    def visit(
        node: ET.Element,
        *,
        template_id: str,
        path: str,
        parent_kind: str,
        analysis_expansion: bool = False,
    ) -> None:
        for raw_name in node.attrib:
            name = local(raw_name)
            attributes[
                ("semantic:" if name in SEMANTIC_ATTRIBUTES else "metadata:")
                + name
            ] += 1

        allowed = _CHILDREN.get(parent_kind, frozenset())
        for index, child in enumerate(list(node)):
            kind = local(child.tag)
            child_path = f"{path}/{kind}[{index}]"
            disposition = _disposition(kind)
            if analysis_expansion or (
                parent_kind == "include"
                and kind in {"attribute", "element", "choice", "include"}
            ):
                disposition = "analysis-expansion"
            elif kind not in allowed:
                disposition = "unsupported"
            constructs[kind] += 1
            dispositions[disposition] += 1
            if disposition == "unsupported":
                unsupported.append({
                    "template_id": template_id,
                    "path": child_path,
                    "construct": kind,
                    "parent": parent_kind,
                })
                continue
            # Prose, examples, and metadata contain arbitrary markup/evidence,
            # not recursively executable template grammar.
            if disposition in {"prose", "example", "metadata"}:
                for raw_name in child.attrib:
                    name = local(raw_name)
                    attributes[
                        ("semantic:" if name in SEMANTIC_ATTRIBUTES else "metadata:")
                        + name
                    ] += 1
                continue
            if disposition == "analysis-expansion":
                visit(
                    child,
                    template_id=template_id,
                    path=child_path,
                    parent_kind=kind,
                    analysis_expansion=True,
                )
                continue
            visit(
                child,
                template_id=template_id,
                path=child_path,
                parent_kind=kind,
            )

    for template in templates:
        template_id = template.get("id") or ""
        constructs["template"] += 1
        dispositions["structure"] += 1
        visit(
            template,
            template_id=template_id,
            path=f"template:{template_id}",
            parent_kind="template",
        )

    return {
        "version": 1,
        "constructs": dict(sorted(constructs.items())),
        "dispositions": dict(sorted(dispositions.items())),
        "attributes": dict(sorted(attributes.items())),
        "unsupported": unsupported,
    }


def require_supported_constructs(coverage: Mapping[str, object]) -> None:
    """Reject source grammar that the compiler would otherwise drop."""

    raw = coverage.get("unsupported", [])
    unsupported = list(raw) if isinstance(raw, list) else []
    if not unsupported:
        return
    rendered = ", ".join(
        f"{item.get('construct')} below {item.get('parent')} at {item.get('path')}"
        for item in unsupported[:10]
        if isinstance(item, Mapping)
    )
    raise ValueError(f"unsupported ART-DECOR template construct(s): {rendered}")
