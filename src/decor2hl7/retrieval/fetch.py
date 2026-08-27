"""Fetch a recursively closed specification through the current API.

The release is the cache scope; a transaction owns only ``transaction.xml``
and ``closure.json``. Shared datasets/templates/value sets/concepts are stored
once below ``spec/<release>/`` and may be reused by other transactions in the
same release.

The selected transaction and its exact artifact dependencies define build
truth. A live project extract is fetched once as *evidence only*: it may
provide historical associations/lineage for mapping analysis but never changes
model/template selection.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, TypedDict
from urllib.parse import parse_qs, unquote, urlsplit

from .api import (
    artifact_representations,
    openapi_url,
    project_extract_url,
    project_url,
    projects_url,
    transaction_representations,
    validate_openapi,
    valueset_expansion_url,
)
from .client import DEFAULT_API_BASE, FINAL_STATUS, get
from .sources import apply_source_hint
from .xml import local, parse_text
from ..workspace import load_json, write_json


class Want(TypedDict, total=False):
    kind: str
    id: str
    effective_date: str
    project: str
    api_base: str
    publication_url: str
    source_hint: str
    dataset: str
    dataset_effective_date: str


KINDS = {"dataset", "concept", "template", "valueset", "codesystem"}
KIND_ORDER = {
    "dataset": 0,
    "template": 1,
    "valueset": 2,
    "codesystem": 3,
    "concept": 4,
}


class RequestBudgetExceeded(RuntimeError):
    """Recursive fetch stopped before another HTTP attempt could be made."""


Progress = Callable[[str], None]


def _emit(progress: Progress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _resource_label(want: Mapping[str, str]) -> str:
    effective = want.get("effective_date") or "dynamic"
    return f"{want.get('kind', 'resource')} {want.get('id', '?')} @ {effective}"


def _size_text(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "resource"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity(
    want: Mapping[str, str],
    *,
    project: str = "",
    effective_date: str = "",
    api_base: str = "",
) -> dict[str, str]:
    """Return the complete retrieval identity recorded with cached artifacts."""
    return {
        "type": want.get("kind", ""),
        "id": want.get("id", ""),
        "effective_date": effective_date or want.get("effective_date", "") or "dynamic",
        "project": project or want.get("project", ""),
        "api_base": api_base or want.get("api_base", "") or DEFAULT_API_BASE,
        **({"context_id": want["dataset"]} if want.get("dataset") else {}),
        **(
            {"context_effective_date": want["dataset_effective_date"]}
            if want.get("dataset_effective_date") else {}
        ),
    }


def _key(want: Mapping[str, str]) -> str:
    effective = want.get("effective_date") or ""
    suffix = f"@{effective}" if effective else ""
    key = f"{want['kind']}:{want['id']}{suffix}"
    dataset = want.get("dataset") or ""
    if dataset:
        dataset_date = want.get("dataset_effective_date") or ""
        key += f"|context={dataset}{('@' + dataset_date) if dataset_date else ''}"
    return key


def _filename(want: Mapping[str, str], form: str = "analysis") -> str:
    stamp = _safe(want.get("effective_date") or "")
    name = _safe(want["id"])
    if stamp:
        name += f"_{stamp}"
    directory = {
        "dataset": "datasets",
        "template": "templates",
        "valueset": "valuesets",
        "codesystem": "codesystems",
        "concept": "concepts",
    }[want["kind"]]
    suffix = "" if form == "analysis" else f".{form}"
    return f"{directory}/{name}{suffix}.xml"


def classify_payload(payload: bytes) -> tuple[str, str]:
    """Return ``ok``, ``empty`` or ``unparseable`` for a service response."""
    if not payload.strip():
        return "empty", "zero bytes"
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError) as error:
        return "unparseable", str(error)
    if len(list(root)) == 0 and not (root.text or "").strip():
        return "empty", f"<{local(root.tag)}/> with no content"
    return "ok", ""


def _parse(path: Path) -> ET.Element | None:
    try:
        return parse_text(path.read_text(encoding="utf-8", errors="replace"))[0]
    except (ET.ParseError, OSError):
        return None


def _project_from_link(value: str | None) -> str:
    """Return an ART-DECOR project prefix carried by a link, if present."""
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


def _reference_project(node: ET.Element) -> str:
    """Prefer an explicit prefix, then derive project context from links."""
    if node.get("prefix"):
        return node.get("prefix") or ""
    preferred = ("href", "url", "link", "source", "canonicalUri")
    for name in preferred:
        project = _project_from_link(node.get(name))
        if project:
            return project
    for name, value in node.attrib.items():
        lowered = local(name).lower()
        if lowered.endswith(("href", "url", "link", "uri")):
            project = _project_from_link(value)
            if project:
                return project
    return ""


def _collect_references(root: ET.Element, *, soft: bool) -> list[Want]:
    """Extract either recursive build dependencies or direct evidence refs.

    Build dependencies are resources required to materialize the selected data
    model/CDA structure and may be recursively closed. Evidence references are
    semantic lineage targets (SPEC/INHERIT/ADAPT/etc.) that may improve mapping;
    they are resolved as the smallest directly referenced resource and are never
    recursively expanded by the fetcher.
    """
    found: dict[tuple[str, str, str, str, str, str], Want] = {}
    reference_project = ""

    def add(kind: str, ident: str | None, effective: str | None = None,
            project: str | None = None, dataset: str | None = None,
            dataset_effective_date: str | None = None) -> None:
        if not ident or kind not in KINDS:
            return
        want: Want = {
            "kind": kind,
            "id": ident,
            "effective_date": "" if effective in (None, "dynamic") else str(effective),
            "project": project or reference_project,
        }
        if dataset:
            want["dataset"] = dataset
        if dataset_effective_date:
            want["dataset_effective_date"] = dataset_effective_date
        found[(
            kind, ident, want["effective_date"], want["project"],
            want.get("dataset", ""), want.get("dataset_effective_date", ""),
        )] = want

    stack: list[tuple[ET.Element, tuple[str, ...]]] = [(root, ())]
    while stack:
        node, ancestors = stack.pop()
        tag = local(node.tag)
        parent_tag = ancestors[-1] if ancestors else ""
        reference_project = _reference_project(node)
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
                    node.get("ref"), node.get("flexibility"),
                )
                continue
            if tag == "answerValueSet":
                add("valueset", node.get("ref"), node.get("flexibility"))
                continue
            if tag == "contains":
                dataset = node.get("datasetId")
                if dataset:
                    add(
                        "dataset", dataset, node.get("datasetEffectiveDate"),
                        node.get("prefix"),
                    )
                elif node.get("ref"):
                    # A structural contains without dataset metadata still has
                    # to materialize the referred concept itself.
                    add(
                        "concept", node.get("ref"),
                        node.get("effectiveDate") or node.get("flexibility"),
                        node.get("prefix"),
                    )
                continue
            if tag == "relationship" and node.get("template"):
                if (node.get("type") or "") in {"SPEC", "VERSION", "COPY"}:
                    add(
                        "template", node.get("template"),
                        node.get("flexibility"), node.get("prefix"),
                    )
                continue
            if tag == "element":
                add("template", node.get("contains"), node.get("flexibility"))
            elif tag == "representingTemplate":
                add("template", node.get("ref"), node.get("flexibility"))
                add(
                    "dataset", node.get("sourceDataset"),
                    node.get("sourceDatasetFlexibility"),
                )
            elif tag == "valueSet":
                if node.get("ref"):
                    add("valueset", node.get("ref"), node.get("flexibility"))
                elif node.get("id"):
                    add("valueset", node.get("id"), node.get("effectiveDate"))
            elif tag == "vocabulary":
                add("valueset", node.get("valueSet"), node.get("flexibility"))
                add(
                    "codesystem", node.get("codeSystem"),
                    node.get("codeSystemEffectiveDate"), node.get("prefix"),
                )
            elif tag == "sourceCodeSystem":
                add(
                    "codesystem", node.get("id"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                )
            elif tag == "include" and node.get("codeSystem"):
                add(
                    "codesystem", node.get("codeSystem"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"),
                )
            elif tag in {"concept", "exception"} and node.get("codeSystem"):
                add(
                    "codesystem", node.get("codeSystem"),
                    node.get("codeSystemEffectiveDate"), node.get("prefix"),
                )
            if node.get("templateId") and tag in {"dataset", "transaction"}:
                add("template", node.get("templateId"), node.get("templateEffectiveDate"))
            continue

        # Evidence mode: semantic lineage is useful, but its containing dataset
        # is not a recursive dependency. Resolve the directly referenced concept
        # (or non-structural template) only when it is not already available.
        if tag == "inherit":
            add(
                "concept", node.get("ref"),
                node.get("effectiveDate") or node.get("flexibility"),
                node.get("prefix"), node.get("datasetId"),
                node.get("datasetEffectiveDate"),
            )
            add(
                "concept", node.get("originalId"), node.get("originalEffectiveDate"),
                node.get("originalPrefix"),
            )
        elif tag == "relationship":
            if node.get("ref") and parent_tag == "concept":
                add(
                    "concept", node.get("ref"),
                    node.get("effectiveDate") or node.get("flexibility"),
                    node.get("prefix"), node.get("datasetId"),
                    node.get("datasetEffectiveDate"),
                )
            if node.get("template") and (node.get("type") or "") not in {"SPEC", "VERSION", "COPY"}:
                add(
                    "template", node.get("template"),
                    node.get("flexibility"), node.get("prefix"),
                )
    rows = list(found.values())
    dated_code_systems = {
        (item["id"], item.get("project", ""))
        for item in rows
        if item["kind"] == "codesystem" and item.get("effective_date")
    }
    return [
        item for item in rows
        if not (
            item["kind"] == "codesystem"
            and not item.get("effective_date")
            and (item["id"], item.get("project", "")) in dated_code_systems
        )
    ]


def hard_references(root: ET.Element) -> list[Want]:
    """Resources that are recursively required to build the selected spec."""
    return _collect_references(root, soft=False)


def soft_references(root: ET.Element) -> list[Want]:
    """Direct non-recursive semantic evidence references."""
    return _collect_references(root, soft=True)


def references(root: ET.Element) -> list[Want]:
    """Backward-compatible name for recursive/build dependencies."""
    return hard_references(root)



def _valueset_complete(node: ET.Element) -> bool:
    for child in node.iter():
        if local(child.tag) in {"concept", "exception"} and child.get("code") and child.get("codeSystem"):
            return True
    return False


def _inventory(root: ET.Element | None) -> set[tuple[str, str, str]]:
    """Resources already embedded in an XML document (kind, id, effectiveDate)."""
    result: set[tuple[str, str, str]] = set()
    if root is None:
        return result
    tags = {
        "dataset": "dataset",
        "concept": "concept",
        "template": "template",
        "valueSet": "valueset",
        "codeSystem": "codesystem",
    }
    for node in root.iter():
        kind = tags.get(local(node.tag))
        ident = node.get("id")
        if not kind or not ident:
            continue
        if kind == "template" and not (node.get("name") or node.get("displayName") or node.get("effectiveDate")):
            continue
        if kind == "valueset" and not _valueset_complete(node):
            continue
        result.add((kind, ident, node.get("effectiveDate") or ""))
    return result


def _satisfied(want: Mapping[str, str], have: set[tuple[str, str, str]]) -> bool:
    kind, ident, effective = want["kind"], want["id"], want.get("effective_date") or ""
    if effective:
        return (kind, ident, effective) in have
    return any(k == kind and i == ident for k, i, _ in have)

def _matching_embedded(
    roots: Iterable[ET.Element | None],
    want: Mapping[str, str],
    *,
    not_after: str = "",
) -> list[ET.Element]:
    """Return the embedded resource revision that satisfies *want*.

    ``not_after`` is used for the live main-project snapshot: a live
    project may contain draft template revisions newer than the selected
    release, and those must never become part of a released build merely
    because they are locally available.  For a dynamic reference the newest
    eligible revision is returned.
    """
    tag_for = {
        "dataset": "dataset",
        "concept": "concept",
        "template": "template",
        "valueset": "valueSet",
        "codesystem": "codeSystem",
    }
    wanted_tag = tag_for.get(want.get("kind", ""))
    if not wanted_tag:
        return []
    rows: list[ET.Element] = []
    effective = want.get("effective_date") or ""
    for root in roots:
        if root is None:
            continue
        for node in root.iter():
            if local(node.tag) != wanted_tag or node.get("id") != want.get("id"):
                continue
            node_effective = node.get("effectiveDate") or ""
            if effective and node_effective != effective:
                continue
            if not_after and node_effective and node_effective > not_after:
                continue
            if wanted_tag == "template" and not (node.get("name") or node.get("displayName") or node_effective):
                continue
            rows.append(node)
    if effective or len(rows) <= 1:
        return rows
    rows.sort(key=lambda node: node.get("effectiveDate") or "")
    return rows[-1:]


def _evidence_references(root: ET.Element, relevant_ids: set[str]) -> list[Want]:
    """External evidence references relevant to the selected transaction only.

    The complete live *main* project is already available locally for lineage
    and templateAssociation analysis.  This function deliberately avoids
    recursively harvesting dependencies of unrelated live-project content.
    """
    found: dict[str, Want] = {}
    for node in root.iter():
        kind = local(node.tag)
        selected = False
        if kind == "concept" and node.get("id"):
            linked = {node.get("id") or ""}
            for child in list(node):
                if local(child.tag) in {"inherit", "relationship"}:
                    linked.update(filter(None, (child.get("ref"), child.get("originalId"))))
            selected = bool(linked & relevant_ids)
        elif kind == "templateAssociation":
            selected = any(
                local(child.tag) == "concept" and (child.get("ref") or "") in relevant_ids
                for child in list(node)
            )
        elif kind == "template" and node.get("id"):
            selected = (node.get("id") or "") in relevant_ids
        if not selected:
            continue
        for want in soft_references(node):
            found[_key(want)] = want
    return list(found.values())


def _resolved_effective_date(payload: bytes, want: Mapping[str, str]) -> str:
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return ""
    tag_for = {
        "dataset": "dataset",
        "concept": "concept",
        "template": "template",
        "valueset": "valueSet",
        "codesystem": "codeSystem",
    }
    wanted_tag = tag_for.get(want.get("kind", ""))
    rows: list[str] = []
    for node in root.iter():
        if wanted_tag and local(node.tag) == wanted_tag and node.get("id") == want.get("id"):
            if node.get("effectiveDate"):
                rows.append(node.get("effectiveDate") or "")
    if not rows and root.get("effectiveDate"):
        rows.append(root.get("effectiveDate") or "")
    return max(rows) if rows else ""


def _repositories(*roots: ET.Element | None, own: str) -> list[str]:
    result = [own]
    for root in roots:
        if root is None:
            continue
        for node in root.iter():
            if local(node.tag) == "buildingBlockRepository" and node.get("ident"):
                ident = node.get("ident") or ""
                if ident and ident not in result:
                    result.append(ident)
    return result


def _project_directory(root: ET.Element | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if root is None:
        return result
    for node in root.iter():
        ident = node.get("id")
        prefix = node.get("prefix") or node.get("ident")
        if ident and prefix and ident not in result:
            result[ident] = prefix
    return result


def _owner(identifier: str, directory: Mapping[str, str]) -> str:
    best = ""
    for project_id in directory:
        if identifier == project_id or identifier.startswith(project_id + "."):
            if len(project_id) > len(best):
                best = project_id
    return directory.get(best, "") if best else ""


def _artifact_owner_key(
    kind: str, identifier: str, effective_date: str = "",
) -> str:
    effective = effective_date or "dynamic"
    return f"{kind}:{identifier}@{effective}"


def _indexed_artifact_owner(
    artifact_owners: Mapping[str, str],
    want: Mapping[str, str],
) -> str:
    return artifact_owners.get(
        _artifact_owner_key(
            want.get("kind", ""),
            want.get("id", ""),
            want.get("effective_date", ""),
        ),
        "",
    )


def _remember_artifact_owner(
    artifact_owners: dict[str, str],
    want: Mapping[str, str],
    project: str,
    *,
    replace: bool = False,
) -> bool:
    if not project:
        return False
    key = _artifact_owner_key(
        want.get("kind", ""),
        want.get("id", ""),
        want.get("effective_date", ""),
    )
    current = artifact_owners.get(key) or ""
    if key == ":" or current == project or (current and not replace):
        return False
    artifact_owners[key] = project
    return True


def _seed_artifact_owners(
    artifact_owners: dict[str, str],
    *roots: ET.Element | None,
) -> bool:
    """Learn artifact owners from explicit prefixes/links already in local XML."""
    changed = False
    for root in roots:
        if root is None:
            continue
        for want in hard_references(root) + soft_references(root):
            project = want.get("project") or ""
            if project:
                changed = _remember_artifact_owner(
                    artifact_owners, want, project
                ) or changed
    return changed


def _seed_manifest_artifact_owners(
    artifact_owners: dict[str, str],
    manifest: Mapping[str, Any],
) -> bool:
    changed = False
    resources = manifest.get("resources", {})
    if not isinstance(resources, Mapping):
        return False
    for entry in resources.values():
        if not isinstance(entry, Mapping) or entry.get("status") != "ok":
            continue
        identity = entry.get("identity", {})
        if not isinstance(identity, Mapping):
            continue
        kind = str(identity.get("type") or "")
        ident = str(identity.get("id") or "")
        effective = str(identity.get("effective_date") or "")
        if effective == "dynamic":
            effective = ""
        project = str(identity.get("project") or entry.get("project") or "")
        if kind in KINDS and ident and project:
            changed = _remember_artifact_owner(
                artifact_owners,
                {"kind": kind, "id": ident, "effective_date": effective},
                project,
                replace=True,
            ) or changed
    return changed


def _payload_artifact_owner(payload: bytes, want: Mapping[str, str]) -> str:
    """Read repository context from an API response/reference stub."""
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return ""
    ident = want.get("id") or ""
    reference_names = {
        "id", "ref", "template", "valueSet", "codeSystem", "datasetId",
        "sourceDataset",
    }
    for node in root.iter():
        if ident and not any(node.get(name) == ident for name in reference_names):
            continue
        project = _reference_project(node)
        if project:
            return project
    return ""


def _load_artifact_owners(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = load_json(path)
    # Format 1 used unversioned kind:OID keys. Do not import it: an owner
    # learned for one revision must not influence another historical revision.
    if not isinstance(data, Mapping) or data.get("format") != 2:
        return {}
    owners = data.get("owners", {})
    if not isinstance(owners, Mapping):
        return {}
    return {
        str(key): str(value)
        for key, value in owners.items()
        if key and value
    }


def _write_artifact_owners(path: Path, artifact_owners: Mapping[str, str]) -> None:
    write_json(path, {
        "format": 2,
        "owners": dict(sorted(artifact_owners.items())),
    })


def _candidate_projects(
    want: Mapping[str, str],
    owners: Mapping[str, str],
    repositories: Iterable[str],
    artifact_owners: Mapping[str, str] | None = None,
) -> list[str]:
    """Return project candidates without probing the whole ecosystem blindly.

    OID/project-directory ownership retains the original crawler semantics and
    stops broad repository probing. For otherwise ownerless external artifacts,
    explicit reference context and the version-aware artifact-owner index are
    tried before the configured BBR list.
    """
    owner = _owner(want["id"], owners)
    declared = want.get("project") or ""
    indexed = _indexed_artifact_owner(artifact_owners or {}, want)
    result: list[str] = []

    # Preserve the old crawler's scope rule: an OID/project-directory owner is
    # authoritative. Explicit reference context is retained only as the same
    # historical fallback the crawler already had; neither cached BBR ownership
    # nor broad repository probing may supersede it.
    if owner:
        result.append(owner)
        if declared and declared != owner:
            result.append(declared)
        return result

    # For ownerless/external identifiers, use the strongest local evidence
    # before probing every configured BBR.
    for value in (declared, indexed):
        if value and value not in result:
            result.append(value)
    for value in repositories:
        if value and value not in result:
            result.append(value)
    return result or [""]


def _requests(
    want: Mapping[str, str],
    project: str,
    *,
    main_project: str,
    release: str,
    language: str,
    default_api_base: str,
) -> list[dict[str, str]]:
    resolved = dict(want)
    resolved["project"] = project
    base_url = want.get("api_base") or default_api_base
    return [
        {"project": project, "api_base": base_url, **item}
        for item in artifact_representations(
            resolved,
            project=project,
            main_project=main_project,
            release=release,
            language=language,
            base_url=base_url,
        )
    ]


def _existing_cache_payload(target: Path, old: Mapping[str, Any]) -> bytes | None:
    """Return a usable on-disk cache payload, even if the manifest is stale.

    A valid file is enough to reconstruct a missing/stale manifest entry.  If an
    existing successful manifest entry carries a checksum, however, a checksum
    mismatch is treated as a modified/corrupt cache entry and forces a fresh
    download rather than silently blessing the changed bytes.
    """
    if not target.is_file():
        return None
    try:
        payload = target.read_bytes()
    except OSError:
        return None
    status, _detail = classify_payload(payload)
    if status != "ok":
        return None
    expected = str(old.get("sha256") or "")
    if old.get("status") == "ok" and expected and _digest(payload) != expected:
        return None
    return payload


def _fetch_direct(
    release_dir: Path,
    manifest: dict[str, Any],
    *,
    key: str,
    relative_file: str,
    url: str,
    ipv4: bool,
    retry_missing: bool,
    progress: Progress | None = None,
    label: str | None = None,
    identity: Mapping[str, str] | None = None,
) -> Path | None:
    resources = manifest.setdefault("resources", {})
    old = resources.get(key, {})
    target = release_dir / relative_file
    display = label or key
    existing = _existing_cache_payload(target, old)
    if existing is not None:
        resources[key] = {
            **old,
            "status": "ok",
            "file": relative_file,
            "url": old.get("url") or url,
            "bytes": len(existing),
            "sha256": _digest(existing),
            **({"identity": dict(identity)} if identity else {}),
        }
        repaired = old.get("status") != "ok" or old.get("file") != relative_file
        suffix = " (manifest repaired)" if repaired else ""
        _emit(progress, f"fetch: {display}: cached{suffix}")
        return target
    if old.get("status") == "missing" and not retry_missing:
        _emit(progress, f"fetch: {display}: known missing")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    _emit(progress, f"fetch: {display}: requesting")
    try:
        payload = get(url, ipv4=ipv4)
    except urllib.error.HTTPError as error:
        status_name = "missing" if error.code in FINAL_STATUS else "error"
        resources[key] = {
            "status": status_name,
            "url": url,
            "http_status": error.code,
            **({"identity": dict(identity)} if identity else {}),
        }
        _emit(progress, f"fetch: {display}: {status_name} (HTTP {error.code})")
        return None
    except OSError as error:
        resources[key] = {
            "status": "error", "url": url, "error": str(error),
            **({"identity": dict(identity)} if identity else {}),
        }
        _emit(progress, f"fetch: {display}: error ({error})")
        return None
    status, detail = classify_payload(payload)
    if status == "empty":
        resources[key] = {
            "status": "missing", "url": url, "detail": detail,
            **({"identity": dict(identity)} if identity else {}),
        }
        _emit(progress, f"fetch: {display}: missing ({detail})")
        return None
    target.write_bytes(payload)
    stored_status = "ok" if status == "ok" else "error"
    resources[key] = {
        "status": stored_status,
        "file": relative_file,
        "url": url,
        "bytes": len(payload),
        "sha256": _digest(payload),
        **({"identity": dict(identity)} if identity else {}),
        **({"detail": detail} if detail else {}),
    }
    _emit(progress, f"fetch: {display}: {stored_status} ({_size_text(len(payload))})")
    return target


def _fetch_openapi(
    release_dir: Path,
    manifest: dict[str, Any],
    *,
    api_base: str,
    ipv4: bool,
    retry_missing: bool,
    progress: Progress | None = None,
) -> Path | None:
    """Cache and capability-check the server's OpenAPI description."""
    key = "api-contract"
    relative = "api.json"
    target = release_dir / relative
    old = manifest.setdefault("resources", {}).get(key, {})
    payload: bytes | None = None
    if target.is_file():
        try:
            candidate = target.read_bytes()
            expected = str(old.get("sha256") or "")
            if not expected or _digest(candidate) == expected:
                validate_openapi(candidate)
                payload = candidate
        except (OSError, ValueError, json.JSONDecodeError):
            payload = None
    if payload is None and old.get("status") == "missing" and not retry_missing:
        _emit(progress, "fetch: API contract: known missing")
        return None
    url = openapi_url(api_base)
    if payload is None:
        _emit(progress, "fetch: API contract: requesting")
        try:
            payload = get(url, ipv4=ipv4, accept="application/json")
            metadata = validate_openapi(payload)
        except (urllib.error.HTTPError, OSError, ValueError, json.JSONDecodeError) as error:
            manifest["resources"][key] = {
                "status": "error",
                "url": url,
                "error": str(error),
            }
            _emit(progress, f"fetch: API contract: error ({error})")
            return None
        target.write_bytes(payload)
    else:
        metadata = validate_openapi(payload)
        _emit(progress, "fetch: API contract: cached")
    manifest["resources"][key] = {
        "status": "ok",
        "file": relative,
        "url": url,
        "bytes": len(payload),
        "sha256": _digest(payload),
        **metadata,
    }
    return target


