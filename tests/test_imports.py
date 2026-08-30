from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


class ImportTests(unittest.TestCase):
    def test_semantics_import_does_not_initialize_cda_renderer(self) -> None:
        environment = os.environ.copy()
        source = Path(__file__).resolve().parents[1] / "src"
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(source), environment.get("PYTHONPATH", ""),
        )))
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from decor2hl7.semantics import accepted_values; "
                    "from decor2hl7 import cda; "
                    "assert callable(cda.emit); "
                    "assert callable(cda.compile_cda)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
