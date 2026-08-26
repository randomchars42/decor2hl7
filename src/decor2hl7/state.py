"""Persistent sent-document state and change detection."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .workspace import load_json, write_json


def fingerprint(record: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> str:
    """Fingerprint document semantics, excluding diagnostic provenance."""
    if "values" in record or "instances" in record:
        def semantic_instances(raw: Any) -> dict[str, list[Any]]:
            result: dict[str, list[Any]] = {}
            if not isinstance(raw, Mapping):
                return result
            for repeat, rows in raw.items():
                if not isinstance(rows, list):
                    continue
                result[str(repeat)] = [
                    {
                        "key": row.get("key"),
                        "values": dict(row.get("values", {})),
                        "instances": semantic_instances(row.get("instances", {})),
                    } if isinstance(row, Mapping) else {}
                    for row in rows
                ]
            return result
        instance_values = semantic_instances(record.get("instances", {}))
        value: Any = {
            "values": record.get("values", {}),
            "instances": instance_values,
        }
    else:
        value = record
    if context is not None:
        value = {"record": value, "transformation": context}
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _index_path(state_dir: Path) -> Path:
    return state_dir / "index.json"


def load_state(state_dir: Path) -> dict[str, Any]:
    path = _index_path(state_dir)
    return load_json(path) if path.exists() else {"version": 1, "documents": {}}


def classify(state_dir: Path, key: str, digest: str) -> tuple[str, int]:
    previous = load_state(state_dir).get("documents", {}).get(key)
    if not previous:
        return "NEW", 1
    if previous.get("fingerprint") == digest:
        return "UNCHANGED", int(previous.get("document_version") or 1)
    return "CHANGED", int(previous.get("document_version") or 1) + 1


def record_sent(
    state_dir: Path,
    *,
    key: str,
    digest: str,
    document_version: int,
    file: str,
    spec_version: str,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_dir)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    entry = {
        "fingerprint": digest,
        "document_version": document_version,
        "sent_at": now,
        "file": file,
        "spec_version": spec_version,
    }
    state.setdefault("documents", {})[key] = entry
    write_json(_index_path(state_dir), state)
    with (state_dir / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"key": key, **entry}, ensure_ascii=False) + "\n")


def rotate(state_dir: Path, days: int) -> Path | None:
    history = state_dir / "history.jsonl"
    if not history.exists() or days <= 0:
        return None
    first_sent: dt.datetime | None = None
    try:
        with history.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                value = raw.get("sent_at")
                if value:
                    first_sent = dt.datetime.fromisoformat(str(value))
                break
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if first_sent is None:
        return None
    if first_sent.tzinfo is None:
        first_sent = first_sent.replace(tzinfo=dt.timezone.utc)
    age = dt.datetime.now(dt.timezone.utc) - first_sent.astimezone(dt.timezone.utc)
    if age < dt.timedelta(days=days):
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = state_dir / f"history-{stamp}.jsonl"
    history.rename(target)
    return target
