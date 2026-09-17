from __future__ import annotations

import unittest

from decor2hl7.value_format import (
    preferred_mapping_value,
    range_quantities,
    scalar_quantity,
)


class ValueFormatTests(unittest.TestCase):
    def test_scalar_quantity_preserves_the_normalized_value_members(self) -> None:
        self.assertEqual(
            scalar_quantity({"value": 12.5, "unit": " mmHg "}),
            (12.5, " mmHg "),
        )
        self.assertIsNone(scalar_quantity({"unit": "mmHg"}))

    def test_range_quantities_preserves_partial_bounds(self) -> None:
        self.assertEqual(
            range_quantities({
                "low": {"value": 1, "unit": "mg"},
                "high": None,
            }),
            ((1, "mg"), None),
        )
        self.assertIsNone(range_quantities({"value": 1, "unit": "mg"}))

    def test_preferred_mapping_value_uses_the_requested_policy_order(self) -> None:
        value = {"raw": "owner wording", "displayName": "Display"}
        self.assertEqual(
            preferred_mapping_value(value, ("displayName", "raw")),
            "Display",
        )
        self.assertEqual(
            preferred_mapping_value(value, ("raw", "displayName")),
            "owner wording",
        )


if __name__ == "__main__":
    unittest.main()
