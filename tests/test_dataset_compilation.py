from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from decor2hl7 import data
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile import site as site_compiler
from decor2hl7.compile.transaction import compile_model
from decor2hl7.compile.structural import value_set_members
from decor2hl7.cda.compile import compile_cda
from decor2hl7.retrieval.references import (
    display_references,
    hard_references,
    soft_references,
)
from decor2hl7.retrieval.api import artifact_representations
from decor2hl7.domain import accepted_values
from decor2hl7.transforms import apply_transform


RELEASE = {"key": "release-v1", "label": "release-v1", "date": "2024-01-02T03:04:05", "status": "final"}


class DatasetCompilationTests(unittest.TestCase):
    def test_reviewed_model_extensions_compile_with_exact_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''
<dataset id="d">
  <valueSet id="1.2.3" effectiveDate="2026-01-01">
    <concept code="A" codeSystem="9.8.7"><name>Alpha</name></concept>
  </valueSet>
  <concept type="group" shortName="encounter" id="g"
           minimumMultiplicity="0" maximumMultiplicity="*">
    <name>Encounter</name>
  </concept>
</dataset>''', encoding="utf-8")
            extension = {
                "version": 1,
                "status": "reviewed",
                "collision_policy": "error",
                "fields": {
                    "encounter.local_status": {
                        "name": "Local status",
                        "parent": "encounter",
                        "type": "code",
                        "min": 0,
                        "max": 1,
                        "value_set": {
                            "id": "1.2.3",
                            "effective_date": "2026-01-01",
                        },
                        "reason": "The reviewed CDA contract requires it.",
                    }
                },
            }

            model = compile_model(transaction, model_extensions=extension)

            field = model["fields"]["encounter.local_status"]
            self.assertEqual(field["concept"], "model-extension:encounter.local_status")
            self.assertEqual(field["repeat_chain"], ["encounter"])
            self.assertEqual(field["formal_terminology"]["status"], "bound")
            self.assertEqual(field["accepted_values"]["Alpha"]["code"], "A")
            self.assertEqual(field["model_extension"]["status"], "reviewed")
            self.assertEqual(model["meta"]["model_extensions"]["field_count"], 1)
            self.assertEqual(len(model["meta"]["model_extensions"]["sha256"]), 64)

    def test_model_extensions_reject_collisions_and_inexact_value_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''
<dataset><concept type="group" shortName="group" id="g">
  <concept type="item" shortName="existing" id="i"><name>Existing</name></concept>
</concept></dataset>''', encoding="utf-8")
            base = {
                "version": 1,
                "status": "reviewed",
                "collision_policy": "error",
                "fields": {
                    "group.existing": {
                        "name": "Collision", "parent": "group", "type": "text",
                        "reason": "Review reason.",
                    }
                },
            }
            with self.assertRaisesRegex(ValueError, "collides"):
                compile_model(transaction, model_extensions=base)

            base["fields"] = {
                "group.code": {
                    "name": "Code", "parent": "group", "type": "code",
                    "value_set": {"id": "1.2.3", "effective_date": "2026"},
                    "reason": "Review reason.",
                }
            }
            with self.assertRaisesRegex(ValueError, "unavailable ValueSet revision"):
                compile_model(transaction, model_extensions=base)

    def test_codesystem_and_concept_context_references_are_typed(self) -> None:
        root = ET.fromstring('''<valueSet id="vs">
          <sourceCodeSystem id="1.2.3" effectiveDate="2020-01-01" prefix="term-"/>
          <concept code="A" codeSystem="1.2.3" prefix="term-"/>
          <concept id="c"><inherit ref="9.1" effectiveDate="2021-01-01"
            datasetId="9" datasetEffectiveDate="2021-01-01" prefix="ext-"/></concept>
        </valueSet>''')
        hard = hard_references(root)
        code_systems = [
            row for row in display_references(root)
            if row["kind"] == "codesystem"
        ]
        self.assertEqual(len(code_systems), 1)
        code_system = code_systems[0]
        self.assertEqual(
            (code_system["id"], code_system["effective_date"], code_system["project"]),
            ("1.2.3", "2020-01-01", "term-"),
        )
        concept = next(row for row in soft_references(root) if row["kind"] == "concept")
        rows = artifact_representations(
            concept, project="ext-", main_project="main-", release=RELEASE["date"],
            language="de-DE",
        )
        self.assertIn("transactionId=9", rows[0]["url"])
        self.assertIn("datasetOrTransactionId=9", rows[1]["url"])
        self.assertNotIn("release=", rows[1]["url"])

    def test_extensional_codesystem_is_evidence_but_intensional_is_required(self) -> None:
        root = ET.fromstring('''<valueSet id="vs"><conceptList>
          <concept code="A" codeSystem="display-cs"/>
          <include code="root" codeSystem="expansion-cs" op="is-a"/>
        </conceptList></valueSet>''')
        hard = hard_references(root)
        display = display_references(root)
        self.assertEqual(
            [(row["id"], row["role"]) for row in hard if row["kind"] == "codesystem"],
            [("expansion-cs", "expansion-support")],
        )
        self.assertIn(
            ("display-cs", "display-evidence"),
            [(row["id"], row["role"]) for row in display if row["kind"] == "codesystem"],
        )
        self.assertNotIn(
            "display-cs", {row["id"] for row in hard + soft_references(root)}
        )

    def test_noncode_and_partly_inline_codesystem_includes_are_display_only(self) -> None:
        root = ET.fromstring('''<dataset>
          <concept id="text"><valueDomain type="text"><conceptList>
            <include codeSystem="text-cs"/>
          </conceptList></valueDomain></concept>
          <concept id="coded"><valueDomain type="code"><conceptList>
            <concept code="A" codeSystem="inline-cs"/>
            <include codeSystem="inline-cs"/>
          </conceptList></valueDomain></concept>
          <valueSet id="standalone"><conceptList>
            <concept code="B" codeSystem="standalone-inline-cs"/>
            <include codeSystem="standalone-inline-cs"/>
          </conceptList></valueSet>
        </dataset>''')
        self.assertEqual(
            [row["id"] for row in hard_references(root)], ["standalone"]
        )
        self.assertEqual(
            {row["id"] for row in display_references(root)},
            {"text-cs", "inline-cs", "standalone-inline-cs"},
        )

    def test_representing_template_preserves_exact_source_dataset_identity(self) -> None:
        root = ET.fromstring('''<transaction>
          <representingTemplate sourceDataset="1.2.3"
            sourceDatasetEffectiveDate="2020-01-02" templateIdent="owner-"/>
        </transaction>''')
        dataset = next(
            row for row in hard_references(root) if row["kind"] == "dataset"
        )
        self.assertEqual(dataset["effective_date"], "2020-01-02")
        self.assertEqual(dataset["project"], "owner-")
        urls = artifact_representations(
            dataset, project=dataset["project"], main_project="main-",
            release=RELEASE["date"], language="de-DE",
        )
        self.assertTrue(all("/dataset/1.2.3/2020-01-02" in row["url"] for row in urls))

    def test_model_separates_groups_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''
