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
ArtifactFormName = Literal[
    "source", "analysis", "expansion", "expansion-evidence",
]
DependencyRole = Literal[
    "structure", "formal-terminology", "expansion-support",
    "mapping-evidence", "display-evidence", "association-endpoint",
    "formal-origin", "template-prototype", "prototype-support",
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
    resolution: dict[str, Any]


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
    result: ArtifactIdentity = {}
    if identity.get("type") is not None:
        result["type"] = str(identity["type"])
    if identity.get("id") is not None:
        result["id"] = str(identity["id"])
    if identity.get("effective_date") is not None:
        result["effective_date"] = str(identity["effective_date"])
    if identity.get("project") is not None:
        result["project"] = str(identity["project"])
    if identity.get("api_base") is not None:
        result["api_base"] = str(identity["api_base"])
    if identity.get("context_id") is not None:
        result["context_id"] = str(identity["context_id"])
    if identity.get("context_effective_date") is not None:
        result["context_effective_date"] = str(
            identity["context_effective_date"]
        )
    return result


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
            "source_hint_origin": str(entry.get("source_hint_origin") or ""),
            "publication_url": str(entry.get("publication_url") or ""),
            "origin": str(entry.get("origin") or "art-decor"),
            "source_url": str(entry.get("source_url") or ""),
            "source_version": str(entry.get("source_version") or ""),
            "completeness": str(entry.get("completeness") or ""),
            "reason": str(entry.get("reason") or ""),
            "expansion_warning": str(entry.get("expansion_warning") or ""),
            "owner": str(entry.get("owner") or resolved.get("project") or ""),
            "owner_source": str(entry.get("owner_source") or ""),
            "identity_corrected": bool(entry.get("identity_corrected")),
            "alias_of": str(entry.get("alias_of") or ""),
            "projects_considered": list(entry.get("projects_considered", [])),
            "resolution_attempts": list(entry.get("resolution_attempts", [])),
        },
    }


def artifact_integrity_problems(record: Mapping[str, Any]) -> list[str]:
    """Return contradictions in an artifact that claims to be usable.

    An unavailable dependency is not an integrity problem: the compiler can
    omit it and report a degraded build.  A successful record with the wrong
    identity, an absent analysis form, or a missing cached file is different;
    using it would make the build untrustworthy and therefore remains fatal.
    """
    problems: list[str] = []
    key = str(record.get("request_key") or "artifact")
    requested = record.get("requested", {})
    resolved = record.get("resolved", {})
    forms = record.get("forms", {})
    if not isinstance(requested, Mapping) or not isinstance(resolved, Mapping):
        return [f"{key}: malformed identity"]
    if record.get("status") == "ok":
        corrected = bool(
            isinstance(record.get("resolution"), Mapping)
            and record.get("resolution", {}).get("identity_corrected")
        )
        resolved_date = str(resolved.get("effective_date") or "")
        requests = record.get("requests", [requested])
        for request in (requests if isinstance(requests, list) else [requested]):
            if not isinstance(request, Mapping):
                continue
            requested_date = str(request.get("effective_date") or "")
            if not corrected and requested_date and requested_date != resolved_date:
                problems.append(
                    f"{key}: requested static revision {requested_date}, "
                    f"resolved {resolved_date or 'unknown'}"
                )
            if (
                not corrected
                and request.get("id")
                and resolved.get("id")
                and request.get("id") != resolved.get("id")
            ):
                problems.append(
                    f"{key}: requested id {request.get('id')}, resolved {resolved.get('id')}"
                )
    if record.get("required") and record.get("status") == "ok" and (
        not isinstance(forms, Mapping) or "analysis" not in forms
    ):
        problems.append(f"{key}: successful artifact has no analysis form")
    if record.get("status") == "ok":
        for name, form in (forms.items() if isinstance(forms, Mapping) else ()):
            if isinstance(form, Mapping):
                path = form.get("path")
                if isinstance(path, Path) and not path.is_file():
                    problems.append(f"{key}[{name}]: missing file {path}")
    return problems


