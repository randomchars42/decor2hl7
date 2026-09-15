from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

from decor2hl7 import assertions
from decor2hl7.cda.art_decor import (
    inspect_template_constructs,
    require_supported_constructs,
)
from decor2hl7.cda.compile import compile_cda, select_template
from decor2hl7.cda import render as cda
from decor2hl7.cda.render import _validate_compiled_value
from decor2hl7.cda.semantics import required_value_set_ids
from decor2hl7.compile.structural import members_for_target
from decor2hl7.compile.transaction import compile_model
from decor2hl7.validate import verify_compiled_cda


class ArtDecorRuleInventoryTests(unittest.TestCase):
    def test_classifies_executable_prose_example_and_analysis_content(self) -> None:
        template = ET.fromstring('''<template id="doc" effectiveDate="2026">
          <context id="**"/>
          <attribute name="classCode" value="DOC"/>
          <element name="hl7:ClinicalDocument" minimumMultiplicity="1">
            <choice minimumMultiplicity="1" maximumMultiplicity="1">
              <element name="hl7:effectiveTime" datatype="TS"/>
              <include ref="time-parts">
                <element name="hl7:low" datatype="TS"/>
              </include>
            </choice>
            <constraint language="en-US"><p>Human-readable condition</p></constraint>
            <example type="valid"><observation><value code="x"/></observation></example>
            <let name="n" value="count(hl7:entry)"/>
            <assert test="$n &gt; 0">At least one entry</assert>
            <report test="$n &gt; 10">Many entries</report>
            <defineVariable name="v" path="hl7:value"/>
          </element>
        </template>''')

        coverage = inspect_template_constructs([template])

        self.assertEqual(coverage["unsupported"], [])
        self.assertEqual(coverage["constructs"]["constraint"], 1)
        self.assertEqual(coverage["constructs"]["example"], 1)
        # Instance/prose markup is opaque and is not mistaken for rule grammar.
        self.assertNotIn("observation", coverage["constructs"])
        self.assertNotIn("p", coverage["constructs"])
        self.assertEqual(coverage["dispositions"]["analysis-expansion"], 1)
        self.assertGreaterEqual(coverage["dispositions"]["validation"], 4)
        require_supported_constructs(coverage)

    def test_rejects_unknown_executable_child_instead_of_dropping_it(self) -> None:
        template = ET.fromstring('''<template id="doc">
          <element name="hl7:ClinicalDocument"><unknownRule/></element>
        </template>''')
        coverage = inspect_template_constructs([template])
        self.assertEqual(coverage["unsupported"][0]["construct"], "unknownRule")
        with self.assertRaisesRegex(ValueError, "unknownRule below element"):
            require_supported_constructs(coverage)

    def test_revision_selection_excludes_historical_only_statuses(self) -> None:
        active = ET.fromstring(
            '<template id="t" effectiveDate="2025" statusCode="active"/>'
        )
        retired = ET.fromstring(
            '<template id="t" effectiveDate="2026" statusCode="retired"/>'
        )
        templates = {"t": [active, retired]}
        self.assertIs(select_template(templates, "t", "dynamic"), active)
        self.assertIsNone(select_template(templates, "t", "2026"))

    def test_choice_and_template_context_attributes_remain_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "templates.xml"
            source.write_text('''<project>
  <template id="person" effectiveDate="2026" name="Person">
    <attribute name="classCode" value="PSN" isOptional="true"/>
    <element name="hl7:name" minimumMultiplicity="1" maximumMultiplicity="1"><text>Jane</text></element>
  </template>
  <template id="doc" effectiveDate="2026" name="Document">
    <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
      <include ref="person" flexibility="2026"/>
      <choice minimumMultiplicity="1" maximumMultiplicity="1">
        <element name="hl7:itemA" minimumMultiplicity="1" maximumMultiplicity="1"><text>A</text></element>
        <include ref="alternative" flexibility="2026"/>
      </choice>
    </element>
  </template>
  <template id="alternative" effectiveDate="2026" name="Alternative">
    <element name="hl7:itemB" minimumMultiplicity="1" maximumMultiplicity="1"><text>B</text></element>
  </template>
</project>''', encoding="utf-8")
            compiled = compile_cda([source], {
                "meta": {
                    "template_id": "doc",
                    "template_effective_date": "2026",
                }
            })
            root = compiled["document"][0]
            included = root["children"][0]
            choice = root["children"][1]
            self.assertEqual(included["attributes"][0]["value"], "PSN")
            self.assertEqual(choice["kind"], "choice")
            self.assertEqual((choice["min"], choice["max"]), (1, 1))
            self.assertEqual(
                [branch["kind"] for branch in choice["children"]],
                ["element", "include"],
            )

            payload, _ = cda.emit(
                {"key": "one", "values": {}}, {"fields": {}}, compiled,
                {"fields": {}}, {"null_flavor": {"missing_required": "NI"}},
            )
            document = ET.fromstring(payload)
            self.assertEqual(document.get("classCode"), "PSN")
            times = document.findall("{urn:hl7-org:v3}itemA")
            self.assertEqual([item.text for item in times], ["A"])
            self.assertEqual(verify_compiled_cda(compiled), [])

    def test_abstract_dataset_options_are_evidence_not_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<transaction id="dataset" transactionId="tx">
  <concept id="field" shortName="destination" type="item">
    <name>Destination</name>
    <valueDomain type="code"><conceptList id="list">
      <concept id="heading" type="A" level="0"><name>Internal</name></concept>
      <concept id="ward" type="L" level="1"><name>Ward</name></concept>
    </conceptList></valueDomain>
  </concept>
