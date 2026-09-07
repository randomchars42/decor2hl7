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
from typing import Any, Callable, Iterable, Mapping, cast

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
from .artifacts import REQUIRED_ROLES
from .sources import (
    SATISFYING_COMPLETENESS, apply_source_hint, builtin_payload, resolve_alias,
)
from .expansion import expansion_status
from .xml import local, parse_text
from .references import (
    KIND_ORDER, KINDS, Want, display_references, hard_references,
    identity_references, references, soft_references,
)
from .resolution import (
    candidate_projects as _candidate_projects,
    load_artifact_owners as _load_artifact_owners,
    payload_artifact_owner as _payload_artifact_owner,
    project_owner as _owner,
    remember_artifact_owner as _remember_artifact_owner,
    write_artifact_owners as _write_artifact_owners,
)
from ..workspace import load_json, write_json
from ..cda.core import CORE_FILES, CORE_RAW_BASE, CORE_REVISION
from ..cda.extensions import normalize_extensions
from ..conformance import (
    VALIDATION_ARCHIVES, extract_validation_packages, package_archive_path,
    validation_package_problems,
)


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
    want: Mapping[str, object],
    *,
    project: str = "",
    effective_date: str = "",
    api_base: str = "",
) -> dict[str, str]:
    """Return the complete retrieval identity recorded with cached artifacts."""
    return {
        "type": str(want.get("kind") or ""),
        "id": str(want.get("id") or ""),
        "effective_date": effective_date
        or str(want.get("effective_date") or "dynamic"),
        "project": project or str(want.get("project") or ""),
        "api_base": api_base
        or str(want.get("api_base") or DEFAULT_API_BASE),
        **({"context_id": str(want["dataset"])} if want.get("dataset") else {}),
        **(
            {"context_effective_date": str(want["dataset_effective_date"])}
            if want.get("dataset_effective_date") else {}
        ),
    }


def _key(want: Mapping[str, object]) -> str:
    effective = str(want.get("effective_date") or "")
    suffix = f"@{effective}" if effective else ""
    key = f"{want['kind']}:{want['id']}{suffix}"
    dataset = str(want.get("dataset") or "")
    if dataset:
        dataset_date = str(want.get("dataset_effective_date") or "")
        key += f"|context={dataset}{('@' + dataset_date) if dataset_date else ''}"
    return key


def _filename(want: Mapping[str, object], form: str = "analysis") -> str:
    stamp = _safe(str(want.get("effective_date") or ""))
    name = _safe(str(want["id"]))
    if stamp:
        name += f"_{stamp}"
    directory = {
        "dataset": "datasets",
        "template": "templates",
        "valueset": "valuesets",
        "codesystem": "codesystems",
        "concept": "concepts",
    }[str(want["kind"])]
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


def _valueset_complete(
    node: ET.Element, document: ET.Element | None = None,
) -> bool:
    resources = document if document is not None else node
    members = any(
        local(child.tag) in {"concept", "exception"}
        and child.get("code")
        and child.get("codeSystem")
        for child in node.iter()
    )
    if not members:
        return False
    local_value_sets = {
        child.get("id") for child in resources.iter()
        if local(child.tag) == "valueSet" and child.get("id")
    }
    local_code_systems = {
        child.get("id") for child in resources.iter()
        if local(child.tag) == "codeSystem" and child.get("id")
    }
    for child in node.iter():
        if local(child.tag) != "include":
            continue
        if child.get("ref") and child.get("ref") not in local_value_sets:
            return False
        if (
            child.get("codeSystem")
            and child.get("codeSystem") not in local_code_systems
        ):
            return False
    return True


def _valueset_needs_expansion(payload: bytes) -> bool:
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return False
    value_sets = [
        node for node in root.iter() if local(node.tag) == "valueSet"
    ]
    if not value_sets and local(root.tag) == "valueSet":
        value_sets = [root]
    return (
        any(local(node.tag) == "include" for node in root.iter())
        or not value_sets
        or any(not _valueset_complete(node, root) for node in value_sets)
    )


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
        if kind == "valueset" and not _valueset_complete(node, root):
            continue
        result.add((kind, ident, node.get("effectiveDate") or ""))
    return result


def _satisfied(
    want: Mapping[str, object], have: set[tuple[str, str, str]],
) -> bool:
    kind = str(want["kind"])
    ident = str(want["id"])
    effective = str(want.get("effective_date") or "")
    if effective:
        return (kind, ident, effective) in have
    return any(k == kind and i == ident for k, i, _ in have)

