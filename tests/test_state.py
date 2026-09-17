from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from decor2hl7 import state


class StateTests(unittest.TestCase):
    def test_state_lifecycle_increments_versions_and_appends_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = state.fingerprint({"values": {"a": 1}})
            second = state.fingerprint({"values": {"a": 2}})
            self.assertEqual(state.load_state(directory), {"version": 1, "documents": {}})
            self.assertEqual(state.classify(directory, "document", first), ("NEW", 1))

            state.record_sent(
                directory, key="document", digest=first, document_version=1,
                file="first.xml", spec_version="release-v1",
            )
            self.assertEqual(
                state.classify(directory, "document", first), ("UNCHANGED", 1)
            )
            self.assertEqual(
                state.classify(directory, "document", second), ("CHANGED", 2)
            )
            state.record_sent(
                directory, key="document", digest=second, document_version=2,
                file="second.xml", spec_version="release-v2",
            )

            saved = state.load_state(directory)["documents"]["document"]
            self.assertEqual(saved["document_version"], 2)
            self.assertEqual(saved["spec_version"], "release-v2")
            history = (directory / "history.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(history), 2)
            self.assertEqual(json.loads(history[-1])["file"], "second.xml")

    def test_history_rotation_ignores_disabled_recent_and_invalid_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertIsNone(state.rotate(directory, 1))
            history = directory / "history.jsonl"
            history.write_text("", encoding="utf-8")
            self.assertIsNone(state.rotate(directory, 0))
            self.assertIsNone(state.rotate(directory, 1))

            history.write_text("not json\n", encoding="utf-8")
            self.assertIsNone(state.rotate(directory, 1))
            recent = dt.datetime.now(dt.timezone.utc).isoformat()
            history.write_text(
                json.dumps({"sent_at": recent}) + "\n", encoding="utf-8"
            )
            self.assertIsNone(state.rotate(directory, 1))
            self.assertTrue(history.exists())

    def test_state_change_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            digest = state.fingerprint({"values": {"a": 1}})
            self.assertEqual(state.classify(path, "tx::x", digest), ("NEW", 1))
            state.record_sent(path, key="tx::x", digest=digest, document_version=1, file="x.xml", spec_version="v")
            self.assertEqual(state.classify(path, "tx::x", digest)[0], "UNCHANGED")

    def test_state_fingerprint_includes_repeating_instances(self) -> None:
        a = {"values": {}, "instances": {"med": [{"values": {"drug": "A", "route": None}}, {"values": {"drug": "B", "route": "oral"}}]}}
        b = {"values": {}, "instances": {"med": [{"values": {"drug": "A", "route": "oral"}}, {"values": {"drug": "B", "route": None}}]}}
        self.assertNotEqual(state.fingerprint(a), state.fingerprint(b))

    def test_state_fingerprint_ignores_csv_row_provenance(self) -> None:
        a = {"values": {}, "instances": {"med": [{"source": "medications", "row": 2, "values": {"drug": "A"}}]}}
        b = {"values": {}, "instances": {"med": [{"source": "medications", "row": 99, "values": {"drug": "A"}}]}}
        self.assertEqual(state.fingerprint(a), state.fingerprint(b))

    def test_history_rotation_uses_first_entry_timestamp_not_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            history = directory / "history.jsonl"
            history.write_text(
                '{"key":"x","sent_at":"2000-01-01T00:00:00+00:00"}\n',
                encoding="utf-8",
            )
            rotated = state.rotate(directory, 1)
            self.assertIsNotNone(rotated)
            self.assertFalse(history.exists())
            assert rotated is not None
            self.assertTrue(rotated.exists())

    def test_state_fingerprint_changes_with_transformation_context(self) -> None:
        record = {"values": {"a": 1}, "instances": {}}
        self.assertNotEqual(
            state.fingerprint(record, {"mapping": "A"}),
            state.fingerprint(record, {"mapping": "B"}),
        )


if __name__ == "__main__":
    unittest.main()
