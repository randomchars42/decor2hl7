from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


class ImportTests(unittest.TestCase):
    def test_data_import_does_not_initialize_cda(self) -> None:
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
                    "import sys; "
                    "from decor2hl7 import data; "
                    "assert data.__name__ == 'decor2hl7.data'; "
                    "assert not any(name == 'decor2hl7.cda' or "
                    "name.startswith('decor2hl7.cda.') for name in sys.modules)"
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
