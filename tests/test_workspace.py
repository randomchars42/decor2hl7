from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from decor2hl7 import validate, workspace
from decor2hl7.workspace import (
    init_workspace,
    input_dir,
    load_json,
    release_spec_dir,
    set_release,
    set_transaction,
    transaction_mapping_dir,
    transaction_model_dir,
    transaction_site_dir,
    transaction_test_dir,
)


RELEASE = {"key": "release-v1", "label": "release-v1", "date": "2024-01-02T03:04:05", "status": "final"}


TRANSACTION = {
    "key": "example--1",
    "id": "1.2.3.4.1",
    "effective_date": "2024-01-01T00:00:00",
    "version_label": "v1",
    "status": "active",
    "name": "Example transaction",
}


class WorkspaceTests(unittest.TestCase):
    def test_workspace_initialization_is_idempotent_and_preserves_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = init_workspace(root, prefix="main-", language="en-US")
            settings = load_json(path)
            settings["prefix"] = "custom-"
            settings["custom"] = {"kept": True}
            settings.pop("network")
            settings["output"] = {}
            workspace.write_json(path, settings)

            self.assertEqual(init_workspace(root, prefix="ignored-"), path)
            reloaded = load_json(path)
            self.assertEqual(reloaded["prefix"], "custom-")
            self.assertEqual(reloaded["custom"], {"kept": True})
            self.assertEqual(reloaded["network"], {"ipv4": True})
            self.assertEqual(reloaded["output"], {"language": "en"})

    def test_selection_guards_and_json_object_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "workspace is not initialized"):
                workspace.load_settings(root)
            init_workspace(root)
            with self.assertRaisesRegex(ValueError, "no release selected"):
                workspace.selected_release(root)
            with self.assertRaisesRegex(ValueError, "no release selected"):
                set_transaction(root, TRANSACTION)
            with self.assertRaisesRegex(ValueError, "no transaction selected"):
                workspace.selected_transaction(root)

            invalid = root / "invalid.json"
            invalid.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                load_json(invalid)

    def test_workspace_path_helpers_share_the_selected_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            set_release(root, RELEASE)
            set_transaction(root, TRANSACTION)

            release = RELEASE["key"]
            transaction = TRANSACTION["key"]
            self.assertEqual(workspace.settings_path(root), root / "decor2hl7.json")
            self.assertEqual(workspace.state_dir(root), root / "state")
            self.assertEqual(
                workspace.transaction_spec_dir(root),
                root / "spec" / release / "transactions" / transaction,
            )
            self.assertEqual(
                workspace.release_mapping_dir(root), root / "mapping" / release
            )
            self.assertEqual(workspace.release_site_dir(root), root / "site" / release)
            self.assertEqual(
                workspace.transaction_out_dir(root),
                root / "out" / release / transaction,
            )

    def test_copy_if_missing_never_overwrites_or_creates_from_absent_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            destination = root / "nested" / "destination.txt"
            self.assertFalse(workspace.copy_if_missing(source, destination))
            source.write_text("first", encoding="utf-8")
            self.assertTrue(workspace.copy_if_missing(source, destination))
            source.write_text("second", encoding="utf-8")
            self.assertFalse(workspace.copy_if_missing(source, destination))
            self.assertEqual(destination.read_text(encoding="utf-8"), "first")

    def test_human_keys_handle_unicode_and_missing_identifiers(self) -> None:
        self.assertEqual(workspace.release_key("", "2024-01-02"), "2024-01-02")
        self.assertEqual(workspace.transaction_key("Ärztliche Übergabe", ""), "aerztliche-uebergabe--unknown")

    def test_workspace_selection_is_path_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            for path in ("spec", "model", "config", "mapping", "site", "test", "out", "state"):
                self.assertTrue((root / path).is_dir())
            self.assertFalse((root / "raw").exists())
            self.assertIsNone(load_json(root / "decor2hl7.json")["release"])
            set_release(root, RELEASE)
            set_transaction(root, TRANSACTION)
            # Selection commands do not create release/transaction artifact paths.
            self.assertFalse(release_spec_dir(root).exists())
            self.assertFalse(transaction_model_dir(root).exists())
            self.assertFalse(transaction_mapping_dir(root).exists())
            self.assertFalse(transaction_site_dir(root).exists())
            self.assertFalse(transaction_test_dir(root).exists())

    def test_external_input_directory_uses_override_then_workspace_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as configured, tempfile.TemporaryDirectory() as override:
            root = Path(tmp)
            init_workspace(root)
            settings = load_json(root / "decor2hl7.json")
            settings["input"]["directory"] = configured
            from decor2hl7.workspace import write_json
            write_json(root / "decor2hl7.json", settings)
            self.assertEqual(input_dir(root), Path(configured).resolve())
            self.assertEqual(input_dir(root, override), Path(override).resolve())
            settings = load_json(root / "decor2hl7.json")
            settings["input"]["directory"] = "relative-input"
            from decor2hl7.workspace import write_json
            write_json(root / "decor2hl7.json", settings)
            self.assertEqual(input_dir(root, required=False), (root / "relative-input").resolve())
            self.assertFalse((root / "raw").exists())

    def test_config_validation_requires_all_fields(self) -> None:
        errors = validate.check_config({"fields": {"a": {}, "b": {}}}, {"targets": {"T.value": {}}},
                                       {"fields": {"a": "cases:a"}}, {"fields": {"a": "T.value", "b": None}})
        self.assertIn("csv-mapping: missing model field b", errors)

    def test_mapping_identity_cannot_silently_cross_transactions(self) -> None:
        model = {
            "meta": {
                "dataset_id": "1.2.3", "transaction_id": "1.2.3.4",
                "transaction_effective_date": "2026-01-01T00:00:00",
            },
            "fields": {},
        }
        errors = validate.check_config(
            model,
            {"targets": {}, "document_template": {"name": "ExpectedTemplate"}},
            {"model": {"transaction_id": "9.9.9"}, "fields": {}},
            {"model": {"transaction_id": "8.8.8"}, "target": {"template": "Other"}, "fields": {}},
        )
        self.assertTrue(any("csv-mapping: transaction_id" in error for error in errors))
        self.assertTrue(any("cda-mapping: transaction_id" in error for error in errors))
        self.assertTrue(any("target template" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
