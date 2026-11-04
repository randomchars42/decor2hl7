"""Admission of the exact reviewed compilation and mapping bundle."""
from __future__ import annotations

from .i18n import message as _msg

from pathlib import Path
from typing import Any, Mapping

from .hashing import json_digest
from .workspace import load_json


def mapping_lock(release: Mapping[str, Any], transaction: Mapping[str, Any], model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "release": {key: release.get(key) for key in ("key", "date")},
        "transaction": {key: transaction.get(key) for key in ("key", "id", "effective_date")},
        "model_sha256": json_digest(model), "cda_sha256": json_digest(cda),
        "mapping_sha256_at_creation": json_digest(mapping),
    }


def admit_mapping(path: Path, release: Mapping[str, Any], transaction: Mapping[str, Any], model: Mapping[str, Any], cda: Mapping[str, Any]) -> None:
    lock_path = path.parent / "mapping-lock.json"
    if not lock_path.is_file():
        raise ValueError(_msg('ui.lock_missing'))
    lock = load_json(lock_path)
    if type(lock.get("version")) is not int or lock["version"] != 1:
        raise ValueError(_msg('ui.lock_version'))
    expected = mapping_lock(release, transaction, model, cda, {})
    for key in ("release", "transaction", "model_sha256", "cda_sha256"):
        if lock.get(key) != expected[key]:
            raise ValueError(_msg('ui.lock_mismatch', key=key))
    meta = model.get("meta", {})
    for key, selected in (("transaction_id", transaction.get("id")), ("transaction_effective_date", transaction.get("effective_date"))):
        if key in meta and meta[key] != selected:
            raise ValueError(_msg('ui.model_transaction_mismatch', key=key))
