"""Typed local artifact records at the retrieval/compiler boundary.

The retrieval manifest records requests and files.  Compilers need a stricter
view: requested and resolved identities must remain distinct, every available
representation must stay addressable, and dependency purpose must be explicit.
This module creates that view without introducing a service-object hierarchy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, TypedDict

from ..workspace import load_json

ArtifactKind = Literal[
    "transaction", "dataset", "concept", "template", "valueset", "codesystem",
]
ArtifactFormName = Literal["source", "analysis", "expansion"]
DependencyRole = Literal[
    "structure", "formal-terminology", "expansion-support",
    "mapping-evidence", "display-evidence",
]

REQUIRED_ROLES: frozenset[str] = frozenset({
    "structure", "formal-terminology", "expansion-support",
})


class ArtifactIdentity(TypedDict, total=False):
    type: str
    id: str
    effective_date: str
    project: str
    api_base: str
    context_id: str
    context_effective_date: str


class ArtifactForm(TypedDict, total=False):
    name: str
    path: Path
    url: str
    sha256: str
    bytes: int


class ArtifactRecord(TypedDict, total=False):
    request_key: str
    aliases: list[str]
    requested: ArtifactIdentity
    requests: list[ArtifactIdentity]
    resolved: ArtifactIdentity
    forms: dict[str, ArtifactForm]
    roles: list[str]
    required: bool
    status: str
    resolution: dict[str, str]


def _request_identity(key: str, entry: Mapping[str, Any]) -> ArtifactIdentity:
    identity = entry.get("identity", {})
    resolved = identity if isinstance(identity, Mapping) else {}
    head, _, raw_effective = key.partition("@")
    kind, separator, identifier = head.partition(":")
    requested_effective = str(entry.get("requested_effective_date") or raw_effective)
    if requested_effective == "dynamic":
        requested_effective = ""
    return {
        "type": kind if separator else str(resolved.get("type") or ""),
        "id": identifier if separator else str(resolved.get("id") or ""),
        "effective_date": requested_effective,
        "project": str(entry.get("declared_project") or resolved.get("project") or ""),
        "api_base": str(resolved.get("api_base") or entry.get("api_base") or ""),
        **(
            {"context_id": str(resolved.get("context_id"))}
            if resolved.get("context_id") else {}
        ),
        **(
            {"context_effective_date": str(resolved.get("context_effective_date"))}
            if resolved.get("context_effective_date") else {}
        ),
    }


def _resolved_identity(entry: Mapping[str, Any]) -> ArtifactIdentity:
    raw = entry.get("identity", {})
    identity = dict(raw) if isinstance(raw, Mapping) else {}
    if entry.get("resolved_effective_date"):
        identity["effective_date"] = entry["resolved_effective_date"]
    return {str(key): str(value) for key, value in identity.items() if value is not None}


def _form(
    release_dir: Path, name: str, entry: Mapping[str, Any],
) -> ArtifactForm | None:
    relative = str(entry.get("file") or "")
    if not relative:
        return None
    return {
        "name": name,
        "path": release_dir / relative,
        "url": str(entry.get("url") or ""),
        "sha256": str(entry.get("sha256") or ""),
        "bytes": int(entry.get("bytes") or 0),
    }


def artifact_record(
    release_dir: Path,
    key: str,
    entry: Mapping[str, Any],
    roles: Iterable[str] = (),
) -> ArtifactRecord:
    """Convert one manifest entry without discarding partial usable forms."""
    forms: dict[str, ArtifactForm] = {}
    representations = entry.get("representations", {})
    if isinstance(representations, Mapping):
        for name, representation in representations.items():
            if isinstance(representation, Mapping):
                parsed = _form(release_dir, str(name), representation)
                if parsed is not None:
                    forms[str(name)] = parsed
    main = _form(release_dir, "analysis", entry)
    if main is not None:
        forms.setdefault("analysis", main)
    role_list = list(dict.fromkeys(str(role) for role in roles if role))
    requested = _request_identity(key, entry)
    resolved = _resolved_identity(entry)
    return {
        "request_key": key,
        "aliases": [key],
        "requested": requested,
        "requests": [requested],
        "resolved": resolved,
        "forms": forms,
        "roles": role_list,
        "required": any(role in REQUIRED_ROLES for role in role_list),
        "status": str(entry.get("status") or "unknown"),
        "resolution": {
            "source_hint": str(entry.get("source_hint") or ""),
            "publication_url": str(entry.get("publication_url") or ""),
            "owner": str(entry.get("owner") or resolved.get("project") or ""),
        },
    }


def artifact_problems(record: Mapping[str, Any]) -> list[str]:
    """Validate exact identity and required compiler representation."""
    problems: list[str] = []
    key = str(record.get("request_key") or "artifact")
    requested = record.get("requested", {})
    resolved = record.get("resolved", {})
    forms = record.get("forms", {})
    if not isinstance(requested, Mapping) or not isinstance(resolved, Mapping):
        return [f"{key}: malformed identity"]
    resolved_date = str(resolved.get("effective_date") or "")
    requests = record.get("requests", [requested])
    for request in (requests if isinstance(requests, list) else [requested]):
        if not isinstance(request, Mapping):
            continue
        requested_date = str(request.get("effective_date") or "")
        if requested_date and requested_date != resolved_date:
            problems.append(
                f"{key}: requested static revision {requested_date}, "
                f"resolved {resolved_date or 'unknown'}"
            )
        if request.get("id") and resolved.get("id") and request.get("id") != resolved.get("id"):
            problems.append(
                f"{key}: requested id {request.get('id')}, resolved {resolved.get('id')}"
            )
    if record.get("required") and record.get("status") != "ok":
        problems.append(f"{key}: required artifact status is {record.get('status')}")
    if record.get("required") and (
        not isinstance(forms, Mapping) or "analysis" not in forms
    ):
        problems.append(f"{key}: required analysis form is unavailable")
    for name, form in (forms.items() if isinstance(forms, Mapping) else ()):
        if isinstance(form, Mapping):
            path = form.get("path")
            if isinstance(path, Path) and not path.is_file():
                problems.append(f"{key}[{name}]: missing file {path}")
    return problems


def closure_records(
    release_dir: Path,
    transaction_dir: Path,
    role: str = "build",
    *,
    require_ready: bool = True,
) -> list[ArtifactRecord]:
    closure = load_json(transaction_dir / "closure.json")
    crawl_complete = closure.get("crawl_complete", closure.get("complete"))
    build_ready = closure.get("build_ready") is True
    if not crawl_complete or closure.get("interrupted") or closure.get("truncated"):
        raise ValueError("transaction crawl is incomplete; rerun `decor2hl7 fetch`")
    if role == "build" and require_ready and not build_ready:
        reasons = closure.get("readiness_errors", [])
        if "build_ready" not in closure:
            reasons = [
                "closure predates build-readiness validation; rerun `decor2hl7 fetch`"
            ]
        suffix = f": {'; '.join(map(str, reasons))}" if reasons else ""
        raise ValueError(f"transaction specification is not build-ready{suffix}")
    manifest = load_json(release_dir / "manifest.json")
    resources = manifest.get("resources", {})
    role_map = closure.get("resource_roles", {})
    records: list[ArtifactRecord] = []
    canonical: dict[tuple[str, ...], ArtifactRecord] = {}
    for key in closure.get(f"{role}_resources", []):
        entry = resources.get(key, {}) if isinstance(resources, Mapping) else {}
        roles = role_map.get(key, []) if isinstance(role_map, Mapping) else []
        if not isinstance(entry, Mapping):
            continue
        record = artifact_record(release_dir, str(key), entry, roles)
        resolved = record.get("resolved", {})
        canonical_key = (
            str(resolved.get("type") or ""),
            str(resolved.get("id") or ""),
            str(resolved.get("effective_date") or ""),
            str(resolved.get("project") or ""),
            str(resolved.get("api_base") or ""),
            str(resolved.get("context_id") or ""),
            str(resolved.get("context_effective_date") or ""),
        )
        # Failed/unresolved requests have no trustworthy canonical identity and
        # remain independent diagnostics.
        if record.get("status") != "ok" or not canonical_key[1]:
            records.append(record)
            continue
        current = canonical.get(canonical_key)
        if current is None:
            canonical[canonical_key] = record
            records.append(record)
            continue
        current["aliases"] = list(dict.fromkeys(
            list(current.get("aliases", [])) + list(record.get("aliases", []))
        ))
        current["requests"] = list(current.get("requests", [])) + list(
            record.get("requests", [])
        )
        current["forms"].update(record.get("forms", {}))
        current["roles"] = list(dict.fromkeys(
            list(current.get("roles", [])) + list(record.get("roles", []))
        ))
        current["required"] = bool(current.get("required") or record.get("required"))
    return records


def transaction_record(release_dir: Path, transaction_dir: Path) -> ArtifactRecord:
    """Combine the separately cached transaction source and analysis entries."""
    manifest = load_json(release_dir / "manifest.json")
    resources = manifest.get("resources", {})
    source_entry: Mapping[str, Any] = {}
    analysis_key = ""
    analysis_entry: Mapping[str, Any] = {}
    for key, raw in (resources.items() if isinstance(resources, Mapping) else ()):
        if not isinstance(raw, Mapping):
            continue
        relative = str(raw.get("file") or "")
        if relative == str((transaction_dir / "transaction.source.xml").relative_to(release_dir)):
            source_entry = raw
        elif relative == str((transaction_dir / "transaction.xml").relative_to(release_dir)):
            analysis_key, analysis_entry = str(key), raw
    if not analysis_key:
        raise ValueError("selected transaction analysis form is absent from the manifest")
    record = artifact_record(release_dir, analysis_key, analysis_entry, ["structure"])
    source = _form(release_dir, "source", source_entry)
    if source is not None:
        record["forms"]["source"] = source
    problems = artifact_problems(record)
    if "source" not in record["forms"]:
        problems.append(f"{analysis_key}: required source form is unavailable")
    if problems:
        raise ValueError("; ".join(problems))
    return record


def form_paths(
    records: Iterable[Mapping[str, Any]],
    *,
    kinds: Iterable[str] = (),
    form: str = "analysis",
) -> list[Path]:
    wanted = set(kinds)
    paths: list[Path] = []
    for record in records:
        identity = record.get("resolved", {})
        if wanted and (
            not isinstance(identity, Mapping) or identity.get("type") not in wanted
        ):
            continue
        forms = record.get("forms", {})
        selected = forms.get(form, {}) if isinstance(forms, Mapping) else {}
        path = selected.get("path") if isinstance(selected, Mapping) else None
        if isinstance(path, Path) and path not in paths:
            paths.append(path)
    return paths
