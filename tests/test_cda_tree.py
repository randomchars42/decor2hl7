from __future__ import annotations

import unittest

from decor2hl7.cda.tree import document_index, parse_location


class CdaTreeTests(unittest.TestCase):
    def test_parse_location_accepts_dotted_indexes_and_rejects_invalid_values(self) -> None:
        self.assertEqual(parse_location("0.2.100001"), (0, 2, 100001))
        self.assertIsNone(parse_location(""))
        self.assertIsNone(parse_location("0.bad"))
        self.assertIsNone(parse_location(None))

    def test_document_index_includes_children_attributes_and_parents(self) -> None:
        child = {"kind": "element", "name": "hl7:value", "children": []}
        attribute = {"kind": "attribute", "name": "classCode"}
        root = {
            "kind": "element",
            "name": "hl7:ClinicalDocument",
            "attributes": [attribute],
            "children": [child],
        }

        nodes, parents = document_index({"document": [root]})

        self.assertIs(nodes[(0,)], root)
        self.assertIs(nodes[(0, 0)], child)
        self.assertIs(nodes[(0, 100000)], attribute)
        self.assertEqual(parents[(0, 0)], (0,))
        self.assertEqual(parents[(0, 100000)], (0,))

    def test_document_index_ignores_malformed_tree_members(self) -> None:
        nodes, parents = document_index({
            "document": ["not-a-node", {"children": "not-a-list"}],
        })
        self.assertEqual(nodes, {(1,): {"children": "not-a-list"}})
        self.assertEqual(parents, {})


if __name__ == "__main__":
    unittest.main()
