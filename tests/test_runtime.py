from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from decor2hl7 import state
from decor2hl7.bundle import mapping_lock
from decor2hl7.workspace import selected_release, selected_transaction
from decor2hl7.cli import main
from decor2hl7.workspace import (
    init_workspace, load_json, set_release, set_transaction,
    transaction_model_dir, transaction_mapping_dir, transaction_out_dir,
    transaction_site_dir, release_site_dir, write_json,
)


class RuntimeRecoveryTests(unittest.TestCase):
    def prepare(self, root: Path) -> Path:
        init_workspace(root)
        set_release(root, {"key": "example-release", "date": "2024-01-01T00:00:00"})
        set_transaction(root, {"key": "example", "id": "1.2.3", "effective_date": "2024-01-01T00:00:00"})
        write_json(transaction_model_dir(root) / "model.json", {
            "groups": {}, "fields": {"note": {"type": "text", "repeat_chain": []}},
        })
        write_json(transaction_model_dir(root) / "cda.json", {
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1,
                "children": [{
                    "kind": "element", "name": "hl7:text", "datatype": "ST",
                    "min": 0, "max": 1, "attributes": [], "children": [], "targets": ["Document.note"],
                }, {
                    "kind": "element", "name": "hl7:relatedDocument", "min": 0, "max": None,
                    "content_role": "document_replacement", "attributes": [], "children": [], "targets": [],
                }], "attributes": [], "targets": [],
            }],
            "targets": {"Document.note": {
                "renderable": True, "writable": True, "prohibited": False,
                "locations": ["0.0"], "logical_types": ["text"], "datatype": "ST",
                "value_representation": {"kind": "element_text", "logical_types": ["text"]},
                "path": "hl7:ClinicalDocument/hl7:text", "repeat_ancestors": [],
            }}, "validation_rules": [], "unresolved_templates": [],
        })
        write_json(transaction_mapping_dir(root) / "cda-mapping.json", {
            "version": 2, "fields": {"note": "Document.note"}, "structures": {},
        })
        write_json(transaction_mapping_dir(root) / "mapping-lock.json", mapping_lock(
            selected_release(root), selected_transaction(root),
            load_json(transaction_model_dir(root) / "model.json"),
            load_json(transaction_model_dir(root) / "cda.json"),
            load_json(transaction_mapping_dir(root) / "cda-mapping.json"),
        ))
        bundle = transaction_site_dir(root)
        write_json(bundle / "csv-mapping.json", {"fields": {"note": "cases:note"}})
        write_json(bundle / "codes-mapping.json", {"fields": {}})
        (bundle / "cases.sql").write_text("SELECT * FROM cases WHERE written_at >= ?")
        site_path = release_site_dir(root) / "site.json"
        write_json(site_path, {
            "timezone": "UTC", "identifiers": {"document_root": "1.2.3.4"},
            "input": {"case_source": "cases", "join_column": "case_id", "delimiter": ",",
                      "sources": {"cases": {"file": "cases.csv", "cardinality": "1:1"}}},
            "source": {"adapter": "sqlite", "database": "source.sqlite", "written_at_column": "written_at",
                       "queries": {"cases": "cases.sql"}, "require_snapshot_advance": False},
            "transport": {"adapter": "spool", "directory": "spool"},
        })
        with sqlite3.connect(site_path.parent / "source.sqlite") as connection:
            connection.execute("CREATE TABLE cases (case_id TEXT, note TEXT, written_at TEXT)")
            connection.execute("INSERT INTO cases VALUES ('case', 'First note', '2026-06-01T12:00:00+00:00')")
        return site_path

    def run_source(self, root: Path, *, send: bool = True) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            status = main(["--root", str(root), "run-source", "--since", "2026-01-01", *(["--send"] if send else [])])
        return status, output.getvalue()

    def test_retry_after_publication_preserves_bytes_and_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            with patch("decor2hl7.state.record_delivery", side_effect=RuntimeError("interrupted after publication")):
                status, output = self.run_source(root)
            self.assertEqual(status, 2, output)
            document = next(transaction_out_dir(root).glob("*.xml"))
            before = (document.read_bytes(), document.with_suffix(".json").read_bytes())
            self.assertEqual(state.load_state(root / "state")["documents"], {})
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(["--root", str(root), "run-source", "--since", "2026-01-01", "--dry-run"]), 0)
            self.assertEqual(state.load_state(root / "state")["documents"], {})
            status, output = self.run_source(root)
            self.assertEqual(status, 0, output)
            self.assertIn("already published", output)
            self.assertEqual((document.read_bytes(), document.with_suffix(".json").read_bytes()), before)
            self.assertEqual(len(state.load_state(root / "state")["documents"]), 1)
            status, output = self.run_source(root)
            self.assertEqual(status, 0, output)
            self.assertIn('"unchanged": 1', output)
            with sqlite3.connect(root / "state/state.sqlite") as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM history").fetchone(), (1,))

    def test_pending_bytes_are_reused_before_delivery_and_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            self.assertEqual(self.run_source(root, send=False)[0], 0)
            document = next(transaction_out_dir(root).glob("*.xml"))
            original = document.with_suffix(".json").read_bytes()
            self.assertEqual(self.run_source(root, send=False)[0], 0)
            self.assertEqual(document.with_suffix(".json").read_bytes(), original)
            document.write_bytes(b"<tampered/>")
            status, output = self.run_source(root)
            self.assertEqual(status, 2, output)
            self.assertIn("checksum", output)
            self.assertFalse((root / "spool").exists())

    def test_published_revision_is_recovered_before_source_correction_is_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site_path = self.prepare(root)
            with patch("decor2hl7.state.record_delivery", side_effect=RuntimeError("interrupted")):
                self.assertEqual(self.run_source(root)[0], 2)
            with sqlite3.connect(site_path.parent / "source.sqlite") as connection:
                connection.execute("UPDATE cases SET note = 'Corrected note'")
            status, output = self.run_source(root)
            self.assertEqual(status, 0, output)
            self.assertIn('"recovered": 1', output)
            self.assertEqual(len(list(transaction_out_dir(root).glob("*-v1.xml"))), 1)
            self.assertEqual(len(list(transaction_out_dir(root).glob("*-v1.json"))), 1)
            delivered = state.load_state(root / "state")["documents"]["1.2.3::case"]
            self.assertEqual(delivered["document_version"], 2)
            self.assertEqual(len(list((root / "spool").glob("*/*"))), 2)
            with sqlite3.connect(root / "state/state.sqlite") as connection:
                self.assertEqual(connection.execute("SELECT document_version FROM history ORDER BY document_version").fetchall(), [(1,), (2,)])

    def test_source_switch_and_query_change_have_independent_watermarks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site_path = self.prepare(root)
            site = load_json(site_path)
            site["source"]["require_snapshot_advance"] = True
            write_json(site_path, site)
            status, output = self.run_source(root)
            self.assertEqual(status, 0, output)
            shutil.copy(site_path.parent / "source.sqlite", site_path.parent / "other.sqlite")
            with sqlite3.connect(site_path.parent / "other.sqlite") as connection:
                connection.execute("UPDATE cases SET written_at = '2026-05-01T12:00:00+00:00'")
            site["source"]["database"] = "other.sqlite"
            write_json(site_path, site)
            status, output = self.run_source(root)
            self.assertEqual(status, 0, output)
            status, output = self.run_source(root)
            self.assertEqual(status, 2, output)
            self.assertIn("has not advanced", output)
            query = transaction_site_dir(root) / "cases.sql"
            query.write_text(query.read_text() + " -- revised query")
            status, output = self.run_source(root)
            self.assertEqual(status, 0, output)
            streams = {run["source_stream"] for run in state.recent_runs(root / "state")}
            self.assertEqual(len(streams), 3)
            # A different transaction must not inherit even the same source's watermark.
            for directory in (transaction_model_dir(root), transaction_mapping_dir(root), transaction_site_dir(root)):
                shutil.copytree(directory, directory.with_name("other-example"))
            set_transaction(root, {"key": "other-example", "id": "1.2.99", "effective_date": "2024-01-01T00:00:00"})
            write_json(transaction_mapping_dir(root) / "mapping-lock.json", mapping_lock(
                selected_release(root), selected_transaction(root),
                load_json(transaction_model_dir(root) / "model.json"),
                load_json(transaction_model_dir(root) / "cda.json"), {},
            ))
            status, output = self.run_source(root, send=False)
            self.assertEqual(status, 0, output)

    def test_mapping_lock_is_admitted_before_extraction_and_handover(self) -> None:
        from decor2hl7.runtime import _send_paths
        for key, invalid in (("model_sha256", "wrong"), ("cda_sha256", "wrong"), ("transaction", {"id": "wrong"}), ("release", {"key": "wrong"}), ("version", 99)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.prepare(root)
                lock_path = transaction_mapping_dir(root) / "mapping-lock.json"
                lock = load_json(lock_path)
                lock[key] = invalid
                write_json(lock_path, lock)
                with patch("decor2hl7.source.extract") as extract:
                    status, output = self.run_source(root)
                self.assertEqual(status, 2, output)
                self.assertIn("mapping-lock.json", output)
                extract.assert_not_called()
                with patch("decor2hl7.transport.send") as send, self.assertRaisesRegex(ValueError, "mapping-lock.json"):
                    _send_paths(root, [])
                send.assert_not_called()

    def test_send_rejects_a_stale_artifact_before_transport_io(self) -> None:
        from decor2hl7.runtime import _send_paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            self.assertEqual(self.run_source(root, send=False)[0], 0)
            document = next(transaction_out_dir(root).glob("*.xml"))
            info = load_json(document.with_suffix(".json"))
            state.record_delivery(root / "state", key=info["state_key"], digest="different", document_version=1, file="other.xml", spec_version="example-release", document_id=info["document_id"], set_id=info["set_id"])
            with patch("decor2hl7.transport.send") as send, redirect_stderr(StringIO()):
                self.assertEqual(_send_paths(root, [document]), (0, 1))
            send.assert_not_called()

    def test_missing_current_sidecar_fields_are_rejected(self) -> None:
        for key in ("state_key", "document_id", "set_id", "previous_document", "prepared_at", "payload_sha256"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.prepare(root)
                self.assertEqual(self.run_source(root, send=False)[0], 0)
                sidecar = next(transaction_out_dir(root).glob("*.json"))
                value = load_json(sidecar)
                del value[key]
                write_json(sidecar, value)
                status, output = self.run_source(root)
                self.assertEqual(status, 2, output)
                self.assertFalse((root / "spool").exists())
                self.assertEqual(state.load_state(root / "state")["documents"], {})

    def test_transport_options_fail_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.prepare(root)
            site = load_json(path)
            site["transport"]["typo"] = True
            write_json(path, site)
            with patch("decor2hl7.source.extract") as extract:
                status, output = self.run_source(root)
            self.assertEqual(status, 2, output)
            self.assertIn("unsupported transport", output)
            extract.assert_not_called()

    def test_all_committed_revision_artifacts_survive_corrections_and_absence(self) -> None:
        from decor2hl7.runtime import _prune_absent_pending
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = self.prepare(root)
            for note in ("First", "Second", "Third"):
                with sqlite3.connect(site.parent / "source.sqlite") as connection:
                    connection.execute("UPDATE cases SET note = ?", (note,))
                status, output = self.run_source(root)
                self.assertEqual(status, 0, output)
            out = transaction_out_dir(root)
            self.assertEqual(len(list(out.glob("*.xml"))), 3)
            self.assertEqual(_prune_absent_pending(out, set(), root / "state"), 0)
            with sqlite3.connect(root / "state/state.sqlite") as connection:
                for (filename,) in connection.execute("SELECT file FROM history"):
                    self.assertTrue(Path(filename).is_file())
                    self.assertTrue(Path(filename).with_suffix(".json").is_file())


if __name__ == "__main__":
    unittest.main()
