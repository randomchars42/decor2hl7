from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from decor2hl7 import cda
from decor2hl7.cda.datatypes import (
    base_datatype,
    classify_datatype,
    datatype_definition,
    expand_datatype,
)
from decor2hl7.cda.compile import compile_cda
from decor2hl7.build.mapping import cda_mapping_proposal


HL7 = "urn:hl7-org:v3"


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
    def test_cda_structural_classes_expand_through_datatypes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema = root / "POCD_MT000040.xsd"
            schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:complexType name="POCD_MT000040.Observation"><xs:sequence>
    <xs:element name="value" type="CD" minOccurs="0" maxOccurs="unbounded"/>
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
            compiled = compile_cda(
                [template],
                {"meta": {"template_id": "doc", "template_effective_date": "2026"}},
                core_definition_paths=[schema],
            )
            _, observation = target_at(compiled, "/hl7:observation/hl7:value")
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

    def test_catalogue_resolves_aliases_and_complex_inheritance(self) -> None:
        self.assertEqual(base_datatype("TS.DATE.MIN"), "TS")
        self.assertEqual(classify_datatype("TS.DATETIME.MIN"), "alias")
        self.assertEqual(classify_datatype("ClinicalDocument"), "structural")
        self.assertEqual(classify_datatype("NOT_A_DATATYPE"), "unsupported")
        self.assertEqual(expand_datatype("PN").base, "EN")
        self.assertEqual(
            {part.name for part in expand_datatype("PN").parts},
            {"hl7:delimiter", "hl7:family", "hl7:given", "hl7:prefix", "hl7:suffix"},
        )
        self.assertEqual(
            datatype_definition("TS.DATE.MIN").profile,
            "DATE.MIN",
        )

    def test_ad_and_pn_expand_map_and_render_without_special_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "project.xml"
            source.write_text(
                '''<project>
  <concept id="postcode"><implementation xpath="hl7:ClinicalDocument/hl7:recordTarget/hl7:addr/hl7:postalCode">
    <templateLocation id="doc" effectiveDate="2026-01-01" xpath="hl7:ClinicalDocument"/>
  </implementation></concept>
  <concept id="given"><implementation xpath="hl7:ClinicalDocument/hl7:recordTarget/hl7:patient/hl7:name/hl7:given">
    <templateLocation id="doc" effectiveDate="2026-01-01" xpath="hl7:ClinicalDocument"/>
  </implementation></concept>
  <template id="doc" effectiveDate="2026-01-01" name="Document">
    <element name="hl7:ClinicalDocument" minimumMultiplicity="1" maximumMultiplicity="1">
      <element name="hl7:recordTarget" minimumMultiplicity="0" maximumMultiplicity="1">
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
                "groups": {},
                "fields": {
                    "patient.anschrift.postleitzahl": {
                        "name": "Postleitzahl", "concept": "postcode", "type": "text",
                        "value_sets": [], "codes": [], "repeat_chain": [], "parent": None,
                    },
                    "patient.name.vorname": {
                        "name": "Vorname", "concept": "given", "type": "text",
                        "value_sets": [], "codes": [], "repeat_chain": [], "parent": None,
                    },
                },
            }
            compiled = compile_cda([source], model)
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

            proposal, _ = cda_mapping_proposal(model, compiled, [source])
            self.assertEqual(
                proposal["fields"]["patient.anschrift.postleitzahl"], postcode_name
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
            source = Path(tmp) / "template.xml"
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
