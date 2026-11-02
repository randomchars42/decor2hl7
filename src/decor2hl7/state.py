"""Transactional runtime state, document lineage, and run bookkeeping.

SQLite is the single production authority. The legacy ``index.json`` is
imported once when a workspace first opens the database; it is never written
again. Each delivered document is committed in its own transaction so a
process interruption cannot advance lineage past an unpublished artifact.
"""

from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping, TextIO

from .workspace import load_json


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  key TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  delivery_status TEXT NOT NULL,
  file TEXT NOT NULL,
  spec_version TEXT NOT NULL,
  document_root TEXT,
  document_extension TEXT,
  set_root TEXT,
  set_extension TEXT,
  delivered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
  key TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  fingerprint TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  file TEXT NOT NULL,
  spec_version TEXT NOT NULL,
  document_root TEXT,
  document_extension TEXT,
  set_root TEXT,
  set_extension TEXT,
  previous_document_root TEXT,
  previous_document_extension TEXT,
  delivered_at TEXT NOT NULL,
  PRIMARY KEY (key, document_version)
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  snapshot_path TEXT,
  snapshot_max_ts TEXT,
  summary TEXT,
  error TEXT
);
"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _database_path(state_dir: Path) -> Path:
    return state_dir / "state.sqlite"


def _connect(state_dir: Path) -> sqlite3.Connection:
    state_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(_database_path(state_dir), isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.executescript(_SCHEMA)
    _import_legacy_state(connection, state_dir)
    return connection


@contextmanager
def _opened(state_dir: Path) -> Iterator[sqlite3.Connection]:
    connection = _connect(state_dir)
    try:
        yield connection
    finally:
        connection.close()


def _import_legacy_state(connection: sqlite3.Connection, state_dir: Path) -> None:
    """Import the former JSON authority once without deleting it."""
    marker = connection.execute(
        "SELECT value FROM metadata WHERE key = 'legacy-index-imported'"
    ).fetchone()
    if marker is not None:
        return
    path = state_dir / "index.json"
    if path.exists():
        raw = load_json(path)
        for key, entry in raw.get("documents", {}).items():
            if not isinstance(entry, Mapping):
                continue
            delivered_at = str(entry.get("sent_at") or _now())
            connection.execute(
                """
                INSERT OR IGNORE INTO documents
                  (key, fingerprint, document_version, delivery_status, file,
                   spec_version, delivered_at)
                VALUES (?, ?, ?, 'sent', ?, ?, ?)
                """,
                (
                    str(key), str(entry.get("fingerprint") or ""),
                    int(entry.get("document_version") or 1),
                    str(entry.get("file") or ""),
                    str(entry.get("spec_version") or ""), delivered_at,
                ),
            )
    connection.execute(
        "INSERT INTO metadata (key, value) VALUES ('legacy-index-imported', ?)",
        (_now(),),
    )


def fingerprint(record: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> str:
    """Fingerprint normalized document semantics and transformation context."""
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
        value: Any = {
            "values": record.get("values", {}),
            "instances": semantic_instances(record.get("instances", {})),
        }
    else:
        value = record
    if context is not None:
        value = {"record": value, "transformation": context}
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_state(state_dir: Path) -> dict[str, Any]:
    """Return a compatibility view of the current SQLite document state."""
    with _opened(state_dir) as connection:
        rows = connection.execute(
            "SELECT * FROM documents ORDER BY key"
        ).fetchall()
    documents: dict[str, Any] = {}
    for row in rows:
        documents[str(row["key"])] = {
            "fingerprint": row["fingerprint"],
            "document_version": row["document_version"],
            "status": row["delivery_status"],
            "file": row["file"],
            "spec_version": row["spec_version"],
            "sent_at": row["delivered_at"],
            "document_id": {
                "root": row["document_root"],
                "extension": row["document_extension"],
            } if row["document_root"] or row["document_extension"] else None,
            "set_id": {
                "root": row["set_root"], "extension": row["set_extension"],
            } if row["set_root"] or row["set_extension"] else None,
        }
    return {"version": 2, "documents": documents}


def classify_loaded(current: Mapping[str, Any], key: str, digest: str) -> tuple[str, int]:
    documents = current.get("documents", {})
    previous = documents.get(key) if isinstance(documents, Mapping) else None
    if previous is None:
        return "NEW", 1
    if not isinstance(previous, Mapping):
        raise ValueError(f"invalid state entry for {key!r}")
    if previous.get("fingerprint") == digest:
        return "UNCHANGED", int(previous.get("document_version") or 1)
    return "CHANGED", int(previous.get("document_version") or 1) + 1


def classify(state_dir: Path, key: str, digest: str) -> tuple[str, int]:
    return classify_loaded(load_state(state_dir), key, digest)


def previous_document_loaded(
    current: Mapping[str, Any], key: str,
) -> dict[str, Any] | None:
    documents = current.get("documents", {})
    raw = documents.get(key) if isinstance(documents, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    document_id = raw.get("document_id")
    set_id = raw.get("set_id")
    if not isinstance(document_id, Mapping) or not document_id.get("extension"):
        return None
    if not isinstance(set_id, Mapping):
        return None
    return {
        "document_id": dict(document_id),
        "set_id": dict(set_id),
        "version": int(raw.get("document_version") or 1),
    }


def previous_document(state_dir: Path, key: str) -> dict[str, Any] | None:
    """Return the last delivered CDA identity for a stream, if recorded."""
    return previous_document_loaded(load_state(state_dir), key)


def record_delivery(
    state_dir: Path,
    *,
    key: str,
    digest: str,
    document_version: int,
    file: str,
    spec_version: str,
    status: str = "sent",
    document_id: Mapping[str, Any] | None = None,
    set_id: Mapping[str, Any] | None = None,
    previous: Mapping[str, Any] | None = None,
) -> None:
    """Commit one successfully handed-over document and its lineage."""
    now = _now()
    document_id = document_id or {}
    set_id = set_id or {}
    previous_id = (
        previous.get("document_id", {})
        if isinstance(previous, Mapping) and isinstance(previous.get("document_id"), Mapping)
        else {}
    )
    connection = _connect(state_dir)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT fingerprint, document_version FROM documents WHERE key = ?",
            (key,),
        ).fetchone()
        if (
            current is not None
            and current["fingerprint"] == digest
            and int(current["document_version"]) == document_version
        ):
            connection.execute("COMMIT")
            return
        expected_version = (
            int(current["document_version"]) + 1 if current is not None else 1
        )
        if document_version != expected_version:
            raise ValueError(
                f"document version {document_version} cannot follow committed "
                f"version {expected_version - 1} for {key!r}"
            )
        connection.execute(
            """
            INSERT INTO history
              (key, document_version, fingerprint, delivery_status, file,
               spec_version, document_root, document_extension, set_root,
               set_extension, previous_document_root,
               previous_document_extension, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key, document_version, digest, status, file, spec_version,
                document_id.get("root"), document_id.get("extension"),
                set_id.get("root"), set_id.get("extension"),
                previous_id.get("root"), previous_id.get("extension"), now,
            ),
        )
        connection.execute(
            """
            INSERT INTO documents
              (key, fingerprint, document_version, delivery_status, file,
               spec_version, document_root, document_extension, set_root,
               set_extension, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              fingerprint=excluded.fingerprint,
              document_version=excluded.document_version,
              delivery_status=excluded.delivery_status,
              file=excluded.file,
              spec_version=excluded.spec_version,
              document_root=excluded.document_root,
              document_extension=excluded.document_extension,
              set_root=excluded.set_root,
              set_extension=excluded.set_extension,
              delivered_at=excluded.delivered_at
            """,
            (
                key, digest, document_version, status, file, spec_version,
                document_id.get("root"), document_id.get("extension"),
                set_id.get("root"), set_id.get("extension"), now,
            ),
        )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def record_sent(
    state_dir: Path,
    *,
    key: str,
    digest: str,
    document_version: int,
    file: str,
    spec_version: str,
    document_id: Mapping[str, Any] | None = None,
    set_id: Mapping[str, Any] | None = None,
    previous: Mapping[str, Any] | None = None,
) -> None:
    """Backward-compatible name for an HTTP delivery commit."""
    record_delivery(
        state_dir, key=key, digest=digest,
        document_version=document_version, file=file,
        spec_version=spec_version, status="sent", document_id=document_id,
        set_id=set_id, previous=previous,
    )


def start_run(
    state_dir: Path, run_id: str, *, kind: str,
    snapshot_path: str | None = None,
) -> None:
    with _opened(state_dir) as connection:
        connection.execute(
            """
            INSERT INTO runs
              (run_id, kind, started_at, status, snapshot_path)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (run_id, kind, _now(), snapshot_path),
        )


def finish_run(
    state_dir: Path, run_id: str, *, status: str,
    summary: Mapping[str, Any] | None = None,
    snapshot_path: str | None = None,
    snapshot_max_ts: str | None = None,
    error: str | None = None,
) -> None:
    with _opened(state_dir) as connection:
        connection.execute(
            """
            UPDATE runs SET finished_at = ?, status = ?, snapshot_path = ?,
              snapshot_max_ts = ?, summary = ?, error = ?
            WHERE run_id = ?
            """,
            (
                _now(), status, snapshot_path, snapshot_max_ts,
                json.dumps(dict(summary or {}), ensure_ascii=False, sort_keys=True),
                error, run_id,
            ),
        )


def last_snapshot_max_ts(state_dir: Path) -> str | None:
    with _opened(state_dir) as connection:
        row = connection.execute(
            """
            SELECT snapshot_max_ts FROM runs
            WHERE status = 'completed' AND snapshot_max_ts IS NOT NULL
              AND snapshot_max_ts != ''
            ORDER BY finished_at DESC, rowid DESC LIMIT 1
            """
        ).fetchone()
    return str(row["snapshot_max_ts"]) if row is not None else None


def recent_runs(state_dir: Path, limit: int = 10) -> list[dict[str, Any]]:
    with _opened(state_dir) as connection:
        rows = connection.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@contextmanager
def workspace_lock(state_dir: Path) -> Iterator[None]:
    """Prevent overlapping state-changing runtime commands."""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / ".runtime.lock"
    handle: TextIO = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, BlockingIOError, OSError) as error:
            handle.close()
            raise RuntimeError(
                f"another runtime command is already active (lock: {lock_path})"
            ) from error
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} acquired={_now()}\n")
        handle.flush()
        yield
    finally:
        if not handle.closed:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def rotate(state_dir: Path, days: int) -> Path | None:
    """Checkpoint SQLite; document history is intentionally append-only."""
    del days
    with _opened(state_dir) as connection:
        connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    return None
