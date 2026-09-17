from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


class ImportTests(unittest.TestCase):
    @staticmethod
    def _run_isolated(source_text: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        source = Path(__file__).resolve().parents[1] / "src"
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(source), environment.get("PYTHONPATH", ""),
        )))
        return subprocess.run(
            [sys.executable, "-c", source_text],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_data_import_does_not_initialize_cda(self) -> None:
        result = self._run_isolated(
            "import sys; "
            "from decor2hl7 import data; "
            "assert data.__name__ == 'decor2hl7.data'; "
            "assert not any(name == 'decor2hl7.cda' or "
            "name.startswith('decor2hl7.cda.') for name in sys.modules)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_validation_does_not_import_art_decor_xml_parser(self) -> None:
        result = self._run_isolated(
            "import sys; "
            "from decor2hl7 import validate; "
            "assert validate.__name__ == 'decor2hl7.validate'; "
            "assert 'decor2hl7.retrieval.xml' not in sys.modules"
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
