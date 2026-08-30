"""Deterministic HL7 V3 datatype catalogue used by the CDA compiler.

The catalogue is compiler knowledge derived from HL7 Version 3 Data Types,
Release 2 and the CDA R2 model.  It intentionally contains no ART-DECOR or
AKTIN mapping decisions.  Coverage is measured from the effective template at
build time, so an unknown datatype fails explicitly instead of becoming an
opaque writable node.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .model import (
    DatatypeAttribute,
    DatatypeDefinition,
    DatatypeKind,
    DatatypePart,
    ValueRepresentation,
    ValueRepresentationKind,
)


def _text(*logical: str) -> ValueRepresentation:
    return ValueRepresentation(ValueRepresentationKind.ELEMENT_TEXT, logical or ("text",))


def _attribute(attribute: str, *logical: str) -> ValueRepresentation:
    return ValueRepresentation(
        ValueRepresentationKind.ATTRIBUTE, logical, attribute=attribute
    )


def _definition(
    name: str,
    *,
    base: str | None = None,
    kind: DatatypeKind = DatatypeKind.PRIMITIVE,
    attributes: tuple[DatatypeAttribute, ...] = (),
    parts: tuple[DatatypePart, ...] = (),
    representation: ValueRepresentation | None = None,
    profile: str | None = None,
    inherit_attributes: bool = True,
    inherit_parts: bool = True,
) -> DatatypeDefinition:
    return DatatypeDefinition(
        name=name,
        base=base,
        kind=kind,
        attributes=attributes,
        parts=parts,
        value_representation=representation,
        profile=profile,
        inherit_attributes=inherit_attributes,
        inherit_parts=inherit_parts,
    )


_CODE_ATTRIBUTES = tuple(
    DatatypeAttribute(name, "ST")
    for name in (
        "code", "codeSystem", "codeSystemName", "codeSystemVersion",
        "displayName",
    )
)

_CATALOGUE: dict[str, DatatypeDefinition] = {
    "ANY": _definition("ANY", representation=None),
    "BL": _definition("BL", representation=ValueRepresentation(
        ValueRepresentationKind.BOOLEAN, ("boolean",), attribute="value"
    )),
    "ST": _definition("ST", representation=_text("text")),
    "ED": _definition(
        "ED", base="ST", representation=_text("text"),
        attributes=(
            DatatypeAttribute("mediaType", "ST"),
            DatatypeAttribute("language", "ST"),
            DatatypeAttribute("compression", "CS"),
            DatatypeAttribute("integrityCheck", "BIN"),
            DatatypeAttribute("integrityCheckAlgorithm", "CS"),
        ),
    ),
    "SD.TEXT": _definition("SD.TEXT", base="ED", kind=DatatypeKind.ALIAS),
    "BIN": _definition("BIN", representation=_text("text")),
    "UID": _definition("UID", representation=_text("identifier", "text")),
    "OID": _definition("OID", base="UID", kind=DatatypeKind.ALIAS),
    "URL": _definition("URL", representation=_text("text")),
    "TEL": _definition(
        "TEL",
        attributes=(
            DatatypeAttribute("value", "URL", optional=False),
            DatatypeAttribute("use", "CS"),
        ),
        representation=_attribute("value", "text"),
    ),
    "II": _definition(
        "II",
        attributes=tuple(
            DatatypeAttribute(name, "ST")
            for name in ("root", "extension", "assigningAuthorityName", "displayable")
        ),
        representation=ValueRepresentation(
            ValueRepresentationKind.IDENTIFIER,
            ("identifier",),
            attributes=("root", "extension", "assigningAuthorityName", "displayable"),
            scalar_attribute="extension",
        ),
    ),
    "TS": _definition(
        "TS",
        attributes=(DatatypeAttribute("value", "ST"),),
        representation=ValueRepresentation(
            ValueRepresentationKind.TIMESTAMP,
            ("datetime", "date"),
            attribute="value",
        ),
    ),
    "SXCM_TS": _definition("SXCM_TS", base="TS", kind=DatatypeKind.ALIAS),
    "IVL_TS": _definition(
        "IVL_TS",
        kind=DatatypeKind.COMPLEX,
        parts=(
            DatatypePart("hl7:low", "TS"),
            DatatypePart("hl7:high", "TS"),
            DatatypePart("hl7:center", "TS"),
            DatatypePart("hl7:width", "PQ"),
        ),
    ),
    "PIVL_TS": _definition(
        "PIVL_TS", base="SXCM_TS", kind=DatatypeKind.COMPLEX,
        parts=(DatatypePart("hl7:phase", "IVL_TS"), DatatypePart("hl7:period", "PQ")),
    ),
    "EIVL_TS": _definition(
        "EIVL_TS", base="SXCM_TS", kind=DatatypeKind.COMPLEX,
        parts=(DatatypePart("hl7:event", "CE"), DatatypePart("hl7:offset", "IVL_PQ")),
    ),
    "INT": _definition(
        "INT", representation=ValueRepresentation(
            ValueRepresentationKind.QUANTITY,
            ("integer", "ordinal", "quantity"),
            attribute="value",
        ),
    ),
    "REAL": _definition(
        "REAL", representation=ValueRepresentation(
            ValueRepresentationKind.QUANTITY,
            ("decimal", "ordinal", "quantity"),
            attribute="value",
        ),
    ),
    "PQ": _definition(
        "PQ",
        attributes=(DatatypeAttribute("value", "REAL"), DatatypeAttribute("unit", "ST")),
        representation=ValueRepresentation(
            ValueRepresentationKind.QUANTITY,
            ("quantity", "decimal", "duration"),
            attributes=("value", "unit"),
            scalar_attribute="value",
        ),
    ),
    "MO": _definition("MO", base="PQ", kind=DatatypeKind.ALIAS),
    "IVL_PQ": _definition(
        "IVL_PQ", kind=DatatypeKind.COMPLEX,
        parts=tuple(DatatypePart(f"hl7:{name}", "PQ") for name in ("low", "high", "center", "width")),
    ),
    "RTO_PQ_PQ": _definition(
        "RTO_PQ_PQ", kind=DatatypeKind.COMPLEX,
        parts=(DatatypePart("hl7:numerator", "PQ"), DatatypePart("hl7:denominator", "PQ")),
    ),
    "CD": _definition(
        "CD",
        attributes=_CODE_ATTRIBUTES,
        parts=(
            DatatypePart("hl7:originalText", "ED"),
            DatatypePart("hl7:qualifier", "CR", maximum=None),
            DatatypePart("hl7:translation", "CD", maximum=None),
        ),
        representation=ValueRepresentation(
            ValueRepresentationKind.CODED,
            ("code", "ordinal"),
            attributes=("code", "codeSystem", "codeSystemName", "codeSystemVersion", "displayName"),
            scalar_attribute="code",
        ),
    ),
    "CE": _definition("CE", base="CD", kind=DatatypeKind.ALIAS),
    "CV": _definition("CV", base="CE", kind=DatatypeKind.ALIAS, inherit_parts=False),
    "CS": _definition("CS", base="CV", kind=DatatypeKind.ALIAS, inherit_parts=False),
    "CO": _definition("CO", base="CV", kind=DatatypeKind.ALIAS, inherit_parts=False),
    "SC": _definition("SC", base="CV", kind=DatatypeKind.ALIAS, inherit_parts=False),
    "CR": _definition(
        "CR", kind=DatatypeKind.COMPLEX,
        parts=(DatatypePart("hl7:name", "CV"), DatatypePart("hl7:value", "CD")),
    ),
    "ADXP": _definition("ADXP", base="ST", kind=DatatypeKind.ALIAS),
    "AD": _definition(
        "AD", kind=DatatypeKind.COMPLEX,
        attributes=(DatatypeAttribute("use", "CS"),),
        parts=tuple(
            DatatypePart(f"hl7:{name}", "ADXP", maximum=None)
            for name in (
                "delimiter", "country", "state", "county", "city", "postalCode",
                "streetAddressLine", "houseNumber", "houseNumberNumeric",
                "direction", "streetName", "streetNameBase", "streetNameType",
                "additionalLocator", "unitID", "unitType", "careOf", "censusTract",
                "deliveryAddressLine", "deliveryInstallationType",
                "deliveryInstallationArea", "deliveryInstallationQualifier",
                "deliveryMode", "deliveryModeIdentifier", "buildingNumberSuffix",
                "postBox", "precinct",
            )
        ),
    ),
    "ENXP": _definition("ENXP", base="ST", kind=DatatypeKind.ALIAS),
    "EN": _definition(
        "EN", kind=DatatypeKind.COMPLEX,
        attributes=(DatatypeAttribute("use", "CS"),),
        parts=tuple(
            DatatypePart(f"hl7:{name}", "ENXP", maximum=None)
            for name in ("delimiter", "family", "given", "prefix", "suffix")
        ),
    ),
    "PN": _definition("PN", base="EN", kind=DatatypeKind.ALIAS),
    "ON": _definition("ON", base="EN", kind=DatatypeKind.ALIAS),
}

for alias, base, profile in (
    ("TS.DATE.MIN", "TS", "DATE.MIN"),
    ("TS.DATETIME.MIN", "TS", "DATETIME.MIN"),
    ("INT.POS", "INT", "POS"),
    ("CS.LANG", "CS", "LANG"),
):
    _CATALOGUE[alias] = _definition(
        alias, base=base, kind=DatatypeKind.ALIAS, profile=profile
    )


STRUCTURAL_TYPES = {
    "CLINICALDOCUMENT", "POCD_MT000040.CLINICALDOCUMENT",
    "POCD_MT000040.RECORDTARGET", "POCD_MT000040.PATIENTROLE",
    "POCD_MT000040.STRUCTUREDBODY", "POCD_MT000040.SECTION",
}


def normalize_datatype(name: str | None) -> str:
    return str(name or "").strip().upper()


def datatype_definition(name: str) -> DatatypeDefinition:
    normalized = normalize_datatype(name)
    try:
        return _CATALOGUE[normalized]
    except KeyError as exc:
        raise KeyError(f"unsupported HL7 V3 datatype {name!r}") from exc


def expand_datatype(name: str, stack: tuple[str, ...] = ()) -> DatatypeDefinition:
    """Resolve inheritance while retaining the declared datatype identity."""
    declared = datatype_definition(name)
    if not declared.base:
        return declared
    if declared.name in stack:
        raise ValueError("recursive HL7 datatype inheritance: " + " -> ".join(stack + (declared.name,)))
    base = expand_datatype(declared.base, stack + (declared.name,))
    attributes = {
        item.name: item for item in base.attributes
    } if declared.inherit_attributes else {}
    attributes.update({item.name: item for item in declared.attributes})
    parts = {item.name: item for item in base.parts} if declared.inherit_parts else {}
    parts.update({item.name: item for item in declared.parts})
    return replace(
        declared,
        attributes=tuple(attributes.values()),
        parts=tuple(parts.values()),
        value_representation=(
            declared.value_representation or base.value_representation
        ),
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
    if normalized in _CATALOGUE:
        definition = _CATALOGUE[normalized]
        return "alias" if definition.kind == DatatypeKind.ALIAS else "datatype"
    if normalized in STRUCTURAL_TYPES or normalized.startswith("POCD_MT"):
        return "structural"
    return "unsupported"


def value_representation(
    name: str | None, *, attribute_name: str | None = None
) -> ValueRepresentation | None:
    if attribute_name is not None:
        logical = ("text",)
        normalized = normalize_datatype(name)
        if normalized == "BL":
            logical = ("boolean",)
        elif normalized in {"TS", "TS.DATE.MIN", "TS.DATETIME.MIN"}:
            logical = ("datetime", "date")
        elif normalized in {"INT", "INT.POS"}:
            logical = ("integer", "ordinal")
        elif normalized == "REAL":
            logical = ("decimal",)
        return ValueRepresentation(
            ValueRepresentationKind.XML_ATTRIBUTE,
            logical,
            attribute=attribute_name,
        )
    if classify_datatype(name) not in {"datatype", "alias"}:
        return None
    return expand_datatype(str(name)).value_representation


def datatype_inventory(nodes: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Classify all declared datatypes in an effective template tree."""
    result: dict[str, set[str]] = {
        "datatype": set(), "alias": set(), "structural": set(), "unsupported": set()
    }

    def add(value: Any) -> None:
        if not value:
            return
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
            walk(
                child for child in node.get("children", [])
                if isinstance(child, Mapping)
            )

    walk(nodes)
    return {key: sorted(values) for key, values in result.items()}
