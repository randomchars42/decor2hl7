"""Typed intermediate model shared by CDA compilation and rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class DatatypeKind(str, Enum):
    PRIMITIVE = "primitive"
    COMPLEX = "complex"
    ALIAS = "alias"
    STRUCTURAL = "structural"


class ValueRepresentationKind(str, Enum):
    ELEMENT_TEXT = "element_text"
    ATTRIBUTE = "attribute"
    XML_ATTRIBUTE = "xml_attribute"
    IDENTIFIER = "identifier"
    TIMESTAMP = "timestamp"
    QUANTITY = "quantity"
    CODED = "coded"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class ValueRepresentation:
    kind: ValueRepresentationKind
    logical_types: tuple[str, ...]
    attribute: str | None = None
    attributes: tuple[str, ...] = ()
    scalar_attribute: str | None = None
    xsi_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["kind"] = self.kind.value
        result["logical_types"] = list(self.logical_types)
        result["attributes"] = list(self.attributes)
        return {key: value for key, value in result.items() if value not in (None, (), [])}


@dataclass(frozen=True)
class DatatypeAttribute:
    name: str
    datatype: str
    optional: bool = True


@dataclass(frozen=True)
class DatatypePart:
    name: str
    datatype: str
    minimum: int = 0
    maximum: int | None = 1


@dataclass(frozen=True)
class DatatypeDefinition:
    name: str
    base: str | None
    kind: DatatypeKind
    attributes: tuple[DatatypeAttribute, ...] = ()
    parts: tuple[DatatypePart, ...] = ()
    value_representation: ValueRepresentation | None = None
    profile: str | None = None
    non_null_required_parts: tuple[str, ...] = ()
    inherit_attributes: bool = True
    inherit_parts: bool = True


@dataclass(frozen=True)
class Provenance:
    source: str
    template_id: str | None = None
    template_effective_date: str | None = None
    element_id: str | None = None
    datatype: str | None = None
    datatype_part: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value for key, value in asdict(self).items() if value is not None
        }


@dataclass(frozen=True)
class CdaValueTarget:
    name: str
    path: str
    logical_types: tuple[str, ...]
    representation: ValueRepresentation
    provenance: tuple[Provenance, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "logical_types": list(self.logical_types),
            "value_representation": self.representation.to_dict(),
            "provenance": [item.to_dict() for item in self.provenance],
        }