<dataset id="d" transactionId="t" transactionEffectiveDate="2026-01-01" templateId="doc">
  <concept type="group" shortName="vital" id="g" minimumMultiplicity="0" maximumMultiplicity="*">
    <name>Vital</name>
    <concept type="item" shortName="temp" id="c" minimumMultiplicity="1" maximumMultiplicity="1">
      <name>Temperatur</name><valueDomain type="quantity"><property unit="Cel"/></valueDomain>
    </concept>
  </concept>
</dataset>''', encoding="utf-8")
            model = compile_model(transaction)
            self.assertIn("vital", model["groups"])
            self.assertNotIn("vital", model["fields"])
            self.assertEqual(model["fields"]["vital.temp"]["repeat"], "vital")

    def test_contains_uses_only_exact_terminal_original_locator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            transaction = directory / "transaction.xml"
            external = directory / "external.xml"
            transaction.write_text('''
<dataset>
  <concept type="group" shortName="literal" id="literal-host">
    <contains ref="literal-group" flexibility="2024-01-01"
      originalId="external-group" originalEffectiveDate="2023-12-27"/>
  </concept>
  <concept type="group" shortName="original" id="original-host">
    <contains ref="missing-alias" flexibility="2024-01-01"
      originalId="external-group" originalEffectiveDate="2023-12-27"/>
  </concept>
  <concept type="group" shortName="specified" id="specified-host">
    <contains ref="specified-alias" flexibility="2023-12-28"
      prefix="external-" datasetId="external-dataset"
      datasetEffectiveDate="2023-10-25" iType="group"
      iEffectiveDate="2023-12-27"/>
    <relationship type="SPEC" ref="external-group" flexibility="2023-12-27"
      prefix="external-" datasetId="external-dataset"
      datasetEffectiveDate="2023-10-25" iType="group"
      iEffectiveDate="2023-12-27"/>
  </concept>
  <concept type="group" shortName="adapted" id="adapted-host">
    <contains ref="adapted-alias" flexibility="2023-12-28"
      prefix="external-" datasetId="external-dataset"
      datasetEffectiveDate="2023-10-25" iType="group"
      iEffectiveDate="2023-12-27"/>
    <relationship type="ADAPT" ref="external-group" flexibility="2023-12-27"
      prefix="external-" datasetId="external-dataset"
      datasetEffectiveDate="2023-10-25" iType="group"
      iEffectiveDate="2023-12-27"/>
  </concept>
  <concept type="group" shortName="ordinary_spec" id="ordinary-spec-host">
    <contains ref="ordinary-alias" flexibility="2023-12-28"
      prefix="other-" datasetId="other-dataset"
      datasetEffectiveDate="2023-10-25" iType="group"
      iEffectiveDate="2023-12-27"/>
    <relationship type="SPEC" ref="external-group" flexibility="2023-12-27"
      prefix="external-" datasetId="external-dataset"
      datasetEffectiveDate="2023-10-25" iType="group"
      iEffectiveDate="2023-12-27"/>
  </concept>
