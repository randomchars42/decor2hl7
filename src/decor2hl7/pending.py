"""Validated current-format metadata for immutable pending documents."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import re
from typing import NoReturn, TypedDict, TypeGuard

from .contracts import JsonObject, is_json
from .i18n import message as _msg
from .hashing import sha256_file
from .workspace import load_json


class DocumentId(TypedDict):
    root: str
    extension: str


class DocumentIdentity(TypedDict):
    document_id: DocumentId
    set_id: DocumentId
    version: int


class PendingDocument(TypedDict):
    key: str
    state_key: str
    fingerprint: str
    document_version: int
    release: str
    transaction: JsonObject
    source_status: str
    document_id: DocumentId
    set_id: DocumentId
    previous_document: DocumentIdentity | None
    prepared_at: str
    payload_sha256: str


def _identity(value: object) -> TypeGuard[DocumentId]:
    return (
        isinstance(value, dict)
        and set(value) == {"root", "extension"}
        and all(isinstance(item, str) and item for item in value.values())
    )


def _pending_document(value: object, path: Path) -> TypeGuard[PendingDocument]:
    if not is_json(value) or not isinstance(value, dict):
        return False

    def reject(reason: str) -> NoReturn:
        raise ValueError(_msg('ui.pending_invalid', path=path, reason=reason))
    strings: dict[str, str] = {}
    for key in ("key", "state_key", "release", "source_status", "prepared_at"):
        item = value.get(key)
        if not isinstance(item, str) or not item:
            reject(_msg('ui.pending_field_missing', key=key))
        strings[key] = item
    for key in ("fingerprint", "payload_sha256"):
        item = value.get(key)
        if not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None:
            reject(_msg('ui.pending_field_missing', key=key))
    version = value.get("document_version")
    if type(version) is not int or version < 1:
        reject(_msg('ui.pending_version_invalid'))
    for key in ("document_id", "set_id"):
        if not _identity(value.get(key)):
            reject(_msg('ui.pending_field_invalid', key=key))
    tx = value.get("transaction")
    if (
        not isinstance(tx, dict)
        or not isinstance(tx.get("id"), str) or not tx["id"]
        or strings["state_key"] != f"{tx['id']}::{strings['key']}"
    ):
        reject(_msg('ui.pending_transaction_invalid'))
    if "previous_document" not in value:
        reject(_msg('ui.pending_previous_missing'))
    previous = value["previous_document"]
    if version == 1:
        if previous is not None or value["source_status"] != "NEW":
            reject(_msg('ui.pending_predecessor_unexpected'))
    elif (
        not isinstance(previous, dict)
        or type(previous.get("version")) is not int
        or previous.get("version") != version - 1
        or not _identity(previous.get("document_id"))
        or previous.get("set_id") != value["set_id"]
        or strings["source_status"] != "CHANGED"
    ):
        reject(_msg('ui.pending_lineage_invalid'))
    try:
        prepared = dt.datetime.fromisoformat(strings["prepared_at"])
    except ValueError:
        reject(_msg('ui.pending_timestamp_invalid'))
    if prepared.tzinfo is None:
        reject(_msg('ui.pending_timezone_required'))
    if value["payload_sha256"] != sha256_file(path):
        reject(_msg('ui.pending_checksum_mismatch'))
    return True


def read_pending(path: Path) -> PendingDocument:
    """Reject incomplete metadata before reuse, recovery, status or handover."""
    value: object = load_json(path.with_suffix(".json"))
    if _pending_document(value, path):
        return value
    raise ValueError(_msg(
        'ui.pending_invalid', path=path, reason=_msg('ui.pending_object_required'),
    ))
