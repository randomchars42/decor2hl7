"""Workspace layout, selection state and JSON helpers.

Selection is deliberately independent from filesystem creation:

* ``init`` creates only the top-level workspace and ``aktin.json``.
* ``version set`` and ``transaction set`` only update selection state.
* commands that create artifacts create the directories they own lazily.

ART-DECOR releases are the acquisition/cache scope. Transactions are the
model/config/output scope within a release.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

SETTINGS = "aktin.json"
TOP_LEVEL = ("spec", "model", "config", "raw", "out", "state")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=False)
            handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try: os.unlink(tmp_name)
        except OSError: pass
        raise


def settings_path(root: Path) -> Path:
    return root / SETTINGS


def load_settings(root: Path) -> dict[str, Any]:
    path = settings_path(root)
    if not path.exists():
        raise ValueError(f"workspace is not initialized: missing {path}; run `decor2hl7 init`")
    return load_json(path)


def init_workspace(root: Path, prefix: str = "aktin-", language: str = "de-DE") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in TOP_LEVEL:
        (root / name).mkdir(parents=True, exist_ok=True)
    path = settings_path(root)
    if path.exists():
        current = load_json(path)
        current.setdefault("prefix", prefix)
        current.setdefault("language", language)
        current.setdefault("network", {"ipv4": True})
        current.setdefault("release", None)
        current.setdefault("transaction", None)
    else:
        current = {
            "prefix": prefix,
            "language": language,
            "network": {"ipv4": True},
            "release": None,
            "transaction": None,
        }
    write_json(path, current)
    return path


def update_settings(root: Path, **updates: Any) -> None:
    current = load_settings(root)
    current.update(updates)
    write_json(settings_path(root), current)


def set_release(root: Path, release: Mapping[str, Any]) -> None:
    current = load_settings(root)
    current["release"] = dict(release)
    # A transaction is selected *within* a release. Never silently carry it to
    # another release even if the transaction OID happens to exist there too.
    current["transaction"] = None
    write_json(settings_path(root), current)


def set_transaction(root: Path, transaction: Mapping[str, Any]) -> None:
    current = load_settings(root)
    if not current.get("release"):
        raise ValueError("no release selected; run `decor2hl7 versions list` and `decor2hl7 version set <key>`")
    current["transaction"] = dict(transaction)
    write_json(settings_path(root), current)


def selected_release(root: Path) -> dict[str, Any]:
    release = load_settings(root).get("release")
    if not isinstance(release, dict) or not release.get("key") or not release.get("date"):
        raise ValueError("no release selected; run `decor2hl7 versions list` and `decor2hl7 version set <key>`")
    return dict(release)


def selected_transaction(root: Path) -> dict[str, Any]:
    transaction = load_settings(root).get("transaction")
    if not isinstance(transaction, dict) or not transaction.get("key") or not transaction.get("id"):
        raise ValueError("no transaction selected; run `decor2hl7 transactions list` and `decor2hl7 transaction set <key>`")
    return dict(transaction)


def _slug(value: str) -> str:
    value = value.replace("ß", "ss").replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "item"


def release_key(label: str, date: str = "") -> str:
    """Stable human-facing key printed by ``versions list``.

    Version labels are normally already ideal keys (``2026.1.2``). A date is
    only appended when a label is unavailable.
    """
    return label.strip() or _slug(date)


def transaction_key(name: str, oid: str) -> str:
    """Stable readable transaction key, e.g. ``notaufnahmeregister--60``."""
    base = re.sub(r"\btransitionsversion\b", "", name, flags=re.IGNORECASE).strip()
    base = re.sub(r"\btransaction\b", "", base, flags=re.IGNORECASE).strip()
    slug = _slug(base or name)
    suffix = oid.rstrip(".").rsplit(".", 1)[-1] if oid else ""
    if suffix and re.fullmatch(r"[A-Za-z0-9_-]+", suffix):
        return f"{slug}--{suffix}"
    digest = hashlib.sha1(oid.encode("utf-8")).hexdigest()[:6] if oid else "unknown"
    return f"{slug}--{digest}"


def raw_dir(root: Path) -> Path:
    return root / "raw"


def state_dir(root: Path) -> Path:
    return root / "state"


def release_spec_dir(root: Path, release: Mapping[str, Any] | None = None) -> Path:
    release = dict(release or selected_release(root))
    return root / "spec" / str(release["key"])


def transaction_spec_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    release = dict(release or selected_release(root))
    transaction = dict(transaction or selected_transaction(root))
    return release_spec_dir(root, release) / "transactions" / str(transaction["key"])


def transaction_model_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    release = dict(release or selected_release(root))
    transaction = dict(transaction or selected_transaction(root))
    return root / "model" / str(release["key"]) / str(transaction["key"])


def release_config_dir(root: Path, release: Mapping[str, Any] | None = None) -> Path:
    release = dict(release or selected_release(root))
    return root / "config" / str(release["key"])


def transaction_config_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    transaction = dict(transaction or selected_transaction(root))
    return release_config_dir(root, release) / str(transaction["key"])


def transaction_out_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    release = dict(release or selected_release(root))
    transaction = dict(transaction or selected_transaction(root))
    return root / "out" / str(release["key"]) / str(transaction["key"])


def copy_if_missing(source: Path, destination: Path) -> bool:
    if destination.exists() or not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return True
