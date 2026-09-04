"""Repository-context inference and version-aware owner caching."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from ..workspace import load_json, write_json
from .xml import local, parse_text


def project_from_link(value: str | None) -> str:
    """Return a project prefix carried by an ART-DECOR link."""
    if not value:
        return ""
    parsed = urlsplit(value)
    for query in (parsed.query, urlsplit(parsed.fragment).query):
        values = parse_qs(query)
        for name in ("project", "prefix"):
            if values.get(name):
                return values[name][0]
    path = unquote("/".join(filter(None, (parsed.path, parsed.fragment))))
    match = re.search(r"(?:^|/)project/([^/?#]+-)(?:/|$)", path)
    return match.group(1) if match else ""


def reference_project(node: ET.Element) -> str:
    """Prefer an explicit prefix, then derive project context from links."""
    if node.get("prefix"):
        return node.get("prefix") or ""
    for name in ("href", "url", "link", "source", "canonicalUri"):
        project = project_from_link(node.get(name))
        if project:
            return project
    for name, value in node.attrib.items():
        if local(name).lower().endswith(("href", "url", "link", "uri")):
            project = project_from_link(value)
            if project:
                return project
    return ""


def project_owner(identifier: str, directory: Mapping[str, str]) -> str:
    """Resolve the longest authoritative OID-prefix owner."""
    best = ""
    for project_id in directory:
        if identifier == project_id or identifier.startswith(project_id + "."):
            if len(project_id) > len(best):
                best = project_id
    return directory.get(best, "") if best else ""


def artifact_owner_key(
    kind: str, identifier: str, effective_date: str = "",
) -> str:
    return f"{kind}:{identifier}@{effective_date or 'dynamic'}"


def indexed_artifact_owner(
    artifact_owners: Mapping[str, str], want: Mapping[str, object],
) -> str:
    return artifact_owners.get(artifact_owner_key(
        str(want.get("kind") or ""), str(want.get("id") or ""),
        str(want.get("effective_date") or ""),
    ), "")


def remember_artifact_owner(
    artifact_owners: dict[str, str],
    want: Mapping[str, object],
    project: str,
    *,
    replace: bool = False,
) -> bool:
    if not project:
        return False
    key = artifact_owner_key(
        str(want.get("kind") or ""), str(want.get("id") or ""),
        str(want.get("effective_date") or ""),
    )
    current = artifact_owners.get(key) or ""
    if key == ":" or current == project or (current and not replace):
        return False
    artifact_owners[key] = project
    return True


def payload_artifact_owner(payload: bytes, want: Mapping[str, object]) -> str:
    """Read repository context from an API response/reference stub."""
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return ""
    identifier = str(want.get("id") or "")
    names = {
        "id", "ref", "template", "valueSet", "codeSystem", "datasetId",
        "sourceDataset",
    }
    for node in root.iter():
        if identifier and not any(node.get(name) == identifier for name in names):
            continue
        project = reference_project(node)
        if project:
            return project
    return ""


def load_artifact_owners(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = load_json(path)
    # Format 1 did not include effective dates and is unsafe for history.
    if not isinstance(data, Mapping) or data.get("format") != 2:
        return {}
    owners = data.get("owners", {})
    if not isinstance(owners, Mapping):
        return {}
    return {str(key): str(value) for key, value in owners.items() if key and value}


def write_artifact_owners(path: Path, artifact_owners: Mapping[str, str]) -> None:
    write_json(path, {"format": 2, "owners": dict(sorted(artifact_owners.items()))})


def candidate_projects(
    want: Mapping[str, object],
    oid_owners: Mapping[str, str],
    repositories: Iterable[str],
    artifact_owners: Mapping[str, str] | None = None,
    configured_oid_owners: Mapping[str, str] | None = None,
) -> list[str]:
    """Order repository candidates without widening authoritative scope."""
    identifier = str(want["id"])
    owner = project_owner(identifier, oid_owners)
    configured_owner = project_owner(identifier, configured_oid_owners or {})
    declared = str(want.get("project") or "")
    indexed = indexed_artifact_owner(artifact_owners or {}, want)
    result: list[str] = []
    if owner:
        result.append(owner)
        if declared and declared != owner:
            result.append(declared)
        return result
    for value in (configured_owner, declared, indexed):
        if value and value not in result:
            result.append(value)
    for value in repositories:
        if value and value not in result:
            result.append(value)
    return result or [""]
