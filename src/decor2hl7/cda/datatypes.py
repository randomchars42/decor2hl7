"""HL7 V3 XML value-representation policy.

Datatype structure and inheritance are read from the pinned CDA core XSD graph.
This module only describes which XML slot carries a scalar model value.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .model import DatatypeDefinition, DatatypeKind, ValueRepresentation, ValueRepresentationKind


# A type enters this set only after review shows that its declared scalar
# representation hides concrete, mapping-relevant XSD branches.  The reverse
# XSD extension index decides which branches exist; it does not decide which
# roots should be expanded throughout a document.
POLYMORPHIC_COMPLEX_ROOTS = frozenset({"SXCM_TS"})


def _text(*logical: str) -> ValueRepresentation:
    return ValueRepresentation(ValueRepresentationKind.ELEMENT_TEXT, logical or ("text",))


def _attribute(attribute: str, *logical: str) -> ValueRepresentation:
    return ValueRepresentation(ValueRepresentationKind.ATTRIBUTE, logical, attribute=attribute)


def _definition(
    name: str, *, base: str | None = None,
    kind: DatatypeKind = DatatypeKind.PRIMITIVE,
    representation: ValueRepresentation | None = None,
    profile: str | None = None,
    non_null_required_parts: tuple[str, ...] = (),
) -> DatatypeDefinition:
    return DatatypeDefinition(
        name=name, base=base, kind=kind,
        value_representation=representation, profile=profile,
        non_null_required_parts=non_null_required_parts,
    )


_POLICY: dict[str, DatatypeDefinition] = {
    "ANY": _definition("ANY"),
    "BL": _definition("BL", representation=ValueRepresentation(
        ValueRepresentationKind.BOOLEAN, ("boolean",), attribute="value")),
    "ST": _definition("ST", representation=_text("text")),
    "ED": _definition("ED", base="ST", representation=_text("text")),
    "SD.TEXT": _definition("SD.TEXT", base="ED", kind=DatatypeKind.ALIAS),
    "BIN": _definition("BIN", representation=_text("text")),
    "UID": _definition("UID", representation=_text("identifier", "text")),
    "OID": _definition("OID", base="UID", kind=DatatypeKind.ALIAS),
    "URL": _definition("URL", representation=_attribute("value", "text")),
    "TEL": _definition("TEL", representation=_attribute("value", "text")),
    "II": _definition("II", representation=ValueRepresentation(
        ValueRepresentationKind.IDENTIFIER, ("identifier",),
        attributes=("root", "extension", "assigningAuthorityName", "displayable"),
        scalar_attribute="extension")),
    "TS": _definition("TS", representation=ValueRepresentation(
        ValueRepresentationKind.TIMESTAMP, ("datetime", "date"), attribute="value")),
    "SXCM_TS": _definition("SXCM_TS", base="TS", kind=DatatypeKind.ALIAS),
    "IVL_TS": _definition("IVL_TS", kind=DatatypeKind.COMPLEX),
    "PIVL_TS": _definition("PIVL_TS", base="SXCM_TS", kind=DatatypeKind.COMPLEX),
    # The CDA XSD deliberately permits combinations that the normative V3
    # datatype rules prohibit.  A non-null event-related interval must carry
    # its TimingEvent; an offset is only a modifier of that event.
    "EIVL_TS": _definition(
        "EIVL_TS", base="SXCM_TS", kind=DatatypeKind.COMPLEX,
        non_null_required_parts=("hl7:event",),
    ),
    "EIVL.EVENT": _definition("EIVL.EVENT", base="CE", kind=DatatypeKind.ALIAS),
    "SXPR_TS": _definition("SXPR_TS", base="SXCM_TS", kind=DatatypeKind.COMPLEX),
    "INT": _definition("INT", representation=ValueRepresentation(
        ValueRepresentationKind.QUANTITY, ("integer", "ordinal", "quantity"),
        attribute="value")),
    "REAL": _definition("REAL", representation=ValueRepresentation(
        ValueRepresentationKind.QUANTITY, ("decimal", "ordinal", "quantity"),
        attribute="value")),
    "PQ": _definition("PQ", representation=ValueRepresentation(
        ValueRepresentationKind.QUANTITY, ("quantity", "decimal", "duration"),
        attributes=("value", "unit"), scalar_attribute="value")),
    "MO": _definition("MO", base="PQ", kind=DatatypeKind.ALIAS),
    "IVL_PQ": _definition("IVL_PQ", kind=DatatypeKind.COMPLEX),
    "IVL_INT": _definition("IVL_INT", kind=DatatypeKind.COMPLEX),
    "RTO_PQ_PQ": _definition("RTO_PQ_PQ", kind=DatatypeKind.COMPLEX),
    "CD": _definition("CD", representation=ValueRepresentation(
        ValueRepresentationKind.CODED, ("code", "ordinal"),
        attributes=("code", "codeSystem", "codeSystemName", "codeSystemVersion", "displayName"),
        scalar_attribute="code")),
    "CE": _definition("CE", base="CD", kind=DatatypeKind.ALIAS),
    "CV": _definition("CV", base="CE", kind=DatatypeKind.ALIAS),
    "CS": _definition("CS", base="CV", kind=DatatypeKind.ALIAS),
    "CO": _definition("CO", base="CV", kind=DatatypeKind.ALIAS),
    "SC": _definition("SC", base="CV", kind=DatatypeKind.ALIAS),
    "CR": _definition("CR", kind=DatatypeKind.COMPLEX),
    "ADXP": _definition("ADXP", base="ST", kind=DatatypeKind.ALIAS),
    "AD": _definition("AD", kind=DatatypeKind.COMPLEX),
    "ENXP": _definition("ENXP", base="ST", kind=DatatypeKind.ALIAS),
    "EN": _definition("EN", kind=DatatypeKind.COMPLEX),
    "PN": _definition("PN", base="EN", kind=DatatypeKind.ALIAS),
    "ON": _definition("ON", base="EN", kind=DatatypeKind.ALIAS),
}

for alias, base, profile in (
    ("TS.DATE.MIN", "TS", "DATE.MIN"), ("TS.DATETIME.MIN", "TS", "DATETIME.MIN"),
    ("INT.POS", "INT", "POS"), ("CS.LANG", "CS", "LANG"),
):
    _POLICY[alias] = _definition(alias, base=base, kind=DatatypeKind.ALIAS, profile=profile)


def normalize_datatype(name: str | None) -> str:
    return str(name or "").strip().upper()


def datatype_definition(name: str) -> DatatypeDefinition:
    try:
        return _POLICY[normalize_datatype(name)]
    except KeyError as exc:
        raise KeyError(f"unsupported HL7 V3 datatype {name!r}") from exc


def expand_datatype(name: str, stack: tuple[str, ...] = ()) -> DatatypeDefinition:
    declared = datatype_definition(name)
    if not declared.base:
        return declared
    if declared.name in stack:
        raise ValueError("recursive HL7 datatype inheritance: " + " -> ".join(stack + (declared.name,)))
    base = expand_datatype(declared.base, stack + (declared.name,))
    required_parts = tuple(dict.fromkeys(
        (*base.non_null_required_parts, *declared.non_null_required_parts)
    ))
    return replace(
        declared,
        value_representation=declared.value_representation or base.value_representation,
        non_null_required_parts=required_parts,
    )


def base_datatype(name: str) -> str:
    definition = datatype_definition(name)
    while definition.base:
        definition = datatype_definition(definition.base)
    return definition.name


def classify_datatype(name: str | None) -> str:
    normalized = normalize_datatype(name)
    if not normalized:
        return "none"
    if normalized in _POLICY:
        return "alias" if _POLICY[normalized].kind == DatatypeKind.ALIAS else "datatype"
    if normalized.startswith("POCD_MT") or normalized == "CLINICALDOCUMENT":
        return "structural"
    return "unsupported"


def value_representation(
    name: str | None, *, attribute_name: str | None = None,
) -> ValueRepresentation | None:
    if attribute_name is not None:
        normalized = normalize_datatype(name)
        logical = (
            ("boolean",) if normalized == "BL" else
            ("datetime", "date") if normalized in {"TS", "TS.DATE.MIN", "TS.DATETIME.MIN"} else
            ("integer", "ordinal") if normalized in {"INT", "INT.POS"} else
            ("decimal",) if normalized == "REAL" else ("text",)
        )
        return ValueRepresentation(ValueRepresentationKind.XML_ATTRIBUTE, logical, attribute=attribute_name)
    if classify_datatype(name) not in {"datatype", "alias"}:
        return None
    return expand_datatype(str(name)).value_representation


def datatype_inventory(nodes: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {
        "datatype": set(), "alias": set(), "structural": set(), "unsupported": set(),
    }

    def add(value: Any) -> None:
        if value:
            normalized = normalize_datatype(str(value))
            category = classify_datatype(normalized)
            if category != "none":
                result[category].add(normalized)

    def walk(items: Iterable[Mapping[str, Any]]) -> None:
        for node in items:
            add(node.get("datatype"))
            for attribute in node.get("attributes", []):
                if isinstance(attribute, Mapping):
                    add(attribute.get("datatype"))
            walk(child for child in node.get("children", []) if isinstance(child, Mapping))

    walk(nodes)
    return {key: sorted(values) for key, values in result.items()}
