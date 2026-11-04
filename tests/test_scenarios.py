from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from decor2hl7.scenario import prepare_scenario_input


TRIAGE_ROOT = "ersteinschatzung.parameter_der_ersteinschatzung"
METHOD = f"{TRIAGE_ROOT}.verwendetes_ersteinschatzungssystem"
RESULT = f"{TRIAGE_ROOT}.ergebnis_der_ersteinschatzung"
ESI = f"{TRIAGE_ROOT}.esitriage"
MTS_ROOT = f"{TRIAGE_ROOT}.manchester_triage_system"
PRESENTATION = f"{MTS_ROOT}.mtsprasentationsdiagramm"
INDICATORS = {
    "rot": f"{MTS_ROOT}.mtsindikator.mtsindikatoren_rot",
    "orange": f"{MTS_ROOT}.mtsindikator.mtsindikatoren_orange",
    "gelb": f"{MTS_ROOT}.mtsindikator.mtsindikatoren_gelb",
    "grün": f"{MTS_ROOT}.mtsindikator.mtsindikatoren_grun",
}
DISCHARGE = "administrative_verlegungsentlassungsinformationen.typ_entlassung"
TRANSFER = "administrative_verlegungsentlassungsinformationen.typ_verlegung"
GCS_COMPONENTS = [
    "scores.glasgow_coma_scale_gcs.gcs_augenoffnen",
    "scores.glasgow_coma_scale_gcs.gcs_verbale_antwort",
    "scores.glasgow_coma_scale_gcs.gcs_motorische_antwort",
]
GCS_SUM = "scores.glasgow_coma_scale_gcs.gcs_summe"


class AuthoredScenarioTests(unittest.TestCase):
    def test_valid_reference_cases_preserve_clinical_branch_invariants(self) -> None:
        scenario = (
            Path(__file__).parent
            / "fixtures/scenarios/2026.1.2/notaufnahmeregister--60"
            / "valid-reference-cases"
        )
        manifest = json.loads((scenario / "scenario.json").read_text())
        with (scenario / "input/cases.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(
            [row["case_id"] for row in rows], manifest["expected"]["cases"]
        )
        self.assertEqual(
            [row[RESULT] for row in rows],
            ["rot", "rot", "orange", "gelb", "grün", "blau"],
        )
        for row in rows:
            expectation = manifest["expected"]["case_fields"][row["case_id"]]
            self.assertTrue(all(row[path] for path in expectation["present"]))
            self.assertTrue(all(not row[path] for path in expectation["absent"]))
            populated_indicators = [
                color for color, path in INDICATORS.items() if row[path]
            ]
            if row[METHOD] == "ESI":
                self.assertTrue(row[ESI])
                self.assertFalse(row[PRESENTATION])
                self.assertEqual(populated_indicators, [])
            else:
                self.assertEqual(row[METHOD], "MTS")
                self.assertFalse(row[ESI])
                self.assertTrue(row[PRESENTATION])
                expected = [] if row[RESULT] == "blau" else [row[RESULT]]
                self.assertEqual(populated_indicators, expected)

            self.assertNotEqual(bool(row[DISCHARGE]), bool(row[TRANSFER]))
            component_sum = sum(int(row[path].split()[0]) for path in GCS_COMPONENTS)
            self.assertEqual(component_sum, int(row[GCS_SUM]))

    def test_invalid_expectations_leave_inputs_and_site_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = root / "scenario"
            (scenario / "input").mkdir(parents=True)
            (scenario / "input/cases.csv").write_text("case_id,note\ncase,Example\n")
            transaction = {"key": "test", "id": "1.2.3", "effective_date": "2026-01-01"}
            (scenario / "scenario.json").write_text(json.dumps({
                "version": 1, "release": "test", "transaction": transaction,
                "input": {"case_source": "cases", "sources": {"cases": {"file": "cases.csv"}}},
                "expected": {"cases": ["different-case"]},
                "site": {"cda": {"values": {"changed": "value"}}},
            }))
            site: dict[str, Any] = {"input": {}, "cda": {"values": {"original": "value"}}}
            original = json.dumps(site, sort_keys=True)
            destination = root / "prepared"
            with self.assertRaisesRegex(ValueError, "expected.cases"):
                prepare_scenario_input(
                    scenario, destination, {"key": "test"}, transaction,
                    {"fields": {"note": {"repeat_chain": []}}, "groups": {}}, site,
                )
            self.assertFalse(destination.exists())
            self.assertEqual(json.dumps(site, sort_keys=True), original)

    def test_authored_scenario_carries_explicit_site_cda_values(self) -> None:
        scenario = (
            Path(__file__).parent
            / "fixtures/scenarios/2026.1.2/notaufnahmeregister--60"
            / "valid-reference-cases"
        )
        manifest = json.loads((scenario / "scenario.json").read_text())
        release = {"key": manifest["release"]}
        transaction = manifest["transaction"]
        headers: set[str] = set()
        for source in manifest["input"]["sources"].values():
            with (scenario / "input" / source["file"]).open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                headers.update(csv.DictReader(handle).fieldnames or [])
        model: dict[str, Any] = {
            "fields": {
                header: {
                    "repeat_chain": [],
                    "type": "code" if header in manifest["codes"] else "text",
                }
                for header in headers
                if header != "case_id" and not header.startswith("occurrence_")
            },
            "groups": {
                path: {"repeating": True}
                for source in manifest["input"]["sources"].values()
                for path in source.get("occurrence_keys", {})
            },
        }
        for source in manifest["input"]["sources"].values():
            chain = list(source.get("occurrence_keys", {}))
            with (scenario / "input" / source["file"]).open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                for header in csv.DictReader(handle).fieldnames or []:
                    if header in model["fields"] and chain:
                        model["fields"][header]["repeat_chain"] = chain
        site: dict[str, Any] = {
            "input": {},
            "cda": {"values": {}, "fallback_if_active": {}},
        }

        with tempfile.TemporaryDirectory() as tmp:
            prepared = prepare_scenario_input(
                scenario, Path(tmp), release, transaction, model, site
            )

        self.assertEqual(
            site["cda"]["values"], manifest["site"]["cda"]["values"]
        )
        self.assertEqual(
            site["cda"]["fallback_if_active"],
            manifest["site"]["cda"]["fallback_if_active"],
        )
        self.assertEqual(prepared.metadata["codes"], manifest["codes"])


if __name__ == "__main__":
    unittest.main()