def _matching_embedded(
    roots: Iterable[ET.Element | None],
    want: Mapping[str, object],
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
    wanted_tag = tag_for.get(str(want.get("kind") or ""))
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


ARTIFACT_TAG_FOR_KIND = {
    "dataset": "dataset",
    "concept": "concept",
    "template": "template",
    "valueset": "valueSet",
    "codesystem": "codeSystem",
}


def _artifact_identity_nodes(
    root: ET.Element, want: Mapping[str, object]
) -> list[ET.Element]:
    """Return the nodes in a payload that declare the requested identity.

    A defining artifact carries its identity on `id`.  A code system that a
    project references rather than defines — an external terminology such as
    SNOMED CT or LOINC, but also a locally referenced table — is published as a
    reference declaration that carries the same identity on `ref` instead, in
    both the source and the analysis form.  Such a node identifies the artifact
    even though it enumerates no concepts, so a cached reference declaration is
    a genuine cache hit for its own identity.
    """
    wanted_tag = ARTIFACT_TAG_FOR_KIND.get(str(want.get("kind") or ""))
    wanted_id = str(want.get("id") or "")
    if not wanted_tag or not wanted_id:
        return []
    return [
        node for node in root.iter()
        if local(node.tag) == wanted_tag
        and wanted_id in {node.get("id"), node.get("ref")}
    ]


def _resolved_effective_date(payload: bytes, want: Mapping[str, object]) -> str:
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return ""
    rows = [
        node.get("effectiveDate") or ""
        for node in _artifact_identity_nodes(root, want)
        if node.get("effectiveDate")
    ]
    if not rows and root.get("effectiveDate"):
        rows.append(root.get("effectiveDate") or "")
    return max(rows) if rows else ""


def _payload_matches_request(payload: bytes, want: Mapping[str, str]) -> bool:
    """Return whether cached XML contains the exact requested artifact.

    Deterministic filenames make an orphan cache discoverable after the
    manifest is deleted, but the filename alone is not evidence that the
    contents have the requested kind, identifier and (for static requests)
    revision.  A reference declaration proves kind and identifier; it can only
    satisfy a static request when it also carries the requested revision.
    """
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return False
    wanted_date = want.get("effective_date") or ""
    return any(
        not wanted_date or node.get("effectiveDate") == wanted_date
        for node in _artifact_identity_nodes(root, want)
    )


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


def _seed_artifact_owners(
    artifact_owners: dict[str, str],
    *roots: ET.Element | None,
) -> bool:
    """Learn artifact owners from explicit prefixes/links already in local XML."""
    changed = False
    for root in roots:
        if root is None:
            continue
        for want in (
            hard_references(root) + soft_references(root) + display_references(root)
        ):
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


def _requests(
    want: Mapping[str, object],
    project: str,
    *,
    main_project: str,
    release: str,
    language: str,
    default_api_base: str,
) -> list[dict[str, str]]:
    resolved = {
        str(key): str(value)
        for key, value in want.items()
        if value not in (None, "")
    }
    resolved["project"] = project
    base_url = str(want.get("api_base") or default_api_base)
    rows = [
        {
            "project": project,
            "api_base": base_url,
            "form": item["form"],
            "url": item["url"],
        }
        for item in artifact_representations(
            resolved,
            project=project,
            main_project=main_project,
            release=release,
            language=language,
            base_url=base_url,
        )
    ]
    if want.get("analysis_only"):
        rows = [row for row in rows if row["form"] == "analysis"]
    return rows


def _existing_cache_payload(
    target: Path,
    old: Mapping[str, Any],
    *,
    classify_xml: bool = True,
) -> bytes | None:
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
    if classify_xml:
        status, _detail = classify_payload(payload)
        if status != "ok":
            return None
    expected = str(old.get("sha256") or "")
    if old.get("status") == "ok" and expected and _digest(payload) != expected:
        return None
    return payload


def _external_manifest_fields(want: Mapping[str, str]) -> dict[str, str]:
    source_url = want.get("source_url") or want.get("publication_url") or ""
    return {
        "origin": "bundled-supplement" if want.get("mode") == "builtin" else "waiver",
        "completeness": want.get("completeness") or (
            "spec-only" if want.get("mode") == "waiver" else ""
        ),
        "source_url": source_url,
        "source_version": want.get("source_version") or "",
        "license": want.get("license") or "",
        **({"source_hint": want["source_hint"]} if want.get("source_hint") else {}),
        **(
            {"source_hint_origin": want["source_hint_origin"]}
            if want.get("source_hint_origin") else {}
        ),
    }


def _source_hint_fields(want: Mapping[str, object]) -> dict[str, str]:
    return {
        **(
            {"source_hint": str(want["source_hint"])}
            if want.get("source_hint") else {}
        ),
        **(
            {"source_hint_origin": str(want["source_hint_origin"])}
            if want.get("source_hint_origin") else {}
        ),
    }


def _materialize_external(
    release_dir: Path,
    manifest: dict[str, Any],
    want: Mapping[str, str],
    *,
    key: str,
    relative: str,
    progress: Progress | None = None,
    save_manifest: Callable[[], None] | None = None,
) -> tuple[bool, Path | None]:
    """Apply one explicitly catalogued phase-1 fallback.

    Builtins are reviewed package resources and therefore work in offline
    mode. Waivers are deliberately not successful artifacts: they settle a
    known absence, retain its evidence and keep the build visibly degraded.
    """
    mode = want.get("mode") or ""
    if mode not in {"builtin", "waiver"}:
        return False, None
    resources = manifest.setdefault("resources", {})
    display = _resource_label(want)
    requested_date = want.get("effective_date") or ""
    identity = {
        "type": want.get("kind") or "",
        "id": want.get("id") or "",
        "effective_date": requested_date or "dynamic",
        "project": "",
        "api_base": "",
        "origin": "external",
    }
    metadata = _external_manifest_fields(want)
    if mode == "waiver":
        # A waiver settles an absence that a previous crawl may already have
        # traced.  Retain that evidence so the reason stays checkable against
        # the attempts that produced it (architecture rule 18).
        previous = resources.get(key, {})
        trace = {
            name: list(previous[name])
            for name in ("projects_considered", "resolution_attempts")
            if isinstance(previous, Mapping) and isinstance(previous.get(name), list)
        }
        resources[key] = {
            "status": "waived",
            "settled": True,
            "reason": want.get("reason") or "",
            "requested_effective_date": requested_date or "dynamic",
            "resolved_effective_date": "",
            "identity": identity,
            **trace,
            **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: waived by reviewed source catalog entry")
        return True, None

    target = release_dir / relative
    try:
        payload = builtin_payload(want)
    except (OSError, ValueError) as error:
        resources[key] = {
            "status": "error",
            "settled": True,
            "reason": str(error),
            "identity": identity,
            **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: builtin error ({error})")
        return True, None
    digest = _digest(payload)
    expected = want.get("sha256") or ""
    if expected and digest != expected:
        resources[key] = {
            "status": "error",
            "settled": True,
            "reason": f"builtin checksum mismatch: expected {expected}, found {digest}",
            "identity": identity,
            **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: builtin checksum mismatch")
        return True, None
    payload_status, detail = classify_payload(payload)
    if payload_status != "ok":
        resources[key] = {
            "status": "error",
            "settled": True,
            "reason": f"builtin payload is {payload_status}: {detail}",
            "identity": identity,
            **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: invalid builtin ({detail})")
        return True, None
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError) as error:
        resources[key] = {
            "status": "error", "settled": True, "reason": str(error),
            "identity": identity, **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        return True, None
    tag_for_kind = {
        "dataset": "dataset", "concept": "concept", "template": "template",
        "valueset": "valueSet", "codesystem": "codeSystem",
    }
    expected_tag = tag_for_kind.get(want.get("kind") or "")
    matching = next((
        node for node in root.iter()
        if local(node.tag) == expected_tag and node.get("id") == want.get("id")
    ), None)
    if matching is None:
        resources[key] = {
            "status": "error",
            "settled": True,
            "reason": "builtin payload does not contain the requested artifact identity",
            "identity": identity,
            **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: builtin identity mismatch")
        return True, None
    resolved_date = matching.get("effectiveDate") or ""
    if requested_date and resolved_date != requested_date:
        resources[key] = {
            "status": "error",
            "settled": True,
            "reason": (
                f"builtin revision mismatch: requested {requested_date}, "
                f"found {resolved_date or 'no effective date'}"
            ),
            "identity": identity,
            **metadata,
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: builtin revision mismatch")
        return True, None
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_bytes() if target.is_file() else None
    if previous != payload:
        target.write_bytes(payload)
    completeness = want.get("completeness") or "fragment"
    # Only a complete reviewed supplement satisfies a required dependency
    # (`DEC-012`); anything else stays an unavailable compiler input.
    status = "ok" if completeness == SATISFYING_COMPLETENESS else "partial"
    representation = {
        "status": status,
        "file": relative,
        "url": metadata.get("source_url", ""),
        "bytes": len(payload),
        "sha256": digest,
        "origin": "bundled-supplement",
        "completeness": completeness,
    }
    resources[key] = {
        "status": status,
        "settled": True,
        "file": relative,
        "url": metadata.get("source_url", ""),
        "bytes": len(payload),
        "sha256": digest,
        "requested_effective_date": requested_date or "dynamic",
        "resolved_effective_date": resolved_date,
        "identity": {**identity, "effective_date": resolved_date or requested_date or "dynamic"},
        "representations": {"analysis": representation},
        "source_warning": "upstream publication is cited but not cached",
        **metadata,
    }
    if save_manifest is not None:
        save_manifest()
    action = "cached" if previous == payload else "materialized"
    _emit(progress, f"fetch: {display}: builtin {action} ({completeness})")
    return True, target if status == "ok" else None


def _fetch_direct(
    release_dir: Path,
    manifest: dict[str, Any],
    *,
    key: str,
    relative_file: str,
    url: str,
    ipv4: bool,
    retry_missing: bool,
    offline: bool = False,
    progress: Progress | None = None,
    label: str | None = None,
    identity: Mapping[str, str] | None = None,
    expected_sha256: str | None = None,
    binary: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> Path | None:
    resources = manifest.setdefault("resources", {})
    old = resources.get(key, {})
    target = release_dir / relative_file
    display = label or key
    existing = _existing_cache_payload(target, old, classify_xml=not binary)
    if existing is not None and expected_sha256 and _digest(existing) != expected_sha256:
        existing = None
    if existing is not None:
        resources[key] = {
            **old,
            "status": "ok",
            "file": relative_file,
            "url": old.get("url") or url,
            "bytes": len(existing),
            "sha256": _digest(existing),
            **({"expected_sha256": expected_sha256} if expected_sha256 else {}),
            **({"identity": dict(identity)} if identity else {}),
            **dict(metadata or {}),
        }
        repaired = old.get("status") != "ok" or old.get("file") != relative_file
        suffix = " (manifest repaired)" if repaired else ""
        _emit(progress, f"fetch: {display}: cached{suffix}")
        return target
    if old.get("status") == "missing" and not retry_missing:
        _emit(progress, f"fetch: {display}: known missing")
        return None
    if offline:
        resources[key] = {
            "status": "unavailable",
            "url": old.get("url") or url,
            "reason": "not cached; network disabled by --offline",
            **({"expected_sha256": expected_sha256} if expected_sha256 else {}),
            **({"identity": dict(identity)} if identity else {}),
            **dict(metadata or {}),
        }
        _emit(progress, f"fetch: {display}: not cached (offline)")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    _emit(progress, f"fetch: {display}: requesting")
    try:
        payload = get(
            url, ipv4=ipv4,
            accept="application/octet-stream" if binary else "application/xml",
        )
    except urllib.error.HTTPError as error:
        status_name = "missing" if error.code in FINAL_STATUS else "error"
        resources[key] = {
            "status": status_name,
            "url": url,
            "http_status": error.code,
            **({"expected_sha256": expected_sha256} if expected_sha256 else {}),
            **({"identity": dict(identity)} if identity else {}),
            **dict(metadata or {}),
        }
        _emit(progress, f"fetch: {display}: {status_name} (HTTP {error.code})")
        return None
    except OSError as error:
        resources[key] = {
            "status": "error", "url": url, "error": str(error),
            **({"expected_sha256": expected_sha256} if expected_sha256 else {}),
            **({"identity": dict(identity)} if identity else {}),
            **dict(metadata or {}),
        }
        _emit(progress, f"fetch: {display}: error ({error})")
        return None
    actual_sha256 = _digest(payload)
    if expected_sha256 and actual_sha256 != expected_sha256:
        resources[key] = {
            "status": "error", "url": url,
            "detail": "pinned checksum mismatch",
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
            **({"identity": dict(identity)} if identity else {}),
            **dict(metadata or {}),
        }
        _emit(progress, f"fetch: {display}: error (pinned checksum mismatch)")
        return None
    status, detail = ("ok", "") if binary else classify_payload(payload)
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
        **({"expected_sha256": expected_sha256} if expected_sha256 else {}),
        **({"identity": dict(identity)} if identity else {}),
        **dict(metadata or {}),
        **({"detail": detail} if detail else {}),
    }
    _emit(progress, f"fetch: {display}: {stored_status} ({_size_text(len(payload))})")
    return target


def _fetch_validation_packages(
    release_dir: Path,
    manifest: dict[str, Any],
    *,
    ipv4: bool,
    retry_missing: bool,
    offline: bool,
    progress: Progress | None,
) -> bool:
    available = True
    for package in VALIDATION_ARCHIVES:
        target = package_archive_path(release_dir, package)
        path = _fetch_direct(
            release_dir,
            manifest,
            key=package.key,
            relative_file=str(target.relative_to(release_dir)),
            url=package.url,
            ipv4=ipv4,
            retry_missing=retry_missing,
            offline=offline,
            progress=progress,
            label=f"pinned {package.project} {package.version}",
            identity={
                "type": (
                    "validation-tool"
                    if package.key.startswith("validation-tool:")
                    else "validation-package"
                ),
                "id": package.project,
                "effective_date": package.version,
                "project": package.project,
                "api_base": package.url.rsplit("/", 1)[0],
            },
            expected_sha256=package.sha256,
            binary=True,
            metadata={"version": package.version, "license": package.license},
        )
        available = available and path is not None
    if not available:
        manifest["validation_packages"] = {
            "status": "unavailable",
            "error": "one or more pinned validation packages are unavailable",
        }
        return False
    try:
        lock = extract_validation_packages(release_dir)
    except (OSError, ValueError) as error:
        manifest["validation_packages"] = {
            "status": "error", "error": str(error),
        }
        _emit(progress, f"fetch: validation packages: error ({error})")
        return False
    manifest["validation_packages"] = {
        "status": "ok",
        "lock": "validation/package-lock.json",
        "packages": len(lock.get("packages", [])),
    }
    _emit(progress, "fetch: validation packages: verified and extracted")
    return True


def _fetch_openapi(
    release_dir: Path,
    manifest: dict[str, Any],
    *,
    api_base: str,
    ipv4: bool,
    retry_missing: bool,
    offline: bool = False,
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
    if payload is None and offline:
        manifest["resources"][key] = {
            "status": "unavailable",
            "url": old.get("url") or url,
            "reason": "not cached; network disabled by --offline",
        }
        _emit(progress, "fetch: API contract: not cached (offline)")
        return None
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
    want: Mapping[str, object],
    *,
    owners: Mapping[str, str],
    repositories: Iterable[str],
    language: str,
    ipv4: bool,
    retry_missing: bool,
    offline: bool = False,
    request_budget: dict[str, int] | None = None,
    progress: Progress | None = None,
    save_manifest: Callable[[], None] | None = None,
    main_project: str = "aktin-",
    release: str = "",
    api_base: str = DEFAULT_API_BASE,
    source_hints: Mapping[str, Mapping[str, str]] | None = None,
    configured_oid_owners: Mapping[str, str] | None = None,
    artifact_owners: dict[str, str] | None = None,
    save_artifact_owners: Callable[[], None] | None = None,
) -> Path | None:
    requested_want = cast(Want, dict(want))
    resolved_want = resolve_alias(want, source_hints or {})
    requested_key = _key(requested_want)
    key = _key(resolved_want)
    old = manifest.setdefault("resources", {}).get(key, {})
    # An earlier dynamic request may already have frozen the exact revision
    # now named by a reviewed profile rule. Reuse that checksum-verified
    # representation instead of requiring a duplicate network fetch or file.
    if not old.get("file"):
        wanted_identity = _identity(resolved_want)
        wanted_date = str(wanted_identity.get("effective_date") or "")
        if wanted_date:
            for candidate in manifest.setdefault("resources", {}).values():
                if not isinstance(candidate, Mapping):
                    continue
                identity = candidate.get("identity", {})
                if not isinstance(identity, Mapping):
                    continue
                if (
                    candidate.get("status") == "ok"
                    and candidate.get("file")
                    and str(identity.get("type") or "")
                    == str(wanted_identity.get("type") or "")
                    and str(identity.get("id") or "")
                    == str(wanted_identity.get("id") or "")
                    and str(identity.get("effective_date") or "") == wanted_date
                ):
                    old = candidate
                    break
    relative = str(old.get("file") or _filename(resolved_want))
    target = release_dir / relative
    display = _resource_label(resolved_want)
    external_mode = resolved_want.get("mode") or ""

    def finish(path: Path | None) -> Path | None:
        """Record a reviewed malformed identity without fabricating success."""
        if requested_key != key and resolved_want.get("alias_requested_key"):
            manifest.setdefault("resources", {})[requested_key] = {
                "status": "alias",
                "alias_of": key,
                "identity_corrected": True,
                "requested_effective_date": (
                    requested_want.get("effective_date") or "dynamic"
                ),
                "identity": _identity(requested_want),
                "reason": resolved_want.get("alias_reason") or "",
                "source_hint": resolved_want.get("alias_requested_key") or "",
                "source_hint_origin": (
                    resolved_want.get("alias_source_hint_origin") or "bundled"
                ),
            }
            if save_manifest is not None:
                save_manifest()
        return path

    def external_resolution() -> tuple[bool, Path | None]:
        return _materialize_external(
            release_dir, manifest, resolved_want, key=key, relative=relative,
            progress=progress, save_manifest=save_manifest,
        )

    # A waiver is an explicit settled decision, not a network fallback. A
    # previously materialized builtin is likewise reconstructed from its
    # package checksum before generic cache adoption, preserving provenance
    # even after manifest.json has been deleted.
    if external_mode == "waiver" or (
        external_mode == "builtin" and target.is_file()
    ):
        handled, external_path = external_resolution()
        if handled:
            return finish(external_path)
    existing = _existing_cache_payload(target, old)
    if existing is not None and not _payload_matches_request(existing, resolved_want):
        existing = None
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

    cached_representations: dict[str, dict[str, Any]] = {}
    cached_payloads: dict[str, bytes] = {}
    cached_expansion_warning = ""
    for form in old_representations:
        payload, entry = cached_representation(str(form))
        if payload is not None:
            if str(form) == "expansion":
                usable, warning = expansion_status(payload)
                if not usable:
                    cached_expansion_warning = warning
                    cached_representations["expansion-evidence"] = entry
                    cached_payloads["expansion-evidence"] = payload
                    continue
            elif str(form) == "expansion-evidence":
                _, cached_expansion_warning = expansion_status(payload)
            cached_representations[str(form)] = entry
            cached_payloads[str(form)] = payload
    cached_source = cached_payloads.get("source")
    if existing is not None:
        resolved_date = _resolved_effective_date(existing, resolved_want)
        # The analysis form of a reference declaration is a project envelope
        # that carries no revision, while its source form does.  A download
        # records the revision from the richer form, so cache adoption must
        # consult the same evidence instead of downgrading the identity to
        # `dynamic`.
        if not resolved_date and cached_source is not None:
            resolved_date = _resolved_effective_date(cached_source, resolved_want)
        requested_date = requested_want.get("effective_date") or ""
        # A static dependency must not accidentally adopt another revision that
        # happens to have the expected filename. Dynamic dependencies may adopt
        # whatever revision the valid cached response actually contains.
        expected_date = resolved_want.get("effective_date") or ""
        if not expected_date or not resolved_date or resolved_date == expected_date:
            cache_entry = {
                **old,
                "status": "ok",
                "file": relative,
                "project": old.get("project") or resolved_want.get("project") or "",
                "api_base": old.get("api_base") or resolved_want.get("api_base") or api_base,
                "bytes": len(existing),
                "sha256": _digest(existing),
                "requested_effective_date": requested_date or "dynamic",
                "resolved_effective_date": resolved_date or old.get("resolved_effective_date", ""),
                "representations": {
                    **cached_representations,
                    "analysis": {
                        "status": "ok",
                        "file": relative,
                        "url": old.get("url") or "",
                        "bytes": len(existing),
                        "sha256": _digest(existing),
                    },
                },
                "identity": _identity(
                    resolved_want,
                    project=str(old.get("project") or resolved_want.get("project") or ""),
                    effective_date=resolved_date or str(old.get("resolved_effective_date") or ""),
                    api_base=str(old.get("api_base") or api_base),
                ),
                **_source_hint_fields(resolved_want),
                **(
                    {"source_warning": "source representation unavailable"}
                    if cached_source is None else {}
                ),
            }
            if cached_source is not None:
                cache_entry.pop("source_warning", None)
            needs_expansion = (
                resolved_want.get("kind") == "valueset"
                and "expansion" not in cached_representations
                and _valueset_needs_expansion(existing)
                and (
                    retry_missing
                    or not (
                        cached_expansion_warning
                        or old.get("expansion_warning")
                    )
                    or "request budget" in str(old.get("expansion_warning") or "")
                    or "network is disabled" in str(old.get("expansion_warning") or "")
                )
            )
            if needs_expansion and offline:
                cache_entry["expansion_warning"] = (
                    cached_expansion_warning
                    or "value-set expansion unavailable while network is disabled"
                )
            elif "expansion" in cached_representations:
                cache_entry.pop("expansion_warning", None)
            manifest["resources"][key] = cache_entry
            repaired = (
                old.get("status") != "ok"
                or old.get("file") != relative
                or cached_source is None and not old.get("source_warning")
            )
            suffix = " (manifest repaired)" if repaired else ""
            _emit(progress, f"fetch: {display}: cached{suffix}")
            if repaired and save_manifest is not None:
                save_manifest()
            if not needs_expansion or offline:
                return finish(target)
    if old.get("status") == "missing" and not retry_missing:
        handled, external_path = external_resolution()
        if handled:
            return finish(external_path)
        normalized_old = dict(old)
        normalized_old["projects_considered"] = list(
            old.get("projects_considered") or old.get("attempted_projects") or []
        )
        normalized_old["resolution_attempts"] = list(
            old.get("resolution_attempts") or old.get("attempts") or []
        )
        manifest["resources"][key] = normalized_old
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: known missing")
        return finish(None)

    request_want = cast(Want, dict(resolved_want))
    if not request_want.get("effective_date") and old.get("resolved_effective_date"):
        request_want["effective_date"] = str(old["resolved_effective_date"])

    attempts: list[dict[str, Any]] = []
    saved_representations: dict[str, dict[str, Any]] = {
        **cached_representations,
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

    if offline:
        handled, external_path = external_resolution()
        if handled:
            return finish(external_path)
        manifest["resources"][key] = {
            "status": "unavailable",
            "reason": "not cached; network disabled by --offline",
            "project": old.get("project") or resolved_want.get("project") or "",
            "api_base": old.get("api_base") or resolved_want.get("api_base") or api_base,
            "requested_effective_date": requested_want.get("effective_date") or "dynamic",
            "resolved_effective_date": old.get("resolved_effective_date") or "",
            "representations": saved_representations,
            "identity": _identity(
                resolved_want,
                project=str(old.get("project") or resolved_want.get("project") or ""),
                effective_date=str(old.get("resolved_effective_date") or ""),
                api_base=str(old.get("api_base") or api_base),
            ),
            **_source_hint_fields(resolved_want),
        }
        if save_manifest is not None:
            save_manifest()
        _emit(progress, f"fetch: {display}: not cached (offline)")
        return finish(None)

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
        representation = {
            "status": "ok",
            "file": form_relative,
            "url": url,
            "bytes": len(payload),
            "sha256": _digest(payload),
        }
        saved_representations[form] = representation
        # Dynamic and exact requests can converge on one frozen representation
        # path. Expansion envelopes carry request-time UUID/timestamp metadata,
        # so a later equivalent response changes the physical checksum. Keep
        # every manifest reference to that shared file synchronized.
        resources = manifest.get("resources", {})
        for resource in resources.values() if isinstance(resources, Mapping) else ():
            if not isinstance(resource, dict):
                continue
            forms = resource.get("representations", {})
            if not isinstance(forms, dict):
                continue
            for old_form, old_representation in list(forms.items()):
                if (
                    isinstance(old_representation, Mapping)
                    and old_representation.get("file") == form_relative
                ):
                    forms[old_form] = dict(representation)
        return path

    candidates = deque(_candidate_projects(
        request_want, owners, repositories, artifact_owners,
        configured_oid_owners,
    ))
    attempted_candidates: set[str] = set()
    considered_projects: list[str] = []
    while candidates:
        project = candidates.popleft()
        if project in attempted_candidates:
            continue
        attempted_candidates.add(project)
        considered_projects.append(project)
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
        if request_want["kind"] == "valueset":
            needs_expansion = _valueset_needs_expansion(analysis_payload)
            if needs_expansion and "expansion" not in saved_representations:
                expansion_effective = (
                    resolved_date
                    or request_want.get("effective_date")
                    or "dynamic"
                )
                expansion_url = valueset_expansion_url(
                    request_want["id"], expansion_effective,
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
                    usable, expansion_error = expansion_status(expansion_payload)
                    if usable:
                        store("expansion", expansion_payload, expansion_url)
                    else:
                        store(
                            "expansion-evidence", expansion_payload, expansion_url
                        )
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
            "projects_considered": considered_projects,
            "resolution_attempts": attempts,
            **(
                {"owner_source": "configured-oid-owner"}
                if not _owner(request_want["id"], owners)
                and project == _owner(
                    request_want["id"], configured_oid_owners or {}
                )
                else {}
            ),
            "representations": saved_representations,
            **_source_hint_fields(request_want),
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
                exact_want = cast(Want, dict(request_want))
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
        return finish(analysis_path)

    relevant_attempts = [item for item in attempts if item.get("form") == "analysis"]
    if not relevant_attempts:
        relevant_attempts = attempts
    settled = bool(relevant_attempts) and all(
        item.get("http_status") in FINAL_STATUS
        or str(item.get("error") or "").startswith("<")
        for item in relevant_attempts
    )
    handled, external_path = external_resolution()
    if handled:
        return finish(external_path)
    final_status = "missing" if settled else "error"
    owner = _owner(resolved_want["id"], owners)
    configured_owner = _owner(
        resolved_want["id"], configured_oid_owners or {}
    )
    projects_considered = considered_projects
    manifest["resources"][key] = {
        "status": final_status,
        "settled": settled,
        "owner": owner,
        **({"configured_owner": configured_owner} if configured_owner else {}),
        "declared_project": resolved_want.get("project") or "",
        "projects_considered": projects_considered,
        "resolution_attempts": attempts,
        # Compatibility spellings retained for existing generated workspaces.
        "attempted_projects": projects_considered,
        "attempts": attempts,
        "representations": saved_representations,
        "identity": _identity(
            resolved_want,
            project=projects_considered[-1] if projects_considered else "",
            api_base=resolved_want.get("api_base") or api_base,
        ),
        **_source_hint_fields(resolved_want),
    }
    if save_manifest is not None:
        save_manifest()
    _emit(progress, f"fetch: {display}: {final_status} after {len(attempts)} attempt(s)")
    return finish(None)


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
        elif (
            entry.get("expected_sha256")
            and _digest(path.read_bytes()) != entry["expected_sha256"]
        ):
            errors.append(f"{label}: pinned checksum mismatch for {relative}")

    for key, entry in manifest.get("resources", {}).items():
        if not isinstance(entry, Mapping):
            continue
        verify_entry(key, entry)
        representations = entry.get("representations", {})
        if isinstance(representations, Mapping):
            for form, representation in representations.items():
                if isinstance(representation, Mapping):
                    verify_entry(f"{key}[{form}]", representation)
    validation_packages = manifest.get("validation_packages", {})
    if isinstance(validation_packages, Mapping) and validation_packages.get("status") == "ok":
        errors.extend(
            f"validation packages: {problem}"
            for problem in validation_package_problems(release_dir)
        )
    return errors


def closure_paths(release_dir: Path, transaction_dir: Path, role: str = "build") -> list[Path]:
    """Resolve resource paths recorded for a completed transaction closure."""
    closure = load_json(transaction_dir / "closure.json")
    crawl_complete = closure.get("crawl_complete", closure.get("complete"))
    if not crawl_complete or closure.get("interrupted") or closure.get("truncated"):
        raise ValueError("transaction crawl is incomplete; rerun `decor2hl7 fetch`")
    manifest = load_json(release_dir / "manifest.json")
    keys = closure.get(f"{role}_resources", [])
    result: list[Path] = []
    for key in keys:
        entry = manifest.get("resources", {}).get(key, {})
        seen = {str(key)}
        while isinstance(entry, Mapping) and entry.get("status") == "alias":
            target_key = str(entry.get("alias_of") or "")
            if not target_key or target_key in seen:
                break
            seen.add(target_key)
            entry = manifest.get("resources", {}).get(target_key, {})
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
    offline: bool = False,
    max_requests: int = 1500,
    progress: Progress | None = None,
    api_base: str = DEFAULT_API_BASE,
    source_hints: Mapping[str, Mapping[str, str]] | None = None,
    cda_extensions: Iterable[Mapping[str, Any]] = (),
    cda_core: bool = False,
    validation_packages: bool = False,
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
    extensions = normalize_extensions(cda_extensions)
    if any(
        extension["transaction_id"] != tx_id
        or extension["transaction_effective_date"] != tx_effective
        for extension in extensions
    ):
        raise ValueError(
            "CDA extension transaction identity does not match the selected transaction"
        )

    roles: dict[str, set[str]] = {"build": set(), "evidence": set()}
    resource_roles: dict[str, set[str]] = {}
    visited: dict[str, set[str]] = {"build": set(), "evidence": set()}
    build_queue: deque[Want] = deque()
    evidence_queue: deque[Want] = deque()
    optional_references: dict[str, Want] = {}
    pending_batch: dict[str, list[Want]] = {"build": [], "evidence": []}
    request_budget = {"made": 0, "max": max(0, int(max_requests))}
    resources_considered = 0
    budget_exhausted = False
    phase = "roots"
    root_errors: list[str] = []
    root_status = {
        "cda_core": "pending" if cda_core else "not-requested",
        "validation_packages": "pending" if validation_packages else "not-requested",
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

    def observe_optional(*roots: ET.Element | None) -> None:
        for root in roots:
            if root is None:
                continue
            for want in display_references(root):
                optional_references.setdefault(_key(want), want)

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
        raw_resources = manifest.get("resources", {})
        manifest_resources = (
            raw_resources if isinstance(raw_resources, Mapping) else {}
        )
        manifest_rows = [
            row for row in manifest_resources.values()
            if isinstance(row, Mapping)
        ]

        def resolved_entry(key: str) -> Mapping[str, Any]:
            resources = manifest.get("resources", {})
            entry = resources.get(key, {}) if isinstance(resources, Mapping) else {}
            seen = {key}
            while isinstance(entry, Mapping) and entry.get("status") == "alias":
                target = str(entry.get("alias_of") or "")
                if not target or target in seen:
                    break
                seen.add(target)
                entry = (
                    resources.get(target, {})
                    if isinstance(resources, Mapping) else {}
                )
            return entry if isinstance(entry, Mapping) else {}

        def resolved_status(key: str) -> str:
            return str(resolved_entry(key).get("status") or "unknown")

        current_errors = sorted(
            key for key in current_keys
            if resolved_status(key) == "error"
        )
        current_missing = sorted(
            key for key in current_keys
            if resolved_status(key) == "missing"
        )
        current_unavailable = sorted(
            key for key in current_keys
            if resolved_status(key) == "unavailable"
        )
        current_waived = sorted(
            key for key in current_keys
            if resolved_status(key) == "waived"
        )
        current_partial = sorted(
            key for key in current_keys
            if resolved_status(key) == "partial"
        )
        current_aliases = sorted(
            key for key in current_keys
            if isinstance(manifest_resources.get(key), Mapping)
            and manifest_resources[key].get("status") == "alias"
        )
        build_pending = pending_keys("build")
        evidence_pending = pending_keys("evidence")
        crawl_complete = complete
        required_failures = sorted(
            key for key in roles["build"]
            if any(
                role in REQUIRED_ROLES
                for role in resource_roles.get(key, set())
            )
            and (
                resolved_status(key) != "ok"
                or bool(resolved_entry(key).get("expansion_warning"))
            )
        )
        resolution = {
            key: {
                "projects_considered": list(
                    resolved_entry(key).get("projects_considered")
                    or resolved_entry(key).get("attempted_projects")
                    or []
                ),
                "resolution_attempts": list(
                    resolved_entry(key).get("resolution_attempts")
                    or resolved_entry(key).get("attempts")
                    or []
                ),
            }
            for key in sorted(
                set(required_failures) | set(current_missing)
                | set(current_unavailable) | set(current_errors)
            )
        }
        readiness_errors: list[str] = []
        if root_status["transaction"] != "ok":
            readiness_errors.append("selected transaction analysis form is unavailable")
        if root_status["transaction_source"] != "ok":
            readiness_errors.append("selected transaction source form is unavailable")
        if cda_core and root_status["cda_core"] != "ok":
            readiness_errors.append("pinned CDA core definition set is unavailable")
        if validation_packages and root_status["validation_packages"] != "ok":
            readiness_errors.append("pinned validation package set is unavailable")
        degradation_warnings = [
            (
                f"dependency expansion incomplete: {key}: "
                f"{resolved_entry(key).get('expansion_warning')}"
                if resolved_entry(key).get("expansion_warning")
                else f"dependency unavailable: {key}"
            )
            for key in required_failures
        ]
        build_ready = crawl_complete and not readiness_errors
        closure = {
            "format": 2,
            "release": dict(release),
            "transaction": dict(transaction),
            "cda_extensions": extensions,
            # ``complete`` remains the compatibility spelling for crawl state.
            # It must not be interpreted as permission to compile.
            "complete": crawl_complete,
            "crawl_complete": crawl_complete,
            "build_ready": build_ready,
            "readiness_errors": readiness_errors,
            "degraded": bool(degradation_warnings),
            "degraded_resources": required_failures,
            "crawl_degraded": required_failures,
            "degradation_warnings": degradation_warnings,
            "resolution": resolution,
            "interrupted": interrupted,
            "phase": phase,
            "build_resources": sorted(roles["build"]),
            "evidence_resources": sorted(roles["evidence"] | roles["build"]),
            "resource_roles": {
                key: sorted(values)
                for key, values in sorted(resource_roles.items())
                if values
            },
            "optional_references": [
                dict(optional_references[key]) for key in sorted(optional_references)
            ],
            "pending": {
                "build": build_pending,
                "evidence": evidence_pending,
            },
            "missing": current_missing,
            "unavailable": current_unavailable,
            "waived": current_waived,
            "partial": current_partial,
            "aliases": current_aliases,
            "errors": current_errors + root_errors,
            "root_status": dict(root_status),
            "summary": {
                "ok": sum(
                    resolved_status(key) == "ok"
                    for key in current_keys
                ) + int(root_status["project_config"] == "ok") + int(root_status["transaction"] == "ok"),
                "missing": len(current_missing),
                "unavailable": len(current_unavailable),
                "waived": len(current_waived),
                "partial": len(current_partial),
                "alias": len(current_aliases),
                "error": len(current_errors) + len(root_errors),
            },
            "resources_considered": resources_considered,
            "recursive_http_requests": request_budget["made"],
            # Backwards-compatible meaning: the request budget stopped the
            # crawler.  A user interruption is recorded separately.
            "truncated": budget_exhausted,
        }
        manifest["summary"] = {
            "resources": len(manifest_resources),
            "ok": sum(row.get("status") == "ok" for row in manifest_rows),
            "missing": sum(
                row.get("status") == "missing" for row in manifest_rows
            ),
            "unavailable": sum(
                row.get("status") == "unavailable" for row in manifest_rows
            ),
            "waived": sum(
                row.get("status") == "waived" for row in manifest_rows
            ),
            "partial": sum(
                row.get("status") == "partial" for row in manifest_rows
            ),
            "alias": sum(
                row.get("status") == "alias" for row in manifest_rows
            ),
            "error": sum(
                row.get("status") == "error" for row in manifest_rows
            ),
        }
        write_json(manifest_path, manifest)
        write_json(closure_path, closure)
        return closure

    try:
        if validation_packages:
            validation_ok = _fetch_validation_packages(
                release_dir, manifest, ipv4=ipv4,
                retry_missing=retry_missing, offline=offline, progress=progress,
            )
            root_status["validation_packages"] = "ok" if validation_ok else "missing"

        if cda_core:
            core_ok = True
            for filename, source_path in CORE_FILES.items():
                path = _fetch_direct(
                    release_dir, manifest,
                    key=f"cda-core:{filename}@{CORE_REVISION}",
                    relative_file=f"cda-core/{filename}",
                    url=CORE_RAW_BASE + source_path, ipv4=ipv4,
                    retry_missing=retry_missing, offline=offline, progress=progress,
                    label=f"pinned CDA core {filename}",
                    identity={
                        "type": "cda-core", "id": filename,
                        "effective_date": CORE_REVISION, "project": "HL7/CDA-core-2.0",
                        "api_base": "https://github.com/HL7/CDA-core-2.0",
                    },
                )
                core_ok = core_ok and path is not None
            root_status["cda_core"] = "ok" if core_ok else "missing"

        contract = _fetch_openapi(
            release_dir, manifest, api_base=api_base, ipv4=ipv4,
            retry_missing=retry_missing, offline=offline, progress=progress,
        )
        root_status["api_contract"] = "ok" if contract is not None else "error"

        project_config = _fetch_direct(
            release_dir, manifest, key=f"project-config:{prefix}",
            relative_file="project.xml",
            url=project_url(prefix, base_url=api_base), ipv4=ipv4,
            retry_missing=retry_missing, offline=offline, progress=progress,
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
            retry_missing=retry_missing, offline=offline, progress=progress,
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
            retry_missing=retry_missing, offline=offline, progress=progress,
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
            url=source_url, ipv4=ipv4, retry_missing=retry_missing, offline=offline,
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
            url=analysis_url, ipv4=ipv4, retry_missing=retry_missing, offline=offline,
            progress=progress,
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
        configured_owners = getattr(source_hints, "oid_owners", {})
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
        observe_optional(
            _parse(project_config) if project_config else None,
            *(build_roots + evidence_roots),
        )

        tx_root = _parse(tx_path) if tx_path else None
        if tx_root is not None:
            build_queue.extend(hard_references(tx_root))
            evidence_queue.extend(soft_references(tx_root))
        for extension in extensions:
            build_queue.append(Want(
                kind="template",
                id=extension["template_id"],
                effective_date=extension["template_effective_date"],
                project="",
                role="structure",
            ))

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
                    cast(Want, apply_source_hint(item, source_hints or {}))
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
                    resource_roles.setdefault(key, set()).add(
                        want.get("role") or "structure"
                    )
                    if key in visited["build"]:
                        continue
                    embedded = _matching_embedded(embedded_roots, want)
                    if _satisfied(want, have_by_role["build"]):
                        visited["build"].add(key)
                        for node in embedded:
                            queue.extend(hard_references(node))
                            evidence_queue.extend(soft_references(node))
                        continue

                    resources_considered += 1
                    try:
                        path = _fetch_want(
                            release_dir, manifest, want, owners=owners,
                            repositories=repositories, language=language,
                            ipv4=ipv4, retry_missing=retry_missing, offline=offline,
                            request_budget=request_budget, progress=progress,
                            save_manifest=save_manifest,
                            main_project=prefix, release=release_date,
                            api_base=api_base, source_hints=source_hints,
                            configured_oid_owners=configured_owners,
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
                        observe_optional(root)
                        inventory = _inventory(root)
                        have_by_role["build"].update(inventory)
                        have_by_role["evidence"].update(inventory)
                        queue.extend(hard_references(root))
                        evidence_queue.extend(soft_references(root))
                pending_batch["build"] = []
                checkpoint(complete=False)

        def resolve_evidence(queue: deque[Want], embedded_roots: list[ET.Element | None]) -> None:
            """Resolve direct evidence and transitively close identity lineage."""
            nonlocal resources_considered, budget_exhausted, phase
            phase = "evidence"

            def next_identity(root: ET.Element, want: Want) -> list[Want]:
                if want.get("kind") != "concept":
                    return []
                return identity_references(root, {want["id"]})

            _emit(
                progress,
                "fetch: resolving direct evidence and identity lineage "
                f"({len(queue)} initial reference(s))",
            )
            while queue and not budget_exhausted:
                merged: dict[str, Want] = {}
                for item in queue:
                    want = cast(
                        Want, apply_source_hint(item, source_hints or {})
                    )
                    key = _key(want)
                    resource_roles.setdefault(key, set()).add(
                        want.get("role") or "mapping-evidence"
                    )
                    current = merged.get(key)
                    if (
                        current is None
                        or (
                            current.get("analysis_only")
                            and not want.get("analysis_only")
                        )
                    ):
                        # A broader request satisfies both consumers; retain
                        # every role above even though the HTTP work is shared.
                        merged[key] = want
                rows = list(merged.values())
                queue.clear()
                rows.sort(key=lambda item: (
                    KIND_ORDER.get(item["kind"], 9),
                    item.get("project", ""),
                    item["id"],
                ))
                pending_batch["evidence"] = list(rows)
                for row_index, want in enumerate(rows):
                    pending_batch["evidence"] = rows[row_index:]
                    key = _key(want)
                    if key in visited["evidence"] or key in visited["build"]:
                        continue
                    embedded = _matching_embedded(embedded_roots, want)
                    if _satisfied(want, have_by_role["evidence"]):
                        visited["evidence"].add(key)
                        for node in embedded:
                            queue.extend(next_identity(node, want))
                        continue
                    # The complete main-project evidence snapshot is already
                    # local; use an exact embedded resource before requesting.
                    if embedded:
                        visited["evidence"].add(key)
                        for node in embedded:
                            queue.extend(next_identity(node, want))
                        continue

                    resources_considered += 1
                    try:
                        path = _fetch_want(
                            release_dir, manifest, want, owners=owners,
                            repositories=repositories, language=language,
                            ipv4=ipv4, retry_missing=retry_missing, offline=offline,
                            request_budget=request_budget, progress=progress,
                            save_manifest=save_manifest,
                            main_project=prefix, release=release_date,
                            api_base=api_base, source_hints=source_hints,
                            configured_oid_owners=configured_owners,
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
                            # A concept response may contain a parent/sibling
                            # subtree. Keep it available so a later exact
                            # endpoint satisfied by that inventory still gets
                            # its own targeted identity ancestry inspected.
                            embedded_roots.append(root)
                            if _seed_artifact_owners(artifact_owners, root):
                                save_artifact_owners()
                            observe_optional(root)
                            have_by_role["evidence"].update(_inventory(root))
                            # Identity is transitive.  Do not recursively follow
                            # ADAPT/derivation, template or terminology evidence.
                            queue.extend(next_identity(root, want))
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
            f"{closure['summary']['unavailable']} unavailable, "
            f"{closure['summary'].get('waived', 0)} waived, "
            f"{closure['summary'].get('partial', 0)} partial, "
            f"{closure['summary']['error']} error(s), "
            f"{closure['recursive_http_requests']} recursive HTTP request(s)",
        )
        return {"manifest": manifest, "closure": closure}
    except KeyboardInterrupt:
        phase = f"{phase}-interrupted"
        checkpoint(complete=False, interrupted=True)
        _emit(progress, "fetch: interrupted by user; checkpoint saved")
        raise
