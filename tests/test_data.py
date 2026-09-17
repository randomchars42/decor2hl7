from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from decor2hl7 import data, validate
from decor2hl7.cda.semantics import direct_compatibility
from decor2hl7.transforms import OMIT, apply_transform


class DataPipelineTests(unittest.TestCase):
    def test_quantity_unit_accepts_german_hour_label_for_ucum_h(self) -> None:
        field = {"type": "quantity", "unit": "Stunden"}
        target = {
            "datatype": "PQ",
            "path": "hl7:observation/hl7:value",
            "writable": True,
            "logical_types": ["quantity", "decimal", "duration"],
            "value_representation": {
                "kind": "quantity",
                "logical_types": ["quantity", "decimal", "duration"],
                "attributes": ["value", "unit"],
                "scalar_attribute": "value",
            },
            "unit": "h",
        }

        self.assertEqual(direct_compatibility(field, target), (True, []))

    def test_code_normalization_rejects_unmapped_finite_domain_code(self) -> None:
        field = {"type": "code", "accepted_values": {"rot": {"code": "R", "code_system": "1.2.3", "display_name": "rot"}}}
        site = {"null_flavor": {"unmapped_code": "OTH"}, "input": {}}
        self.assertEqual(data.normalize_value("1", field, {"1": "rot"}, site)["code"], "R")
        with self.assertRaisesRegex(ValueError, "not admitted"):
            data.normalize_value("X", field, {}, site)

    def test_open_code_normalization_retains_raw_value_without_null_flavor(self) -> None:
        open_field = {
            "type": "code",
            "formal_terminology": {
                "status": "unconstrained", "bound": False, "complete": True,
            },
        }
        self.assertEqual(
            data.normalize_value(
                "local-code", open_field, {},
                {"null_flavor": {"unmapped_code": "OTH"}},
            ),
            {"raw": "local-code"},
        )

        unresolved = {
            "type": "code",
            "formal_terminology": {
                "status": "unresolved", "bound": True, "complete": False,
            },
        }
        with self.assertRaisesRegex(ValueError, "not admitted"):
            data.normalize_value("local-code", unresolved, {}, {})
        with self.assertRaisesRegex(ValueError, "finite dataset domain"):
            data.normalize_value(
                "local-code", unresolved,
                {"local-code": {"code": "X", "codeSystem": "1.2.3"}},
                {},
            )

    def test_input_transform_cannot_create_null_flavor(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot create.*nullFlavor"):
            data.normalize_input_value(
                "unknown",
                {"type": "code"},
                {}, {},
                {"parse_as": "text", "transform": {
                    "type": "enum",
                    "map": {"unknown": {"nullFlavor": "OTH"}},
                }},
            )

    def test_datetime_requires_time_when_precision_does(self) -> None:
        with self.assertRaises(ValueError):
            data.normalize_value("2026-08-21", {"type": "datetime", "precision": "YMDHM"}, {}, {"timezone": "Europe/Berlin", "input": {}})

    def test_datetime_minimum_precision_preserves_more_precise_input(self) -> None:
        site = {"timezone": "Europe/Berlin", "input": {}}
        self.assertEqual(
            data.normalize_value(
                "2026-08-21T12:34:56+02:00",
                {"type": "datetime", "precision": "YMDHM"}, {}, site,
            ),
            "2026-08-21T12:34:56+02:00",
        )
        self.assertEqual(
            data.normalize_value(
                "2026-08-21T12:34:56+02:00",
                {"type": "datetime", "precision": "YMD"}, {}, site,
            ),
            "2026-08-21T12:34:56+02:00",
        )

    def test_multiple_primary_rows_are_rejected_without_mutation(self) -> None:
        rows = [{"main": "0", "v": "a"}, {"main": "1", "v": "b"}, {"main": "1", "v": "c"}]
        ordered, problems = data._order_rows(rows, {"column": "main", "true_values": ["1"], "false_value": "0"})
        self.assertEqual([row["v"] for row in ordered], ["a", "b", "c"])
        self.assertEqual([row["main"] for row in ordered], ["0", "1", "1"])
        self.assertEqual(problems[0]["severity"], "error")

    def test_boolean_leading_diagnosis_becomes_sequence_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("case_id\nP1\n", encoding="utf-8")
            (raw / "diagnoses.csv").write_text(
                "case_id,leading,icd,text\n"
                "P1,false,S93.4,Distorsion\n"
                "P1,true,S82.1,Tibiakopffraktur\n",
                encoding="utf-8",
            )
            model: dict[str, Any] = {
                "groups": {"diagnoses": {"repeating": True}},
                "fields": {
                    "diagnoses.sequence": {
                        "type": "integer", "repeat": "diagnoses",
                        "repeat_chain": ["diagnoses"],
                    },
                    "diagnoses.icd": {
                        "type": "text", "repeat": "diagnoses",
                        "repeat_chain": ["diagnoses"],
                    },
                    "diagnoses.text": {
                        "type": "text", "repeat": "diagnoses",
                        "repeat_chain": ["diagnoses"],
                    },
                },
            }
            csv_mapping = {"join": {"column": "case_id"}, "fields": {
                "diagnoses.sequence": {
                    "source": "diagnoses", "column": "leading", "parse_as": "boolean",
                    "transform": {
                        "type": "enum", "select": "value",
                        "map": {"true": 1, "false": None},
                    },
                },
                "diagnoses.icd": "diagnoses:icd",
                "diagnoses.text": "diagnoses:text",
            }}
            site = {"input": {
                "case_source": "cases",
                "sources": {
                    "cases": {"file": "cases.csv", "cardinality": "1:1"},
                    "diagnoses": {
                        "file": "diagnoses.csv", "cardinality": "1:n",
                        "primary": {"column": "leading", "required": False},
                    },
                },
            }}
            record = data.ingest(raw, model, csv_mapping, {"fields": {}}, site)[0]
            self.assertEqual(
                data.field_value(record, "diagnoses.sequence", model["fields"]["diagnoses.sequence"]),
                [1, None],
            )
            self.assertEqual(
                data.field_value(record, "diagnoses.icd", model["fields"]["diagnoses.icd"]),
                ["S82.1", "S93.4"],
            )
            self.assertFalse(record["problems"])

    def test_codes_mapping_must_resolve_to_canonical_value(self) -> None:
        errors = validate.check_config(
            {"fields": {"status": {"accepted_values": {"active": {"code": "A"}}}}},
            {"targets": {}},
            {"fields": {"status": None}},
            {"fields": {"status": None}},
            {"fields": {"status": {"1": "typo"}}},
        )
        self.assertTrue(any("unknown canonical value" in error for error in errors))

    def test_unbound_code_accepts_explicit_site_code_identity(self) -> None:
        field = {"type": "code", "accepted_values": {}}
        translation = {
            "LOCAL": {
                "code": "LOCAL",
                "codeSystem": "2.25.186589136976866630731912149362364494481",
                "displayName": "Local procedure",
            },
        }
        errors = validate.check_config(
            {"fields": {"procedure": field}},
            {"targets": {}},
            {"fields": {"procedure": None}},
            {"fields": {"procedure": None}},
            {"fields": {"procedure": translation}},
        )
        self.assertEqual(errors, [])
        value = data.normalize_value("LOCAL", field, translation, {})
        self.assertEqual(value["code"], "LOCAL")
        self.assertEqual(
            value["codeSystem"],
            "2.25.186589136976866630731912149362364494481",
        )

    def test_csv_missing_join_column_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("wrong,value\nP1,x\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required CSV column"):
                data.ingest(
                    raw,
                    {"fields": {"x": {"type": "text"}}},
                    {"join": {"column": "patient_id"}, "fields": {"x": "cases:value"}},
                    {"fields": {}},
                    {"input": {"case_source": "cases", "sources": {"cases": {"file": "cases.csv", "cardinality": "1:1"}}}},
                )

    def test_csv_duplicate_one_to_one_key_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("patient_id,value\nP1,a\nP1,b\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configured 1:1"):
                data.ingest(
                    raw,
                    {"fields": {"x": {"type": "text"}}},
                    {"join": {"column": "patient_id"}, "fields": {"x": "cases:value"}},
                    {"fields": {}},
                    {"input": {"case_source": "cases", "sources": {"cases": {"file": "cases.csv", "cardinality": "1:1"}}}},
                )

    def test_csv_orphan_detail_key_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("patient_id,value\nP1,a\n", encoding="utf-8")
            (raw / "detail.csv").write_text("patient_id,item\nP2,x\n", encoding="utf-8")
            model = {"fields": {"x": {"type": "text"}, "d": {"type": "text", "repeat": "g"}}}
            mapping = {"join": {"column": "patient_id"}, "fields": {"x": "cases:value", "d": "detail:item"}}
            site = {"input": {"case_source": "cases", "sources": {
                "cases": {"file": "cases.csv", "cardinality": "1:1"},
                "detail": {"file": "detail.csv", "cardinality": "1:n"},
            }}}
            with self.assertRaisesRegex(ValueError, "absent from case source"):
                data.ingest(raw, model, mapping, {"fields": {}}, site)

    def test_uncoded_code_option_stays_target_neutral_until_transformed(self) -> None:
        field = {"type": "code", "accepted_values": {"Label": {"display_name": "Label"}, "Coded": {"code": "A", "code_system": "9", "display_name": "Coded"}}}
        site = {"null_flavor": {"unmapped_code": "OTH"}}
        logical = data.normalize_value("Label", field, {}, site)
        self.assertEqual(logical, {"raw": "Label", "canonical": "Label"})
        self.assertEqual(
            apply_transform(logical, {
                "type": "ordinal", "map": {"Label": 2},
            }),
            2,
        )
        coded = data.normalize_value("Label", field, {"Label": "Coded"}, site)
        self.assertEqual(coded["code"], "A")
        self.assertEqual(coded["codeSystem"], "9")

    def test_textual_ordinal_uses_leading_numeric_rank(self) -> None:
        field = {"type": "ordinal", "accepted_values": {"1 keine": {"display_name": "1 keine"}, "2 Schmerzreiz": {"display_name": "2 Schmerzreiz"}}}
        self.assertEqual(data.normalize_value("1 keine", field, {}, {}), 1)
        self.assertEqual(data.normalize_value("raw-two", field, {"raw-two": "2 Schmerzreiz"}, {}), 2)

    def test_ordinal_transform_can_explicitly_omit_a_value(self) -> None:
        self.assertIs(
            apply_transform(
                {"canonical": "not applicable"},
                {"type": "ordinal", "map": {"not applicable": None}},
            ),
            OMIT,
        )

    def test_quantity_normalization_preserves_scalar_and_range_units(self) -> None:
        self.assertEqual(
            data.normalize_value("2.5 mg", {"type": "quantity"}, {}, {}),
            {"value": 2.5, "unit": "mg"},
        )
        self.assertEqual(
            data.normalize_value("1-2 {tablet}", {"type": "quantity"}, {}, {}),
            {
                "low": {"value": 1, "unit": "{tablet}"},
                "high": {"value": 2, "unit": "{tablet}"},
            },
        )
        self.assertEqual(
            data.normalize_value("3", {"type": "quantity", "unit": "g/h"}, {}, {}),
            {"value": 3, "unit": "g/h"},
        )
        self.assertEqual(
            data.normalize_value("1e3 mg", {"type": "quantity"}, {}, {}),
            {"value": 1000, "unit": "mg"},
        )
        self.assertEqual(
            data.normalize_value("1,5–2,5 mg", {"type": "quantity"}, {}, {
                "input": {"decimal_separator": ","},
            }),
            {
                "low": {"value": 1.5, "unit": "mg"},
                "high": {"value": 2.5, "unit": "mg"},
            },
        )
        self.assertEqual(
            data.normalize_value(
                "2 g / h",
                {"type": "quantity", "units": ["ml/h", "g/h"]},
                {},
                {"input": {"unit_aliases": {"g / h": "g/h"}}},
            ),
            {"value": 2, "unit": "g/h"},
        )

    def test_quantity_normalization_rejects_ambiguous_or_invalid_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicts with fixed dataset unit"):
            data.normalize_value(
                "3 mg", {"type": "quantity", "unit": "g"}, {}, {}
            )
        with self.assertRaisesRegex(ValueError, "low exceeds high"):
            data.normalize_value("3-2 mg", {"type": "quantity"}, {}, {})
        with self.assertRaisesRegex(ValueError, "must contain low, high"):
            data.normalize_value(
                {"low": 1}, {"type": "quantity"}, {}, {}
            )
        with self.assertRaisesRegex(ValueError, "must be finite"):
            data.normalize_value(float("inf"), {"type": "quantity"}, {}, {})

    def test_quantity_validation_checks_each_range_bound(self) -> None:
        problems = validate.validate_record(
            {"values": {"dose": {
                "low": {"value": 0, "unit": "mg"},
                "high": {"value": 12, "unit": "mg"},
            }}},
            {"fields": {"dose": {
                "type": "quantity", "min_value": 1, "max_value": 10,
                "repeat_chain": [],
            }}},
        )
        self.assertEqual(
            [(item["path"], item["message"]) for item in problems],
            [
                ("dose.low", "0 is below minimum 1"),
                ("dose.high", "12 is above maximum 10"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
