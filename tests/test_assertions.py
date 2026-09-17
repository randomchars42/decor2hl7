from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from decor2hl7 import assertions
from decor2hl7.cda import render as cda


class AssertionTests(unittest.TestCase):
    def test_art_decor_assertion_failure_blocks_rendering(self) -> None:
        compiled = {"targets": {}, "document": [{
            "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1, "mandatory": True,
            "attributes": [], "codes": [], "fixed": {}, "targets": [], "validation_rules": [], "lets": {},
            "children": [{
                "kind": "element", "name": "hl7:procedure", "min": 1, "max": 1, "mandatory": True,
                "attributes": [{"kind": "attribute", "name": "negationInd", "optional": True, "value": "true", "targets": []}],
                "codes": [], "fixed": {}, "targets": [], "lets": {},
                "validation_rules": [{"test": "not(@negationInd='true' and hl7:entryRelationship)", "role": "error", "message": "no reason when negated", "template_id": "iso"}],
                "children": [{
                    "kind": "element", "name": "hl7:entryRelationship", "min": 1, "max": 1, "mandatory": True,
                    "attributes": [], "codes": [], "fixed": {"typeCode": "RSON"}, "targets": [], "children": [],
                    "validation_rules": [], "lets": {},
                }],
            }],
        }]}
        with self.assertRaisesRegex(ValueError, "ART-DECOR assertions"):
            cda.emit(
                {"key": "x", "values": {}, "instances": {}}, {"fields": {}}, compiled,
                {"fields": {}}, {"null_flavor": {}},
            )

    def test_assertion_evaluator_supports_source_expression_shapes(self) -> None:
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
        text = assertions.schematron({"validation_rules": [{
            "path": "hl7:observation", "template_id": "1.2.3", "role": "error",
            "test": "empty($seq)", "message": "unique", "lets": {"seq": "//hl7:value"},
        }]})
        self.assertIn('<sch:let name="seq" value="//hl7:value"/>', text)
        self.assertIn('test="empty($seq)"', text)

    def test_schematron_declares_assertion_template_namespaces(self) -> None:
        text = assertions.schematron({"validation_rules": [{
            "path": "pharmhl7:ingredientSubstance",
            "template_id": "2.16.840.1.113883.10.21.4.18",
            "role": "error", "test": "pharmhl7:code or pharmhl7:name",
            "message": "code or name",
            "namespaces": {"pharmhl7": "urn:hl7-org:pharm"},
        }]})
        self.assertIn(
            '<sch:ns prefix="pharmhl7" uri="urn:hl7-org:pharm"/>', text
        )


if __name__ == "__main__":
    unittest.main()
