from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
import json
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from decor2hl7 import assertions, cda, data, state, validate
from decor2hl7.bindings import build_assignments
from decor2hl7.build import mapping
from decor2hl7.build.mapping import cda_mapping_proposal
from decor2hl7.build.model import compile_model
from decor2hl7.build.target import collect_templates, compile_cda, select_template
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.artifacts import compiler_inputs, write_build_diagnostics
from decor2hl7.compile.cda import compile_cda_model
from decor2hl7.compile.reports import (
    _outline_datapoint_lines, render_cda_mapping_markdown,
)
from decor2hl7.compile.terminology import domain_difference
from decor2hl7.retrieval.artifacts import artifact_problems, artifact_record, closure_records
from decor2hl7.retrieval.catalog import parse_releases, parse_transactions, transactions
from decor2hl7.retrieval.fetch import (
    RequestBudgetExceeded, _candidate_projects, _evidence_references, _fetch_want,
    _inventory, display_references, fetch_spec, hard_references, soft_references,
)
from decor2hl7.retrieval.api import REQUIRED_PATHS, artifact_representations
from decor2hl7.retrieval.sources import apply_source_hint, load_source_hints
from decor2hl7.semantics import accepted_values, direct_compatibility
from decor2hl7.workspace import load_json
from decor2hl7.workspace import (
    init_workspace, input_dir, load_json, release_spec_dir, set_release, set_transaction,
    transaction_mapping_dir, transaction_key, transaction_model_dir,
    transaction_site_dir, transaction_test_dir,
)


RELEASE = {"key": "2026.1.2", "label": "2026.1.2", "date": "2026-04-27T18:50:33", "status": "final"}
TRANSACTION = {
    "key": "notaufnahmeregister--60",
    "id": "2.16.840.1.113883.2.6.60.3.4.60",
    "effective_date": "2026-03-25T00:00:00",
    "version_label": "2026",
    "status": "active",
    "name": "Notaufnahmeregister Transitionsversion",
}


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()


def api_path(url: str) -> str:
    return urlsplit(url).path


class CoreTests(unittest.TestCase):
    def test_workspace_selection_is_path_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            for path in ("spec", "model", "config", "mapping", "site", "test", "out", "state"):
                self.assertTrue((root / path).is_dir())
            self.assertFalse((root / "raw").exists())
            self.assertIsNone(load_json(root / "aktin.json")["release"])
            set_release(root, RELEASE)
            set_transaction(root, TRANSACTION)
            # Selection commands do not create release/transaction artifact paths.
            self.assertFalse(release_spec_dir(root).exists())
            self.assertFalse(transaction_model_dir(root).exists())
            self.assertFalse(transaction_mapping_dir(root).exists())
            self.assertFalse(transaction_site_dir(root).exists())
            self.assertFalse(transaction_test_dir(root).exists())

    def test_external_input_directory_uses_override_then_workspace_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as configured, tempfile.TemporaryDirectory() as override:
            root = Path(tmp)
            init_workspace(root)
            settings = load_json(root / "aktin.json")
            settings["input"]["directory"] = configured
            from decor2hl7.workspace import write_json
            write_json(root / "aktin.json", settings)
            self.assertEqual(input_dir(root), Path(configured).resolve())
            self.assertEqual(input_dir(root, override), Path(override).resolve())
            settings = load_json(root / "aktin.json")
            settings["input"]["directory"] = "relative-input"
            from decor2hl7.workspace import write_json
            write_json(root / "aktin.json", settings)
            self.assertEqual(input_dir(root, required=False), (root / "relative-input").resolve())
            self.assertFalse((root / "raw").exists())

    def test_catalog_keys_are_human_readable_and_stable(self) -> None:
        releases = parse_releases('''<return><release date="2026-04-27T18:50:33" versionLabel="2026.1.2" statusCode="final"/></return>''')
        self.assertEqual(releases[0]["key"], "2026.1.2")
        rows = parse_transactions('''<project><transaction id="2.16.840.1.113883.2.6.60.3.4.60" effectiveDate="2026-03-25T00:00:00" versionLabel="2026"><name>Notaufnahmeregister Transitionsversion</name></transaction></project>''')
        self.assertEqual(rows[0]["key"], "notaufnahmeregister--60")
        self.assertEqual(transaction_key(rows[0]["name"], rows[0]["id"]), rows[0]["key"])

    def test_transaction_catalog_uses_current_api_transaction_view(self) -> None:
        calls: list[str] = []
        def fake_get(url: str, **_: object) -> bytes:
            calls.append(url)
            return b'<return><transaction id="1.2.3" effectiveDate="2026-01-01T00:00:00" versionLabel="2026"><name>Example</name></transaction></return>'
        with patch("decor2hl7.retrieval.catalog.get", side_effect=fake_get):
            rows = transactions("aktin-", "2026-04-27T18:50:33", ipv4=True)
        self.assertEqual(rows[0]["id"], "1.2.3")
        self.assertEqual(len(calls), 1)
        self.assertTrue(api_path(calls[0]).endswith("/transaction"))
        self.assertIn("project=aktin-", calls[0])
        self.assertIn("release=2026-04-27T18%3A50%3A33", calls[0])

    def test_template_api_retains_source_and_expanded_analysis_forms(self) -> None:
        rows = artifact_representations(
            {
                "kind": "template", "id": "1.2.3",
                "effective_date": "2025-05-01T00:00:00",
            },
            project="aktin-", main_project="aktin-", release=RELEASE["date"],
            language="de-DE",
        )
        self.assertEqual([row["form"] for row in rows], ["source", "analysis"])
        self.assertIn("/template/1.2.3/2025-05-01T00%3A00%3A00/$extract", rows[0]["url"])
        self.assertNotIn("tree=expand", rows[0]["url"])
        self.assertIn("tree=expand", rows[1]["url"])
        self.assertFalse(any("/decor/services/" in row["url"] for row in rows))
        self.assertFalse(any("expandedxml" in row["url"] for row in rows))

    def test_external_source_hint_supplies_exact_repository_identity(self) -> None:
        resolved = apply_source_hint(
            {
                "kind": "template",
                "id": "1.3.6.1.4.1.19376.1.9.1.3.1",
                "effective_date": "",
                "project": "",
            },
            load_source_hints(),
        )
        self.assertEqual(resolved["project"], "ch-pharm-")
        self.assertEqual(resolved["effective_date"], "2019-08-27T16:13:43")
        self.assertTrue(resolved["api_base"].endswith("/exist/apps/api"))

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
            concept, project="ext-", main_project="aktin-", release=RELEASE["date"],
            language="de-DE",
        )
        self.assertIn("transactionId=9", rows[0]["url"])
        self.assertIn("datasetOrTransactionId=9", rows[1]["url"])
        self.assertNotIn("release=", rows[1]["url"])

    def test_reference_project_is_inferred_from_art_decor_link(self) -> None:
        root = ET.fromstring('''<template>
          <include ref="1.2.3" flexibility="dynamic"
            href="https://art-decor.org/exist/apps/api/project/ad1bbr-/template/1.2.3"/>
          <vocabulary codeSystem="2.16.840.1.113883.5.25"
            url="https://art-decor.org/exist/apps/api/codesystem/2.16.840.1.113883.5.25?project=ad1bbr-"/>
        </template>''')
        template = next(
            row for row in hard_references(root) if row["kind"] == "template"
        )
        codesystem = next(
            row for row in display_references(root) if row["kind"] == "codesystem"
        )
        self.assertEqual(template["project"], "ad1bbr-")
        self.assertEqual(codesystem["project"], "ad1bbr-")

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
                domain_difference(field)["logical_only"], ["Logical only"]
            )
            self.assertEqual(len(field["terminology_associations"]), 2)
            self.assertEqual(
                {row["scope"] for row in field["terminology_associations"]},
                {"lineage-concept", "related-concept"},
            )
            self.assertEqual(
                [(row["code"], row["scope"]) for row in field["codes"]],
                [("B", "lineage-concept")],
            )
            defaults = mapping.code_mapping_defaults(model)["fields"]["status"]
            self.assertEqual(defaults["A"], "Alpha")
            self.assertNotIn("Logical only", defaults)
            self.assertNotIn("values", field)

    def test_named_cda_target_and_ta_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''
<project>
  <templateAssociation templateId="doc" effectiveDate="2026-01-01"><concept ref="c" elementId="e"/></templateAssociation>
  <template id="doc" effectiveDate="2026-01-01" name="ExampleDocument">
    <element name="hl7:ClinicalDocument" id="root" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:value" id="e" datatype="ST" minimumMultiplicity="0" maximumMultiplicity="1"/>
    </element>
  </template>
