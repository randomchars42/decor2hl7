from __future__ import annotations

import unittest

from decor2hl7.text import normalize_match_text


class TextTests(unittest.TestCase):
    def test_normalize_match_text_removes_accents_case_and_punctuation(self) -> None:
        self.assertEqual(
            normalize_match_text("Ärztliche Befunde / CODE-7"),
            "arztlichebefundecode7",
        )


if __name__ == "__main__":
    unittest.main()
