"""Bounded ODBC extraction into replayable, atomically published CSV snapshots.

This boundary performs no clinical normalization. Database scalar values are
serialized stably; the existing input layer remains the sole owner of null,
datatype, terminology, repeat, and mapping semantics.
"""

from __future__ import annotations

import csv
import datetime as dt
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

from .workspace import load_json, write_json

try:
    import pyodbc  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - dependency error is reported clearly
    pyodbc = None


MANIFEST = ".decor2hl7-snapshot.json"


def _source_config(site: Mapping[str, Any]) -> Mapping[str, Any]:
    value = site.get("source", {})
    if not isinstance(value, Mapping) or value.get("adapter") != "odbc":
        raise ValueError("site source.adapter must be 'odbc' for database extraction")
    return value


def _input_sources(site: Mapping[str, Any]) -> Mapping[str, Any]:
    input_config = site.get("input", {})
    sources = input_config.get("sources", {}) if isinstance(input_config, Mapping) else {}
    if not isinstance(sources, Mapping) or not sources:
        raise ValueError("site input.sources must configure at least one source")
    return sources


def _source_file(name: str, value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return str(value.get("file") or f"{name}.csv")
    return f"{name}.csv"


def _snapshot_destination(root: Path, name: str, value: Any) -> Path:
    relative = Path(_source_file(name, value))
    if (
        str(relative) in {"", "."} or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(
            f"input source {name!r} file must be a relative path inside the snapshot"
        )
    return root / relative


def _source_cardinality(value: Any) -> str:
    return str(value.get("cardinality") or "1:1") if isinstance(value, Mapping) else "1:1"


def _occurrence_columns(value: Any) -> tuple[str, ...]:
    occurrence = value.get("occurrence_keys", {}) if isinstance(value, Mapping) else {}
    if not isinstance(occurrence, Mapping):
        return ()
    return tuple(str(column) for column in occurrence.values())


def _order_columns(value: Any) -> tuple[str, ...]:
    raw = value.get("order_by", []) if isinstance(value, Mapping) else []
    return tuple(str(column) for column in raw) if isinstance(raw, list) else ()


def _join_column(value: Any, default: str) -> str:
    if isinstance(value, Mapping) and value.get("join_column"):
        return str(value["join_column"])
    return default


def _required_source_columns(value: Any) -> set[str]:
    result = {*_occurrence_columns(value), *_order_columns(value)}
    primary = value.get("primary", {}) if isinstance(value, Mapping) else {}
    if isinstance(primary, Mapping) and primary.get("column"):
        result.add(str(primary["column"]))
    return result


def _query_path(site_dir: Path, name: str, configured: Any) -> Path:
    value = str(configured or f"sql/{name}.sql")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (site_dir / path).resolve()


def _stable_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (bytes, bytearray, memoryview)):
        # ODBC binary columns are opaque octets, not encoded text. Hex keeps
        # hashes and other VARBINARY occurrence keys lossless and sortable.
        return bytes(value).hex()
    return str(value)


def _sort_value(value: Any) -> tuple[bool, str]:
    return value is None, _stable_scalar(value)


def _execute(connection: Any, sql: str, window_from: dt.date) -> tuple[list[str], list[dict[str, Any]]]:
    cursor = connection.cursor()
    try:
        cursor.execute(sql, (window_from,))
        if cursor.description is None:
            raise ValueError("source query returned no result columns")
        columns = [str(column[0]) for column in cursor.description]
        if len(columns) != len(set(columns)):
            raise ValueError("source query returned duplicate column names")
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return columns, rows
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"source query failed: {error}") from error
    finally:
        cursor.close()


def _connect(config: Mapping[str, Any]) -> Any:
    if pyodbc is None:
        raise ValueError("pyodbc is not installed; install decor2hl7 with its runtime dependencies")
    env_name = str(config.get("dsn_env") or "")
    connection_string = os.environ.get(env_name) if env_name else None
    if not connection_string:
        raise ValueError(
            f"environment variable {env_name!r} is not set to an ODBC DSN or connection string"
        )
    try:
        return pyodbc.connect(connection_string)
    except Exception as error:
        raise ValueError(f"could not connect to the source database: {error}") from error


def check_connection(site: Mapping[str, Any]) -> None:
    connection = _connect(_source_config(site))
    connection.close()


def query_errors(site: Mapping[str, Any], site_dir: Path) -> list[str]:
    """Return filesystem-level query contract errors without opening ODBC."""
    try:
        config = _source_config(site)
        sources = _input_sources(site)
    except ValueError as error:
        return [str(error)]
    queries = config.get("queries", {})
    if not isinstance(queries, Mapping):
        return ["site source.queries must be an object"]
    errors: list[str] = []
    for name in sources:
        if name not in queries:
            errors.append(f"site source.queries is missing {name!r}")
            continue
        path = _query_path(site_dir, str(name), queries[name])
        if not path.is_file():
            errors.append(f"source query file does not exist: {path}")
    return errors


def window_from(site: Mapping[str, Any], since: dt.date | None = None) -> dt.date:
    if since is not None:
        return since
    config = _source_config(site)
    days = int(config.get("window_days") or 90)
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date()


