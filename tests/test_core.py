from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from email.message import Message
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch
from urllib.parse import urlsplit

from decor2hl7 import assertions, cda, data, state, validate
from decor2hl7.bindings import build_assignments, target_default_values
from decor2hl7.build import mapping
from decor2hl7.build.mapping import cda_mapping_proposal
from decor2hl7.build.model import compile_model
from decor2hl7.build.target import collect_templates, compile_cda, select_template
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.artifacts import (
    compiler_inputs,
    selected_closure_template_revisions,
    selected_closure_templates,
    write_build_diagnostics,
)
from decor2hl7.compile.structural import (
    boolean_example_discriminator_rules, value_set_members,
)
from decor2hl7.cda.compile import compile_cda_model
from decor2hl7.cda.datatypes import value_representation
from decor2hl7.cda.extensions import load_extensions
from decor2hl7.cda.parity import declared_endpoint_parity
from decor2hl7.compile.reports import (
    _outline_datapoint_lines, coverage_headline_counts,
    format_coverage_headline, render_accepted_cda_mappings_markdown,
    render_cda_mapping_markdown, render_cda_mapping_trees_markdown,
)
from decor2hl7.compile.terminology import domain_difference
from decor2hl7.retrieval.artifacts import artifact_problems, artifact_record, closure_records
from decor2hl7.retrieval.catalog import parse_releases, parse_transactions, transactions
from decor2hl7.retrieval.fetch import (
    RequestBudgetExceeded, _candidate_projects, _evidence_references, _fetch_want,
    _inventory, _payload_matches_request, _resolved_effective_date,
    _satisfied, display_references, fetch_spec, hard_references,
    original_references,
    soft_references,
)
from decor2hl7.retrieval.api import REQUIRED_PATHS, artifact_representations
from decor2hl7.retrieval.sources import apply_source_hint, load_source_hints
from decor2hl7.semantics import accepted_values, direct_compatibility
from decor2hl7.transforms import OMIT, apply_transform
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


def find_required(parent: ET.Element[str], path: str) -> ET.Element[str]:
    found = parent.find(path)
    if found is None:
        raise AssertionError(f"expected XML element at {path!r}")
    return found


def complete_fixture_value_targets(cda_model: Mapping[str, Any]) -> None:
    """Apply the compiler's value-target pass to intentionally small fixtures."""
    locations: dict[str, dict[str, object]] = {}

    def walk(nodes: list[dict[str, Any]], prefix: tuple[int, ...] = ()) -> None:
        for index, node in enumerate(nodes):
            here = prefix + (index,)
            locations[".".join(map(str, here))] = node
            for attr_index, attribute in enumerate(node.get("attributes", [])):
                locations[".".join(map(str, here + (100000 + attr_index,)))] = attribute
            walk(node.get("children", []), here)

    walk(cda_model.get("document", []))
    for target in cda_model.get("targets", {}).values():
        location = str((target.get("locations") or [""])[0])
        physical = locations.get(location, {})
        datatype = target.get("datatype") or physical.get("datatype")
        target["datatype"] = datatype
        path = str(target.get("path") or "")
        attribute_name = path.rsplit("/@", 1)[-1] if "/@" in path else None
        representation = value_representation(
            str(datatype or ""), attribute_name=attribute_name
        )
        if representation is None:
            continue
        target["value_representation"] = representation.to_dict()
        target["logical_types"] = list(representation.logical_types)
        target["writable"] = bool(target.get("renderable"))


def api_path(url: str) -> str:
    return urlsplit(url).path