</project>''', encoding="utf-8")
            model = {"meta": {"template_id": "doc", "template_effective_date": "2026-01-01"}, "groups": {}, "fields": {"foo": {"name": "Foo", "concept": "c", "type": "text", "value_sets": [], "codes": [], "parent": None}}}
            target = compile_cda([project], model)
            self.assertIn("ExampleDocument.value", target["targets"])
            proposal, report = cda_mapping_proposal(model, target, [project])
            _, _, details = mapping.cda_mapping_reports(model, target, [project])
            self.assertEqual(proposal["fields"]["foo"], "ExampleDocument.value")
            self.assertIn("TA", report)
            self.assertIn("Reason", report)
            self.assertIn("Candidates", report)
            self.assertNotIn("Evidence chain", report)
            self.assertIn("Evidence chain", details)
            self.assertIn("Dataset concept: `c`", details)
            output = Path(tmp) / "model"
            output.mkdir()
            mapping.write_cda_mapping([project], output, model, target)
            audit = load_json(output / "mapping-audit.json")
            self.assertEqual(audit["fields"]["foo"]["selected"], "ExampleDocument.value")
            readable = (output / "cda-expanded-readable.xml").read_text(encoding="utf-8")
            self.assertIn("Mapped dataset path(s): foo", readable)
            self.assertTrue((output / "cda-expanded-readable.md").is_file())
            guide = (output / "cda-mapping.md").read_text(encoding="utf-8")
            self.assertIn(
                "| Name in dataset | `model.json` datapoint | "
                "`cda-mapping.json` target | Name in CDA template | Status |",
                guide,
            )
            self.assertIn(
                'setting `fields["foo"]` to `"ExampleDocument.value"`', guide
            )
            self.assertLess(
                guide.index("Abridged configuration excerpt"),
                guide.index("Resulting CDA placement"),
            )
            self.assertNotIn("Put the value", guide)


    def test_ta_selects_formally_bound_hl7_code_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''
<project>
  <templateAssociation templateId="entry" effectiveDate="2026-01-01">
    <concept ref="referral" elementId="referral-code"/>
  </templateAssociation>
  <template id="entry" effectiveDate="2026-01-01" name="Referral">
    <element name="hl7:act" id="act" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:participant" id="participant" minimumMultiplicity="1" maximumMultiplicity="1">
        <element name="hl7:participantRole" id="role" minimumMultiplicity="1" maximumMultiplicity="1">
          <element name="hl7:code" id="referral-code" datatype="CE"
                   minimumMultiplicity="1" maximumMultiplicity="1" conformance="R">
            <vocabulary valueSet="referral-vs"/>
            <element name="hl7:originalText" id="referral-text" datatype="ST"
                     minimumMultiplicity="0" maximumMultiplicity="1"/>
          </element>
        </element>
      </element>
    </element>
  </template>
</project>''', encoding="utf-8")
            field = {
                "name": "Zuweisung",
                "concept": "referral",
                "type": "code",
                "value_sets": ["referral-vs"],
                "value_set_refs": [{"id": "referral-vs", "effective_date": "2025-01-01"}],
                "formal_terminology": {
                    "value_sets": [{"id": "referral-vs", "effective_date": "2025-01-01"}],
                    "members": {
                        "Notarzt": {
                            "code": "NA",
                            "code_system": "1.2.3",
                            "display_name": "Notarzt",
                        }
                    },
                    "complete": True,
                },
                "accepted_values": {
                    "Notarzt": {
                        "code": "NA",
                        "code_system": "1.2.3",
                        "display_name": "Notarzt",
                    }
                },
                "codes": [],
                "parent": None,
            }
            model = {
                "meta": {
                    "template_id": "entry",
                    "template_effective_date": "2026-01-01",
                },
                "groups": {},
                "fields": {"referral": field},
            }
            target = compile_cda([project], model)
            target_name = "Referral.act.participant.participantRole.code"
            self.assertTrue(target["targets"][target_name]["has_children"])
            self.assertEqual(
                direct_compatibility(field, target["targets"][target_name]),
                (True, []),
            )
            proposal, _ = cda_mapping_proposal(model, target, [project])
            self.assertEqual(proposal["fields"]["referral"], target_name)

            section_code = {
                **target["targets"][target_name],
                "path": "hl7:section/hl7:code",
                "value_sets": ["section-vs"],
                "codes": [{"code": "11293-8", "code_system": "2.16.840.1.113883.6.1"}],
            }
            compatible, reasons = direct_compatibility(field, section_code)
            self.assertFalse(compatible)
            self.assertIn("not a direct code payload", reasons[0])

    def test_mapping_outline_keeps_names_and_wraps_long_targets(self) -> None:
        short = _outline_datapoint_lines(
            "│   │   ",
            {"dataset_name": "Patienten ID", "target": "PatientIdentifier.id"},
            last=True,
        )
        self.assertEqual(
            short,
            ["│   │   └── Patienten ID → {PatientIdentifier.id}"],
        )

        long = _outline_datapoint_lines(
            "│   │   ",
            {
                "dataset_name": "Aufnahmezeitpunkt",
                "target": (
                    "CDAEncompassingEncounter.componentOf.encompassingEncounter."
                    "effectiveTime.low@20160601"
                ),
            },
            last=False,
        )
        self.assertEqual(
            long,
            [
                "│   │   ├── Aufnahmezeitpunkt",
                "│   │   │   → {CDAEncompassingEncounter.componentOf."
                "encompassingEncounter.effectiveTime.low@20160601}",
            ],
        )

    def test_cda_guide_merges_xml_context_and_explains_candidates(self) -> None:
        def element(name: str, children: list[dict] | None = None, **values: object) -> dict:
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
        section = element("hl7:section", [candidate], target="Referral.section")
        document = element("hl7:ClinicalDocument", [header, element("hl7:component", [section])])
        cda_model = {
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
                },
            },
        }
        model = {
            "order": ["case.start", "case.end", "case.referral"],
            "groups": {"case": {"name": "Case"}},
            "fields": {
                "case.start": {"name": "Start"},
                "case.end": {"name": "End"},
                "case.referral": {"name": "Referral source"},
            },
        }
        mapping_cfg = {"fields": {
            "case.start": "Encounter.low", "case.end": "Encounter.high",
            "case.referral": None,
        }}
        audit = {
            "summary": {"field_coverage": {"NO": 1}},
            "fields": {"case.referral": {"alternatives": [{
                "target": "Referral.code", "datatype": "CE", "confidence": "STRONG",
                "chain": ["SPEC", "TA"], "actionable": False,
            }]}},
        }
        report = render_cda_mapping_markdown(model, cda_model, mapping_cfg, audit)
        self.assertIn('<componentOf typeCode="COMP">', report)
        self.assertIn('<encompassingEncounter classCode="ENC" moodCode="EVN">', report)
        self.assertIn('<low value="{Encounter.low}"/>', report)
        self.assertIn('<high value="{Encounter.high}"/>', report)
        self.assertIn("**1** unresolved dataset datapoint(s)", report)
        self.assertIn("Referral code", report)
        self.assertIn("SPEC → TA", report)
        self.assertIn("evidence only", report)
        self.assertIn("None of these rows is directly selectable", report)

    def test_code_normalization_and_unmapped_code(self) -> None:
        field = {"type": "code", "values": {"rot": {"code": "R", "code_system": "1.2.3", "display_name": "rot"}}}
        site = {"null_flavor": {"unmapped_code": "OTH"}, "input": {}}
        self.assertEqual(data.normalize_value("1", field, {"1": "rot"}, site)["code"], "R")
        self.assertEqual(data.normalize_value("X", field, {}, site)["nullFlavor"], "OTH")

    def test_cda_renderer(self) -> None:
        compiled = {
            "targets": {"Doc.value": {"element_id": None, "renderable": True, "locations": ["0.0"]}},
            "document": [{"kind": "element", "name": "hl7:ClinicalDocument", "id": "r", "min": 1, "max": 1,
                "mandatory": True, "attributes": [], "codes": [], "fixed": {}, "targets": [],
                "children": [{"kind": "element", "name": "hl7:value", "id": None, "datatype": "ST", "min": 0,
                    "max": 1, "mandatory": False, "attributes": [], "codes": [], "fixed": {}, "children": [],
                    "targets": ["Doc.value"], "target": "Doc.value"}]}],
        }
        payload, problems = cda.emit({"key": "1", "values": {"foo": "hello"}}, {"fields": {"foo": {}}}, compiled,
                                     {"fields": {"foo": "Doc.value"}}, {"null_flavor": {"missing_required": "NI"}})
        root = ET.fromstring(payload)
        self.assertEqual(root[0].text, "hello")
        self.assertEqual(problems, [])

    def test_spec_replaced_containment_does_not_survive_as_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''
<project>
  <template id="old-section" effectiveDate="2020-01-01" name="VitalSignsSectionOld"><element name="hl7:section" id="section"><element name="hl7:entry" contains="observation" id="entry"/></element></template>
  <template id="new-section" effectiveDate="2026-01-01" name="VitalSignsSectionNew"><relationship type="VERSION" template="old-section" flexibility="2020-01-01"/><element name="hl7:section" id="section"><element name="hl7:entry" contains="container" id="entry"/></element></template>
  <template id="observation" effectiveDate="2020-01-01" name="Observation"><element name="hl7:observation" id="obs"><element name="hl7:value" id="value" datatype="PQ"/></element></template>
  <template id="container" effectiveDate="2026-01-01" name="Container"><element name="hl7:organizer" id="org"><element name="hl7:component" contains="observation" id="component"/></element></template>
  <template id="parent-doc" effectiveDate="2020-01-01" name="ParentDocument"><element name="hl7:ClinicalDocument" id="doc"><element name="hl7:component" contains="old-section" id="vital-component"/></element></template>
  <template id="doc" effectiveDate="2026-01-01" name="Document"><relationship type="SPEC" template="parent-doc" flexibility="2020-01-01"/><element name="hl7:ClinicalDocument" id="doc"><element name="hl7:component" contains="new-section" id="vital-component"/></element></template>
