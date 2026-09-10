from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