def _fetch_want(
    release_dir: Path,
    manifest: dict[str, Any],
    want: Want,
    *,
    owners: Mapping[str, str],
    repositories: Iterable[str],
    language: str,
    ipv4: bool,
    retry_missing: bool,
    request_budget: dict[str, int] | None = None,
    progress: Progress | None = None,
    save_manifest: Callable[[], None] | None = None,
    main_project: str = "aktin-",
    release: str = "",
    api_base: str = DEFAULT_API_BASE,
    source_hints: Mapping[str, Mapping[str, str]] | None = None,
    artifact_owners: dict[str, str] | None = None,
    save_artifact_owners: Callable[[], None] | None = None,
) -> Path | None:
    requested_want = dict(want)
    resolved_want = apply_source_hint(want, source_hints or {})
    key = _key(resolved_want)
    old = manifest.setdefault("resources", {}).get(key, {})
    relative = str(old.get("file") or _filename(resolved_want))
    target = release_dir / relative
    display = _resource_label(resolved_want)
    existing = _existing_cache_payload(target, old)
    old_representations = (
        old.get("representations", {})
        if isinstance(old.get("representations"), Mapping) else {}
    )

    def cached_representation(form: str) -> tuple[bytes | None, dict[str, Any]]:
        entry = old_representations.get(form, {})
        if not isinstance(entry, Mapping) or not entry.get("file"):
            return None, {}
        path = release_dir / str(entry["file"])
        payload = _existing_cache_payload(path, entry)
        return payload, dict(entry) if payload is not None else {}

    cached_source, cached_source_entry = cached_representation("source")
    if existing is not None and cached_source is not None:
        resolved_date = _resolved_effective_date(existing, resolved_want)
        requested_date = requested_want.get("effective_date") or ""
        # A static dependency must not accidentally adopt another revision that
        # happens to have the expected filename. Dynamic dependencies may adopt
        # whatever revision the valid cached response actually contains.
        expected_date = resolved_want.get("effective_date") or ""
        if not expected_date or not resolved_date or resolved_date == expected_date:
            manifest["resources"][key] = {
                **old,
                "status": "ok",
                "file": relative,
                "bytes": len(existing),
                "sha256": _digest(existing),
                "requested_effective_date": requested_date or "dynamic",
                "resolved_effective_date": resolved_date or old.get("resolved_effective_date", ""),
                "representations": {
                    **dict(old_representations),
                    "analysis": {
                        "status": "ok",
                        "file": relative,
                        "url": old.get("url") or "",
                        "bytes": len(existing),
                        "sha256": _digest(existing),
                    },
                    "source": cached_source_entry,
                },
                "identity": _identity(
                    resolved_want,
                    project=str(old.get("project") or ""),
                    effective_date=resolved_date or str(old.get("resolved_effective_date") or ""),
                    api_base=str(old.get("api_base") or api_base),
                ),
                **({"source_hint": resolved_want["source_hint"]} if resolved_want.get("source_hint") else {}),
            }
            repaired = old.get("status") != "ok" or old.get("file") != relative
            suffix = " (manifest repaired)" if repaired else ""
            _emit(progress, f"fetch: {display}: cached{suffix}")
            if repaired and save_manifest is not None:
                save_manifest()
            return target
    if old.get("status") == "missing" and not retry_missing:
        _emit(progress, f"fetch: {display}: known missing")
        return None

    request_want: Want = dict(resolved_want)
    if not request_want.get("effective_date") and old.get("resolved_effective_date"):
        request_want["effective_date"] = str(old["resolved_effective_date"])

    attempts: list[dict[str, Any]] = []
    saved_representations: dict[str, dict[str, Any]] = {
        **({"source": cached_source_entry} if cached_source is not None else {}),
        **(
            {
                "analysis": {
                    "status": "ok",
                    "file": relative,
                    "url": old.get("url") or "",
                    "bytes": len(existing),
                    "sha256": _digest(existing),
                }
            }
            if existing is not None else {}
        ),
    }

    def request(project: str, form: str, url: str) -> bytes | None:
        if request_budget is not None:
            if request_budget.get("made", 0) >= request_budget.get("max", 0):
                raise RequestBudgetExceeded
            request_budget["made"] = request_budget.get("made", 0) + 1
        count = request_budget.get("made", 0) if request_budget is not None else 0
        maximum = request_budget.get("max", 0) if request_budget is not None else 0
        budget = f" [{count}/{maximum}]" if maximum else ""
        _emit(
            progress,
            f"fetch: {display}: requesting {form} via {project or 'global'}{budget}",
        )
        try:
            payload = get(url, ipv4=ipv4)
        except urllib.error.HTTPError as error:
            attempts.append({
                "project": project,
                "form": form,
                "url": url,
                "http_status": error.code,
            })
            _emit(
                progress,
                f"fetch: {display}: {form} HTTP {error.code} via {project or 'global'}",
            )
            return None
        except OSError as error:
            attempts.append({
                "project": project,
                "form": form,
                "url": url,
                "error": str(error),
            })
            _emit(
                progress,
                f"fetch: {display}: {form} {error} via {project or 'global'}",
            )
            return None
        status, detail = classify_payload(payload)
        if status != "ok":
            attempts.append({
                "project": project,
                "form": form,
                "url": url,
                "error": detail,
            })
            _emit(
                progress,
                f"fetch: {display}: {form} {status} via {project or 'global'}",
            )
            return None
        return payload

    def store(form: str, payload: bytes, url: str) -> Path:
        form_relative = relative if form == "analysis" else _filename(request_want, form)
        path = release_dir / form_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        saved_representations[form] = {
            "status": "ok",
            "file": form_relative,
            "url": url,
            "bytes": len(payload),
            "sha256": _digest(payload),
        }
        return path

    candidates = deque(_candidate_projects(
        request_want, owners, repositories, artifact_owners
    ))
    attempted_candidates: set[str] = set()
    while candidates:
        project = candidates.popleft()
        if project in attempted_candidates:
            continue
        attempted_candidates.add(project)
        forms = _requests(
            request_want,
            project,
            main_project=main_project,
            release=release,
            language=language,
            default_api_base=api_base,
        )
        source_payload: bytes | None = None
        analysis_payload: bytes | None = existing
        analysis_url = str(old.get("url") or "") if existing is not None else ""
        redirected = False
        for item in forms:
            form, url = item["form"], item["url"]
            if form == "source" and cached_source is not None:
                payload = cached_source
                source_payload = cached_source
            elif form == "analysis" and existing is not None:
                payload = existing
                analysis_payload = existing
            else:
                payload = request(project, form, url)
            if payload is None:
                continue
            if form == "source" and artifact_owners is not None:
                linked_project = _payload_artifact_owner(payload, request_want)
                oid_owner = _owner(request_want["id"], owners)
                if not oid_owner and linked_project and linked_project != project:
                    changed = _remember_artifact_owner(
                        artifact_owners, request_want, linked_project,
                        replace=True,
                    )
                    if changed and save_artifact_owners is not None:
                        save_artifact_owners()
                    candidates.appendleft(linked_project)
                    _emit(
                        progress,
                        f"fetch: {display}: source points to {linked_project}; "
                        f"retrying there",
                    )
                    redirected = True
                    break
            if form not in saved_representations:
                store(form, payload, url)
            if form == "source":
                source_payload = payload
                if not request_want.get("effective_date"):
                    discovered = _resolved_effective_date(payload, request_want)
                    if discovered:
                        request_want["effective_date"] = discovered
            elif form == "analysis":
                analysis_payload = payload
                analysis_url = url

        if redirected:
            continue

        # Dataset/concept latest routes only provide a source representation.
        # Resolve the date from it, then request the exact analysis extract.
        if analysis_payload is None and source_payload is not None and request_want.get("effective_date"):
            exact_forms = _requests(
                request_want,
                project,
                main_project=main_project,
                release=release,
                language=language,
                default_api_base=api_base,
            )
            exact_analysis = next(
                (item for item in exact_forms if item["form"] == "analysis"), None
            )
            if exact_analysis is not None:
                analysis_url = exact_analysis["url"]
                analysis_payload = request(project, "analysis", analysis_url)
                if analysis_payload is not None:
                    store("analysis", analysis_payload, analysis_url)

        if analysis_payload is None:
            continue

        resolved_date = _resolved_effective_date(analysis_payload, request_want)
        analysis_path = release_dir / relative
        representation = saved_representations.get("analysis", {})

        # Expansion sets are additional frozen evidence for intensional value
        # sets; failure does not invalidate the extracted definition.
        expansion_error = ""
        if request_want["kind"] == "valueset" and resolved_date:
            try:
                root, _ = parse_text(analysis_payload.decode("utf-8", "replace"))
                intensional = any(
                    local(node.tag) == "include" for node in root.iter()
                )
            except (ET.ParseError, ValueError):
                intensional = False
            if intensional:
                expansion_url = valueset_expansion_url(
                    request_want["id"], resolved_date,
                    project=project, language=language,
                    base_url=request_want.get("api_base") or api_base,
                )
                budget_full = (
                    request_budget is not None
                    and request_budget.get("made", 0) >= request_budget.get("max", 0)
                )
                expansion_payload = (
                    None if budget_full
                    else request(project, "expansion", expansion_url)
                )
                if expansion_payload is not None:
                    store("expansion", expansion_payload, expansion_url)
                else:
                    expansion_error = (
                        "value-set expansion deferred by request budget"
                        if budget_full else "value-set expansion unavailable"
                    )

        manifest["resources"][key] = {
            "status": "ok",
            "file": relative,
            "url": analysis_url,
            "project": project,
            "api_base": request_want.get("api_base") or api_base,
            "bytes": representation.get("bytes", len(analysis_payload)),
            "sha256": representation.get("sha256", _digest(analysis_payload)),
            "requested_effective_date": requested_want.get("effective_date") or "dynamic",
            "resolved_effective_date": resolved_date,
            "identity": _identity(
                request_want, project=project, effective_date=resolved_date,
                api_base=request_want.get("api_base") or api_base,
            ),
            "representations": saved_representations,
            **({"source_hint": request_want["source_hint"]} if request_want.get("source_hint") else {}),
            **({"publication_url": request_want["publication_url"]} if request_want.get("publication_url") else {}),
            **(
                {"source_warning": "source representation unavailable"}
                if "source" not in saved_representations else {}
            ),
            **({"expansion_warning": expansion_error} if expansion_error else {}),
        }
        if artifact_owners is not None:
            changed = _remember_artifact_owner(
                artifact_owners, request_want, project, replace=True
            )
            if resolved_date:
                exact_want = dict(request_want)
                exact_want["effective_date"] = resolved_date
                changed = _remember_artifact_owner(
                    artifact_owners, exact_want, project, replace=True
                ) or changed
            if changed and save_artifact_owners is not None:
                save_artifact_owners()
        resolved_note = (
            f", resolved {resolved_date}"
            if not requested_want.get("effective_date") and resolved_date
            else ""
        )
        _emit(
            progress,
            f"fetch: {display}: ok via {project or 'global'} "
            f"({_size_text(len(analysis_payload))}{resolved_note})",
        )
        if save_manifest is not None:
            save_manifest()
        return analysis_path

    relevant_attempts = [item for item in attempts if item.get("form") == "analysis"]
    if not relevant_attempts:
        relevant_attempts = attempts
    settled = bool(relevant_attempts) and all(
        item.get("http_status") in FINAL_STATUS
        or str(item.get("error") or "").startswith("<")
        for item in relevant_attempts
    )
    final_status = "missing" if settled else "error"
    owner = _owner(resolved_want["id"], owners)
    attempted_projects = list(dict.fromkeys(
        str(item.get("project") or "") for item in attempts
    ))
    manifest["resources"][key] = {
        "status": final_status,
        "settled": settled,
        "owner": owner,
        "declared_project": resolved_want.get("project") or "",
        "attempted_projects": attempted_projects,
        "attempts": attempts,
        "representations": saved_representations,
        "identity": _identity(
            resolved_want,
            project=attempted_projects[-1] if attempted_projects else "",
            api_base=resolved_want.get("api_base") or api_base,
        ),
        **({"source_hint": resolved_want["source_hint"]} if resolved_want.get("source_hint") else {}),
    }
    if save_manifest is not None:
        save_manifest()
    _emit(progress, f"fetch: {display}: {final_status} after {len(attempts)} attempt(s)")
    return None