</project>''', encoding="utf-8")
            compiled = compile_cda([project], {"meta": {"template_id": "doc", "template_effective_date": "2026-01-01"}, "groups": {}, "fields": {}})
            contains: list[str] = []
            def walk(nodes: list[dict[str, object]]) -> None:
                for node in nodes:
                    if node.get("contains"):
                        contains.append(str(node["contains"]))
                    walk(list(node.get("children", [])))
            walk(compiled["document"])
            self.assertIn("new-section", contains)
            self.assertNotIn("old-section", contains)


    def test_fetch_uses_release_cache_and_transaction_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "notaufnahmeregister--60"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b'<return><project id="9.9" prefix="ext-"/></return>'
                if "/transaction/t/" in path:
                    return b'<dataset id="d" transactionId="t" templateId="doc"><concept id="c" shortName="x" type="group"><name>X</name><contains ref="old" datasetId="9.9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if path.endswith("/project/aktin-/$extract"):
                    return b'<project><transaction id="t"><representingTemplate ref="doc"/></transaction><dataset id="9.9.1" effectiveDate="2020-01-01"><concept id="old" shortName="old" type="item"><name>Old embedded</name></concept></dataset></project>'
                if path.endswith("/project/aktin-"):
                    return b'<project><buildingBlockRepository ident="ext-"/></project>'
                if "/dataset/9.9.1/" in path:
                    return b'<dataset id="9.9.1" effectiveDate="2020-01-01"><concept id="old" shortName="old" type="item"><name>Old</name></concept></dataset>'
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026-01-01" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t"},
                    retry_missing=False, max_requests=50, progress=progress.append,
                )
            self.assertTrue((release_dir / "manifest.json").exists())
            self.assertTrue((tx_dir / "transaction.xml").exists())
            self.assertTrue((tx_dir / "closure.json").exists())
            self.assertTrue(any(path.parent.name == "datasets" for path in release_dir.rglob("*.xml")))
            self.assertTrue(any("/dataset/9.9.1/" in api_path(url) for url in calls))
            self.assertTrue(any(path.parent.name == "templates" for path in release_dir.rglob("*.xml")))
            self.assertFalse(result["closure"]["truncated"])
            self.assertTrue(any("API contract" in line and "requesting" in line for line in progress))
            self.assertTrue(any("dataset 9.9.1 @ 2020-01-01" in line for line in progress))
            self.assertTrue(any(line.startswith("fetch: complete:") for line in progress))

            before = len(calls)
            with patch("decor2hl7.retrieval.fetch.get", side_effect=AssertionError("cache miss")):
                fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t"},
                    retry_missing=False, max_requests=50,
                )
            self.assertEqual(len(calls), before)

    def test_fetches_static_template_even_when_present_in_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="2026-01-15T00:00:00"/></transaction>'
                if path.endswith("/project/aktin-/$extract"):
                    return b'<project><template id="doc" effectiveDate="2026-01-15T00:00:00" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></project>'
                if path.endswith("/project/aktin-"):
                    return b'<project/>'
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026-01-15T00:00:00" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20, progress=progress.append,
                )

            self.assertTrue(any("/template/doc/" in api_path(url) for url in calls))
            self.assertFalse(result["closure"]["errors"])
            self.assertTrue(result["closure"]["build_ready"])
            self.assertIn(
                "template:doc@2026-01-15T00:00:00",
                result["closure"]["build_resources"],
            )

    def test_dynamic_template_is_fetched_and_frozen_not_taken_from_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="dynamic"/></transaction>'
                if path.endswith("/project/aktin-/$extract"):
                    return (
                        b'<project>'
                        b'<template id="doc" effectiveDate="2026-02-01T00:00:00" name="ReleasedDoc"><element name="hl7:ClinicalDocument" id="released"/></template>'
                        b'<template id="doc" effectiveDate="2026-05-01T00:00:00" name="FutureDraft"><element name="hl7:ClinicalDocument" id="future"/></template>'
                        b'</project>'
                    )
                if path.endswith("/project/aktin-"):
                    return b'<project/>'
                if "/template/doc" in path:
                    return b'<return><template id="doc" effectiveDate="2026-02-01T00:00:00" name="ReleasedDoc"><element name="hl7:ClinicalDocument" id="released"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20, progress=progress.append,
                )

            self.assertTrue(any("/template/doc" in api_path(url) for url in calls))
            self.assertFalse(result["closure"]["errors"])
            entry = result["manifest"]["resources"]["template:doc"]
            self.assertEqual(entry["resolved_effective_date"], "2026-02-01T00:00:00")
            self.assertTrue(result["closure"]["build_ready"])

    def test_fetch_interrupt_writes_incomplete_closure_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"

            def fake_get(url: str, **_: object) -> bytes:
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<dataset id="d"><concept id="c"><contains ref="old" datasetId="9.9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if path.endswith("/project/aktin-/$extract") or path.endswith("/project/aktin-"):
                    return b'<project><transaction id="t"/></project>'
                if "/dataset/9.9.1/" in path:
                    raise KeyboardInterrupt
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                with self.assertRaises(KeyboardInterrupt):
                    fetch_spec(
                        release_dir, tx_dir, prefix="aktin-",
                        release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                        max_requests=20, progress=progress.append,
                    )

            closure = load_json(tx_dir / "closure.json")
            self.assertFalse(closure["complete"])
            self.assertTrue(closure["interrupted"])
            self.assertIn("build-interrupted", closure["phase"])
            self.assertIn("dataset:9.9.1@2020-01-01", closure["pending"]["build"])
            self.assertTrue((release_dir / "manifest.json").exists())
            self.assertTrue(any("checkpoint saved" in line for line in progress))
            with self.assertRaisesRegex(ValueError, "crawl is incomplete"):
                from decor2hl7.retrieval.fetch import closure_paths
                closure_paths(release_dir, tx_dir)

            # A cache-only rerun settles the pending closure without touching
            # the unavailable server. Uncached dependencies remain explicit
            # degraded inputs and can be retried by a later online fetch.
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("offline fetch attempted HTTP"),
            ) as mocked:
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE,
                    transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    offline=True, max_requests=20,
                )
            self.assertEqual(mocked.call_count, 0)
            self.assertTrue(result["closure"]["crawl_complete"])
            self.assertTrue(result["closure"]["build_ready"])
            self.assertEqual(result["closure"]["recursive_http_requests"], 0)
            self.assertIn(
                "dataset:9.9.1@2020-01-01",
                result["closure"]["unavailable"],
            )

    def test_recursive_request_budget_counts_actual_http_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "project": "first-"}
            budget = {"made": 0, "max": 1}
            def missing(_url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(_url, 404, "missing", None, None)
            with patch("decor2hl7.retrieval.fetch.get", side_effect=missing):
                with self.assertRaises(RequestBudgetExceeded):
                    _fetch_want(
                        Path(tmp), manifest, want, owners={}, repositories=["first-", "second-"],
                        language="de-DE", ipv4=True, retry_missing=False, request_budget=budget,
                    )
            self.assertEqual(budget["made"], 1)
            self.assertNotIn("template:1.2.3", manifest["resources"])


    def test_state_change_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            digest = state.fingerprint({"values": {"a": 1}})
            self.assertEqual(state.classify(path, "tx::x", digest), ("NEW", 1))
            state.record_sent(path, key="tx::x", digest=digest, document_version=1, file="x.xml", spec_version="v")
            self.assertEqual(state.classify(path, "tx::x", digest)[0], "UNCHANGED")

    def test_datetime_requires_time_when_precision_does(self) -> None:
        with self.assertRaises(ValueError):
            data.normalize_value("2026-08-21", {"type": "datetime", "precision": "YMDHM"}, {}, {"timezone": "Europe/Berlin", "input": {}})

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
            model = {
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

    def test_fan_out_creates_side_discriminated_occurrences(self) -> None:
        model = {"fields": {
            "pupil.right": {"type": "text", "repeat_chain": []},
            "pupil.left": {"type": "text", "repeat_chain": []},
        }}
        cda_model = {"targets": {
            "Pupil.value": {
                "datatype": "ST", "path": "hl7:observation/hl7:value",
                "renderable": True, "locations": ["0.0.0"],
                "repeat_ancestors": ["0.0"],
            },
            "Pupil.side": {
                "datatype": "CD", "path": "hl7:observation/hl7:targetSiteCode",
                "renderable": True, "locations": ["0.0.1"],
                "repeat_ancestors": ["0.0"],
            },
        }}
        mapping_cfg = {
            "fields": {
                "pupil.right": {
                    "target": "Pupil_right.value", "cda_target": "Pupil.value",
                    "structure": "pupils", "branch": "right",
                },
                "pupil.left": {
                    "target": "Pupil_left.value", "cda_target": "Pupil.value",
                    "structure": "pupils", "branch": "left",
                },
            },
            "structures": {"pupils": {
                "type": "fan_out",
                "branches": [
                    {"source": "pupil.right", "target": "Pupil_right.value",
                     "cda_target": "Pupil.value", "constants": {
                        "Pupil.side": {"code": "R", "codeSystem": "1.2.276.0.76.3.1.195.5.48", "displayName": "Auge rechts"},
                    }},
                    {"source": "pupil.left", "target": "Pupil_left.value",
                     "cda_target": "Pupil.value", "constants": {
                        "Pupil.side": {"code": "L", "codeSystem": "1.2.276.0.76.3.1.195.5.48", "displayName": "Auge links"},
                    }},
                ],
            }},
        }
        assignments, problems = build_assignments(
            {"values": {"pupil.right": "3", "pupil.left": "2"}, "instances": {}},
            model, cda_model, mapping_cfg, {},
        )
        self.assertEqual(assignments["Pupil.value"], ["3", "2"])
        self.assertEqual([value["code"] for value in assignments["Pupil.side"]], ["R", "L"])
        self.assertFalse(problems)
        datapoints = mapping_compiler.cda_datapoints(cda_model, mapping_cfg)
        self.assertEqual(
            set(datapoints), {"Pupil_right.value", "Pupil_left.value"}
        )
        self.assertEqual(
            {value["cda_target"] for value in datapoints.values()},
            {"Pupil.value"},
        )
        self.assertEqual(
            datapoints["Pupil_right.value"]["occurrence"]["branch"], "right"
        )
        report_cda = {
            **cda_model,
            "document_template": {
                "id": "1.2.3", "effective_date": "2026-01-01T00:00:00",
                "name": "Document", "display_name": "Test document",
            },
            "document": [],
            "datapoints": datapoints,
        }
        report = render_cda_mapping_markdown(
            model, report_cda, mapping_cfg,
            {"summary": {"field_coverage": {"NO": 0}}},
        )
        self.assertIn("{Pupil_right.value}", report)
        self.assertIn("{Pupil_left.value}", report)
        self.assertLess(
            report.index("Abridged configuration excerpt"),
            report.index("Resulting CDA placement"),
        )
        self.assertIn("do not edit the XML examples", report)
        self.assertIn("review the rule stored at `fields[\"pupil.right\"]`", report)
        self.assertIn("Text in `{braces}` names a generated CDA datapoint", report)
        self.assertEqual(
            validate.check_config(
                model, cda_model,
                {"fields": {"pupil.right": None, "pupil.left": None}},
                mapping_cfg,
            ),
            [],
        )

    def test_compiler_infers_data_driven_structural_and_certainty_rules(self) -> None:
        pupil_model = {"fields": {
            "vitals.pupil_right": {
                "name": "Pupillenweite rechts", "type": "code",
                "repeat_chain": ["vitals"],
            },
            "vitals.pupil_left": {
                "name": "Pupillenweite links", "type": "code",
                "repeat_chain": ["vitals"],
            },
        }}
        pupil_cda = {"targets": {
            "Pupil.value": {
                "path": "hl7:observation/hl7:value", "renderable": True,
                "locations": ["0.0.0"], "repeat_ancestors": ["0", "0.0"],
            },
            "Pupil.targetSiteCode": {
                "path": "hl7:observation/hl7:targetSiteCode", "renderable": True,
                "locations": ["0.0.1"], "repeat_ancestors": ["0", "0.0"],
                "value_sets": ["eye-sides"],
            },
        }}
        inferred = mapping_compiler._fanout_rule(
            ["vitals.pupil_right", "vitals.pupil_left"], "Pupil.value",
            pupil_model, pupil_cda,
            {"eye-sides": [
                {"code": "362502000", "codeSystem": "2.16.840.1.113883.6.96", "displayName": "Entire right eye"},
                {"code": "362503005", "codeSystem": "2.16.840.1.113883.6.96", "displayName": "Entire left eye"},
            ]},
        )
        self.assertIsNotNone(inferred)
        _, fanout = inferred
        self.assertEqual(
            [branch["target"] for branch in fanout["branches"]],
            ["Pupil_right.value", "Pupil_left.value"],
        )
        self.assertEqual(
            {branch["cda_target"] for branch in fanout["branches"]},
            {"Pupil.value"},
        )
        self.assertEqual(
            [branch["constants"]["Pupil.targetSiteCode"]["code"] for branch in fanout["branches"]],
            ["362502000", "362503005"],
        )

        certainty_field = {
            "name": "Zusatzkennzeichen",
            "accepted_values": {
                "Verdachtsdiagnose": {"synonyms": ["V"]},
                "ausgeschlossene Diagnose": {"synonyms": ["A"]},
                "Zustand nach": {"synonyms": ["Z"]},
                "gesicherte Diagnose": {"synonyms": ["G"]},
            },
        }
        certainty_cda = {"targets": {
            "Certainty.value": {
                "path": "hl7:qualifier/hl7:value", "renderable": True,
                "locations": ["0.0"], "repeat_ancestors": ["0"],
                "value_sets": ["certainty-vs"],
            },
            "Diagnosis.negationInd": {
                "path": "hl7:observation/@negationInd", "renderable": True,
                "locations": ["0.1"], "repeat_ancestors": ["0"],
            },
            "Diagnosis.low": {
                "kind": "element", "datatype": "TS", "min": 1, "max": 1,
                "mandatory": False, "has_children": False, "conformance": "R",
                "path": "hl7:observation/hl7:effectiveTime/hl7:low",
                "renderable": True, "locations": ["0.2"],
                "repeat_ancestors": ["0"],
            },
        }}
        certainty = mapping_compiler._certainty_mapping(
            "diagnoses.certainty", certainty_field, certainty_cda,
            {"certainty-vs": [
                {"code": code, "codeSystem": "example-certainty", "displayName": code}
                for code in "VAZG"
            ]},
        )
        self.assertIsNotNone(certainty)
        selection, metadata = certainty
        self.assertIn("VS(certainty-vs)", selection["primary"]["chain"])
        self.assertFalse(any(rule.get("mode") == "fallback" for rule in selection["mapping"]))
        self.assertEqual(
            metadata["target_defaults"]["Diagnosis.low"]["nullFlavor"], "UNK"
        )
        certainty_datapoints = mapping_compiler.cda_datapoints(
            certainty_cda,
            {
                "fields": {"diagnoses.certainty": selection["mapping"]},
                "target_defaults": metadata["target_defaults"],
            },
        )
        self.assertEqual(
            certainty_datapoints["Diagnosis.low"]["default"]["nullFlavor"],
            "UNK",
        )
        self.assertEqual(certainty_datapoints["Diagnosis.low"]["dataset_fields"], [])

        coalesced = mapping_compiler._coalesce_rule(
            ["encounter.admission", "encounter.documentation"], "Encounter.low",
            {"fields": {
                "encounter.admission": {"type": "datetime", "repeat_chain": []},
                "encounter.documentation": {"type": "datetime", "repeat_chain": []},
            }},
            {"targets": {"Encounter.low": {"repeat_ancestors": []}}},
        )
        self.assertEqual(coalesced[1]["policy"], "equal_or_error")

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

    def test_coalesce_equal_or_error(self) -> None:
        model = {"fields": {
            "encounter.admission": {"type": "datetime"},
            "encounter.documentation_start": {"type": "datetime"},
        }}
        cda_model = {"targets": {"Encounter.time": {
            "datatype": "TS", "renderable": True, "locations": ["0.0"],
            "repeat_ancestors": [],
        }}}
        mapping_cfg = {
            "fields": {
                "encounter.admission": "Encounter.time",
                "encounter.documentation_start": "Encounter.time",
            },
            "structures": {"encounter-time": {
                "type": "coalesce", "policy": "equal_or_error",
                "sources": ["encounter.admission", "encounter.documentation_start"],
                "target": "Encounter.time",
            }},
        }
        value = "2026-08-28T10:15:00+02:00"
        assignments, _ = build_assignments(
            {"values": {"encounter.admission": value, "encounter.documentation_start": value}},
            model, cda_model, mapping_cfg, {},
        )
        self.assertEqual(assignments["Encounter.time"], value)
        one, _ = build_assignments(
            {"values": {"encounter.admission": value}}, model, cda_model, mapping_cfg, {},
        )
        self.assertEqual(one["Encounter.time"], value)
        with self.assertRaisesRegex(ValueError, "differing values"):
            build_assignments(
                {"values": {
                    "encounter.admission": value,
                    "encounter.documentation_start": "2026-08-28T10:16:00+02:00",
                }},
                model, cda_model, mapping_cfg, {},
            )

    def test_explicit_diagnosis_fallback_is_occurrence_aligned(self) -> None:
        # This verifies the generic, explicitly configured fallback mechanism.
        # The compiler intentionally does not generate a Z-to-end-time rule.
        fields = {
            "diagnoses.certainty": {"type": "code", "repeat_chain": ["diagnoses"]},
            "diagnoses.end": {"type": "datetime", "repeat_chain": ["diagnoses"]},
        }
        targets = {
            "Diagnosis.certainty": {
                "datatype": "CD", "renderable": True, "locations": ["0.0.0"],
                "repeat_ancestors": ["0.0"],
            },
            "Diagnosis.negation": {
                "datatype": "BL", "renderable": True, "locations": ["0.0.1"],
                "repeat_ancestors": ["0.0"],
            },
            "Diagnosis.high": {
                "datatype": "TS", "renderable": True, "locations": ["0.0.2"],
                "repeat_ancestors": ["0.0"],
            },
        }
        certainty_map = {
            code: {"code": code, "codeSystem": "1.2.276.0.76.11.121"}
            for code in "VAZG"
        }
        mapping_cfg = {"fields": {
            "diagnoses.certainty": [
                {"target": "Diagnosis.certainty", "transform": {
                    "type": "enum", "select": "raw", "map": certainty_map,
                }},
                {"target": "Diagnosis.negation", "transform": {
                    "type": "enum", "select": "raw", "map": {"A": True},
                }},
                {"target": "Diagnosis.high", "mode": "fallback", "transform": {
                    "type": "enum", "select": "raw", "map": {"Z": {"nullFlavor": "UNK"}},
                }},
            ],
            "diagnoses.end": "Diagnosis.high",
        }}
        record = {"values": {}, "instances": {"diagnoses": [
            {"values": {
                "diagnoses.certainty": {"raw": "A", "canonical": "Ausgeschlossen", "code": "A"},
            }},
            {"values": {
                "diagnoses.certainty": {"raw": "Z", "canonical": "Zustand nach", "code": "Z"},
            }},
            {"values": {
                "diagnoses.certainty": {"raw": "Z", "canonical": "Zustand nach", "code": "Z"},
                "diagnoses.end": "2026-08-28T12:00:00+02:00",
            }},
        ]}}
        assignments, _ = build_assignments(record, {"fields": fields}, {"targets": targets}, mapping_cfg, {})
        self.assertEqual([item["code"] for item in assignments["Diagnosis.certainty"]], ["A", "Z", "Z"])
        self.assertEqual(assignments["Diagnosis.negation"], [True, None, None])
        self.assertEqual(assignments["Diagnosis.high"][0], None)
        self.assertEqual(assignments["Diagnosis.high"][1], {"nullFlavor": "UNK"})
        self.assertEqual(assignments["Diagnosis.high"][2], "2026-08-28T12:00:00+02:00")

    def test_mapping_owned_defaults_complete_each_active_occurrence(self) -> None:
        def target(location: str, datatype: str, minimum: int = 1) -> dict[str, object]:
            return {
                "kind": "element", "datatype": datatype, "min": minimum, "max": 1,
                "mandatory": False, "has_children": False, "conformance": "R",
                "renderable": True, "locations": [location],
                "repeat_ancestors": ["0.0"], "fixed": {},
                "template_name": "Diagnosis", "template_display_name": "Diagnosis",
            }

        compiled = {
            "targets": {
                "Diagnosis.value": {
                    **target("0.0.0", "ST"),
                    "path": "hl7:observation/hl7:value",
                },
                "Diagnosis.low": {
                    **target("0.0.1", "TS"),
                    "path": "hl7:observation/hl7:effectiveTime/hl7:low",
                },
                "Diagnosis.requiredNote": {
                    **target("0.0.2", "ST"),
                    "path": "hl7:observation/hl7:text",
                },
                "Diagnosis.optionalComment": {
                    **target("0.0.3", "ST", 0),
                    "path": "hl7:observation/hl7:comment",
                },
            },
            "document_template": {
                "id": "1.2.3", "effective_date": "2026-01-01",
                "name": "Document", "display_name": "Test document",
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1,
                "max": 1, "mandatory": True, "attributes": [], "codes": [],
                "fixed": {}, "targets": [], "children": [{
                    "kind": "element", "name": "hl7:observation", "min": 0,
                    "max": None, "mandatory": False, "attributes": [], "codes": [],
                    "fixed": {}, "targets": [], "children": [
                        {"kind": "element", "name": "hl7:value", "datatype": "ST",
                         "min": 1, "max": 1, "mandatory": False, "attributes": [],
                         "codes": [], "fixed": {}, "children": [],
                         "targets": ["Diagnosis.value"], "target": "Diagnosis.value"},
                        {"kind": "element", "name": "hl7:low", "datatype": "TS",
                         "min": 1, "max": 1, "mandatory": False, "attributes": [],
                         "codes": [], "fixed": {}, "children": [],
                         "targets": ["Diagnosis.low"], "target": "Diagnosis.low"},
                        {"kind": "element", "name": "hl7:text", "datatype": "ST",
                         "min": 1, "max": 1, "mandatory": False, "attributes": [],
                         "codes": [], "fixed": {}, "children": [],
                         "targets": ["Diagnosis.requiredNote"],
                         "target": "Diagnosis.requiredNote"},
                        {"kind": "element", "name": "hl7:comment", "datatype": "ST",
                         "min": 0, "max": 1, "mandatory": False, "attributes": [],
                         "codes": [], "fixed": {}, "children": [],
                         "targets": ["Diagnosis.optionalComment"],
                         "target": "Diagnosis.optionalComment"},
                    ],
                }],
            }],
        }
        model = {"fields": {
            "diagnoses.value": {"type": "text", "repeat_chain": ["diagnoses"]},
            "diagnoses.onset": {"type": "datetime", "repeat_chain": ["diagnoses"]},
            "diagnoses.note": {"type": "text", "repeat_chain": ["diagnoses"]},
        }}
        mapping = {
            "version": 5,
            "fields": {
                "diagnoses.value": "Diagnosis.value",
                "diagnoses.onset": "Diagnosis.low",
                "diagnoses.note": None,
            },
            "defaults": {"required_unmapped": {"nullFlavor": "NI"}},
            "target_defaults": {
                "Diagnosis.low": {
                    "nullFlavor": "UNK",
                    "reason": "No diagnosis-onset datapoint is available.",
                },
            },
        }
        record = {"key": "P1", "values": {}, "instances": {"diagnoses": [
            {"values": {
                "diagnoses.value": "A",
                "diagnoses.onset": "2026-01-01",
            }},
            {"values": {"diagnoses.value": "B"}},
        ]}}
        errors = validate.check_config(
            model, compiled,
            {"fields": {
                "diagnoses.value": None,
                "diagnoses.onset": None,
                "diagnoses.note": None,
            }},
            mapping,
        )
        self.assertEqual(errors, [])
        payload, problems = cda.emit(
            record, model, compiled, mapping,
            {"null_flavor": {"missing_required": "UNK"}},
        )
        self.assertEqual(problems, [])
        observations = list(ET.fromstring(payload))
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0][1].get("value"), "20260101")
        self.assertEqual(observations[1][1].get("nullFlavor"), "UNK")
        self.assertEqual(observations[0][2].get("nullFlavor"), "NI")
        self.assertEqual(observations[1][2].get("nullFlavor"), "NI")
        self.assertEqual(len(observations[0]), 3)
        self.assertEqual(len(observations[1]), 3)

        report = render_cda_mapping_markdown(
            model, compiled, mapping,
            {"summary": {"field_coverage": {"NO": 0}}},
        )
        self.assertIn("## Required CDA completion", report)
        self.assertIn('nullFlavor="NI"', report)
        self.assertIn('nullFlavor="UNK"', report)
        self.assertIn("No diagnosis-onset datapoint is available", report)
        self.assertIn("## Review required", report)
        self.assertIn("`diagnoses.note`", report)
        self.assertIn("explicitly `null` in `cda-mapping.json`", report)

    def test_target_default_validation_rejects_unsafe_nullification(self) -> None:
        def target(**changes: object) -> dict[str, object]:
            result: dict[str, object] = {
                "kind": "element", "datatype": "ST", "min": 1, "max": 1,
                "mandatory": False, "has_children": False, "conformance": "R",
                "renderable": True, "locations": ["0.0"], "fixed": {},
            }
            result.update(changes)
            return result

        compiled = {"targets": {
            "Optional.value": target(min=0),
            "Required.attribute": target(kind="attribute"),
            "Mandatory.value": target(mandatory=True),
            "Complex.value": target(has_children=True),
        }}
        mapping = {
            "fields": {},
            "defaults": {"required_unmapped": {"nullFlavor": "BAD"}},
            "target_defaults": {
                name: {"nullFlavor": "NI"} for name in compiled["targets"]
            },
        }
        errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, mapping
        )
        self.assertTrue(any("invalid nullFlavor 'BAD'" in error for error in errors))
        self.assertTrue(any("Optional.value" in error and "optional" in error for error in errors))
        self.assertTrue(any("Required.attribute" in error and "attribute" in error for error in errors))
        self.assertTrue(any("Mandatory.value" in error and "does not permit" in error for error in errors))
        self.assertTrue(any("Complex.value" in error and "complex" in error for error in errors))

    def test_mapping_default_does_not_nullify_mandatory_or_complex_elements(self) -> None:
        def document(child: dict[str, object]) -> dict[str, object]:
            return {
                "targets": {},
                "document": [{
                    "kind": "element", "name": "hl7:ClinicalDocument",
                    "min": 1, "max": 1, "mandatory": True,
                    "attributes": [], "fixed": {"classCode": "DOCCLIN"},
                    "children": [child],
                }],
            }

        mandatory = {
            "kind": "element", "name": "hl7:value", "datatype": "ST",
            "min": 1, "max": 1, "mandatory": True, "attributes": [],
            "codes": [], "fixed": {}, "children": [], "targets": [],
        }
        complex_required = {
            "kind": "element", "name": "hl7:component", "min": 1, "max": 1,
            "mandatory": False, "attributes": [], "codes": [], "fixed": {},
            "children": [{
                "kind": "element", "name": "hl7:text", "datatype": "ST",
                "min": 0, "max": 1, "mandatory": False, "attributes": [],
                "codes": [], "fixed": {}, "children": [], "targets": [],
            }], "targets": [],
        }
        mapping = {
            "fields": {},
            "defaults": {"required_unmapped": {"nullFlavor": "NI"}},
        }
        for compiled, message in (
            (document(mandatory), "mandatory CDA element"),
            (document(complex_required), "required complex CDA element"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                cda.emit(
                    {"key": "1", "values": {}}, {"fields": {}}, compiled,
                    mapping, {},
                )

    def test_config_validation_requires_all_fields(self) -> None:
        errors = validate.check_config({"fields": {"a": {}, "b": {}}}, {"targets": {"T.value": {}}},
                                       {"fields": {"a": "cases:a"}}, {"fields": {"a": "T.value", "b": None}})
        self.assertIn("csv-mapping: missing model field b", errors)

    def test_mapping_identity_cannot_silently_cross_transactions(self) -> None:
        model = {
            "meta": {
                "dataset_id": "1.2.3", "transaction_id": "1.2.3.4",
                "transaction_effective_date": "2026-01-01T00:00:00",
            },
            "fields": {},
        }
        errors = validate.check_config(
            model,
            {"targets": {}, "document_template": {"name": "ExpectedTemplate"}},
            {"model": {"transaction_id": "9.9.9"}, "fields": {}},
            {"model": {"transaction_id": "8.8.8"}, "target": {"template": "Other"}, "fields": {}},
        )
        self.assertTrue(any("csv-mapping: transaction_id" in error for error in errors))
        self.assertTrue(any("cda-mapping: transaction_id" in error for error in errors))
        self.assertTrue(any("target template" in error for error in errors))

    def test_repeating_instances_preserve_row_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("patient_id\nP1\n", encoding="utf-8")
            (raw / "medications.csv").write_text(
                "patient_id,drug,route\nP1,A,\nP1,B,oral\n", encoding="utf-8"
            )
            model = {
                "fields": {
                    "med.drug": {"type": "text", "repeat": "med", "required": True},
                    "med.route": {"type": "text", "repeat": "med", "required": False},
                }
            }
            csv_mapping = {
                "join": {"column": "patient_id"},
                "fields": {
                    "med.drug": "medications:drug",
                    "med.route": "medications:route",
                },
            }
            site = {
                "input": {
                    "case_source": "cases",
                    "sources": {
                        "cases": {"file": "cases.csv", "cardinality": "1:1"},
                        "medications": {"file": "medications.csv", "cardinality": "1:n"},
                    },
                    "empty_is_null": True,
                },
                "null_flavor": {"missing_required": "NI"},
            }
            records = data.ingest(raw, model, csv_mapping, {"fields": {}}, site)
            rows = records[0]["instances"]["med"]
            self.assertEqual(rows[0]["values"]["med.drug"], "A")
            self.assertIsNone(rows[0]["values"]["med.route"])
            self.assertEqual(rows[1]["values"]["med.drug"], "B")
            self.assertEqual(rows[1]["values"]["med.route"], "oral")
            self.assertNotIn("med.drug", records[0]["values"])

    def test_renderer_keeps_optional_repeat_value_with_its_occurrence(self) -> None:
        compiled = {
            "targets": {
                "Drug.value": {"renderable": True, "locations": ["0.0.0"]},
                "Route.value": {"renderable": True, "locations": ["0.0.1"]},
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1,
                "mandatory": True, "attributes": [], "codes": [], "fixed": {}, "targets": [],
                "children": [{
                    "kind": "element", "name": "hl7:entry", "min": 0, "max": None,
                    "mandatory": False, "attributes": [], "codes": [], "fixed": {}, "targets": [],
                    "children": [
                        {"kind": "element", "name": "hl7:value", "datatype": "ST", "min": 0, "max": 1,
                         "mandatory": False, "attributes": [], "codes": [], "fixed": {}, "children": [],
                         "targets": ["Drug.value"], "target": "Drug.value"},
                        {"kind": "element", "name": "hl7:text", "datatype": "ST", "min": 0, "max": 1,
                         "mandatory": False, "attributes": [], "codes": [], "fixed": {}, "children": [],
                         "targets": ["Route.value"], "target": "Route.value"},
                    ],
                }],
            }],
        }
        model = {"fields": {
            "med.drug": {"repeat": "med"}, "med.route": {"repeat": "med"},
        }}
        record = {
            "key": "P1", "values": {},
            "instances": {"med": [
                {"values": {"med.drug": "A", "med.route": None}},
                {"values": {"med.drug": "B", "med.route": "oral"}},
            ]},
        }
        payload, problems = cda.emit(
            record, model, compiled,
            {"fields": {"med.drug": "Drug.value", "med.route": "Route.value"}},
            {"null_flavor": {"missing_required": "NI"}},
        )
        root = ET.fromstring(payload)
        entries = list(root)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0].text, "A")
        self.assertEqual(len(entries[0]), 1)
        self.assertEqual(entries[1][0].text, "B")
        self.assertEqual(entries[1][1].text, "oral")
        self.assertEqual(problems, [])

    def test_fixed_text_and_np_constraints_are_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''<project>
              <template id="doc" effectiveDate="2026-01-01" name="Doc">
                <element name="hl7:ClinicalDocument" id="root" minimumMultiplicity="1" maximumMultiplicity="1">
                  <element name="hl7:title" id="title" datatype="ST" minimumMultiplicity="1" maximumMultiplicity="1" isMandatory="true"><text>Fixed title</text></element>
                  <element name="hl7:value" id="forbidden" datatype="ST" conformance="NP"/>
                </element>
              </template>
            </project>''', encoding="utf-8")
            compiled = compile_cda([project], {"meta": {"template_id": "doc", "template_effective_date": "2026-01-01"}, "groups": {}, "fields": {}})
            self.assertEqual(validate.verify_compiled_cda(compiled), [])
            forbidden = [t for t in compiled["targets"].values() if t.get("element_id") == "forbidden"][0]
            self.assertTrue(forbidden["prohibited"])
            self.assertFalse(forbidden["renderable"])
            payload, problems = cda.emit({"key": "1", "values": {}}, {"fields": {}}, compiled, {"fields": {}}, {"null_flavor": {"missing_required": "NI"}})
            root = ET.fromstring(payload)
            self.assertEqual(root[0].text, "Fixed title")
            self.assertEqual(len(root), 1)
            self.assertEqual(problems, [])

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

    def test_standalone_value_set_populates_model_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "transaction.xml"
            valueset = Path(tmp) / "valueset.xml"
            transaction.write_text('''<dataset id="d"><concept type="item" shortName="status" id="c"><name>Status</name><valueDomain type="code"/><valueSet id="1.2.3"/></concept></dataset>''', encoding="utf-8")
            valueset.write_text('''<valueSet id="1.2.3"><concept code="A" codeSystem="9.9"><name>aktiv</name></concept></valueSet>''', encoding="utf-8")
            model = compile_model(transaction, [valueset])
            self.assertEqual(accepted_values(model["fields"]["status"])["aktiv"]["code"], "A")

    def test_live_evidence_does_not_seed_unrelated_external_crawl(self) -> None:
        root = ET.fromstring('''<project>
          <concept id="relevant"><name>Relevant</name><inherit ref="old" datasetId="9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept>
          <concept id="unrelated"><name>Unrelated</name><inherit ref="other" datasetId="9.2" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept>
        </project>''')
        refs = _evidence_references(root, {"relevant"})
        self.assertEqual({item["id"] for item in refs if item["kind"] == "concept"}, {"old"})
        self.assertFalse(any(item["kind"] == "dataset" for item in refs))

    def test_fetch_want_adopts_cached_analysis_without_backfilling_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "1.2.3_2025-05-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="1.2.3" effectiveDate="2025-05-01" name="T"><element name="hl7:observation"/></template></return>',
                encoding="utf-8",
            )
            manifest = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "2025-05-01", "project": "aktin-"}
            progress: list[str] = []
            with patch(
                "decor2hl7.retrieval.fetch.get",
                return_value=target.read_bytes(),
            ) as mocked:
                path = _fetch_want(
                    release_dir, manifest, want, owners={}, repositories=["aktin-"],
                    language="de-DE", ipv4=True, retry_missing=False, progress=progress.append,
                )
            self.assertEqual(path, target)
            entry = manifest["resources"]["template:1.2.3@2025-05-01"]
            self.assertEqual(entry["status"], "ok")
            self.assertEqual(entry["file"], "templates/1.2.3_2025-05-01.xml")
            self.assertTrue(entry["sha256"])
            self.assertNotIn("source", entry["representations"])
            self.assertEqual(
                entry["source_warning"], "source representation unavailable"
            )
            self.assertEqual(mocked.call_count, 0)

    def test_fetch_want_redownloads_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "1.2.3_2025-05-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="1.2.3" effectiveDate="2025-05-01" name="Changed"/></return>',
                encoding="utf-8",
            )
            manifest = {"resources": {
                "template:1.2.3@2025-05-01": {
                    "status": "ok",
                    "file": "templates/1.2.3_2025-05-01.xml",
                    "sha256": "not-the-current-digest",
                }
            }}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "2025-05-01", "project": "aktin-"}
            downloaded = b'<return><template id="1.2.3" effectiveDate="2025-05-01" name="Fresh"/></return>'
            with patch("decor2hl7.retrieval.fetch.get", return_value=downloaded) as mocked:
                path = _fetch_want(
                    release_dir, manifest, want, owners={}, repositories=["aktin-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                )
            self.assertEqual(path, target)
            self.assertEqual(target.read_bytes(), downloaded)
            self.assertGreaterEqual(mocked.call_count, 1)

    def test_dynamic_fetch_records_and_reuses_resolved_effective_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "project": "aktin-"}
            calls: list[str] = []
            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                return b'<return><template id="1.2.3" effectiveDate="2025-05-01T00:00:00" name="T"><element name="hl7:observation"/></template></return>'
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(release_dir, manifest, want, owners={}, repositories=["aktin-"], language="de-DE", ipv4=True, retry_missing=False)
            entry = manifest["resources"]["template:1.2.3"]
            self.assertEqual(entry["requested_effective_date"], "dynamic")
            self.assertEqual(entry["resolved_effective_date"], "2025-05-01T00:00:00")
            assert path is not None
            path.unlink()
            calls.clear()
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                _fetch_want(release_dir, manifest, want, owners={}, repositories=["aktin-"], language="de-DE", ipv4=True, retry_missing=False)
            self.assertTrue(any("/2025-05-01T00%3A00%3A00/" in url for url in calls))

    def test_hard_and_soft_reference_scopes_are_distinct(self) -> None:
        root = ET.fromstring('''<dataset id="current" templateId="doc">
          <relationship type="VERSION" ref="old-dataset" flexibility="2020-01-01" prefix="aktin-"/>
          <concept id="current-concept">
            <relationship type="SPEC" ref="old-concept" flexibility="2020-01-01" prefix="aktin-" datasetId="old-dataset" datasetEffectiveDate="2020-01-01"/>
            <contains ref="external-root" datasetId="external-dataset" datasetEffectiveDate="2023-01-01" prefix="ext-"/>
          </concept>
        </dataset>''')
        hard = hard_references(root)
        soft = soft_references(root)
        self.assertEqual({row["id"] for row in hard if row["kind"] == "dataset"}, {"external-dataset"})
        self.assertNotIn("old-dataset", {row["id"] for row in hard})
        self.assertEqual({row["id"] for row in soft if row["kind"] == "concept"}, {"old-concept"})

    def test_known_owner_stops_broad_repository_probe(self) -> None:
        want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "aktin-"}
        self.assertEqual(
            _candidate_projects(want, {"1.2.3": "aktin-"}, ["aktin-", "pmp-", "hl7de-"]),
            ["aktin-"],
        )
        stale = {**want, "project": "old-"}
        self.assertEqual(
            _candidate_projects(stale, {"1.2.3": "aktin-"}, ["aktin-", "pmp-"]),
            ["aktin-", "old-"],
        )

    def test_static_template_selection_never_substitutes_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "templates.xml"
            source.write_text('''<project>
              <template id="t" effectiveDate="2007-01-01" name="Newer"/>
            </project>''', encoding="utf-8")
            templates = collect_templates([source])
            self.assertIsNone(select_template(templates, "t", "2005-01-01"))
            selected = select_template(templates, "t", "dynamic")
            self.assertIsNotNone(selected)
            assert selected is not None
            self.assertEqual(selected.get("effectiveDate"), "2007-01-01")
            with self.assertRaisesRegex(ValueError, "fallback template inputs"):
                collect_templates([], [source])

    def test_artifact_identity_mismatch_is_fatal_but_missing_dependency_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            analysis = release / "templates" / "t.xml"
            analysis.parent.mkdir()
            analysis.write_text('<template id="t" effectiveDate="2007"/>', encoding="utf-8")
            entry = {
                "status": "ok", "file": "templates/t.xml",
                "requested_effective_date": "2005",
                "resolved_effective_date": "2007",
                "identity": {"type": "template", "id": "t", "effective_date": "2007"},
            }
            record = artifact_record(release, "template:t@2005", entry, ["structure"])
            self.assertTrue(any(
                "requested static revision" in item
                for item in artifact_problems(record)
            ))

            transaction = release / "transactions" / "tx"
            transaction.mkdir(parents=True)
            (release / "manifest.json").write_text(
                json.dumps({"resources": {"template:t@2005": entry}}),
                encoding="utf-8",
            )
            (transaction / "closure.json").write_text(json.dumps({
                "complete": True,
                "crawl_complete": True,
                "build_ready": False,
                "readiness_errors": [
                    "required artifact unavailable: template:t@2005"
                ],
                "build_resources": ["template:t@2005"],
                "resource_roles": {"template:t@2005": ["structure"]},
            }), encoding="utf-8")
            records = closure_records(release, transaction)
            self.assertEqual(len(records), 1)
            self.assertTrue(any(
                "requested static revision" in item
                for item in artifact_problems(records[0])
            ))

            (transaction / "closure.json").write_text(json.dumps({
                "complete": True,
                "build_resources": [],
            }), encoding="utf-8")
            self.assertEqual(closure_records(release, transaction), [])

    def test_compiler_inputs_omit_and_report_missing_auxiliary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            transaction = release / "transactions" / "tx"
            transaction.mkdir(parents=True)
            source = transaction / "transaction.source.xml"
            analysis = transaction / "transaction.xml"
            template = release / "templates" / "doc.xml"
            template.parent.mkdir()
            source.write_text(
                '<transaction id="tx" effectiveDate="2026"><representingTemplate ref="doc"/></transaction>',
                encoding="utf-8",
            )
            analysis.write_text(
                '<dataset transactionId="tx" transactionEffectiveDate="2026" templateId="doc"/>',
                encoding="utf-8",
            )
            template.write_text(
                '<template id="doc" effectiveDate="2026"><element name="hl7:ClinicalDocument"/></template>',
                encoding="utf-8",
            )
            resources = {
                "transaction-source:tx@2026": {
                    "status": "ok",
                    "file": str(source.relative_to(release)),
                    "identity": {"type": "transaction", "id": "tx", "effective_date": "2026"},
                    "requested_effective_date": "2026",
                    "resolved_effective_date": "2026",
                },
                "transaction:tx@2026": {
                    "status": "ok",
                    "file": str(analysis.relative_to(release)),
                    "identity": {"type": "transaction", "id": "tx", "effective_date": "2026"},
                    "requested_effective_date": "2026",
                    "resolved_effective_date": "2026",
                },
                "template:doc@2026": {
                    "status": "ok",
                    "file": str(template.relative_to(release)),
                    "identity": {"type": "template", "id": "doc", "effective_date": "2026"},
                    "requested_effective_date": "2026",
                    "resolved_effective_date": "2026",
                },
                "dataset:missing@2020": {
                    "status": "missing",
                    "identity": {"type": "dataset", "id": "missing", "effective_date": "2020"},
                    "requested_effective_date": "2020",
                },
            }
            (release / "manifest.json").write_text(
                json.dumps({"resources": resources}), encoding="utf-8"
            )
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True,
                "build_ready": False,
                "build_resources": ["template:doc@2026", "dataset:missing@2020"],
                "evidence_resources": ["template:doc@2026", "dataset:missing@2020"],
                "resource_roles": {
                    "template:doc@2026": ["structure"],
                    "dataset:missing@2020": ["structure"],
                },
            }), encoding="utf-8")

            inputs = compiler_inputs(release, transaction)
            self.assertEqual(inputs["templates"], [template])
            self.assertEqual(
                [item["request_key"] for item in inputs["unavailable_artifacts"]],
                ["dataset:missing@2020"],
            )
            self.assertNotIn(release / "datasets" / "missing.xml", inputs["model_resources"])

    def test_tolerant_cda_compile_reports_nested_gap_but_requires_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            document = directory / "doc.xml"
            document.write_text('''<template id="doc" effectiveDate="2026" name="Doc">
              <element name="hl7:ClinicalDocument"><include ref="missing" flexibility="2020"/></element>
            </template>''', encoding="utf-8")
            model = {"meta": {"template_id": "doc", "template_effective_date": "2026"}, "fields": {}, "groups": {}}
            compiled = compile_cda_model([document], model)
            self.assertEqual(len(compiled["unresolved_templates"]), 1)
            self.assertEqual(compiled["unresolved_templates"][0]["template"], "missing")
            with self.assertRaisesRegex(ValueError, "document template absent .*not fetched"):
                compile_cda_model([], {"meta": {"template_id": "absent"}, "fields": {}, "groups": {}})

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
                field["formal_terminology"]["missing_value_sets"][0]["id"],
                "missing-vs",
            )

    def test_dynamic_and_exact_requests_share_one_canonical_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            transaction = release / "transactions" / "tx"
            transaction.mkdir(parents=True)
            artifact = release / "valuesets" / "vs.xml"
            artifact.parent.mkdir()
            artifact.write_text(
                '<valueSet id="vs" effectiveDate="2025"/>', encoding="utf-8"
            )
            base = {
                "status": "ok", "file": "valuesets/vs.xml",
                "resolved_effective_date": "2025",
                "identity": {
                    "type": "valueset", "id": "vs",
                    "effective_date": "2025", "project": "term-",
                },
            }
            dynamic = {**base, "requested_effective_date": "dynamic"}
            exact = {**base, "requested_effective_date": "2025"}
            (release / "manifest.json").write_text(json.dumps({
                "resources": {"valueset:vs": dynamic, "valueset:vs@2025": exact}
            }), encoding="utf-8")
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True, "build_ready": True,
                "build_resources": ["valueset:vs", "valueset:vs@2025"],
                "resource_roles": {
                    "valueset:vs": ["formal-terminology"],
                    "valueset:vs@2025": ["formal-terminology"],
                },
            }), encoding="utf-8")
            records = closure_records(release, transaction)
            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0]["aliases"], ["valueset:vs", "valueset:vs@2025"]
            )

    def test_cached_artifact_owner_precedes_repository_probe(self) -> None:
        want = {
            "kind": "codesystem",
            "id": "2.16.840.1.113883.5.25",
            "effective_date": "",
            "project": "",
        }
        self.assertEqual(
            _candidate_projects(
                want, {}, ["aktin-", "pmp-", "ad1bbr-"],
                {"codesystem:2.16.840.1.113883.5.25@dynamic": "ad1bbr-"},
            ),
            ["ad1bbr-", "aktin-", "pmp-"],
        )

    def test_cached_owner_never_overrides_oid_owner(self) -> None:
        want = {
            "kind": "codesystem",
            "id": "1.2.3.4",
            "effective_date": "2020-01-01",
            "project": "",
        }
        self.assertEqual(
            _candidate_projects(
                want, {"1.2.3": "aktin-"}, ["aktin-", "ad1bbr-"],
                {"codesystem:1.2.3.4@2020-01-01": "ad1bbr-"},
            ),
            ["aktin-"],
        )

    def test_cached_owner_is_effective_date_specific(self) -> None:
        owners = {
            "codesystem:2.16.840.1.113883.5.25@2019-12-30": "ad1bbr-",
        }
        historical = {
            "kind": "codesystem",
            "id": "2.16.840.1.113883.5.25",
            "effective_date": "2019-12-30",
            "project": "",
        }
        current = {**historical, "effective_date": "2024-01-01"}
        repositories = ["aktin-", "pmp-", "ad1bbr-"]
        self.assertEqual(
            _candidate_projects(historical, {}, repositories, owners),
            ["ad1bbr-", "aktin-", "pmp-"],
        )
        self.assertEqual(
            _candidate_projects(current, {}, repositories, owners),
            repositories,
        )

    def test_format_one_owner_cache_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact-owners.json"
            path.write_text(
                '{"format":1,"owners":{"codesystem:1.2.3":"wrong-"}}',
                encoding="utf-8",
            )
            from decor2hl7.retrieval.fetch import _load_artifact_owners
            self.assertEqual(_load_artifact_owners(path), {})

    def test_source_reference_redirects_before_wrong_project_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = {"resources": {}}
            owners: dict[str, str] = {}
            calls: list[str] = []
            want = {
                "kind": "codesystem",
                "id": "2.16.840.1.113883.5.25",
                "effective_date": "",
                "project": "aktin-",
            }

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if "$extract" not in path and "prefix=aktin-" in url:
                    return (
                        b'<return><codeSystem id="2.16.840.1.113883.5.25" '
                        b'href="https://art-decor.org/exist/apps/api/project/ad1bbr-/codesystem/'
                        b'2.16.840.1.113883.5.25"/></return>'
                    )
                if "$extract" in path and "project=aktin-" in url:
                    raise AssertionError("wrong-project analysis must be skipped")
                return (
                    b'<return><codeSystem id="2.16.840.1.113883.5.25" '
                    b'effectiveDate="2020-01-01T00:00:00"><concept code="N"/></codeSystem></return>'
                )

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(
                    release_dir, manifest, want,
                    owners={}, repositories=["aktin-", "pmp-", "ad1bbr-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                    artifact_owners=owners,
                )

            self.assertIsNotNone(path)
            self.assertEqual(
                owners["codesystem:2.16.840.1.113883.5.25@dynamic"], "ad1bbr-"
            )
            self.assertFalse(any(
                "$extract" in api_path(url) and "project=aktin-" in url
                for url in calls
            ))

    def test_source_link_does_not_redirect_known_oid_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = {"resources": {}}
            owner_index: dict[str, str] = {}
            calls: list[str] = []
            want = {
                "kind": "codesystem",
                "id": "1.2.3.4",
                "effective_date": "",
                "project": "",
            }

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if "$extract" not in path:
                    return (
                        b'<return><codeSystem id="1.2.3.4" '
                        b'href="https://art-decor.org/exist/apps/api/project/ad1bbr-/codesystem/1.2.3.4" '
                        b'effectiveDate="2020-01-01T00:00:00"/></return>'
                    )
                if "project=aktin-" in url:
                    return (
                        b'<return><codeSystem id="1.2.3.4" '
                        b'effectiveDate="2020-01-01T00:00:00"><concept code="A"/></codeSystem></return>'
                    )
                raise AssertionError("known OID owner must not redirect to BBR")

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(
                    release_dir, manifest, want,
                    owners={"1.2.3": "aktin-"},
                    repositories=["aktin-", "ad1bbr-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                    artifact_owners=owner_index,
                )

            self.assertIsNotNone(path)
            self.assertTrue(any(
                "$extract" in api_path(url) and "project=aktin-" in url
                for url in calls
            ))
            self.assertFalse(any(
                "$extract" in api_path(url) and "project=ad1bbr-" in url
                for url in calls
            ))

    def test_soft_evidence_resolution_is_non_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b'<return><project id="9" prefix="ext-"/></return>'
                if "/transaction/t/" in path:
                    return b'<dataset id="d" transactionId="t"><concept id="current"><inherit ref="9.1" effectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if path.endswith("/project/aktin-/$extract") or path.endswith("/project/aktin-"):
                    return b'<project><transaction id="t"/></project>'
                if "/concept/9.1/" in path:
                    return b'<return><concept id="9.1" effectiveDate="2020-01-01"><inherit ref="9.2" effectiveDate="2019-01-01" prefix="ext-"/></concept></return>'
                if "/concept/9.2/" in path:
                    raise AssertionError("soft evidence must not recurse")
                raise AssertionError(url)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20,
                )
            self.assertTrue(any("/concept/9.1/" in api_path(url) for url in calls))
            self.assertFalse(any("/concept/9.2/" in api_path(url) for url in calls))
            self.assertIn("concept:9.1@2020-01-01", result["closure"]["evidence_resources"])


    def test_fetch_progress_does_not_claim_nonexistent_next_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = {"resources": {}}
            want = {"kind": "concept", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "pmp-"}
            progress: list[str] = []

            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", None, None)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=missing):
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "pmp-"}, repositories=["pmp-", "hl7de-"],
                    language="de-DE", ipv4=True, retry_missing=False, progress=progress.append,
                ))
            failure = next(line for line in progress if "HTTP 404" in line)
            self.assertEqual(failure, "fetch: concept 1.2.3.4 @ 2020-01-01: source HTTP 404 via pmp-")
            self.assertFalse(any("trying next source" in line for line in progress))

    def test_settled_missing_is_persisted_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = {"resources": {}}
            want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "aktin-"}
            persisted: list[dict[str, object]] = []
            def save() -> None:
                persisted.append(dict(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]))
            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", None, None)
            with patch("decor2hl7.retrieval.fetch.get", side_effect=missing) as mocked:
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "aktin-"}, repositories=["aktin-", "pmp-"],
                    language="de-DE", ipv4=True, retry_missing=False, save_manifest=save,
                ))
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue(persisted)
            self.assertTrue(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]["settled"])
            with patch("decor2hl7.retrieval.fetch.get", side_effect=AssertionError("known missing must not retry")):
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "aktin-"}, repositories=["aktin-", "pmp-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                ))

    def test_state_fingerprint_includes_repeating_instances(self) -> None:
        a = {"values": {}, "instances": {"med": [{"values": {"drug": "A", "route": None}}, {"values": {"drug": "B", "route": "oral"}}]}}
        b = {"values": {}, "instances": {"med": [{"values": {"drug": "A", "route": "oral"}}, {"values": {"drug": "B", "route": None}}]}}
        self.assertNotEqual(state.fingerprint(a), state.fingerprint(b))

    def test_state_fingerprint_ignores_csv_row_provenance(self) -> None:
        a = {"values": {}, "instances": {"med": [{"source": "medications", "row": 2, "values": {"drug": "A"}}]}}
        b = {"values": {}, "instances": {"med": [{"source": "medications", "row": 99, "values": {"drug": "A"}}]}}
        self.assertEqual(state.fingerprint(a), state.fingerprint(b))

    def test_spec_refinement_drops_parent_only_nested_choices_and_replaces_contains(self) -> None:
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
                  <element name="hl7:component" id="component" contains="old" flexibility="2020-01-01" minimumMultiplicity="1" maximumMultiplicity="1">
                    <element name="hl7:oldChoice" id="old-choice" datatype="ST"/>
                  </element>
                </element>
              </template>
              <template id="doc" effectiveDate="2026-01-01" name="Doc">
                <relationship type="SPEC" template="base" flexibility="2020-01-01"/>
                <element name="hl7:ClinicalDocument" id="root">
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
            old_choice = [t for t in compiled["targets"].values() if t.get("element_id") == "old-choice"][0]
            new_choice = [t for t in compiled["targets"].values() if t.get("element_id") == "new-choice"][0]
            old_value = [t for t in compiled["targets"].values() if t.get("element_id") == "old-value"][0]
            new_value = [t for t in compiled["targets"].values() if t.get("element_id") == "new-value"][0]
            self.assertEqual(old_choice.get("locations"), [])
            self.assertEqual(old_value.get("locations"), [])
            self.assertEqual(len(new_choice.get("locations", [])), 1)
            self.assertEqual(len(new_value.get("locations", [])), 1)
            component = compiled["document"][0]["children"][0]
            self.assertEqual(component["contains"], "new")
            self.assertEqual(component["contains_flexibility"], "2026-01-01")
            self.assertEqual(component["min"], 1)  # inherited from the matched SPEC wrapper

    def test_codes_mapping_must_resolve_to_canonical_value(self) -> None:
        errors = validate.check_config(
            {"fields": {"status": {"values": {"active": {"code": "A"}}}}},
            {"targets": {}},
            {"fields": {"status": None}},
            {"fields": {"status": None}},
            {"fields": {"status": {"1": "typo"}}},
        )
        self.assertTrue(any("unknown canonical value" in error for error in errors))

    def test_history_rotation_uses_first_entry_timestamp_not_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            history = directory / "history.jsonl"
            history.write_text(
                '{"key":"x","sent_at":"2000-01-01T00:00:00+00:00"}\n',
                encoding="utf-8",
            )
            rotated = state.rotate(directory, 1)
            self.assertIsNotNone(rotated)
            self.assertFalse(history.exists())
            assert rotated is not None
            self.assertTrue(rotated.exists())


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

    def test_identifier_root_is_required_and_rendered(self) -> None:
        compiled = {
            "targets": {"PatientIdentifier.id": {
                "datatype": "II", "path": "hl7:recordTarget/hl7:id", "renderable": True,
                "locations": ["0.0"], "fixed": {},
            }},
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1,
                "mandatory": True, "attributes": [], "codes": [], "fixed": {}, "targets": [],
                "children": [{
                    "kind": "element", "name": "hl7:id", "datatype": "II", "min": 0, "max": 1,
                    "mandatory": False, "attributes": [], "codes": [], "fixed": {}, "children": [],
                    "targets": ["PatientIdentifier.id"], "target": "PatientIdentifier.id",
                }],
            }],
        }
        model = {"fields": {"patient": {"type": "identifier"}}}
        mapping = {"fields": {"patient": "PatientIdentifier.id"}}
        record = {"key": "P1", "values": {"patient": "123"}, "instances": {}}
        with self.assertRaisesRegex(ValueError, "no fixed/configured root"):
            cda.emit(record, model, compiled, mapping, {"identifiers": {}, "null_flavor": {}})
        payload, _ = cda.emit(
            record, model, compiled, mapping,
            {"identifiers": {"patient_root": "1.2.3"}, "null_flavor": {}},
        )
        identifier = list(ET.fromstring(payload))[0]
        self.assertEqual(identifier.get("root"), "1.2.3")
        self.assertEqual(identifier.get("extension"), "123")

    def test_required_cda_attribute_without_value_is_fatal(self) -> None:
        compiled = {"targets": {}, "document": [{
            "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1, "mandatory": True,
            "attributes": [{"kind": "attribute", "name": "classCode", "optional": False, "value": None, "targets": []}],
            "codes": [], "fixed": {}, "targets": [], "children": [],
        }]}
        with self.assertRaisesRegex(ValueError, "required CDA attribute"):
            cda.emit(
                {"key": "x", "values": {}, "instances": {}}, {"fields": {}}, compiled,
                {"fields": {}}, {"null_flavor": {}},
            )

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
            proposal, report = mapping.cda_mapping_proposal(model, compiled, [tx, project])
            self.assertIsNotNone(proposal["fields"]["rank"])
            self.assertIn("XPATH(entry)", report)

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

    def test_incomplete_embedded_valueset_does_not_satisfy_fetch_inventory(self) -> None:
        root = ET.fromstring(
            '<dataset><valueSet id="1.2.3" effectiveDate="2020"><conceptList><include ref="4.5.6"/></conceptList></valueSet></dataset>'
        )
        self.assertNotIn(("valueset", "1.2.3", "2020"), _inventory(root))
        root = ET.fromstring(
            '<dataset><valueSet id="1.2.3" effectiveDate="2020"><concept code="A" codeSystem="9"/></valueSet></dataset>'
        )
        self.assertIn(("valueset", "1.2.3", "2020"), _inventory(root))

    def test_uncoded_code_option_becomes_oth_until_mapped_to_real_code(self) -> None:
        field = {"type": "code", "values": {"Label": {"display_name": "Label"}, "Coded": {"code": "A", "code_system": "9", "display_name": "Coded"}}}
        site = {"null_flavor": {"unmapped_code": "OTH"}}
        self.assertEqual(data.normalize_value("Label", field, {}, site)["nullFlavor"], "OTH")
        coded = data.normalize_value("Label", field, {"Label": "Coded"}, site)
        self.assertEqual(coded["code"], "A")
        self.assertEqual(coded["codeSystem"], "9")

    def test_textual_ordinal_uses_leading_numeric_rank(self) -> None:
        field = {"type": "ordinal", "values": {"1 keine": {"display_name": "1 keine"}, "2 Schmerzreiz": {"display_name": "2 Schmerzreiz"}}}
        self.assertEqual(data.normalize_value("1 keine", field, {}, {}), 1)
        self.assertEqual(data.normalize_value("raw-two", field, {"raw-two": "2 Schmerzreiz"}, {}), 2)

    def test_state_fingerprint_changes_with_transformation_context(self) -> None:
        record = {"values": {"a": 1}, "instances": {}}
        self.assertNotEqual(
            state.fingerprint(record, {"mapping": "A"}),
            state.fingerprint(record, {"mapping": "B"}),
        )


    def test_art_decor_assertion_failure_blocks_rendering(self) -> None:
        compiled = {"targets": {}, "document": [{
            "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1, "mandatory": True,
            "attributes": [], "codes": [], "fixed": {}, "targets": [], "asserts": [], "lets": {},
            "children": [{
                "kind": "element", "name": "hl7:procedure", "min": 1, "max": 1, "mandatory": True,
                "attributes": [{"kind": "attribute", "name": "negationInd", "optional": True, "value": "true", "targets": []}],
                "codes": [], "fixed": {}, "targets": [], "lets": {},
                "asserts": [{"test": "not(@negationInd='true' and hl7:entryRelationship)", "role": "error", "message": "no reason when negated", "template_id": "iso"}],
                "children": [{
                    "kind": "element", "name": "hl7:entryRelationship", "min": 1, "max": 1, "mandatory": True,
                    "attributes": [], "codes": [], "fixed": {"typeCode": "RSON"}, "targets": [], "children": [],
                    "asserts": [], "lets": {},
                }],
            }],
        }]}
        with self.assertRaisesRegex(ValueError, "ART-DECOR assertions"):
            cda.emit(
                {"key": "x", "values": {}, "instances": {}}, {"fields": {}}, compiled,
                {"fields": {}}, {"null_flavor": {}},
            )

    def test_assertion_evaluator_supports_aktin_expression_shapes(self) -> None:
        root = ET.fromstring('''<ClinicalDocument xmlns="urn:hl7-org:v3"><act><code code="FAMDEP"/><associatedPerson/></act><observation negationInd="false"><value><qualifier><name code="FSTAT"/></qualifier></value></observation><component><observation><templateId root="1.2.276.0.76.10.4046"/><targetSiteCode code="L"/></observation></component></ClinicalDocument>''')
        act = root.find('{urn:hl7-org:v3}act')
        observation = root.find('{urn:hl7-org:v3}observation')
        self.assertIs(assertions.evaluate("not(hl7:code[@code='FAMDEP']) or hl7:associatedPerson", act, root), True)
        self.assertIs(assertions.evaluate("not(@negationInd='true' and hl7:value/hl7:qualifier/hl7:name/@code='FSTAT')", observation, root), True)
        self.assertIs(assertions.evaluate("count(hl7:component/hl7:observation[hl7:targetSiteCode/@code='L'])<=1", root, root), True)

    def test_schematron_preserves_assert_and_let(self) -> None:
        text = assertions.schematron({"assertions": [{
            "path": "hl7:observation", "template_id": "1.2.3", "role": "error",
            "test": "empty($seq)", "message": "unique", "lets": {"seq": "//hl7:value"},
        }]})
        self.assertIn('<sch:let name="seq" value="//hl7:value"/>', text)
        self.assertIn('test="empty($seq)"', text)

    def test_transform_rules_render_negation_nullflavor_and_ordinal(self) -> None:
        compiled = {
            "targets": {
                "Iso.negationInd": {"datatype": "BL", "path": "hl7:procedure/@negationInd", "renderable": True, "locations": ["0.0.100000"], "fixed": {}, "repeat_ancestors": []},
                "Iso.nullFlavor": {"datatype": "cs", "path": "hl7:procedure/@nullFlavor", "renderable": True, "locations": ["0.0.100001"], "fixed": {}, "repeat_ancestors": []},
                "Rank.value": {"datatype": "PQ", "path": "hl7:observation/hl7:value", "renderable": True, "locations": ["0.1.0"], "fixed": {}, "unit": "{score}", "repeat_ancestors": []},
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1, "mandatory": True,
                "attributes": [], "codes": [], "fixed": {}, "targets": [], "asserts": [], "lets": {},
                "children": [
                    {"kind": "element", "name": "hl7:procedure", "min": 0, "max": 1, "mandatory": False,
                     "attributes": [
                         {"kind": "attribute", "name": "negationInd", "optional": True, "value": None, "targets": ["Iso.negationInd"]},
                         {"kind": "attribute", "name": "nullFlavor", "optional": True, "value": None, "targets": ["Iso.nullFlavor"]},
                     ], "codes": [], "fixed": {}, "targets": [], "children": [], "asserts": [], "lets": {}},
                    {"kind": "element", "name": "hl7:observation", "min": 0, "max": 1, "mandatory": False,
                     "attributes": [], "codes": [], "fixed": {}, "targets": [], "asserts": [], "lets": {},
                     "children": [{"kind": "element", "name": "hl7:value", "datatype": "PQ", "unit": "{score}", "min": 0, "max": 1, "mandatory": False,
                                  "attributes": [], "codes": [], "fixed": {}, "targets": ["Rank.value"], "children": [], "asserts": [], "lets": {}}]},
                ],
            }],
        }
        model = {"fields": {"iso": {"type": "code"}, "rank": {"type": "code"}}}
        mapping_cfg = {"fields": {
            "iso": [
                {"target": "Iso.negationInd", "transform": {"type": "enum", "map": {"unknown": False}}},
                {"target": "Iso.nullFlavor", "transform": {"type": "enum", "map": {"unknown": "NI"}}},
            ],
            "rank": {"target": "Rank.value", "transform": {"type": "ordinal", "map": {"Rankin 2": 2}}},
        }}
        record = {"key": "P1", "values": {"iso": {"canonical": "unknown"}, "rank": {"canonical": "Rankin 2"}}, "instances": {}}
        payload, _ = cda.emit(record, model, compiled, mapping_cfg, {"null_flavor": {}})
        xml = ET.fromstring(payload)
        procedure = list(xml)[0]
        self.assertEqual(procedure.get("negationInd"), "false")
        self.assertEqual(procedure.get("nullFlavor"), "NI")
        value = list(list(xml)[1])[0]
        self.assertEqual(value.get("value"), "2")
        self.assertEqual(value.get("unit"), "{score}")

    def test_nested_occurrence_keys_preserve_independent_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("patient_id\nP1\n", encoding="utf-8")
            (raw / "details.csv").write_text(
                "patient_id,med_id,dose_id,drug,dose\n"
                "P1,m1,d1,A,1\nP1,m1,d2,A,2\nP1,m2,d3,B,3\n",
                encoding="utf-8",
            )
            model = {"fields": {
                "med.drug": {"type": "text", "repeat": "med", "repeat_chain": ["med"]},
                "med.dose.amount": {"type": "integer", "repeat": "med.dose", "repeat_chain": ["med", "med.dose"]},
            }}
            csv_map = {"join": {"column": "patient_id"}, "fields": {
                "med.drug": "details:drug", "med.dose.amount": "details:dose",
            }}
            site = {"input": {"case_source": "cases", "sources": {
                "cases": {"file": "cases.csv", "cardinality": "1:1"},
                "details": {"file": "details.csv", "cardinality": "1:n", "occurrence_keys": {"med": "med_id", "med.dose": "dose_id"}},
            }}}
            records = data.ingest(raw, model, csv_map, {"fields": {}}, site)
            self.assertEqual(data.field_value(records[0], "med.drug", model["fields"]["med.drug"]), ["A", "B"])
            self.assertEqual(data.field_value(records[0], "med.dose.amount", model["fields"]["med.dose.amount"]), [[1, 2], [3]])



    def test_nested_repetition_renders_matching_cda_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            project = d / "project.xml"
            project.write_text('''<project><template id="doc" effectiveDate="2026-01-01" name="Doc">
              <element name="hl7:ClinicalDocument" id="root">
                <element name="hl7:component" id="outer" minimumMultiplicity="0" maximumMultiplicity="*">
                  <element name="hl7:act" id="act">
                    <element name="hl7:entryRelationship" id="inner" minimumMultiplicity="0" maximumMultiplicity="*">
                      <element name="hl7:observation" id="obs"><element name="hl7:value" id="value" datatype="INT"/></element>
                    </element>
                  </element>
                </element>
              </element>
            </template></project>''', encoding="utf-8")
            model = {"meta": {"template_id": "doc", "template_effective_date": "2026-01-01"}, "fields": {
                "outer.inner.value": {"type": "integer", "repeat": "outer.inner", "repeat_chain": ["outer", "outer.inner"]},
            }}
            compiled = compile_cda([project], model)
            target_name = next(
                name for name, target in compiled["targets"].items()
                if str(target.get("path") or "").endswith("hl7:observation/hl7:value")
            )
            self.assertEqual(len(compiled["targets"][target_name]["repeat_ancestors"]), 2)
            record = {"key": "P1", "values": {}, "instances": {
                "outer": [
                    {"key": "o1", "values": {}, "instances": {"outer.inner": [
                        {"key": "i1", "values": {"outer.inner.value": 1}, "instances": {}},
                        {"key": "i2", "values": {"outer.inner.value": 2}, "instances": {}},
                    ]}},
                    {"key": "o2", "values": {}, "instances": {"outer.inner": [
                        {"key": "i3", "values": {"outer.inner.value": 3}, "instances": {}},
                    ]}},
                ]
            }}
            payload, _ = cda.emit(record, model, compiled, {"fields": {"outer.inner.value": target_name}}, {"null_flavor": {}})
            root = ET.fromstring(payload)
            ns = {"h": "urn:hl7-org:v3"}
            components = root.findall("h:component", ns)
            self.assertEqual(len(components), 2)
            self.assertEqual(
                [node.get("value") for node in components[0].findall("h:act/h:entryRelationship/h:observation/h:value", ns)],
                ["1", "2"],
            )
            self.assertEqual(
                [node.get("value") for node in components[1].findall("h:act/h:entryRelationship/h:observation/h:value", ns)],
                ["3"],
            )



    def test_identity_inheritance_is_transitive_but_adapt_is_not_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tx = d / "tx.xml"; extra = d / "extra.xml"
            tx.write_text('''<dataset>
              <concept type="item" shortName="derived" id="derived"><name>Derived</name><relationship type="SPEC" ref="mid"/></concept>
              <concept type="item" shortName="adapted" id="adapted"><name>Adapted</name><relationship type="ADAPT" ref="root"/></concept>
            </dataset>''', encoding="utf-8")
            extra.write_text('''<dataset>
              <concept type="item" shortName="mid" id="mid"><name>Mid</name><inherit ref="root"/></concept>
              <concept type="item" shortName="root" id="root"><name>Root</name><valueDomain type="quantity"><property unit="mg"/></valueDomain></concept>
            </dataset>''', encoding="utf-8")
            model = compile_model(tx, [extra])
            self.assertEqual(model["fields"]["derived"]["type"], "quantity")
            self.assertEqual(model["fields"]["derived"]["unit"], "mg")
            self.assertEqual(model["fields"]["adapted"]["type"], "text")



    def test_codes_mapping_prepopulates_option_identities_without_expanded_values(self) -> None:
        model = {
            "fields": {
                "triage.color": {
                    "type": "code",
                    "options": ["rot", "orange", "gelb"],
                }
            }
        }
        csv_mapping = {"fields": {"triage.color": None}}
        proposal, report = mapping.codes_mapping_proposal(model, csv_mapping, None)
        self.assertEqual(
            proposal["fields"]["triage.color"],
            {"rot": "rot", "orange": "orange", "gelb": "gelb"},
        )
        self.assertIn("3 canonical values accepted directly", report)
        self.assertIn("No aliases require configuration", report)

    def test_codes_mapping_contains_model_codes_and_display_aliases_without_csv(self) -> None:
        model = {
            "fields": {
                "referral": {
                    "name": "Zuweisung",
                    "type": "code",
                    "values": {
                        "ohne": {
                            "code": "NPHYS",
                            "code_system": "1.2.276.0.76.5.440",
                            "display_name": "Zuweisung nicht durch Arzt",
                        },
                        "Vertragsarzt/Praxis": {
                            "code": "VAP",
                            "code_system": "1.2.276.0.76.5.440",
                            "display_name": "Vertragsarzt/Praxis",
                        },
                    },
                }
            }
        }
        proposal, _ = mapping.codes_mapping_proposal(model, {"fields": {}}, None)
        self.assertEqual(proposal["fields"]["referral"]["NPHYS"], "ohne")
        self.assertEqual(proposal["fields"]["referral"]["Zuweisung nicht durch Arzt"], "ohne")
        self.assertEqual(proposal["fields"]["referral"]["ohne"], "ohne")
        self.assertEqual(proposal["fields"]["referral"]["VAP"], "Vertragsarzt/Praxis")

    def test_write_code_mapping_is_build_side_and_populated(self) -> None:
        model = {
            "fields": {
                "transport": {
                    "type": "code",
                    "values": {
                        "KTW": {"code": "1", "code_system": "1.2.3", "display_name": "KTW"},
                        "RTW": {"code": "2", "code_system": "1.2.3", "display_name": "RTW"},
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = mapping.write_code_mapping(Path(tmp), model)
            stored = load_json(Path(tmp) / "codes-mapping.proposed.json")
            self.assertEqual(result, stored)
            self.assertEqual(stored["fields"]["transport"]["1"], "KTW")
            self.assertEqual(stored["fields"]["transport"]["2"], "RTW")
            self.assertTrue((Path(tmp) / "codes-mapping.md").exists())


if __name__ == "__main__":
    unittest.main()
