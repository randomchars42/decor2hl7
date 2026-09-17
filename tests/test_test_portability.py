from __future__ import annotations

import unittest
from pathlib import Path


class TestFixturePortabilityTests(unittest.TestCase):
    def test_selected_profile_identifiers_stay_in_reference_suites(self) -> None:
        tests_dir = Path(__file__).parent
        allowed = {
            "test_closure.py",
            "test_reference_sources.py",
            "test_scenarios.py",
        }
        markers = (
            "ak" + "tin-",
            "AK" + "TIN",
            "2026." + "1.2",
            "notaufnahme" + "register--60",
            "2.16.840.1.113883.2.6.60.3.4." + "60",
            "Notaufnahme" + "register Transitionsversion",
        )
        violations: list[str] = []
        for path in sorted(tests_dir.glob("test_*.py")):
            if path.name in allowed:
                continue
            source = path.read_text(encoding="utf-8")
            for marker in markers:
                if marker.casefold() in source.casefold():
                    violations.append(f"{path.name}: {marker}")
        self.assertEqual(
            violations, [],
            "selected-profile identifiers leaked into generic tests",
        )


if __name__ == "__main__":
    unittest.main()
