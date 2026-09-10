from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from decor2hl7.cda.parity import declared_endpoint_parity
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.artifacts import compiler_inputs, selected_closure_templates
from decor2hl7.compile.mapping import mapping_field_delta
from decor2hl7.compile.schematron import read_datatype_cooccurrences
from decor2hl7.cooccurrence import unavoidable_targets_problems
from decor2hl7.transforms import cda_target_name, mapping_rules


REFERENCE_RELEASE = "2026.1.2"
REFERENCE_TRANSACTION = "notaufnahmeregister--60"
# The reviewed phase-4 residue.  The AKTIN referral-actions value set cannot be
# expanded while its intension code system stays waived, and the CCD Product
# SPEC parent is published in no revision but `2007-04-01`, which must not
# substitute it (`DEC-004`, `DEC-012`).
ALLOWED_BUILD_DEGRADED = {
    "valueset:1.2.276.0.76.11.53",
    "codesystem:1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00",
    "template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00",
}
MAX_GENERATION_MESSAGES = 3
MAX_CRAWL_DEGRADED = 56
MAX_UNAVAILABLE_ARTIFACTS = 20
EXPECTED_UNRESOLVED_TEMPLATES = 1
ASSEMBLED_SHA256 = "c8540830e76c9aff7f6ad51d8d5ca596833f41e35f906b859909dcc69f7cc766"
SCHEMATRON_SHA256 = "05165794709a99ee12ba697b251499e3c3811ebee315344f6b3166039fa4fd99"
VALIDATOR_SHA256 = "e85facc96502027591b3b9c6240513f38e286ea4926a043a446985c85ebb9ad5"


