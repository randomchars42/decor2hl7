from __future__ import annotations

import csv
import datetime as dt
from decimal import Decimal
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from decor2hl7 import source, validate


class _Cursor:
    def __init__(self, results: dict[str, tuple[list[str], list[tuple[Any, ...]]]]) -> None:
        self.results = results
        self.description: list[tuple[str]] | None = None
        self.rows: list[tuple[Any, ...]] = []
        self.parameters: tuple[Any, ...] | None = None

    def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        columns, rows = self.results[sql.strip()]
        self.description = [(column,) for column in columns]
        self.rows = rows
        self.parameters = parameters

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        pass


class _Connection:
    def __init__(self, results: dict[str, tuple[list[str], list[tuple[Any, ...]]]]) -> None:
        self.results = results
        self.cursors: list[_Cursor] = []
        self.closed = False

    def cursor(self) -> _Cursor:
        cursor = _Cursor(self.results)
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        self.closed = True


def _site() -> dict[str, Any]:
    return {
        "input": {
            "case_source": "cases",
            "join_column": "case_id",
            "encoding": "utf-8",
            "delimiter": ";",
            # Deliberately child-first: extraction must still establish the
            # case key set before checking child rows.
            "sources": {
                "diagnoses": {
                    "file": "diagnoses.csv", "cardinality": "1:n",
                    "occurrence_keys": {"diagnosis": "rank"},
                    "order_by": ["rank"],
                },
                "cases": {"file": "cases.csv", "cardinality": "1:1"},
            },
        },
        "source": {
            "adapter": "odbc",
            "dsn_env": "TEST_DSN",
            "written_at_column": "written_at",
            "window_days": 90,
            "queries": {
                "cases": "sql/cases.sql", "diagnoses": "sql/diagnoses.sql",
            },
            "require_snapshot_advance": True,
        },
    }


