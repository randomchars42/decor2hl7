from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from decor2hl7 import assertions, cda, data, state, validate
from decor2hl7.build import mapping
from decor2hl7.build.mapping import cda_mapping_proposal
from decor2hl7.build.model import compile_model
from decor2hl7.build.target import compile_cda
from decor2hl7.decor.catalog import parse_releases, parse_transactions, transactions
from decor2hl7.decor.fetch import (
    RequestBudgetExceeded, _candidate_prefixes, _evidence_references, _fetch_want,
    _inventory, fetch_spec, hard_references, soft_references,
)
from decor2hl7.workspace import load_json
from decor2hl7.workspace import (
    init_workspace, input_dir, load_json, release_spec_dir, set_release, set_transaction,
    transaction_config_dir, transaction_key, transaction_model_dir,
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


class CoreTests(unittest.TestCase):
    def test_workspace_selection_is_path_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_workspace(root)
            for path in ("spec", "model", "config", "out", "state"):
                self.assertTrue((root / path).is_dir())
            self.assertFalse((root / "raw").exists())
            self.assertIsNone(load_json(root / "aktin.json")["release"])
            set_release(root, RELEASE)
            set_transaction(root, TRANSACTION)
            # Selection commands do not create release/transaction artifact paths.
            self.assertFalse(release_spec_dir(root).exists())
            self.assertFalse(transaction_model_dir(root).exists())
            self.assertFalse(transaction_config_dir(root).exists())

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

    def test_transaction_catalog_prefers_project_index_transaction_view(self) -> None:
        calls: list[str] = []
        def fake_get(url: str, **_: object) -> bytes:
            calls.append(url)
            return b'<return><transaction id="1.2.3" effectiveDate="2026-01-01T00:00:00" versionLabel="2026"><name>Example</name></transaction></return>'
        with patch("decor2hl7.decor.catalog.get", side_effect=fake_get):
            rows = transactions("aktin-", "2026-04-27T18:50:33", ipv4=True)
        self.assertEqual(rows[0]["id"], "1.2.3")
        self.assertEqual(len(calls), 1)
        self.assertIn("ProjectIndex", calls[0])
        self.assertIn("view=t", calls[0])


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
            self.assertEqual(proposal["fields"]["foo"], "ExampleDocument.value")
            self.assertIn("TA", report)

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
                if "ProjectIndex" in url:
                    return b'<return><project id="9.9" prefix="ext-"/></return>'
                if "RetrieveTransaction" in url:
                    return b'<dataset id="d" transactionId="t" templateId="doc"><concept id="c" shortName="x" type="group"><name>X</name><contains ref="old" datasetId="9.9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if "RetrieveProject" in url:
                    return b'<project><transaction id="t"><representingTemplate ref="doc"/></transaction><dataset id="9.9.1" effectiveDate="2020-01-01"><concept id="old" shortName="old" type="item"><name>Old embedded</name></concept></dataset></project>'
                if "RetrieveDataSet" in url:
                    return b'<dataset id="9.9.1" effectiveDate="2020-01-01"><concept id="old" shortName="old" type="item"><name>Old</name></concept></dataset>'
                if "RetrieveTemplate" in url:
                    return b'<return><template id="doc" effectiveDate="2026-01-01" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t"},
                    retry_missing=False, max_requests=50, progress=progress.append,
                )
            self.assertTrue((release_dir / "manifest.json").exists())
            self.assertTrue((tx_dir / "transaction.xml").exists())
            self.assertTrue((tx_dir / "closure.json").exists())
            self.assertTrue(any(path.parent.name == "datasets" for path in release_dir.rglob("*.xml")))
            self.assertTrue(any("RetrieveDataSet" in url for url in calls))
            self.assertTrue(any(path.parent.name == "templates" for path in release_dir.rglob("*.xml")))
            self.assertFalse(result["closure"]["truncated"])
            self.assertTrue(any("release project" in line and "requesting" in line for line in progress))
            self.assertTrue(any("dataset 9.9.1 @ 2020-01-01" in line for line in progress))
            self.assertTrue(any(line.startswith("fetch: complete:") for line in progress))

            before = len(calls)
            with patch("decor2hl7.decor.fetch.get", side_effect=AssertionError("cache miss")):
                fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t"},
                    retry_missing=False, max_requests=50,
                )
            self.assertEqual(len(calls), before)

    def test_fetch_uses_static_template_from_main_project_evidence_before_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                if "ProjectIndex" in url:
                    return b"<return/>"
                if "RetrieveTransaction" in url:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="2026-01-15T00:00:00"/></transaction>'
                if "RetrieveProject" in url and "version=" in url:
                    return b'<project><transaction id="t"><representingTemplate ref="doc" flexibility="2026-01-15T00:00:00"/></transaction></project>'
                if "RetrieveProject" in url:
                    return b'<project><template id="doc" effectiveDate="2026-01-15T00:00:00" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></project>'
                if "RetrieveTemplate" in url:
                    raise AssertionError(f"template should have been satisfied by project-evidence.xml: {url}")
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20, progress=progress.append,
                )

            self.assertFalse(any("RetrieveTemplate" in url for url in calls))
            self.assertFalse(result["closure"]["errors"])
            self.assertTrue(any(
                "template doc @ 2026-01-15T00:00:00" in line
                and "available in main project evidence" in line
                for line in progress
            ))

    def test_dynamic_template_from_main_project_evidence_is_capped_at_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                if "ProjectIndex" in url:
                    return b"<return/>"
                if "RetrieveTransaction" in url:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="dynamic"/></transaction>'
                if "RetrieveProject" in url and "version=" in url:
                    return b'<project><transaction id="t"><representingTemplate ref="doc" flexibility="dynamic"/></transaction></project>'
                if "RetrieveProject" in url:
                    return (
                        b'<project>'
                        b'<template id="doc" effectiveDate="2026-02-01T00:00:00" name="ReleasedDoc"><element name="hl7:ClinicalDocument" id="released"/></template>'
                        b'<template id="doc" effectiveDate="2026-05-01T00:00:00" name="FutureDraft"><element name="hl7:ClinicalDocument" id="future"/></template>'
                        b'</project>'
                    )
                if "RetrieveTemplate" in url:
                    raise AssertionError(f"template should have been satisfied by project-evidence.xml: {url}")
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20, progress=progress.append,
                )

            self.assertFalse(any("RetrieveTemplate" in url for url in calls))
            self.assertFalse(result["closure"]["errors"])
            evidence_lines = [line for line in progress if "available in main project evidence" in line]
            self.assertTrue(any("2026-02-01T00:00:00" in line for line in evidence_lines))
            self.assertFalse(any("2026-05-01T00:00:00" in line for line in evidence_lines))

    def test_fetch_interrupt_writes_incomplete_closure_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"

            def fake_get(url: str, **_: object) -> bytes:
                if "ProjectIndex" in url:
                    return b"<return/>"
                if "RetrieveTransaction" in url:
                    return b'<dataset id="d"><concept id="c"><contains ref="old" datasetId="9.9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if "RetrieveProject" in url:
                    return b'<project><transaction id="t"/></project>'
                if "RetrieveDataSet" in url:
                    raise KeyboardInterrupt
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
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
            with self.assertRaisesRegex(ValueError, "closure is incomplete"):
                from decor2hl7.decor.fetch import closure_paths
                closure_paths(release_dir, tx_dir)

    def test_recursive_request_budget_counts_actual_http_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "prefix": "first-"}
            budget = {"made": 0, "max": 1}
            def missing(_url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(_url, 404, "missing", None, None)
            with patch("decor2hl7.decor.fetch.get", side_effect=missing):
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

    def test_multiple_primary_rows_are_demoted(self) -> None:
        rows = [{"main": "0", "v": "a"}, {"main": "1", "v": "b"}, {"main": "1", "v": "c"}]
        ordered, problems = data._order_rows(rows, {"column": "main", "true_values": ["1"], "false_value": "0"})
        self.assertEqual([row["v"] for row in ordered], ["b", "a", "c"])
        self.assertEqual(ordered[2]["main"], "0")
        self.assertEqual(problems[0]["severity"], "error")

    def test_config_validation_requires_all_fields(self) -> None:
        errors = validate.check_config({"fields": {"a": {}, "b": {}}}, {"targets": {"T.value": {}}},
                                       {"fields": {"a": "cases:a"}}, {"fields": {"a": "T.value", "b": None}})
        self.assertIn("csv-mapping: missing model field b", errors)

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
            self.assertEqual(model["fields"]["status"]["values"]["aktiv"]["code"], "A")

    def test_live_evidence_does_not_seed_unrelated_external_crawl(self) -> None:
        root = ET.fromstring('''<project>
          <concept id="relevant"><name>Relevant</name><inherit ref="old" datasetId="9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept>
          <concept id="unrelated"><name>Unrelated</name><inherit ref="other" datasetId="9.2" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept>
        </project>''')
        refs = _evidence_references(root, {"relevant"})
        self.assertEqual({item["id"] for item in refs if item["kind"] == "concept"}, {"old"})
        self.assertFalse(any(item["kind"] == "dataset" for item in refs))

    def test_fetch_want_adopts_valid_existing_file_without_manifest_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "1.2.3_2025-05-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="1.2.3" effectiveDate="2025-05-01" name="T"><element name="hl7:observation"/></template></return>',
                encoding="utf-8",
            )
            manifest = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "2025-05-01", "prefix": "aktin-"}
            progress: list[str] = []
            with patch("decor2hl7.decor.fetch.get", side_effect=AssertionError("must not download")):
                path = _fetch_want(
                    release_dir, manifest, want, owners={}, repositories=["aktin-"],
                    language="de-DE", ipv4=True, retry_missing=False, progress=progress.append,
                )
            self.assertEqual(path, target)
            entry = manifest["resources"]["template:1.2.3@2025-05-01"]
            self.assertEqual(entry["status"], "ok")
            self.assertEqual(entry["file"], "templates/1.2.3_2025-05-01.xml")
            self.assertTrue(entry["sha256"])
            self.assertTrue(any("manifest repaired" in line for line in progress))

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
            want = {"kind": "template", "id": "1.2.3", "effective_date": "2025-05-01", "prefix": "aktin-"}
            downloaded = b'<return><template id="1.2.3" effectiveDate="2025-05-01" name="Fresh"/></return>'
            with patch("decor2hl7.decor.fetch.get", return_value=downloaded) as mocked:
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
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "prefix": "aktin-"}
            calls: list[str] = []
            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                return b'<return><template id="1.2.3" effectiveDate="2025-05-01T00:00:00" name="T"><element name="hl7:observation"/></template></return>'
            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
                path = _fetch_want(release_dir, manifest, want, owners={}, repositories=["aktin-"], language="de-DE", ipv4=True, retry_missing=False)
            entry = manifest["resources"]["template:1.2.3"]
            self.assertEqual(entry["requested_effective_date"], "dynamic")
            self.assertEqual(entry["resolved_effective_date"], "2025-05-01T00:00:00")
            assert path is not None
            path.unlink()
            calls.clear()
            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
                _fetch_want(release_dir, manifest, want, owners={}, repositories=["aktin-"], language="de-DE", ipv4=True, retry_missing=False)
            self.assertTrue(any("effectiveDate=2025-05-01" in url for url in calls))

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
        want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "prefix": "aktin-"}
        self.assertEqual(
            _candidate_prefixes(want, {"1.2.3": "aktin-"}, ["aktin-", "pmp-", "hl7de-"]),
            ["aktin-"],
        )
        stale = {**want, "prefix": "old-"}
        self.assertEqual(
            _candidate_prefixes(stale, {"1.2.3": "aktin-"}, ["aktin-", "pmp-"]),
            ["aktin-", "old-"],
        )

    def test_soft_evidence_resolution_is_non_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "2026.1.2"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                if "ProjectIndex" in url:
                    return b'<return><project id="9" prefix="ext-"/></return>'
                if "RetrieveTransaction" in url:
                    return b'<dataset id="d" transactionId="t"><concept id="current"><inherit ref="9.1" effectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if "RetrieveProject" in url:
                    return b'<project><transaction id="t"/></project>'
                if "RetrieveConcept" in url and "conceptId=9.1" in url:
                    return b'<return><concept id="9.1" effectiveDate="2020-01-01"><inherit ref="9.2" effectiveDate="2019-01-01" prefix="ext-"/></concept></return>'
                if "RetrieveConcept" in url and "conceptId=9.2" in url:
                    raise AssertionError("soft evidence must not recurse")
                raise AssertionError(url)

            with patch("decor2hl7.decor.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="aktin-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20,
                )
            self.assertTrue(any("RetrieveConcept" in url and "conceptId=9.1" in url for url in calls))
            self.assertFalse(any("conceptId=9.2" in url for url in calls))
            self.assertIn("concept:9.1@2020-01-01", result["closure"]["evidence_resources"])

    def test_settled_missing_is_persisted_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = {"resources": {}}
            want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "prefix": "aktin-"}
            persisted: list[dict[str, object]] = []
            def save() -> None:
                persisted.append(dict(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]))
            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", None, None)
            with patch("decor2hl7.decor.fetch.get", side_effect=missing) as mocked:
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "aktin-"}, repositories=["aktin-", "pmp-"],
                    language="de-DE", ipv4=True, retry_missing=False, save_manifest=save,
                ))
            self.assertEqual(mocked.call_count, 1)
            self.assertTrue(persisted)
            self.assertTrue(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]["settled"])
            with patch("decor2hl7.decor.fetch.get", side_effect=AssertionError("known missing must not retry")):
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
            self.assertEqual(set(model["fields"]["status"]["values"]), {"B"})
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
            values = model["fields"]["indicator"]["values"]
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



if __name__ == "__main__":
    unittest.main()
