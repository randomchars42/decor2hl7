from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from decor2hl7.cli import _prune_absent_pending, _prune_stale_pending, main
from decor2hl7.workspace import load_json, set_release, set_transaction, transaction_model_dir, write_json

RELEASES = [{"key": "2026.1.2", "label": "2026.1.2", "date": "2026-04-27T18:50:33", "status": "final"}]
TRANSACTIONS = [{
    "key": "notaufnahmeregister--60", "id": "2.16.840.1.113883.2.6.60.3.4.60",
    "effective_date": "2026-03-25T00:00:00", "version_label": "2026",
    "status": "active", "name": "Notaufnahmeregister Transitionsversion",
}]


class CliTests(unittest.TestCase):
    def test_symmetric_release_and_transaction_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            with patch("decor2hl7.retrieval.catalog.releases", return_value=RELEASES):
                self.assertEqual(main(["--root", str(root), "set-version", "2026.1.2"]), 0)
            settings = load_json(root / "aktin.json")
            self.assertEqual(settings["release"]["key"], "2026.1.2")
            self.assertIsNone(settings["transaction"])
            with patch("decor2hl7.retrieval.catalog.transactions", return_value=TRANSACTIONS):
                self.assertEqual(main(["--root", str(root), "set-transaction", "notaufnahmeregister--60"]), 0)
            settings = load_json(root / "aktin.json")
            self.assertEqual(settings["transaction"]["key"], "notaufnahmeregister--60")
            # Set commands still have no artifact-directory side effects.
            self.assertFalse((root / "spec" / "2026.1.2").exists())


    def test_selection_lists_put_key_first_and_use_verb_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            out = StringIO()
            with patch("decor2hl7.retrieval.catalog.releases", return_value=RELEASES), redirect_stdout(out):
                self.assertEqual(main(["--root", str(root), "list-versions"]), 0)
            lines = out.getvalue().splitlines()
            self.assertTrue(lines[0].startswith("KEY"))
            self.assertTrue(lines[1].startswith("2026.1.2"))

            with patch("decor2hl7.retrieval.catalog.releases", return_value=RELEASES):
                self.assertEqual(main(["--root", str(root), "set-version", "2026.1.2"]), 0)
            out = StringIO()
            with patch("decor2hl7.retrieval.catalog.transactions", return_value=TRANSACTIONS), redirect_stdout(out):
                self.assertEqual(main(["--root", str(root), "list-transactions"]), 0)
            lines = out.getvalue().splitlines()
            self.assertTrue(lines[0].startswith("KEY"))
            self.assertTrue(lines[1].startswith("notaufnahmeregister--60"))

    def test_keyboard_interrupt_exits_130_without_traceback(self) -> None:
        err = StringIO()
        with patch("decor2hl7.cli.cmd_init", side_effect=KeyboardInterrupt), redirect_stderr(err):
            self.assertEqual(main(["init"]), 130)
        self.assertEqual(err.getvalue().strip(), "aborted by user")

    def test_input_commands_accept_external_input_root_and_build_is_uncoupled(self) -> None:
        from decor2hl7.cli import parser
        propose = parser().parse_args(["propose-input", "--input", "/tmp/input"])
        self.assertEqual(propose.input, "/tmp/input")
        self.assertEqual(propose.join_column, "patient_id")
        transform = parser().parse_args(["transform", "--input", "/tmp/input"])
        self.assertEqual(transform.input, "/tmp/input")
        run = parser().parse_args(["run", "--input", "/tmp/input"])
        self.assertEqual(run.input, "/tmp/input")
        check_input = parser().parse_args(["check-input", "--input", "/tmp/input"])
        self.assertEqual(check_input.input, "/tmp/input")
        build = parser().parse_args(["build"])
        self.assertFalse(hasattr(build, "input"))
        self.assertFalse(hasattr(build, "join_column"))
        check = parser().parse_args(["check"])
        self.assertFalse(hasattr(check, "input"))

    def test_propose_input_writes_only_csv_and_code_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            source.mkdir()
            (source / "cases.csv").write_text(
                "patient_id;Aufnahmezeitpunkt;Triage\n1;2026-01-01T12:00:00;rot\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model_dir = transaction_model_dir(root)
            model_dir.mkdir(parents=True)
            write_json(model_dir / "model.json", {
                "meta": {
                    "dataset_id": "dataset",
                    "transaction_id": TRANSACTIONS[0]["id"],
                    "transaction_effective_date": TRANSACTIONS[0]["effective_date"],
                },
                "fields": {
                    "aufnahme.aufnahmezeitpunkt": {
                        "name": "Aufnahmezeitpunkt",
                        "type": "datetime",
                    },
                    "aufnahme.triage": {
                        "name": "Triage",
                        "type": "code",
                        "values": {
                            "rot": {"code": "R", "display_name": "Rot"},
                            "orange": {"code": "O", "display_name": "Orange"},
                        },
                    },
                },
            })

            self.assertEqual(
                main(["--root", str(root), "propose-input", "--input", str(source)]),
                0,
            )
            csv_proposal = load_json(model_dir / "csv-mapping.proposed.json")
            code_proposal = load_json(model_dir / "codes-mapping.proposed.json")
            self.assertEqual(csv_proposal["fields"]["aufnahme.aufnahmezeitpunkt"], "cases:Aufnahmezeitpunkt")
            self.assertEqual(csv_proposal["fields"]["aufnahme.triage"], "cases:Triage")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["rot"], "rot")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["R"], "rot")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["orange"], "orange")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["O"], "orange")
            self.assertFalse((model_dir / "cda-mapping.proposed.json").exists())

    def test_config_adds_new_code_defaults_without_overwriting_user_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model = transaction_model_dir(root)
            model.mkdir(parents=True)
            write_json(model / "csv-mapping.proposed.json", {"version": 1, "fields": {}})
            write_json(model / "cda-mapping.proposed.json", {"version": 2, "fields": {}})
            write_json(model / "codes-mapping.proposed.json", {
                "version": 1,
                "fields": {"triage": {"R": "rot", "O": "orange", "unknown": None}},
            })
            config_dir = root / "config" / "2026.1.2" / "notaufnahmeregister--60"
            config_dir.mkdir(parents=True)
            write_json(config_dir / "codes-mapping.json", {
                "version": 1,
                "fields": {"triage": {"R": "custom"}},
            })

            self.assertEqual(main(["--root", str(root), "config"]), 0)
            configured = load_json(config_dir / "codes-mapping.json")
            self.assertEqual(configured["fields"]["triage"]["R"], "custom")
            self.assertEqual(configured["fields"]["triage"]["O"], "orange")
            self.assertNotIn("unknown", configured["fields"]["triage"] )

    def test_config_never_overwrites_user_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model = transaction_model_dir(root)
            model.mkdir(parents=True)
            (model / "csv-mapping.proposed.json").write_text('{"fields":{"a":"cases:a"}}')
            (model / "codes-mapping.proposed.json").write_text('{"fields":{}}')
            (model / "cda-mapping.proposed.json").write_text('{"fields":{"a":"Doc.value"}}')
            self.assertEqual(main(["--root", str(root), "config"]), 0)
            config = root / "config" / "2026.1.2" / "notaufnahmeregister--60" / "csv-mapping.json"
            config.write_text('{"user":true}')
            self.assertEqual(main(["--root", str(root), "config"]), 0)
            self.assertEqual(load_json(config), {"user": True})
            self.assertTrue((root / "config" / "2026.1.2" / "site.json").exists())

    def test_stale_pending_output_is_pruned_when_source_changes_or_reverts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            xml = out / "case-v2.xml"
            sidecar = out / "case-v2.json"
            xml.write_text("<old/>", encoding="utf-8")
            write_json(sidecar, {"state_key": "tx::case", "fingerprint": "old"})
            removed = _prune_stale_pending(out, "tx::case", "current")
            self.assertEqual(removed, 1)
            self.assertFalse(xml.exists())
            self.assertFalse(sidecar.exists())


    def test_absent_pending_output_is_pruned_but_sent_artifact_is_kept(self) -> None:
        from decor2hl7 import state
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            state_path = root / "state"
            out.mkdir()
            (out / "pending.xml").write_text("<pending/>", encoding="utf-8")
            write_json(out / "pending.json", {"state_key": "tx::gone", "fingerprint": "new"})
            (out / "sent.xml").write_text("<sent/>", encoding="utf-8")
            write_json(out / "sent.json", {"state_key": "tx::sent", "fingerprint": "same"})
            state.record_sent(state_path, key="tx::sent", digest="same", document_version=1, file="sent.xml", spec_version="v")
            removed = _prune_absent_pending(out, set(), state_path)
            self.assertEqual(removed, 1)
            self.assertFalse((out / "pending.xml").exists())
            self.assertTrue((out / "sent.xml").exists())



if __name__ == "__main__":
    unittest.main()
