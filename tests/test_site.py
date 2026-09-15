from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from decor2hl7.compile import site
from decor2hl7.workspace import load_json


class SiteProposalTests(unittest.TestCase):
    def test_codes_mapping_prepopulates_option_identities(self) -> None:
        model = {
            "fields": {
                "triage.color": {
                    "type": "code",
                    "accepted_values": {
                        "rot": {},
                        "orange": {},
                        "gelb": {},
                    },
                }
            }
        }
        proposal, report = site.codes_mapping_proposal(
            model, {"fields": {"triage.color": None}}, None
        )
        self.assertEqual(
            proposal["fields"]["triage.color"],
            {"rot": "rot", "orange": "orange", "gelb": "gelb"},
        )
        self.assertIn("3 canonical values accepted directly", report)
        self.assertIn("No aliases require configuration", report)

    def test_codes_mapping_contains_model_codes_and_display_aliases(self) -> None:
        model = {
            "fields": {
                "referral": {
                    "name": "Zuweisung",
                    "type": "code",
                    "accepted_values": {
                        "ohne": {
                            "code": "NPHYS",
                            "code_system": "1.2.276.0.76.5.440",
                            "display_name": "Zuweisung nicht durch Arzt",
                        },
                        "Vertragsarzt/Praxis": {
                            "code": "VAP",
                            "code_system": "1.2.276.0.76.5.440",
                            "display_name": "Vertragsarzt/Praxis",
                        },
                    },
                }
            }
        }
        proposal, _ = site.codes_mapping_proposal(model, {"fields": {}}, None)
        values = proposal["fields"]["referral"]
        self.assertEqual(values["NPHYS"], "ohne")
        self.assertEqual(values["Zuweisung nicht durch Arzt"], "ohne")
        self.assertEqual(values["ohne"], "ohne")
        self.assertEqual(values["VAP"], "Vertragsarzt/Praxis")

    def test_write_code_mapping_is_build_side_and_populated(self) -> None:
        model = {
            "fields": {
                "transport": {
                    "type": "code",
                    "accepted_values": {
                        "KTW": {
                            "code": "1",
                            "code_system": "1.2.3",
                            "display_name": "KTW",
                        },
                        "RTW": {
                            "code": "2",
                            "code_system": "1.2.3",
                            "display_name": "RTW",
                        },
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = site.write_code_mapping(root, model)
            stored = load_json(root / "codes-mapping.proposed.json")
            self.assertEqual(result, stored)
            self.assertEqual(stored["fields"]["transport"]["1"], "KTW")
            self.assertEqual(stored["fields"]["transport"]["2"], "RTW")
            self.assertTrue((root / "codes-mapping.md").exists())


if __name__ == "__main__":
    unittest.main()
