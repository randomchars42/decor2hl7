"""Create a runnable SQLite source bundle from an authored mapping fixture."""

from __future__ import annotations

import argparse
from contextlib import closing
import csv
import datetime as dt
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any

from decor2hl7.i18n import Translator


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def create_source(fixture: Path, output: Path, *, written_at: str) -> dict[str, Any]:
    """Seed raw strings and explicit joins; no clinical semantics are inferred."""
    t = Translator()
    timestamp = dt.datetime.fromisoformat(written_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError(t.text("cli.sqlite_fixture_timezone_required"))
    stamp = timestamp.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    fixture, output = fixture.resolve(), output.resolve()
    if output.exists():
        raise ValueError(t.text("cli.sqlite_fixture_output_exists", path=output))
    site = json.loads((fixture / "config" / "site.json").read_text(encoding="utf-8"))
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    if not expected.get("scenario") or not isinstance(expected.get("cases"), list):
        raise ValueError(t.text("cli.sqlite_fixture_authored_required"))
    config = site["input"]
    sources = config["sources"]
    case_source, join = config["case_source"], config["join_column"]
    written_column = "_decor2hl7_written_at"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as tmp:
        staging = Path(tmp) / "bundle"
        (staging / "sql").mkdir(parents=True)
        queries: dict[str, str] = {}
        counts: dict[str, int] = {}
        with closing(sqlite3.connect(staging / "source.sqlite")) as connection:
            with connection:
                for name, spec in sources.items():
                    filename = spec if isinstance(spec, str) else spec["file"]
                    relative = Path(filename)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError(t.text("cli.sqlite_fixture_relative_file", path=filename))
                    with (fixture / "input" / relative).open(
                        encoding=config.get("encoding") or "utf-8-sig", newline="",
                    ) as handle:
                        reader = csv.reader(handle, delimiter=config.get("delimiter") or ",")
                        columns = next(reader)
                        rows = list(reader)
                    if written_column in columns:
                        raise ValueError(t.text("cli.sqlite_fixture_reserved_column", column=written_column))
                    if name == case_source:
                        columns.append(written_column)
                        rows = [row + [stamp] for row in rows]
                    declaration = ", ".join(f"{_quote(column)} TEXT" for column in columns)
                    connection.execute(f"CREATE TABLE {_quote(name)} ({declaration})")
                    placeholders = ", ".join("?" for _ in columns)
                    connection.executemany(
                        f"INSERT INTO {_quote(name)} VALUES ({placeholders})", rows,
                    )
                    if name == case_source:
                        query = (
                            f"SELECT * FROM {_quote(name)} "
                            f"WHERE {_quote(written_column)} >= ?\n"
                        )
                    else:
                        source_join = (spec.get("join_column") or join) if isinstance(spec, dict) else join
                        query = (
                            f"SELECT s.* FROM {_quote(name)} AS s "
                            f"JOIN {_quote(case_source)} AS c "
                            f"ON s.{_quote(source_join)} = c.{_quote(join)} "
                            f"WHERE c.{_quote(written_column)} >= ?\n"
                        )
                    # Source names can be arbitrary logical identifiers; use
                    # numeric filenames rather than interpreting them as paths.
                    query_file = f"sql/source-{len(queries) + 1}.sql"
                    (staging / query_file).write_text(query, encoding="utf-8")
                    queries[name] = query_file
                    counts[name] = len(rows)
        site["source"] = {
            "adapter": "sqlite", "database": "source.sqlite",
            "written_at_column": written_column, "window_days": 90,
            "queries": queries, "require_snapshot_advance": False,
        }
        site["transport"] = {"adapter": "spool", "directory": str(output / "spool")}
        (staging / "site.json").write_text(
            json.dumps(site, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        for name in ("csv-mapping.json", "codes-mapping.json"):
            shutil.copyfile(fixture / "config" / name, staging / name)
        evidence = {
            "scenario": expected["scenario"], "cases": expected["cases"],
            "written_at": stamp, "row_counts": counts,
        }
        (staging / "fixture.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        staging.rename(output)
    return evidence


def main() -> int:
    t = Translator()
    parser = argparse.ArgumentParser(description=t.text("cli.sqlite_fixture_description"))
    parser.add_argument("--fixture", required=True, type=Path, help=t.text("cli.sqlite_fixture_fixture_help"))
    parser.add_argument("--output", required=True, type=Path, help=t.text("cli.sqlite_fixture_output_help"))
    parser.add_argument("--written-at", required=True, help=t.text("cli.sqlite_fixture_written_at_help"))
    args = parser.parse_args()
    try:
        result = create_source(args.fixture, args.output, written_at=args.written_at)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps({"bundle": str(args.output.resolve()), **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
