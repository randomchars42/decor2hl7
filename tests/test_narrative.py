from __future__ import annotations

import copy
import unittest
from typing import Any

from decor2hl7.cda.narrative import (
    build_section_narratives,
    narrative_blocks,
    narrative_source_rules,
    validate_narratives,
)


def _valid_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    model = {
        "fields": {
            "note": {"name": "Reviewed note", "repeat_chain": []},
        }
    }
    cda = {
        "targets": {
            "section.text": {
                "writable": True,
                "prohibited": False,
                "locations": ["0.1"],
                "content_role": "section_narrative",
                "value_representation": {"kind": "element_text"},
                "logical_types": ["text"],
                "repeat_ancestors": [],
            },
        }
    }
    mapping = {
        "fields": {"note": None},
        "field_reviews": {},
        "narratives": {
            "section.text": {
                "blocks": [{
                    "type": "fact",
                    "source": "note",
                    "label": "Note",
                    "reason": "Reviewed narrative-only presentation",
                }]
            }
        },
    }
    return model, cda, mapping


class NarrativeTests(unittest.TestCase):
    def test_narrative_blocks_normalize_only_well_formed_mapping_entries(self) -> None:
        mapping = {
            "narratives": {
                "section.one": {
                    "blocks": [
                        {"type": "fact", "source": "a"},
                        "ignored",
                    ]
                },
                "section.two": {"blocks": "not-a-list"},
                "section.three": "not-an-object",
            }
        }
        self.assertEqual(narrative_blocks(mapping), [{
            "section_target": "section.one", "type": "fact", "source": "a"
        }])
        self.assertEqual(
            narrative_source_rules(mapping),
            {"a": [{
                "section_target": "section.one", "type": "fact", "source": "a"
            }]},
        )
        self.assertEqual(narrative_blocks({"narratives": []}), [])

    def test_validate_narratives_accepts_the_minimal_reviewed_contract(self) -> None:
        model, cda, mapping = _valid_fixture()
        self.assertEqual(validate_narratives(model, cda, mapping), [])
        self.assertEqual(
            validate_narratives(model, cda, {"narratives": []}),
            ["cda-mapping: narratives must be an object"],
        )

    def test_validate_narratives_reports_target_and_block_contract_violations(self) -> None:
        model, cda, mapping = _valid_fixture()
        broken_cda = copy.deepcopy(cda)
        target = broken_cda["targets"]["section.text"]
        target.update({
            "writable": False,
            "content_role": "ordinary_text",
            "value_representation": {"kind": "attribute"},
            "repeat_ancestors": ["sections"],
        })
        broken_mapping = copy.deepcopy(mapping)
        broken_mapping["narratives"]["section.text"]["extra"] = True
        block = broken_mapping["narratives"]["section.text"]["blocks"][0]
        block.update({
            "type": "for_each",
            "source_repeat": "wrong-repeat",
            "label": "",
            "reason": "",
            "decision": "",
            "reviewed_at": "",
            "extra": True,
        })
        model["fields"]["note"]["repeat_chain"] = ["notes"]
        broken_mapping["fields"]["note"] = "structured.target"
        broken_mapping["field_reviews"]["note"] = {"reason": "conflict"}

        errors = validate_narratives(model, broken_cda, broken_mapping)
        for expected in (
            "unknown keys",
            "one writable, unambiguous",
            "not a compiled section narrative",
            "not a writable text value",
            "cannot target a repeated section",
            "must remain null in fields",
            "conflicts with field_reviews",
            ".label must be non-empty text",
            ".reason must be non-empty text",
            ".decision must be non-empty text",
            ".reviewed_at must be non-empty text",
            "must have repeat_chain ['wrong-repeat']",
        ):
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_validate_narratives_rejects_duplicates_and_invalid_block_shapes(self) -> None:
        model, cda, mapping = _valid_fixture()
        mapping["narratives"]["section.text"]["blocks"].extend([
            {"type": "fact", "source": "note", "label": "Again", "reason": "Duplicate"},
            "not-an-object",
        ])
        errors = validate_narratives(model, cda, mapping)
        self.assertTrue(any("duplicates the narrative rule" in error for error in errors))
        self.assertTrue(any("must be an object" in error for error in errors))

    def test_build_section_narratives_activates_a_reviewed_narrative_only_fact(self) -> None:
        model, cda, mapping = _valid_fixture()
        cda["targets"]["section.title"] = {
            "content_role": "section_title",
            "fixed_text": "Example section",
            "repeat_ancestors": [],
        }
        cda["document"] = [{
            "kind": "element",
            "name": "hl7:section",
            "targets": [],
            "attributes": [],
            "children": [
                {
                    "kind": "element", "name": "hl7:title",
                    "targets": ["section.title"], "attributes": [], "children": [],
                },
                {
                    "kind": "element", "name": "hl7:text",
                    "targets": ["section.text"], "attributes": [], "children": [],
                },
            ],
        }]

        titles, narratives = build_section_narratives(
            {"values": {"note": True}}, model, cda, mapping,
            assignments={}, explicit_names=set(),
            site={"cda": {"values": {"document.languageCode": "de-DE"}}},
        )
        self.assertEqual(titles, {"section.title": "Example section"})
        narrative = narratives["section.text"]
        self.assertTrue(narrative["__section_narrative__"])
        self.assertEqual(narrative["facts"], [{
            "source": "note", "label": "Note", "value": "Ja"
        }])


if __name__ == "__main__":
    unittest.main()