class CoreTests(unittest.TestCase):
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

    def test_cda_extensions_are_exact_and_transaction_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cda-extensions.json"
            attachment = {
                "transaction_id": "tx", "transaction_effective_date": "2026",
                "document_template_id": "doc", "document_template_effective_date": "2026.1",
                "parent_template_id": "section", "parent_template_effective_date": "2024",
                "parent_element_id": "section-root", "element_name": "hl7:entry",
                "template_id": "entry", "template_effective_date": "2024",
                "minimum_multiplicity": 0, "maximum_multiplicity": 1,
                "conformance": "r", "reason": "Reviewed placement",
            }
            path.write_text(json.dumps({
                "format": 1,
                "attachments": [attachment, {**attachment, "transaction_id": "other"}],
            }), encoding="utf-8")
            selected = load_extensions(
                path, {"id": "tx", "effective_date": "2026"}
            )
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["conformance"], "R")
            self.assertEqual(selected[0]["template_id"], "entry")
            missing_maximum = dict(attachment)
            missing_maximum.pop("maximum_multiplicity")
            path.write_text(json.dumps({
                "format": 1, "attachments": [missing_maximum],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "maximum_multiplicity"):
                load_extensions(
                    path,
                    {"id": "tx", "effective_date": "2026"},
                )

            branch = {
                "operation": "select_spec_branch",
                "transaction_id": "tx", "transaction_effective_date": "2026",
                "document_template_id": "doc",
                "document_template_effective_date": "2026.1",
                "parent_template_id": "medication",
                "parent_template_effective_date": "2024",
                "parent_element_id": "medication-root",
                "element_name": "hl7:consumable",
                "template_id": "detail", "template_effective_date": "2024",
                "replaces_template_id": "simple",
                "replaces_template_effective_date": "2023",
                "reason": "Reviewed richer branch",
            }
            path.write_text(json.dumps({
                "format": 1, "attachments": [branch],
            }), encoding="utf-8")
            self.assertEqual(
                load_extensions(
                    path, {"id": "tx", "effective_date": "2026"}
                ),
                [branch],
            )

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
            dataset, project=dataset["project"], main_project="aktin-",
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
                domain_difference(field)["logical_only"], ["Logical only"]
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
    <desc language="en-US">Example document description</desc>
    <element name="hl7:ClinicalDocument" id="root" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:value" id="e" datatype="ST" minimumMultiplicity="0" maximumMultiplicity="1">
        <desc language="en-US">Example payload description</desc>
      </element>
    </element>
  </template>
</project>''', encoding="utf-8")
            model = {"meta": {"template_id": "doc", "template_effective_date": "2026-01-01"}, "groups": {}, "fields": {"foo": {"name": "Foo", "concept": "c", "type": "text", "value_sets": [], "codes": [], "parent": None}}}
            target = compile_cda([project], model)
            self.assertIn("ExampleDocument.value", target["targets"])
            self.assertEqual(
                target["document_template"]["description"],
                "Example document description",
            )
            self.assertEqual(
                target["targets"]["ExampleDocument.value"]["description"],
                "Example payload description",
            )
            self.assertEqual(
                target["targets"]["ExampleDocument.value"]["template_description"],
                "Example document description",
            )
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
            guide = (output / "cda-mapping-details.md").read_text(encoding="utf-8")
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
            decisions = (output / "cda-mapping.md").read_text(encoding="utf-8")
            self.assertNotIn("Abridged configuration excerpt", decisions)
            self.assertTrue((output / "cda-mapping-trees.md").is_file())


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
            <attribute name="nullFlavor" datatype="CS" isOptional="true"/>
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
            target_name = "Referral.code"
            self.assertTrue(target["targets"][target_name]["has_children"])
            self.assertTrue(
                target["targets"][target_name]["permits_null_flavor"]
            )
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
                "writable": False,
            }
            compatible, reasons = direct_compatibility(field, section_code)
            self.assertFalse(compatible)
            self.assertIn("structural, fixed, prohibited, or ambiguous", reasons[0])

    def test_mapping_outline_keeps_status_gutter_and_never_wraps_leaves(self) -> None:
        short = _outline_datapoint_lines(
            "│   │   ",
            {"dataset_name": "Patienten ID", "target": "PatientIdentifier.id"},
            last=True, status="✓",
        )
        self.assertEqual(
            short,
            ["✓  │   │   └── Patienten ID → {PatientIdentifier.id}"],
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
            last=False, status="!",
        )
        self.assertEqual(
            long,
            [
                "!  │   │   ├── Aufnahmezeitpunkt → "
                "{CDAEncompassingEncounter.componentOf.encompassingEncounter."
                "effectiveTime.low@20160601}",
            ],
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

    def test_exact_structural_description_projects_to_deepest_writable_leaf(self) -> None:
        context = {"chain": ["CTX[link]"], "node": {
            "locations": ["0"], "path": "hl7:observation",
        }}
        targets = {
            "ExternalDocument": {
                "locations": ["0.1"],
                "path": "hl7:observation/hl7:externalDocument",
                "description": "Link zur Definition", "writable": False,
            },
            "ExternalDocument.text": {
                "locations": ["0.1.0"],
                "path": "hl7:observation/hl7:externalDocument/hl7:text",
                "datatype": "ED", "writable": True,
                "logical_types": ["text"], "value_representation": {
                    "kind": "element_text", "logical_types": ["text"],
                },
            },
            "ExternalDocument.reference": {
                "locations": ["0.1.0.0"],
                "path": "hl7:observation/hl7:externalDocument/hl7:text/hl7:reference",
                "datatype": "URL", "writable": True,
                "logical_types": ["text"], "value_representation": {
                    "kind": "attribute", "attribute": "value",
                    "logical_types": ["text"],
                },
            },
        }
        candidates = mapping_compiler._context_description_candidates(
            {"name": "Definitorischer Link", "description": "Link zur Definition", "type": "text"},
            context, {"targets": targets}, {"structures": {}},
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["target"], "ExternalDocument.reference")
        self.assertTrue(candidates[0]["actionable"])
        self.assertIn("CDA_DESCENDANT", candidates[0]["chain"])

    def test_choice_branch_prefers_atomic_value_and_follows_complex_duration(self) -> None:
        context = {"chain": ["CTX[time]"], "node": {
            "locations": ["0"], "path": "hl7:observation",
            "repeat_ancestors": [],
        }}
        common = {
            "kind": "element", "writable": True, "prohibited": False,
            "locations": ["0.1"], "repeat_ancestors": [],
        }
        targets = {
            "Time.interval": {
                **common, "path": "hl7:observation/hl7:effectiveTime[@xsi:type='IVL_TS']",
                "datatype": "IVL_TS", "has_children": True,
                "logical_types": ["datetime"], "value_representation": {
                    "kind": "timestamp", "logical_types": ["datetime"],
                    "attribute": "value",
                },
            },
            "Time.point": {
                **common, "locations": ["0.2"],
                "path": "hl7:observation/hl7:effectiveTime[not(@xsi:type)]",
                "datatype": "TS", "has_children": False,
                "logical_types": ["datetime"], "value_representation": {
                    "kind": "timestamp", "logical_types": ["datetime"],
                    "attribute": "value",
                },
            },
            "Time.width": {
                "kind": "element", "writable": True, "prohibited": False,
                "datatype_derived": True, "locations": ["0.1.0"],
                "repeat_ancestors": [],
                "path": "hl7:observation/hl7:effectiveTime[@xsi:type='IVL_TS']/hl7:width",
                "datatype": "PQ", "has_children": False,
                "logical_types": ["duration"], "value_representation": {
                    "kind": "quantity", "logical_types": ["duration"],
                    "attributes": ["value", "unit"], "scalar_attribute": "value",
                },
            },
        }
        point = mapping_compiler._choice_branch_candidates(
            {"type": "datetime", "repeat_chain": []}, context,
            {"targets": targets}, {"structures": {}},
        )
        duration = mapping_compiler._choice_branch_candidates(
            {"type": "duration", "repeat_chain": []}, context,
            {"targets": targets}, {"structures": {}},
        )
        self.assertEqual(point[0]["target"], "Time.point")
        self.assertEqual(duration[0]["target"], "Time.width")

    def test_context_descendant_prefers_existing_outer_leaf_over_polymorphic_leaf(self) -> None:
        context = {"chain": ["CTX[timing]"], "node": {
            "locations": ["0"], "path": "hl7:substanceAdministration",
            "repeat_ancestors": [],
        }}
        common = {
            "kind": "element", "writable": True, "prohibited": False,
            "datatype": "PQ", "logical_types": ["quantity"],
            "repeat_ancestors": [], "value_representation": {
                "kind": "quantity", "logical_types": ["quantity"],
                "attributes": ["value", "unit"], "scalar_attribute": "value",
            },
        }
        targets = {
            "Timing.offset": {
                **common, "locations": ["0.0"],
                "path": "hl7:substanceAdministration/hl7:effectiveTime/hl7:offset",
            },
            "Timing.comp_as_EIVL_TS.offset": {
                **common, "datatype_derived": True, "locations": ["0.1.0"],
                "path": (
                    "hl7:substanceAdministration/hl7:effectiveTime/"
                    "hl7:comp_as_EIVL_TS/hl7:offset"
                ),
            },
        }
        candidates = mapping_compiler._context_descendant_candidates(
            {
                "name": "Offset", "short_name": "offset", "concept": "offset",
                "type": "quantity", "repeat_chain": [],
            },
            context, {"targets": targets}, {"offset": {"Offset"}}, {},
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["target"], "Timing.offset")

    def test_context_labels_follow_formal_origins_not_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "concepts.xml"
            source.write_text(
                """<decor><dataset>
                <concept id="current"><name>Current</name>
                  <inherit ref="original"/>
                  <relationship type="ADAPT" ref="related"/>
                </concept>
                <concept id="original"><name>Formal label</name></concept>
                <concept id="related"><name>Relationship label</name></concept>
                </dataset></decor>""",
                encoding="utf-8",
            )
            labels, neighbours = mapping_compiler._formal_origin_label_index(
                [source]
            )
        evidence = mapping_compiler._formal_origin_labels(
            "current", labels, neighbours
        )
        self.assertIn(("original", 1, "Formal label"), evidence)
        self.assertFalse(any(row[0] == "related" for row in evidence))

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
        unused = element("hl7:text", datatype="ST", targets=["Referral.unused"])
        section = element("hl7:section", [candidate, unused], target="Referral.section")
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
                    "writable": True, "fixed": {}, "system_value": None,
                },
                "Referral.unused": {
                    "locations": ["0.1.0.1"], "path": "hl7:section/hl7:text",
                    "datatype": "ST", "kind": "element", "description": "Unused text",
                    "template_name": "Referral", "template_display_name": "Referral",
                    "writable": True, "fixed": {}, "system_value": None,
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
        mapping_cfg = {"fields": {
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
        accepted = render_accepted_cda_mappings_markdown(
            model, cda_model, mapping_cfg
        )
        counts = coverage_headline_counts(model, cda_model, mapping_cfg, audit)
        self.assertEqual(counts, {
            "datapoints": 3,
            "mapped_datapoints": 2,
            "mapped_leaves": 2,
            "suggested_datapoints": 1,
            "suggested_leaves": 1,
            "no_target_datapoints": 0,
            "no_source_leaves": 1,
        })
        self.assertEqual(
            format_coverage_headline(counts, markdown=False),
            "Model: 3 datapoints · ✓ mapped 2 dp → 2 leaves · "
            "! suggested 1 dp → 1 leaf · × no target 0 dp · "
            "○ no source 1 leaf",
        )
        self.assertIn(
            "Model: **3 datapoints** · ✓ mapped **2 dp → 2 leaves** · "
            "! suggested **1 dp → 1 leaf** · × no target **0 dp** · "
            "○ no source **1 leaf**",
            report,
        )
        self.assertIn("!      └── Referral source", report)
        self.assertIn("✓  │       ├── low {Encounter.low} ← Start", trees)
        self.assertIn(
            "○          └── text {Referral.unused} ← no dataset counterpart",
            trees,
        )
        self.assertIn('<componentOf typeCode="COMP">', accepted)
        self.assertIn('<encompassingEncounter classCode="ENC" moodCode="EVN">', accepted)
        self.assertIn('<low value="{Encounter.low}"/>', accepted)
        self.assertIn('<high value="{Encounter.high}"/>', accepted)
        self.assertIn("manual decision workbench", report)
        self.assertIn("Referral code", report)
        self.assertIn("SPEC → TA", report)
        self.assertIn("selectable after review", report)

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
        complete_fixture_value_targets(compiled)
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
            def walk(nodes: list[dict[str, Any]]) -> None:
                for node in nodes:
                    if node.get("contains"):
                        contains.append(str(node["contains"]))
                    walk(node.get("children", []))
            walk(compiled["document"])
            self.assertIn("new-section", contains)
            self.assertNotIn("old-section", contains)

    def test_spec_weakening_uses_explicit_child_constraint_and_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''
<project>
  <template id="parent" effectiveDate="2020-01-01" name="Parent">
    <element name="hl7:ClinicalDocument" id="document">
      <element name="hl7:statusCode" id="status" datatype="CS"
               minimumMultiplicity="1" maximumMultiplicity="1"
               conformance="R" isMandatory="true"/>
    </element>
  </template>
  <template id="child" effectiveDate="2026-01-01" name="Child">
    <relationship type="SPEC" template="parent" flexibility="2020-01-01"/>
    <element name="hl7:ClinicalDocument" id="document">
      <attribute name="classCode" value="DOCCLIN"/>
      <element name="hl7:statusCode" id="status" datatype="CS"
               minimumMultiplicity="0" maximumMultiplicity="1"
               conformance="R"/>
    </element>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {
                    "template_id": "child",
                    "template_effective_date": "2026-01-01",
                },
                "groups": {},
                "fields": {},
            }
            compiled = compile_cda([project], model)
            status = compiled["document"][0]["children"][0]
            self.assertEqual(status["min"], 0)
            self.assertFalse(status["mandatory"])
            self.assertEqual(
                compiled["stats"]["constraint_diagnostics"], 1,
            )
            diagnostic = compiled["constraint_diagnostics"][0]
            self.assertEqual(diagnostic["code"], "spec-constraint-weakening")
            self.assertEqual(
                [change["property"] for change in diagnostic["changes"]],
                ["minimumMultiplicity", "mandatory"],
            )

            payload, problems = cda.emit(
                {"key": "1", "values": {}}, {"fields": {}}, compiled,
                {"fields": {}}, {"null_flavor": {"missing_required": "NI"}},
            )
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            self.assertIsNone(root.find("{urn:hl7-org:v3}statusCode"))

            with self.assertRaisesRegex(
                ValueError, "CDA SPEC constraint weakening",
            ):
                compile_cda(
                    [project], model, strict_specializations=True,
                )

    def test_spec_weakening_policy_also_applies_to_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''
<project>
  <template id="group" effectiveDate="2020-01-01" name="Group">
    <element name="hl7:title" minimumMultiplicity="0"
             maximumMultiplicity="1"/>
  </template>
  <template id="parent" effectiveDate="2020-01-01" name="Parent">
    <element name="hl7:ClinicalDocument" id="document">
      <include ref="group" flexibility="2020-01-01"
               minimumMultiplicity="1" maximumMultiplicity="1"
               conformance="R" isMandatory="true"/>
    </element>
  </template>
  <template id="child" effectiveDate="2026-01-01" name="Child">
    <relationship type="SPEC" template="parent" flexibility="2020-01-01"/>
    <element name="hl7:ClinicalDocument" id="document">
      <attribute name="classCode" value="DOCCLIN"/>
      <include ref="group" flexibility="2020-01-01"
               minimumMultiplicity="0" maximumMultiplicity="1"
               conformance="R"/>
    </element>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {
                    "template_id": "child",
                    "template_effective_date": "2026-01-01",
                },
                "groups": {},
                "fields": {},
            }

            compiled = compile_cda([project], model)
            include = compiled["document"][0]["children"][0]
            self.assertEqual(include["kind"], "include")
            self.assertEqual(include["min"], 0)
            self.assertFalse(include["mandatory"])
            self.assertEqual(
                compiled["constraint_diagnostics"][0]["path"],
                "include:group",
            )

    def test_missing_spec_parent_revision_degrades_only_the_refinement(self) -> None:
        """A missing SPEC parent revision must not erase or replace its child.

        `template:2.16.840.1.113883.10.20.1.53@2005-09-07` is requested by the
        medication branch, but only `@2007-04-01` is published anywhere. The
        child must still compile from its own constraints plus the pinned
        CDA/RIM expansion, stay located in the selected document, and leave the
        unresolved relation visible (`DEC-004`, `DEC-010`).
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.xml"
            project.write_text('''
<project>
  <template id="product" effectiveDate="2007-04-01" name="Product"><element name="hl7:manufacturedProduct" id="mp"><element name="hl7:manufacturedMaterial" id="mm"/></element></template>
  <template id="material" effectiveDate="2017-06-04" name="Material"><relationship type="SPEC" template="product" flexibility="2005-09-07"/><element name="hl7:manufacturedProduct" id="mp"><element name="hl7:manufacturedMaterial" id="mm"><element name="hl7:code" id="code" datatype="CE"/></element></element></template>
  <template id="doc" effectiveDate="2026-01-01" name="Document"><element name="hl7:ClinicalDocument" id="doc"><element name="hl7:component" contains="material" id="component"/></element></template>
</project>''', encoding="utf-8")
            model = {
                "meta": {
                    "template_id": "doc",
                    "template_effective_date": "2026-01-01",
                },
                "groups": {},
                "fields": {},
            }
            # SPEC is an optional editor prototype, not part of the
            # executable include/contains closure. Its exact absence remains
            # visible but does not make either compile mode incomplete.
            compiled = compile_cda([project], model)
            self.assertEqual(compiled["unresolved_templates"], [])
            self.assertIn(
                ("SPEC", "product", "2005-09-07"),
                {
                    (row["relation"], row["template"], row["flexibility"])
                    for row in compiled["unresolved_template_prototypes"]
                },
            )
            child = {
                name: target
                for name, target in compiled["targets"].items()
                if target.get("template_id") == "material"
            }
            self.assertTrue(child, "the child template must still compile")
            self.assertTrue(
                any(target.get("locations") for target in child.values()),
                "the child must stay located in the selected document",
            )
            # The refinement is omitted, not satisfied by the other revision.
            self.assertEqual(
                {target.get("template_effective_date") for target in child.values()},
                {"2017-06-04"},
            )


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

    def test_fetch_adds_reviewed_cda_extension_to_build_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []
            attachment = {
                "transaction_id": "t", "transaction_effective_date": "2026-03-25",
                "document_template_id": "doc", "document_template_effective_date": "2026",
                "parent_template_id": "section", "parent_template_effective_date": "2024",
                "parent_element_id": "section-root", "element_name": "hl7:entry",
                "template_id": "extra", "template_effective_date": "2024",
                "minimum_multiplicity": 0, "maximum_multiplicity": 1,
                "conformance": "R", "reason": "Reviewed placement",
            }

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="2026"/></transaction>'
                if path.endswith("/project/aktin-/$extract"):
                    return b"<project/>"
                if path.endswith("/project/aktin-"):
                    return b"<project/>"
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026" name="Doc"><element name="hl7:ClinicalDocument"/></template></return>'
                if "/template/extra/" in path:
                    return b'<return><template id="extra" effectiveDate="2024" name="Extra"><element name="hl7:observation"/></template></return>'
                raise AssertionError(url)

            transaction = {
                **TRANSACTION,
                "id": "t", "effective_date": "2026-03-25", "key": "tx",
            }
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-", release=RELEASE,
                    transaction=transaction, max_requests=30,
                    cda_extensions=[attachment],
                )
            self.assertTrue(any("/template/extra/" in api_path(url) for url in calls))
            self.assertIn(
                "template:extra@2024", result["closure"]["build_resources"]
            )
            self.assertEqual(result["closure"]["cda_extensions"], [attachment])
            self.assertEqual(
                compiler_inputs(release_dir, tx_dir)["cda_extensions"],
                [attachment],
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
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "project": "first-"}
            budget = {"made": 0, "max": 1}
            def missing(_url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(_url, 404, "missing", Message(), None)
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

    def test_repeat_by_discriminator_creates_side_discriminated_occurrences(self) -> None:
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
                "value_set_bindings": [{"id": "eye-sides", "effective_date": "2015-11-17"}],
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
                "type": "repeat_by_discriminator",
                "discriminator": {
                    "target": "Pupil.side",
                    "value_set": {"id": "eye-sides", "effective_date": "2015-11-17"},
                    "members": [
                        {"code": "R", "codeSystem": "1.2.276.0.76.3.1.195.5.48"},
                        {"code": "L", "codeSystem": "1.2.276.0.76.3.1.195.5.48"},
                    ],
                    "evidence_level": "STRONG",
                },
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
        complete_fixture_value_targets(cda_model)
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
        report = render_accepted_cda_mappings_markdown(
            model, report_cda, mapping_cfg,
        )
        self.assertIn("{Pupil_right.value}", report)
        self.assertIn("{Pupil_left.value}", report)
        self.assertLess(
            report.index("Abridged configuration excerpt"),
            report.index("Resulting CDA placement"),
        )
        self.assertIn("XML excerpts below are read-only", report)
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
        invalid = json.loads(json.dumps(mapping_cfg))
        invalid["structures"]["pupils"]["branches"][0]["constants"]["Pupil.side"] = {
            "code": "X", "codeSystem": "1.2.276.0.76.3.1.195.5.48",
        }
        self.assertTrue(any(
            "outside the selected bound ValueSet" in error
            for error in validate.check_config(
                model, cda_model,
                {"fields": {"pupil.right": None, "pupil.left": None}},
                invalid,
            )
        ))

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
                "min": 1, "max": 1, "value_sets": ["eye-sides"],
                "value_set_bindings": [{
                    "id": "eye-sides", "effective_date": "2015-11-17",
                }],
            },
        }, "assertions": [
            {"test": "count(hl7:targetSiteCode[@code='R']) &lt;= 1"},
            {"test": "count(hl7:targetSiteCode[@code='L']) &lt;= 1"},
        ]}
        inferred = mapping_compiler._fanout_rule(
            ["vitals.pupil_right", "vitals.pupil_left"], "Pupil.value",
            pupil_model, pupil_cda,
            {("eye-sides", "2015-11-17"): [
                {"code": "R", "codeSystem": "1.2.276.0.76.3.1.195.5.48", "displayName": "Auge rechts", "designations": [{"language": "en-US", "displayName": "Right eye"}]},
                {"code": "L", "codeSystem": "1.2.276.0.76.3.1.195.5.48", "displayName": "Auge links", "designations": [{"language": "en-US", "displayName": "Left eye"}]},
            ]},
        )
        self.assertIsNotNone(inferred)
        assert inferred is not None
        _, fanout = inferred
        self.assertEqual(fanout["type"], "repeat_by_discriminator")
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
            ["R", "L"],
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
        assert certainty is not None
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
        assert coalesced is not None
        self.assertEqual(coalesced[1]["policy"], "equal_or_error")

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
            }
            proposal, _ = mapping_compiler.cda_mapping_proposal(
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

        self.assertIsNone(classify(
            "case.complete",
            {"selected": "Observation.value"},
            {"formal_terminology": {"status": "bound", "complete": True}},
            [],
        ))

    def test_schematron_constraints_only_strengthen_an_existing_candidate(self) -> None:
        target = {
            "writable": True,
            "datatype": "TS",
            "path": "hl7:observation/hl7:effectiveTime",
            "logical_types": ["datetime", "date"],
            "repeat_ancestors": [],
            "schematron_constraints": [{
                "kind": "required", "path": "hl7:effectiveTime", "value": 1,
            }],
        }
        field = {"type": "datetime", "repeat_chain": []}
        strengthen = mapping_compiler._schematron_constraint_candidates
        self.assertEqual(strengthen(field, [], {"targets": {}}, None), [])
        original = mapping_compiler._candidate(
            "Observation.effectiveTime", target, ["NAME"], "WEAK", 60,
            kind="NAME", actionable=False,
        )
        rows = strengthen(
            field, [original], {"targets": {"Observation.effectiveTime": target}},
            None,
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["actionable"])
        self.assertEqual(rows[0]["kind"], "SCHEMATRON_CONSTRAINT")
        self.assertIn("SCHEMATRON_CONSTRAINT(required)", rows[0]["chain"])

    def test_relationship_paths_stay_review_only_but_contains_is_origin(self) -> None:
        target = {
            "template_id": "encounter", "template_effective_date": "2026",
            "element_id": "low", "kind": "element", "writable": True,
            "renderable": True, "locations": ["0.0"],
            "path": "hl7:effectiveTime/hl7:low", "datatype": "TS",
            "logical_types": ["datetime", "date"], "repeat_ancestors": [],
            "value_representation": {
                "kind": "timestamp", "logical_types": ["datetime", "date"],
                "attribute": "value",
            },
            "schematron_constraints": [{"kind": "required", "value": 1}],
        }
        field = {
            "name": "Documentation start", "concept": "current",
            "type": "datetime", "repeat_chain": [],
        }
        associations = [{
            "concept": "legacy", "template_id": "encounter",
            "effective_date": "2026", "element_id": "low",
            "kind": "templateAssociation", "code_systems": [],
        }]
        cda_model = {
            "source_index": {"encounter|ID:low": ["Encounter.low"]},
            "targets": {"Encounter.low": target},
        }
        for relationship in (
            "REPL", "SPEC", "GEN", "COPY", "ADAPT", "EQUIV",
            "VERSION", "BACKWD", "DRIV",
        ):
            with self.subTest(relationship=relationship):
                candidates = mapping_compiler._ta_candidates(
                    field,
                    {"current": {(f"relationship:{relationship}", "legacy")}},
                    associations,
                    {"legacy": "Admission time"},
                    cda_model,
                )
                self.assertEqual(len(candidates), 1)
                candidate = candidates[0]
                self.assertFalse(candidate["actionable"])
                self.assertEqual(
                    candidate["semantic_blocked"],
                    "relationship_requires_review",
                )
                self.assertIn("relationship name drift", candidate["warnings"])
                self.assertTrue(any(
                    "not formal concept inheritance" in warning
                    for warning in candidate["warnings"]
                ))
                strengthened = mapping_compiler._schematron_constraint_candidates(
                    field, candidates, cda_model, None,
                )
                self.assertEqual(len(strengthened), 1)
                self.assertFalse(strengthened[0]["actionable"])
                transformed = mapping_compiler._semantic_transform_candidates(
                    {
                        **field,
                        "type": "code",
                        "accepted_values": {
                            "Present": {"synonyms": []},
                            "Not present": {"synonyms": []},
                        },
                    },
                    candidates,
                    {"targets": {
                        **cda_model["targets"],
                        "Encounter.negationInd": {
                            **target,
                            "path": "hl7:observation/@negationInd",
                            "datatype": "BL",
                        },
                    }},
                )
                self.assertEqual(transformed, [])

        contained = mapping_compiler._ta_candidates(
            {**field, "name": "Admission time"},
            {"current": {("contains", "legacy")}},
            associations,
            {"legacy": "Admission time"},
            cda_model,
        )
        self.assertEqual(len(contained), 1)
        self.assertTrue(contained[0]["actionable"])
        self.assertEqual(contained[0]["confidence"], "STRONG")

    def test_semantic_negation_transform_beats_unrelated_named_code_slot(self) -> None:
        model = {"groups": {}, "fields": {"measures.isolation": {
            "name": "Isolation", "short_name": "Isolation", "concept": "isolation",
            "type": "code", "repeat_chain": [], "value_sets": [], "codes": [],
            "accepted_values": {
                "Patient muss isoliert werden": {"synonyms": []},
                "Patient muss nicht isoliert werden": {"synonyms": []},
            },
        }}}
        common = {
            "template_id": "isolation", "template_name": "isolation",
            "template_display_name": "Isolation", "renderable": True,
            "writable": True, "locations": ["0.0"], "repeat_ancestors": [],
            "datatype_derived": False,
        }
        cda_model: dict[str, Any] = {"targets": {
            "isolation.statusCode": {
                **common, "path": "hl7:observation/hl7:statusCode", "datatype": "CS",
                "value_representation": {"kind": "coded"}, "logical_types": ["code"],
            },
            "isolation.negationInd": {
                **common, "path": "hl7:observation/@negationInd", "datatype": "BL",
                "value_representation": {"kind": "boolean"}, "logical_types": ["boolean"],
            },
        }}
        proposal, audit, _, _ = mapping_compiler.cda_mapping_audit(
            model, cda_model, []
        )
        self.assertEqual(proposal["fields"]["measures.isolation"], [{
            "target": "isolation.negationInd",
            "transform": {"type": "enum", "map": {
                "Patient muss isoliert werden": False,
                "Patient muss nicht isoliert werden": True,
            }},
        }])
        self.assertEqual(
            audit["fields"]["measures.isolation"]["alternatives"][0]["target"],
            "isolation.statusCode",
        )

    def test_semantic_negation_does_not_collapse_a_multivalued_domain(self) -> None:
        model = {"groups": {}, "fields": {"triage.complaint": {
            "name": "Complaint", "short_name": "Complaint", "concept": "complaint",
            "type": "code", "repeat_chain": [], "value_sets": ["complaints"],
            "codes": [], "accepted_values": {
                "Chest pain": {"synonyms": []},
                "Pain not caused by trauma": {"synonyms": []},
                "Headache": {"synonyms": []},
            },
        }}}
        common = {
            "template_id": "complaint", "template_name": "complaint",
            "template_display_name": "Complaint", "renderable": True,
            "writable": True, "locations": ["0.0"], "repeat_ancestors": [],
            "datatype_derived": False,
        }
        cda_model: dict[str, Any] = {"targets": {
            "complaint.value": {
                **common, "path": "hl7:observation/hl7:value", "datatype": "CD",
                "value_sets": ["complaints"],
                "value_representation": {"kind": "coded"}, "logical_types": ["code"],
            },
            "complaint.negationInd": {
                **common, "path": "hl7:observation/@negationInd", "datatype": "BL",
                "value_representation": {"kind": "boolean"},
                "logical_types": ["boolean"],
            },
        }}
        proposal, audit, _, _ = mapping_compiler.cda_mapping_audit(
            model, cda_model, []
        )
        self.assertEqual(
            proposal["fields"]["triage.complaint"], "complaint.value"
        )
        self.assertFalse(any(
            row["target"] == "complaint.negationInd"
            and row["kind"] == "TRANSFORM"
            for row in audit["fields"]["triage.complaint"]["alternatives"]
        ))

    def test_boolean_act_presence_uses_template_negation_semantics(self) -> None:
        model = {"groups": {}, "fields": {"diagnostics.spine_xray": {
            "name": "Röntgen-Wirbelsäule durchgeführt",
            "short_name": "spine_xray", "concept": "spine-xray",
            "description": "Wurde ein Röntgen der Wirbelsäule durchgeführt?",
            "type": "boolean", "repeat_chain": [], "value_sets": [],
            "codes": [{
                "code": "79760008", "code_system": "2.16.840.1.113883.6.96",
                "display_name": "Radiography of spine (procedure)",
            }],
        }}}
        target = {
            "template_id": "spine", "template_name": "Radiographyofspine",
            "template_display_name": "Radiography of spine",
            "path": "hl7:observation/@negationInd", "datatype": "BL",
            "renderable": True, "writable": True, "locations": ["0.100000"],
            "repeat_ancestors": [], "datatype_derived": False,
            "logical_types": ["boolean"],
            "value_representation": {"kind": "boolean", "attribute": "value"},
        }
        proposal, _ = mapping_compiler.cda_mapping_proposal(
            model, {"targets": {"Radiographyofspine.negationInd": target}}, []
        )
        self.assertEqual(proposal["fields"]["diagnostics.spine_xray"], {
            "target": "Radiographyofspine.negationInd",
            "transform": {"type": "not"},
        })

    def test_boolean_can_activate_optional_fixed_statement(self) -> None:
        model = {"groups": {}, "fields": {"triage.direct_contact": {
            "name": "Direkter Arztkontakt", "short_name": "direct_contact",
            "concept": "direct-contact", "type": "boolean", "repeat_chain": [],
            "value_sets": [], "codes": [{
                "code": "FLN-13", "code_system": "1.2.3",
                "display_name": "Direkter Arztkontakt", "equivalence": "equal",
            }],
        }}}
        root = {
            "template_id": "contact", "template_name": "direct_contact",
            "template_display_name": "Direkter Arztkontakt", "kind": "element",
            "path": "hl7:observation", "renderable": True, "writable": False,
            "has_children": True, "locations": ["0.0"], "repeat_ancestors": [],
        }
        code = {
            **root, "path": "hl7:observation/hl7:code", "has_children": True,
            "locations": ["0.0.0"], "codes": [{
                "code": "FLN-13", "code_system": "1.2.3",
            }],
            "value_representation": {
                "kind": "coded", "attributes": ["code", "codeSystem"],
                "scalar_attribute": "code",
            },
        }
        cda_model: dict[str, Any] = {"targets": {
                "direct_contact.observation": root,
                "direct_contact.code": code,
            }, "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument",
                "min": 1, "mandatory": True, "fixed": {"classCode": "DOCCLIN"},
                "attributes": [], "codes": [], "targets": [], "children": [{
                    "kind": "element", "name": "hl7:observation",
                    "min": 0, "mandatory": False, "fixed": {},
                    "attributes": [], "codes": [],
                    "targets": ["direct_contact.observation"], "children": [{
                        "kind": "element", "name": "hl7:code", "datatype": "CD",
                        "min": 1, "mandatory": True, "fixed": {},
                        "attributes": [], "codes": [{
                            "code": "FLN-13", "code_system": "1.2.3",
                        }], "targets": ["direct_contact.code"], "children": [],
                    }],
                }],
            }]}
        proposal, audit, _, _ = mapping_compiler.cda_mapping_audit(
            model, cda_model, []
        )
        self.assertEqual(proposal["fields"]["triage.direct_contact"], {
            "target": "direct_contact.observation", "mode": "presence",
        })
        self.assertEqual(
            audit["fields"]["triage.direct_contact"]["primary"]["kind"],
            "CONDITIONAL_PRESENCE",
        )

        cda_model["targets"]["direct_contact.value"] = {
            **root, "path": "hl7:observation/hl7:value", "datatype": "ST",
            "writable": True, "has_children": False, "locations": ["0.0.1"],
            "compiled_default": {
                "value": "Example content", "source": "template-example",
            },
            "value_representation": {
                "kind": "element_text", "logical_types": ["text"],
            },
        }
        cda_model["document"][0]["children"][0]["children"].append({
            "kind": "element", "name": "hl7:value", "datatype": "ST",
            "min": 1, "mandatory": True, "fixed": {}, "attributes": [],
            "codes": [], "targets": ["direct_contact.value"], "children": [],
            "compiled_default": {
                "value": "Example content", "source": "template-example",
            },
        })
        incomplete, _ = mapping_compiler.cda_mapping_proposal(
            model, cda_model, []
        )
        self.assertIsNone(incomplete["fields"]["triage.direct_contact"])

    def test_repeat_scope_selects_nearest_unique_value(self) -> None:
        field = {
            "parent": "vitals", "repeat_chain": ["vitals"], "type": "datetime",
        }
        section = {
            "path": "hl7:section", "locations": ["0"], "renderable": True,
        }
        common = {
            "kind": "element", "writable": True, "renderable": True,
            "prohibited": False, "logical_types": ["datetime"],
            "value_representation": {"kind": "timestamp"},
            "repeat_ancestors": ["0.2"],
        }
        cda_model = {"targets": {
            "section": section,
            "entry": {
                "path": "hl7:section/hl7:entry", "locations": ["0.2"],
                "renderable": True, "repeatable": True,
            },
            # Document plumbing can be physically nearer and even look type-
            # compatible in a reduced fixture; it is never a clinical repeat
            # payload fallback.
            "entry.realmCode": {
                **common, "path": "hl7:entry/hl7:realmCode",
                "element_name": "hl7:realmCode", "locations": ["0.2.0"],
            },
            "organizer.effectiveTime": {
                **common, "path": "hl7:organizer/hl7:effectiveTime",
                "locations": ["0.2.0.3"],
            },
            "observation.effectiveTime": {
                **common, "path": "hl7:observation/hl7:effectiveTime",
                "locations": ["0.2.0.4.0.3"],
            },
        }}
        candidates = mapping_compiler._repeat_scope_candidates(
            field, {"node": section, "chain": ["CTX[vitals]"]}, cda_model,
            {"structures": {"for-each-vitals": {
                "type": "for_each", "source_group": "vitals",
                "target_repeat": "entry",
            }}},
        )
        self.assertEqual(
            [candidate["target"] for candidate in candidates],
            ["organizer.effectiveTime"],
        )

    def test_presence_assignment_emits_fixed_statement_only_for_true(self) -> None:
        compiled = {
            "targets": {
                "Contact.observation": {
                    "kind": "element", "path": "hl7:observation",
                    "renderable": True, "writable": False, "has_children": True,
                    "locations": ["0.0"], "repeat_ancestors": [],
                },
                "Contact.code": {
                    "kind": "element", "path": "hl7:observation/hl7:code",
                    "renderable": True, "writable": False, "has_children": True,
                    "locations": ["0.0.0"], "repeat_ancestors": [],
                    "value_representation": {
                        "kind": "coded", "attributes": ["code", "codeSystem"],
                        "scalar_attribute": "code",
                    },
                },
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1,
                "max": 1, "mandatory": True, "attributes": [], "codes": [],
                "fixed": {"classCode": "DOCCLIN"}, "targets": [], "asserts": [], "lets": {},
                "children": [{
                    "kind": "element", "name": "hl7:observation", "min": 0,
                    "max": 1, "mandatory": False, "attributes": [], "codes": [],
                    "fixed": {}, "targets": ["Contact.observation"],
                    "asserts": [], "lets": {}, "children": [{
                        "kind": "element", "name": "hl7:code", "min": 1,
                        "max": 1, "mandatory": True, "attributes": [],
                        "codes": [{"code": "FLN-13", "code_system": "1.2.3"}],
                        "fixed": {}, "targets": ["Contact.code"], "children": [],
                        "asserts": [], "lets": {},
                    }],
                }],
            }],
        }
        model = {"fields": {"contact": {"type": "boolean"}}}
        mapping_cfg = {"fields": {"contact": {
            "target": "Contact.observation", "mode": "presence",
        }}}
        true_record = {"key": "P1", "values": {"contact": True}, "instances": {}}
        false_record = {"key": "P2", "values": {"contact": False}, "instances": {}}
        true_xml, _ = cda.emit(true_record, model, compiled, mapping_cfg, {})
        false_xml, _ = cda.emit(false_record, model, compiled, mapping_cfg, {})
        true_root = ET.fromstring(true_xml)
        false_root = ET.fromstring(false_xml)
        self.assertEqual(len(true_root), 1)
        self.assertEqual(list(true_root)[0][0].get("code"), "FLN-13")
        self.assertEqual(len(false_root), 0)

    def test_compiler_infers_shared_section_entry_occurrences(self) -> None:
        model: dict[str, Any] = {
            "groups": {
                "therapy": {
                    "parent": None, "repeating": True, "min": 0, "max": None,
                },
                "therapy.medication": {
                    "parent": "therapy", "repeating": False, "min": 0, "max": 1,
                },
            },
            "fields": {
                "therapy.medication.code": {
                    "type": "code", "repeat_chain": ["therapy"],
                },
            },
        }
        cda_model: dict[str, Any] = {"targets": {
            "MedicationSection.section": {
                "path": "hl7:section", "renderable": True,
                "locations": ["0.0"], "repeatable": True,
                "repeat_ancestors": [], "min": 0, "max": None,
            },
            "MedicationSection.entry": {
                "path": "hl7:section/hl7:entry", "renderable": True,
                "locations": ["0.0.0"], "repeatable": True,
                "repeat_ancestors": ["0.0"], "min": 0, "max": None,
            },
            "MedicationStatement.substanceAdministration": {
                "path": "hl7:substanceAdministration", "renderable": True,
                "locations": ["0.0.0.0"], "repeatable": True,
                "repeat_ancestors": ["0.0", "0.0.0"], "min": 0, "max": 1,
            },
            "Medication.code": {
                "path": "hl7:substanceAdministration/hl7:code",
                "renderable": True, "locations": ["0.0.0.0.0"],
                "repeatable": True,
                "repeat_ancestors": ["0.0", "0.0.0"], "min": 0, "max": 1,
            },
        }}
        group_results = {
            "therapy": {
                "primary": {"target": "MedicationSection.section"},
            },
            "therapy.medication": {
                "primary": {"target": "MedicationStatement.substanceAdministration"},
            },
        }
        rules = mapping_compiler._for_each_rules(
            model, cda_model,
            {"therapy.medication.code": "Medication.code"}, group_results,
        )
        self.assertEqual(
            rules["for-each-therapy"]["target_repeat"],
            "MedicationSection.entry",
        )
        self.assertIn(
            "shared section container with occurrence-aligned entries",
            rules["for-each-therapy"]["evidence"],
        )
        candidate_target = {
            **cda_model["targets"]["Medication.code"],
            "writable": True,
            "logical_types": ["code", "ordinal"],
            "value_representation": {
                "kind": "coded", "logical_types": ["code", "ordinal"],
            },
            "fixed": {}, "codes": [],
        }
        self.assertEqual(
            mapping_compiler._direct(
                model["fields"]["therapy.medication.code"],
                candidate_target,
                cda=cda_model,
                occurrence_mapping={"structures": rules},
            ),
            (True, []),
        )
        self.assertEqual(
            mapping_compiler._for_each_rules(
                {
                    "groups": {"rows": {"repeating": True}},
                    "fields": {"rows.value": {"repeat_chain": ["rows"]}},
                },
                {"targets": {"Observation.value": {
                    "renderable": True, "locations": ["0.0"],
                    "repeatable": True, "repeat_ancestors": ["0"],
                }}},
                {"rows.value": "Observation.value"},
            ),
            {},
        )

    def test_group_name_mapping_selects_typed_structural_container(self) -> None:
        structural = {
            "kind": "element", "datatype": "POCD_MT000040.SubstanceAdministration",
            "path": "hl7:substanceAdministration", "renderable": True,
            "writable": False, "has_children": True,
        }
        writable = {
            "kind": "attribute", "datatype": None,
            "path": "hl7:substanceAdministration/hl7:text/hl7:reference/@value",
            "renderable": True, "writable": True, "has_children": False,
        }
        generated = {
            "kind": "element", "datatype": "POCD_MT000040.Participant2",
            "path": "hl7:substanceAdministration/hl7:participant",
            "renderable": True, "writable": False, "has_children": True,
            "datatype_derived": True,
        }
        selected = mapping_compiler._principal_target(
            "medication", {}, {"medication": [
                ("Medication.value", writable),
                ("Medication.participant", generated),
                ("Medication.substanceAdministration", structural),
            ]},
        )
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected[0], "Medication.substanceAdministration")

    def test_for_each_can_bind_source_repeat_below_shared_cda_container(self) -> None:
        code_target = {
            "kind": "element", "datatype": "CD",
            "path": "hl7:substanceAdministration/hl7:code",
            "renderable": True, "locations": ["0.0.0.0.0"],
            "repeatable": True, "repeat_ancestors": ["0.0", "0.0.0"],
            "min": 0, "max": 1, "fixed": {}, "value_sets": ["meds"],
        }
        compiled = {
            "targets": {
                "MedicationSection.entry": {
                    "kind": "element", "path": "hl7:section/hl7:entry",
                    "renderable": True, "locations": ["0.0.0"],
                    "repeatable": True, "repeat_ancestors": ["0.0"],
                    "min": 0, "max": None,
                },
                "Medication.code": code_target,
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument",
                "min": 1, "max": 1, "mandatory": True,
                "attributes": [], "codes": [], "fixed": {}, "targets": [],
                "children": [{
                    "kind": "element", "name": "hl7:section",
                    "min": 0, "max": None, "mandatory": False,
                    "attributes": [], "codes": [], "fixed": {}, "targets": [],
                    "children": [{
                        "kind": "element", "name": "hl7:entry",
                        "min": 0, "max": None, "mandatory": False,
                        "attributes": [], "codes": [], "fixed": {},
                        "targets": ["MedicationSection.entry"],
                        "children": [{
                            "kind": "element", "name": "hl7:substanceAdministration",
                            "min": 0, "max": 1, "mandatory": False,
                            "attributes": [], "codes": [], "fixed": {}, "targets": [],
                            "children": [{
                                "kind": "element", "name": "hl7:code", "datatype": "CD",
                                "min": 0, "max": 1, "mandatory": False,
                                "attributes": [], "codes": [], "fixed": {}, "children": [],
                                "targets": ["Medication.code"], "target": "Medication.code",
                            }],
                        }],
                    }],
                }],
            }],
        }
        model = {
            "groups": {"therapy": {"repeating": True}},
            "fields": {
                "therapy.medication.code": {
                    "type": "code", "repeat_chain": ["therapy"],
                    "value_sets": ["meds"],
                },
            },
        }
        mapping_cfg = {
            "fields": {"therapy.medication.code": "Medication.code"},
            "structures": {"for-each-therapy": {
                "type": "for_each", "source_group": "therapy",
                "target_repeat": "MedicationSection.entry",
            }},
        }
        record = {
            "key": "P1", "values": {},
            "instances": {"therapy": [
                {"values": {"therapy.medication.code": {
                    "code": "A", "codeSystem": "1.2.3",
                }}},
                {"values": {"therapy.medication.code": {
                    "code": "B", "codeSystem": "1.2.3",
                }}},
            ]},
        }
        complete_fixture_value_targets(compiled)
        assignments, problems = build_assignments(
            record, model, compiled, mapping_cfg, {}
        )
        self.assertEqual(
            [[value["code"] for value in assignments["Medication.code"][0]]],
            [["A", "B"]],
        )
        self.assertFalse(problems)
        self.assertEqual(
            validate.check_config(
                model, compiled,
                {"fields": {"therapy.medication.code": None}},
                mapping_cfg,
            ),
            [],
        )
        payload, problems = cda.emit(record, model, compiled, mapping_cfg, {})
        root = ET.fromstring(payload)
        sections = root.findall("{urn:hl7-org:v3}section")
        self.assertEqual(len(sections), 1)
        entries = sections[0].findall("{urn:hl7-org:v3}entry")
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            [
                find_required(
                    entry,
                    "{urn:hl7-org:v3}substanceAdministration/{urn:hl7-org:v3}code"
                ).get("code")
                for entry in entries
            ],
            ["A", "B"],
        )
        self.assertFalse(problems)

    def test_static_association_projects_common_rim_slot_and_open_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "project.xml"
            evidence.write_text('''<project>
  <templateAssociation templateId="active" effectiveDate="2026">
    <concept ref="drug" elementId="active-root"/>
  </templateAssociation>
  <template id="legacy" effectiveDate="2020" name="LegacyMaterial">
    <element name="hl7:manufacturedMaterial" id="legacy-root">
      <element name="hl7:code" id="legacy-code" datatype="CD">
        <vocabulary codeSystem="1.2.3.4"/>
      </element>
      <element name="hl7:name" id="legacy-name" datatype="EN"/>
    </element>
    <staticAssociations>
      <origconcept ref="drug-code" elementId="legacy-code"
          templateId="legacy" templateEffectiveDate="2020"/>
      <origconcept ref="drug-name" elementId="legacy-name"
          templateId="legacy" templateEffectiveDate="2020"/>
    </staticAssociations>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {"dataset_id": "ds", "transaction_id": "tx"},
                "groups": {
                    "drug": {
                        "name": "Drug", "concept": "drug", "parent": None,
                        "repeating": False, "repeat_chain": [],
                    },
                },
                "fields": {
                    "drug.code": {
                        "name": "Drug code", "concept": "drug-code",
                        "type": "code", "parent": "drug", "repeat_chain": [],
                        "value_sets": [], "codes": [],
                    },
                    "drug.name": {
                        "name": "Drug name", "concept": "drug-name",
                        "type": "text", "parent": "drug", "repeat_chain": [],
                        "value_sets": [], "codes": [],
                    },
                },
            }
            material_slot = {
                "source": "cda-rim", "datatype": "POCD_MT000040.Material",
            }
            compiled = {
                "document_template": {"name": "ActiveDocument"},
                "source_index": {},
                "assertions": [],
                "targets": {
                    "Active.material": {
                        "template_id": "active", "template_effective_date": "2026",
                        "element_id": "active-root", "kind": "element",
                        "path": "hl7:manufacturedMaterial", "renderable": True,
                        "writable": False, "locations": ["0"],
                        "repeat_ancestors": [], "has_children": True,
                    },
                    "Active.code": {
                        "template_id": "active", "kind": "element",
                        "path": "hl7:manufacturedMaterial/hl7:code",
                        "datatype": "CD", "renderable": True, "writable": True,
                        "locations": ["0.0"], "repeat_ancestors": [],
                        "value_representation": {
                            "kind": "coded", "logical_types": ["code", "ordinal"],
                            "attributes": ["code", "codeSystem", "displayName"],
                            "scalar_attribute": "code",
                        },
                        "logical_types": ["code", "ordinal"],
                        "fixed": {}, "codes": [], "has_children": False,
                        "provenance": [{
                            **material_slot, "datatype_part": "hl7:code",
                            "path": "hl7:manufacturedMaterial/hl7:code",
                        }],
                    },
                    "Active.name": {
                        "template_id": "active", "kind": "element",
                        "path": "hl7:manufacturedMaterial/hl7:name",
                        "datatype": "EN", "renderable": True, "writable": True,
                        "locations": ["0.1"], "repeat_ancestors": [],
                        "value_representation": {
                            "kind": "element_text", "logical_types": ["text"],
                        },
                        "logical_types": ["text"], "fixed": {}, "codes": [],
                        "has_children": True,
                        "provenance": [{
                            **material_slot, "datatype_part": "hl7:name",
                            "path": "hl7:manufacturedMaterial/hl7:name",
                        }],
                    },
                    "Legacy.code": {
                        "template_id": "legacy", "template_effective_date": "2020",
                        "element_id": "legacy-code", "kind": "element",
                        "path": "hl7:manufacturedMaterial/hl7:code",
                        "datatype": "CD", "renderable": False, "writable": False,
                        "locations": [], "provenance": [],
                    },
                    "Legacy.name": {
                        "template_id": "legacy", "template_effective_date": "2020",
                        "element_id": "legacy-name", "kind": "element",
                        "path": "hl7:manufacturedMaterial/hl7:name",
                        "datatype": "EN", "renderable": False, "writable": False,
                        "locations": [], "provenance": [],
                    },
                },
                "document": [{
                    "kind": "element", "name": "hl7:manufacturedMaterial",
                    "min": 1, "max": 1, "mandatory": True,
                    "attributes": [], "codes": [], "fixed": {},
                    "targets": ["Active.material"], "target": "Active.material",
                    "asserts": [], "lets": {}, "children": [
                        {
                            "kind": "element", "name": "hl7:code", "datatype": "CD",
                            "min": 0, "max": 1, "mandatory": False,
                            "attributes": [], "codes": [], "fixed": {},
                            "targets": ["Active.code"], "target": "Active.code",
                            "asserts": [], "lets": {}, "children": [],
                        },
                        {
                            "kind": "element", "name": "hl7:name", "datatype": "EN",
                            "min": 0, "max": 1, "mandatory": False,
                            "attributes": [], "codes": [], "fixed": {},
                            "targets": ["Active.name"], "target": "Active.name",
                            "asserts": [], "lets": {}, "children": [],
                        },
                    ],
                }],
            }
            proposal, report = cda_mapping_proposal(
                model, compiled, [evidence]
            )
            self.assertEqual(proposal["fields"]["drug.name"], "Active.name")
            self.assertEqual(proposal["fields"]["drug.code"], {
                "target": "Active.code",
                "transform": {
                    "type": "code_system", "code_system": "1.2.3.4",
                },
            })
            self.assertIn("STATIC_ASSOC", report)
            record = {
                "key": "P1", "values": {
                    "drug.name": "Example drug",
                    "drug.code": {"nullFlavor": "OTH", "raw": "01234567"},
                }, "instances": {},
            }
            payload, problems = cda.emit(record, model, compiled, proposal, {})
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            code = root.find("{urn:hl7-org:v3}code")
            name = root.find("{urn:hl7-org:v3}name")
            assert code is not None
            assert name is not None
            self.assertEqual(code.get("code"), "01234567")
            self.assertEqual(code.get("codeSystem"), "1.2.3.4")
            self.assertEqual(name.text, "Example drug")

    def test_static_association_outside_selected_occurrence_is_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "project.xml"
            evidence.write_text('''<project>
  <templateAssociation templateId="active" effectiveDate="2026">
    <concept ref="root" elementId="active-root"/>
  </templateAssociation>
  <templateAssociation templateId="legacy" effectiveDate="2020">
    <concept ref="unrelated-identifier" elementId="legacy-id"/>
  </templateAssociation>
  <concept id="insurance"><inherit ref="common-group"/></concept>
  <concept id="legacy-insurance"><inherit ref="common-group"/></concept>
  <concept id="identifier"><inherit ref="common-id"/></concept>
  <concept id="legacy-identifier"><inherit ref="common-id"/></concept>
  <template id="legacy" effectiveDate="2020" name="LegacyParticipant">
    <staticAssociations>
      <origconcept ref="legacy-insurance" elementId="legacy-container"
          templateId="legacy" templateEffectiveDate="2020"/>
      <origconcept ref="legacy-identifier" elementId="legacy-id"
          templateId="legacy" templateEffectiveDate="2020"/>
    </staticAssociations>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {"dataset_id": "ds", "transaction_id": "tx"},
                "groups": {
                    "root": {
                        "name": "Root", "concept": "root", "parent": None,
                        "repeating": False, "repeat_chain": [],
                    },
                    "root.insurance": {
                        "name": "Insurance", "concept": "insurance",
                        "parent": "root", "repeating": False,
                        "repeat_chain": [],
                    },
                },
                "fields": {
                    "root.insurance.identifier": {
                        "name": "Insurance identifier",
                        "short_name": "insurance_identifier",
                        "concept": "identifier", "type": "identifier",
                        "parent": "root.insurance", "repeat_chain": [],
                        "value_sets": [], "codes": [],
                    },
                },
            }
            common_root = {
                "kind": "element", "renderable": True, "writable": False,
                "repeat_ancestors": [], "has_children": True,
            }
            common_id = {
                "kind": "element", "datatype": "II", "renderable": True,
                "writable": True, "repeat_ancestors": [],
                "logical_types": ["identifier"], "value_representation": {
                    "kind": "identifier", "logical_types": ["identifier"],
                }, "schematron_constraints": [{"kind": "required"}],
            }
            cda_model = {
                "document_template": {"name": "Document"},
                "assertions": [], "unresolved_templates": [],
                "source_index": {
                    "active|ID:active-root": ["Active.root"],
                    "legacy|ID:legacy-container": ["Legacy.container"],
                    "legacy|ID:legacy-id": ["Legacy.identifier"],
                },
                "targets": {
                    "Active.root": {
                        **common_root, "template_id": "active",
                        "element_id": "active-root", "path": "hl7:participant",
                        "locations": ["0"],
                    },
                    "Active.identifier": {
                        **common_id, "template_id": "active",
                        "path": "hl7:participant/hl7:id", "locations": ["0.0"],
                    },
                    "Legacy.container": {
                        **common_root, "template_id": "legacy",
                        "element_id": "legacy-container",
                        "path": "hl7:participant", "locations": ["1"],
                    },
                    "Legacy.identifier": {
                        **common_id, "template_id": "legacy",
                        "element_id": "legacy-id",
                        "path": "hl7:participant/hl7:id", "locations": ["1.0"],
                    },
                },
            }
            proposal, audit, _, _ = mapping_compiler.cda_mapping_audit(
                model, cda_model, [evidence]
            )

            self.assertIsNone(
                proposal["fields"]["root.insurance.identifier"]
            )
            child = audit["groups"]["root.insurance"]
            self.assertIsNone(child["selected"])
            self.assertEqual(child["context"]["target"], "Active.root")
            candidate = audit["fields"][
                "root.insurance.identifier"
            ]["alternatives"][0]
            self.assertEqual(candidate["target"], "Legacy.identifier")
            self.assertFalse(candidate["actionable"])
            self.assertTrue(candidate["occurrence_mismatch"])
            self.assertIn(
                "outside the selected CDA occurrence",
                candidate["warnings"][0],
            )

    def test_template_association_does_not_revive_static_occurrence_mismatch(self) -> None:
        field = {
            "name": "Narrative", "concept": "source", "type": "text",
            "value_sets": [], "codes": [], "repeat_chain": [],
        }
        context_node = {
            "path": "hl7:section", "locations": ["0"],
        }
        target = {
            "template_id": "other", "template_effective_date": "2020",
            "element_id": "text", "kind": "element",
            "path": "hl7:section/hl7:text", "locations": ["1.0"],
            "datatype": "ST", "renderable": True, "writable": True,
            "repeat_ancestors": [], "logical_types": ["text"],
            "value_representation": {
                "kind": "element_text", "logical_types": ["text"],
            },
        }
        associations = [
            {
                "concept": "source", "template_id": "other",
                "effective_date": "2020", "element_id": "text",
                "kind": "templateAssociation", "code_systems": [],
            },
            {
                "concept": "source", "template_id": "other",
                "effective_date": "2020", "element_id": "text",
                "kind": "staticAssociation", "code_systems": [],
            },
        ]
        rows = mapping_compiler._ta_candidates(
            field, {}, associations, {}, {
                "source_index": {"other|ID:text": ["Other.text"]},
                "targets": {"Other.text": target},
            }, {"target": "Active.section", "node": context_node},
        )
        direct = next(row for row in rows if row["kind"] == "TA")
        static = next(row for row in rows if row["kind"] == "STATIC_ASSOC")
        self.assertTrue(direct["actionable"])
        self.assertFalse(static["actionable"])
        self.assertTrue(static["occurrence_mismatch"])

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
        cda_model: dict[str, object] = {"targets": targets}
        complete_fixture_value_targets(cda_model)
        assignments, _ = build_assignments(record, {"fields": fields}, cda_model, mapping_cfg, {})
        self.assertEqual([item["code"] for item in assignments["Diagnosis.certainty"]], ["A", "Z", "Z"])
        self.assertEqual(assignments["Diagnosis.negation"], [True, None, None])
        self.assertEqual(assignments["Diagnosis.high"][0], None)
        self.assertEqual(assignments["Diagnosis.high"][1], {"nullFlavor": "UNK"})
        self.assertEqual(assignments["Diagnosis.high"][2], "2026-08-28T12:00:00+02:00")

    def test_reviewed_fallback_fills_only_an_already_active_branch(self) -> None:
        compiled: dict[str, Any] = {
            "targets": {
                "AllergyConcern.low": {
                    "kind": "element", "datatype": "TS", "min": 1, "max": 1,
                    "mandatory": True, "has_children": False,
                    "renderable": True, "writable": True,
                    "locations": ["0.0.0.0.0"], "repeat_ancestors": [],
                    "logical_types": ["datetime", "date"],
                },
                "AllergyObservation.effectiveTime": {
                    "kind": "element", "datatype": "IVL_TS", "min": 1,
                    "max": 1, "mandatory": False, "conformance": "R",
                    "has_children": True, "template_id": "allergy-observation",
                    "template_effective_date": "2026",
                    "path": "hl7:observation/hl7:effectiveTime",
                    "renderable": True, "writable": True,
                    "locations": ["0.0.0.1.0.0"],
                    "repeat_ancestors": [],
                    "logical_types": ["datetime", "date"],
                    "value_representation": {
                        "kind": "timestamp",
                        "logical_types": ["datetime", "date"],
                        "attribute": "value",
                    },
                },
                "AllergyObservation.effectiveTime.nullFlavor": {
                    "kind": "attribute", "datatype": "CS", "min": 0,
                    "max": 1, "mandatory": False, "has_children": False,
                    "template_id": "allergy-observation",
                    "template_effective_date": "2026",
                    "path": "hl7:observation/hl7:effectiveTime/@nullFlavor",
                    "renderable": True, "writable": True,
                    "locations": ["0.0.0.1.0.0.100000"],
                    "repeat_ancestors": [], "logical_types": ["text"],
                },
                "AllergyObservation.value": {
                    "kind": "element", "datatype": "ST", "min": 1, "max": 1,
                    "mandatory": True, "has_children": False,
                    "renderable": True, "writable": True,
                    "locations": ["0.0.0.1.0.1"], "repeat_ancestors": [],
                    "logical_types": ["text"],
                },
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1,
                "max": 1, "mandatory": True, "attributes": [], "codes": [],
                "fixed": {"classCode": "DOCCLIN"}, "targets": [], "children": [{
                    "kind": "element", "name": "hl7:component", "min": 0,
                    "max": 1, "mandatory": False, "attributes": [], "codes": [],
                    "fixed": {}, "targets": [], "children": [{
                        "kind": "element", "name": "hl7:act", "min": 1,
                        "max": 1, "mandatory": True, "attributes": [], "codes": [],
                        "fixed": {"classCode": "ACT"}, "targets": [], "children": [{
                            "kind": "element", "name": "hl7:effectiveTime", "min": 1,
                            "max": 1, "mandatory": True, "attributes": [], "codes": [],
                            "fixed": {}, "targets": [], "children": [{
                                "kind": "element", "name": "hl7:low", "datatype": "TS",
                                "min": 1, "max": 1, "mandatory": True,
                                "attributes": [], "codes": [], "fixed": {},
                                "targets": ["AllergyConcern.low"], "children": [],
                            }],
                        }, {
                            "kind": "element", "name": "hl7:entryRelationship", "min": 0,
                            "max": 1, "mandatory": False, "attributes": [], "codes": [],
                            "fixed": {}, "targets": [], "children": [{
                                "kind": "element", "name": "hl7:observation", "min": 1,
                                "max": 1, "mandatory": True, "attributes": [], "codes": [],
                                "fixed": {"classCode": "OBS"}, "targets": [], "children": [{
                                    "kind": "element", "name": "hl7:effectiveTime",
                                    "datatype": "IVL_TS", "min": 1, "max": 1,
                                    "mandatory": False, "conformance": "R",
                                    "attributes": [{
                                        "name": "nullFlavor", "optional": True,
                                        "targets": [],
                                    }],
                                    "codes": [], "fixed": {},
                                    "targets": ["AllergyObservation.effectiveTime"],
                                    "children": [],
                                }, {
                                    "kind": "element", "name": "hl7:value", "datatype": "ST",
                                    "min": 1, "max": 1, "mandatory": True,
                                    "attributes": [], "codes": [], "fixed": {},
                                    "targets": ["AllergyObservation.value"], "children": [],
                                }],
                            }],
                        }],
                    }],
                }],
            }],
        }
        complete_fixture_value_targets(compiled)
        model = {"fields": {
            "encounter.admission": {"type": "datetime", "repeat_chain": []},
            "allergy.agent": {"type": "text", "repeat_chain": []},
        }}
        mapping = {
            "version": 7,
            "fields": {
                "encounter.admission": {
                    "target": "AllergyConcern.low",
                    "mode": "fallback_if_active",
                    "reason": "Use the reviewed ED admission time as concern start.",
                },
                "allergy.agent": "AllergyObservation.value",
            },
            "defaults": {"required_unmapped": {"nullFlavor": "NI"}},
            "target_defaults": {
                "AllergyObservation.effectiveTime": {
                    "nullFlavor": "UNK",
                    "reason": "The allergy onset is unknown.",
                },
            },
        }
        errors = validate.check_config(
            model, compiled,
            {"fields": {"encounter.admission": None, "allergy.agent": None}},
            mapping,
        )
        self.assertEqual(errors, [])

        admission = "2026-09-09T10:15:00+02:00"
        empty, problems = cda.emit(
            {"key": "P1", "values": {"encounter.admission": admission}},
            model, compiled, mapping, {},
        )
        self.assertEqual(problems, [])
        self.assertIsNone(ET.fromstring(empty).find("{urn:hl7-org:v3}component"))

        payload, problems = cda.emit(
            {"key": "P1", "values": {
                "encounter.admission": admission, "allergy.agent": "Penicillin",
            }},
            model, compiled, mapping, {},
        )
        self.assertEqual(problems, [])
        root = ET.fromstring(payload)
        low = find_required(
            root,
            "{urn:hl7-org:v3}component/{urn:hl7-org:v3}act/"
            "{urn:hl7-org:v3}effectiveTime/{urn:hl7-org:v3}low",
        )
        self.assertEqual(low.get("value"), "20260909101500+0200")
        onset = find_required(
            root,
            "{urn:hl7-org:v3}component/{urn:hl7-org:v3}act/"
            "{urn:hl7-org:v3}entryRelationship/{urn:hl7-org:v3}observation/"
            "{urn:hl7-org:v3}effectiveTime",
        )
        self.assertEqual(onset.get("nullFlavor"), "UNK")

        with self.assertRaisesRegex(ValueError, "mandatory CDA element"):
            cda.emit(
                {"key": "P1", "values": {"allergy.agent": "Penicillin"}},
                model, compiled, mapping, {},
            )

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
                "Diagnosis.moodCode": {
                    **target("0.0.100000", "cs"),
                    "kind": "attribute", "mandatory": True,
                    "path": "hl7:observation/@moodCode",
                },
                "Diagnosis.statusCode": {
                    **target("0.0.4", "CS"),
                    "mandatory": True, "has_children": True,
                    "path": "hl7:observation/hl7:statusCode",
                },
                "Diagnosis.negationInd": {
                    **target("0.0.100001", "bl"),
                    "kind": "attribute", "mandatory": True,
                    "path": "hl7:observation/@negationInd",
                },
                "Unused.statusCode": {
                    **target("0.1.0", "CS"),
                    "mandatory": True, "has_children": True,
                    "repeat_ancestors": [],
                    "path": "hl7:act/hl7:statusCode",
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
                    "max": None, "mandatory": False, "attributes": [{
                        "kind": "attribute", "name": "moodCode", "datatype": "cs",
                        "optional": False, "value": None,
                        "targets": ["Diagnosis.moodCode"],
                    }, {
                        "kind": "attribute", "name": "negationInd", "datatype": "bl",
                        "optional": False, "value": None,
                        "targets": ["Diagnosis.negationInd"],
                    }], "codes": [],
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
                        {"kind": "element", "name": "hl7:statusCode", "datatype": "CS",
                         "min": 1, "max": 1, "mandatory": True, "attributes": [],
                         "codes": [], "fixed": {}, "children": [],
                         "targets": ["Diagnosis.statusCode"],
                         "target": "Diagnosis.statusCode"},
                    ],
                }, {
                    "kind": "element", "name": "hl7:act", "min": 0,
                    "max": 1, "mandatory": False, "attributes": [], "codes": [],
                    "fixed": {}, "targets": [], "children": [{
                        "kind": "element", "name": "hl7:statusCode", "datatype": "CS",
                        "min": 1, "max": 1, "mandatory": True, "attributes": [],
                        "codes": [], "fixed": {}, "children": [],
                        "targets": ["Unused.statusCode"],
                        "target": "Unused.statusCode",
                    }],
                }],
            }],
        }
        model = {"fields": {
            "diagnoses.value": {"type": "text", "repeat_chain": ["diagnoses"]},
            "diagnoses.onset": {"type": "datetime", "repeat_chain": ["diagnoses"]},
            "diagnoses.note": {"type": "text", "repeat_chain": ["diagnoses"]},
            "diagnoses.mood": {"type": "text", "repeat_chain": ["diagnoses"]},
        }}
        mapping = {
            "version": 5,
            "fields": {
                "diagnoses.value": "Diagnosis.value",
                "diagnoses.onset": "Diagnosis.low",
                "diagnoses.note": None,
                "diagnoses.mood": "Diagnosis.moodCode",
            },
            "defaults": {"required_unmapped": {"nullFlavor": "NI"}},
            "target_defaults": {
                "Diagnosis.low": {
                    "nullFlavor": "UNK",
                    "reason": "No diagnosis-onset datapoint is available.",
                },
                "Diagnosis.moodCode": {
                    "value": "EVN",
                    "reason": "Absent per-occurrence mood uses the reviewed event policy.",
                },
                "Diagnosis.statusCode": {
                    "value": "active",
                    "reason": "Every active observation uses the reviewed lifecycle policy.",
                },
                "Diagnosis.negationInd": {
                    "value": False,
                    "reason": "Exercise canonical boolean attribute rendering.",
                },
                "Unused.statusCode": {
                    "value": "active",
                    "reason": "A default must not activate this unused optional branch.",
                },
            },
        }
        record = {"key": "P1", "values": {}, "instances": {"diagnoses": [
            {"values": {
                "diagnoses.value": "A",
                "diagnoses.onset": "2026-01-01",
                "diagnoses.mood": "INT",
            }},
            {"values": {"diagnoses.value": "B"}},
        ]}}
        complete_fixture_value_targets(compiled)
        errors = validate.check_config(
            model, compiled,
            {"fields": {
                "diagnoses.value": None,
                "diagnoses.onset": None,
                "diagnoses.note": None,
                "diagnoses.mood": None,
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
        self.assertEqual(observations[0].get("moodCode"), "INT")
        self.assertEqual(observations[1].get("moodCode"), "EVN")
        self.assertEqual(observations[0].get("negationInd"), "false")
        self.assertEqual(observations[1].get("negationInd"), "false")
        self.assertEqual(observations[0][1].get("value"), "20260101")
        self.assertEqual(observations[1][1].get("nullFlavor"), "UNK")
        self.assertEqual(observations[0][2].get("nullFlavor"), "NI")
        self.assertEqual(observations[1][2].get("nullFlavor"), "NI")
        self.assertEqual(observations[0][3].get("code"), "active")
        self.assertEqual(observations[1][3].get("code"), "active")
        self.assertEqual(len(observations[0]), 4)
        self.assertEqual(len(observations[1]), 4)
        self.assertEqual(ET.fromstring(payload).find("{urn:hl7-org:v3}act"), None)

        accepted = render_accepted_cda_mappings_markdown(
            model, compiled, mapping
        )
        report = render_cda_mapping_markdown(
            model, compiled, mapping,
            {"summary": {"field_coverage": {"NO": 0}}},
        )
        self.assertIn("## Accepted required-CDA completion", accepted)
        self.assertIn('nullFlavor="NI"', accepted)
        self.assertIn('nullFlavor="UNK"', accepted)
        self.assertIn('value="EVN"', accepted)
        self.assertIn('value="active"', accepted)
        self.assertIn("No diagnosis-onset datapoint is available", accepted)
        self.assertIn("## Decisions", report)
        self.assertIn("`diagnoses.note`", report)
        self.assertIn("explicit `null` entry in `cda-mapping.json`", report)

    def test_target_default_validation_rejects_unsafe_scalar_values(self) -> None:
        def target(kind: str, logical_types: list[str]) -> dict[str, object]:
            return {
                "kind": "element", "datatype": "ST", "min": 1, "max": 1,
                "mandatory": True, "has_children": False, "conformance": "M",
                "renderable": True, "writable": True, "locations": ["0.0"],
                "fixed": {}, "logical_types": logical_types,
                "value_representation": {"kind": kind},
            }

        compiled = {"targets": {
            "Boolean.value": target("boolean", ["boolean"]),
            "Coded.value": {
                **target("coded", ["code"]),
                "codes": [{"code": "active"}],
            },
            "Compound.value": {
                **target("timestamp", ["datetime"]),
                "non_null_requires": ["Compound.event"],
            },
        }}
        mapping = {"fields": {}, "target_defaults": {
            "Boolean.value": {"value": "true", "reason": "Wrong JSON type."},
            "Coded.value": {"value": "completed"},
            "Compound.value": {"value": "20260907", "reason": "Incomplete compound."},
        }}
        errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, mapping
        )
        self.assertTrue(any("Boolean.value" in error and "must be boolean" in error for error in errors))
        self.assertTrue(any("Coded.value" in error and "reason must be non-empty" in error for error in errors))
        self.assertTrue(any("Coded.value" in error and "compiled code constraint" in error for error in errors))
        self.assertTrue(any("Compound.value" in error and "compound non-null companions" in error for error in errors))

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

    def test_mapping_target_identity_migrates_unique_owner_slot(self) -> None:
        owner = "1.2.3|ID:slot-7|PATH:hl7:observation/hl7:value"
        current = {
            "version": 7,
            "fields": {"finding": {
                "target": "OldFinding.value", "cda_target": "OldFinding.value",
            }},
            "target_identities": {"OldFinding.value": {
                "cda_target": "OldFinding.value",
                "revisionless_source_key": owner,
            }},
        }
        proposed = {"target_identities": {"NewFinding.value": {
            "cda_target": "NewFinding.value",
            "revisionless_source_key": owner,
        }}}
        compiled = {"targets": {"NewFinding.value": {
            "template_id": "1.2.3", "template_effective_date": "2027-01-01",
            "element_id": "slot-7", "path": "hl7:observation/hl7:value",
            "source_key": "1.2.3@2027-01-01|ID:slot-7|PATH:hl7:observation/hl7:value",
        }}}

        changed = mapping_compiler.migrate_mapping_target_identities(
            current, proposed, compiled
        )

        self.assertEqual(changed, 1)
        self.assertEqual(current["version"], 8)
        self.assertEqual(current["fields"]["finding"], {
            "target": "NewFinding.value", "cda_target": "NewFinding.value",
        })
        self.assertEqual(
            current["target_identities"]["NewFinding.value"]
            ["revisionless_source_key"], owner,
        )

    def test_mapping_target_identity_does_not_guess_ambiguous_slot(self) -> None:
        owner = "1.2.3|ID:slot-7|PATH:hl7:observation/hl7:value"
        current = {
            "fields": {"finding": "OldFinding.value"},
            "target_identities": {"OldFinding.value": {
                "revisionless_source_key": owner,
            }},
        }
        compiled = {"targets": {
            name: {
                "template_id": "1.2.3", "element_id": "slot-7",
                "path": "hl7:observation/hl7:value",
            }
            for name in ("Finding.value_as_CD", "Finding.value_as_ST")
        }}

        changed = mapping_compiler.migrate_mapping_target_identities(
            current, {"target_identities": {}}, compiled
        )

        self.assertEqual(changed, 0)
        self.assertEqual(current["fields"]["finding"], "OldFinding.value")
        self.assertEqual(
            current["target_identities"]["OldFinding.value"]
            ["revisionless_source_key"], owner,
        )

    def test_coded_target_default_inherits_unique_compiled_coding(self) -> None:
        target = {
            "kind": "element", "datatype": "CE", "min": 1, "max": 1,
            "mandatory": True, "has_children": True, "conformance": "M",
            "renderable": True, "writable": True, "locations": ["0.0"],
            "fixed": {}, "logical_types": ["code"],
            "value_representation": {
                "kind": "coded",
                "attributes": ["code", "codeSystem", "displayName"],
                "scalar_attribute": "code",
            },
            "codes": [{
                "code": "29308-4",
                "code_system": "2.16.840.1.113883.6.1",
                "display_name": "Diagnosis",
            }, {
                "code": "75324-4",
                "code_system": "2.16.840.1.113883.6.1",
            }],
        }
        compiled = {"targets": {"Diagnosis.code": target}}
        mapping = {"fields": {}, "target_defaults": {
            "Diagnosis.code": {
                "value": "29308-4",
                "reason": "The template prefers this statement-kind code.",
            },
        }}

        self.assertEqual(target_default_values(compiled, mapping), {
            "Diagnosis.code": {
                "code": "29308-4",
                "codeSystem": "2.16.840.1.113883.6.1",
                "displayName": "Diagnosis",
            },
        })

    def test_coded_target_default_rejects_ambiguous_companions(self) -> None:
        compiled = {"targets": {"Diagnosis.code": {
            "kind": "element", "datatype": "CE", "min": 1, "max": 1,
            "mandatory": True, "has_children": True, "conformance": "M",
            "renderable": True, "writable": True, "locations": ["0.0"],
            "fixed": {}, "logical_types": ["code"],
            "value_representation": {
                "kind": "coded", "attributes": ["code", "codeSystem"],
                "scalar_attribute": "code",
            },
            "codes": [
                {"code": "same", "code_system": "1.2.3"},
                {"code": "same", "code_system": "4.5.6"},
            ],
        }}}
        mapping = {"fields": {}, "target_defaults": {
            "Diagnosis.code": {
                "value": "same", "reason": "Intentionally ambiguous.",
            },
        }}

        errors = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, mapping
        )
        self.assertTrue(any(
            "Diagnosis.code" in error and "ambiguous compiled coding companions" in error
            for error in errors
        ))

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
                "Drug.value": {
                    "renderable": True, "locations": ["0.0.0"],
                    "repeat_ancestors": ["0.0"],
                },
                "Route.value": {
                    "renderable": True, "locations": ["0.0.1"],
                    "repeat_ancestors": ["0.0"],
                },
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
        complete_fixture_value_targets(compiled)
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
            manifest: dict[str, Any] = {"resources": {}}
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

    def test_exact_request_reuses_matching_frozen_dynamic_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "detail_resource.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="detail" effectiveDate="2025" '
                'name="Detail"><element name="hl7:observation"/></template></return>',
                encoding="utf-8",
            )
            payload = target.read_bytes()
            manifest: dict[str, Any] = {"resources": {
                "template:detail": {
                    "status": "ok",
                    "file": "templates/detail_resource.xml",
                    "project": "profile-",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "requested_effective_date": "dynamic",
                    "resolved_effective_date": "2025",
                    "representations": {
                        "analysis": {
                            "status": "ok",
                            "file": "templates/detail_resource.xml",
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        },
                    },
                    "identity": {
                        "type": "template", "id": "detail",
                        "effective_date": "2025", "project": "profile-",
                    },
                },
            }}
            want = {
                "kind": "template", "id": "detail",
                "effective_date": "2025", "project": "profile-",
            }
            with patch("decor2hl7.retrieval.fetch.get") as mocked:
                path = _fetch_want(
                    release_dir, manifest, want, owners={},
                    repositories=["profile-"], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True,
                )
            self.assertEqual(path, target)
            self.assertEqual(mocked.call_count, 0)
            exact = manifest["resources"]["template:detail@2025"]
            self.assertEqual(exact["status"], "ok")
            self.assertEqual(exact["file"], "templates/detail_resource.xml")
            self.assertEqual(exact["resolved_effective_date"], "2025")

    def test_referenced_codesystem_cache_is_adopted_offline(self) -> None:
        """A cached reference declaration is a cache hit for its own identity.

        A code system a project references rather than defines is published with
        its identity on `ref`, and its analysis form is a project envelope
        carrying no revision. Offline adoption must recognise it instead of
        reporting the cached file as missing, and must recover the revision from
        the cached source form the way a download does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            analysis = release_dir / "codesystems" / "cs_resource.xml"
            analysis.parent.mkdir(parents=True)
            analysis.write_text('<codeSystems><project ident="hl7de-"><codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" displayName="Snomed-CT" language="de-DE"/></project></codeSystems>', encoding="utf-8")
            source = release_dir / "codesystems" / "cs_resource.source.xml"
            source.write_text('<codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" external="true" effectiveDate="2025-04-30T00:00:00" ident="hl7de-"><issueAssociation count="0"/></codeSystem>', encoding="utf-8")
            key = "codesystem:2.16.840.1.113883.6.96"
            manifest: dict[str, Any] = {"resources": {key: {
                "status": "ok",
                "file": "codesystems/cs_resource.xml",
                "project": "hl7de-",
                "requested_effective_date": "dynamic",
                "resolved_effective_date": "",
                "representations": {
                    "analysis": {
                        "status": "ok", "file": "codesystems/cs_resource.xml",
                    },
                    "source": {
                        "status": "ok",
                        "file": "codesystems/cs_resource.source.xml",
                    },
                },
            }}}
            want = {
                "kind": "codesystem", "id": "2.16.840.1.113883.6.96",
                "effective_date": "", "project": "hl7de-",
            }
            with patch("decor2hl7.retrieval.fetch.get") as mocked:
                _fetch_want(
                    release_dir, manifest, want, owners={},
                    repositories=["hl7de-"], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True,
                )
            self.assertEqual(mocked.call_count, 0)
            entry = manifest["resources"][key]
            self.assertEqual(entry["status"], "ok")
            self.assertEqual(
                entry["resolved_effective_date"], "2025-04-30T00:00:00"
            )
            self.assertEqual(
                entry["identity"]["effective_date"], "2025-04-30T00:00:00"
            )

    def test_reference_declaration_cannot_satisfy_another_revision(self) -> None:
        """`ref` proves identity, never a revision the payload does not carry."""
        envelope = '<codeSystems><project ident="hl7de-"><codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" displayName="Snomed-CT" language="de-DE"/></project></codeSystems>'.encode()
        dynamic = {
            "kind": "codesystem", "id": "2.16.840.1.113883.6.96",
            "effective_date": "",
        }
        self.assertTrue(_payload_matches_request(envelope, dynamic))
        self.assertFalse(_payload_matches_request(
            envelope, {**dynamic, "effective_date": "2025-04-30T00:00:00"}
        ))
        dated = '<codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" external="true" effectiveDate="2025-04-30T00:00:00" ident="hl7de-"><issueAssociation count="0"/></codeSystem>'.encode()
        self.assertTrue(_payload_matches_request(
            dated, {**dynamic, "effective_date": "2025-04-30T00:00:00"}
        ))
        self.assertFalse(_payload_matches_request(
            dated, {**dynamic, "effective_date": "2011-01-01T00:00:00"}
        ))
        self.assertFalse(_payload_matches_request(
            envelope, {**dynamic, "id": "2.16.840.1.113883.6.1"}
        ))
        self.assertEqual(
            _resolved_effective_date(dated, dynamic), "2025-04-30T00:00:00"
        )

    def test_fetch_want_redownloads_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "1.2.3_2025-05-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="1.2.3" effectiveDate="2025-05-01" name="Changed"/></return>',
                encoding="utf-8",
            )
            manifest: dict[str, Any] = {"resources": {
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
            manifest: dict[str, Any] = {"resources": {}}
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
          <template id="doc">
            <relationship type="SPEC" template="prototype" flexibility="2019"/>
            <relationship type="VERSION" template="old-template" flexibility="2018"/>
          </template>
        </dataset>''')
        hard = hard_references(root)
        soft = soft_references(root)
        self.assertEqual({row["id"] for row in hard if row["kind"] == "dataset"}, {"external-dataset"})
        self.assertNotIn("old-dataset", {row["id"] for row in hard})
        self.assertEqual(
            {row["id"] for row in soft if row["kind"] == "concept"},
            {"old-concept", "external-root"},
        )
        self.assertEqual(
            {
                (row["id"], row["role"])
                for row in soft if row["kind"] == "template"
            },
            {
                ("prototype", "template-prototype"),
                ("old-template", "mapping-evidence"),
            },
        )
        self.assertNotIn(
            "prototype", {row["id"] for row in hard if row["kind"] == "template"}
        )

    def test_dynamic_request_is_not_satisfied_by_arbitrary_frozen_embed(self) -> None:
        inventory = {
            ("valueset", "1.2.3", "2015-01-01"),
            ("template", "4.5.6", ""),
        }
        self.assertFalse(_satisfied(
            {"kind": "valueset", "id": "1.2.3", "effective_date": ""},
            inventory,
        ))
        self.assertTrue(_satisfied(
            {
                "kind": "valueset", "id": "1.2.3",
                "effective_date": "2015-01-01",
            },
            inventory,
        ))
        self.assertTrue(_satisfied(
            {"kind": "template", "id": "4.5.6", "effective_date": ""},
            inventory,
        ))

    def test_association_endpoints_and_formal_origins_are_typed(self) -> None:
        root = ET.fromstring('''<project>
          <concept id="child">
            <inherit ref="parent" effectiveDate="2020" prefix="base-"
              originalId="original" originalEffectiveDate="2019"
              originalPrefix="original-"/>
            <relationship type="SPEC" ref="spec" flexibility="2018"
              prefix="base-"/>
            <relationship type="ADAPT" ref="adapted" flexibility="2017"
              prefix="weak-"/>
          </concept>
          <concept id="contained-child">
            <contains ref="contained-parent" flexibility="2021"
              prefix="base-" originalId="contained-original"
              originalEffectiveDate="2019"
              originalPrefix="original-"/>
          </concept>
          <templateAssociation templateId="active" effectiveDate="2026">
            <concept ref="dynamic-endpoint" effectiveDate="2025"
              elementId="active-element" prefix="source-"/>
          </templateAssociation>
          <template id="legacy" effectiveDate="2020" name="Legacy">
            <staticAssociations>
              <origconcept ref="static-endpoint" effectiveDate="2016"
                ident="external-" datasetId="dataset"
                datasetEffectiveDate="2015" elementId="legacy-element"/>
              <origconcept ref="second-static-endpoint" effectiveDate="2016"
                ident="external-" datasetId="dataset"
                datasetEffectiveDate="2015" elementId="second-legacy-element"/>
              <origconcept ref="bare-static-endpoint" effectiveDate="2014"
                ident="bare-" elementId="other-legacy-element"/>
            </staticAssociations>
          </template>
        </project>''')
        soft = soft_references(root)
        self.assertEqual(
            {
                (row["id"], row["effective_date"], row["project"], row["role"])
                for row in soft if row["kind"] == "concept"
            },
            {
                ("parent", "2020", "base-", "mapping-evidence"),
                ("original", "2019", "original-", "mapping-evidence"),
                ("spec", "2018", "base-", "mapping-evidence"),
                ("adapted", "2017", "weak-", "mapping-evidence"),
                ("contained-parent", "2021", "base-", "mapping-evidence"),
                ("contained-original", "2019", "original-", "mapping-evidence"),
                ("dynamic-endpoint", "2025", "source-", "association-endpoint"),
                ("static-endpoint", "2016", "external-", "association-endpoint"),
                ("second-static-endpoint", "2016", "external-", "association-endpoint"),
                ("bare-static-endpoint", "2014", "bare-", "association-endpoint"),
            },
        )
        self.assertEqual(
            {
                (
                    row["id"], row.get("dataset"),
                    row.get("dataset_effective_date"),
                )
                for row in soft if row.get("dataset") == "dataset"
            },
            {
                ("static-endpoint", "dataset", "2015"),
                ("second-static-endpoint", "dataset", "2015"),
            },
        )
        self.assertEqual(
            {
                (row["id"], row["effective_date"], row["role"])
                for row in original_references(root)
            },
            {
                ("parent", "2020", "formal-origin"),
                ("original", "2019", "formal-origin"),
                ("contained-parent", "2021", "formal-origin"),
                ("contained-original", "2019", "formal-origin"),
            },
        )
        self.assertTrue(all(
            row.get("analysis_only")
            for row in soft
            if row.get("role") == "association-endpoint"
        ))
        self.assertTrue(all(
            row.get("analysis_only") for row in original_references(root)
        ))

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

    def test_configured_owner_precedes_probe_but_not_project_directory(self) -> None:
        want = {
            "kind": "template", "id": "1.2.3.4",
            "effective_date": "", "project": "",
        }
        self.assertEqual(
            _candidate_projects(
                want, {}, ["aktin-", "configured-"], None,
                {"1.2.3": "configured-"},
            ),
            ["configured-", "aktin-"],
        )
        self.assertEqual(
            _candidate_projects(
                want, {"1.2": "directory-"}, ["aktin-"], None,
                {"1.2.3": "configured-"},
            ),
            ["directory-"],
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
            self.assertIn(analysis, inputs["terminology_resources"])
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

    def test_validator_value_sets_follow_the_selected_document_closure(self) -> None:
        """A rule skipped on a branch this document never uses is not degrading.

        The publication transform emits rules for every template the assembled
        specification reaches. Only a rule whose context template is actually
        instantiated in the selected document can affect this build
        (`DEC-010`, `DEC-019`).
        """
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            conformance = model_dir / "conformance-validation"
            conformance.mkdir()
            (conformance / "validator-manifest.json").write_text(
                '{"version": 2, "generation_messages": ["in", "out"], "generation_message_scopes": [{"message": "in", "severity": "error", "value_sets": ["selected-vs"], "context_templates": ["located-template"], "in_selected_closure": true}, {"message": "out", "severity": "error", "value_sets": ["inactive-vs"], "context_templates": ["unlocated-template"], "in_selected_closure": false}]}', encoding="utf-8"
            )
            inputs = {
                "terminology_resources": [],
                "build_artifacts": [],
                "unavailable_artifacts": [
                    {
                        "request_key": "valueset:selected-vs",
                        "type": "valueset", "id": "selected-vs",
                        "status": "missing", "roles": ["formal-terminology"],
                        "reasons": [],
                    },
                    {
                        "request_key": "valueset:inactive-vs",
                        "type": "valueset", "id": "inactive-vs",
                        "status": "missing", "roles": ["formal-terminology"],
                        "reasons": [],
                    },
                ],
            }
            result = write_build_diagnostics(
                model_dir, inputs, {"unresolved_templates": []}, {"fields": {}}
            )
            self.assertEqual(result["summary"]["crawl_degraded"], 2)
            self.assertEqual(
                [item["request_key"] for item in result["build_degraded"]],
                ["valueset:selected-vs"],
            )

    def test_selected_closure_templates_require_a_document_location(self) -> None:
        cda_model = {"targets": {
            "Located.value": {
                "template_id": "located",
                "template_effective_date": "2026-01-02T00:00:00",
                "locations": ["0.1"],
            },
            "Reachable.value": {
                "template_id": "unlocated",
                "template_effective_date": "2025-01-02T00:00:00",
                "locations": [],
            },
        }}
        self.assertEqual(selected_closure_templates(cda_model), {"located"})
        self.assertEqual(
            selected_closure_template_revisions(cda_model),
            {("located", "2026-01-02T00:00:00")},
        )

    def test_declared_endpoint_parity_accepts_only_fixed_structural_folds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text(
                """<templates><template id="t" name="T" effectiveDate="2026">
                <element id="root" name="hl7:observation">
                  <attribute id="folded" name="classCode" value="PSN"/>
                  <attribute id="missing" name="extension"/>
                </element>
                </template></templates>""",
                encoding="utf-8",
            )
            cda_model = {"targets": {
                "T.root": {
                    "template_id": "t", "element_id": "root",
                    "locations": ["0"],
                },
                "T.extension": {
                    "template_id": "t",
                    "element_id": "decor2hl7-extension:x",
                    "locations": ["0.1"],
                },
            }, "document": [{
                "kind": "template", "template_id": "t", "children": [{
                    "kind": "element", "fixed": {"classCode": "PSN"},
                    "children": [],
                }],
            }]}
            parity = declared_endpoint_parity([source], cda_model, {"t"})
            self.assertEqual(parity["declared"], 3)
            self.assertEqual(parity["compiled"], 2)
            self.assertEqual(
                [item["element_id"] for item in parity["fixed_structural_attributes"]],
                ["folded"],
            )
            self.assertEqual(
                [item["element_id"] for item in parity["unexpected_missing"]],
                ["missing"],
            )
            self.assertEqual(parity["reviewed_branch_replacements"], [])
            self.assertEqual(
                [item["element_id"] for item in parity["compiler_only"]],
                ["decor2hl7-extension:x"],
            )

    def test_declared_endpoint_parity_accepts_reviewed_spec_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text(
                """<templates><template id="parent" name="Parent" effectiveDate="2026">
                <element id="host" name="hl7:consumable" contains="simple"
                         flexibility="2025"/>
                </template></templates>""",
                encoding="utf-8",
            )
            cda_model = {
                "targets": {},
                "reviewed_extensions": [{
                    "operation": "select_spec_branch",
                    "parent_template_id": "parent",
                    "parent_template_effective_date": "2026",
                    "parent_element_id": "host",
                    "element_name": "hl7:consumable",
                    "template_id": "detail",
                    "replaces_template_id": "simple",
                    "replaces_template_effective_date": "2025",
                }],
            }
            parity = declared_endpoint_parity(
                [source], cda_model, {"parent"}
            )
            self.assertEqual(parity["unexpected_missing"], [])
            self.assertEqual(
                [
                    item["element_id"]
                    for item in parity["reviewed_branch_replacements"]
                ],
                ["host"],
            )

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
                               minimumMultiplicity="1" maximumMultiplicity="1">
                        <vocabulary valueSet="status-vs"/>
                      </element>
                      <element name="hl7:participant" id="participant"
                               minimumMultiplicity="1" maximumMultiplicity="1">
                        <element name="hl7:playingEntity" id="entity"
                                 minimumMultiplicity="1" maximumMultiplicity="1">
                          <element name="hl7:code" id="agent-code" datatype="CE"
                                   minimumMultiplicity="1" maximumMultiplicity="1">
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
            proposal, report = cda_mapping_proposal(model, compiled, [project])
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
            ambiguous = {**compiled, "targets": dict(compiled["targets"])}
            duplicate = {
                **compiled["targets"][target_name],
                "path": "hl7:ClinicalDocument/hl7:section/hl7:other/hl7:code",
                "locations": ["0.0.999.0"],
            }
            duplicate_text = {
                **compiled["targets"][original_text_name],
                "path": duplicate["path"] + "/hl7:originalText",
                "locations": ["0.0.999.0.0"],
            }
            ambiguous["targets"]["Alternative.code"] = duplicate
            ambiguous["targets"]["Alternative.code.originalText"] = duplicate_text
            ambiguous_proposal, _ = cda_mapping_proposal(
                model, ambiguous, [project]
            )
            self.assertIsNone(ambiguous_proposal["fields"]["allergies.agent"])

    def test_neutral_examples_derive_and_coalesce_boolean_discriminators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "allergy.xml"
            source.write_text('''<project>
              <template id="allergy" effectiveDate="2026" name="Allergy">
                <example type="neutral" caption="Antibiotic allergy known">
                  <observation>
                    <participant><participantRole><playingEntity>
                      <code code="ANTIBIOTIC" codeSystem="9.8.7"/>
                    </playingEntity></participantRole></participant>
                  </observation>
                </example>
                <example type="neutral" caption="No contrast allergy known">
                  <observation negationInd="true">
                    <participant><participantRole><playingEntity>
                      <code code="CONTRAST" codeSystem="9.8.7"/>
                    </playingEntity></participantRole></participant>
                  </observation>
                </example>
              </template>
              <valueSet id="allergen-vs" effectiveDate="2025"><conceptList>
                <concept code="ANTIBIOTIC" codeSystem="9.8.7"
                         displayName="Antibiotic"/>
                <concept code="CONTRAST" codeSystem="9.8.7"
                         displayName="Contrast medium"/>
              </conceptList></valueSet>
            </project>''', encoding="utf-8")
            agent = "allergies.agent"
            antibiotic = "allergies.antibiotic_allergy"
            contrast = "allergies.contrast_allergy"
            negation_target = "Allergy.negationInd"
            discriminator_target = "Allergy.participant.playingEntity.code"
            model = {"fields": {
                agent: {
                    "name": "Agent", "short_name": "agent", "type": "code",
                    "repeat_chain": [],
                },
                antibiotic: {
                    "name": "Antibiotic allergy",
                    "short_name": "antibiotic_allergy",
                    "type": "boolean", "repeat_chain": [],
                    "codes": [{
                        "code": "SOURCE-DISORDER-A", "code_system": "1.2.3",
                    }],
                },
                contrast: {
                    "name": "Contrast allergy",
                    "short_name": "contrast_allergy",
                    "type": "boolean", "repeat_chain": [],
                    "codes": [{
                        "code": "SOURCE-DISORDER-C", "code_system": "1.2.3",
                    }],
                },
            }, "groups": {}}
            common = {
                "template_id": "allergy",
                "template_effective_date": "2026",
                "renderable": True,
                "writable": True,
                "locations": ["0.1"],
                "repeat_ancestors": ["0.1"],
                "repeatable": True,
                "max": 1,
            }
            cda_model = {"targets": {
                negation_target: {
                    **common,
                    "path": "hl7:observation/@negationInd",
                    "datatype": "BL", "min": 0,
                    "logical_types": ["boolean"],
                    "value_representation": {
                        "kind": "xml_attribute",
                        "logical_types": ["boolean"],
                        "attribute": "negationInd",
                    },
                },
                discriminator_target: {
                    **common,
                    "locations": ["0.1.0.0.0"],
                    "path": (
                        "hl7:observation/hl7:participant/hl7:participantRole/"
                        "hl7:playingEntity/hl7:code"
                    ),
                    "datatype": "CE", "min": 1,
                    "logical_types": ["code", "ordinal"],
                    "value_sets": ["allergen-vs"],
                    "value_set_bindings": [{
                        "id": "allergen-vs", "effective_date": "2025",
                    }],
                    "value_representation": {
                        "kind": "coded",
                        "logical_types": ["code", "ordinal"],
                        "attributes": ["code", "codeSystem", "displayName"],
                    },
                },
            }}
            context = {
                "chain": ["CTX[allergies]"],
                "target": "Allergy.section",
                "node": {"locations": ["0"]},
            }
            existing = {
                agent: discriminator_target,
                antibiotic: None,
                contrast: None,
            }
            generated = boolean_example_discriminator_rules(
                model,
                cda_model,
                [source],
                {antibiotic: context, contrast: context},
                existing,
                value_set_members([source]),
            )
            self.assertEqual(len(generated), 1)
            rule_name, result = next(iter(generated.items()))
            rule = result["rule"]
            self.assertTrue(rule["coalesce_existing_discriminator"])
            self.assertEqual(rule["existing_discriminator_sources"], [agent])
            self.assertEqual(
                [
                    branch["constants"][discriminator_target]["code"]
                    for branch in rule["branches"]
                ],
                ["ANTIBIOTIC", "CONTRAST"],
            )

            selections = result["selections"]
            cda_mapping = {
                "fields": {
                    agent: discriminator_target,
                    antibiotic: selections[antibiotic]["mapping"],
                    contrast: selections[contrast]["mapping"],
                },
                "structures": {rule_name: rule},
            }
            record = {"key": "P1", "values": {
                agent: {
                    "code": "ANTIBIOTIC", "codeSystem": "9.8.7",
                    "displayName": "Antibiotic",
                },
                antibiotic: True,
                contrast: False,
            }, "instances": {}}
            assignments, problems = build_assignments(
                record, model, cda_model, cda_mapping, {}
            )
            self.assertEqual(problems, [])
            self.assertEqual(assignments[negation_target], [False, True])
            self.assertEqual(
                [value["code"] for value in assignments[discriminator_target]],
                ["ANTIBIOTIC", "CONTRAST"],
            )
            self.assertEqual(
                validate.validate_structures(model, cda_model, cda_mapping), []
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
            manifest: dict[str, Any] = {"resources": {}}
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
            manifest: dict[str, Any] = {"resources": {}}
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

    def test_soft_evidence_closes_formal_origin_but_not_relationships(self) -> None:
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
                    return b'<return><concept id="9.1" effectiveDate="2020-01-01"><inherit ref="9.2" effectiveDate="2019-01-01" prefix="ext-"/><relationship type="ADAPT" ref="9.3" flexibility="2018-01-01" prefix="ext-"/></concept></return>'
                if "/concept/9.2/" in path:
                    return b'<return><concept id="9.2" effectiveDate="2019-01-01"/></return>'
                if "/concept/9.3/" in path:
                    raise AssertionError("weak evidence must not recurse")
                raise AssertionError(url)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20,
                )
            self.assertTrue(any("/concept/9.1/" in api_path(url) for url in calls))
            self.assertTrue(any("/concept/9.2/" in api_path(url) for url in calls))
            self.assertFalse(any("/concept/9.3/" in api_path(url) for url in calls))
            self.assertTrue(all(
                "$extract" in api_path(url)
                for url in calls if "/concept/9.2/" in api_path(url)
            ))
            self.assertIn("concept:9.1@2020-01-01", result["closure"]["evidence_resources"])
            self.assertIn("concept:9.2@2019-01-01", result["closure"]["evidence_resources"])

    def test_static_association_endpoint_closes_to_shared_ancestor(self) -> None:
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
                    return b'<dataset id="d" transactionId="t" templateId="doc" templateEffectiveDate="2026"><concept id="selected"><inherit ref="common" effectiveDate="2015" prefix="base-"/></concept></dataset>'
                if path.endswith("/project/aktin-/$extract"):
                    return b'<project><transaction id="t"/></project>'
                if path.endswith("/project/aktin-"):
                    return b'<project><buildingBlockRepository ident="assoc-"/><buildingBlockRepository ident="base-"/></project>'
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026" name="Doc"><element name="hl7:ClinicalDocument" id="root"/><staticAssociations><origconcept ref="association" effectiveDate="2016" ident="assoc-" datasetId="association-dataset" datasetEffectiveDate="2016" elementId="legacy-id" templateId="legacy" templateEffectiveDate="2014"/><origconcept ref="association-sibling" effectiveDate="2016" ident="assoc-" datasetId="association-dataset" datasetEffectiveDate="2016" elementId="legacy-sibling" templateId="legacy" templateEffectiveDate="2014"/></staticAssociations></template></return>'
                if "/concept/association/" in path:
                    return b'<return><concept id="association" effectiveDate="2016"><inherit ref="common" effectiveDate="2015" prefix="base-"/></concept><concept id="association-sibling" effectiveDate="2016"><inherit ref="sibling-common" effectiveDate="2015" prefix="base-"/></concept></return>'
                if "/concept/common/" in path:
                    return b'<return><concept id="common" effectiveDate="2015"/></return>'
                if "/concept/sibling-common/" in path:
                    return b'<return><concept id="sibling-common" effectiveDate="2015"/></return>'
                raise AssertionError(url)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE,
                    transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=30,
                )

            self.assertTrue(any(
                "/concept/association/" in api_path(url) for url in calls
            ))
            self.assertTrue(all(
                "$extract" in api_path(url)
                for url in calls
                if "/concept/association/" in api_path(url)
            ))
            self.assertIn(
                "concept:association@2016|context=association-dataset@2016",
                result["closure"]["evidence_resources"],
            )
            self.assertIn(
                "association-endpoint",
                result["closure"]["resource_roles"][
                    "concept:association@2016|context=association-dataset@2016"
                ],
            )
            self.assertIn(
                "concept:common@2015",
                result["closure"]["evidence_resources"],
            )
            self.assertIn(
                "concept:sibling-common@2015",
                result["closure"]["evidence_resources"],
            )
            self.assertFalse(any(
                "/concept/association-sibling/" in api_path(url)
                for url in calls
            ))


    def test_fetch_progress_does_not_claim_nonexistent_next_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "concept", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "pmp-"}
            progress: list[str] = []

            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", Message(), None)

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
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "aktin-"}
            persisted: list[dict[str, object]] = []
            def save() -> None:
                persisted.append(dict(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]))
            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", Message(), None)
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

    def test_codes_mapping_must_resolve_to_canonical_value(self) -> None:
        errors = validate.check_config(
            {"fields": {"status": {"values": {"active": {"code": "A"}}}}},
            {"targets": {}},
            {"fields": {"status": None}},
            {"fields": {"status": None}},
            {"fields": {"status": {"1": "typo"}}},
        )
        self.assertTrue(any("unknown canonical value" in error for error in errors))

    def test_unbound_code_accepts_explicit_site_code_identity(self) -> None:
        field = {"type": "code", "values": {}}
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
        complete_fixture_value_targets(compiled)
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
        logical = data.normalize_value("Label", field, {}, site)
        self.assertEqual(logical["nullFlavor"], "OTH")
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
        field = {"type": "ordinal", "values": {"1 keine": {"display_name": "1 keine"}, "2 Schmerzreiz": {"display_name": "2 Schmerzreiz"}}}
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
        assert act is not None
        assert observation is not None
        self.assertIs(assertions.evaluate("not(hl7:code[@code='FAMDEP']) or hl7:associatedPerson", act, root), True)
        self.assertIs(assertions.evaluate("not(@negationInd='true' and hl7:value/hl7:qualifier/hl7:name/@code='FSTAT')", observation, root), True)
        self.assertIs(assertions.evaluate("count(hl7:component/hl7:observation[hl7:targetSiteCode/@code='L'])<=1", root, root), True)

    def test_assertion_evaluator_resolves_template_namespaces(self) -> None:
        root = ET.fromstring('''<ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:pharmhl7="urn:hl7-org:pharm"><pharmhl7:ingredientSubstance><pharmhl7:name>Aspirin</pharmhl7:name></pharmhl7:ingredientSubstance></ClinicalDocument>''')
        substance = root.find('{urn:hl7-org:pharm}ingredientSubstance')
        assert substance is not None
        self.assertIs(
            assertions.evaluate(
                "pharmhl7:code or pharmhl7:name", substance, root,
                namespaces={"pharmhl7": "urn:hl7-org:pharm"},
            ),
            True,
        )

    def test_schematron_preserves_assert_and_let(self) -> None:
        text = assertions.schematron({"assertions": [{
            "path": "hl7:observation", "template_id": "1.2.3", "role": "error",
            "test": "empty($seq)", "message": "unique", "lets": {"seq": "//hl7:value"},
        }]})
        self.assertIn('<sch:let name="seq" value="//hl7:value"/>', text)
        self.assertIn('test="empty($seq)"', text)

    def test_schematron_declares_assertion_template_namespaces(self) -> None:
        text = assertions.schematron({"assertions": [{
            "path": "pharmhl7:ingredientSubstance",
            "template_id": "2.16.840.1.113883.10.21.4.18",
            "role": "error", "test": "pharmhl7:code or pharmhl7:name",
            "message": "code or name",
            "namespaces": {"pharmhl7": "urn:hl7-org:pharm"},
        }]})
        self.assertIn(
            '<sch:ns prefix="pharmhl7" uri="urn:hl7-org:pharm"/>', text
        )

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
        complete_fixture_value_targets(compiled)
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
