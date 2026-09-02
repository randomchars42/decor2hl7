from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from decor2hl7 import cda, validate
from decor2hl7.cda.datatypes import (
    base_datatype,
    classify_datatype,
    datatype_definition,
    expand_datatype,
)
from decor2hl7.cda.compile import compile_cda
from decor2hl7.build.mapping import cda_mapping_audit, cda_mapping_proposal
from decor2hl7.bindings import non_null_requirement_problems
from decor2hl7.compile.structural import value_set_members
from decor2hl7.compile.reports import render_cda_mapping_markdown


HL7 = "urn:hl7-org:v3"


def write_datatype_schema(root: Path) -> Path:
    schema = root / "datatypes.xsd"
    schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:complexType name="AD"><xs:sequence>
    <xs:element name="city" type="ADXP" minOccurs="0" maxOccurs="unbounded"/>
    <xs:element name="postalCode" type="ADXP" minOccurs="0" maxOccurs="unbounded"/>
    <xs:element name="streetAddressLine" type="ADXP" minOccurs="0" maxOccurs="unbounded"/>
  </xs:sequence><xs:attribute name="use" type="xs:string"/></xs:complexType>
  <xs:complexType name="ADXP"><xs:simpleContent><xs:extension base="xs:string"/></xs:simpleContent></xs:complexType>
  <xs:complexType name="EN" mixed="true"><xs:sequence>
    <xs:element name="family" type="ENXP" minOccurs="0" maxOccurs="unbounded"/>
    <xs:element name="given" type="ENXP" minOccurs="0" maxOccurs="unbounded"/>
    <xs:element name="prefix" type="ENXP" minOccurs="0" maxOccurs="unbounded"/>
    <xs:element name="suffix" type="ENXP" minOccurs="0" maxOccurs="unbounded"/>
  </xs:sequence><xs:attribute name="use" type="xs:string"/></xs:complexType>
  <xs:complexType name="PN"><xs:complexContent><xs:extension base="EN"/></xs:complexContent></xs:complexType>
  <xs:complexType name="ENXP"><xs:simpleContent><xs:extension base="xs:string"/></xs:simpleContent></xs:complexType>
  <xs:complexType name="IVL_PQ"><xs:sequence>
    <xs:element name="low" type="PQ" minOccurs="0"/>
    <xs:element name="high" type="PQ" minOccurs="0"/>
  </xs:sequence></xs:complexType>
  <xs:complexType name="PQ"><xs:attribute name="value" type="xs:string"/><xs:attribute name="unit" type="xs:string"/></xs:complexType>
</xs:schema>''', encoding="utf-8")
    return schema


def target_at(compiled: dict[str, object], suffix: str) -> tuple[str, dict[str, object]]:
    matches = [
        (str(name), target)
        for name, target in compiled["targets"].items()  # type: ignore[union-attr]
        if str(target.get("path") or "").endswith(suffix)
        and target.get("writable")
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one writable target ending {suffix!r}, got {matches!r}")
    return matches[0]


class CdaDatatypeTests(unittest.TestCase):
    def test_eivl_offset_requires_event_companion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "project.xml"
            timing_path = (
                "hl7:ClinicalDocument/hl7:component/hl7:substanceAdministration/"
                "hl7:effectiveTime[@xsi:type='EIVL_TS']"
            )
            source.write_text(f'''<project xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <concept id="event"><name>Event</name><implementation xpath="{timing_path}/hl7:event">
    <templateLocation id="doc" effectiveDate="2026" xpath="hl7:ClinicalDocument"/>
  </implementation></concept>
  <concept id="offset"><name>Offset</name><implementation xpath="{timing_path}/hl7:offset">
    <templateLocation id="doc" effectiveDate="2026" xpath="hl7:ClinicalDocument"/>
  </implementation></concept>
  <templateAssociation templateId="timing" effectiveDate="2026">
    <concept ref="event" elementId="event-node"/>
    <concept ref="offset" elementId="offset-node"/>
  </templateAssociation>
  <template id="timing" effectiveDate="2026" name="Timing">
    <element name="hl7:substanceAdministration" minimumMultiplicity="0" maximumMultiplicity="1">
      <element name="hl7:effectiveTime[@xsi:type='EIVL_TS']" datatype="EIVL_TS"
               minimumMultiplicity="0" maximumMultiplicity="1">
        <element id="event-node" name="hl7:event" datatype="EIVL.event"
                 minimumMultiplicity="0" maximumMultiplicity="1"/>
        <element id="offset-node" name="hl7:offset" datatype="PQ"
                 minimumMultiplicity="0" maximumMultiplicity="1"/>
      </element>
    </element>
  </template>
  <template id="doc" effectiveDate="2026" name="Document">
    <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:component" contains="timing" flexibility="2026"
               minimumMultiplicity="0" maximumMultiplicity="1"/>
    </element>
  </template>
