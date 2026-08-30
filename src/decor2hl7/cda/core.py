"""Procedural reader for the pinned CDA R2 XML Schema definition set."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


XSD = "{http://www.w3.org/2001/XMLSchema}"
CORE_REVISION = "e922fc35586fd2629f0c8a021080bca9ab424e18"
CORE_FILES = {
    "POCD_MT000040.xsd": "schema/normative/infrastructure/cda/POCD_MT000040.xsd",
    "datatypes.xsd": "schema/normative/processable/coreschemas/datatypes.xsd",
    "datatypes-base.xsd": "schema/normative/processable/coreschemas/datatypes-base.xsd",
    "infrastructureRoot.xsd": "schema/normative/processable/coreschemas/infrastructureRoot.xsd",
}
CORE_RAW_BASE = f"https://raw.githubusercontent.com/HL7/CDA-core-2.0/{CORE_REVISION}/"


@dataclass(frozen=True)
class ModelPart:
    name: str
    datatype: str
    minimum: int = 0
    maximum: int | None = 1


@dataclass(frozen=True)
class ModelAttribute:
    name: str
    datatype: str
    optional: bool = True
    fixed: str | None = None
    default: str | None = None


@dataclass(frozen=True)
class ModelDefinition:
    name: str
    base: str | None
    parts: tuple[ModelPart, ...]
    attributes: tuple[ModelAttribute, ...]


def _local_type(value: str | None) -> str:
    result = str(value or "").split(":", 1)[-1]
    return "SD.TEXT" if result == "StrucDoc.Text" else result


def _attribute_type(value: str | None) -> str:
    """Represent XSD simple/vocabulary attributes with V3 scalar datatypes."""
    result = _local_type(value)
    if result.lower() == "boolean":
        return "BL"
    if result in {"string", "ID"}:
        return "ST"
    # CDA vocabulary schema types are code-valued simple restrictions.
    return result if result in {"BL", "CS", "INT", "REAL", "ST", "TS"} else "CS"


def _maximum(value: str | None) -> int | None:
    return None if value == "unbounded" else int(value or "1")


def index_definitions(paths: Iterable[Path]) -> dict[str, ModelDefinition]:
    """Index XSD complex types without encoding individual CDA class names."""
    result: dict[str, ModelDefinition] = {}
    for path in paths:
        root = ET.parse(path).getroot()
        for node in root.findall(f".//{XSD}complexType"):
            name = node.get("name")
            if not name:
                continue
            extension = node.find(f"./{XSD}complexContent/{XSD}extension")
            content = extension if extension is not None else node
            result[name] = ModelDefinition(
                name=name,
                base=_local_type(extension.get("base")) if extension is not None else None,
                parts=tuple(
                    ModelPart(
                        "hl7:" + str(item.get("name")),
                        _local_type(item.get("type")),
                        int(item.get("minOccurs") or "1"),
                        _maximum(item.get("maxOccurs")),
                    )
                    for item in content.findall(f"./{XSD}sequence/{XSD}element")
                    if item.get("name") and item.get("type")
                ),
                attributes=tuple(
                    ModelAttribute(
                        str(item.get("name")), _attribute_type(item.get("type")),
                        item.get("use") != "required", item.get("fixed"),
                        item.get("default"),
                    )
                    for item in content.findall(f"./{XSD}attribute")
                    if item.get("name") and item.get("type")
                ),
            )
    return result


def resolve_definition(
    definitions: dict[str, ModelDefinition], name: str,
    stack: tuple[str, ...] = (),
) -> ModelDefinition:
    """Follow XSD extension inheritance and return one effective definition."""
    definition = definitions[name]
    if not definition.base or definition.base not in definitions:
        return definition
    if name in stack:
        raise ValueError("recursive CDA model inheritance: " + " -> ".join(stack + (name,)))
    base = resolve_definition(definitions, definition.base, stack + (name,))
    parts = {part.name: part for part in base.parts}
    parts.update({part.name: part for part in definition.parts})
    attributes = {item.name: item for item in base.attributes}
    attributes.update({item.name: item for item in definition.attributes})
    return ModelDefinition(
        definition.name, definition.base, tuple(parts.values()),
        tuple(attributes.values()),
    )


def structural_definition(
    definitions: dict[str, ModelDefinition], xml_name: str,
) -> ModelDefinition | None:
    """Resolve an XML element to its CDA class by schema naming convention."""
    local = xml_name.split(":", 1)[-1]
    candidates = (
        "POCD_MT000040." + local[:1].upper() + local[1:],
        local[:1].upper() + local[1:],
    )
    for candidate in candidates:
        if candidate in definitions:
            return resolve_definition(definitions, candidate)
    return None


def core_paths(release_dir: Path) -> list[Path]:
    directory = release_dir / "cda-core"
    return [directory / name for name in CORE_FILES if (directory / name).exists()]