</transaction>''', encoding="utf-8")
            model = compile_model(transaction)
            field = model["fields"]["destination"]
            self.assertEqual(list(field["logical_domain"]["options"]), ["Ward"])
            self.assertEqual(
                field["coded_domain"]["abstract_members"],
                [{"id": "heading", "label": "Internal", "level": "0"}],
            )

    def test_dataset_rule_pipeline_keeps_object_relationships_as_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<dataset>
  <concept id="field" shortName="field" type="item">
    <name>Field</name><valueDomain type="string"/>
    <relationship type="ADAPT" ref="base" flexibility="2025"/>
    <relationship type="SPEC" ref="prototype" flexibility="2024"/>
  </concept>
</dataset>''', encoding="utf-8")
            model = compile_model(transaction)
            field = model["fields"]["field"]
            self.assertEqual(
                [(row["type"], row["execution"]) for row in field["relationships"]],
                [("ADAPT", "hint-only"), ("SPEC", "hint-only")],
            )
            self.assertEqual(field["type"], "text")
            self.assertEqual(
                [row["rule"] for row in model["meta"]["dataset_rule_pipeline"]],
                [
                    "transaction-concept-selection",
                    "inherit-or-contains-terminal-original",
                    "contains-current-stored-descendants",
                    "object-relationships",
                    "formal-terminology-binding",
                ],
            )

    def test_binding_strength_controls_constraints_not_evidence_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:routeCode"
      id="route" datatype="CE" strength="example">
    <vocabulary valueSet="1.2.3"/>
  </element></element>
</template>''', encoding="utf-8")
            compiled = compile_cda([source], {
                "meta": {"template_id": "doc", "template_effective_date": "2026"}
            })
            target = next(
                item for item in compiled["targets"].values()
                if item.get("element_id") == "route"
            )
            self.assertEqual(
                target["value_set_bindings"][0]["strength"], "example"
            )
            self.assertEqual(required_value_set_ids(target), set())
            self.assertEqual(
                members_for_target(target, {"1.2.3": [{"code": "X"}]}),
                ([], None),
            )

    def test_template_properties_and_datatype_flavours_are_executable(self) -> None:
        problems: list[str] = []
        target = {"datatype": "INT", "properties": [{
            "min_include": 3, "max_include": 15,
        }]}
        _validate_compiled_value(16, target, target, problems)
        self.assertEqual(len(problems), 1)
        _validate_compiled_value(10, target, target, [])
        with self.assertRaisesRegex(ValueError, "property constraints"):
            _validate_compiled_value(
                "ab", {"datatype": "ST", "properties": [{"min_length": 3}]},
                {"datatype": "ST", "properties": [{"min_length": 3}]}, [],
            )
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            _validate_compiled_value(
                0, {"datatype": "INT.POS"}, {"datatype": "INT.POS"}, [],
            )
        with self.assertRaisesRegex(ValueError, "14 timestamp digits"):
            _validate_compiled_value(
                "2026-09-12", {"datatype": "TS.DATETIME.MIN"},
                {"datatype": "TS.DATETIME.MIN"}, [],
            )
        binding_target = {
            "datatype": "CD", "required_binding_constraints": ["vs@2026"],
        }
        binding_registry = {"vs@2026": {
            "id": "vs", "resolved": True, "members": [["GOOD", "1.2.3"]],
        }}
        _validate_compiled_value(
            {"code": "GOOD", "codeSystem": "1.2.3"}, binding_target,
            binding_target, [], binding_registry,
        )
        with self.assertRaisesRegex(ValueError, "outside required"):
            _validate_compiled_value(
                {"code": "BAD", "codeSystem": "1.2.3"}, binding_target,
                binding_target, [], binding_registry,
            )

    def test_assert_report_and_free_form_constraints_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument" minimumMultiplicity="1">
    <let name="entries" value="count(hl7:entry)"/>
    <assert role="error" test="$entries &gt;= 0">Always valid</assert>
    <report role="warning" test="@code='OLD'">Deprecated code</report>
    <constraint language="en-US">A subordinate element SHALL be present conditionally.</constraint>
    <element name="hl7:entry" minimumMultiplicity="0" maximumMultiplicity="1"
        conformance="C">
      <constraint language="en-US">Present when the source contains an entry.</constraint>
    </element>
  </element>
</template>''', encoding="utf-8")
            compiled = compile_cda([source], {
                "meta": {"template_id": "doc", "template_effective_date": "2026"}
            })
            self.assertEqual(
                [rule["kind"] for rule in compiled["validation_rules"]],
                ["assert", "report"],
            )
            self.assertEqual(compiled["stats"]["reports"], 1)
            self.assertEqual(compiled["stats"]["textual_constraints"], 2)
            self.assertTrue(any(
                row["code"] == "textual-constraint-not-executable"
                for row in compiled["constraint_diagnostics"]
            ))
            self.assertTrue(any(
                row["code"] == "conditional-conformance-not-machine-enforced"
                for row in compiled["constraint_diagnostics"]
            ))
            generated = assertions.schematron(compiled)
            self.assertIn("<sch:assert", generated)
            self.assertIn("<sch:report", generated)

            root = ET.fromstring('<ClinicalDocument code="OLD"/>')
            errors, warnings = assertions.validate_contexts(root, [(
                root,
                [{
                    "kind": "report", "role": "warning",
                    "test": "@code='OLD'", "message": "Deprecated code",
                }],
                {},
            )])
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
