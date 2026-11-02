from __future__ import annotations

import csv
import datetime as dt
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path
from typing import Any

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


if __name__ == "__main__":
    unittest.main()
