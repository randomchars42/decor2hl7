"""Data-driven source hints for references that omit repository identity."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping


SOURCE_MODES = {"alias", "builtin", "waiver"}
SOURCE_KINDS = {"dataset", "concept", "template", "valueset", "codesystem"}
RESOLUTION_FIELDS = ("effective_date", "project", "api_base", "publication_url")
EXTERNAL_FIELDS = (
    "mode", "artifact", "source_url", "source_version", "completeness",
    "license", "sha256", "reason", "alias_of",
)


class SourceHints(dict[str, dict[str, str]]):
    """Artifact hints plus validated top-level resolution configuration."""

    oid_owners: dict[str, str]
    configured_artifacts: frozenset[str]
    configured_oid_owners: frozenset[str]

    def __init__(
        self,
        *args: Any,
        oid_owners: Mapping[str, str] | None = None,
        configured_artifacts: set[str] | None = None,
        configured_oid_owners: set[str] | None = None,
    ) -> None:
        super().__init__(*args)
        self.oid_owners = dict(oid_owners or {})
        self.configured_artifacts = frozenset(configured_artifacts or set())
        self.configured_oid_owners = frozenset(configured_oid_owners or set())


def _read(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _artifact_key(value: str, *, label: str) -> tuple[str, str, str]:
    head, separator, effective = value.partition("@")
    kind, colon, identifier = head.partition(":")
    if not colon or kind not in SOURCE_KINDS or not identifier:
        raise ValueError(
            f"{label} must use kind:id or kind:id@effectiveDate with a supported kind"
        )
    return kind, identifier, effective


def load_source_hints(override: Path | None = None) -> SourceHints:
    bundled = json.loads(
        files("decor2hl7.retrieval").joinpath("sources.json").read_text(encoding="utf-8")
    )
    configured = _read(override)
    result: dict[str, dict[str, str]] = {}
    oid_owners: dict[str, str] = {}
    configured_artifacts: set[str] = set()
    configured_oid_owners: set[str] = set()
    for source_index, source in enumerate((bundled, configured)):
        configured_source = source_index == 1
        artifacts = source.get("artifacts", {}) if isinstance(source, Mapping) else {}
        if not isinstance(artifacts, Mapping):
            raise ValueError("source hints 'artifacts' must contain an object")
        for key, value in artifacts.items():
            key = str(key)
            _artifact_key(key, label="source hint key")
            if not isinstance(value, Mapping):
                raise ValueError(f"source hint {key!r} must contain an object")
            normalized = {
                str(name): str(item)
                for name, item in value.items()
                if item not in (None, "")
            }
            mode = normalized.get("mode", "")
            if mode and mode not in SOURCE_MODES:
                raise ValueError(
                    f"source hint {key!r} has unsupported mode {mode!r}; "
                    f"supported modes are {sorted(SOURCE_MODES)}"
                )
            if mode == "alias":
                alias_of = normalized.get("alias_of", "")
                if not alias_of or not normalized.get("reason"):
                    raise ValueError(
                        f"alias source hint {key!r} requires 'alias_of' and 'reason'"
                    )
                key_kind, _, _ = _artifact_key(key, label="source hint key")
                alias_kind, _, _ = _artifact_key(
                    alias_of, label=f"alias_of for source hint {key!r}"
                )
                if alias_kind != key_kind:
                    raise ValueError(
                        f"alias source hint {key!r} must target the same artifact kind"
                    )
                if alias_of == key:
                    raise ValueError(f"alias source hint {key!r} cannot refer to itself")
                forbidden = {
                    "artifact", "source_url", "source_version", "completeness",
                    "license", "sha256",
                } & normalized.keys()
                if forbidden:
                    raise ValueError(
                        f"alias source hint {key!r} cannot contain builtin/waiver "
                        f"fields {sorted(forbidden)}"
                    )
            if mode == "builtin":
                for required in ("artifact", "sha256", "completeness"):
                    if not normalized.get(required):
                        raise ValueError(
                            f"builtin source hint {key!r} requires {required!r}"
                        )
            if mode == "waiver" and not normalized.get("reason"):
                raise ValueError(f"waiver source hint {key!r} requires 'reason'")
            result[key] = normalized
            if configured_source:
                configured_artifacts.add(key)

        owners = source.get("oid_owners", {}) if isinstance(source, Mapping) else {}
        if not isinstance(owners, Mapping):
            raise ValueError("source hints 'oid_owners' must contain an object")
        for oid, project in owners.items():
            oid_text, project_text = str(oid).strip(), str(project).strip()
            if not oid_text or not project_text:
                raise ValueError("source hint oid_owners keys and values must be non-empty")
            oid_owners[oid_text] = project_text
            if configured_source:
                configured_oid_owners.add(oid_text)
    return SourceHints(
        result,
        oid_owners=oid_owners,
        configured_artifacts=configured_artifacts,
        configured_oid_owners=configured_oid_owners,
    )


def apply_source_hint(
    artifact: Mapping[str, str],
    hints: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """Fill missing resolution properties without replacing explicit XML data."""
    result = dict(artifact)
    base = f"{artifact.get('kind', '')}:{artifact.get('id', '')}"
    effective = artifact.get("effective_date") or ""
    hint = hints.get(f"{base}@{effective}") if effective else None
    if hint is None:
        hint = hints.get(base, {})
    for name in RESOLUTION_FIELDS:
        if not result.get(name) and hint.get(name):
            result[name] = str(hint[name])
    # External acquisition metadata describes the catalog entry itself.  XML
    # references do not carry these properties, so a matching exact artifact
    # hint may add them without changing the requested artifact identity.
    for name in EXTERNAL_FIELDS:
        if hint.get(name):
            result[name] = str(hint[name])
    if hint:
        result["source_hint"] = f"{base}@{effective}" if effective and f"{base}@{effective}" in hints else base
        configured = getattr(hints, "configured_artifacts", frozenset())
        result["source_hint_origin"] = (
            "configured" if result["source_hint"] in configured else "bundled"
        )
    return result


def resolve_alias(
    artifact: Mapping[str, str],
    hints: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """Resolve one reviewed identity correction while retaining its provenance."""
    hinted = apply_source_hint(artifact, hints)
    if hinted.get("mode") != "alias":
        return hinted
    kind, identifier, effective = _artifact_key(
        hinted.get("alias_of", ""), label="alias_of"
    )
    corrected = {
        str(key): str(value)
        for key, value in artifact.items()
        if key not in RESOLUTION_FIELDS
        and key not in EXTERNAL_FIELDS
        and key not in {"source_hint", "source_hint_origin"}
    }
    corrected.update({"kind": kind, "id": identifier, "effective_date": effective})
    corrected = apply_source_hint(corrected, hints)
    corrected["alias_requested_key"] = str(hinted.get("source_hint") or "")
    corrected["alias_reason"] = str(hinted.get("reason") or "")
    corrected["alias_source_hint_origin"] = str(
        hinted.get("source_hint_origin") or "bundled"
    )
    return corrected


def builtin_payload(artifact: Mapping[str, str]) -> bytes:
    """Read one reviewed package-local supplement without network access."""
    relative = PurePosixPath(str(artifact.get("artifact") or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe builtin artifact path: {relative}")
    resource = files("decor2hl7.retrieval").joinpath(*relative.parts)
    if not resource.is_file():
        raise ValueError(f"builtin artifact is missing from the package: {relative}")
    return resource.read_bytes()
