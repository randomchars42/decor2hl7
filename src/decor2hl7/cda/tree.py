"""Shared navigation helpers for the compiled CDA document tree."""

from __future__ import annotations

from typing import Any, Mapping


Location = tuple[int, ...]


def parse_location(value: Any) -> Location | None:
    """Parse a compiled dotted tree location, returning ``None`` if invalid."""
    try:
        result = tuple(int(part) for part in str(value).split("."))
    except (TypeError, ValueError):
        return None
    return result or None


def document_index(
    cda: Mapping[str, Any],
) -> tuple[dict[Location, Mapping[str, Any]], dict[Location, Location]]:
    """Index compiled elements and attributes together with their parents."""
    nodes: dict[Location, Mapping[str, Any]] = {}
    parents: dict[Location, Location] = {}

    def walk(items: Any, prefix: Location = ()) -> None:
        if not isinstance(items, list):
            return
        for index, node in enumerate(items):
            if not isinstance(node, Mapping):
                continue
            here = prefix + (index,)
            nodes[here] = node
            if prefix:
                parents[here] = prefix
            attributes = node.get("attributes", [])
            if isinstance(attributes, list):
                for attribute_index, attribute in enumerate(attributes):
                    if not isinstance(attribute, Mapping):
                        continue
                    location = here + (100000 + attribute_index,)
                    nodes[location] = attribute
                    parents[location] = here
            walk(node.get("children", []), here)

    walk(cda.get("document", []))
    return nodes, parents