def verify_manifest(release_dir: Path) -> list[str]:
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"missing {manifest_path}"]
    manifest = load_json(manifest_path)
    errors: list[str] = []
    checked: set[tuple[str, str]] = set()

    def verify_entry(label: str, entry: Mapping[str, Any]) -> None:
        relative = str(entry.get("file") or "")
        if entry.get("status") != "ok" or not relative:
            return
        marker = (relative, str(entry.get("sha256") or ""))
        if marker in checked:
            return
        checked.add(marker)
        path = release_dir / relative
        if not path.exists():
            errors.append(f"{label}: missing downloaded file {relative}")
        elif entry.get("sha256") and _digest(path.read_bytes()) != entry["sha256"]:
            errors.append(f"{label}: checksum mismatch for {relative}")

    for key, entry in manifest.get("resources", {}).items():
        if not isinstance(entry, Mapping):
            continue
        verify_entry(key, entry)
        representations = entry.get("representations", {})
        if isinstance(representations, Mapping):
            for form, representation in representations.items():
                if isinstance(representation, Mapping):
                    verify_entry(f"{key}[{form}]", representation)
    return errors


def closure_paths(release_dir: Path, transaction_dir: Path, role: str = "build") -> list[Path]:
    """Resolve resource paths recorded for a completed transaction closure."""
    closure = load_json(transaction_dir / "closure.json")
    if closure.get("complete") is False or closure.get("interrupted") or closure.get("truncated"):
        raise ValueError("transaction closure is incomplete; rerun `decor2hl7 fetch`")
    manifest = load_json(release_dir / "manifest.json")
    keys = closure.get(f"{role}_resources", [])
    result: list[Path] = []
    for key in keys:
        entry = manifest.get("resources", {}).get(key, {})
        if entry.get("status") == "ok" and entry.get("file"):
            path = release_dir / str(entry["file"])
            if path.exists():
                result.append(path)
    return result


