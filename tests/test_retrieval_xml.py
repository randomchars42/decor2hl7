from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from decor2hl7.retrieval import xml


class RetrievalXmlTests(unittest.TestCase):
    def test_text_helpers_normalize_markup_whitespace_and_namespaces(self) -> None:
        node = ET.fromstring(
            '<root xmlns:x="urn:example"><x:name> First <b>value</b> </x:name></root>'
        )
        self.assertEqual(xml.local("{urn:example}name"), "name")
        self.assertEqual(xml.clean("  one\u00a0 <b>two</b>  "), "one two")
        self.assertEqual(xml.child_text(node, "name"), "First value")
        self.assertEqual(xml.child_text(node, "missing"), "")

    def test_namespace_repair_adds_only_known_undeclared_prefixes(self) -> None:
        source = (
            '<?xml version="1.0"?><template xmlns:hl7="urn:hl7-org:v3">'
            '<hl7:observation xsi:type="CD"/></template>'
        )
        repaired, repairs = xml.repair_namespaces(source)
        self.assertEqual(repairs, ["xsi"])
        self.assertEqual(repaired.count("xmlns:hl7"), 1)
        root, parsed_repairs = xml.parse_text(source)
        self.assertEqual(xml.local(root.tag), "template")
        self.assertEqual(parsed_repairs, ["xsi"])

        untouched, repairs = xml.repair_namespaces("<unknown:item/>")
        self.assertEqual(untouched, "<unknown:item/>")
        self.assertEqual(repairs, [])
        self.assertEqual(xml.repair_namespaces("not XML"), ("not XML", []))

    def test_template_namespace_maps_preserve_nested_lexical_scope(self) -> None:
        source = '''<root xmlns:p="urn:outer">
          <template id="outer" effectiveDate="2024"><element name="p:value"/></template>
          <group xmlns:p="urn:inner" xmlns:q="urn:second">
            <template id="inner" effectiveDate="2025"><element name="q:value"/></template>
          </group>
        </root>'''
        maps = xml.template_namespace_maps(source)
        self.assertEqual(maps[("outer", "2024")]["p"], "urn:outer")
        self.assertEqual(maps[("inner", "2025")]["p"], "urn:inner")
        self.assertEqual(maps[("inner", "2025")]["q"], "urn:second")

    def test_parse_file_repairs_known_prefixes_and_reports_malformed_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.xml"
            path.write_text(
                '<template><hl7:observation/></template>', encoding="utf-8"
            )
            root, repairs = xml.parse_file(path)
            self.assertEqual(xml.local(root[0].tag), "observation")
            self.assertEqual(repairs, ["hl7"])

        with self.assertRaises(ET.ParseError):
            xml.parse_text("<template>")


if __name__ == "__main__":
    unittest.main()
