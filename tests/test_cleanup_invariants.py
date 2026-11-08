from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from decor2hl7.compile.site import csv_mapping_proposal


class CleanupInvariantTests(unittest.TestCase):
    def test_mapping_products_are_independent_of_process_hash_seed(self) -> None:
        project = Path(__file__).resolve().parents[1]
        fixture = project / "tests/fixtures/mapping-order.py"
        outputs = []
        for seed in ("1", "42", "123"):
            result = subprocess.run(
                [sys.executable, str(fixture)],
                env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(project / "src")},
                capture_output=True, text=True, check=True,
            )
            outputs.append(result.stdout)
        self.assertTrue(outputs[0])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_site_proposals_reject_duplicate_csv_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cases.csv").write_text("case_id,note,note\ncase,A,B\n")
            with self.assertRaisesRegex(ValueError, "duplicate column"):
                csv_mapping_proposal(
                    {"meta": {}, "fields": {"note": {"type": "text", "name": "Note"}}},
                    root, "case_id",
                )