def fetch_spec(
    release_dir: Path,
    transaction_dir: Path,
    *,
    prefix: str,
    release: Mapping[str, str],
    transaction: Mapping[str, str],
    language: str = "de-DE",
    ipv4: bool = True,
    retry_missing: bool = False,
    max_requests: int = 1500,
    progress: Progress | None = None,
    api_base: str = DEFAULT_API_BASE,
    source_hints: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Fetch the selected transaction and recursively close its dependencies.

    ``closure.json`` is a checkpoint, not merely an end-of-run report.  It is
    written after the root resources, after each crawler batch, when the
    request budget is exhausted, and when the user interrupts the command.
    An incomplete closure is deliberately not accepted by ``build``.
    """
    release_dir.mkdir(parents=True, exist_ok=True)
    transaction_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / "manifest.json"
    artifact_owners_path = release_dir / "artifact-owners.json"
    closure_path = transaction_dir / "closure.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {
        "format": 2,
        "release": dict(release),
        "project": prefix,
        "api_base": api_base,
        "resources": {},
    }
    manifest["format"] = 2
    manifest["release"] = dict(release)
    manifest["project"] = prefix
    manifest["api_base"] = api_base
    artifact_owners = _load_artifact_owners(artifact_owners_path)
    _seed_manifest_artifact_owners(artifact_owners, manifest)

    release_date = release.get("date") or ""
    tx_id = transaction.get("id") or ""
    tx_effective = transaction.get("effective_date") or ""

    roles: dict[str, set[str]] = {"build": set(), "evidence": set()}
    visited: dict[str, set[str]] = {"build": set(), "evidence": set()}
    build_queue: deque[Want] = deque()
    evidence_queue: deque[Want] = deque()
    pending_batch: dict[str, list[Want]] = {"build": [], "evidence": []}
    request_budget = {"made": 0, "max": max(0, int(max_requests))}
    resources_considered = 0
    budget_exhausted = False
    phase = "roots"
    root_errors: list[str] = []
    root_status = {
        "api_contract": "pending",
        "project_config": "pending",
        "transaction": "pending",
        "transaction_source": "pending",
        "project_evidence": "pending",
        "project_directory": "pending",
    }

    project_config: Path | None = None
    evidence: Path | None = None
    project_directory: Path | None = None
    tx_source: Path | None = None
    tx_path: Path | None = None

    def pending_keys(role: str) -> list[str]:
        wants = list(pending_batch[role]) + list(
            build_queue if role == "build" else evidence_queue
        )
        seen: set[str] = set()
        keys: list[str] = []
        for want in wants:
            key = _key(want)
            if key not in seen and key not in visited[role]:
                seen.add(key)
                keys.append(key)
        return sorted(keys)

    def checkpoint(*, complete: bool, interrupted: bool = False) -> dict[str, Any]:
        current_keys = roles["build"] | roles["evidence"]
        current_errors = sorted(
            key for key in current_keys
            if manifest.get("resources", {}).get(key, {}).get("status") == "error"
        )
        current_missing = sorted(
            key for key in current_keys
            if manifest.get("resources", {}).get(key, {}).get("status") == "missing"
        )
        build_pending = pending_keys("build")
        evidence_pending = pending_keys("evidence")
        closure = {
            "format": 2,
            "release": dict(release),
            "transaction": dict(transaction),
            "complete": complete,
            "interrupted": interrupted,
            "phase": phase,
            "build_resources": sorted(roles["build"]),
            "evidence_resources": sorted(roles["evidence"] | roles["build"]),
            "pending": {
                "build": build_pending,
                "evidence": evidence_pending,
            },
            "missing": current_missing,
            "errors": current_errors + root_errors,
            "root_status": dict(root_status),
            "summary": {
                "ok": sum(
                    manifest.get("resources", {}).get(key, {}).get("status") == "ok"
                    for key in current_keys
                ) + int(root_status["project_config"] == "ok") + int(root_status["transaction"] == "ok"),
                "missing": len(current_missing),
                "error": len(current_errors) + len(root_errors),
            },
            "resources_considered": resources_considered,
            "recursive_http_requests": request_budget["made"],
            # Backwards-compatible meaning: the request budget stopped the
            # crawler.  A user interruption is recorded separately.
            "truncated": budget_exhausted,
        }
        manifest["summary"] = {
            "resources": len(manifest.get("resources", {})),
            "ok": sum(1 for row in manifest.get("resources", {}).values() if row.get("status") == "ok"),
            "missing": sum(1 for row in manifest.get("resources", {}).values() if row.get("status") == "missing"),
            "error": sum(1 for row in manifest.get("resources", {}).values() if row.get("status") == "error"),
        }
        write_json(manifest_path, manifest)
        write_json(closure_path, closure)
        return closure

    try:
        contract = _fetch_openapi(
            release_dir, manifest, api_base=api_base, ipv4=ipv4,
            retry_missing=retry_missing, progress=progress,
        )
        root_status["api_contract"] = "ok" if contract is not None else "error"

        project_config = _fetch_direct(
            release_dir, manifest, key=f"project-config:{prefix}",
            relative_file="project.xml",
            url=project_url(prefix, base_url=api_base), ipv4=ipv4,
            retry_missing=retry_missing, progress=progress,
            label=f"project configuration {prefix}",
            identity={
                "type": "project", "id": prefix, "effective_date": "live",
                "project": prefix, "api_base": api_base,
            },
        )
        root_status["project_config"] = "ok" if project_config is not None else "missing"

        evidence = _fetch_direct(
            release_dir, manifest, key=f"project-evidence:{prefix}",
            relative_file="project-evidence.xml",
            url=project_extract_url(
                prefix, language=language, mode="verbatim", base_url=api_base
            ),
            ipv4=ipv4,
            retry_missing=retry_missing, progress=progress,
            label=f"live evidence project {prefix}",
            identity={
                "type": "project-evidence", "id": prefix,
                "effective_date": "live", "project": prefix,
                "api_base": api_base,
            },
        )
        root_status["project_evidence"] = "ok" if evidence is not None else "missing"

        project_directory = _fetch_direct(
            release_dir, manifest, key="project-directory",
            relative_file="project-directory.xml",
            url=projects_url(base_url=api_base), ipv4=ipv4,
            retry_missing=retry_missing, progress=progress,
            label="global project directory",
            identity={
                "type": "project-directory", "id": "project",
                "effective_date": "live", "project": "", "api_base": api_base,
            },
        )
        root_status["project_directory"] = "ok" if project_directory is not None else "missing"

        tx_forms = transaction_representations(
            tx_id, tx_effective, project=prefix, release=release_date,
            language=language, base_url=api_base,
        )
        source_url = next(item["url"] for item in tx_forms if item["form"] == "source")
        analysis_url = next(item["url"] for item in tx_forms if item["form"] == "analysis")
        tx_source = _fetch_direct(
            release_dir, manifest,
            key=f"transaction-source:{tx_id}@{tx_effective}",
            relative_file=str(
                (transaction_dir / "transaction.source.xml").relative_to(release_dir)
            ),
            url=source_url, ipv4=ipv4, retry_missing=retry_missing,
            progress=progress,
            label=f"transaction source {transaction.get('key') or tx_id or '?'}",
            identity={
                "type": "transaction", "id": tx_id,
                "effective_date": tx_effective, "project": prefix,
                "api_base": api_base, "form": "source",
            },
        )
        root_status["transaction_source"] = "ok" if tx_source is not None else "missing"

        tx_path = _fetch_direct(
            release_dir, manifest,
            key=f"transaction:{tx_id}@{tx_effective}",
            relative_file=str((transaction_dir / "transaction.xml").relative_to(release_dir)),
            url=analysis_url, ipv4=ipv4, retry_missing=retry_missing, progress=progress,
            label=f"transaction {transaction.get('key') or tx_id or '?'}",
            identity={
                "type": "transaction", "id": tx_id,
                "effective_date": tx_effective, "project": prefix,
                "api_base": api_base, "form": "analysis",
            },
        )
        root_status["transaction"] = "ok" if tx_path is not None else "missing"

        if contract is None:
            root_errors.append("current API contract could not be validated")
        if tx_path is None:
            root_errors.append("selected transaction could not be fetched")

        build_roots = [_parse(tx_path)] if tx_path else []
        evidence_roots = [_parse(evidence)] if evidence else []
        owners = _project_directory(
            _parse(project_directory) if project_directory else None
        )
        repositories = _repositories(
            _parse(project_config) if project_config else None,
            *(build_roots + evidence_roots),
            own=prefix,
        )
        if _seed_artifact_owners(
            artifact_owners,
            _parse(project_config) if project_config else None,
            *(build_roots + evidence_roots),
        ) or artifact_owners:
            _write_artifact_owners(artifact_owners_path, artifact_owners)

        tx_root = _parse(tx_path) if tx_path else None
        if tx_root is not None:
            build_queue.extend(hard_references(tx_root))
            evidence_queue.extend(soft_references(tx_root))

        # Only count embedded resources as "already available" when the later
        # compiler actually receives the container that holds them.
        build_have: set[tuple[str, str, str]] = set()
        if tx_root is not None:
            build_have.update(_inventory(tx_root))
        evidence_have = set(build_have)
        for root in evidence_roots:
            evidence_have.update(_inventory(root))
        have_by_role = {"build": build_have, "evidence": evidence_have}

        phase = "build"
        checkpoint(complete=False)

        def save_manifest() -> None:
            write_json(manifest_path, manifest)

        def save_artifact_owners() -> None:
            _write_artifact_owners(artifact_owners_path, artifact_owners)

        def crawl_build(queue: deque[Want], embedded_roots: list[ET.Element | None]) -> None:
            nonlocal resources_considered, budget_exhausted, phase
            phase = "build"
            _emit(progress, f"fetch: resolving build dependency closure ({len(queue)} initial reference(s))")
            while queue and not budget_exhausted:
                rows = [
                    Want(**apply_source_hint(item, source_hints or {}))
                    for item in queue
                ]
                queue.clear()
                rows.sort(key=lambda item: (
                    KIND_ORDER.get(item["kind"], 9),
                    item.get("project", ""),
                    item["id"],
                ))
                pending_batch["build"] = list(rows)
                for row_index, want in enumerate(rows):
                    pending_batch["build"] = rows[row_index:]
                    key = _key(want)
                    if key in visited["build"]:
                        continue
                    embedded = _matching_embedded(embedded_roots, want)
                    if _satisfied(want, have_by_role["build"]):
                        visited["build"].add(key)
                        for node in embedded:
                            queue.extend(hard_references(node))
                            evidence_queue.extend(soft_references(node))
                        continue

                    if want.get("kind") == "template" and evidence_roots:
                        evidence_template = _matching_embedded(
                            evidence_roots, want, not_after=release_date
                        )
                        if evidence_template:
                            visited["build"].add(key)
                            resolved = evidence_template[-1].get("effectiveDate") or ""
                            suffix = f" @ {resolved}" if resolved else ""
                            _emit(
                                progress,
                                f"fetch: {_resource_label(want)}: available in main project evidence{suffix}",
                            )
                            for node in evidence_template:
                                queue.extend(hard_references(node))
                                evidence_queue.extend(soft_references(node))
                            continue

                    resources_considered += 1
                    try:
                        path = _fetch_want(
                            release_dir, manifest, want, owners=owners,
                            repositories=repositories, language=language,
                            ipv4=ipv4, retry_missing=retry_missing,
                            request_budget=request_budget, progress=progress,
                            save_manifest=save_manifest,
                            main_project=prefix, release=release_date,
                            api_base=api_base, source_hints=source_hints,
                            artifact_owners=artifact_owners,
                            save_artifact_owners=save_artifact_owners,
                        )
                    except RequestBudgetExceeded:
                        for pending in reversed(rows[row_index:]):
                            queue.appendleft(pending)
                        pending_batch["build"] = []
                        budget_exhausted = True
                        checkpoint(complete=False)
                        return
                    visited["build"].add(key)
                    roles["build"].add(key)
                    if path is None:
                        continue
                    root = _parse(path)
                    if root is not None:
                        if _seed_artifact_owners(artifact_owners, root):
                            save_artifact_owners()
                        inventory = _inventory(root)
                        have_by_role["build"].update(inventory)
                        have_by_role["evidence"].update(inventory)
                        queue.extend(hard_references(root))
                        evidence_queue.extend(soft_references(root))
                pending_batch["build"] = []
                checkpoint(complete=False)

        def resolve_evidence(queue: deque[Want], embedded_roots: list[ET.Element | None]) -> None:
            """Resolve soft dependencies directly and deliberately stop there."""
            nonlocal resources_considered, budget_exhausted, phase
            phase = "evidence"
            rows = [
                Want(**apply_source_hint(item, source_hints or {}))
                for item in queue
            ]
            queue.clear()
            rows.sort(key=lambda item: (
                KIND_ORDER.get(item["kind"], 9),
                item.get("project", ""),
                item["id"],
            ))
            _emit(progress, f"fetch: resolving direct evidence ({len(rows)} reference(s), non-recursive)")
            pending_batch["evidence"] = list(rows)
            for row_index, want in enumerate(rows):
                pending_batch["evidence"] = rows[row_index:]
                key = _key(want)
                if key in visited["evidence"] or key in visited["build"]:
                    continue
                if _satisfied(want, have_by_role["evidence"]):
                    visited["evidence"].add(key)
                    continue
                # The complete main-project evidence snapshot is already local;
                # use an exact/direct embedded resource before making a request.
                if _matching_embedded(embedded_roots, want):
                    visited["evidence"].add(key)
                    continue

                resources_considered += 1
                try:
                    path = _fetch_want(
                        release_dir, manifest, want, owners=owners,
                        repositories=repositories, language=language,
                        ipv4=ipv4, retry_missing=retry_missing,
                        request_budget=request_budget, progress=progress,
                        save_manifest=save_manifest,
                        main_project=prefix, release=release_date,
                        api_base=api_base, source_hints=source_hints,
                        artifact_owners=artifact_owners,
                        save_artifact_owners=save_artifact_owners,
                    )
                except RequestBudgetExceeded:
                    for pending in reversed(rows[row_index:]):
                        queue.appendleft(pending)
                    pending_batch["evidence"] = []
                    budget_exhausted = True
                    checkpoint(complete=False)
                    return
                visited["evidence"].add(key)
                roles["evidence"].add(key)
                if path is not None:
                    root = _parse(path)
                    if root is not None:
                        if _seed_artifact_owners(artifact_owners, root):
                            save_artifact_owners()
                        have_by_role["evidence"].update(_inventory(root))
                # Crucially: no references(root) here. Soft evidence stops at the
                # directly resolved resource and cannot turn into another crawl.
            pending_batch["evidence"] = []
            checkpoint(complete=False)

        crawl_build(build_queue, build_roots)

        relevant_ids: set[str] = set()
        if tx_root is not None:
            relevant_ids.update(ident for _, ident, _ in _inventory(tx_root))
        for key in visited["build"] | roles["build"]:
            try:
                relevant_ids.add(key.split(":", 1)[1].split("@", 1)[0])
            except IndexError:
                pass
        for root in evidence_roots:
            if root is not None:
                evidence_queue.extend(_evidence_references(root, relevant_ids))
        resolve_evidence(evidence_queue, build_roots + evidence_roots)

        phase = "complete"
        complete = not budget_exhausted and not build_queue and not evidence_queue
        closure = checkpoint(complete=complete)
        _emit(
            progress,
            "fetch: complete: "
            f"{closure['summary']['ok']} ok/cached, "
            f"{closure['summary']['missing']} missing, "
            f"{closure['summary']['error']} error(s), "
            f"{closure['recursive_http_requests']} recursive HTTP request(s)",
        )
        return {"manifest": manifest, "closure": closure}
    except KeyboardInterrupt:
        phase = f"{phase}-interrupted"
        checkpoint(complete=False, interrupted=True)
        _emit(progress, "fetch: interrupted by user; checkpoint saved")
        raise
