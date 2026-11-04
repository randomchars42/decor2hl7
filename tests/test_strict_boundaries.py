"""Regression cases for the whole-project review's admission failures."""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any
import unittest
import xml.etree.ElementTree as ET

from decor2hl7 import assertions, data, validate
from decor2hl7.hashing import sha256_file
from decor2hl7.retrieval.artifacts import artifact_integrity_problems
from decor2hl7.transforms import mapping_rules, validate_transform


class StrictBoundaryTests(unittest.TestCase):
    def test_non_null_mapping_entries_are_never_silently_discarded(self) -> None:
        for value in ({"targte": "Target.value"}, {}, "", [], 3, [None], {"target": "Target.value", "trasnform": {}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mapping_rules(value)
        for value in ({"soruce": "cases", "column": "x"}, {}, "cases:", {"source": "cases", "column": "x", "parser": "integer"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                data.mapping_locator(value)
        self.assertTrue(validate_transform({"type": "identity", "typo": True}))
        self.assertTrue(validate.check_config({"fields": {}}, {"targets": {}}, {"fields": []}, {"fields": {}}))
        self.assertEqual(mapping_rules(None), [])
        self.assertIsNone(data.mapping_locator(None))

    def test_input_transform_objects_cannot_extend_a_closed_source_domain(self) -> None:
        field = {"type": "code", "accepted_values": {"Alpha": {"code": "A", "code_system": "1.2.3"}}}
        for code, system in (("Z", "9.9.9"), ("A", "9.9.9")):
            with self.subTest(code=code, system=system), self.assertRaisesRegex(ValueError, "not admitted"):
                data.normalize_input_value("local", field, {}, {}, {"parse_as": "text", "transform": {"type": "enum", "map": {"local": {"code": code, "codeSystem": system}}}})
        value = data.normalize_input_value("local", field, {}, {}, {"parse_as": "text", "transform": {"type": "enum", "map": {"local": {"code": "A", "codeSystem": "1.2.3", "displayName": "untrusted"}}}})
        self.assertEqual(value["canonical"], "Alpha")
        self.assertEqual(value["displayName"], "Alpha")

    def test_unsupported_assertion_syntax_stays_unsupported_on_all_trees(self) -> None:
        for xml in ('<root xmlns:hl7="urn:hl7-org:v3"><hl7:entry/></root>', '<root/>'):
            root = ET.fromstring(xml)
            for expression in ("not(hl7:entry[position()=1])", "not(hl7:entry[unknown()])", "hl7:entry or not(hl7:entry[position()=1])", "not(bad:entry)"):
                with self.subTest(xml=xml, expression=expression):
                    self.assertIsNone(assertions.evaluate(expression, root, root))
        root = ET.fromstring('<root><entry code="two  spaces"/></root>')
        self.assertIs(assertions.evaluate("entry[@code='two  spaces']", root, root), True)
        self.assertIs(assertions.evaluate("entry[@code='two spaces']", root, root), False)
        self.assertTrue(validate.verify_compiled_cda({"validation_rules": [{"role": "error", "test": "not(hl7:entry[position()=1])"}]}))

    def test_numeric_parsing_is_exact_for_integers_and_rejects_nonfinite_values(self) -> None:
        self.assertEqual(data.normalize_value("9007199254740993", {"type": "integer"}, {}, {}), 9007199254740993)
        for kind, value in (("integer", "4.9"), ("integer", "NaN"), ("decimal", "NaN"), ("decimal", "Infinity")):
            with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                data.normalize_value(value, {"type": kind}, {}, {})
        self.assertEqual(data.normalize_value("1e309", {"type": "integer"}, {}, {}), 10 ** 309)
        self.assertEqual(data.normalize_value("1e309", {"type": "quantity"}, {}, {})["value"], 10 ** 309)
        self.assertEqual(data.normalize_value(9007199254740993, {"type": "quantity"}, {}, {})["value"], 9007199254740993)
        with self.assertRaises(ValueError):
            data.normalize_value("1e-10000", {"type": "decimal"}, {}, {})

    def test_invalid_scalar_quarantines_only_its_own_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cases.csv").write_text("case_id,n\nbad,NaN\ngood,4\n")
            records = data.ingest(root, {"fields": {"n": {"type": "integer"}}}, {"fields": {"n": "cases:n"}}, {}, {"input": {"case_source": "cases", "join_column": "case_id", "sources": {"cases": {"file": "cases.csv"}}}})
            self.assertTrue(records[0]["problems"])
            self.assertEqual(records[1]["values"]["n"], 4)
            self.assertFalse(records[1]["problems"])

    def test_csv_duplicate_headers_and_row_width_are_rejected(self) -> None:
        for content in ("id,n,n\na,120,80\n", "id,\na,80\n", "id,n\na,80,90\n", "id,n\na\n"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "cases.csv"
                path.write_text(content)
                with self.assertRaises(ValueError):
                    data._read_csv(path, {"input": {"delimiter": ","}})

    def test_singleton_from_multiple_source_rows_requires_one_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cases.csv").write_text("case_id\na\n")
            (root / "facts.csv").write_text("case_id,n,main\na,120,0\na,80,1\n")
            model = {"fields": {"n": {"type": "integer"}}}
            mapping = {"fields": {"n": "facts:n"}}
            site: dict[str, Any] = {"input": {"case_source": "cases", "join_column": "case_id", "sources": {"cases": {"file": "cases.csv"}, "facts": {"file": "facts.csv", "cardinality": "1:n"}}}}
            record = data.ingest(root, model, mapping, {}, site)[0]
            self.assertTrue(record["problems"])
            self.assertIsNone(record["values"].get("n"))
            site["input"]["sources"]["facts"]["primary"] = {"column": "main", "true_values": ["1"]}
            record = data.ingest(root, model, mapping, {}, site)[0]
            self.assertFalse(record["problems"])
            self.assertEqual(record["values"]["n"], 80)

    def test_repeat_cardinality_is_checked_per_parent_occurrence(self) -> None:
        model = {"fields": {}, "groups": {"parent": {"repeating": True, "min": 1, "max": 2}, "parent.child": {"parent": "parent", "repeating": True, "min": 1, "max": 2}}}
        self.assertTrue(validate.validate_record({"instances": {}}, model))
        record: dict[str, Any] = {"instances": {"parent": [{"instances": {"parent.child": [{}]}}, {"instances": {"parent.child": [{}, {}, {}]}}]}}
        problems = validate.validate_record(record, model)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["path"], "parent.child[1]")
        self.assertIn("maximum 2", problems[0]["message"])
        self.assertTrue(validate.validate_record({"instances": {}}, {"fields": {}, "groups": {"cycle": {"repeating": True, "parent": "cycle"}}}))
        optional = {"fields": {}, "groups": {"optional": {"min": 0}, "optional.children": {"parent": "optional", "repeating": True, "min": 1}}}
        self.assertEqual(validate.validate_record({"values": {}, "instances": {}}, optional), [])
        self.assertTrue(validate.validate_record({"values": {"optional.note": "active"}, "instances": {}}, optional))

    def test_successful_cached_forms_require_their_exact_recorded_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.xml"
            path.write_bytes(b"<template/>")
            record: dict[str, Any] = {"status": "ok", "requested": {}, "resolved": {}, "forms": {"analysis": {"path": path, "sha256": sha256_file(path)}}}
            self.assertEqual(artifact_integrity_problems(record), [])
            path.write_bytes(b"<modified/>")
            self.assertTrue(any("checksum mismatch" in problem for problem in artifact_integrity_problems(record)))
            record["forms"]["analysis"]["sha256"] = ""
            self.assertTrue(any("missing checksum" in problem for problem in artifact_integrity_problems(record)))


if __name__ == "__main__":
    unittest.main()