class SourceTests(unittest.TestCase):
    def test_binary_scalars_are_serialized_as_lossless_hex(self) -> None:
        self.assertEqual(source._stable_scalar(b"\x00\xff\x10"), "00ff10")
        self.assertEqual(source._stable_scalar(bytearray(b"\x80\x01")), "8001")
        self.assertEqual(source._stable_scalar(memoryview(b"\xde\xad")), "dead")

    def test_site_validation_rejects_incomplete_or_unknown_source_contract(self) -> None:
        site = _site()
        site["source"]["window_days"] = 0
        site["source"]["queries"] = {"unknown": "sql/unknown.sql"}
        site["operation"] = {"failure_threshold": -1}
        errors = validate.check_site(site)
        self.assertTrue(any("positive integer" in error for error in errors))
        self.assertTrue(any("missing 'cases'" in error for error in errors))
        self.assertTrue(any("unknown input source" in error for error in errors))
        self.assertTrue(any("non-negative integer" in error for error in errors))

    def test_odbc_extraction_publishes_replayable_sorted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql = root / "sql"
            sql.mkdir()
            (sql / "cases.sql").write_text("CASES\n", encoding="utf-8")
            (sql / "diagnoses.sql").write_text("DIAGNOSES\n", encoding="utf-8")
            connection = _Connection({
                "CASES": (
                    ["case_id", "written_at", "amount"],
                    [
                        ("B", dt.datetime(2026, 9, 23, 8, 30), Decimal("2.50")),
                        ("A", dt.datetime(2026, 9, 22, 8, 30), Decimal("1.00")),
                    ],
                ),
                "DIAGNOSES": (
                    ["case_id", "rank", "code"],
                    [("A", 2, b"\x00\xff"), ("A", 1, "A"), ("B", 1, "C")],
                ),
            })
            output = root / "snapshot"

            manifest = source.extract(
                _site(), root, output,
                since=dt.date(2026, 1, 1), connection=connection,
            )

            self.assertEqual(manifest["row_counts"], {"cases": 2, "diagnoses": 3})
            self.assertEqual(manifest["snapshot_max_ts"], "2026-09-23T08:30:00.000000")
            self.assertTrue((output / source.MANIFEST).is_file())
            with (output / "cases.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual([row["case_id"] for row in rows], ["A", "B"])
            self.assertEqual(rows[0]["amount"], "1.00")
            with (output / "diagnoses.csv").open(encoding="utf-8", newline="") as handle:
                diagnoses = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual(
                [(row["case_id"], row["rank"]) for row in diagnoses],
                [("A", "1"), ("A", "2"), ("B", "1")],
            )
            self.assertEqual(diagnoses[1]["code"], "00ff")
            self.assertEqual(
                [cursor.parameters for cursor in connection.cursors],
                [(dt.date(2026, 1, 1),), (dt.date(2026, 1, 1),)],
            )
            self.assertFalse(connection.closed)

    def test_extraction_rejects_existing_target_and_duplicate_case_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql = root / "sql"
            sql.mkdir()
            (sql / "cases.sql").write_text("CASES", encoding="utf-8")
            (sql / "diagnoses.sql").write_text("DIAGNOSES", encoding="utf-8")
            output = root / "snapshot"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                source.extract(_site(), root, output, connection=_Connection({}))

            output.rmdir()
            connection = _Connection({
                "CASES": (
                    ["case_id", "written_at"],
                    [("A", "2026-01-01"), ("A", "2026-01-02")],
                ),
                "DIAGNOSES": (["case_id"], []),
            })
            with self.assertRaisesRegex(ValueError, "duplicate 1:1"):
                source.extract(_site(), root, output, connection=connection)
            self.assertFalse(output.exists())


class SQLiteSourceTests(unittest.TestCase):
    @staticmethod
    def prepare(root: Path) -> dict[str, Any]:
        site = _site()
        site["source"].update({"adapter": "sqlite", "database": "source #1?.sqlite"})
        site["source"].pop("dsn_env")
        (root / "sql").mkdir()
        (root / "sql/cases.sql").write_text(
            "SELECT * FROM cases WHERE written_at >= ?", encoding="utf-8",
        )
        (root / "sql/diagnoses.sql").write_text(
            "SELECT d.* FROM diagnoses d JOIN cases c ON d.case_id = c.case_id "
            "WHERE c.written_at >= ?", encoding="utf-8",
        )
        with sqlite3.connect(root / site["source"]["database"]) as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE cases (case_id TEXT, written_at TEXT, amount REAL, note TEXT);
                CREATE TABLE diagnoses (case_id TEXT, rank INTEGER, code BLOB);
                INSERT INTO cases VALUES
                  ('B', '2026-09-23T08:30:00+00:00', 2.5, 'Übung'),
                  ('A', '2026-09-22T08:30:00+00:00', 1, NULL),
                  ('OLD', '2025-01-01T00:00:00+00:00', 0, 'old');
                INSERT INTO diagnoses VALUES
                  ('A', 2, X'00FF'), ('B', 1, 'C'), ('A', 1, 'A'), ('OLD', 1, 'OLD');
            """)
        return site

    def test_native_numeric_ranks_keep_numeric_order_with_mixed_and_null_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            with sqlite3.connect(root / site["source"]["database"]) as connection:
                connection.executemany(
                    "INSERT INTO diagnoses VALUES ('A', ?, ?)",
                    [(10, "ten"), (2.5, "fraction"), ("text", "text"), (None, "null")],
                )
            source.extract(site, root, root / "snapshot", since=dt.date(2026, 1, 1))
            with (root / "snapshot/diagnoses.csv").open() as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual(
                [row["rank"] for row in rows if row["case_id"] == "A"],
                ["1", "2", "2.5", "10", "text", ""],
            )
            # Textual identifiers are not guessed to be numbers. Decimal and
            # float values sort alongside integers without comparison errors.
            values = [None, "2", 10, Decimal("2.25"), "10", 2.5, 1]
            self.assertEqual(
                sorted(values, key=source._sort_value),
                [1, Decimal("2.25"), 2.5, 10, "10", "2", None],
            )
            sorted([float("nan"), Decimal("NaN"), float("inf"), None], key=source._sort_value)

    def test_source_identity_resolves_database_paths_and_tracks_queries_not_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            first = source.extract(site, root, root / "first", since=dt.date(2026, 1, 1))
            site["source"]["database"] = str((root / site["source"]["database"]).resolve())
            site["source"]["window_days"] = 365
            site["source"]["require_snapshot_advance"] = False
            second = source.extract(site, root, root / "second", since=dt.date(2026, 1, 1))
            self.assertEqual(first["source_identity_sha256"], second["source_identity_sha256"])
            query = root / "sql/cases.sql"
            query.write_text(query.read_text() + " -- changed query")
            third = source.extract(site, root, root / "third", since=dt.date(2026, 1, 1))
            self.assertNotEqual(first["source_identity_sha256"], third["source_identity_sha256"])

    def test_odbc_source_identity_changes_without_exposing_connection_strings(self) -> None:
        config = {"adapter": "odbc", "dsn_env": "SOURCE_TEST_CONNECTION"}
        with patch.dict(os.environ, {"SOURCE_TEST_CONNECTION": "DSN=one;PWD=secret-one"}):
            first = source._source_identity(config, Path("."), {}, {"cases": "query-hash"})
        with patch.dict(os.environ, {"SOURCE_TEST_CONNECTION": "DSN=two;PWD=secret-two"}):
            second = source._source_identity(config, Path("."), {}, {"cases": "query-hash"})
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_sqlite_extracts_without_odbc_and_replays_identical_csv_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            with patch.dict(sys.modules, {"pyodbc": None}):
                source.check_connection(site, root)
                for name in ("first", "second"):
                    result = source.extract(site, root, root / name, since=dt.date(2026, 1, 1))
                    self.assertEqual(result["adapter"], "sqlite")
                    self.assertEqual(result["row_counts"], {"cases": 2, "diagnoses": 3})
            for name in ("cases.csv", "diagnoses.csv"):
                self.assertEqual((root / "first" / name).read_bytes(), (root / "second" / name).read_bytes())
            with (root / "first/cases.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual([row["case_id"] for row in rows], ["A", "B"])
            self.assertEqual(rows[0]["note"], "")
            self.assertEqual(rows[1]["note"], "Übung")
            with (root / "first/diagnoses.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual([row["code"] for row in rows], ["A", "00ff", "C"])

    def test_missing_and_invalid_databases_fail_without_creating_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            for name, content in (("missing.sqlite", None), ("invalid.sqlite", "not a database")):
                with self.subTest(name=name):
                    site["source"]["database"] = name
                    if content is not None:
                        (root / name).write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "SQLite"):
                        source.extract(site, root, root / "output")
                    self.assertFalse((root / "output").exists())
                    self.assertEqual((root / name).exists(), content is not None)

    def test_sqlite_queries_cannot_write_or_change_the_read_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            for sql in (
                "UPDATE diagnoses SET code = ? RETURNING case_id, rank, code",
                "PRAGMA query_only = OFF",
                "COMMIT",
                "ATTACH DATABASE ? AS other",
            ):
                with self.subTest(sql=sql):
                    (root / "sql/diagnoses.sql").write_text(sql, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "source query failed"):
                        source.extract(site, root, root / "output", since=dt.date(2026, 1, 1))
                    self.assertFalse((root / "output").exists())
                    self.assertEqual(list(root.glob(".output-*")), [])
            with sqlite3.connect(root / site["source"]["database"]) as connection:
                self.assertEqual(connection.execute("SELECT code FROM diagnoses WHERE case_id='A' AND rank=1").fetchone(), ("A",))

    def test_all_queries_observe_one_snapshot_despite_a_concurrent_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            execute = source._execute
            calls = 0

            def update_after_cases(connection: Any, sql: str, lower: dt.date) -> tuple[list[str], list[dict[str, Any]]]:
                nonlocal calls
                result = execute(connection, sql, lower)
                calls += 1
                if calls == 1:
                    with sqlite3.connect(root / site["source"]["database"]) as writer:
                        writer.execute("UPDATE diagnoses SET code='changed' WHERE case_id='A' AND rank=1")
                return result

            with patch("decor2hl7.source._execute", side_effect=update_after_cases):
                source.extract(site, root, root / "output", since=dt.date(2026, 1, 1))
            with (root / "output/diagnoses.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual(rows[0]["code"], "A")
            with sqlite3.connect(root / site["source"]["database"]) as connection:
                self.assertEqual(connection.execute("SELECT code FROM diagnoses WHERE case_id='A' AND rank=1").fetchone(), ("changed",))

    def test_sqlite_configuration_requires_a_filename_but_not_a_dsn(self) -> None:
        site = _site()
        site["source"]["adapter"] = "sqlite"
        site["source"].pop("dsn_env")
        self.assertTrue(any("source.database" in error for error in validate.check_site(site)))
        site["source"]["database"] = "source.sqlite"
        self.assertEqual(validate.check_site(site), [])
        site["source"]["database"] = []
        self.assertTrue(any("source.database" in error for error in validate.check_site(site)))


if __name__ == "__main__":
    unittest.main()
