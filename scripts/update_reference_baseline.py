#!/usr/bin/env python3
"""Refresh the committed mapping guard from the local reference workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RELEASE = "2026.1.2"
TRANSACTION = "notaufnahmeregister--60"


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    workspace = repository.parent / "test-workplace"
    selection = load(workspace / "decor2hl7.json")
    if (
        selection.get("release", {}).get("key") != RELEASE
        or selection.get("transaction", {}).get("key") != TRANSACTION
    ):
        raise ValueError(
            "reference workspace selection does not match "
            f"{RELEASE}/{TRANSACTION}"
        )
    audit = load(
        workspace / "model" / RELEASE / TRANSACTION / "mapping-audit.json"
    )
    counts = audit.get("summary", {}).get("coverage_headline")
    if not isinstance(counts, dict):
        raise ValueError("reference mapping audit has no coverage_headline summary")
    fields = {
        str(path): {"selected": True}
        for path, detail in audit.get("fields", {}).items()
        if isinstance(detail, dict) and detail.get("selected") is not None
    }
    fixture = {
        "version": 1,
        "note": f"{RELEASE}/{TRANSACTION} mapped-field regression baseline",
        "coverage_headline": counts,
        "fields": fields,
    }
    destination = (
        repository / "tests" / "fixtures" / "reference-mapping-audit.json"
    )
    destination.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {destination}")


if __name__ == "__main__":
    main()
