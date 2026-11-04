from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping

from decor2hl7 import data, validate
from decor2hl7.bindings import build_assignments
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.transaction import compile_model
from decor2hl7.compile.artifacts import write_build_diagnostics
from decor2hl7.cda.compile import compile_cda
from decor2hl7.cda import render as cda
from decor2hl7.compile.reports import (
    render_accepted_cda_mappings_markdown,
    render_cda_mapping_markdown,
)
from decor2hl7.domain import accepted_values
from decor2hl7.transforms import apply_transform


def find_required(parent: ET.Element[str], path: str) -> ET.Element[str]:
    found = parent.find(path)
    if found is None:
        raise AssertionError(f"expected XML element at {path!r}")
    return found


def mapping_proposal(
    model: Mapping[str, Any],
    cda_model: Mapping[str, Any],
    xml_paths: Iterable[Path],
) -> tuple[dict[str, Any], str]:
    proposal, _, report, _ = mapping_compiler.cda_mapping_audit(
        model, cda_model, xml_paths
    )
    return proposal, report


class MappingAnalysisTests(unittest.TestCase):
    def test_template_name_prefers_unique_required_payload(self) -> None:
        field = {"type": "text"}
        optional_narrative = {
            "datatype": "ED",
            "path": "hl7:observation/hl7:text",
            "writable": True,
            "logical_types": ["text"],
            "value_representation": {"kind": "element_text"},
            "min": 0,
        }
        required_value = {
            "datatype": "ST",
            "path": "hl7:observation/hl7:value",
            "writable": True,
            "logical_types": ["text"],
            "value_representation": {"kind": "element_text"},
            "min": 1,
        }
        required_narrative_reference = {
            "datatype": "TEL",
            "path": "hl7:observation/hl7:text/hl7:reference",
            "writable": True,
            "logical_types": ["text"],
            "value_representation": {"kind": "url"},
            "min": 1,
        }

        self.assertEqual(
            mapping_compiler._principal_target(
                "edis",
                field,
                {"edis": [
                    ("edis.text", optional_narrative),
                    ("edis.reference", required_narrative_reference),
                    ("edis.value", required_value),
                ]},
            ),
            ("edis.value", required_value),
        )

    def test_explicit_leaf_role_inside_mapped_context_is_actionable(self) -> None:
        field = {"name": "Name", "short_name": "name", "type": "text"}
        target = {
            "writable": True, "prohibited": False, "locations": ["0.1"],
            "path": "hl7:participant/hl7:name", "datatype": "ST",
            "logical_types": ["text"], "value_representation": {
                "kind": "element_text", "logical_types": ["text"],
            },
        }
        suggestions = mapping_compiler._unbridged_writable_candidates(
            field,
            {"node": {"locations": ["0"], "path": "hl7:participant"}},
            {"targets": {"Organization.name": target}},
            {"structures": {}},
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["target"], "Organization.name")
        self.assertTrue(suggestions[0]["actionable"])
        self.assertEqual(suggestions[0]["confidence"], "MEDIUM")
        self.assertEqual(suggestions[0]["chain"], ["ARTDECOR_ROLE(name)"])

    def test_exact_bound_value_set_enum_and_field_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "values.xml"
            evidence.write_text('''
              <decor>
                <valueSet id="angiography" effectiveDate="2024-07-22">
                  <concept code="0" codeSystem="9.8.7" displayName="nein"/>
                  <concept code="1" codeSystem="9.8.7" displayName="vor Aufnahme"/>
                </valueSet>
              </decor>
            ''', encoding="utf-8")
            model = {"groups": {}, "fields": {"diagnostics.angiography": {
                "name": "Angiographie", "type": "code", "repeat_chain": [],
                "accepted_values": {
                    "nein": {"synonyms": ["0"]},
                    "vor Aufnahme": {"synonyms": ["1"]},
                },
            }}}
            target = {
                "template_id": "observation", "path": "hl7:observation/hl7:value",
                "datatype": "CV", "renderable": True, "writable": True,
                "locations": ["0.0"], "repeat_ancestors": [],
                "logical_types": ["code", "ordinal"],
                "value_representation": {"kind": "coded"},
                "value_sets": ["angiography"],
                "value_set_bindings": [{
                    "id": "angiography",
                    "effective_date": "2024-07-22",
                    "strength": "required",
                }],
            }
            proposal, _ = mapping_proposal(
                model, {"targets": {"Observation.value": target}}, [evidence]
            )
            rule = proposal["fields"]["diagnostics.angiography"]
            self.assertEqual(rule["target"], "Observation.value")
            self.assertEqual(
                rule["transform"]["map"]["vor Aufnahme"]["code"], "1"
            )
            delta = mapping_compiler.mapping_field_delta(
                {"fields": {"a": "A", "b": "B", "c": None}},
                {"fields": {"a": "A2", "b": None, "c": "C"}},
            )
            self.assertEqual(delta["preserved"], ["a"])
            self.assertEqual(delta["lost"], ["b"])
            self.assertEqual(delta["gained"], ["c"])
            audit_delta = mapping_compiler.mapping_field_delta(
                {"fields": {
                    "a": {"selected": "A"},
                    "b": {"selected": "B"},
                    "c": {"selected": None},
                }},
                {"fields": {
                    "a": {"selected": "A2"},
                    "b": {"selected": None},
                    "c": {"selected": "C"},
                }},
            )
            self.assertEqual(audit_delta["preserved"], ["a"])
            self.assertEqual(audit_delta["lost"], ["b"])
            self.assertEqual(audit_delta["gained"], ["c"])

    def test_ambiguous_selected_target_is_fatal(self) -> None:
        compiled = {
            "targets": {"T.value": {"renderable": True, "locations": ["0.0", "0.1"]}},
            "document": [{"kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1, "mandatory": True, "attributes": [], "children": []}],
        }
        errors = validate.check_config(
            {"fields": {"a": {}}}, compiled, {"fields": {"a": "cases:a"}}, {"fields": {"a": "T.value"}}
        )
        self.assertTrue(any("physical locations" in error for error in errors))
        with self.assertRaises(ValueError):
            cda.emit({"key": "1", "values": {"a": "x"}}, {"fields": {"a": {}}}, compiled, {"fields": {"a": "T.value"}}, {})

    def test_possible_targets_are_contextual_typed_and_claim_aware(self) -> None:
        def target(**values: Any) -> dict[str, Any]:
            return {
                "writable": True, "locations": ["0.0.0"],
                "logical_types": ["text"], "fixed": {},
                "system_value": None, "element_name": "hl7:value",
                "template_id": "t", "template_effective_date": "2026",
                "template_name": "T", "path": "hl7:observation/hl7:value",
                "datatype": "ST", "provenance": [{"source": "template"}],
                **values,
            }

        cda_model = {
            "document": [{
                "kind": "element", "children": [{
                    "kind": "template", "template_id": "t", "children": [{
                        "kind": "element", "children": [], "attributes": [],
                    }], "attributes": [],
                }], "attributes": [],
            }],
            "targets": {
                "T.value": target(
                    template_display_name="Readable template",
                    template_description="A human-readable template description.",
                    description="The candidate payload.", min=1, max=1,
                    conformance="R", codes=[{
                        "code": "KNOWN", "code_system": "9.8.7",
                        "display_name": "Known value",
                    }],
                    value_set_bindings=[{
                        "id": "1.2.3", "effective_date": "2026",
                        "display_name": "Example values",
                    }],
                    value_representation={"kind": "element_text"},
                ),
                "T.id": target(
                    locations=["0.0.0.0"], element_name="hl7:id",
                    path="hl7:observation/hl7:id", datatype_derived=True,
                    provenance=[{"source": "cda-rim"}],
                ),
                "T.datatypePart": target(
                    locations=["0.0.0.1"], datatype_derived=True,
                    provenance=[{"source": "datatype"}],
                ),
                "T.status": target(
                    locations=["0.0.0.2"], element_name="hl7:statusCode",
                ),
                "T.fixed": target(
                    locations=["0.0.0.3"], fixed={"value": "x"},
                ),
                "T.number": target(
                    locations=["0.0.0.4"], logical_types=["integer"],
                ),
            },
        }
        fields = {
            "a": {"target": "logical", "cda_target": "T.value"},
            "b": [{"target": "T.id"}],
        }
        claimed_by, occurrence_claims = mapping_compiler._mapping_target_claims(
            fields, cda_model
        )
        inventory = mapping_compiler._possible_target_inventory(
            {"type": "text", "repeat_chain": []},
            {"target": "T.container", "node": {"locations": ["0"]}},
            cda_model, claimed_by, occurrence_claims,
        )
        self.assertIsNotNone(inventory)
        assert inventory is not None
        self.assertEqual(inventory["document_pool_size"], 3)
        self.assertEqual(
            [item["target"] for item in inventory["items"]],
            ["T.id", "T.value"],
        )
        self.assertEqual(inventory["items"][0]["claimed_by"], ["b"])
        self.assertFalse(inventory["items"][0]["available"])
        self.assertEqual(inventory["items"][1]["claimed_by"], ["a"])
        self.assertTrue(
            any(
                claim["target"] == "T.value"
                for claim in inventory["items"][0][
                    "containing_instance_claimed_by"
                ]
            )
        )
        value_item = next(
            item for item in inventory["items"] if item["target"] == "T.value"
        )
        self.assertEqual(
            value_item["template"]["description"],
            "A human-readable template description.",
        )
        guide = render_cda_mapping_markdown(
            {
                "meta": {}, "order": ["field"], "groups": {},
                "fields": {"field": {"name": "Unmapped field", "type": "text"}},
            },
            {
                **cda_model,
                "document_template": {
                    "id": "doc", "effective_date": "2026",
                    "display_name": "Document",
                },
            },
            {"fields": {"field": None}},
            {"fields": {"field": {
                "possible_targets": inventory,
                "gap": {"gate": "semantic", "kind": "no_association"},
            }}},
        )
        self.assertIn("#### Possible targets (unproven)", guide)
        self.assertIn("A human-readable template description.", guide)
        self.assertIn(
            "<!-- Bound ValueSet: Example values (1.2.3@2026) -->", guide
        )
        self.assertIn('displayName="Known value"', guide)
        self.assertIn("<!-- Possible target (unproven): T.value -->", guide)
        self.assertNotIn("## Sections and entities", guide)

    def test_possible_target_pool_excludes_generated_narrative_references(self) -> None:
        def target(**values: Any) -> dict[str, Any]:
            return {
                "writable": True,
                "locations": ["0.0"],
                "logical_types": ["text"],
                "fixed": {},
                "conditional_fixed": False,
                "system_value": None,
                "element_name": "hl7:value",
                "path": "hl7:observation/hl7:value",
                "provenance": [{"source": "template"}],
                **values,
            }

        pool = mapping_compiler._cda_target_candidate_pool({
            "targets": {
                "Clinical.value": target(),
                "Generated.reference": target(
                    element_name="@value",
                    path="hl7:observation/hl7:text/hl7:reference/@value",
                    content_role="narrative_reference",
                    system_value="generated_narrative_reference",
                ),
            },
        })

        self.assertEqual(list(pool), ["Clinical.value"])

    def test_possible_targets_apply_datatype_cooccurrence_admissibility(self) -> None:
        def target(
            location: str, path: str, datatype: str,
            representation: Mapping[str, Any], **values: Any,
        ) -> dict[str, Any]:
            return {
                "writable": True, "renderable": True,
                "locations": [location], "kind": "element",
                "logical_types": list(representation.get("logical_types", [])),
                "value_representation": dict(representation),
                "fixed": {}, "system_value": None,
                "element_name": path.rsplit("/", 1)[-1],
                "template_id": "t", "template_effective_date": "2026",
                "template_name": "T", "path": path, "datatype": datatype,
                "provenance": [{"source": "template"}],
                **values,
            }

        cda_model = {
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument",
                "children": [{
                    "kind": "element", "name": "hl7:effectiveTime",
                    "datatype": "IVL_TS", "min": 0, "children": [
                        {
                            "kind": "element", "name": "hl7:width",
                            "datatype": "PQ", "min": 1, "children": [],
                            "attributes": [], "targets": ["T.width"],
                        },
                        {
                            "kind": "element", "name": "hl7:low",
                            "datatype": "TS", "min": 0, "children": [],
                            "attributes": [], "targets": ["T.low"],
                        },
                    ], "attributes": [], "targets": ["T.interval"],
                }], "attributes": [], "targets": ["T.root"],
            }],
            "targets": {
                "T.interval": target(
                    "0.0", "hl7:ClinicalDocument/hl7:effectiveTime", "IVL_TS",
                    {
                        "kind": "timestamp",
                        "logical_types": ["datetime", "date"],
                        "attribute": "value",
                    },
                ),
                "T.width": target(
                    "0.0.0", "hl7:ClinicalDocument/hl7:effectiveTime/hl7:width",
                    "PQ", {
                        "kind": "quantity", "logical_types": ["quantity"],
                        "attributes": ["value", "unit"],
                        "scalar_attribute": "value",
                    }, min=1,
                ),
                "T.low": target(
                    "0.0.1", "hl7:ClinicalDocument/hl7:effectiveTime/hl7:low",
                    "TS", {
                        "kind": "timestamp",
                        "logical_types": ["datetime", "date"],
                        "attribute": "value",
                    }, datatype_derived=True,
                    provenance=[{"source": "datatype"}],
                ),
            },
            "datatype_constraints": {
                "version": 1,
                "rules": {"IVL_TS": [{
                    "selectors": ["@value", "hl7:*"],
                    "test": "not(@value and hl7:*)",
                    "declared_in": "IVL_TS",
                    "source": "DTr1_IVL_TS.sch",
                }, {
                    "selectors": ["@value", "hl7:low"],
                    "test": "not(@value and (hl7:low|hl7:width))",
                    "declared_in": "IVL_TS",
                    "source": "DTr1_IVL_TS.sch",
                }]},
            },
        }
        inventory = mapping_compiler._possible_target_inventory(
            {"type": "datetime", "repeat_chain": []},
            {"target": "T.root", "node": {"locations": ["0"]}},
            cda_model, {}, {},
        )
        self.assertIsNotNone(inventory)
        assert inventory is not None
        items = {item["target"]: item for item in inventory["items"]}
        self.assertFalse(items["T.interval"]["available"])
        self.assertIn(
            "not(@value and hl7:*)",
            items["T.interval"]["conformance_conflicts"][0]["message"],
        )
        self.assertTrue(items["T.low"]["available"])
        self.assertEqual(items["T.low"]["conformance_conflicts"], [])

    def test_partial_expansion_degrades_only_an_active_value_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = {
                "terminology_resources": [],
                "unavailable_artifacts": [],
                "build_artifacts": [{
                    "request_key": "valueset:active",
                    "resolved": {"type": "valueset", "id": "active"},
                    "resolution": {"expansion_warning": (
                        "partial value-set expansion: returned 100 of 200 members"
                    )},
                    "forms": {"analysis": {}, "expansion-evidence": {}},
                    "roles": ["formal-terminology"],
                }, {
                    "request_key": "valueset:inactive",
                    "resolved": {"type": "valueset", "id": "inactive"},
                    "resolution": {"expansion_warning": "partial"},
                    "forms": {"analysis": {}},
                    "roles": ["formal-terminology"],
                }],
            }
            model = {"fields": {"coded": {"formal_terminology": {
                "status": "unresolved", "value_sets": [{"id": "active"}],
            }}}}
            result = write_build_diagnostics(
                Path(tmp), inputs, {"unresolved_templates": []}, model
            )
            self.assertEqual(
                [item["request_key"] for item in result["build_degraded"]],
                ["valueset:active"],
            )

    def test_missing_formal_valueset_does_not_promote_logical_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<dataset>
              <concept id="c" shortName="status" type="item">
                <name>Status</name>
                <valueDomain type="code"><conceptList><concept><name>Logical label</name></concept></conceptList></valueDomain>
                <valueSet id="missing-vs" effectiveDate="2020"/>
              </concept>
            </dataset>''', encoding="utf-8")
            model = compile_model(transaction)
            field = model["fields"]["status"]
            self.assertEqual(accepted_values(field), {})
            self.assertFalse(field["formal_terminology"]["complete"])
            self.assertEqual(
                field["formal_terminology"]["status"], "unresolved"
            )
            self.assertEqual(
                field["formal_terminology"]["missing_value_sets"][0]["id"],
                "missing-vs",
            )

    def test_dynamic_value_set_binding_freezes_without_unioning_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            transaction = directory / "transaction.xml"
            terminology = directory / "terminology.xml"
            transaction.write_text('''<dataset>
              <concept id="dynamic" shortName="dynamic" type="item">
                <name>Dynamic</name>
                <valueDomain type="code"/>
                <valueSet id="vs" effectiveDate="2020"><concept code="old" codeSystem="cs" displayName="Old"/></valueSet>
                <terminologyAssociation valueSet="vs" flexibility="dynamic"/>
              </concept>
              <concept id="exact" shortName="exact" type="item">
                <name>Exact</name>
                <valueDomain type="code"/>
                <valueSet id="vs" effectiveDate="2019"/>
              </concept>
            </dataset>''', encoding="utf-8")
            terminology.write_text('''<decor>
              <valueSet id="vs" effectiveDate="2021">
                <concept code="new" codeSystem="cs" displayName="New"/>
              </valueSet>
            </decor>''', encoding="utf-8")

            model = compile_model(transaction, [terminology])
            dynamic = model["fields"]["dynamic"]
            self.assertEqual(dynamic["formal_terminology"]["status"], "bound")
            self.assertEqual(
                dynamic["formal_terminology"]["value_sets"],
                [{"id": "vs", "effective_date": "2021"}],
            )
            self.assertEqual(set(dynamic["accepted_values"]), {"New"})
            self.assertNotIn("Old", dynamic["accepted_values"])

            exact = model["fields"]["exact"]
            self.assertEqual(exact["formal_terminology"]["status"], "unresolved")
            self.assertEqual(exact.get("accepted_values", {}), {})

    def test_empty_owned_concept_list_is_explicitly_unconstrained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<dataset>
              <concept id="c" shortName="agent" type="item">
                <name>Agent</name>
                <valueDomain type="code">
                  <conceptList id="owned-empty-list"/>
                </valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            field = compile_model(transaction)["fields"]["agent"]
            self.assertEqual(field["coded_domain"], {
                "kind": "inline_concept_list",
                "id": "owned-empty-list",
                "status": "unconstrained",
                "member_count": 0,
                "references": [],
                "unrecognized_children": [],
            })
            self.assertEqual(
                field["formal_terminology"]["status"], "unconstrained"
            )
            self.assertFalse(field["formal_terminology"]["bound"])
            self.assertTrue(field["formal_terminology"]["complete"])
            self.assertEqual(field["formal_terminology"]["missing_value_sets"], [])
            self.assertEqual(accepted_values(field), {})

    def test_open_coded_domain_uses_unique_oth_original_text_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            transaction = directory / "transaction.xml"
            project = directory / "project.xml"
            transaction.write_text('''<dataset templateId="doc" templateEffectiveDate="2026">
              <concept id="allergies" shortName="allergies" type="group">
                <name>Allergies</name>
                <concept id="agent" shortName="agent" type="item">
                  <name>Agent</name>
                  <valueDomain type="code">
                    <conceptList id="owned-empty-list"/>
                  </valueDomain>
                </concept>
              </concept>
            </dataset>''', encoding="utf-8")
            project.write_text('''<project>
              <templateAssociation templateId="doc" effectiveDate="2026">
                <concept ref="allergies" elementId="section"/>
              </templateAssociation>
              <template id="doc" effectiveDate="2026" name="ExampleDocument">
                <element name="hl7:ClinicalDocument" id="root"
                         minimumMultiplicity="1" maximumMultiplicity="1">
                  <element name="hl7:section" id="section"
                           minimumMultiplicity="0" maximumMultiplicity="1">
                    <element name="hl7:observation" id="observation"
                             minimumMultiplicity="0" maximumMultiplicity="*">
                      <element name="hl7:code" id="observation-code" datatype="CE"
                               minimumMultiplicity="0" maximumMultiplicity="1">
                        <vocabulary valueSet="status-vs"/>
                      </element>
                      <element name="hl7:participant" id="participant"
                               minimumMultiplicity="1" maximumMultiplicity="1">
                        <element name="hl7:playingEntity" id="entity"
                                 minimumMultiplicity="1" maximumMultiplicity="1">
                          <element name="hl7:code" id="agent-code" datatype="CE"
                                   minimumMultiplicity="1" maximumMultiplicity="1">
                            <attribute name="nullFlavor" datatype="CS" isOptional="true"/>
                            <vocabulary valueSet="agent-vs" flexibility="2025"/>
                            <element name="hl7:originalText" id="agent-text" datatype="ED"
                                     minimumMultiplicity="0" maximumMultiplicity="1"/>
                          </element>
                        </element>
                      </element>
                    </element>
                  </element>
                </element>
              </template>
              <valueSet id="status-vs" effectiveDate="2025"><conceptList>
                <concept code="active" codeSystem="1.2.3" displayName="Active"/>
              </conceptList></valueSet>
              <valueSet id="agent-vs" effectiveDate="2025"><conceptList>
                <concept code="KNOWN" codeSystem="9.8.7" displayName="Known agent"/>
                <exception code="OTH" codeSystem="2.16.840.1.113883.5.1008"
                           displayName="Other"/>
              </conceptList></valueSet>
            </project>''', encoding="utf-8")
            model = compile_model(transaction, [project], [project])
            compiled = compile_cda([project], model)
            proposal, report = mapping_proposal(model, compiled, [project])
            rule = proposal["fields"]["allergies.agent"]
            self.assertIsInstance(rule, dict)
            self.assertEqual(rule["transform"]["type"], "coded_fallback")
            self.assertEqual(rule["transform"]["null_flavor"], "OTH")
            self.assertIn("OPEN_CODED_DOMAIN", report)
            self.assertIn("UNIQUE_DESCENDANT", report)
            self.assertIn("YES · STRONG · INDIRECT · TRANSFORM", report)
            _, audit, _, _ = mapping_compiler.cda_mapping_audit(
                model, compiled, [project]
            )
            guide = render_accepted_cda_mappings_markdown(
                model, compiled, proposal
            )
            self.assertIn("Target-governed coded fallback", guide)
            self.assertIn('`nullFlavor="OTH"`', guide)
            self.assertIn("1 exact code/code-system pairs", guide)

            csv_mapping = {"fields": {"allergies.agent": None}}
            valid_errors = validate.check_config(
                model, compiled, csv_mapping, proposal,
            )
            self.assertFalse([
                error for error in valid_errors if "coded_fallback" in error
            ])

            wrong_flavor = json.loads(json.dumps(proposal))
            wrong_flavor["fields"]["allergies.agent"]["transform"][
                "null_flavor"
            ] = "UNK"
            wrong_flavor_errors = validate.check_config(
                model, compiled, csv_mapping, wrong_flavor,
            )
            self.assertTrue(any(
                "coded_fallback null flavor" in error
                or "coded_fallback requires a null flavor" in error
                for error in wrong_flavor_errors
            ))

            incomplete_members = json.loads(json.dumps(proposal))
            incomplete_members["fields"]["allergies.agent"]["transform"][
                "allowed"
            ] = []
            incomplete_errors = validate.check_config(
                model, compiled, csv_mapping, incomplete_members,
            )
            self.assertTrue(any(
                "allowed members must equal" in error
                for error in incomplete_errors
            ))

            field = model["fields"]["allergies.agent"]
            raw = data.normalize_value(
                "Latex", field, {},
                {"null_flavor": {"unmapped_code": "UNK"}},
            )
            record = {
                "key": "P1", "values": {"allergies.agent": raw},
                "instances": {},
            }
            payload, problems = cda.emit(
                record, model, compiled, proposal,
                {"null_flavor": {"unmapped_code": "UNK"}},
            )
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            code = root.find(
                ".//{urn:hl7-org:v3}playingEntity/{urn:hl7-org:v3}code"
            )
            self.assertIsNotNone(code)
            assert code is not None
            self.assertEqual(code.get("nullFlavor"), "OTH")
            self.assertIsNone(code.get("code"))
            original_text = code.find("{urn:hl7-org:v3}originalText")
            assert original_text is not None
            self.assertEqual(original_text.text, "Latex")

            known = apply_transform({
                "code": "KNOWN", "codeSystem": "9.8.7", "raw": "Known agent",
            }, rule["transform"])
            self.assertEqual(known["code"], "KNOWN")
            self.assertEqual(known["codeSystem"], "9.8.7")

            target_name = rule["target"]
            target_path = compiled["targets"][target_name]["path"]
            original_text_name = next(
                name for name, target in compiled["targets"].items()
                if target.get("content_role") == "coded_original_text"
                and str(target.get("path") or "").rsplit("/", 1)[0]
                == target_path
            )
            ambiguous = compiled.copy()
            ambiguous["targets"] = compiled["targets"].copy()
            duplicate = compiled["targets"][target_name].copy()
            duplicate.update({
                "path": "hl7:ClinicalDocument/hl7:section/hl7:other/hl7:code",
                "locations": ["0.0.999.0"],
            })
            duplicate_text = compiled["targets"][original_text_name].copy()
            duplicate_text.update({
                "path": duplicate["path"] + "/hl7:originalText",
                "locations": ["0.0.999.0.0"],
            })
            ambiguous["targets"]["Alternative.code"] = duplicate
            ambiguous["targets"]["Alternative.code.originalText"] = duplicate_text
            ambiguous_proposal, _ = mapping_proposal(
                model, ambiguous, [project]
            )
            self.assertIsNone(ambiguous_proposal["fields"]["allergies.agent"])

    def test_reviewed_coded_map_is_finite_target_scoped_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            transaction = directory / "transaction.xml"
            project = directory / "project.xml"
            transaction.write_text('''<dataset templateId="doc" templateEffectiveDate="2026">
              <concept id="referral" shortName="referral" type="item">
                <name>Referral</name>
                <valueDomain type="code"><conceptList id="referral-options">
                  <concept id="referral.internal"><name>Internal</name></concept>
                  <concept id="referral.other" exception="true"><name>Other</name></concept>
                </conceptList></valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            project.write_text('''<project>
              <template id="doc" effectiveDate="2026" name="ExampleDocument">
                <element name="hl7:ClinicalDocument" id="root"
                         minimumMultiplicity="1" maximumMultiplicity="1">
                  <element name="hl7:section" id="section"
                           minimumMultiplicity="0" maximumMultiplicity="1">
                    <element name="hl7:act" id="referral-act"
                             minimumMultiplicity="0" maximumMultiplicity="1">
                      <element name="hl7:code" id="referral-code" datatype="CE"
                               minimumMultiplicity="1" maximumMultiplicity="1">
                        <attribute name="nullFlavor" datatype="CS" isOptional="true"/>
                        <vocabulary valueSet="missing-referral-vs" flexibility="2025"/>
                        <element name="hl7:originalText" id="referral-text" datatype="ED"
                                 minimumMultiplicity="0" maximumMultiplicity="1"/>
                      </element>
                    </element>
                  </element>
                </element>
              </template>
            </project>''', encoding="utf-8")
            model = compile_model(transaction)
            compiled = compile_cda([project], model)
            target_name = next(
                name for name, target in compiled["targets"].items()
                if target.get("element_id") == "referral-code"
                and target.get("path") == "hl7:ClinicalDocument/hl7:section/hl7:act/hl7:code"
            )
            target = compiled["targets"][target_name]
            original_binding_key = target["required_binding_constraints"][0]
            compiled_binding = compiled["terminology_constraints"].pop(
                original_binding_key
            )
            binding_key = "missing-referral-vs@2025"
            compiled_binding.update({
                "id": "missing-referral-vs",
                "effective_date": "2025",
                "resolved_effective_date": "2025",
            })
            compiled["terminology_constraints"][binding_key] = compiled_binding
            target["required_binding_constraints"] = [binding_key]
            self.assertFalse(
                compiled_binding["resolved"]
            )
            transform = {
                "type": "reviewed_coded_map",
                "value_set": {
                    "id": compiled_binding["id"],
                    "effective_date": compiled_binding["effective_date"],
                },
                "reason": (
                    "Reviewed finite bridge while the exact target terminology "
                    "artifact remains unavailable."
                ),
                "source_options": {
                    "Internal": "referral.internal",
                    "Other": "referral.other",
                },
                "map": {
                    "referral.internal": {
                        "value": {
                            "code": "1", "codeSystem": "1.2.3",
                            "displayName": "Internal referral",
                        },
                        "reason": "The owner associates this exact option with code 1.",
                    },
                    "referral.other": {
                        "value": {"nullFlavor": "OTH"},
                        "reason": "No one target code is established; retain its wording.",
                    },
                },
            }
            mapping_cfg = {
                "fields": {"referral": {
                    "target": target_name, "transform": transform,
                }},
            }
            errors = validate.check_config(
                model, compiled, {"fields": {"referral": None}}, mapping_cfg,
            )
            self.assertEqual(errors, [])

            field = model["fields"]["referral"]
            internal = data.normalize_value("Internal", field, {}, {})
            payload, problems = cda.emit(
                {"key": "P1", "values": {"referral": internal}, "instances": {}},
                model, compiled, mapping_cfg, {},
            )
            self.assertEqual(problems, [])
            code = find_required(
                ET.fromstring(payload), ".//{urn:hl7-org:v3}act/{urn:hl7-org:v3}code",
            )
            self.assertEqual(code.get("code"), "1")
            self.assertEqual(code.get("codeSystem"), "1.2.3")

            other = data.normalize_value("Other", field, {}, {})
            payload, problems = cda.emit(
                {"key": "P2", "values": {"referral": other}, "instances": {}},
                model, compiled, mapping_cfg, {},
            )
            self.assertEqual(problems, [])
            code = find_required(
                ET.fromstring(payload), ".//{urn:hl7-org:v3}act/{urn:hl7-org:v3}code",
            )
            self.assertEqual(code.get("nullFlavor"), "OTH")
            self.assertEqual(
                find_required(code, "{urn:hl7-org:v3}originalText").text,
                "Other",
            )

            incomplete = json.loads(json.dumps(mapping_cfg))
            incomplete["fields"]["referral"]["transform"]["source_options"].pop(
                "Other"
            )
            incomplete["fields"]["referral"]["transform"]["map"].pop(
                "referral.other"
            )
            incomplete_errors = validate.check_config(
                model, compiled, {"fields": {"referral": None}}, incomplete,
            )
            self.assertTrue(any(
                "source_options must equal every executable logical source option"
                in error for error in incomplete_errors
            ))

            resolved = json.loads(json.dumps(compiled))
            resolved["terminology_constraints"][binding_key]["resolved"] = True
            resolved["terminology_constraints"][binding_key]["members"] = [
                ["1", "1.2.3"],
            ]
            resolved_errors = validate.check_config(
                model, resolved, {"fields": {"referral": None}}, mapping_cfg,
            )
            self.assertTrue(any(
                "now-resolved target binding" in error
                for error in resolved_errors
            ))

            ordinary_mapping = json.loads(json.dumps(mapping_cfg))
            ordinary_mapping["fields"]["referral"]["transform"] = {
                "type": "enum", "select": "canonical",
                "map": {"Internal": {
                    "code": "1", "codeSystem": "1.2.3",
                }},
            }
            with self.assertRaisesRegex(
                ValueError, "required ART-DECOR binding membership is unavailable",
            ):
                cda.emit(
                    {
                        "key": "P3",
                        "values": {"referral": internal},
                        "instances": {},
                    },
                    model, compiled, ordinary_mapping, {},
                )

    def test_direct_mapping_rejects_incompatible_datatype_and_shared_target(self) -> None:
        model = {"fields": {"a": {"type": "code"}, "b": {"type": "code"}}}
        cda_model = {"targets": {"T.negationInd": {
            "datatype": "BL", "path": "hl7:act/@negationInd", "renderable": True,
            "locations": ["0.100000"], "fixed": {},
        }}}
        errors = validate.check_config(
            model, cda_model, {"fields": {"a": None, "b": None}},
            {"fields": {"a": "T.negationInd", "b": "T.negationInd"}}, {"fields": {}},
        )
        self.assertTrue(any("not directly executable" in error for error in errors))
        self.assertTrue(any("multiple model fields" in error for error in errors))

    def test_explicit_implementation_xpath_maps_non_value_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tx = d / "transaction.xml"
            project = d / "project.xml"
            tx.write_text('''<dataset transactionId="t" templateId="doc" templateEffectiveDate="2026-01-01">
              <concept type="item" shortName="rank" id="c" maximumMultiplicity="1"><name>Rank</name>
                <implementation hl7Type="INT.POS" xpath="/hl7:ClinicalDocument/hl7:act/hl7:entryRelationship/hl7:sequenceNumber">
                  <templateLocation id="entry" effectiveDate="2026-01-01" xpath="/hl7:ClinicalDocument/hl7:act"/>
                </implementation>
                <valueDomain type="count"><property minInclude="1"/></valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            project.write_text('''<project>
              <template id="entry" effectiveDate="2026-01-01" name="Entry"><element name="hl7:act" id="act"><element name="hl7:entryRelationship" id="er"><element name="hl7:sequenceNumber" id="seq" datatype="INT.POS"/></element></element></template>
              <template id="doc" effectiveDate="2026-01-01" name="Doc"><element name="hl7:ClinicalDocument" id="root"><element name="hl7:act" contains="entry" flexibility="2026-01-01" id="holder"/></element></template>
            </project>''', encoding="utf-8")
            model = compile_model(tx)
            compiled = compile_cda([project], model)
            proposal, report = mapping_proposal(
                model, compiled, [tx, project]
            )
            self.assertIsNotNone(proposal["fields"]["rank"])
            self.assertIn("XPATH(entry)", report)

    def test_compiler_keeps_only_injective_explicit_ordinal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<dataset>
              <concept type="item" shortName="score" id="score"><name>Score</name>
                <valueDomain type="ordinal"><conceptList>
                  <concept><name>1 keine</name></concept>
                  <concept><name>2 Schmerzreiz</name></concept>
                </conceptList></valueDomain>
              </concept>
              <concept type="item" shortName="xray" id="xray"><name>Röntgen</name>
                <valueDomain type="code"><conceptList>
                  <concept><name>Thorax</name><synonym>30745-4</synonym></concept>
                  <concept><name>Wirbelsäule</name><synonym>38008-9</synonym></concept>
                </conceptList></valueDomain>
              </concept>
              <concept type="item" shortName="explicit" id="explicit"><name>Expliziter Rang</name>
                <valueDomain type="ordinal"><conceptList>
                  <concept><name>Rank 4</name></concept>
                  <concept><name>Fünf Punkte 5</name><synonym>5 Punkte</synonym></concept>
                </conceptList></valueDomain>
              </concept>
              <concept type="item" shortName="fall" id="fall"><name>Fallhöhe</name>
                <valueDomain type="code"><conceptList>
                  <concept><name>Sturz mit Fallhöhe &gt;= 3 m</name></concept>
                  <concept><name>Sturz mit Fallhöhe &lt; 3 m</name></concept>
                </conceptList></valueDomain>
              </concept>
              <concept type="item" shortName="cedis" id="cedis"><name>CEDIS</name>
                <valueDomain type="code"><conceptList>
                  <concept><name>HNO (Mund, Rachen, Hals)</name><synonym>101-150</synonym></concept>
                  <concept><name>Zahn-/Zahnfleischprobleme</name><synonym>101</synonym></concept>
                  <concept><name>Gastrointestinal</name><synonym>251-300</synonym></concept>
                  <concept><name>Bauchschmerzen</name><synonym>251</synonym></concept>
                </conceptList></valueDomain>
              </concept>
              <concept type="item" shortName="duplicate_ranks" id="duplicate_ranks"><name>Duplicate ranks</name>
                <valueDomain type="code"><conceptList>
                  <concept><name>101 Hauptgruppe</name></concept>
                  <concept><name>101 Untergruppe</name></concept>
                  <concept><name>102 Andere Gruppe</name></concept>
                </conceptList></valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            model = compile_model(transaction)

        score = model["fields"]["score"]["logical_domain"]["options"]
        self.assertEqual([score[label]["ordinal"] for label in score], [1, 2])
        explicit = model["fields"]["explicit"]["logical_domain"]["options"]
        self.assertEqual(
            [explicit[label]["ordinal"] for label in explicit], [4, 5]
        )
        for path in ("xray", "fall", "cedis", "duplicate_ranks"):
            options = model["fields"][path]["logical_domain"]["options"]
            self.assertFalse(any("ordinal" in info for info in options.values()))

    def test_intentional_unmapped_review_requires_a_null_and_reason(self) -> None:
        model = {"fields": {"a": {"type": "text"}}, "groups": {}}
        cda_model: dict[str, Any] = {"targets": {}, "document": []}
        csv_mapping = {"fields": {"a": None}}
        valid_mapping = {
            "version": 10,
            "fields": {"a": None},
            "field_reviews": {"a": {
                "status": "intentionally_unmapped",
                "reason": "Reviewed source scope excludes this field.",
            }},
        }
        self.assertEqual(
            validate.check_config(
                model, cda_model, csv_mapping, valid_mapping,
                require_site_configuration=False,
            ),
            [],
        )
        invalid_mapping = {
            **valid_mapping,
            "field_reviews": {"a": {"status": "intentionally_unmapped"}},
        }
        self.assertIn(
            "cda-mapping: field_reviews['a'] requires a reason",
            validate.check_config(
                model, cda_model, csv_mapping, invalid_mapping,
                require_site_configuration=False,
            ),
        )

    def test_quantity_range_requires_compiled_bound_targets(self) -> None:
        assignments, problems = build_assignments(
            {"values": {"dose": {
                "low": {"value": 1, "unit": "mg"},
                "high": {"value": 2, "unit": "mg"},
            }}},
            {"fields": {"dose": {"type": "quantity", "repeat_chain": []}}},
            {"targets": {"Dose.value": {
                "writable": True, "renderable": True, "prohibited": False,
                "locations": ["0"], "repeat_ancestors": [],
                "value_representation": {
                    "kind": "quantity", "attributes": ["value", "unit"],
                    "scalar_attribute": "value",
                },
            }}},
            {"fields": {"dose": "Dose.value"}},
            {},
        )
        self.assertEqual(assignments, {})
        self.assertEqual(
            problems,
            ["CDA target 'Dose.value' has no compiled low/high quantity targets"],
        )


if __name__ == "__main__":
    unittest.main()