</dataset>''', encoding="utf-8")
            external.write_text('''
<dataset>
  <concept type="group" shortName="literal-source" id="literal-group"
    effectiveDate="2024-01-01">
    <concept type="item" shortName="literal_value" id="literal-value">
      <name>Literal value</name>
    </concept>
  </concept>
  <concept type="group" shortName="medication" id="external-group"
    effectiveDate="2023-12-27">
    <concept type="item" shortName="value" id="external-value">
      <name>Value</name>
    </concept>
  </concept>
</dataset>''', encoding="utf-8")

            model = compile_model(transaction, [external])

            self.assertIn("literal.literal_value", model["fields"])
            self.assertNotIn("literal.value", model["fields"])
            self.assertIn("original.value", model["fields"])
            self.assertIn("specified.value", model["fields"])
            self.assertNotIn("adapted.value", model["fields"])
            self.assertNotIn("ordinary_spec.value", model["fields"])
            self.assertEqual(
                model["groups"]["specified"]["contains_resolution"],
                "terminal-original-SPEC",
            )
            self.assertEqual(
                model["groups"]["literal"]["contains_resolution"],
                "contains",
            )
            self.assertEqual(
                model["groups"]["original"]["contains_resolution"],
                "originalId",
            )

    def test_transaction_source_controls_selection_and_formal_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "transaction.source.xml"
            analysis = directory / "transaction.xml"
            terminology = directory / "valueset.xml"
            source.write_text('''<transaction id="tx" effectiveDate="2026-01-01">
              <representingTemplate>
                <concept ref="c" minimumMultiplicity="1" maximumMultiplicity="1">
                  <terminologyAssociation conceptId="old.c" valueSet="vs" flexibility="2025-01-01"
                    code="B" codeSystem="legacy-cs" displayName="Predecessor status"/>
                  <terminologyAssociation conceptId="c.option.c" code="A" codeSystem="cs" displayName="Alpha"/>
                </concept>
              </representingTemplate>
            </transaction>''', encoding="utf-8")
            analysis.write_text('''<dataset id="dataset" transactionId="tx" transactionEffectiveDate="2026-01-01">
              <concept id="c" shortName="status" type="item" minimumMultiplicity="0" maximumMultiplicity="1">
                <inherit ref="old.c"/><name>Status</name><valueDomain type="code"><conceptList>
                  <concept><name>Logical only</name></concept>
                </conceptList></valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            terminology.write_text('''<valueSet id="vs" effectiveDate="2025-01-01">
              <conceptList><concept code="A" codeSystem="cs" displayName="Alpha"><name>Alpha</name></concept></conceptList>
            </valueSet>''', encoding="utf-8")
            model = compile_model(
                analysis, [terminology], [terminology], transaction_source=source
            )
            field = model["fields"]["status"]
            self.assertTrue(field["required"])
            self.assertEqual(model["meta"]["selected_concepts"], 1)
            self.assertEqual(set(field["accepted_values"]), {"Alpha"})
            self.assertEqual(set(field["logical_domain"]["options"]), {"Logical only"})
            self.assertEqual(
                set(field["logical_domain"]["options"])
                - set(accepted_values(field)),
                {"Logical only"},
            )
            self.assertEqual(len(field["terminology_associations"]), 2)
            self.assertEqual(
                {row["scope"] for row in field["terminology_associations"]},
                {"original-concept", "related-concept"},
            )
            self.assertEqual(
                [(row["code"], row["scope"]) for row in field["codes"]],
                [("B", "original-concept")],
            )
            defaults = site_compiler.code_mapping_defaults(model)["fields"]["status"]
            self.assertEqual(defaults["A"], "Alpha")
            self.assertNotIn("Logical only", defaults)
            self.assertNotIn("values", field)

    def test_concept_list_member_identity_compiles_formal_code_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "transaction.source.xml"
            analysis = directory / "transaction.xml"
            terminology = directory / "valueset.xml"
            source.write_text('''<transaction id="tx" effectiveDate="2026-01-01">
              <representingTemplate>
                <concept ref="c">
                  <terminologyAssociation conceptId="c.option.local"
                    code="A" codeSystem="1.2.3" displayName="Formal A"/>
                  <terminologyAssociation conceptId="c.option.other"
                    code="74964007" codeSystem="2.16.840.1.113883.6.96"
                    displayName="Other (qualifier value)"/>
                  <terminologyAssociation conceptId="c.option.outside"
                    code="Z" codeSystem="1.2.3" displayName="Outside"/>
                </concept>
              </representingTemplate>
            </transaction>''', encoding="utf-8")
            analysis.write_text('''<dataset id="dataset" transactionId="tx"
                transactionEffectiveDate="2026-01-01">
              <concept id="c" shortName="status" type="item">
                <name>Status</name><valueDomain type="code"><conceptList>
                  <concept id="c.option.local"><name>Lokaler Wert</name>
                    <synonym>Lokales Synonym</synonym></concept>
                  <concept id="c.option.other" exception="true">
                    <name>Andere</name></concept>
                  <concept id="c.option.outside"><name>Außerhalb</name></concept>
                </conceptList></valueDomain>
                <valueSet id="vs" effectiveDate="2025-01-01"/>
              </concept>
            </dataset>''', encoding="utf-8")
            terminology.write_text('''<valueSet id="vs" effectiveDate="2025-01-01">
              <conceptList>
                <concept code="A" codeSystem="1.2.3" displayName="Formal A"/>
                <concept code="74964007" codeSystem="2.16.840.1.113883.6.96"
                  displayName="Other (qualifier value)"/>
              </conceptList>
            </valueSet>''', encoding="utf-8")

            model = compile_model(
                analysis, [terminology], [terminology],
                transaction_source=source,
            )
            logical = model["fields"]["status"]["logical_domain"]
            local = logical["options"]["Lokaler Wert"]
            other = logical["options"]["Andere"]
            self.assertEqual(local["concept_id"], "c.option.local")
            self.assertEqual(local["terminology_association"]["canonical"], "Formal A")
            self.assertEqual(local["terminology_association"]["code"], "A")
            self.assertEqual(
                local["terminology_associations"],
                [local["terminology_association"]],
            )
            self.assertEqual(
                other["terminology_association"]["canonical"],
                "Other (qualifier value)",
            )
            self.assertEqual(other["terminology_association"]["code"], "74964007")
            self.assertTrue(other["exception"])
            self.assertEqual(
                logical["terminology_association_diagnostics"],
                [{
                    "kind": "outside-formal-domain",
                    "label": "Außerhalb",
                    "concept_id": "c.option.outside",
                    "declared": [{"code": "Z", "code_system": "1.2.3"}],
                    "admitted_canonical_values": [],
                }],
            )
            defaults = site_compiler.code_mapping_defaults(model)["fields"]["status"]
            self.assertEqual(defaults["Lokaler Wert"], "Formal A")
            self.assertEqual(defaults["Lokales Synonym"], "Formal A")
            self.assertEqual(defaults["Andere"], "Other (qualifier value)")
            self.assertNotIn("Außerhalb", defaults)

    def test_target_valueset_disambiguates_exact_option_associations(self) -> None:
        field = {
            "name": "Scale result",
            "type": "code",
            "repeat_chain": [],
            "value_sets": ["source-vs", "target-vs"],
            "accepted_values": {
                "Source red": {
                    "code": "1", "code_system": "source-system",
                },
                "Target red": {
                    "code": "R", "code_system": "target-system",
                },
                "Source blue": {
                    "code": "2", "code_system": "source-system",
                },
                "Target blue": {
                    "code": "B", "code_system": "target-system",
                },
            },
            "logical_domain": {"options": {
                "Rot": {
                    "display_name": "Rot", "concept_id": "option.red",
                    "terminology_associations": [
                        {"code": "1", "code_system": "source-system"},
                        {"code": "R", "code_system": "target-system"},
                    ],
                },
                "Blau": {
                    "display_name": "Blau", "concept_id": "option.blue",
                    "terminology_associations": [
                        {"code": "2", "code_system": "source-system"},
                        {"code": "B", "code_system": "target-system"},
                    ],
                },
            }},
        }
        members = [{
            "code": "R", "codeSystem": "target-system",
            "displayName": "Target red",
            "valueSetEffectiveDate": "2026",
        }, {
            "code": "B", "codeSystem": "target-system",
            "displayName": "Target blue",
            "valueSetEffectiveDate": "2026",
        }]
        target = {
            "path": "hl7:observation/hl7:value",
            "datatype": "CE", "writable": True, "locations": ["0.0"],
            "logical_types": ["code", "ordinal"], "repeat_ancestors": [],
            "value_representation": {
                "kind": "coded", "logical_types": ["code", "ordinal"],
                "attributes": ["code", "codeSystem", "displayName"],
            },
            "value_set_bindings": [{
                "id": "target-vs", "effective_date": "2026",
                "strength": "required",
            }],
        }
        source_target = {
            **target,
            "path": "hl7:observation/hl7:translation",
            "locations": ["0.1"],
            "value_set_bindings": [{
                "id": "source-vs", "effective_date": "2026",
                "strength": "required",
            }],
        }
        source_members = [{
            "code": "1", "codeSystem": "source-system",
            "displayName": "Source red", "valueSetEffectiveDate": "2026",
        }, {
            "code": "2", "codeSystem": "source-system",
            "displayName": "Source blue", "valueSetEffectiveDate": "2026",
        }]
        result = mapping_compiler._bound_enum_mapping(
            field, {"targets": {
                "Scale.value": target,
                "Scale.translation": source_target,
            }},
            {"target-vs": members, "source-vs": source_members},
            "Scale.value",
        )
        self.assertIsNotNone(result)
        assert result is not None
        selection, metadata = result
        transform = selection["mapping"]["transform"]
        self.assertEqual(metadata["evidence_level"], "EXACT_CONCEPT_ASSOCIATION")
        self.assertEqual(transform["map"]["Rot"]["code"], "R")
        self.assertEqual(transform["map"]["Blau"]["codeSystem"], "target-system")
        normalized = data.normalize_value("Rot", field, {}, {})
        self.assertEqual(normalized, {"raw": "Rot", "canonical": "Rot"})
        self.assertEqual(apply_transform(normalized, transform)["code"], "R")

    def test_logical_only_domain_never_yields_an_empty_exact_enum(self) -> None:
        field = {
            "type": "code",
            "logical_domain": {"options": {
                "One": {"display_name": "One", "concept_id": "option.1"},
                "Two": {"display_name": "Two", "concept_id": "option.2"},
            }},
            "formal_terminology": {
                "bound": True, "complete": False, "members": {},
            },
        }
        target = {
            "path": "hl7:act/hl7:code",
            "datatype": "CE", "writable": True, "locations": ["0.0"],
            "logical_types": ["code", "ordinal"], "repeat_ancestors": [],
            "value_representation": {
                "kind": "coded", "logical_types": ["code", "ordinal"],
                "attributes": ["code", "codeSystem", "displayName"],
            },
            "value_set_bindings": [{
                "id": "target-vs", "effective_date": "2026",
                "strength": "required",
            }],
        }
        result = mapping_compiler._bound_enum_mapping(
            field, {"targets": {"Referral.code": target}},
            {"target-vs": [{
                "code": "1", "codeSystem": "target-system",
                "displayName": "One", "valueSetEffectiveDate": "2026",
            }]},
        )
        self.assertIsNone(result)

    def test_unresolved_shared_valueset_is_review_evidence_only(self) -> None:
        field = {
            "type": "code", "value_sets": ["shared-vs"],
            "formal_terminology": {"status": "unresolved"},
        }
        target = {
            "datatype": "CE", "writable": True, "locations": ["0.0"],
            "logical_types": ["code", "ordinal"], "repeat_ancestors": [],
            "value_representation": {
                "kind": "coded", "logical_types": ["code", "ordinal"],
            },
        }
        candidates = mapping_compiler._vocabulary_candidates(
            field, {"shared-vs": [("Referral.code", target)]}, {}, {},
        )
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0]["actionable"])
        self.assertIn("review evidence only", candidates[0]["warnings"][0])

    def test_standalone_value_set_populates_model_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            valueset = Path(tmp) / "valueset.xml"
            transaction.write_text('''<dataset id="d"><concept type="item" shortName="status" id="c"><name>Status</name><valueDomain type="code"/><valueSet id="1.2.3"/></concept></dataset>''', encoding="utf-8")
            valueset.write_text('''<valueSet id="1.2.3"><concept code="A" codeSystem="9.9"><name>aktiv</name></concept></valueSet>''', encoding="utf-8")
            model = compile_model(transaction, [valueset])
            self.assertEqual(accepted_values(model["fields"]["status"])["aktiv"]["code"], "A")

    def test_complete_expansion_wrapper_populates_structural_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            expansion = Path(tmp) / "valueset.expansion.xml"
            expansion.write_text('''<valueSetExpansionSet current="1" count="1">
              <valueSet id="1.2.3" effectiveDate="2025">
                <conceptList><include codeSystem="9.9"/></conceptList>
              </valueSet>
              <expansion><items is="concept" code="A" codeSystem="9.9"
                displayName="Active"/></expansion>
            </valueSetExpansionSet>''', encoding="utf-8")
            members = value_set_members([expansion])
            self.assertEqual(members[("1.2.3", "2025")][0]["code"], "A")
            self.assertEqual(members[("1.2.3", "2025")][0]["kind"], "concept")

    def test_spec_prototype_does_not_merge_parent_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''<project>
              <template id="old" effectiveDate="2020-01-01" name="OldEntry">
                <element name="hl7:observation" id="old-root"><element name="hl7:value" id="old-value" datatype="ST"/></element>
              </template>
              <template id="new" effectiveDate="2026-01-01" name="NewEntry">
                <element name="hl7:observation" id="new-root"><element name="hl7:value" id="new-value" datatype="ST"/></element>
              </template>
              <template id="base" effectiveDate="2020-01-01" name="Base">
                <element name="hl7:ClinicalDocument" id="root">
                  <attribute name="classCode" value="BASE"/>
                  <element name="hl7:component" id="component" contains="old" flexibility="2020-01-01" minimumMultiplicity="1" maximumMultiplicity="1">
                    <element name="hl7:oldChoice" id="old-choice" datatype="ST"/>
                  </element>
                </element>
              </template>
              <template id="doc" effectiveDate="2026-01-01" name="Doc">
                <relationship type="SPEC" template="base" flexibility="2020-01-01"/>
                <element name="hl7:ClinicalDocument" id="root">
                  <attribute name="moodCode" value="EVN"/>
                  <element name="hl7:component" id="component" contains="new" flexibility="2026-01-01" maximumMultiplicity="1">
                    <element name="hl7:newChoice" id="new-choice" datatype="ST"/>
                  </element>
                </element>
              </template>
            </project>''', encoding="utf-8")
            compiled = compile_cda(
                [project],
                {"meta": {"template_id": "doc", "template_effective_date": "2026-01-01"}, "groups": {}, "fields": {}},
            )
            new_choice = [t for t in compiled["targets"].values() if t.get("element_id") == "new-choice"][0]
            new_value = [t for t in compiled["targets"].values() if t.get("element_id") == "new-value"][0]
            self.assertFalse(any(
                target.get("element_id") in {"old-choice", "old-value"}
                for target in compiled["targets"].values()
            ))
            self.assertEqual(len(new_choice.get("locations", [])), 1)
            self.assertEqual(len(new_value.get("locations", [])), 1)
            component = compiled["document"][0]["children"][0]
            self.assertEqual(component["contains"], "new")
            self.assertEqual(component["contains_flexibility"], "2026-01-01")
            self.assertEqual(component["min"], 0)
            self.assertEqual(compiled["document"][0]["fixed"], {"moodCode": "EVN"})
            self.assertEqual(compiled["stats"]["reachable_templates"], 2)

    def test_value_set_revisions_do_not_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tx = d / "tx.xml"
            tx.write_text(
                '<dataset><concept type="item" shortName="status" id="c"><name>Status</name>'
                '<valueDomain type="code"/><valueSet id="1.2.3" effectiveDate="2021-01-01"/>'
                '</concept></dataset>',
                encoding="utf-8",
            )
            (d / "old.xml").write_text(
                '<valueSet id="1.2.3" effectiveDate="2020-01-01"><concept code="A" codeSystem="9"><name>A</name></concept></valueSet>',
                encoding="utf-8",
            )
            (d / "new.xml").write_text(
                '<valueSet id="1.2.3" effectiveDate="2021-01-01"><concept code="B" codeSystem="9"><name>B</name></concept></valueSet>',
                encoding="utf-8",
            )
            model = compile_model(tx, [d / "old.xml", d / "new.xml"])
            self.assertEqual(set(accepted_values(model["fields"]["status"])), {"B"})
            self.assertEqual(len(model["value_sets"]), 2)

    def test_local_codesystem_include_expands_value_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tx = d / "tx.xml"
            terminology = d / "project.xml"
            tx.write_text(
                '<dataset><concept type="item" shortName="indicator" id="c"><name>Indicator</name>'
                '<valueDomain type="code"/><valueSet id="vs" effectiveDate="2024-01-01"/>'
                '</concept></dataset>', encoding="utf-8",
            )
            terminology.write_text('''<project>
              <codeSystem id="cs" effectiveDate="2023-01-01"><conceptList>
                <codedConcept code="red" level="0"><designation language="de-DE" type="preferred" displayName="rot"/></codedConcept>
                <codedConcept code="A" level="1"><designation language="de-DE" type="preferred" displayName="A-Problem"/><parent code="red"/></codedConcept>
                <codedConcept code="A1" level="2"><designation language="de-DE" type="preferred" displayName="A-Untergruppe"/><parent code="A"/></codedConcept>
                <codedConcept code="orange" level="0"><designation language="de-DE" type="preferred" displayName="orange"/></codedConcept>
              </conceptList></codeSystem>
              <valueSet id="vs" effectiveDate="2024-01-01"><conceptList>
                <include op="descendent-of" code="red" codeSystem="cs"/>
              </conceptList></valueSet>
            </project>''', encoding="utf-8")
            model = compile_model(tx, [], [terminology])
            values = accepted_values(model["fields"]["indicator"])
            self.assertEqual(values["A-Problem"]["code"], "A")
            self.assertEqual(values["A-Untergruppe"]["code"], "A1")
            self.assertNotIn("rot", values)
            self.assertNotIn("orange", values)

    def test_compiler_preserves_multiple_quantity_units_as_a_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<dataset>
              <concept type="item" shortName="rate" id="rate"><name>Rate</name>
                <valueDomain type="quantity">
                  <property unit="ml/h"/><property unit="l/h"/>
                  <property unit="µg/h"/><property unit="mg/h"/>
                  <property unit="g/h"/>
                </valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            model = compile_model(transaction)
        self.assertEqual(
            model["fields"]["rate"]["units"],
            ["ml/h", "l/h", "µg/h", "mg/h", "g/h"],
        )
        self.assertNotIn("unit", model["fields"]["rate"])

    def test_formal_original_enrichment_excludes_all_relationship_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tx = d / "tx.xml"; extra = d / "extra.xml"
            tx.write_text('''<dataset>
              <concept type="item" shortName="inherited" id="inherited"><name>Inherited</name><inherit ref="mid" effectiveDate="2020" originalId="root" originalEffectiveDate="2019"/></concept>
              <concept type="item" shortName="contained" id="contained"><name>Contained</name><contains ref="mid" flexibility="2020" originalId="root" originalEffectiveDate="2019"/></concept>
              <concept type="item" shortName="specific" id="specific"><name>Specific</name><relationship type="SPEC" ref="root"/></concept>
              <concept type="item" shortName="adapted" id="adapted"><name>Adapted</name><relationship type="ADAPT" ref="root"/></concept>
              <concept type="item" shortName="equivalent" id="equivalent"><name>Equivalent</name><relationship type="EQUIV" ref="root"/></concept>
              <concept type="item" shortName="copied" id="copied"><name>Copied</name><relationship type="COPY" ref="root"/></concept>
              <concept type="item" shortName="versioned" id="versioned"><name>Versioned</name><relationship type="VERSION" ref="root"/></concept>
            </dataset>''', encoding="utf-8")
            extra.write_text('''<dataset>
              <concept type="item" shortName="mid" id="mid" effectiveDate="2020"><name>Mid</name><inherit ref="root" effectiveDate="2019"/></concept>
              <concept type="item" shortName="root" id="root" effectiveDate="2019"><name>Root</name><valueDomain type="quantity"><property unit="mg"/></valueDomain></concept>
            </dataset>''', encoding="utf-8")
            model = compile_model(tx, [extra])
            self.assertEqual(model["fields"]["inherited"]["type"], "quantity")
            self.assertEqual(model["fields"]["inherited"]["unit"], "mg")
            self.assertEqual(model["fields"]["inherited"]["name"], "Root")
            self.assertEqual(model["fields"]["contained"]["type"], "quantity")
            self.assertEqual(model["fields"]["contained"]["unit"], "mg")
            self.assertEqual(model["fields"]["contained"]["name"], "Root")
            for path in (
                "specific", "adapted", "equivalent", "copied", "versioned",
            ):
                self.assertEqual(model["fields"][path]["type"], "text")


if __name__ == "__main__":
    unittest.main()
