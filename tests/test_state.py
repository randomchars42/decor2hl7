from __future__ import annotations

import sqlite3
import json
import tempfile
import unittest
from pathlib import Path

from decor2hl7 import state


class StateTests(unittest.TestCase):
    def test_legacy_json_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "index.json").write_text('{"documents":{}}')
            with self.assertRaisesRegex(ValueError, "unsupported legacy state"):
                state.load_state(directory)

    def test_state_lifecycle_increments_versions_and_appends_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = state.fingerprint({"values": {"a": 1}})
            second = state.fingerprint({"values": {"a": 2}})
            self.assertEqual(state.load_state(directory), {"version": 2, "documents": {}})
            self.assertEqual(state.classify(directory, "document", first), ("NEW", 1))

            state.record_delivery(
                directory, key="document", digest=first, document_version=1,
                file="first.xml", spec_version="release-v1",
            )
            self.assertEqual(
                state.classify(directory, "document", first), ("UNCHANGED", 1)
            )
            self.assertEqual(
                state.classify(directory, "document", second), ("CHANGED", 2)
            )
            state.record_delivery(
                directory, key="document", digest=second, document_version=2,
                file="second.xml", spec_version="release-v2",
                document_id={"root": "1.2.3", "extension": "document-2"},
                set_id={"root": "1.2.3", "extension": "document"},
                previous={
                    "document_id": {"root": "1.2.3", "extension": "document-1"},
                    "set_id": {"root": "1.2.3", "extension": "document"},
                    "version": 1,
                },
            )

            saved = state.load_state(directory)["documents"]["document"]
            self.assertEqual(saved["document_version"], 2)
            self.assertEqual(saved["spec_version"], "release-v2")
            with sqlite3.connect(directory / "state.sqlite") as connection:
                history = connection.execute(
                    "SELECT file FROM history ORDER BY document_version"
                ).fetchall()
            self.assertEqual(history, [("first.xml",), ("second.xml",)])
            self.assertEqual(
                state.previous_document(directory, "document"),
                {
                    "document_id": {"root": "1.2.3", "extension": "document-2"},
                    "set_id": {"root": "1.2.3", "extension": "document"},
                    "version": 2,
                },
            )

    def test_state_change_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            digest = state.fingerprint({"values": {"a": 1}})
            self.assertEqual(state.classify(path, "tx::x", digest), ("NEW", 1))
            state.record_delivery(path, key="tx::x", digest=digest, document_version=1, file="x.xml", spec_version="v")
            self.assertEqual(state.classify(path, "tx::x", digest)[0], "UNCHANGED")
            with self.assertRaisesRegex(ValueError, "cannot follow"):
                state.record_delivery(
                    path, key="tx::x", digest="future", document_version=3,
                    file="x-v3.xml", spec_version="v",
                )

    def test_state_fingerprint_includes_repeating_instances(self) -> None:
        a = {"values": {}, "instances": {"med": [{"values": {"drug": "A", "route": None}}, {"values": {"drug": "B", "route": "oral"}}]}}
        b = {"values": {}, "instances": {"med": [{"values": {"drug": "A", "route": "oral"}}, {"values": {"drug": "B", "route": None}}]}}
        self.assertNotEqual(state.fingerprint(a), state.fingerprint(b))

    def test_state_fingerprint_ignores_csv_row_provenance(self) -> None:
        a = {"values": {}, "instances": {"med": [{"source": "medications", "row": 2, "values": {"drug": "A"}}]}}
        b = {"values": {}, "instances": {"med": [{"source": "medications", "row": 99, "values": {"drug": "A"}}]}}
        self.assertEqual(state.fingerprint(a), state.fingerprint(b))

    def test_run_ledger_records_completed_snapshot_and_lock_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            state.start_run(directory, "r1", kind="run-source")
            state.finish_run(
                directory, "r1", status="completed",
                snapshot_max_ts="2026-09-23T01:02:03",
                source_stream="source-a",
                summary={"records": 4},
            )
            self.assertEqual(
                state.last_snapshot_max_ts(directory, "source-a"), "2026-09-23T01:02:03"
            )
            self.assertEqual(state.recent_runs(directory)[0]["status"], "completed")
            with state.workspace_lock(directory):
                with self.assertRaisesRegex(RuntimeError, "already active"):
                    with state.workspace_lock(directory):
                        pass

    def test_snapshot_watermarks_are_scoped_and_ignore_incomplete_and_legacy_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for run_id, stream, status, maximum in (
                ("legacy", None, "completed", "2099-01-01"),
                ("a", "source-a", "completed", "2026-06-01"),
                ("b", "source-b", "completed", "2026-05-01"),
                ("partial", "source-a", "partial", "2026-08-01"),
                ("failed", "source-a", "failed", "2026-09-01"),
            ):
                state.start_run(directory, run_id, kind="run-source")
                state.finish_run(directory, run_id, status=status, source_stream=stream, snapshot_max_ts=maximum)
            self.assertEqual(state.last_snapshot_max_ts(directory, "source-a"), "2026-06-01")
            self.assertEqual(state.last_snapshot_max_ts(directory, "source-b"), "2026-05-01")
            self.assertIsNone(state.last_snapshot_max_ts(directory, "new-source"))

    def test_old_run_ledger_is_rejected_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with sqlite3.connect(directory / "state.sqlite") as connection:
                connection.execute("""CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY, kind TEXT, started_at TEXT,
                    finished_at TEXT, status TEXT, snapshot_path TEXT,
                    snapshot_max_ts TEXT, summary TEXT, error TEXT
                )""")
                connection.execute("INSERT INTO runs (run_id, kind, status, snapshot_max_ts) VALUES ('old', 'run-source', 'completed', '2099-01-01')")
            with self.assertRaisesRegex(ValueError, "unsupported state schema"):
                state.last_snapshot_max_ts(directory, "new-source")
            with sqlite3.connect(directory / "state.sqlite") as connection:
                self.assertNotIn("source_stream", [row[1] for row in connection.execute("PRAGMA table_info(runs)")])

    def test_state_fingerprint_changes_with_transformation_context(self) -> None:
        record = {"values": {"a": 1}, "instances": {}}
        self.assertNotEqual(
            state.fingerprint(record, {"mapping": "A"}),
            state.fingerprint(record, {"mapping": "B"}),
        )


if __name__ == "__main__":
    unittest.main()
