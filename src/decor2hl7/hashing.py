"""Stable content digests shared by compilation and runtime admission."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
        return digest.hexdigest()
