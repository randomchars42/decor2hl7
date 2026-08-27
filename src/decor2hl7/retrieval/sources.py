"""Data-driven source hints for references that omit repository identity."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping


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
            result[str(key)] = {
                str(name): str(item)
                for name, item in value.items()
                if item not in (None, "")
            }
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
    for name in ("effective_date", "project", "api_base", "publication_url"):
        if not result.get(name) and hint.get(name):
            result[name] = str(hint[name])
    if hint:
        result["source_hint"] = f"{base}@{effective}" if effective and f"{base}@{effective}" in hints else base
    return result
