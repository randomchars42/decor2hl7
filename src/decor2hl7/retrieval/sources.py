"""Data-driven source hints for references that omit repository identity."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping


SOURCE_MODES = {"builtin", "waiver"}
RESOLUTION_FIELDS = ("effective_date", "project", "api_base", "publication_url")
EXTERNAL_FIELDS = (
    "mode", "artifact", "source_url", "source_version", "completeness",
    "license", "sha256", "reason",
)


def _read(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_source_hints(override: Path | None = None) -> dict[str, dict[str, str]]:
    bundled = json.loads(
        files("decor2hl7.retrieval").joinpath("sources.json").read_text(encoding="utf-8")
    )
    configured = _read(override)
    result: dict[str, dict[str, str]] = {}
    for source in (bundled, configured):
        artifacts = source.get("artifacts", {}) if isinstance(source, Mapping) else {}
        if not isinstance(artifacts, Mapping):
            raise ValueError("source hints 'artifacts' must contain an object")
        for key, value in artifacts.items():
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
                    f"supported phase-1 modes are {sorted(SOURCE_MODES)}"
                )
            if mode == "builtin":
                for required in ("artifact", "sha256", "completeness"):
                    if not normalized.get(required):
                        raise ValueError(
                            f"builtin source hint {key!r} requires {required!r}"
                        )
            if mode == "waiver" and not normalized.get("reason"):
                raise ValueError(f"waiver source hint {key!r} requires 'reason'")
            result[str(key)] = normalized
    return result


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
    return result


def builtin_payload(artifact: Mapping[str, str]) -> bytes:
    """Read one reviewed package-local supplement without network access."""
    relative = PurePosixPath(str(artifact.get("artifact") or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe builtin artifact path: {relative}")
    resource = files("decor2hl7.retrieval").joinpath(*relative.parts)
    if not resource.is_file():
        raise ValueError(f"builtin artifact is missing from the package: {relative}")
    return resource.read_bytes()