def extract(
    site: Mapping[str, Any], site_dir: Path, output: Path, *,
    since: dt.date | None = None, connection: Any | None = None,
) -> dict[str, Any]:
    """Execute every configured query once and atomically publish a snapshot."""
    config = _source_config(site)
    sources = _input_sources(site)
    input_config = site.get("input", {})
    if not isinstance(input_config, Mapping):
        raise ValueError("site input must be an object")
    case_source = str(input_config.get("case_source") or "")
    join_column = str(input_config.get("join_column") or "")
    if case_source not in sources:
        raise ValueError("site input.case_source must name a configured input source")
    if not join_column:
        raise ValueError("site input.join_column is required for ODBC extraction")
    if _source_cardinality(sources[case_source]) != "1:1":
        raise ValueError("site input.case_source must have cardinality 1:1")
    filenames = [_source_file(str(name), value) for name, value in sources.items()]
    if len(filenames) != len(set(filenames)):
        raise ValueError("configured input sources must use distinct snapshot files")

    queries = config.get("queries", {})
    if not isinstance(queries, Mapping):
        raise ValueError("site source.queries must be an object")
    unknown_queries = sorted(str(name) for name in queries if name not in sources)
    if unknown_queries:
        raise ValueError("site source.queries names unknown input sources: " + ", ".join(unknown_queries))
    missing_queries = sorted(str(name) for name in sources if name not in queries)
    if missing_queries:
        raise ValueError("site source.queries is missing: " + ", ".join(missing_queries))
    if output.exists():
        raise ValueError(f"snapshot output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    owns_connection = connection is None
    query_digests: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    maximum_timestamp: str | None = None
    case_keys: set[str] = set()
    try:
        if connection is None:
            connection = _connect(config)
        lower_bound = window_from(site, since)
        ordered_names = [case_source, *sorted(str(name) for name in sources if str(name) != case_source)]
        for source_name in ordered_names:
            source_spec = sources[source_name]
            path = _query_path(site_dir, source_name, queries[source_name])
            if not path.is_file():
                raise ValueError(f"source query file does not exist: {path}")
            sql = path.read_text(encoding="utf-8")
            query_digests[source_name] = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            columns, rows = _execute(connection, sql, lower_bound)
            source_join = _join_column(source_spec, join_column)
            if source_join not in columns:
                raise ValueError(f"source {source_name!r} does not return join column {source_join!r}")
            missing_columns = sorted(_required_source_columns(source_spec) - set(columns))
            if missing_columns:
                raise ValueError(
                    f"source {source_name!r} does not return configured occurrence/primary column(s): "
                    + ", ".join(missing_columns)
                )
            if _source_cardinality(source_spec) not in {"1:1", "1:n"}:
                raise ValueError(f"source {source_name!r} has invalid cardinality")

            keys = [_stable_scalar(row.get(source_join)) for row in rows]
            if any(not key for key in keys):
                raise ValueError(f"source {source_name!r} contains an empty join key")
            if _source_cardinality(source_spec) == "1:1" and len(keys) != len(set(keys)):
                raise ValueError(f"source {source_name!r} contains duplicate 1:1 join keys")
            if source_name == case_source:
                case_keys = set(keys)
                written_column = str(config.get("written_at_column") or "")
                if written_column not in columns:
                    raise ValueError(
                        f"case source {source_name!r} does not return written-at column {written_column!r}"
                    )
                timestamps = [
                    _stable_scalar(row.get(written_column))
                    for row in rows if row.get(written_column) is not None
                ]
                maximum_timestamp = max(timestamps) if timestamps else None
            else:
                orphans = sorted(set(keys) - case_keys)
                if orphans:
                    raise ValueError(
                        f"source {source_name!r} contains {len(orphans)} row key(s) absent from the case source"
                    )

            sort_columns = tuple(dict.fromkeys((
                source_join, *_order_columns(source_spec),
                *_occurrence_columns(source_spec),
            )))
            remaining = tuple(sorted(column for column in columns if column not in sort_columns))
            rows.sort(key=lambda row: tuple(_sort_value(row.get(column)) for column in (*sort_columns, *remaining)))
            destination = _snapshot_destination(temporary, source_name, source_spec)
            destination.parent.mkdir(parents=True, exist_ok=True)
            delimiter = str(input_config.get("delimiter") or ",")
            encoding = str(input_config.get("encoding") or "utf-8-sig")
            with destination.open("w", encoding=encoding, newline="") as handle:
                writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
                writer.writerow(columns)
                for row in rows:
                    writer.writerow(_stable_scalar(row.get(column)) for column in columns)
            row_counts[source_name] = len(rows)

        manifest = {
            "version": 1,
            "adapter": "odbc",
            "extracted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "window_from": lower_bound.isoformat(),
            "window_to": dt.datetime.now(dt.timezone.utc).date().isoformat(),
            "snapshot_max_ts": maximum_timestamp,
            "row_counts": row_counts,
            "query_sha256": query_digests,
            "configuration_sha256": hashlib.sha256(json.dumps(
                {"source": dict(config), "input": dict(input_config)},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
        }
        write_json(temporary / MANIFEST, manifest)
        temporary.rename(output)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if owns_connection and connection is not None:
            connection.close()


def load_manifest(snapshot: Path) -> dict[str, Any]:
    path = snapshot / MANIFEST
    if not path.is_file():
        raise ValueError(f"snapshot manifest is missing: {path}")
    return load_json(path)
