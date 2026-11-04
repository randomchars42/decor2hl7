from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from decor2hl7.bundle import mapping_lock
from decor2hl7.integration_testing import setup_integration_test
from decor2hl7.scenario import packaged_scenario
from decor2hl7.workspace import load_json, write_json


class IntegrationSetupTests(unittest.TestCase):
    @staticmethod
    def prepare(root: Path) -> Path:
        release = {"key": "example", "date": "2026-01-01"}
        transaction = {"key": "example--1", "id": "1.2.3", "effective_date": "2026-01-01"}
        model = {"fields": {"note": {"type": "text", "repeat_chain": []}}, "groups": {}}
        cda: dict[str, object] = {"targets": {}, "document": [{
            "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1,
            "attributes": [], "children": [], "targets": [],
        }]}
        mapping = {"version": 2, "fields": {"note": None}}
        write_json(root / "decor2hl7.json", {"release": release, "transaction": transaction})
        model_dir = root / "model/example/example--1"
        write_json(model_dir / "model.json", model)
        write_json(model_dir / "cda.json", cda)
        mapping_dir = root / "mapping/example/example--1"
        write_json(mapping_dir / "cda-mapping.json", mapping)
        write_json(mapping_dir / "mapping-lock.json", mapping_lock(release, transaction, model, cda, mapping))
        scenario = root / "authored"
        write_json(scenario / "scenario.json", {
            "version": 1, "name": "custom", "release": "example", "transaction": transaction,
            "input": {"case_source": "cases", "sources": {"cases": {"file": "cases.csv", "cardinality": "1:1"}}},
            "expected": {"cases": ["A"], "documents": 1},
        })
        (scenario / "input").mkdir()
        (scenario / "input/cases.csv").write_text("case_id,note\nA,Authored note\n")
        return scenario

    def test_packaged_scenarios_require_the_exact_version_and_safe_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "no packaged scenario"):
            packaged_scenario("unpublished-release", "example--1", "valid-reference-cases")
        with self.assertRaisesRegex(ValueError, "identity component"):
            packaged_scenario("example", "../example--1", "valid-reference-cases")

    def test_existing_output_and_overlap_are_rejected_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "source"
            root.mkdir()
            existing = parent / "existing"
            existing.mkdir()
            marker = existing / "keep"
            marker.write_text("unchanged")
            with self.assertRaisesRegex(ValueError, "already exists"):
                setup_integration_test(root, existing)
            self.assertEqual(marker.read_text(), "unchanged")
            with self.assertRaisesRegex(ValueError, "separate"):
                setup_integration_test(root, root / "nested")
            self.assertFalse((root / "nested").exists())

    def test_mapping_lock_mismatch_leaves_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "source"
            scenario = self.prepare(root)
            write_json(root / "model/example/example--1/model.json", {"fields": {}, "groups": {}})
            with self.assertRaisesRegex(ValueError, "model_sha256"):
                setup_integration_test(root, parent / "output", scenario=str(scenario))
            self.assertFalse((parent / "output").exists())

    def test_output_cannot_be_nested_in_an_external_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "source"
            scenario = self.prepare(root)
            external = parent / "scenario"
            scenario.rename(external)
            with self.assertRaisesRegex(ValueError, "separate"):
                setup_integration_test(root, external / "generated", scenario=str(external))
            self.assertFalse((external / "generated").exists())

    def test_wrong_scenario_and_naive_timestamp_leave_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "source"
            scenario = self.prepare(root)
            with self.assertRaisesRegex(ValueError, "timezone"):
                setup_integration_test(root, parent / "output", scenario=str(scenario), written_at="2026-01-01T12:00:00")
            manifest = load_json(scenario / "scenario.json")
            manifest["release"] = "another-release"
            write_json(scenario / "scenario.json", manifest)
            with self.assertRaisesRegex(ValueError, "scenario identity mismatch"):
                setup_integration_test(root, parent / "output", scenario=str(scenario))
            self.assertFalse((parent / "output").exists())
            self.assertEqual(sorted(path.name for path in parent.iterdir()), ["source"])

    def test_invalid_receiver_configuration_fails_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "source"
            scenario = self.prepare(root)
            with self.assertRaisesRegex(ValueError, "transport.url"):
                setup_integration_test(root, parent / "output", scenario=str(scenario), receiver_url="file:///tmp/receiver")
            self.assertFalse((parent / "output").exists())


if __name__ == "__main__":
    unittest.main()