</project>''', encoding="utf-8")
            offset_field = {
                "name": "Offset", "concept": "offset", "type": "quantity",
                "repeat_chain": [], "value_sets": [], "codes": [],
            }
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {"timing.offset": offset_field},
            }
            compiled = compile_cda([source], model)
            owner_name, _ = target_at(
                compiled, "/hl7:effectiveTime[@xsi:type='EIVL_TS']"
            )
            event_name, _ = target_at(compiled, "/hl7:effectiveTime[@xsi:type='EIVL_TS']/hl7:event")
            offset_name, offset = target_at(compiled, "/hl7:effectiveTime[@xsi:type='EIVL_TS']/hl7:offset")
            self.assertEqual(offset["non_null_requires"], [event_name])
            self.assertEqual(
                offset["non_null_requirement_owners"],
                {event_name: [owner_name]},
            )

            proposal, audit, _, details = cda_mapping_audit(
                model, compiled, [source]
            )
            self.assertIsNone(proposal["fields"]["timing.offset"])
            self.assertEqual(
                audit["fields"]["timing.offset"]["runtime_blocked"],
                f"REQUIRED_COMPANION({event_name})",
            )
            self.assertIn("REQUIRES COMPANION", details)
            guide = render_cda_mapping_markdown(
                model, compiled, proposal, audit
            )
            self.assertIn("required companion missing", guide)
            self.assertIn(
                "Map the required compound-datatype companion", guide
            )
            manual = {"fields": {"timing.offset": offset_name}}
            self.assertIn(
                f"cda-mapping: target {offset_name} requires a non-null companion at {event_name}",
                validate.check_config(
                    model, compiled, {"fields": {"timing.offset": None}}, manual,
                ),
            )
            with self.assertRaisesRegex(ValueError, "without required companion"):
                cda.emit(
                    {
                        "key": "P1", "instances": {},
                        "values": {"timing.offset": {"value": "30", "unit": "min"}},
                    },
                    model, compiled, manual, {},
                )

            paired_model = {
                **model,
                "fields": {
                    "timing.event": {
                        "name": "Event", "concept": "event", "type": "code",
                        "repeat_chain": [], "value_sets": [], "codes": [],
                    },
                    "timing.offset": offset_field,
                },
            }
            paired, _, _, _ = cda_mapping_audit(
                paired_model, compiled, [source]
            )
            self.assertEqual(paired["fields"]["timing.event"], event_name)
            self.assertEqual(paired["fields"]["timing.offset"], offset_name)
            self.assertEqual(
                validate.check_config(
                    paired_model, compiled,
                    {"fields": {"timing.event": None, "timing.offset": None}},
                    paired,
                ),
                [],
            )
            payload, problems = cda.emit(
                {
                    "key": "P1", "instances": {},
                    "values": {
                        "timing.event": {"code": "ACM"},
                        "timing.offset": {"value": "30", "unit": "min"},
                    },
                },
                paired_model, compiled, paired, {},
            )
            self.assertEqual(problems, [])
            document = ET.fromstring(payload)
            self.assertEqual(document.find(f".//{{{HL7}}}event").get("code"), "ACM")
            self.assertEqual(document.find(f".//{{{HL7}}}offset").get("unit"), "min")

            occurrence_problems = non_null_requirement_problems(
                compiled,
                {
                    event_name: [{"code": "ACM"}, None],
                    offset_name: [
                        {"value": "30", "unit": "min"},
                        {"value": "15", "unit": "min"},
                    ],
                },
            )
            self.assertEqual(len(occurrence_problems), 1)
            self.assertIn("occurrence 1", occurrence_problems[0])
            self.assertEqual(
                non_null_requirement_problems(
                    compiled, {owner_name: {"nullFlavor": "NI"}}
                ),
                [],
            )
            self.assertTrue(non_null_requirement_problems(
                compiled, {offset_name: {"nullFlavor": "NI"}}
            ))

    def test_single_element_vocabulary_code_without_system_is_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:statusCode"
      datatype="CS" minimumMultiplicity="1" maximumMultiplicity="1" isMandatory="true">
    <vocabulary code="completed"/>
  </element></element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            target = next(
                target for target in compiled["targets"].values()
                if str(target.get("path") or "").endswith("/hl7:statusCode")
            )
            self.assertEqual(
                target["codes"], [{"code": "completed", "code_system": ""}]
            )
            self.assertFalse(target["writable"])
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            status = ET.fromstring(payload).find(f"{{{HL7}}}statusCode")
            self.assertEqual(status.get("code"), "completed")
            self.assertNotIn("codeSystem", status.attrib)

    def test_neutral_example_default_requires_exact_allowed_terminology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<project>
  <valueSet id="act-status" effectiveDate="2024-01-01">
    <concept code="active" codeSystem="1.2.3" displayName="Active"/>
    <concept code="completed" codeSystem="1.2.3" displayName="Completed"/>
  </valueSet>
  <template id="doc" effectiveDate="2026" name="Document">
    <example type="neutral"><act><statusCode code="active"/></act></example>
    <element name="hl7:act" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:statusCode" datatype="CS" minimumMultiplicity="1"
          maximumMultiplicity="1" isMandatory="true">
        <vocabulary valueSet="act-status" vseffectiveDate="2024-01-01"/>
      </element>
    </element>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {},
                "fields": {
                    "status": {
                        "name": "Status", "concept": "status", "type": "code",
                        "parent": None, "repeat_chain": [], "value_sets": [],
                        "codes": [],
                    },
                },
            }
            compiled = compile_cda([source], model)
            target_name, target = target_at(compiled, "/hl7:statusCode")
            self.assertEqual(target["compiled_default"]["value"], {
                "code": "active", "codeSystem": "1.2.3",
            })
            self.assertEqual(target["compiled_default"]["evidence"], "STRONG")
            self.assertEqual(target["compiled_default"]["value_set"], {
                "id": "act-status", "effective_date": "2024-01-01",
            })
            self.assertTrue(any(
                item.get("source") == "template-example"
                for item in target["provenance"]
            ))

            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            status = ET.fromstring(payload).find(f".//{{{HL7}}}statusCode")
            self.assertEqual(
                (status.get("code"), status.get("codeSystem")),
                ("active", "1.2.3"),
            )

            payload, problems = cda.emit(
                {
                    "key": "P1",
                    "values": {"status": {"code": "completed", "codeSystem": "1.2.3"}},
                    "instances": {},
                },
                model, compiled, {"fields": {"status": target_name}}, {},
            )
            self.assertEqual(problems, [])
            status = ET.fromstring(payload).find(f".//{{{HL7}}}statusCode")
            self.assertEqual(status.get("code"), "completed")

    def test_neutral_example_outside_allowed_set_is_not_a_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<project>
  <valueSet id="act-status" effectiveDate="2024-01-01">
    <concept code="completed" codeSystem="1.2.3"/>
  </valueSet>
  <template id="doc" effectiveDate="2026" name="Document">
    <example type="neutral"><act><statusCode code="active"/></act></example>
    <element name="hl7:act"><element name="hl7:statusCode" datatype="CS"
        minimumMultiplicity="1" maximumMultiplicity="1" isMandatory="true">
      <vocabulary valueSet="act-status" vseffectiveDate="2024-01-01"/>
    </element></element>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            target = next(
                value for value in compiled["targets"].values()
                if str(value.get("path") or "").endswith("/hl7:statusCode")
            )
            self.assertNotIn("compiled_default", target)
            with self.assertRaisesRegex(ValueError, "mandatory CDA element"):
                cda.emit(
                    {"key": "P1", "values": {}, "instances": {}},
                    model, compiled, {"fields": {}}, {},
                )

    def test_coded_original_text_is_completed_from_compiled_datatype_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
    <element name="hl7:value" datatype="CD" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:originalText" datatype="ST" minimumMultiplicity="0" maximumMultiplicity="1"/>
    </element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {},
                "fields": {
                    "coded": {"type": "code", "repeat_chain": []},
                    "wording": {"type": "text", "repeat_chain": []},
                },
            }
            compiled = compile_cda([source], model)
            value_name, _ = target_at(compiled, "/hl7:value")
            text_name, text_target = target_at(
                compiled, "/hl7:value/hl7:originalText"
            )
            self.assertEqual(text_target["content_role"], "coded_original_text")

            record = {
                "key": "P1",
                "values": {
                    "coded": {
                        "raw": "Original wording", "canonical": "X",
                        "code": "X", "codeSystem": "1.2.3",
                    },
                },
                "instances": {},
            }
            payload, problems = cda.emit(
                record, model, compiled, {"fields": {"coded": value_name}}, {},
            )
            self.assertEqual(problems, [])
            original = ET.fromstring(payload).find(
                f".//{{{HL7}}}value/{{{HL7}}}originalText"
            )
            self.assertIsNotNone(original)
            self.assertEqual(original.text, "Original wording")

            record["values"]["wording"] = "Reviewed wording"
            payload, _ = cda.emit(
                record, model, compiled,
                {"fields": {"coded": value_name, "wording": text_name}}, {},
            )
            original = ET.fromstring(payload).find(
                f".//{{{HL7}}}value/{{{HL7}}}originalText"
            )
            self.assertEqual(original.text, "Reviewed wording")

    def test_artdecor_path_predicates_do_not_leak_into_xml_qnames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
    <element name="hl7:id[1]" datatype="II" minimumMultiplicity="1"
        maximumMultiplicity="1" isMandatory="true"/>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            identifier = root.find(f"{{{HL7}}}id")
            self.assertIsNotNone(identifier)
            self.assertNotIn("[", payload.decode("utf-8"))

    def test_neutral_example_can_select_from_multiple_explicit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<project>
  <template id="prototype" effectiveDate="2020" name="Prototype">
    <element name="hl7:act"><element name="hl7:statusCode" datatype="CS">
      <vocabulary valueSet="broad-status" vseffectiveDate="2020"/>
    </element></element>
  </template>
  <template id="doc" effectiveDate="2026" name="Document">
    <relationship type="SPEC" template="prototype" flexibility="2020"/>
    <example type="neutral"><act><statusCode code="active"/></act></example>
    <element name="hl7:act"><element name="hl7:statusCode" datatype="CS"
        minimumMultiplicity="1" maximumMultiplicity="1" isMandatory="true">
      <vocabulary code="active"/><vocabulary code="completed"/>
    </element></element>
  </template>
</project>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            _, target = target_at(compiled, "/hl7:statusCode")
            self.assertEqual(target["value_sets"], [])
            self.assertEqual(target["value_set_bindings"], [])
            self.assertEqual(
                target["compiled_default"]["value"], {"code": "active"}
            )
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            status = ET.fromstring(payload).find(f".//{{{HL7}}}statusCode")
            self.assertEqual(status.get("code"), "active")

    def test_xsd_default_completes_explicit_artdecor_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            schema = root_dir / "POCD_MT000040.xsd"
            schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="entry" type="POCD_MT000040.Entry"/>
  <xs:complexType name="POCD_MT000040.Entry">
    <xs:attribute name="typeCode" type="cs" use="required" default="COMP"/>
  </xs:complexType>
</xs:schema>''', encoding="utf-8")
            source = root_dir / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:entry"
      minimumMultiplicity="1" maximumMultiplicity="1">
    <attribute name="typeCode" isOptional="false"/>
  </element></element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda(
                [source], model, core_definition_paths=[schema]
            )
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            entry = ET.fromstring(payload).find(f"{{{HL7}}}entry")
            self.assertEqual(entry.get("typeCode"), "COMP")

    def test_generated_identifiers_complete_only_active_repeat_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><attribute name="classCode" value="DOCCLIN"/>
    <element name="hl7:component" minimumMultiplicity="0" maximumMultiplicity="*">
      <element name="hl7:observation" minimumMultiplicity="1" maximumMultiplicity="1">
        <element name="hl7:id" datatype="II" minimumMultiplicity="1" maximumMultiplicity="1"/>
        <element name="hl7:value" datatype="ST" minimumMultiplicity="1" maximumMultiplicity="1"/>
      </element>
    </element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {},
                "fields": {"fact": {
                    "name": "Fact", "concept": "fact", "type": "text",
                    "parent": None, "repeat_chain": ["facts"],
                    "value_sets": [], "codes": [],
                }},
            }
            compiled = compile_cda([source], model)
            value_target, _ = target_at(compiled, "/hl7:observation/hl7:value")
            id_target, identifier = target_at(compiled, "/hl7:observation/hl7:id")
            self.assertEqual(identifier["system_value"], "generated_identifier")
            mapping = {"fields": {"fact": value_target}}
            site = {"identifiers": {"document_root": "1.2.3.4"}}

            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, mapping, site,
            )
            self.assertEqual(problems, [])
            self.assertEqual(
                ET.fromstring(payload).findall(f".//{{{HL7}}}observation"), []
            )

            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {"facts": [
                    {"key": "1", "values": {"fact": "one"}, "instances": {}},
                    {"key": "2", "values": {"fact": "two"}, "instances": {}},
                ]}},
                model, compiled, mapping, site,
            )
            self.assertEqual(problems, [])
            ids = ET.fromstring(payload).findall(f".//{{{HL7}}}id")
            self.assertEqual(len(ids), 2)
            self.assertEqual({item.get("root") for item in ids}, {"1.2.3.4"})
            self.assertEqual(len({item.get("extension") for item in ids}), 2)
            self.assertIn(id_target, compiled["targets"])

    def test_optional_fixed_attribute_is_writable_only_with_fixed_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:observation"
      minimumMultiplicity="1" maximumMultiplicity="1">
    <attribute name="classCode" value="OBS" isOptional="false"/>
    <attribute name="nullFlavor" value="NI" isOptional="true"/>
  </element></element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {},
                "fields": {
                    "unknown": {
                        "name": "Unknown", "concept": "unknown", "type": "text",
                        "parent": None, "repeat_chain": [], "value_sets": [], "codes": [],
                    },
                },
            }
            compiled = compile_cda([source], model)
            target_name, target = target_at(compiled, "/hl7:observation/@nullFlavor")
            self.assertTrue(target["writable"])
            self.assertTrue(target["conditional_fixed"])
            mapping = {"fields": {"unknown": target_name}}

            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, mapping, {},
            )
            self.assertEqual(problems, [])
            observation = ET.fromstring(payload).find(f".//{{{HL7}}}observation")
            self.assertNotIn("nullFlavor", observation.attrib)

            payload, problems = cda.emit(
                {"key": "P1", "values": {"unknown": "NI"}, "instances": {}},
                model, compiled, mapping, {},
            )
            self.assertEqual(problems, [])
            observation = ET.fromstring(payload).find(f".//{{{HL7}}}observation")
            self.assertEqual(observation.get("nullFlavor"), "NI")

            with self.assertRaisesRegex(ValueError, "fixed to 'NI'"):
                cda.emit(
                    {"key": "P1", "values": {"unknown": "UNK"}, "instances": {}},
                    model, compiled, mapping, {},
                )

    def test_compiled_header_time_roles_supply_document_generation_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:effectiveTime" datatype="TS" minimumMultiplicity="1"
             maximumMultiplicity="1" conformance="R"/>
    <element name="hl7:author" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:time" datatype="TS" minimumMultiplicity="1"
               maximumMultiplicity="1" conformance="R"/>
    </element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            roles = {
                target["path"]: target.get("system_value")
                for target in compiled["targets"].values()
                if target.get("system_value")
            }
            self.assertEqual(roles, {
                "hl7:ClinicalDocument/hl7:effectiveTime": "document_generation_time",
                "hl7:ClinicalDocument/hl7:author/hl7:time": "document_generation_time",
            })
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            values = [
                root.find(f"{{{HL7}}}effectiveTime").get("value"),
                root.find(f"{{{HL7}}}author/{{{HL7}}}time").get("value"),
            ]
            self.assertRegex(values[0], r"^\d{14}\+0000$")
            self.assertEqual(values[0], values[1])

    def test_required_complex_value_uses_only_compiled_null_flavor_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:name" datatype="PN" minimumMultiplicity="1"
             maximumMultiplicity="1" conformance="R">
      <attribute name="nullFlavor" isOptional="true"/>
      <element name="hl7:given" datatype="ST" minimumMultiplicity="0"
               maximumMultiplicity="1"/>
    </element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            name = ET.fromstring(payload).find(f"{{{HL7}}}name")
            self.assertEqual(name.get("nullFlavor"), "NI")

            compiled["document"][0]["children"][0]["attributes"] = []
            with self.assertRaisesRegex(ValueError, "required complex CDA element"):
                cda.emit(
                    {"key": "P1", "values": {}, "instances": {}},
                    model, compiled, {"fields": {}}, {},
                )

    def test_compiled_custodian_roles_use_site_organization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:custodian" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:assignedCustodian" minimumMultiplicity="1" maximumMultiplicity="1">
        <element name="hl7:representedCustodianOrganization" minimumMultiplicity="1" maximumMultiplicity="1">
          <element name="hl7:id" datatype="II" minimumMultiplicity="1" maximumMultiplicity="1"/>
          <element name="hl7:name" datatype="ST" minimumMultiplicity="1" maximumMultiplicity="1"/>
        </element>
      </element>
    </element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}},
                {"organization": {"oid": "1.2.3.4", "name": "Example ED"}},
            )
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            org = root.find(
                f"{{{HL7}}}custodian/{{{HL7}}}assignedCustodian/"
                f"{{{HL7}}}representedCustodianOrganization"
            )
            self.assertEqual(org.find(f"{{{HL7}}}id").get("root"), "1.2.3.4")
            self.assertEqual(org.find(f"{{{HL7}}}name").text, "Example ED")

    def test_custodian_roles_address_one_physical_reused_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "templates.xml"
            source.write_text('''<decor>
<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:author" minimumMultiplicity="0" maximumMultiplicity="1">
      <element name="hl7:assignedAuthor" minimumMultiplicity="1" maximumMultiplicity="1">
        <include ref="organization" flexibility="2026"/>
      </element>
    </element>
    <element name="hl7:custodian" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:assignedCustodian" minimumMultiplicity="1" maximumMultiplicity="1">
        <element name="hl7:representedCustodianOrganization"
                 minimumMultiplicity="1" maximumMultiplicity="1">
          <include ref="organization" flexibility="2026"/>
        </element>
      </element>
    </element>
  </element>
</template>
<template id="organization" effectiveDate="2026" name="OrganizationElements">
  <element name="hl7:id" datatype="II" minimumMultiplicity="1"
           maximumMultiplicity="1"/>
  <element name="hl7:name" datatype="ST" minimumMultiplicity="1"
           maximumMultiplicity="1"/>
</template>
</decor>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            shared = compiled["targets"]["OrganizationElements.id"]
            self.assertEqual(len(shared["locations"]), 2)
            self.assertFalse(shared["writable"])

            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}},
                {"organization": {"oid": "1.2.3.4", "name": "Example ED"}},
            )
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            self.assertIsNone(root.find(f"{{{HL7}}}author"))
            org = root.find(
                f"{{{HL7}}}custodian/{{{HL7}}}assignedCustodian/"
                f"{{{HL7}}}representedCustodianOrganization"
            )
            self.assertEqual(org.find(f"{{{HL7}}}id").get("root"), "1.2.3.4")
            self.assertEqual(org.find(f"{{{HL7}}}name").text, "Example ED")

    def test_active_section_title_and_narrative_follow_compiled_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document"
    displayName="Clinical facts">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:component"><element name="hl7:structuredBody">
      <element name="hl7:component" minimumMultiplicity="0" maximumMultiplicity="1">
        <element name="hl7:section" minimumMultiplicity="1" maximumMultiplicity="1">
          <element name="hl7:title" datatype="ST" minimumMultiplicity="1" maximumMultiplicity="1"/>
          <element name="hl7:text" datatype="ST" minimumMultiplicity="1" maximumMultiplicity="1"/>
          <element name="hl7:entry" minimumMultiplicity="0" maximumMultiplicity="1">
            <element name="hl7:observation"><element name="hl7:value" datatype="ST"/></element>
          </element>
        </element>
      </element>
    </element></element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {},
                "fields": {"fact": {
                    "name": "Fact", "concept": "fact", "type": "text",
                    "parent": None, "repeat_chain": [], "value_sets": [], "codes": [],
                }},
            }
            compiled = compile_cda([source], model)
            value_target, _ = target_at(compiled, "/hl7:observation/hl7:value")
            payload, problems = cda.emit(
                {"key": "P1", "values": {"fact": "mapped fact"}, "instances": {}},
                model, compiled, {"fields": {"fact": value_target}}, {},
            )
            self.assertEqual(problems, [])
            section = ET.fromstring(payload).find(f".//{{{HL7}}}section")
            self.assertEqual(section.find(f"{{{HL7}}}title").text, "Clinical facts")
            self.assertEqual(section.find(f"{{{HL7}}}text").text, "mapped fact")

    def test_single_vocabulary_code_fixes_required_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1" isMandatory="true">
    <element name="hl7:realmCode" datatype="CS" minimumMultiplicity="1" maximumMultiplicity="1" isMandatory="true">
      <attribute name="code" datatype="cs" isOptional="false"><vocabulary code="DE"/></attribute>
    </element>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda([source], model)
            realm = next(
                target for target in compiled["targets"].values()  # type: ignore[union-attr]
                if str(target.get("path") or "") == "hl7:ClinicalDocument/hl7:realmCode/@code"
            )
            self.assertEqual(realm["fixed"], {"value": "DE"})
            self.assertFalse(realm["writable"])
            payload, problems = cda.emit(
                {"key": "P1", "values": {}, "instances": {}},
                model, compiled, {"fields": {}}, {},
            )
            self.assertEqual(problems, [])
            node = ET.fromstring(payload).find(f"{{{HL7}}}realmCode")
            self.assertEqual(node.get("code"), "DE")

    def test_reused_artdecor_ids_keep_path_specific_fixed_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument" id="root">
    <element name="hl7:participant[hl7:templateId[@root='branch-a']]" id="participant">
      <element name="hl7:templateId" datatype="II" id="template-id">
        <attribute name="root" value="branch-a" datatype="uid" id="template-root"/>
      </element>
    </element>
    <element name="hl7:participant[hl7:templateId[@root='branch-b']]" id="participant">
      <element name="hl7:templateId" datatype="II" id="template-id">
        <attribute name="root" value="branch-b" datatype="uid" id="template-root"/>
      </element>
    </element>
  </element>
</template>''', encoding="utf-8")
            compiled = compile_cda(
                [source],
                {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
            )
            template_ids = [
                target for target in compiled["targets"].values()  # type: ignore[union-attr]
                if str(target.get("path") or "").endswith("/hl7:templateId")
            ]
            self.assertEqual(len(template_ids), 2)
            self.assertEqual(
                {tuple(target["locations"]): target["fixed"]["root"] for target in template_ids},
                {("0.0.0",): "branch-a", ("0.1.0",): "branch-b"},
            )
            self.assertEqual(validate.verify_compiled_against_artdecor(compiled, [source]), [])

    def test_value_set_versions_and_cda_binding_identity_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "project.xml"
            source.write_text('''<project>
  <valueSet id="eyes" effectiveDate="2015-03-01"><concept code="362502000" codeSystem="2.16.840.1.113883.6.96" displayName="Entire right eye"/></valueSet>
  <valueSet id="eyes" effectiveDate="2015-11-17"><concept code="R" codeSystem="1.2.276.0.76.3.1.195.5.48" displayName="Auge rechts"><designation language="en-US" displayName="Right eye"/></concept></valueSet>
  <template id="doc" effectiveDate="2026" name="Document"><element name="hl7:ClinicalDocument">
    <element name="hl7:targetSiteCode" datatype="CD"><vocabulary valueSet="eyes" vseffectiveDate="2015-11-17"/></element>
  </element></template>
</project>''', encoding="utf-8")
            members = value_set_members([source])
            self.assertEqual(members[("eyes", "2015-03-01")][0]["code"], "362502000")
            self.assertEqual(members[("eyes", "2015-11-17")][0]["code"], "R")
            compiled = compile_cda(
                [source],
                {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
            )
            _, target = target_at(compiled, "/hl7:targetSiteCode")
            self.assertEqual(target["value_set_bindings"], [{
                "id": "eyes", "effective_date": "2015-11-17", "flexibility": "",
            }])

    def test_seven_real_fixed_unit_quantities_keep_scalar_values_writable(self) -> None:
        fields = (
            ("temperature", "Körperkerntemperatur", "Cel", 37.2),
            ("gcs_eye", "Glasgow Coma Scale: Augen öffnen", "1", 4),
            ("gcs_verbal", "Glasgow Coma Scale: Verbale Reaktion", "1", 5),
            ("gcs_motor", "Glasgow Coma Scale: Motorische Reaktion", "1", 6),
            ("gcs_total", "Glasgow Coma Scale: Gesamtwert", "1", 15),
            ("rankin", "Modified Rankin Scale", "1", 2),
            ("pain", "Schmerzstärke", "1", 3),
        )
        for field_path, label, unit, scalar in fields:
            with self.subTest(field=label), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "template.xml"
                source.write_text(f'''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:observation">
    <element name="hl7:value" datatype="PQ">
      <attribute name="value" isOptional="false"/>
      <attribute name="unit" value="{unit}"/>
    </element>
  </element></element>
</template>''', encoding="utf-8")
                model = {"meta": {"template_id": "doc", "template_effective_date": "2026"}, "groups": {}, "fields": {
                    field_path: {"name": label, "concept": field_path, "type": "quantity", "parent": None, "repeat_chain": [], "value_sets": [], "codes": []},
                }}
                compiled = compile_cda([source], model)
                target_name, target = target_at(compiled, "/hl7:observation/hl7:value")
                self.assertEqual(target["unit"], unit)
                payload, problems = cda.emit(
                    {"key": "P1", "values": {field_path: scalar}, "instances": {}},
                    model, compiled, {"fields": {field_path: target_name}}, {},
                )
                self.assertEqual(problems, [])
                value = ET.fromstring(payload).find(f".//{{{HL7}}}value")
                self.assertEqual((value.get("value"), value.get("unit")), (str(scalar), unit))

    def test_cda_structural_classes_expand_through_datatypes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema = root / "POCD_MT000040.xsd"
            schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="observation" type="POCD_MT000040.Observation"/>
  <xs:element name="procedure" type="POCD_MT000040.Procedure"/>
  <xs:element name="substanceAdministration" type="POCD_MT000040.SubstanceAdministration"/>
  <xs:complexType name="POCD_MT000040.Observation"><xs:sequence>
    <xs:element name="code" type="CD" minOccurs="0"/>
    <xs:element name="value" type="ANY" minOccurs="0" maxOccurs="unbounded"/>
  </xs:sequence></xs:complexType>
  <xs:complexType name="POCD_MT000040.Procedure"><xs:sequence>
    <xs:element name="code" type="CD" minOccurs="0"/>
  </xs:sequence></xs:complexType>
  <xs:complexType name="POCD_MT000040.SubstanceAdministration"><xs:sequence>
    <xs:element name="doseQuantity" type="IVL_PQ" minOccurs="0"/>
  </xs:sequence></xs:complexType>
</xs:schema>''', encoding="utf-8")
            template = root / "template.xml"
            template.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:component">
    <element name="hl7:observation"/><element name="hl7:procedure"/>
    <element name="hl7:substanceAdministration"/>
  </element></element>
</template>''', encoding="utf-8")
            datatype_schema = write_datatype_schema(root)
            compiled = compile_cda(
                [template],
                {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
                core_definition_paths=[schema, datatype_schema],
            )
            _, observation = target_at(compiled, "/hl7:observation/hl7:code")
            _, procedure = target_at(compiled, "/hl7:procedure/hl7:code")
            _, dose = target_at(
                compiled,
                "/hl7:substanceAdministration/hl7:doseQuantity/hl7:low",
            )
            self.assertEqual(observation["value_representation"]["kind"], "coded")
            self.assertEqual(procedure["value_representation"]["kind"], "coded")
            self.assertEqual(dose["value_representation"]["kind"], "quantity")
            self.assertTrue(any(
                item.get("source") == "cda-rim"
                for item in dose["provenance"]
            ))
            observation_value = [
                target for target in compiled["targets"].values()  # type: ignore[union-attr]
                if str(target.get("path") or "").endswith("/hl7:observation/hl7:value")
            ]
            self.assertEqual(len(observation_value), 8)
            self.assertEqual(
                sum(not target.get("writable") for target in observation_value), 1,
            )
            self.assertEqual(
                {
                    target.get("value_representation", {}).get("xsi_type")
                    for target in observation_value if target.get("writable")
                },
                {"BL", "CD", "II", "INT", "PQ", "ST", "TS"},
            )

    def test_cda_particle_overlay_ignores_artdecor_predicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema = root / "POCD_MT000040.xsd"
            schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="substanceAdministration" type="POCD_MT000040.SubstanceAdministration"/>
  <xs:complexType name="POCD_MT000040.SubstanceAdministration"><xs:sequence>
    <xs:element name="entryRelationship" type="POCD_MT000040.EntryRelationship" minOccurs="0" maxOccurs="unbounded"/>
  </xs:sequence></xs:complexType>
  <xs:complexType name="POCD_MT000040.EntryRelationship"><xs:sequence>
    <xs:element name="sequenceNumber" type="INT" minOccurs="0"/>
  </xs:sequence></xs:complexType>
</xs:schema>''', encoding="utf-8")
            template = root / "template.xml"
            template.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:substanceAdministration">
    <choice maximumMultiplicity="1">
      <element name="hl7:entryRelationship[exists(hl7:substanceAdministration)]">
        <element name="hl7:sequenceNumber"/>
      </element>
      <element name="hl7:entryRelationship[exists(hl7:observation)]"/>
    </choice>
  </element>
</template>''', encoding="utf-8")
            compiled = compile_cda(
                [template],
                {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
                core_definition_paths=[schema, write_datatype_schema(root)],
            )
            _, sequence = target_at(
                compiled,
                "entryRelationship[exists(hl7:substanceAdministration)]/hl7:sequenceNumber",
            )
            self.assertEqual(sequence["datatype"], "INT")
            self.assertEqual(sequence["value_representation"]["kind"], "quantity")
            self.assertEqual(len(sequence["locations"]), 1)
            self.assertTrue(any(
                item.get("source") == "template + cda-rim"
                and item.get("datatype_part") == "hl7:sequenceNumber"
                for item in sequence["provenance"]
            ))

    def test_contained_template_satisfies_structural_child_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema = root / "POCD_MT000040.xsd"
            schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="ClinicalDocument" type="POCD_MT000040.ClinicalDocument"/>
  <xs:complexType name="POCD_MT000040.ClinicalDocument"><xs:sequence>
    <xs:element name="component" type="POCD_MT000040.Component3" minOccurs="1" maxOccurs="unbounded"/>
  </xs:sequence></xs:complexType>
  <xs:complexType name="POCD_MT000040.Component3"><xs:sequence>
    <xs:element name="section" type="POCD_MT000040.Section"/>
  </xs:sequence></xs:complexType>
  <xs:complexType name="POCD_MT000040.Section"><xs:sequence>
    <xs:element name="title" type="ST"/>
    <xs:element name="text" type="ST" minOccurs="0"/>
  </xs:sequence></xs:complexType>
</xs:schema>''', encoding="utf-8")
            template = root / "template.xml"
            template.write_text('''<project>
  <template id="special-section" effectiveDate="2026" name="SpecialSection">
    <element name="hl7:section" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:title" datatype="ST" minimumMultiplicity="1"
          maximumMultiplicity="1"><text>Special section</text></element>
      <element name="hl7:text" datatype="ST" minimumMultiplicity="0"
          maximumMultiplicity="1"/>
    </element>
  </template>
  <template id="doc" effectiveDate="2026" name="Document">
    <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:component" contains="special-section"
          minimumMultiplicity="1" maximumMultiplicity="1"/>
    </element>
  </template>
</project>''', encoding="utf-8")
            compiled = compile_cda(
                [template],
                {
                    "meta": {
                        "template_id": "doc",
                        "template_effective_date": "2026",
                    },
                    "groups": {},
                    "fields": {
                        "note": {"type": "text", "repeat_chain": []},
                    },
                },
                core_definition_paths=[schema],
            )

            sections: list[dict[str, object]] = []

            def collect(nodes: list[dict[str, object]]) -> None:
                for node in nodes:
                    if node.get("name") == "hl7:section":
                        sections.append(node)
                    collect(list(node.get("children", [])))

            collect(compiled["document"])
            self.assertEqual(len(sections), 1)
            self.assertEqual(sections[0]["datatype"], "POCD_MT000040.Section")
            self.assertTrue(any(
                item.get("source") == "template + cda-rim"
                for item in sections[0]["provenance"]
            ))
            text_target, _ = target_at(
                compiled, "hl7:section/hl7:text"
            )

            payload, problems = cda.emit(
                {
                    "key": "P1",
                    "values": {"note": "Rendered once"},
                    "instances": {},
                },
                {
                    "groups": {},
                    "fields": {
                        "note": {"type": "text", "repeat_chain": []},
                    },
                },
                compiled,
                {"fields": {"note": text_target}},
                {},
            )
            self.assertEqual(problems, [])
            rendered = ET.fromstring(payload)
            rendered_sections = rendered.findall(f".//{{{HL7}}}section")
            self.assertEqual(len(rendered_sections), 1)
            self.assertEqual(
                rendered_sections[0].find(f"{{{HL7}}}title").text,
                "Special section",
            )
            self.assertEqual(
                rendered_sections[0].find(f"{{{HL7}}}text").text,
                "Rendered once",
            )

    def test_catalogue_resolves_aliases_and_complex_inheritance(self) -> None:
        self.assertEqual(base_datatype("TS.DATE.MIN"), "TS")
        self.assertEqual(classify_datatype("TS.DATETIME.MIN"), "alias")
        self.assertEqual(classify_datatype("ClinicalDocument"), "structural")
        self.assertEqual(classify_datatype("NOT_A_DATATYPE"), "unsupported")
        self.assertEqual(expand_datatype("PN").base, "EN")
        self.assertEqual(expand_datatype("PN").parts, ())
        self.assertEqual(base_datatype("EIVL.event"), "CD")
        self.assertEqual(expand_datatype("SXPR_TS").kind.value, "complex")
        self.assertEqual(
            datatype_definition("TS.DATE.MIN").profile,
            "DATE.MIN",
        )

    def test_url_uses_the_cda_value_attribute(self) -> None:
        representation = expand_datatype("URL").value_representation
        self.assertIsNotNone(representation)
        self.assertEqual(representation.kind.value, "attribute")
        self.assertEqual(representation.attribute, "value")

    def test_any_exposes_typed_writable_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:observation"><element name="hl7:value" datatype="ANY"
      minimumMultiplicity="0" maximumMultiplicity="1"/></element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {
                    "result": {"type": "text", "repeat_chain": []},
                },
            }
            compiled = compile_cda([source], model)
            choices = [
                (name, target) for name, target in compiled["targets"].items()
                if target.get("declared_datatype") == "ANY"
                and target.get("datatype") == "ST"
            ]
            self.assertEqual(len(choices), 1)
            name, target = choices[0]
            self.assertTrue(target["writable"])
            self.assertEqual(target["value_representation"]["xsi_type"], "ST")
            self.assertEqual(
                validate.verify_compiled_against_artdecor(compiled, [source]), []
            )

            payload, problems = cda.emit(
                {"key": "P1", "values": {"result": "free text"}, "instances": {}},
                model, compiled, {"fields": {"result": name}}, {},
            )
            self.assertEqual(problems, [])
            value = ET.fromstring(payload).find(f".//{{{HL7}}}value")
            self.assertEqual(value.text, "free text")
            self.assertEqual(
                value.get("{http://www.w3.org/2001/XMLSchema-instance}type"),
                "ST",
            )

    def test_xsd_mixed_content_makes_complex_root_text_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            source = root_dir / "template.xml"
            schema = write_datatype_schema(root_dir)
            source.write_text('''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:name" datatype="EN" minimumMultiplicity="0" maximumMultiplicity="1"/>
  </element>
</template>''', encoding="utf-8")
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026"},
                "groups": {}, "fields": {},
            }
            compiled = compile_cda(
                [source], model, core_definition_paths=[schema]
            )
            _, target = target_at(compiled, "/hl7:name")
            self.assertEqual(target["datatype"], "EN")
            self.assertEqual(
                target["value_representation"],
                {"kind": "element_text", "logical_types": ["text"]},
            )
            self.assertTrue(target["has_children"])

    def test_ad_and_pn_expand_map_and_render_without_special_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            source = root_dir / "project.xml"
            schema = write_datatype_schema(root_dir)
            source.write_text(
                '''<project>
  <concept id="address"><name>Anschrift</name></concept>
  <concept id="postcode"><name>Postleitzahl</name><relationship type="SPEC" ref="postal-base"/></concept>
  <concept id="postal-base"><name>Postleitzahl</name></concept>
  <concept id="postal-three"><name language="en-US">Postal code three digits</name><relationship type="ADAPT" ref="postal-base"/></concept>
  <concept id="given"><implementation xpath="hl7:ClinicalDocument/hl7:recordTarget/hl7:patient/hl7:name/hl7:given">
    <templateLocation id="doc" effectiveDate="2026-01-01" xpath="hl7:ClinicalDocument"/>
  </implementation></concept>
  <templateAssociation templateId="doc" effectiveDate="2026-01-01">
    <concept ref="address" elementId="record-target"/>
  </templateAssociation>
  <template id="doc" effectiveDate="2026-01-01" name="Document">
    <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
      <element id="record-target" name="hl7:recordTarget" minimumMultiplicity="0" maximumMultiplicity="1">
        <element name="hl7:addr" datatype="AD" minimumMultiplicity="0" maximumMultiplicity="1"/>
        <element name="hl7:patient" minimumMultiplicity="0" maximumMultiplicity="1">
          <element name="hl7:name" datatype="PN" minimumMultiplicity="0" maximumMultiplicity="1"/>
        </element>
      </element>
    </element>
  </template>
</project>''',
                encoding="utf-8",
            )
            model = {
                "meta": {"template_id": "doc", "template_effective_date": "2026-01-01"},
                "groups": {
                    "patient.anschrift": {
                        "name": "Anschrift", "concept": "address", "parent": None,
                        "repeat_chain": [], "repeating": False,
                    },
                },
                "fields": {
                    "patient.anschrift.postleitzahl": {
                        "name": "Postleitzahl", "concept": "postcode", "type": "text",
                        "value_sets": [], "codes": [], "repeat_chain": [], "parent": "patient.anschrift",
                    },
                    "patient.name.vorname": {
                        "name": "Vorname", "concept": "given", "type": "text",
                        "value_sets": [], "codes": [], "repeat_chain": [], "parent": None,
                    },
                },
            }
            compiled = compile_cda([source], model, core_definition_paths=[schema])
            postcode_name, postcode = target_at(compiled, "/hl7:addr/hl7:postalCode")
            given_name, given = target_at(compiled, "/hl7:name/hl7:given")
            self.assertEqual(postcode["value_representation"]["kind"], "element_text")  # type: ignore[index]
            self.assertEqual(given["value_representation"]["kind"], "element_text")  # type: ignore[index]
            self.assertTrue(any(
                item.get("source") == "datatype" and item.get("datatype") == "AD"
                for item in postcode["provenance"]  # type: ignore[union-attr]
            ))
            self.assertEqual(compiled["datatype_inventory"]["datatype"], ["AD"])  # type: ignore[index]
            self.assertEqual(compiled["datatype_inventory"]["alias"], ["PN"])  # type: ignore[index]

            proposal, report = cda_mapping_proposal(model, compiled, [source])
            self.assertEqual(
                proposal["fields"]["patient.anschrift.postleitzahl"], postcode_name,
                report,
            )
            self.assertEqual(proposal["fields"]["patient.name.vorname"], given_name)

            record = {
                "key": "P1",
                "values": {
                    "patient.anschrift.postleitzahl": "10115",
                    "patient.name.vorname": "Ada",
                },
                "instances": {},
            }
            payload, problems = cda.emit(record, model, compiled, proposal, {})
            self.assertEqual(problems, [])
            root = ET.fromstring(payload)
            self.assertEqual(root.find(f".//{{{HL7}}}postalCode").text, "10115")
            self.assertEqual(root.find(f".//{{{HL7}}}given").text, "Ada")

    def test_art_decor_constraints_overlay_generic_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            source = root_dir / "template.xml"
            schema = write_datatype_schema(root_dir)
            source.write_text(
                '''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument">
    <element name="hl7:addr" datatype="AD">
      <element name="hl7:postalCode" datatype="ST" minimumMultiplicity="1"
               maximumMultiplicity="1" conformance="R"/>
    </element>
  </element>
</template>''',
                encoding="utf-8",
            )
            compiled = compile_cda(
                [source],
                {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
                core_definition_paths=[schema],
            )
            _, postcode = target_at(compiled, "/hl7:addr/hl7:postalCode")
            _, city = target_at(compiled, "/hl7:addr/hl7:city")
            self.assertEqual((postcode["min"], postcode["max"], postcode["conformance"]), (1, 1, "R"))
            self.assertEqual((city["min"], city["max"]), (0, None))
            sources = {item.get("source") for item in postcode["provenance"]}  # type: ignore[union-attr]
            self.assertIn("template", sources)
            self.assertIn("template + datatype", sources)

    def test_unknown_datatype_fails_with_identity_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "template.xml"
            source.write_text(
                '''<template id="doc" effectiveDate="2026" name="Document">
  <element name="hl7:ClinicalDocument"><element name="hl7:mystery" datatype="ABC"/></element>
</template>''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "unsupported HL7 V3 datatype.*ABC"
            ):
                compile_cda(
                    [source],
                    {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
                )


if __name__ == "__main__":
    unittest.main()
