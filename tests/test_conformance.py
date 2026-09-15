from __future__ import annotations

import io
import json
import shutil
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from decor2hl7.cda.core import CORE_FILES, CORE_REVISION, core_paths
from decor2hl7.compile.schematron import (
    attach_constraints, read_constraints, read_datatype_cooccurrences,
    split_xpath,
)
from decor2hl7.conformance import (
    _complete_schematron_namespaces,
    _generation_message_scope,
    _normalize_generated_see_uris,
    _profile_extension_projection,
    _repair_generated_stylesheet,
    _safe_member,
    _extract_cda,
    _extract_decor,
    assemble_decor_closure,
    sha256_file,
    validate_cda_documents,
    validate_xsd,
    validation_package_problems,
    write_conformance_report,
)
from decor2hl7.retrieval.fetch import _fetch_direct


class ConformanceTests(unittest.TestCase):
    def test_profile_extension_projection_is_exact_and_cda_core_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "cda.json").write_text(json.dumps({
                "document": [{
                    "kind": "element", "name": "hl7:ClinicalDocument",
                    "namespace_uri": "urn:hl7-org:v3", "children": [{
                        "kind": "element", "name": "hl7:manufacturedMaterial",
                        "namespace_uri": "urn:hl7-org:v3", "children": [{
                            "kind": "element", "name": "pharmhl7:formCode",
                            "namespace_prefix": "pharmhl7",
                            "namespace_uri": "urn:hl7-org:pharm",
                            "children": [], "attributes": [],
                        }], "attributes": [{
                            "kind": "attribute",
                            "name": "pharmhl7:classification",
                            "namespace_prefix": "pharmhl7",
                            "namespace_uri": "urn:hl7-org:pharm",
                        }],
                    }], "attributes": [],
                }],
            }), encoding="utf-8")
            valid = root / "valid.xml"
            valid.write_text(
                '''<ClinicalDocument xmlns="urn:hl7-org:v3"
 xmlns:pharmhl7="urn:hl7-org:pharm"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <manufacturedMaterial pharmhl7:classification="direct">
 <value xsi:type="CE" code="TAB"/>
 <pharmhl7:formCode code="TAB"/></manufacturedMaterial></ClinicalDocument>''',
                encoding="utf-8",
            )
            projected, diagnostics, removed, namespaces = (
                _profile_extension_projection(
                    model_dir, [valid], root / "projected"
                )
            )
            self.assertEqual(diagnostics, [])
            self.assertEqual(removed, 2)
            self.assertEqual(namespaces, {"urn:hl7-org:pharm"})
            self.assertIsNone(
                ET.parse(projected[0]).find(".//{urn:hl7-org:pharm}formCode")
            )
            projected_material = ET.parse(projected[0]).find(
                ".//{urn:hl7-org:v3}manufacturedMaterial"
            )
            assert projected_material is not None
            self.assertNotIn(
                "{urn:hl7-org:pharm}classification",
                projected_material.attrib,
            )
            projected_text = projected[0].read_text(encoding="utf-8")
            self.assertIn('xmlns="urn:hl7-org:v3"', projected_text)
            self.assertNotIn("xmlns:ns0=", projected_text)
            self.assertIn('xsi:type="CE"', projected_text)
            self.assertIsNotNone(
                ET.parse(valid).find(".//{urn:hl7-org:pharm}formCode")
            )

            invalid = root / "invalid.xml"
            invalid.write_text(
                valid.read_text(encoding="utf-8").replace(
                    "formCode", "unexpected"
                ),
                encoding="utf-8",
            )
            _, invalid_diagnostics, _, _ = _profile_extension_projection(
                model_dir, [invalid], root / "invalid-projected"
            )
            self.assertEqual(len(invalid_diagnostics), 1)
            self.assertIn("not selected", invalid_diagnostics[0]["message"])

    def test_datatype_presence_cooccurrences_are_strict_and_inherited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            include = Path(temporary)
            (include / "DTr1_BASE.sch").write_text('''<rule
    xmlns="http://purl.oclc.org/dsdl/schematron" abstract="true" id="BASE">
  <assert role="error" test="not(@value and hl7:*)">base</assert>
  <assert role="error" test="not(hl7:low/@value = hl7:high/@value)">unsupported</assert>
  <assert role="warning" test="not(@code and hl7:translation)">warning</assert>
</rule>''', encoding="utf-8")
            (include / "DTr1_CHILD.sch").write_text('''<rule
    xmlns="http://purl.oclc.org/dsdl/schematron" abstract="true" id="CHILD">
  <extends rule="BASE"/>
  <assert role="error" test="not(@value and (hl7:low|hl7:high))">union</assert>
  <assert role="error" test="not(hl7:width and hl7:low and hl7:high)">n-ary</assert>
</rule>''', encoding="utf-8")

            rules, summary = read_datatype_cooccurrences(
                include.glob("DTr1_*.sch")
            )
            self.assertEqual(summary["supported_assertions"], 3)
            self.assertEqual(summary["unsupported_error_assertions"], 1)
            self.assertEqual(summary["unresolved_extends"], [])
            self.assertEqual(
                [row["selectors"] for row in rules["CHILD"]],
                [
                    ["@value", "hl7:*"],
                    ["@value", "hl7:low"],
                    ["@value", "hl7:high"],
                    ["hl7:width", "hl7:low", "hl7:high"],
                ],
            )

    def test_generated_template_constraints_are_parsed_and_cross_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            include = Path(temporary)
            pattern = include / "1.2.3-2026-01-01T000000.sch"
            pattern.write_text('''<pattern xmlns="http://purl.oclc.org/dsdl/schematron"
    id="template-1.2.3-2026-01-01T000000">
  <rule context="*[hl7:observation[hl7:templateId[@root='1.2.3']]]/hl7:observation">
    <assert see="file:///must/not/be/read" test="string(@classCode) = ('OBS')">fixed</assert>
    <assert test="@moodCode">required attribute</assert>
    <assert test="count(hl7:value[concat(@code,@codeSystem) = doc('include/voc-9.8.7-DYNAMIC.xml')//concept/concat(@code,@codeSystem)]) &gt;= 1">required value</assert>
    <assert test="count(hl7:value[@xsi:type='CD']) &lt;= 1">typed choice</assert>
  </rule>
</pattern>''', encoding="utf-8")
            (include / "DTr1_TS.sch").write_text(
                '<pattern xmlns="http://purl.oclc.org/dsdl/schematron" '
                'id="template-7.7.7-2026"><rule context="hl7:value">'
                '<assert test="@value">ignored</assert></rule></pattern>',
                encoding="utf-8",
            )
            constraints = read_constraints(include.glob("*.sch"))
            self.assertEqual(
                {item["kind"] for item in constraints},
                {
                    "attribute_required", "fixed_value", "max_occurs",
                    "required", "value_set", "xsi_type",
                },
            )
            self.assertTrue(any(
                item.get("value_set") == "9.8.7" for item in constraints
            ))
            self.assertEqual(
                split_xpath(
                    "hl7:value[doc('include/voc-9.8.7-DYNAMIC.xml')]/hl7:originalText"
                ),
                [
                    "hl7:value[doc('include/voc-9.8.7-DYNAMIC.xml')]",
                    "hl7:originalText",
                ],
            )

            cda_model: dict[str, Any] = {"targets": {
                "Observation.value": {
                    "template_id": "1.2.3",
                    "template_effective_date": "2026-01-01",
                    "path": "hl7:observation/hl7:value",
                },
                "Observation.classCode": {
                    "template_id": "1.2.3",
                    "template_effective_date": "2026-01-01",
                    "path": "hl7:observation/@classCode",
                },
                "Other.value": {
                    "template_id": "4.5.6",
                    "template_effective_date": "2026-01-01",
                    "path": "hl7:observation/hl7:value",
                },
            }}
            summary = attach_constraints(cda_model, include)
            self.assertGreaterEqual(summary["matched"], 4)
            value_constraints = cda_model["targets"]["Observation.value"][
                "schematron_constraints"
            ]
            self.assertEqual(
                {item["kind"] for item in value_constraints},
                {"max_occurs", "required", "value_set", "xsi_type"},
            )
            self.assertNotIn(
                "schematron_constraints", cda_model["targets"]["Other.value"]
            )

    def test_generated_see_uris_are_workspace_relative_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            filename = "tmp-1.2.3-2026-01-01T000000.html"
            for directory, machine, stamp in (
                (left, "machine-a/work", "20260903T201617"),
                (right, "machine-b/elsewhere", "20261004T091011"),
            ):
                (directory / "rule.sch").write_text(
                    '<assert see="http://aktin.art-decor.pub/file:///'
                    f'{machine}/generated/aktin-html-{stamp}/{filename}" '
                    'test="true()"/>'
                    '<assert see="https://docs.art-decor.org/stable" '
                    'test="true()"/>',
                    encoding="utf-8",
                )

            left_repairs = _normalize_generated_see_uris(left)
            right_repairs = _normalize_generated_see_uris(right)
            self.assertEqual(len(left_repairs), 1)
            self.assertEqual(len(right_repairs), 1)
            self.assertEqual(
                (left / "rule.sch").read_bytes(),
                (right / "rule.sch").read_bytes(),
            )
            normalized = (left / "rule.sch").read_text(encoding="utf-8")
            self.assertIn(f'see="generated/documentation/{filename}"', normalized)
            self.assertIn('see="https://docs.art-decor.org/stable"', normalized)

    def test_generation_message_scope_follows_the_selected_document(self) -> None:
        """A skipped rule only counts when its context template is instantiated."""
        message = "ERROR  : +++ value set skipped for use in schematron because the value set contents are not defined - value set 2.16.840.1.113762.1.4.1021.30: dynamic in rule MedicationActivity: 2013-01-31T00:00:00 (context=*[cda:substanceAdministration[cda:templateId[@root = '2.16.840.1.113883.10.20.22.4.16']]]/cda:substanceAdministration/cda:administrationUnitCode)"
        outside = _generation_message_scope(message, {"1.2.276.0.76.3.1.195.10.93"})
        self.assertEqual(outside["severity"], "error")
        self.assertEqual(outside["value_sets"], ["2.16.840.1.113762.1.4.1021.30"])
        self.assertEqual(
            outside["context_templates"], ["2.16.840.1.113883.10.20.22.4.16"]
        )
        self.assertFalse(outside["in_selected_closure"])
        inside = _generation_message_scope(
            message, {"2.16.840.1.113883.10.20.22.4.16"}
        )
        self.assertTrue(inside["in_selected_closure"])

    def test_generation_message_without_context_stays_inside_the_closure(self) -> None:
        """An unparsed message must never silently weaken the claim."""
        scope = _generation_message_scope("ERROR  : +++ unparsed", {"anything"})
        self.assertEqual(scope["context_templates"], [])
        self.assertTrue(scope["in_selected_closure"])
        # Without a compiled document the classifier cannot scope anything.
        self.assertTrue(
            _generation_message_scope("ERROR  : x", None)["in_selected_closure"]
        )

    def test_generated_supply_match_repair_is_exact_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stylesheet = Path(temporary) / "validator.xsl"
            stylesheet.write_text(
                '<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
                '<xsl:template match="hl7:entryRelationship[@typeCode=\'REFR\'][[hl7:supply]"/>'
                '<xsl:template match="hl7:entryRelationship[@typeCode=\'REFR\'][hl7:supply]"/>'
                '<xsl:template match="hl7:other[[hl7:supply][x]"/>'
                '</xsl:stylesheet>', encoding="utf-8",
            )
            repairs = _repair_generated_stylesheet(stylesheet)
            updated = stylesheet.read_text(encoding="utf-8")
            self.assertEqual(len(repairs), 1)
            self.assertIn(
                'match="hl7:entryRelationship[@typeCode=\'REFR\'][hl7:supply]"',
                updated,
            )
            self.assertIn('match="hl7:other[[hl7:supply][x]"', updated)

    def test_generated_schematron_declares_qname_string_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assembled = root / "assembled.xml"
            assembled.write_text(
                '<decor xmlns:pharm="urn:example:pharm" '
                'pharm:dummy="urn:example:pharm"/>',
                encoding="utf-8",
            )
            schematron = root / "generated.sch"
            schematron.write_text(
                '<schema xmlns="http://purl.oclc.org/dsdl/schematron">'
                '<title>Generated</title><pattern>'
                '<include href="include/medicine.sch"/>'
                '</pattern></schema>',
                encoding="utf-8",
            )
            include = root / "include"
            include.mkdir()
            (include / "medicine.sch").write_text(
                '<rule xmlns="http://purl.oclc.org/dsdl/schematron" '
                'context="pharm:medicine">'
                '<assert test="pharm:code">code required</assert></rule>',
                encoding="utf-8",
            )

            _complete_schematron_namespaces(assembled, schematron)

            namespace = ET.parse(schematron).getroot().find(
                "{http://purl.oclc.org/dsdl/schematron}ns"
            )
            self.assertIsNotNone(namespace)
            assert namespace is not None
            self.assertEqual(namespace.get("prefix"), "pharm")
            self.assertEqual(namespace.get("uri"), "urn:example:pharm")

    def test_package_extractors_preserve_required_relative_graphs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decor_archive = root / "decor.xar"
            decor_members = (
                "DECOR.xsd",
                "DECOR-datatypes.xsd",
                "DECOR.sch",
                "DECOR2schematron.xsl",
                "iso-schematron/iso_svrl_for_xslt2.xsl",
                "coreschematrons/DTr1_EIVL_TS.sch",
            )
            with zipfile.ZipFile(decor_archive, "w") as archive:
                for name in decor_members:
                    archive.writestr(name, name)
            decor_output = root / "decor"
            extracted_decor = _extract_decor(decor_archive, decor_output)
            self.assertEqual(len(extracted_decor), len(decor_members))
            self.assertTrue((decor_output / decor_members[-1]).is_file())

            cda_archive = root / "cda.tar.gz"
            cda_members = (
                "schema/normative/infrastructure/cda/CDA.xsd",
                "schema/normative/infrastructure/cda/POCD_MT000040.xsd",
                "schema/normative/processable/coreschemas/NarrativeBlock.xsd",
                "schema/normative/processable/coreschemas/voc.xsd",
                "schema/extensions/SDTC/infrastructure/cda/CDA_SDTC.xsd",
                "schema/extensions/SDTC/infrastructure/cda/SDTC.xsd",
            )
            with tarfile.open(cda_archive, "w:gz") as archive:
                for name in cda_members:
                    payload = name.encode("utf-8")
                    item = tarfile.TarInfo(f"repository-revision/{name}")
                    item.size = len(payload)
                    archive.addfile(item, io.BytesIO(payload))
            cda_output = root / "cda"
            extracted_cda = _extract_cda(cda_archive, cda_output)
            self.assertEqual(len(extracted_cda), len(cda_members))
            self.assertTrue((cda_output / cda_members[-1]).is_file())

    def test_assembled_closure_excludes_artdecor_result_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "spec"
            release_dir.mkdir()
            (release_dir / "project.xml").write_text(
                '<project prefix="demo-"><name>Demo</name></project>',
                encoding="utf-8",
            )
            dataset = root / "dataset.xml"
            dataset.write_text(
                '<dataset id="1.2.3" effectiveDate="2026-01-01T00:00:00"/>',
                encoding="utf-8",
            )
            transaction = root / "transaction.xml"
            transaction.write_text(
                '<transaction id="1.2.3.4.5" effectiveDate="2026-01-02T00:00:00"/>',
                encoding="utf-8",
            )
            template = root / "template.xml"
            template.write_text(
                '<result xmlns:pharm="urn:example:pharm"><template id="9.8.7">'
                '<template id="9.8.7" name="Actual" '
                'effectiveDate="2026-01-03T00:00:00">'
                '<element name="pharm:medicine"/></template></template></result>',
                encoding="utf-8",
            )
            other_template = root / "other-template.xml"
            other_template.write_text(
                '<result xmlns:pharm="urn:other:pharm">'
                '<template id="9.8.6" name="Other" '
                'effectiveDate="2026-01-03T00:00:00">'
                '<element name="pharm:product"/></template></result>',
                encoding="utf-8",
            )
            old_template = root / "old-template.xml"
            old_template.write_text(
                '<template id="9.8.7" name="Old" '
                'effectiveDate="2025-01-03T00:00:00">'
                '<element name="hl7:observation"/></template>',
                encoding="utf-8",
            )
            terminology = root / "terminology.xml"
            terminology.write_text(
                '<valueSets><project><valueSet id="7.8.9" name="Codes" '
                'effectiveDate="2026-01-04T00:00:00"/></project></valueSets>',
                encoding="utf-8",
            )
            output = root / "assembled.xml"
            assemble_decor_closure(
                release_dir,
                {
                    "transaction_analysis": dataset,
                    "transaction_source": transaction,
                    "model_resources": [],
                    "terminology_resources": [terminology],
                    "templates": [template, other_template, old_template],
                },
                {"key": "2026.1", "date": "2026-01-05T00:00:00"},
                {"id": "1.2.3.4.5", "effective_date": "2026-01-02T00:00:00"},
                output,
            )
            assembled = ET.parse(output).getroot()
            templates = assembled.find("rules").findall("template")  # type: ignore[union-attr]
            self.assertEqual(len(templates), 3)
            self.assertEqual(templates[0].get("name"), "Actual")
            self.assertEqual(templates[0].get("effectiveDate"), "2026-01-03T00:00:00")
            self.assertIn('xmlns:pharm="urn:example:pharm"', output.read_text(encoding="utf-8"))
            self.assertIn('xmlns:pharm2="urn:other:pharm"', output.read_text(encoding="utf-8"))
            self.assertEqual(
                templates[1].find("element").get("name"),  # type: ignore[union-attr]
                "pharm2:product",
            )
            filtered = root / "assembled-filtered.xml"
            assemble_decor_closure(
                release_dir,
                {
                    "transaction_analysis": dataset,
                    "transaction_source": transaction,
                    "model_resources": [],
                    "terminology_resources": [terminology],
                    "templates": [template, other_template, old_template],
                },
                {"key": "2026.1", "date": "2026-01-05T00:00:00"},
                {
                    "id": "1.2.3.4.5",
                    "effective_date": "2026-01-02T00:00:00",
                },
                filtered,
                {("9.8.7", "2026-01-03T00:00:00")},
            )
            filtered_templates = (
                ET.parse(filtered).getroot().find("rules").findall("template")  # type: ignore[union-attr]
            )
            self.assertEqual(
                [(item.get("id"), item.get("effectiveDate")) for item in filtered_templates],
                [("9.8.7", "2026-01-03T00:00:00")],
            )
            values = assembled.find("terminology").findall("valueSet")  # type: ignore[union-attr]
            self.assertEqual([(item.get("id"), item.get("effectiveDate")) for item in values], [
                ("7.8.9", "2026-01-04T00:00:00")
            ])

    def test_assembled_closure_requires_selected_formal_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "spec"
            release_dir.mkdir()
            (release_dir / "project.xml").write_text(
                '<project prefix="demo-"/>', encoding="utf-8"
            )
            dataset = root / "dataset.xml"
            dataset.write_text(
                '<dataset id="1.2.3" effectiveDate="2026-01-01"/>',
                encoding="utf-8",
            )
            transaction = root / "transaction.xml"
            transaction.write_text(
                '<transaction id="1.2.3.4.5" effectiveDate="2026-01-02"/>',
                encoding="utf-8",
            )
            parent = root / "parent.xml"
            parent.write_text(
                '<template id="9.8.7" effectiveDate="2026-01-03">'
                '<element contains="9.8.6" '
                'tmeffectiveDate="2026-01-04"/></template>',
                encoding="utf-8",
            )
            child = root / "child.xml"
            child.write_text(
                '<template id="9.8.6" effectiveDate="2026-01-04"/>',
                encoding="utf-8",
            )
            inputs = {
                "transaction_analysis": dataset,
                "transaction_source": transaction,
                "model_resources": [],
                "terminology_resources": [],
                "templates": [parent, child],
            }
            release = {"key": "2026.1", "date": "2026-01-05"}
            selected_transaction = {
                "id": "1.2.3.4.5",
                "effective_date": "2026-01-02",
            }

            with self.assertRaisesRegex(
                ValueError,
                r"9\.8\.7@2026-01-03 contains 9\.8\.6@2026-01-04",
            ):
                assemble_decor_closure(
                    release_dir,
                    inputs,
                    release,
                    selected_transaction,
                    root / "incomplete.xml",
                    {("9.8.7", "2026-01-03")},
                )

            complete = root / "complete.xml"
            assemble_decor_closure(
                release_dir,
                inputs,
                release,
                selected_transaction,
                complete,
                {
                    ("9.8.7", "2026-01-03"),
                    ("9.8.6", "2026-01-04"),
                },
            )
            templates = ET.parse(complete).getroot().find("rules")
            self.assertEqual(
                {
                    (item.get("id"), item.get("effectiveDate"))
                    for item in (templates if templates is not None else ())
                },
                {
                    ("9.8.7", "2026-01-03"),
                    ("9.8.6", "2026-01-04"),
                },
            )

    def test_assembled_closure_merges_valueset_definition_and_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "spec"
            release_dir.mkdir()
            (release_dir / "project.xml").write_text(
                '<project prefix="demo-"/>', encoding="utf-8"
            )
            dataset = root / "dataset.xml"
            dataset.write_text(
                '<dataset id="d" effectiveDate="2026"/>', encoding="utf-8"
            )
            transaction = root / "transaction.xml"
            transaction.write_text(
                '<transaction id="t" effectiveDate="2026"/>', encoding="utf-8"
            )
            definition = root / "definition.xml"
            definition.write_text('''<valueSet id="vs" effectiveDate="2025">
              <conceptList><include codeSystem="cs"/></conceptList>
            </valueSet>''', encoding="utf-8")
            expansion = root / "expansion.xml"
            expansion.write_text('''<valueSetExpansionSet current="1" count="1">
              <valueSet id="vs" effectiveDate="2025">
                <conceptList><include codeSystem="cs"/></conceptList>
              </valueSet>
              <expansion><items is="concept" code="A" codeSystem="cs"/></expansion>
            </valueSetExpansionSet>''', encoding="utf-8")
            output = root / "assembled.xml"
            assemble_decor_closure(
                release_dir,
                {
                    "transaction_analysis": dataset,
                    "transaction_source": transaction,
                    "model_resources": [], "templates": [],
                    "terminology_resources": [definition, expansion],
                },
                {"key": "2026", "date": "2026"},
                {"id": "t", "effective_date": "2026"}, output,
            )
            terminology = ET.parse(output).getroot().find("terminology")
            self.assertIsNotNone(terminology)
            assert terminology is not None
            value_sets = terminology.findall("valueSet")
            self.assertEqual(len(value_sets), 1)
            self.assertIsNone(value_sets[0].find(".//include"))
            self.assertIsNotNone(value_sets[0].find(".//concept"))

    def test_markdown_report_is_bounded_but_json_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "report"
            diagnostics = [
                {
                    "phase": "source",
                    "severity": "warning",
                    "kind": "failed-assert",
                    "rule_id": "",
                    "test": "",
                    "location": f"/{index}",
                    "document": "source.xml",
                    "message": f"warning {index}",
                }
                for index in range(205)
            ]
            result = write_conformance_report(
                base,
                scope="build",
                diagnostics=diagnostics,
                stages=[{"phase": "packages", "status": "not-run", "detail": "missing"}],
                policy="report-only",
            )
            self.assertEqual(result["status"], "not-run")
            stored = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(len(stored["diagnostics"]), 205)
            markdown = base.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("first 200 of 205 diagnostics", markdown)
            self.assertNotIn("warning 204 |", markdown)

    def test_partly_unrun_conformance_report_is_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = write_conformance_report(
                Path(temporary) / "report",
                scope="build",
                diagnostics=[],
                stages=[
                    {"phase": "source", "status": "passed", "detail": "complete"},
                    {"phase": "compiled", "status": "not-run", "detail": "absent"},
                ],
                policy="report-only",
            )
            self.assertEqual(result["status"], "degraded")

    @unittest.skipUnless(shutil.which("java"), "Java source-file mode is unavailable")
    def test_xsd_backend_reports_document_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            schema = root / "schema.xsd"
            schema.write_text(
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                '<xs:element name="count" type="xs:integer"/>'
                '</xs:schema>',
                encoding="utf-8",
            )
            invalid = root / "invalid.xml"
            invalid.write_text("<count>not-an-integer</count>", encoding="utf-8")
            diagnostics = validate_xsd(schema, [invalid], phase="test-xsd")
            self.assertTrue(any(item["severity"] == "error" for item in diagnostics))
            self.assertTrue(all(item["phase"] == "test-xsd" for item in diagnostics))

    def test_pinned_download_rejects_unexpected_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary)
            manifest: dict[str, object] = {"resources": {}}
            with patch("decor2hl7.retrieval.fetch.get", return_value=b"wrong"):
                result = _fetch_direct(
                    release_dir,
                    manifest,
                    key="validation-package:test",
                    relative_file="validation/packages/test.bin",
                    url="https://example.invalid/test.bin",
                    ipv4=True,
                    retry_missing=False,
                    expected_sha256="0" * 64,
                    binary=True,
                )
            self.assertIsNone(result)
            self.assertFalse((release_dir / "validation/packages/test.bin").exists())
            resource = manifest["resources"]["validation-package:test"]  # type: ignore[index]
            self.assertEqual(resource["status"], "error")

    def test_pinned_binary_package_is_reused_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary)
            target = release_dir / "validation/packages/test.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"not XML, but checksum-pinned")
            expected = sha256_file(target)
            manifest: dict[str, object] = {
                "resources": {
                    "validation-package:test": {"status": "unavailable"},
                },
            }
            with patch("decor2hl7.retrieval.fetch.get") as get:
                result = _fetch_direct(
                    release_dir,
                    manifest,
                    key="validation-package:test",
                    relative_file="validation/packages/test.bin",
                    url="https://example.invalid/test.bin",
                    ipv4=True,
                    retry_missing=False,
                    offline=True,
                    expected_sha256=expected,
                    binary=True,
                )
            self.assertEqual(result, target)
            self.assertEqual(
                manifest["resources"]["validation-package:test"]["status"],  # type: ignore[index]
                "ok",
            )
            get.assert_not_called()

    def test_cda_gate_does_not_run_a_nonexecutable_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "spec"
            model_dir = root / "model"
            conformance = model_dir / "conformance-validation"
            conformance.mkdir(parents=True)
            validator = conformance / "cda-template.xsl"
            validator.write_text("validator", encoding="utf-8")
            (conformance / "validator-manifest.json").write_text(
                json.dumps({
                    "executable": False,
                    "complete": False,
                    "validator_sha256": sha256_file(validator),
                }),
                encoding="utf-8",
            )
            document = root / "document.xml"
            document.write_text("<ClinicalDocument/>", encoding="utf-8")
            with (
                patch("decor2hl7.conformance.validation_packages_available", return_value=True),
                patch("decor2hl7.conformance.cda_schema_path", return_value=root / "cda.xsd"),
                patch("decor2hl7.conformance.validate_xsd", return_value=[]),
                patch("decor2hl7.conformance.validate_schematron", return_value=[]) as schematron,
            ):
                result = validate_cda_documents(
                    release_dir, model_dir, [document], root / "report"
                )
            self.assertEqual(result["status"], "failed")
            schematron.assert_not_called()
            self.assertEqual(
                result["stages"][0],
                {
                    "phase": "template-validator-provenance",
                    "status": "failed",
                    "detail": (
                        "validator compilation probe failed; see "
                        "validator-compilation-errors.txt"
                    ),
                },
            )

    def test_package_lock_paths_cannot_escape_extraction_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary)
            lock = release_dir / "validation/package-lock.json"
            lock.parent.mkdir(parents=True)
            lock.write_text(
                json.dumps({
                    "packages": [],
                    "extracted": {
                        "decor_core": {"../../outside": "unused"},
                        "cda_core": {"../../outside": "unused"},
                    },
                }),
                encoding="utf-8",
            )
            problems = validation_package_problems(release_dir)
            self.assertTrue(any("unsafe validation-package member" in item for item in problems))
            with self.assertRaises(ValueError):
                _safe_member("../outside.xsd")

    def test_cda_compiler_prefers_preserved_normative_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary)
            normative = release_dir / "validation" / "cda-core" / CORE_REVISION
            expected = []
            for source in CORE_FILES.values():
                path = normative / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("schema", encoding="utf-8")
                expected.append(path)
            self.assertEqual(core_paths(release_dir), expected)


if __name__ == "__main__":
    unittest.main()
