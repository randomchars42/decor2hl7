from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

from decor2hl7.cda.parity import declared_endpoint_parity
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.artifacts import compiler_inputs, selected_closure_templates
from decor2hl7.compile.mapping import mapping_field_delta
from decor2hl7.compile.schematron import read_datatype_cooccurrences
from decor2hl7.cooccurrence import unavoidable_targets_problems
from decor2hl7.testing import json_digest
from decor2hl7.transforms import cda_target_name, mapping_rules


REFERENCE_RELEASE = "2026.1.2"
REFERENCE_TRANSACTION = "notaufnahmeregister--60"
# The reviewed terminology residue. The AKTIN referral-actions value set cannot
# be expanded while its intension code system stays waived (`DEC-004`,
# `DEC-012`). Missing SPEC editor prototypes are reported separately and do not
# degrade executable closure (`DEC-037`).
ALLOWED_BUILD_DEGRADED = {
    "valueset:1.2.276.0.76.11.53",
    "codesystem:1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00",
}
MAX_GENERATION_MESSAGES = 0
MAX_SELECTED_GENERATION_ERRORS = 0
MAX_CRAWL_DEGRADED = 2
MAX_UNAVAILABLE_ARTIFACTS = 1
EXPECTED_UNRESOLVED_TEMPLATES = 0
EXPECTED_UNRESOLVED_PROTOTYPES = 6
ASSEMBLED_SHA256 = "deb0b22a7ec2b53c1d4af8f73f9e023abe8316539e242624677b1b509e11fc0b"
SCHEMATRON_SHA256 = "517ba6a4dc62ea02de3d71946ea38520b3073528264872de75229c269f224e55"
VALIDATOR_SHA256 = "abbadf9200e0d6519308281a1c76692672c645298d40b9b4d22dccde7c93cbb7"


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
        self.assertEqual(parity["declared"], 1525)
        # Six template-context attributes are executable endpoints and remain
        # attached to their owning elements instead of being flattened away.
        self.assertEqual(parity["compiled"], 1510)
        self.assertEqual(parity["declared_only"], 18)
        self.assertEqual(len(parity["fixed_structural_attributes"]), 18)
        self.assertEqual(len(parity["reviewed_branch_replacements"]), 0)
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
        self.assertEqual(len(inventories), 29)
        self.assertTrue(all(value["items"] for value in inventories.values()))
        self.assertEqual(
            {value["document_pool_size"] for value in inventories.values()},
            {928},
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

    def test_datatype_cooccurrence_narrows_cedis_after_mapping_reset(self) -> None:
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
        self.assertEqual(inventory["document_pool_size"], 928)
        by_name = {item["target"]: item for item in inventory["items"]}
        parent = by_name["Problemobservationcedis.effectiveTime"]
        low = by_name[
            "Problemobservationcedis.observation.effectiveTime.low"
        ]
        self.assertFalse(parent["available"])
        self.assertTrue(parent["conformance_conflicts"])
        self.assertTrue(low["available"])
        self.assertEqual(low["claimed_by"], [])
        self.assertEqual(low["conformance_conflicts"], [])

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            return cast(dict[str, Any], json.load(handle))

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
        self.assertEqual(
            summary.get("unresolved_template_prototypes"),
            EXPECTED_UNRESOLVED_PROTOTYPES,
        )
        manifest = self._load(
            self.model_dir / "conformance-validation" / "validator-manifest.json"
        )
        selected = {
            (str(item["id"]), str(item["effective_date"]))
            for item in manifest.get("selected_closure_template_revisions", [])
        }
        assembled = ET.parse(
            self.model_dir / "conformance-validation" / "decor-assembled.xml"
        ).getroot()
        rules = assembled.find("rules")
        definitions = {
            (str(item.get("id") or ""), str(item.get("effectiveDate") or ""))
            for item in (rules if rules is not None else ())
            if item.tag == "template"
        }
        self.assertEqual(len(selected), 119)
        self.assertEqual(definitions, selected)
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

    def test_validator_selected_document_generation_is_complete(self) -> None:
        """Only the exact, formally closed selected revisions generate rules."""
        manifest = self._load(
            self.model_dir / "conformance-validation" / "validator-manifest.json"
        )
        scopes = manifest.get("generation_message_scopes", [])
        self.assertEqual(
            len(scopes), len(manifest.get("generation_messages", []))
        )
        selected_errors = [
            scope for scope in scopes
            if scope.get("severity") == "error"
            and scope.get("in_selected_closure")
        ]
        self.assertLessEqual(
            len(selected_errors), MAX_SELECTED_GENERATION_ERRORS,
        )
        self.assertEqual(len(selected_errors), MAX_SELECTED_GENERATION_ERRORS)
        self.assertTrue(manifest.get("complete"))
        self.assertTrue(manifest.get("executable"))

    def test_mapping_delta_matches_reviewed_relationship_boundary(self) -> None:
        baseline = self._load(
            Path(__file__).parent / "fixtures" / "reference-mapping-audit.json"
        )
        current = self._load(self.model_dir / "mapping-audit.json")
        delta = mapping_field_delta(baseline, current)
        self.assertEqual(delta["lost"], [
            "abschlussdiagnosen.abschlussdiagnose.freitext_abschlussdiagnose",
            "abschlussdiagnosen.abschlussdiagnose.icd10",
            "administrative_aufnahmeinformationen.aufnahmezeitpunkt",
            "administrative_verlegungsentlassungsinformationen.typ_verlegung",
            "dokumentationsinformationen.beginn_patientenbezogene_dokumentation.zeitpunkt_beginn_patientenbezogene_dokumentation",
            "masnahmen.medikamentose_therapie.medikation.dosierung.art_der_anwendung",
            "masnahmen.medikamentose_therapie.medikation.dosierung.freitext",
            "masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelcode",
            "masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelname",
            "notfallanamnese.zeitpunkt_erster_arztkontakt",
            "patient.anschrift.postleitzahl",
            "patient.identifikatoren.patienten_id",
        ])
        self.assertEqual(delta["gained"], [
            "hauptkostentrager.versicherungsverhaltnis.identifikation",
        ])
        current_counts = current["summary"]["coverage_headline"]
        self.assertEqual(current_counts["mapped_datapoints"], 84)
        self.assertEqual(current_counts["no_target_datapoints"], 32)

    def test_reviewed_recovery_overlay_matches_authoritative_mapping(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        recovery = self._load(
            repository / "docs" / "recovery"
            / "2026.1.2-notaufnahmeregister--60-reviewed-cda-overrides.json"
        )
        proposal = self._load(self.model_dir / "cda-mapping.proposed.json")
        reviewed = self._load(
            self.workspace / "mapping" / REFERENCE_RELEASE
            / REFERENCE_TRANSACTION / "cda-mapping.json"
        )
        model = self._load(self.model_dir / "model.json")
        cda = self._load(self.model_dir / "cda.json")

        proposal_null_reviewed = {
            path: value for path, value in reviewed["fields"].items()
            if value is not None and proposal["fields"].get(path) is None
        }
        reviewed_only_defaults = {
            path: value for path, value in reviewed["target_defaults"].items()
            if path not in proposal.get("target_defaults", {})
        }
        self.assertEqual(recovery["field_overrides"], proposal_null_reviewed)
        reviewed_only_structures = {
            name: value for name, value in reviewed["structures"].items()
            if proposal.get("structures", {}).get(name) != value
        }
        self.assertEqual(
            recovery["structure_overrides"], reviewed_only_structures,
        )
        self.assertEqual(
            recovery["field_review_overrides"],
            reviewed.get("field_reviews", {}),
        )
        self.assertEqual(
            recovery["target_default_overrides"], reviewed_only_defaults,
        )
        self.assertEqual(
            recovery["site_requirement_overrides"],
            reviewed.get("site_requirements", {}),
        )
        self.assertEqual(
            recovery["expected"],
            {
                "dataset_fields": 120,
                "generated_mapped_fields": 84,
                "reviewed_mapped_fields": 107,
                "field_override_count": 23,
                "structure_override_count": 3,
                "field_review_override_count": 5,
                "target_default_override_count": 6,
                "site_requirement_override_count": 6,
            },
        )
        self.assertEqual(recovery["identity"]["model_sha256"], json_digest(model))
        self.assertEqual(recovery["identity"]["cda_sha256"], json_digest(cda))
        product_name = (
            "masnahmen.medikamentose_therapie.medikation.medikament."
            "arzneimittel.arzneimittelname"
        )
        lot_number = (
            "masnahmen.medikamentose_therapie.medikation.medikament."
            "chargennummer"
        )
        material_name = (
            "UVMedicationInformationsimple.manufacturedProduct."
            "manufacturedMaterial.name"
        )
        self.assertEqual(
            reviewed["fields"][product_name],
            [
                {
                    "target": "UVMedicationInformationsimple.code",
                    "structure": "compose-medication-product-code",
                },
                {
                    "target": "Medikation.text",
                    "structure": "concatenate-medication-narrative",
                    "transform": {
                        "type": "narrative",
                        "prefix": "Arzneimittel: ",
                    },
                },
            ],
        )
        self.assertEqual(
            reviewed["fields"][lot_number],
            "UVMedicationInformationsimple.lotNumberText",
        )
        self.assertTrue(cda["targets"][material_name]["datatype_derived"])
        self.assertIsNone(cda["targets"][material_name]["element_id"])
        self.assertEqual(
            {item["source"] for item in cda["targets"][material_name]["provenance"]},
            {"cda-rim"},
        )
        self.assertFalse(
            cda["targets"]["UVMedicationInformationsimple.lotNumberText"].get(
                "datatype_derived", False,
            )
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