class ReferenceClosureTests(unittest.TestCase):
    """Regression guards for the optional local companion reference workspace."""

    workspace: Path
    model_dir: Path

    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[2]
        cls.workspace = project_root / "test-workplace"
        cls.model_dir = (
            cls.workspace / "model" / REFERENCE_RELEASE / REFERENCE_TRANSACTION
        )
        required = [
            cls.workspace / "aktin.json",
            cls.model_dir / "build-diagnostics.json",
            cls.model_dir / "cda.json",
            cls.model_dir / "mapping-audit.json",
            cls.model_dir / "cda-mapping.proposed.json",
            cls.model_dir / "model.json",
            cls.model_dir / "conformance-validation" / "validator-manifest.json",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise unittest.SkipTest(
                "local companion reference workspace is unavailable: "
                + ", ".join(missing)
            )
        selection = cls._load(cls.workspace / "aktin.json")
        if (
            selection.get("release", {}).get("key") != REFERENCE_RELEASE
            or selection.get("transaction", {}).get("key")
            != REFERENCE_TRANSACTION
        ):
            raise unittest.SkipTest(
                "local companion workspace has a different selected release/transaction"
            )

    def test_compiler_covers_every_declared_ig_endpoint(self) -> None:
        cda = self._load(self.model_dir / "cda.json")
        release_dir = self.workspace / "spec" / REFERENCE_RELEASE
        transaction_dir = (
            release_dir / "transactions" / REFERENCE_TRANSACTION
        )
        inputs = compiler_inputs(release_dir, transaction_dir)
        parity = declared_endpoint_parity(
            inputs["templates"], cda, selected_closure_templates(cda)
        )
        self.assertEqual(parity["declared"], 2234)
        self.assertEqual(parity["compiled"], 2213)
        self.assertEqual(parity["declared_only"], 26)
        self.assertEqual(len(parity["fixed_structural_attributes"]), 25)
        self.assertEqual(len(parity["reviewed_branch_replacements"]), 1)
        self.assertEqual(parity["unexpected_missing"], [])

    def test_unmapped_fields_have_reproducible_possible_targets(self) -> None:
        model = self._load(self.model_dir / "model.json")
        cda = self._load(self.model_dir / "cda.json")
        audit = self._load(self.model_dir / "mapping-audit.json")
        proposal = self._load(self.model_dir / "cda-mapping.proposed.json")
        claimed_by, occurrence_claims = mapping_compiler._mapping_target_claims(
            proposal["fields"], cda
        )
        inventories: dict[str, dict[str, Any]] = {}
        for path, detail in audit["fields"].items():
            if detail.get("selected") is not None:
                continue
            inventory = mapping_compiler._possible_target_inventory(
                model["fields"][path], detail.get("context"), cda,
                claimed_by, occurrence_claims,
            )
            if inventory is not None:
                inventories[path] = inventory
        self.assertEqual(len(inventories), 20)
        self.assertTrue(all(value["items"] for value in inventories.values()))
        self.assertEqual(
            {value["document_pool_size"] for value in inventories.values()},
            {1058},
        )

        xray_path = (
            "diagnostik.bildgebende_diagnostik.rontgen.untersuchungsregion"
        )
        by_name = {
            item["target"]: item for item in inventories[xray_path]["items"]
        }
        expected = {
            "Plainchestxray.value",
            "Radiographyofspine.value",
            "Pelvisxray.value",
            "Plainradiographylimbstructure.value",
            "Plainradiography.value",
        }
        self.assertLessEqual(expected, set(by_name))
        self.assertTrue(
            by_name["Plainchestxray.value"][
                "containing_instance_claimed_by"
            ]
        )

    def test_datatype_cooccurrence_narrows_cedis_without_mapping_loss(self) -> None:
        model = self._load(self.model_dir / "model.json")
        cda = self._load(self.model_dir / "cda.json")
        audit = self._load(self.model_dir / "mapping-audit.json")
        accepted = self._load(
            self.workspace / "mapping" / REFERENCE_RELEASE
            / REFERENCE_TRANSACTION / "cda-mapping.json"
        )
        rules, summary = read_datatype_cooccurrences(
            (
                self.model_dir / "conformance-validation" / "generated"
                / "include"
            ).glob("DTr1_*.sch")
        )
        self.assertEqual(summary["supported_assertions"], 42)
        self.assertEqual(summary["unresolved_extends"], [])
        self.assertEqual(summary["inheritance_cycles"], [])
        cda["datatype_constraints"] = {
            "version": 1, "source": "generated-datatype-schematron",
            "rules": rules,
        }

        selected_targets = [
            cda_target_name(rule)
            for value in accepted["fields"].values()
            for rule in mapping_rules(value)
        ]
        self.assertFalse(any(
            unavoidable_targets_problems(cda, selected_targets).values()
        ))

        claimed_by, occurrence_claims = mapping_compiler._mapping_target_claims(
            accepted["fields"], cda
        )
        path = (
            "notfallanamnese.beschwerden_bei_vorstellung.ereigniseintritt"
        )
        inventory = mapping_compiler._possible_target_inventory(
            model["fields"][path], audit["fields"][path].get("context"), cda,
            claimed_by, occurrence_claims,
        )
        self.assertIsNotNone(inventory)
        assert inventory is not None
        self.assertEqual(inventory["document_pool_size"], 1058)
        by_name = {item["target"]: item for item in inventory["items"]}
        parent = by_name["Problemobservationcedis.effectiveTime"]
        low = by_name[
            "Problemobservationcedis.observation.effectiveTime.low"
        ]
        self.assertFalse(parent["available"])
        self.assertTrue(parent["conformance_conflicts"])
        self.assertFalse(low["available"])
        self.assertEqual(low["claimed_by"], [path])
        self.assertEqual(low["conformance_conflicts"], [])

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_build_degradation_stays_inside_reviewed_boundary(self) -> None:
        """The allowed set may shrink only through a deliberate fixture edit."""
        diagnostics = self._load(self.model_dir / "build-diagnostics.json")
        actual = {
            str(item.get("request_key") or "")
            for item in diagnostics.get("build_degraded", [])
        }
        self.assertLessEqual(actual, ALLOWED_BUILD_DEGRADED)
        self.assertLessEqual(
            diagnostics.get("summary", {}).get("build_degraded", 0),
            diagnostics.get("summary", {}).get("crawl_degraded", 0),
        )

    def test_closure_counts_and_assembled_input_do_not_regress(self) -> None:
        diagnostics = self._load(self.model_dir / "build-diagnostics.json")
        summary = diagnostics.get("summary", {})
        self.assertLessEqual(summary.get("crawl_degraded", 0), MAX_CRAWL_DEGRADED)
        self.assertLessEqual(
            summary.get("unavailable_artifacts", 0), MAX_UNAVAILABLE_ARTIFACTS
        )
        self.assertEqual(
            summary.get("unresolved_templates"), EXPECTED_UNRESOLVED_TEMPLATES
        )
        manifest = self._load(
            self.model_dir / "conformance-validation" / "validator-manifest.json"
        )
        self.assertEqual(manifest.get("assembled_sha256"), ASSEMBLED_SHA256)
        self.assertEqual(manifest.get("schematron_sha256"), SCHEMATRON_SHA256)
        self.assertEqual(manifest.get("validator_sha256"), VALIDATOR_SHA256)

    def test_validator_generation_message_ceiling(self) -> None:
        manifest = self._load(
            self.model_dir / "conformance-validation" / "validator-manifest.json"
        )
        self.assertLessEqual(
            len(manifest.get("generation_messages", [])),
            MAX_GENERATION_MESSAGES,
        )
        self.assertTrue(manifest.get("executable"))

    def test_validator_is_complete_for_the_selected_document(self) -> None:
        """Every rule that can apply to the selected document was generated.

        The residual upstream messages describe C-CDA medication templates the
        AKTIN document never instantiates; they stay listed as evidence but do
        not deny the claim (`DEC-019`).
        """
        manifest = self._load(
            self.model_dir / "conformance-validation" / "validator-manifest.json"
        )
        scopes = manifest.get("generation_message_scopes", [])
        self.assertEqual(
            len(scopes), len(manifest.get("generation_messages", []))
        )
        self.assertEqual(
            [
                scope for scope in scopes
                if scope.get("severity") == "error"
                and scope.get("in_selected_closure")
            ],
            [],
        )
        self.assertTrue(manifest.get("complete"))

    def test_mapped_fields_do_not_regress_from_committed_baseline(self) -> None:
        baseline = self._load(
            Path(__file__).parent / "fixtures" / "reference-mapping-audit.json"
        )
        current = self._load(self.model_dir / "mapping-audit.json")
        delta = mapping_field_delta(baseline, current)
        self.assertEqual(delta["lost"], [])
        baseline_counts = baseline["coverage_headline"]
        current_counts = current["summary"]["coverage_headline"]
        self.assertGreaterEqual(
            current_counts["mapped_datapoints"],
            baseline_counts["mapped_datapoints"],
        )
        self.assertLessEqual(
            current_counts["no_target_datapoints"],
            baseline_counts["no_target_datapoints"],
        )

    def test_mapping_gaps_are_persisted_and_rendered(self) -> None:
        audit = self._load(self.model_dir / "mapping-audit.json")
        for section in ("fields", "groups"):
            for path, detail in audit[section].items():
                formal = detail.get("formal_terminology", {})
                needs_gap = detail.get("selected") is None or (
                    isinstance(formal, dict)
                    and formal.get("status") == "unresolved"
                )
                if needs_gap:
                    self.assertIn("gap", detail, f"missing gap for {section}:{path}")
        terminology_gap = audit["fields"][
            "administrative_verlegungsentlassungsinformationen.typ_verlegung"
        ]["gap"]
        self.assertEqual(
            (terminology_gap["gate"], terminology_gap["kind"]),
            ("terminology", "closure"),
        )
        details = (self.model_dir / "cda-mapping-details.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("**Gap:** `semantic:shared_target` — reopens with:", details)
        self.assertIn("**Gap:** `terminology:closure` — reopens with:", details)


if __name__ == "__main__":
    unittest.main()