def artifact_unavailable_reasons(record: Mapping[str, Any]) -> list[str]:
    """Explain why a dependency cannot contribute to a degraded build."""
    key = str(record.get("request_key") or "artifact")
    status = str(record.get("status") or "unknown")
    reasons: list[str] = []
    resolution = record.get("resolution", {})
    reason = str(resolution.get("reason") or "") if isinstance(resolution, Mapping) else ""
    completeness = (
        str(resolution.get("completeness") or "")
        if isinstance(resolution, Mapping) else ""
    )
    if status == "waived":
        reasons.append(
            f"{key}: external artifact absence is provisionally waived"
            + (f" ({reason})" if reason else "")
        )
    elif status == "partial":
        reasons.append(
            f"{key}: external artifact is only {completeness or 'partial'}"
        )
    if status != "ok":
        if status not in {"waived", "partial"}:
            reasons.append(f"{key}: artifact status is {status}")
    forms = record.get("forms", {})
    analysis = forms.get("analysis", {}) if isinstance(forms, Mapping) else {}
    path = analysis.get("path") if isinstance(analysis, Mapping) else None
    if status == "ok" and not isinstance(path, Path):
        reasons.append(f"{key}: analysis form is unavailable")
    return reasons


def artifact_problems(record: Mapping[str, Any]) -> list[str]:
    """Return the strict artifact contract used by explicit validators."""
    problems = artifact_integrity_problems(record)
    if record.get("required"):
        problems.extend(artifact_unavailable_reasons(record))
    return problems


def closure_records(
    release_dir: Path,
    transaction_dir: Path,
    role: str = "build",
) -> list[ArtifactRecord]:
    closure = load_json(transaction_dir / "closure.json")
    crawl_complete = closure.get("crawl_complete")
    if not crawl_complete or closure.get("interrupted") or closure.get("truncated"):
        raise ValueError("transaction crawl is incomplete; rerun `decor2hl7 fetch`")
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
        alias_keys = [str(key)]
        alias_entry = entry
        seen = {str(key)}
        while entry.get("status") == "alias":
            target_key = str(entry.get("alias_of") or "")
            if not target_key or target_key in seen or not isinstance(resources, Mapping):
                break
            target = resources.get(target_key, {})
            if not isinstance(target, Mapping):
                break
            seen.add(target_key)
            alias_keys.append(target_key)
            entry = target
        if len(alias_keys) > 1:
            merged = dict(entry)
            merged["requested_effective_date"] = alias_entry.get(
                "requested_effective_date", "dynamic"
            )
            alias_identity = alias_entry.get("identity", {})
            if isinstance(alias_identity, Mapping):
                merged["declared_project"] = alias_identity.get("project", "")
            merged["identity_corrected"] = True
            merged["alias_of"] = alias_keys[-1]
            merged["reason"] = alias_entry.get("reason", "")
            merged["source_hint"] = alias_entry.get("source_hint", "")
            merged["source_hint_origin"] = alias_entry.get(
                "source_hint_origin", ""
            )
            record = artifact_record(release_dir, str(key), merged, roles)
            record["aliases"] = alias_keys
        else:
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
        current_resolution = current.get("resolution", {})
        record_resolution = record.get("resolution", {})
        if (
            isinstance(current_resolution, dict)
            and isinstance(record_resolution, Mapping)
        ):
            if record_resolution.get("identity_corrected"):
                current_resolution["identity_corrected"] = True
            for name in (
                "alias_of", "reason", "source_hint", "source_hint_origin",
                "expansion_warning",
            ):
                if record_resolution.get(name):
                    current_resolution[name] = record_resolution[name]
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
    if source_entry.get("status") != "ok":
        problems.append(
            f"{analysis_key}: required source artifact status is "
            f"{source_entry.get('status') or 'unknown'}"
        )
    if "source" not in record["forms"]:
        problems.append(f"{analysis_key}: required source form is unavailable")
    elif not record["forms"]["source"]["path"].is_file():
        problems.append(
            f"{analysis_key}[source]: missing file "
            f"{record['forms']['source']['path']}"
        )
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
        if isinstance(path, Path) and path.is_file() and path not in paths:
            paths.append(path)
    return paths
