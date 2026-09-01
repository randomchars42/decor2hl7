"""Procedural reader for the pinned CDA R2 XML Schema definition set."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    mixed: bool = False
    category: str = "datatype"
    source: str = ""


class DefinitionIndex(dict[str, ModelDefinition]):
    """Definition registry with XSD-derived element/type relationships."""

    def __init__(self) -> None:
        super().__init__()
        self.global_elements: dict[str, str] = {}
        self.element_types: dict[str, set[str]] = {}


def _local_type(value: str | None) -> str:
    result = str(value or "").split(":", 1)[-1]
    return "SD.TEXT" if result == "StrucDoc.Text" else result


def _attribute_type(value: str | None) -> str:
    """Represent XSD simple/vocabulary attributes with V3 scalar datatypes."""
    result = _local_type(value)
    normalized = result.upper()
    if result.lower() in {"boolean", "bl"}:
        return "BL"
    if result in {"string", "ID"}:
        return "ST"
    # CDA vocabulary schema types are code-valued simple restrictions.
    return normalized if normalized in {"BL", "CS", "INT", "REAL", "ST", "TS"} else "CS"


def _maximum(value: str | None) -> int | None:
    return None if value == "unbounded" else int(value or "1")


def _effective_occurrence(
    item: ET.Element, content: ET.Element,
) -> tuple[int, int | None]:
    """Return an element's occurrence after its surrounding model groups."""
    parents = {child: parent for parent in content.iter() for child in parent}
    minimum = int(item.get("minOccurs") or "1")
    maximum = _maximum(item.get("maxOccurs"))
    current = parents.get(item)
    while current is not None and current is not content:
        local = current.tag.rsplit("}", 1)[-1]
        # A particular branch of a choice is never required by itself.
        if local == "choice" or int(current.get("minOccurs") or "1") == 0:
            minimum = 0
        group_maximum = _maximum(current.get("maxOccurs"))
        if maximum is None or group_maximum is None:
            maximum = None
        else:
            maximum *= group_maximum
        current = parents.get(current)
    return minimum, maximum


def _merge_parts(parts: Iterable[ModelPart]) -> tuple[ModelPart, ...]:
    """Collapse repeated XSD choice branches into one effective XML child."""
    grouped: dict[str, list[ModelPart]] = {}
    for part in parts:
        grouped.setdefault(part.name, []).append(part)
    result: list[ModelPart] = []
    for name, alternatives in grouped.items():
        datatypes = {part.datatype for part in alternatives}
        # Different declarations for one XML name cannot be resolved without
        # the enclosing template constraint, so do not invent one.
        if len(datatypes) != 1:
            continue
        maxima = [part.maximum for part in alternatives]
        result.append(ModelPart(
            name=name,
            datatype=alternatives[0].datatype,
            minimum=min(part.minimum for part in alternatives),
            maximum=None if any(value is None for value in maxima) else max(maxima),
        ))
    return tuple(result)


def index_definitions(paths: Iterable[Path]) -> DefinitionIndex:
    """Index one inheritance graph from the pinned CDA core XSD set."""
    result = DefinitionIndex()
    documents = [(path, ET.parse(path).getroot()) for path in paths]
    for _, root in documents:
        for node in root.findall(f"./{XSD}element"):
            if node.get("name") and node.get("type"):
                result.global_elements[str(node.get("name"))] = _local_type(node.get("type"))
    for path, root in documents:
        for node in root.findall(f".//{XSD}complexType"):
            name = node.get("name")
            if not name:
                continue
            derivation = None
            for expression in (
                f"./{XSD}complexContent/{XSD}extension",
                f"./{XSD}complexContent/{XSD}restriction",
                f"./{XSD}simpleContent/{XSD}extension",
                f"./{XSD}simpleContent/{XSD}restriction",
            ):
                derivation = node.find(expression)
                if derivation is not None:
                    break
            content = derivation if derivation is not None else node
            parts: list[ModelPart] = []
            for item in content.findall(f".//{XSD}element"):
                element_name = item.get("name") or _local_type(item.get("ref"))
                datatype = _local_type(item.get("type"))
                if not datatype and item.get("ref"):
                    datatype = result.global_elements.get(_local_type(item.get("ref")), "")
                if not element_name or not datatype:
                    continue
                minimum, maximum = _effective_occurrence(item, content)
                part = ModelPart(
                    "hl7:" + str(element_name), datatype, minimum, maximum,
                )
                parts.append(part)
                result.element_types.setdefault(str(element_name), set()).add(datatype)
            result[name] = ModelDefinition(
                name=name,
                base=_local_type(derivation.get("base")) if derivation is not None else None,
                parts=_merge_parts(parts),
                attributes=tuple(
                    ModelAttribute(
                        str(item.get("name")), _attribute_type(item.get("type")),
                        item.get("use") != "required", item.get("fixed"),
                        item.get("default"),
                    )
                    for item in content.findall(f".//{XSD}attribute")
                    if item.get("name") and item.get("type")
                ),
                mixed=node.get("mixed") == "true",
                category=(
                    "structural"
                    if name.startswith("POCD_MT") or path.name == "POCD_MT000040.xsd"
                    else "datatype"
                ),
                source=path.name,
            )
    # The CDA schema contains a few restricted datatype flavours (notably
    # InfrastructureRoot.typeId) beside the RIM classes.  Classify by resolved
    # inheritance, not merely by which XSD file happened to declare the type.
    changed = True
    while changed:
        changed = False
        for name, definition in list(result.items()):
            if (
                definition.category == "structural"
                and definition.base in result
                and result[str(definition.base)].category == "datatype"
            ):
                result[name] = replace(definition, category="datatype")
                changed = True
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
        name=definition.name,
        base=definition.base,
        parts=tuple(parts.values()),
        attributes=tuple(attributes.values()),
        mixed=definition.mixed or base.mixed,
        category=definition.category,
        source=definition.source,
    )


def structural_definition(
    definitions: dict[str, ModelDefinition], xml_name: str,
) -> ModelDefinition | None:
    """Resolve an XML element through XSD element declarations only."""
    local = xml_name.split(":", 1)[-1]
    if isinstance(definitions, DefinitionIndex):
        candidates = set(definitions.element_types.get(local, set()))
        global_type = definitions.global_elements.get(local)
        if global_type:
            candidates.add(global_type)
        structural = {
            candidate for candidate in candidates
            if candidate in definitions
            and definitions[candidate].category == "structural"
        }
        if len(structural) == 1:
            return resolve_definition(definitions, structural.pop())
    return None


def element_definition(
    definitions: dict[str, ModelDefinition],
    xml_name: str,
    *,
    declared_type: str | None = None,
    parent: ModelDefinition | None = None,
) -> ModelDefinition | None:
    """Resolve a node type from its declaration or its parent's XSD particle."""
    declared = _local_type(declared_type)
    if declared in definitions:
        return resolve_definition(definitions, declared)
    local = xml_name.split(":", 1)[-1]
    if parent is not None:
        matches = {
            part.datatype for part in parent.parts
            if part.name.split(":", 1)[-1] == local and part.datatype in definitions
        }
        if len(matches) == 1:
            return resolve_definition(definitions, matches.pop())
    return structural_definition(definitions, xml_name)


def core_paths(release_dir: Path) -> list[Path]:
    directory = release_dir / "cda-core"
    return [directory / name for name in CORE_FILES if (directory / name).exists()]
