"""Workspace layout, selection state and JSON helpers.

Selection is deliberately independent from filesystem creation:

* ``init`` creates only the top-level workspace and ``decor2hl7.json``.
* ``set-version KEY`` and ``set-transaction KEY`` only update selection state.
* commands that create artifacts create the directories they own lazily.

Specification releases are the acquisition/cache scope. Transactions are the
model/mapping/site/test/output scope within a release.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal, Mapping, overload

SETTINGS = "decor2hl7.json"
# ``config`` is intentionally reserved for acquisition-wide configuration
# such as sources.json.  Shareable CDA mappings, site-specific input mappings,
# and generated test fixtures have different owners and lifecycles.
TOP_LEVEL = ("spec", "model", "config", "mapping", "site", "test", "out", "state")


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


def init_workspace(
    root: Path,
    prefix: str = "aktin-",
    language: str = "de-DE",
    output_language: str = "en",
) -> Path:
    from .i18n import normalize_output_language

    output_language = normalize_output_language(output_language)
    root.mkdir(parents=True, exist_ok=True)
    for name in TOP_LEVEL:
        (root / name).mkdir(parents=True, exist_ok=True)
    path = settings_path(root)
    if path.exists():
        current = load_json(path)
        current.setdefault("prefix", prefix)
        current.setdefault("language", language)
        output = current.setdefault("output", {})
        if not isinstance(output, dict):
            raise ValueError("workspace output configuration must be an object")
        output.setdefault("language", output_language)
        current.setdefault("network", {"ipv4": True})
        current.setdefault("api", {"base_url": "https://art-decor.org/exist/apps/api"})
        current.setdefault("release", None)
        current.setdefault("transaction", None)
        current.setdefault("input", {"directory": None})
    else:
        current = {
            "prefix": prefix,
            "language": language,
            "output": {"language": output_language},
            "network": {"ipv4": True},
            "api": {"base_url": "https://art-decor.org/exist/apps/api"},
            "release": None,
            "transaction": None,
            "input": {"directory": None},
        }
    write_json(path, current)
    return path


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
        raise ValueError("no release selected; run `decor2hl7 list-versions` and `decor2hl7 set-version <KEY>`")
    current["transaction"] = dict(transaction)
    write_json(settings_path(root), current)


def selected_release(root: Path) -> dict[str, Any]:
    release = load_settings(root).get("release")
    if not isinstance(release, dict) or not release.get("key") or not release.get("date"):
        raise ValueError("no release selected; run `decor2hl7 list-versions` and `decor2hl7 set-version <KEY>`")
    return dict(release)


def selected_transaction(root: Path) -> dict[str, Any]:
    transaction = load_settings(root).get("transaction")
    if not isinstance(transaction, dict) or not transaction.get("key") or not transaction.get("id"):
        raise ValueError("no transaction selected; run `decor2hl7 list-transactions` and `decor2hl7 set-transaction <KEY>`")
    return dict(transaction)


def _slug(value: str) -> str:
    value = value.replace("ß", "ss").replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "item"


def release_key(label: str, date: str = "") -> str:
    """Stable human-facing key printed by ``list-versions``.

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


@overload
def input_dir(
    root: Path,
    override: str | Path | None = None,
    *,
    required: Literal[True] = True,
) -> Path: ...


@overload
def input_dir(
    root: Path,
    override: str | Path | None = None,
    *,
    required: Literal[False],
) -> Path | None: ...


def input_dir(
    root: Path,
    override: str | Path | None = None,
    *,
    required: bool = True,
) -> Path | None:
    """Resolve the external CSV input root.

    Command-line input wins over the optional deployment default in
    ``decor2hl7.json``.
    The path is external to the decor2hl7 workspace and is never created here.
    """
    explicit = override is not None
    value: str | Path | None = override
    if value is None:
        configured = load_settings(root).get("input", {})
        if isinstance(configured, Mapping):
            value = configured.get("directory")
    if value in (None, ""):
        if required:
            raise ValueError(
                "no input directory configured; pass `--input PATH` or set "
                "`input.directory` in decor2hl7.json"
            )
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        # Explicit CLI paths follow ordinary shell semantics; a stored relative
        # The stored deployment default is anchored at its owning workspace.
        path = path.resolve() if explicit else (root / path).resolve()
    else:
        path = path.resolve()
    if required and not path.is_dir():
        raise ValueError(f"input directory does not exist or is not a directory: {path}")
    return path


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


def release_mapping_dir(root: Path, release: Mapping[str, Any] | None = None) -> Path:
    release = dict(release or selected_release(root))
    return root / "mapping" / str(release["key"])


def transaction_mapping_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    transaction = dict(transaction or selected_transaction(root))
    return release_mapping_dir(root, release) / str(transaction["key"])


def release_site_dir(root: Path, release: Mapping[str, Any] | None = None) -> Path:
    release = dict(release or selected_release(root))
    return root / "site" / str(release["key"])


def transaction_site_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    transaction = dict(transaction or selected_transaction(root))
    return release_site_dir(root, release) / str(transaction["key"])


def transaction_test_dir(
    root: Path,
    release: Mapping[str, Any] | None = None,
    transaction: Mapping[str, Any] | None = None,
) -> Path:
    release = dict(release or selected_release(root))
    transaction = dict(transaction or selected_transaction(root))
    return root / "test" / str(release["key"]) / str(transaction["key"])


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
