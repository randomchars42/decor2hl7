from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from decor2hl7 import validate
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.transaction import compile_model
from decor2hl7.compile.artifacts import write_build_diagnostics
from decor2hl7.compile.reports import (
    _gap_trace,
    coverage_headline_counts,
    format_coverage_headline,
    render_accepted_cda_mappings_markdown,
    render_cda_mapping_extended_trees_markdown,
    render_cda_mapping_markdown,
    render_cda_mapping_trees_markdown,
)


class MappingReportTests(unittest.TestCase):
    def test_mapping_notes_only_report_configured_rules_in_selected_use(self) -> None:
        proposal = {"fields": {
            "field": "Attached.value",
            "anchored": "Attached.host::Child.value",
        }}
        audit = {"fields": {
            "field": {"selected": "Attached.value", "primary": {"via": "entry"}}
        }}
        model = {"meta": {"configured_source_rules": [
            {
                "rule": "configured OID-owner override",
                "request_key": "template:entry",
                "requested_id": "entry", "resolved_id": "entry",
            },
            {
                "rule": "configured artifact source hint",
                "request_key": "template:unused",
                "requested_id": "unused", "resolved_id": "unused",
            },
        ]}}
        cda_model = {
            "targets": {
                "Attached.value": {"template_id": "entry"},
                "Attached.host": {"template_id": "entry"},
                "Attached.host::Child.value": {
                    "template_id": "child",
                    "occurrence_anchor": "Attached.host",
                },
            },
            "reviewed_extensions": [{"template_id": "entry"}],
        }
        notes = mapping_compiler._mapping_configuration_notes(
            proposal, audit, model, cda_model
        )
        self.assertEqual(len(notes), 2)
        self.assertTrue(all(note["generated"] for note in notes))
        self.assertFalse(any("unused" in str(note) for note in notes))
        self.assertIn("anchored", notes[0]["fields"])

        unselected = mapping_compiler._mapping_configuration_notes(
            {"fields": {"field": None}}, audit, model, cda_model
        )
        self.assertEqual(unselected, [])

    def test_cda_guide_merges_xml_context_and_explains_candidates(self) -> None:
        def element(
            name: str,
            children: list[dict[str, Any]] | None = None,
            **values: object,
        ) -> dict[str, Any]:
            return {
                "kind": "element", "name": name, "attributes": [],
                "children": children or [], "fixed": {}, "targets": [], **values,
            }

        low = element("hl7:low", datatype="TS", targets=["Encounter.low"])
        high = element("hl7:high", datatype="TS", targets=["Encounter.high"])
        effective = element("hl7:effectiveTime", [low, high])
        encounter = element(
            "hl7:encompassingEncounter", [effective],
            fixed={"classCode": "ENC", "moodCode": "EVN"},
        )
        header = element("hl7:componentOf", [encounter], fixed={"typeCode": "COMP"})
        candidate = element("hl7:code", datatype="CE", targets=["Referral.code"])
        unused = element("hl7:text", datatype="ST", targets=["Referral.unused"])
        section = element(
            "hl7:section", [candidate, unused], target="Referral.section", min=1,
        )
        document = element(
            "hl7:ClinicalDocument",
            [header, element("hl7:component", [section], min=1)],
            min=1,
        )
        unused["min"] = 1
        unused["mandatory"] = True
        cda_model: dict[str, Any] = {
            "document_template": {
                "id": "doc", "effective_date": "2026-01-01",
                "name": "Document", "display_name": "Test document",
            },
            "document": [document],
            "targets": {
                "Encounter.low": {
                    "locations": ["0.0.0.0.0"], "path": (
                        "hl7:componentOf/hl7:encompassingEncounter/"
                        "hl7:effectiveTime/hl7:low"
                    ), "datatype": "TS", "kind": "element",
                    "template_name": "Encounter", "template_id": "enc",
                    "template_effective_date": "2026-01-01",
                },
                "Encounter.high": {
                    "locations": ["0.0.0.0.1"], "path": (
                        "hl7:componentOf/hl7:encompassingEncounter/"
                        "hl7:effectiveTime/hl7:high"
                    ), "datatype": "TS", "kind": "element",
                    "template_name": "Encounter", "template_id": "enc",
                    "template_effective_date": "2026-01-01",
                },
                "Referral.section": {
                    "locations": ["0.1.0"], "path": "hl7:section",
                    "template_name": "Referral", "template_display_name": "Referral",
                },
                "Referral.code": {
                    "locations": ["0.1.0.0"], "path": "hl7:section/hl7:code",
                    "datatype": "CE", "kind": "element", "description": "Referral code",
                    "template_name": "Referral", "template_display_name": "Referral",
                    "writable": True, "fixed": {}, "system_value": None,
                },
                "Referral.unused": {
                    "locations": ["0.1.0.1"], "path": "hl7:section/hl7:text",
                    "datatype": "ST", "kind": "element", "description": "Unused text",
                    "template_name": "Referral", "template_display_name": "Referral",
                    "writable": True, "fixed": {}, "system_value": None,
                    "min": 1, "mandatory": True,
                },
            },
        }
        model = {
            "order": ["case.start", "case.end", "case.referral"],
            "groups": {"case": {"name": "Case"}},
            "fields": {
                "case.start": {"name": "Start", "parent": "case"},
                "case.end": {"name": "End", "parent": "case"},
                "case.referral": {"name": "Referral source", "parent": "case"},
            },
        }
        mapping_cfg: dict[str, Any] = {"fields": {
            "case.start": "Encounter.low", "case.end": "Encounter.high",
            "case.referral": None,
        }}
        audit = {
            "summary": {"field_coverage": {"NO": 1}},
            "fields": {"case.referral": {"alternatives": [{
                "target": "Referral.code", "datatype": "CE", "confidence": "STRONG",
                "chain": ["SPEC", "TA"], "actionable": True,
            }]}},
        }
        report = render_cda_mapping_markdown(model, cda_model, mapping_cfg, audit)
        trees = render_cda_mapping_trees_markdown(
            model, cda_model, mapping_cfg, audit
        )
        extended_trees = render_cda_mapping_extended_trees_markdown(
            model, cda_model, mapping_cfg, audit
        )
        accepted = render_accepted_cda_mappings_markdown(
            model, cda_model, mapping_cfg
        )
        counts = coverage_headline_counts(model, cda_model, mapping_cfg, audit)
        self.assertEqual(counts, {
            "datapoints": 3,
            "mapped_datapoints": 2,
            "mapped_leaves": 2,
            "reviewed_datapoints": 0,
            "suggested_datapoints": 1,
            "suggested_leaves": 1,
            "no_target_datapoints": 0,
            "no_source_leaves": 1,
        })
        self.assertEqual(
            format_coverage_headline(counts, markdown=False),
            "Model: 3 datapoints · ✓ mapped 2 dp → 2 leaves · "
            "= reviewed null 0 dp · "
            "! suggested 1 dp → 1 leaf · × no target 0 dp · "
            "○ no source 1 leaf",
        )
        self.assertIn(
            "Model: **3 datapoints** · ✓ mapped **2 dp → 2 leaves** · "
            "= reviewed null **0 dp** · "
            "! suggested **1 dp → 1 leaf** · × no target **0 dp** · "
            "○ no source **1 leaf**",
            report,
        )
        self.assertIn("!      └── Referral source", report)
        self.assertIn("✓  │       ├── low {Encounter.low} ← Start", trees)
        self.assertIn("S: case.start", extended_trees)
        self.assertIn(
            "T: Encounter · enc @ 2026-01-01 · template-relative "
            "hl7:componentOf/hl7:encompassingEncounter/hl7:effectiveTime/hl7:low · TS",
            extended_trees,
        )
        self.assertIn("## Complete physical CDA coverage tree", extended_trees)
        logical_mapping = {
            "fields": {
                **mapping_cfg["fields"],
                "case.start": {
                    "target": "Encounter.logical_low",
                    "cda_target": "Encounter.low",
                },
            },
        }
        logical_trees = render_cda_mapping_extended_trees_markdown(
            model, cda_model, logical_mapping, audit
        )
        self.assertIn("low {Encounter.low} ← Start", logical_trees)
        self.assertIn("logical {Encounter.logical_low}", logical_trees)
        self.assertNotIn(
            "low {Encounter.low} ← no dataset counterpart", logical_trees
        )
        self.assertIn(
            "○▲         └── text {Referral.unused} ← no dataset counterpart",
            trees,
        )
        cda_model["targets"]["Referral.unused"]["datatype_derived"] = True
        mapping_cfg["site_requirements"] = {"Referral.unused": {
            "channel": "values",
            "reason": "The deployment owns this required value.",
        }}
        site_owned_trees = render_cda_mapping_trees_markdown(
            model, cda_model, mapping_cfg, audit
        )
        self.assertIn(
            "○◆         └── text {Referral.unused} ← site configuration via "
            "cda.values; no dataset counterpart",
            site_owned_trees,
        )
        self.assertIn("◆ **Site-owned requirement**", site_owned_trees)
        self.assertIn(
            "it does not claim that a concrete site value was checked",
            site_owned_trees,
        )
        mapping_cfg.pop("site_requirements")
        cda_model["targets"]["Referral.unused"].pop("datatype_derived")
        section["min"] = 0
        document["children"][1]["min"] = 0
        optional_trees = render_cda_mapping_trees_markdown(
            model, cda_model, mapping_cfg, audit
        )
        self.assertIn(
            "○          └── text {Referral.unused} ← no dataset counterpart",
            optional_trees,
        )
        self.assertIn('<componentOf typeCode="COMP">', accepted)
        self.assertIn('<encompassingEncounter classCode="ENC" moodCode="EVN">', accepted)
        self.assertIn('<low value="{Encounter.low}"/>', accepted)
        self.assertIn('<high value="{Encounter.high}"/>', accepted)
        self.assertIn("manual decision workbench", report)
        self.assertIn("Referral code", report)
        self.assertIn("SPEC → TA", report)
        self.assertIn("selectable after review", report)

    def test_review_workbench_contains_only_undecided_nulls(self) -> None:
        model = {
            "order": ["open", "reviewed", "narrative"],
            "groups": {},
            "fields": {
                "open": {"name": "Open source value", "type": "text"},
                "reviewed": {"name": "Reviewed null value", "type": "text"},
                "narrative": {"name": "Narrative-only value", "type": "text"},
            },
        }
        cda_model = {
            "document_template": {
                "id": "document", "effective_date": "2026",
                "name": "Document",
            },
            "document": [],
            "targets": {},
        }
        mapping = {
            "fields": {"open": None, "reviewed": None, "narrative": None},
            "field_reviews": {"reviewed": {
                "status": "intentionally_unmapped",
                "reason": "Reviewed scope excludes this value.",
            }},
            "narratives": {"Diagnostics.text": {"blocks": [{
                "type": "fact", "source": "narrative", "label": "Narrative",
                "reason": "Reviewed wording-only representation.",
            }]}},
        }
        audit = {"fields": {
            path: {
                "unresolved_reason": "no_semantic_evidence",
                "gap": {
                    "gate": "blocked_upstream", "kind": "no_candidate",
                    "reopens_with": [],
                },
            }
            for path in model["fields"]
        }}

        report = render_cda_mapping_markdown(
            model, cda_model, mapping, audit
        )

        self.assertIn("Open source value", report)
        self.assertNotIn("Reviewed null value", report)
        self.assertNotIn("Narrative-only value", report)
        self.assertIn("✓ mapped **1 dp", report)
        self.assertIn("= reviewed null **1 dp**", report)
        self.assertIn("× no target **1 dp**", report)
        self.assertIn(
            "intentional nulls are resolved decisions and therefore omitted",
            report,
        )

    def test_gap_classifier_labels_each_reopening_gate(self) -> None:
        classify = mapping_compiler._gap_classification
        context = {
            "target": "Section.entry",
            "node": {
                "template_id": "section-template",
                "template_effective_date": "2026",
                "is_closed": False,
                "datatype": "IVL_PQ",
                "locations": ["0.1"],
            },
        }
        structural_context = {
            "target": "Medication.substanceAdministration",
            "node": {
                "template_id": "medication-template",
                "template_effective_date": "2026",
                "is_closed": False,
                "datatype": "POCD_MT000040.SubstanceAdministration",
                "locations": ["0.2"],
            },
        }
        candidate = {
            "target": "Observation.value",
            "node": {"logical_types": ["code"], "locations": ["0.1.0"]},
        }
        cases: list[tuple[
            str,
            Mapping[str, Any],
            Mapping[str, Any],
            list[Mapping[str, Any]],
            Mapping[str, Any] | None,
        ]] = [
            (
                "semantic:shared_target",
                {
                    "selected": None, "primary": candidate,
                    "runtime_blocked": "SHARED(2)",
                    "shared_target_fields": ["case.a", "case.b"],
                },
                {}, [], None,
            ),
            (
                "semantic:missing_companion",
                {
                    "selected": None, "primary": candidate,
                    "runtime_blocked": "REQUIRED_COMPANION(Observation.event)",
                    "required_companions": ["Observation.event"],
                },
                {}, [], None,
            ),
            (
                "terminology:closure",
                {"selected": "Observation.value"},
                {"formal_terminology": {
                    "status": "unresolved",
                    "missing_value_sets": [{"id": "vs", "effective_date": "2026"}],
                    "unresolved_includes": [],
                }},
                [], None,
            ),
            (
                "physical:closure",
                {"selected": None, "context": context},
                {},
                [{"template": "section-template", "flexibility": "2026"}],
                None,
            ),
            (
                "physical:containment",
                {
                    "selected": None, "context": context,
                    "unresolved_reason": "structural_only",
                    "alternatives": [{
                        "target": "Detached.entry",
                        "node": {
                            "template_id": "detached-template",
                            "template_effective_date": "2026",
                            "locations": [],
                        },
                    }],
                },
                {}, [], None,
            ),
            (
                "physical:no_writable_leaf",
                {
                    "selected": None, "context": context,
                    "unresolved_reason": "structural_only",
                },
                {}, [], None,
            ),
            (
                "physical:ambiguous_target",
                {
                    "selected": None,
                    "unresolved_reason": "ambiguous_value_target",
                    "alternatives": [candidate, {"target": "Observation.text", "node": {}}],
                },
                {}, [], None,
            ),
            (
                "physical:datatype_component",
                {
                    "selected": None, "context": context,
                    "unresolved_reason": "datatype_component_available",
                },
                {}, [], {"targets": {
                    "Section.code": {
                        "writable": True, "locations": ["0.1.0"],
                    },
                    "Section.deep": {
                        "writable": True, "locations": ["0.1.0.0"],
                    },
                }},
            ),
            (
                "physical:structural_container",
                {
                    "selected": None, "context": structural_context,
                    "unresolved_reason": "structural_container_available",
                },
                {"type": "datetime", "repeat_chain": []}, [], {"targets": {
                    "Medication.routeCode": {
                        "writable": True, "locations": ["0.2.0"],
                        "logical_types": ["code"], "repeat_ancestors": [],
                    },
                    "Medication.deepTime": {
                        "writable": True, "locations": ["0.2.0.0.0"],
                        "logical_types": ["datetime"], "repeat_ancestors": [],
                    },
                    "Medication.deepText": {
                        "writable": True, "locations": ["0.2.0.0"],
                        "logical_types": ["text"], "repeat_ancestors": [],
                    },
                }},
            ),
            (
                "semantic:no_association",
                {
                    "selected": None, "context": structural_context,
                    "unresolved_reason": "structural_container_available",
                    "possible_targets": {
                        "items": [{"target": "Medication.deepTime"}],
                    },
                },
                {"type": "datetime", "repeat_chain": []}, [], None,
            ),
            (
                "semantic:lossy_domain",
                {
                    "selected": None,
                    "unresolved_reason": "incompatible_value_type",
                    "alternatives": [candidate],
                },
                {"type": "datetime"}, [], None,
            ),
            (
                "semantic:no_association",
                {
                    "selected": None, "context": context,
                    "unresolved_reason": "no_semantic_evidence",
                },
                {}, [], None,
            ),
            (
                "blocked_upstream:no_candidate",
                {"selected": None, "unresolved_reason": "no_semantic_evidence"},
                {}, [], None,
            ),
        ]
        for expected, detail, field, unresolved, cda_model in cases:
            with self.subTest(expected=expected):
                gap = classify("case.a", detail, field, unresolved, cda_model)
                self.assertIsNotNone(gap)
                assert gap is not None
                self.assertEqual(f"{gap['gate']}:{gap['kind']}", expected)
                self.assertIsInstance(gap["reopens_with"], list)
                if expected == "physical:datatype_component":
                    self.assertEqual(
                        gap["reopens_with"],
                        ["Section.entry", "Section.code"],
                    )
                if expected == "physical:structural_container":
                    self.assertEqual(
                        gap["reopens_with"],
                        [
                            "Medication.substanceAdministration",
                            "Medication.deepTime",
                            "Medication.routeCode",
                            "Medication.deepText",
                        ],
                    )
                if (
                    expected == "semantic:no_association"
                    and detail.get("possible_targets")
                ):
                    self.assertEqual(
                        gap["reopens_with"], ["association:case.a"]
                    )

        self.assertIsNone(classify(
            "case.complete",
            {"selected": "Observation.value"},
            {"formal_terminology": {"status": "bound", "complete": True}},
            [],
        ))

    def test_gap_trace_explains_unproven_target_inventory(self) -> None:
        trace = _gap_trace({
            "unresolved_reason": "structural_container_available",
            "possible_targets": {"items": [{"target": "Medication.code"}]},
            "gap": {
                "gate": "semantic",
                "kind": "no_association",
                # Cached v9 audits used to repeat the source path here. The
                # renderer must not leak that tautology while the audit is
                # being regenerated with the stable association request key.
                "reopens_with": ["case.a"],
            },
        })

        self.assertEqual(
            trace,
            "semantic:no_association · reopen with upstream association or "
            "reviewed semantic bridge · compatible writable targets are unproven "
            "inventory, not semantic evidence",
        )
        self.assertNotIn("case.a", trace)

    def test_transaction_model_keeps_human_explanations_and_synonyms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            transaction.write_text('''<dataset id="d" transactionId="t">
              <concept id="c" shortName="certainty" type="item">
                <name>Zusatzkennzeichen</name>
                <desc>Diagnosesicherheit</desc>
                <comment>Für jede Diagnose</comment>
                <implementation markdown="V, A, Z oder G"/>
                <valueDomain type="code"><conceptList>
                  <concept><name>Verdachtsdiagnose</name><synonym>V</synonym></concept>
                </conceptList></valueDomain>
              </concept>
            </dataset>''', encoding="utf-8")
            field = compile_model(transaction)["fields"]["certainty"]
            self.assertEqual(field["description"], "Diagnosesicherheit")
            self.assertEqual(field["comment"], "Für jede Diagnose")
            self.assertEqual(field["implementation"], "V, A, Z oder G")
            self.assertEqual(
                field["logical_domain"]["options"]["Verdachtsdiagnose"]["synonyms"],
                ["V"],
            )

    def test_mapping_check_reports_unsupplied_mandatory_cda_leaf(self) -> None:
        leaf = {
            "kind": "element", "name": "hl7:confidentialityCode",
            "datatype": "CE", "min": 1, "max": 1, "mandatory": True,
            "conformance": "M", "attributes": [], "codes": [], "fixed": {},
            "children": [], "targets": ["Header.confidentiality"],
            "origin": {
                "template_id": "1.2.3", "template_effective_date": "2026-01-01",
                "path": "hl7:confidentialityCode",
            },
        }
        target = {
            **leaf, "name": "Header.confidentiality", "locations": ["0.0"],
            "renderable": True, "writable": True, "has_children": False,
            "logical_types": ["code"],
            "value_representation": {
                "kind": "coded", "attributes": ["code"],
                "scalar_attribute": "code",
            },
        }
        compiled = {
            "targets": {"Header.confidentiality": target},
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument",
                "min": 1, "max": 1, "mandatory": True,
                "fixed": {"classCode": "DOCCLIN"}, "attributes": [],
                "targets": [], "children": [leaf],
            }],
        }
        errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, {"fields": {}},
        )
        self.assertTrue(any(
            "mandatory CDA element hl7:confidentialityCode" in error
            for error in errors
        ))

        errors = validate.check_config(
            {"fields": {"privacy": {"type": "code"}}}, compiled,
            {"fields": {"privacy": None}},
            {"fields": {"privacy": "Header.confidentiality"}},
        )
        self.assertFalse(any("mandatory CDA element" in error for error in errors))

        delegated = {
            "fields": {},
            "site_requirements": {
                "Header.confidentiality": {
                    "channel": "values",
                    "reason": "Confidentiality is selected by deployment policy.",
                },
            },
        }
        mapping_only_errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, delegated,
            site={"cda": {"values": {}, "fallback_if_active": {}}},
            require_site_configuration=False,
        )
        self.assertEqual(mapping_only_errors, [])
        accepted = render_accepted_cda_mappings_markdown(
            {"fields": {}}, compiled, delegated,
        )
        self.assertIn("## Required site configuration", accepted)
        self.assertIn("`site.cda.values`", accepted)

        missing_site_errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, delegated,
            site={"cda": {"values": {}, "fallback_if_active": {}}},
        )
        self.assertTrue(any(
            "site: cda.values['Header.confidentiality'] is required" in error
            for error in missing_site_errors
        ))
        self.assertFalse(any(
            "mandatory CDA element" in error for error in missing_site_errors
        ))

        configured_site_errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, delegated,
            site={
                "cda": {
                    "values": {"Header.confidentiality": "N"},
                    "fallback_if_active": {},
                },
            },
        )
        self.assertEqual(configured_site_errors, [])

        wrong_channel_errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, delegated,
            site={
                "cda": {
                    "values": {},
                    "fallback_if_active": {"Header.confidentiality": "N"},
                },
            },
        )
        self.assertTrue(any(
            "configured under cda.fallback_if_active" in error
            for error in wrong_channel_errors
        ))

        invalid_delegation_errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}},
            {"fields": {}, "site_requirements": {
                "Header.confidentiality": {"channel": "values"},
            }},
            site={"cda": {"values": {}, "fallback_if_active": {}}},
            require_site_configuration=False,
        )
        self.assertTrue(any(
            ".reason must be non-empty text" in error
            for error in invalid_delegation_errors
        ))
        self.assertTrue(any(
            "mandatory CDA element" in error
            for error in invalid_delegation_errors
        ))

    def test_build_diagnostics_describe_omissions_and_no_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            inputs = {"unavailable_artifacts": [{
                "request_key": "valueset:vs@2020", "type": "valueset",
                "status": "missing", "roles": ["formal-terminology"],
                "reasons": ["valueset:vs@2020: artifact status is missing"],
            }]}
            cda_model = {"unresolved_templates": [{
                "relation": "include", "template": "nested", "flexibility": "2019",
            }]}
            result = write_build_diagnostics(model_dir, inputs, cda_model)
            self.assertEqual(result["status"], "degraded")
            self.assertFalse(result["policy"]["substitute_revisions"])
            report = (model_dir / "build-diagnostics.md").read_text(encoding="utf-8")
            self.assertIn("valueset:vs@2020", report)
            self.assertIn("nested", report)

    def test_build_diagnostics_include_spec_constraint_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            cda_model = {
                "unresolved_templates": [],
                "constraint_diagnostics": [{
                    "severity": "warning",
                    "code": "spec-constraint-weakening",
                    "path": "hl7:ClinicalDocument/hl7:statusCode",
                    "message": "child weakens parent; using the child",
                }],
            }
            result = write_build_diagnostics(
                model_dir, {"unavailable_artifacts": []}, cda_model,
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["summary"]["constraint_diagnostics"], 1)
            report = (model_dir / "build-diagnostics.md").read_text(
                encoding="utf-8",
            )
            self.assertIn("CDA constraint diagnostics", report)
            self.assertIn("spec-constraint-weakening", report)

    def test_build_diagnostics_limit_headline_to_consulted_terminology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            value_set = model_dir / "valueset.xml"
            value_set.write_text('''<valueSet id="vs" effectiveDate="2020">
              <conceptList><include codeSystem="active-cs"/></conceptList>
            </valueSet>''', encoding="utf-8")
            inputs = {
                "terminology_resources": [value_set],
                "build_artifacts": [],
                "unavailable_artifacts": [
                    {
                        "request_key": "codesystem:active-cs",
                        "type": "codesystem", "id": "active-cs",
                        "status": "missing", "roles": ["expansion-support"],
                        "reasons": [],
                    },
                    {
                        "request_key": "codesystem:display-only",
                        "type": "codesystem", "id": "display-only",
                        "status": "missing", "roles": ["display-evidence"],
                        "reasons": [],
                    },
                ],
            }
            model = {"fields": {"coded": {"formal_terminology": {
                "status": "unresolved", "value_sets": [{"id": "vs"}],
            }}}}
            result = write_build_diagnostics(
                model_dir, inputs, {"unresolved_templates": []}, model
            )
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["summary"]["crawl_degraded"], 2)
            self.assertEqual(
                [item["request_key"] for item in result["build_degraded"]],
                ["codesystem:active-cs"],
            )


if __name__ == "__main__":
    unittest.main()
