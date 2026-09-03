from __future__ import annotations

import json
import unittest
from pathlib import Path

from decor2hl7.compile.mapping import mapping_field_delta


REFERENCE_RELEASE = "2026.1.2"
REFERENCE_TRANSACTION = "notaufnahmeregister--60"
ALLOWED_BUILD_DEGRADED = {
    "valueset:1.2.276.0.76.11.53",
    "valueset:2.16.840.1.113762.1.4.1021.30",
    "valueset:2.16.840.1.113762.1.4.1099.12",
    "codesystem:1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00",
    "template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00",
}
MAX_GENERATION_MESSAGES = 3


class ReferenceClosureTests(unittest.TestCase):
    """Regression guards for the optional local companion reference workspace."""

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
            cls.model_dir / "mapping-audit.json",
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

    @staticmethod
    def _load(path: Path) -> dict:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_build_degradation_stays_inside_reviewed_boundary(self) -> None:
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

    def test_validator_generation_message_ceiling(self) -> None:
        manifest = self._load(
            self.model_dir / "conformance-validation" / "validator-manifest.json"
        )
        self.assertLessEqual(
            len(manifest.get("generation_messages", [])),
            MAX_GENERATION_MESSAGES,
        )
        self.assertTrue(manifest.get("executable"))

    def test_mapped_fields_do_not_regress_from_committed_baseline(self) -> None:
        baseline = self._load(
            Path(__file__).parent / "fixtures" / "reference-mapping-audit.json"
        )
        current = self._load(self.model_dir / "mapping-audit.json")
        delta = mapping_field_delta(baseline, current)
        self.assertEqual(delta["lost"], [])


if __name__ == "__main__":
    unittest.main()
