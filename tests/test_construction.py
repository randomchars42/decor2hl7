from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from decor2hl7 import data, validate
from decor2hl7.bindings import build_assignments, target_default_values
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.cda.compile import compile_cda
from decor2hl7.cda import render as cda
from decor2hl7.cda.datatypes import value_representation
from decor2hl7.compile.reports import (
    coverage_headline_counts,
    render_accepted_cda_mappings_markdown,
    render_cda_mapping_markdown,
)
from decor2hl7.transforms import OMIT, apply_transform


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
        # Hand-authored fixture models stand in for datatype-expanded CDA
        # nodes. Concrete CDA scalar datatypes inherit the optional
        # nullFlavor property even when these compact fixtures omit it.
        target["permits_null_flavor"] = physical.get("kind") == "element"


class ConstructionTests(unittest.TestCase):
    def test_quarter_end_transform(self) -> None:
        self.assertEqual(
            apply_transform(
                "2026-02-17T14:30:00+01:00", {"type": "quarter_end"},
            ),
            "2026-03-31",
        )
        self.assertEqual(
            apply_transform("2024-11-09", {"type": "quarter_end"}),
            "2024-12-31",
        )

    def test_if_active_uses_an_exact_guard_independent_of_mapping_order(self) -> None:
        model = {"fields": {
            "admission": {"type": "datetime", "repeat_chain": []},
            "payer_id": {"type": "text", "repeat_chain": []},
        }}
        compiled = {"targets": {
            "Payer.time.high": {
                "writable": True, "renderable": True, "locations": ["0.0.0"],
                "repeat_ancestors": [], "logical_types": ["date", "datetime"],
                "value_representation": {
                    "kind": "xml_attribute", "attribute": "value",
                    "logical_types": ["date", "datetime"],
                },
            },
            "Payer.id": {
                "writable": True, "renderable": True, "locations": ["0.1"],
                "repeat_ancestors": [], "logical_types": ["text"],
                "value_representation": {
                    "kind": "xml_text", "logical_types": ["text"],
                },
            },
        }}
        mapping = {"fields": {
            "admission": {
                "target": "Payer.time.high", "mode": "if_active",
                "active_if": "Payer.id",
                "transform": {"type": "quarter_end"},
                "reason": "The reviewed payer period exists only with its id.",
            },
            "payer_id": "Payer.id",
        }}

        assignments, problems = build_assignments(
            {"values": {"admission": "2026-02-01", "payer_id": "A"}},
            model, compiled, mapping, {},
        )
        self.assertEqual(problems, [])
        self.assertEqual(assignments["Payer.time.high"], "2026-03-31")

        assignments, problems = build_assignments(
            {"values": {"admission": "2026-02-01"}},
            model, compiled, mapping, {},
        )
        self.assertEqual(problems, [])
        self.assertNotIn("Payer.time.high", assignments)

    def test_construction_rejects_conflicting_logical_and_physical_targets(self) -> None:
        model: dict[str, Any] = {"fields": {"finding": {}}}
        compiled = {
            "datapoints": {
                "Finding_right.value": {"cda_target": "Finding.value"},
            },
            "targets": {
                "Finding.value": {
                    "writable": True,
                    "locations": ["0"],
                    "value_representation": {
                        "kind": "text",
                        "logical_types": ["text"],
                    },
                    "logical_types": ["text"],
                },
            },
        }
        mapping = {"fields": {"finding": {
            "target": "Finding_right.value",
            "cda_target": "Other.value",
        }}}

        with self.assertRaisesRegex(
            ValueError, "resolves to 'Finding.value'.*specifies 'Other.value'",
        ):
            build_assignments(
                {"values": {"finding": "present"}},
                model,
                compiled,
                mapping,
                {},
            )

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

    def test_cda_renderer_emits_standard_replacement_lineage(self) -> None:
        compiled = {
            "targets": {},
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument",
                "id": "root", "min": 1, "max": 1, "mandatory": True,
                "attributes": [], "codes": [],
                "fixed": {"classCode": "DOCCLIN"}, "targets": [],
                "children": [{
                    "kind": "element", "name": "hl7:relatedDocument",
                    "min": 0, "max": None, "mandatory": False,
                    "attributes": [], "codes": [], "fixed": {},
                    "targets": [], "children": [], "render_order": 23,
                    "content_role": "document_replacement",
                }],
            }],
        }
        previous = {
            "document_id": {"root": "1.2.3", "extension": "CASE-1"},
            "set_id": {"root": "1.2.3", "extension": "CASE"},
            "version": 1,
        }
        payload, problems = cda.emit(
            {"key": "CASE", "values": {}}, {"fields": {}}, compiled,
            {"fields": {}},
            {"identifiers": {"document_root": "1.2.3"}, "cda": {}},
            document_version=2, previous_document=previous,
        )
        self.assertEqual(problems, [])
        root = ET.fromstring(payload)
        related = find_required(root, "{urn:hl7-org:v3}relatedDocument")
        self.assertEqual(related.get("typeCode"), "RPLC")
        parent = find_required(related, "{urn:hl7-org:v3}parentDocument")
        self.assertEqual(
            find_required(parent, "{urn:hl7-org:v3}id").attrib,
            {"root": "1.2.3", "extension": "CASE-1"},
        )
        self.assertEqual(
            find_required(parent, "{urn:hl7-org:v3}setId").attrib,
            {"root": "1.2.3", "extension": "CASE"},
        )
        self.assertEqual(
            find_required(parent, "{urn:hl7-org:v3}versionNumber").get("value"),
            "1",
        )

        with self.assertRaisesRegex(ValueError, "direct predecessor"):
            cda.emit(
                {"key": "CASE", "values": {}}, {"fields": {}}, compiled,
                {"fields": {}},
                {"identifiers": {"document_root": "1.2.3"}, "cda": {}},
                document_version=3, previous_document=previous,
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
                    "permits_null_flavor": True,
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

    def test_site_requirement_value_obeys_required_binding(self) -> None:
        leaf = {
            "kind": "element", "name": "hl7:statusCode", "datatype": "CS",
            "min": 1, "max": 1, "mandatory": True, "attributes": [],
            "codes": [], "fixed": {}, "children": [],
            "targets": ["Act.statusCode"],
        }
        target = {
            **leaf, "name": "Act.statusCode", "locations": ["0.0"],
            "renderable": True, "writable": True, "has_children": False,
            "logical_types": ["code"],
            "value_representation": {
                "kind": "coded", "attributes": ["code"],
                "scalar_attribute": "code",
            },
            "required_binding_constraints": ["1.2.3@2026-01-01"],
        }
        compiled = {
            "targets": {"Act.statusCode": target},
            "terminology_constraints": {"1.2.3@2026-01-01": {
                "id": "1.2.3", "resolved": True,
                "members": [["completed", "2.16.840.1.113883.5.14"]],
            }},
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument",
                "min": 1, "max": 1, "mandatory": True,
                "fixed": {"classCode": "DOCCLIN"}, "attributes": [],
                "targets": [], "children": [leaf],
            }],
        }
        mapping = {"fields": {}, "site_requirements": {
            "Act.statusCode": {
                "channel": "fallback_if_active",
                "reason": "The deployment supplies the assertion lifecycle.",
            },
        }}
        valid = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, mapping,
            site={"cda": {
                "values": {},
                "fallback_if_active": {"Act.statusCode": "completed"},
            }},
        )
        self.assertEqual(valid, [])
        invalid = validate.check_config(
            {"fields": {}}, compiled, {"fields": {}}, mapping,
            site={"cda": {
                "values": {},
                "fallback_if_active": {"Act.statusCode": "active"},
            }},
        )
        self.assertTrue(any(
            "outside required ART-DECOR binding" in error for error in invalid
        ))

    def test_mapping_target_identity_migrates_unique_owner_slot(self) -> None:
        owner = "1.2.3|ID:slot-7|PATH:hl7:observation/hl7:value"
        current: dict[str, Any] = {
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
        self.assertEqual(current["version"], 10)
        self.assertEqual(current["fields"]["finding"], {
            "target": "NewFinding.value", "cda_target": "NewFinding.value",
        })
        self.assertEqual(
            current["target_identities"]["NewFinding.value"]
            ["revisionless_source_key"], owner,
        )

    def test_site_requirement_target_identity_migrates_unique_owner_slot(
        self,
    ) -> None:
        owner = "1.2.3|ID:slot-7|PATH:hl7:observation/hl7:statusCode"
        current: dict[str, Any] = {
            "version": 8,
            "fields": {},
            "site_requirements": {
                "OldFinding.statusCode": {
                    "channel": "fallback_if_active",
                    "reason": "The deployment supplies the assertion lifecycle.",
                },
            },
            "target_identities": {"OldFinding.statusCode": {
                "cda_target": "OldFinding.statusCode",
                "revisionless_source_key": owner,
            }},
        }
        proposed = {"target_identities": {"NewFinding.statusCode": {
            "cda_target": "NewFinding.statusCode",
            "revisionless_source_key": owner,
        }}}
        compiled = {"targets": {"NewFinding.statusCode": {
            "template_id": "1.2.3", "template_effective_date": "2027-01-01",
            "element_id": "slot-7",
            "path": "hl7:observation/hl7:statusCode",
            "source_key": (
                "1.2.3@2027-01-01|ID:slot-7|"
                "PATH:hl7:observation/hl7:statusCode"
            ),
        }}}

        changed = mapping_compiler.migrate_mapping_target_identities(
            current, proposed, compiled
        )

        self.assertEqual(changed, 1)
        self.assertNotIn("OldFinding.statusCode", current["site_requirements"])
        self.assertEqual(
            current["site_requirements"]["NewFinding.statusCode"],
            {
                "channel": "fallback_if_active",
                "reason": "The deployment supplies the assertion lifecycle.",
            },
        )
        self.assertIn("NewFinding.statusCode", current["target_identities"])

    def test_narrative_target_identity_migrates_unique_owner_slot(self) -> None:
        owner = "1.2.3|ID:text-7|PATH:hl7:section/hl7:text"
        current: dict[str, Any] = {
            "fields": {"finding": None},
            "narratives": {"OldSection.text": {"blocks": [{
                "type": "fact", "source": "finding", "label": "Finding",
                "reason": "Reviewed wording-only representation.",
            }]}},
            "target_identities": {"OldSection.text": {
                "cda_target": "OldSection.text",
                "revisionless_source_key": owner,
            }},
        }
        proposed = {"target_identities": {"NewSection.text": {
            "cda_target": "NewSection.text",
            "revisionless_source_key": owner,
        }}}
        compiled = {"targets": {"NewSection.text": {
            "template_id": "1.2.3", "template_effective_date": "2027-01-01",
            "element_id": "text-7", "path": "hl7:section/hl7:text",
            "source_key": "1.2.3@2027-01-01|ID:text-7|PATH:hl7:section/hl7:text",
        }}}

        changed = mapping_compiler.migrate_mapping_target_identities(
            current, proposed, compiled
        )

        self.assertEqual(changed, 1)
        self.assertNotIn("OldSection.text", current["narratives"])
        self.assertIn("NewSection.text", current["narratives"])
        self.assertIn("NewSection.text", current["target_identities"])

    def test_mapping_target_identity_does_not_guess_ambiguous_slot(self) -> None:
        owner = "1.2.3|ID:slot-7|PATH:hl7:observation/hl7:value"
        current: dict[str, Any] = {
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

    def test_mapping_target_identity_preserves_logical_alias_physical_target(self) -> None:
        owner = "1.2.3|ID:slot-7|PATH:hl7:observation/hl7:value"
        target = {
            "template_id": "1.2.3", "template_effective_date": "2027-01-01",
            "element_id": "slot-7", "path": "hl7:observation/hl7:value",
            "source_key": "1.2.3@2027-01-01|ID:slot-7|PATH:hl7:observation/hl7:value",
        }
        current: dict[str, Any] = {
            "fields": {"finding": {
                "target": "Finding_right.value",
                "cda_target": "Finding.value",
                "structure": "finding-by-side", "branch": "right",
            }},
            "structures": {"finding-by-side": {
                "type": "repeat_by_discriminator",
                "branches": [{
                    "source": "finding", "target": "Finding_right.value",
                    "cda_target": "Finding.value", "branch": "right",
                }],
            }},
            "target_identities": {},
        }
        proposed = {"target_identities": {"Finding_right.value": {
            "cda_target": "Finding.value",
            "revisionless_source_key": owner,
        }}}
        compiled = {
            "targets": {"Finding.value": target},
            "datapoints": {"Finding_right.value": {
                "cda_target": "Finding.value",
            }},
        }

        changed = mapping_compiler.migrate_mapping_target_identities(
            current, proposed, compiled
        )

        self.assertEqual(changed, 0)
        self.assertEqual(
            current["fields"]["finding"]["cda_target"], "Finding.value"
        )
        self.assertEqual(
            current["structures"]["finding-by-side"]["branches"][0]
            ["cda_target"],
            "Finding.value",
        )
        self.assertEqual(
            current["target_identities"]["Finding_right.value"]["cda_target"],
            "Finding.value",
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

    def test_required_fields_are_inactive_inside_absent_optional_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "cases.csv").write_text("patient_id\nP1\n", encoding="utf-8")
            (raw / "events.csv").write_text(
                "patient_id,event_id,code,time,duration\nP1,e1,X,,\n",
                encoding="utf-8",
            )
            model = {
                "groups": {
                    "events": {"min": 0, "parent": None},
                    "events.timing": {"min": 0, "parent": "events"},
                },
                "fields": {
                    "events.code": {
                        "type": "text", "parent": "events",
                        "repeat_chain": ["events"], "required": True,
                    },
                    "events.timing.time": {
                        "type": "datetime", "parent": "events.timing",
                        "repeat_chain": ["events"], "required": True,
                    },
                    "events.timing.duration": {
                        "type": "duration", "parent": "events.timing",
                        "repeat_chain": ["events"], "required": True,
                    },
                },
            }
            csv_mapping = {
                "join": {"column": "patient_id"},
                "fields": {
                    "events.code": "events:code",
                    "events.timing.time": "events:time",
                    "events.timing.duration": "events:duration",
                },
            }
            site = {"input": {
                "case_source": "cases", "empty_is_null": True,
                "sources": {
                    "cases": {"file": "cases.csv", "cardinality": "1:1"},
                    "events": {
                        "file": "events.csv", "cardinality": "1:n",
                        "occurrence_keys": {"events": "event_id"},
                    },
                },
            }}
            record = data.ingest(
                raw, model, csv_mapping, {"fields": {}}, site,
            )[0]
            row = record["instances"]["events"][0]
            self.assertEqual(row["values"]["events.code"], "X")
            self.assertIsNone(row["values"]["events.timing.time"])
            self.assertIsNone(row["values"]["events.timing.duration"])
            self.assertEqual(validate.validate_record(record, model), [])

            (raw / "events.csv").write_text(
                "patient_id,event_id,code,time,duration\n"
                "P1,e1,X,2026-01-01T12:00:00Z,\n",
                encoding="utf-8",
            )
            active = data.ingest(
                raw, model, csv_mapping, {"fields": {}}, site,
            )[0]["instances"]["events"][0]["values"]
            self.assertEqual(
                active["events.timing.duration"], {"nullFlavor": "NI"},
            )

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

    def test_reviewed_medication_merge_and_narrative_rules(self) -> None:
        self.assertEqual(
            apply_transform(
                {"code": "PUFF", "codeSystem": "2.16.840.1.113883.5.85"},
                {"type": "coded_only"},
            ),
            {"code": "PUFF", "codeSystem": "2.16.840.1.113883.5.85"},
        )
        self.assertIs(
            apply_transform({"raw": "Dosieraerosol"}, {"type": "coded_only"}),
            OMIT,
        )
        model = {"fields": {
            "art": {"type": "code", "repeat_chain": []},
            "methode": {"type": "text", "repeat_chain": []},
            "product_name": {"type": "text", "repeat_chain": []},
            "ingredient_name": {"type": "text", "repeat_chain": []},
            "ingredient_code": {"type": "code", "repeat_chain": []},
            "ingredient_active": {"type": "boolean", "repeat_chain": []},
            "ingredient_strength": {"type": "text", "repeat_chain": []},
            "freitext": {"type": "text", "repeat_chain": []},
            "additional_instruction": {"type": "code", "repeat_chain": []},
            "patient_instruction": {"type": "text", "repeat_chain": []},
            "prn": {"type": "boolean", "repeat_chain": []},
        }}
        cda_model = {"targets": {
            "Medication.route": {
                "writable": True, "renderable": True, "locations": ["0"],
                "repeat_ancestors": [], "logical_types": ["code"],
                "permits_null_flavor": True,
                "value_representation": {"kind": "coded"},
            },
            "Medication.text": {
                "writable": True, "renderable": True, "locations": ["1"],
                "repeat_ancestors": [], "logical_types": ["text"],
                "value_representation": {"kind": "text"},
            },
        }}
        route_transform = {
            "type": "coded_or_original_text", "null_flavor": "OTH",
        }
        mapping = {
            "fields": {
                "art": {"target": "Medication.route", "structure": "route", "transform": route_transform},
                "methode": {"target": "Medication.route", "structure": "route", "transform": route_transform},
                "product_name": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative", "prefix": "Arzneimittel: "}},
                "ingredient_name": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative", "prefix": "Wirkstoff: "}},
                "ingredient_code": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative", "prefix": "Wirkstoff-Code: "}},
                "ingredient_active": {"target": "Medication.text", "structure": "text", "transform": {"type": "enum", "map": {"true": "Arzneilich wirksamer Bestandteil: ja", "false": "Arzneilich wirksamer Bestandteil: nein"}}},
                "ingredient_strength": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative", "prefix": "Wirkstärke: "}},
                "freitext": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative"}},
                "additional_instruction": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative", "prefix": "Zusätzlicher Hinweis: "}},
                "patient_instruction": {"target": "Medication.text", "structure": "text", "transform": {"type": "narrative", "prefix": "Einnahmeanweisung: "}},
                "prn": {"target": "Medication.text", "structure": "text", "transform": {"type": "enum", "map": {"true": "Einnahme bei Bedarf", "false": None}}},
            },
            "structures": {
                "route": {
                    "type": "coalesce", "target": "Medication.route",
                    "sources": ["art", "methode"],
                    "policy": "prefer_first_warn_if_different",
                    "transform": route_transform,
                },
                "text": {
                    "type": "concatenate", "target": "Medication.text",
                    "separator": "; ",
                    "sources": [
                        {"source": "product_name", "transform": {"type": "narrative", "prefix": "Arzneimittel: "}},
                        {"source": "ingredient_name", "transform": {"type": "narrative", "prefix": "Wirkstoff: "}},
                        {"source": "ingredient_code", "transform": {"type": "narrative", "prefix": "Wirkstoff-Code: "}},
                        {"source": "ingredient_active", "transform": {"type": "enum", "map": {"true": "Arzneilich wirksamer Bestandteil: ja", "false": "Arzneilich wirksamer Bestandteil: nein"}}},
                        {"source": "ingredient_strength", "transform": {"type": "narrative", "prefix": "Wirkstärke: "}},
                        {"source": "freitext", "transform": {"type": "narrative"}},
                        {"source": "additional_instruction", "transform": {"type": "narrative", "prefix": "Zusätzlicher Hinweis: "}},
                        {"source": "patient_instruction", "transform": {"type": "narrative", "prefix": "Einnahmeanweisung: "}},
                        {"source": "prn", "transform": {"type": "enum", "map": {"true": "Einnahme bei Bedarf", "false": None}}},
                    ],
                },
            },
        }
        assignments, problems = build_assignments(
            {"values": {
                "art": {"raw": "oral"},
                "methode": "oral",
                "product_name": "Ramipril",
                "ingredient_name": "Ramipril",
                "ingredient_code": {"raw": "C09AA05"},
                "ingredient_active": True,
                "ingredient_strength": "5 mg pro Tablette",
                "freitext": "2 Tabletten",
                "additional_instruction": {"raw": "Kann Schwindel verursachen"},
                "patient_instruction": "Mit Wasser einnehmen",
                "prn": True,
            }},
            model, cda_model, mapping, {},
        )
        self.assertEqual(problems, [])
        self.assertEqual(
            assignments["Medication.route"],
            {"nullFlavor": "OTH", "raw": "oral"},
        )
        self.assertEqual(
            assignments["Medication.text"],
            "Arzneimittel: Ramipril; Wirkstoff: Ramipril; "
            "Wirkstoff-Code: C09AA05; Arzneilich wirksamer Bestandteil: ja; "
            "Wirkstärke: 5 mg pro Tablette; 2 Tabletten; "
            "Zusätzlicher Hinweis: Kann Schwindel verursachen; "
            "Einnahmeanweisung: Mit Wasser einnehmen; Einnahme bei Bedarf",
        )

        assignments, problems = build_assignments(
            {"values": {"ingredient_active": False}},
            model, cda_model, mapping, {},
        )
        self.assertEqual(problems, [])
        self.assertEqual(
            assignments["Medication.text"],
            "Arzneilich wirksamer Bestandteil: nein",
        )

        assignments, problems = build_assignments(
            {"values": {}}, model, cda_model, mapping, {},
        )
        self.assertEqual(problems, [])
        self.assertNotIn("Medication.text", assignments)

        assignments, problems = build_assignments(
            {"values": {"art": {"raw": "oral"}, "methode": "intravenös"}},
            model, cda_model, mapping, {},
        )
        self.assertEqual(assignments["Medication.route"]["raw"], "oral")
        self.assertEqual(len(problems), 1)
        self.assertIn("used the first source", problems[0])

    def test_reviewed_narrative_rules_require_exact_source_shapes(self) -> None:
        model = {"fields": {
            "mri": {"type": "code", "repeat_chain": []},
            "xray.region": {"type": "code", "repeat_chain": ["xray"]},
        }, "groups": {}}
        target = "Diagnostics.text"
        cda_model: dict[str, Any] = {"targets": {target: {
            "writable": True, "prohibited": False, "locations": ["0.1"],
            "content_role": "section_narrative", "logical_types": ["text"],
            "value_representation": {"kind": "element_text"},
            "repeat_ancestors": [],
        }}, "document": []}
        csv_mapping = {"fields": {"mri": None, "xray.region": None}}
        valid_mapping = {
            "fields": {"mri": None, "xray.region": None},
            "narratives": {target: {"blocks": [
                {
                    "type": "fact", "source": "mri", "label": "MRI region",
                    "reason": "Reviewed wording-only representation.",
                },
                {
                    "type": "for_each", "source_repeat": "xray",
                    "source": "xray.region", "label": "X-ray region",
                    "reason": "Preserve every reviewed occurrence.",
                },
            ]}},
        }
        self.assertEqual(
            validate.check_config(
                model, cda_model, csv_mapping, valid_mapping,
                require_site_configuration=False,
            ),
            [],
        )
        counts = coverage_headline_counts(
            model, cda_model, valid_mapping,
            {"fields": {"mri": {}, "xray.region": {}}},
        )
        self.assertEqual(counts["mapped_datapoints"], 2)
        self.assertEqual(counts["mapped_leaves"], 2)
        self.assertEqual(counts["no_target_datapoints"], 0)
        invalid = {
            **valid_mapping,
            "narratives": {target: {"blocks": [{
                "type": "fact", "source": "xray.region", "label": "X-ray",
                "reason": "Incorrectly loses occurrence identity.",
            }]}},
        }
        self.assertTrue(any(
            "source is repeated; use for_each" in error
            for error in validate.check_config(
                model, cda_model, csv_mapping, invalid,
                require_site_configuration=False,
            )
        ))

    def test_transform_rules_render_negation_nullflavor_and_ordinal(self) -> None:
        compiled = {
            "targets": {
                "Iso.negationInd": {"datatype": "BL", "path": "hl7:procedure/@negationInd", "renderable": True, "locations": ["0.0.100000"], "fixed": {}, "repeat_ancestors": []},
                "Iso.nullFlavor": {"datatype": "cs", "path": "hl7:procedure/@nullFlavor", "renderable": True, "locations": ["0.0.100001"], "fixed": {}, "repeat_ancestors": []},
                "Rank.value": {"datatype": "PQ", "path": "hl7:observation/hl7:value", "renderable": True, "locations": ["0.1.0"], "fixed": {}, "unit": "{score}", "repeat_ancestors": []},
            },
            "document": [{
                "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1, "mandatory": True,
                "attributes": [], "codes": [], "fixed": {}, "targets": [], "validation_rules": [], "lets": {},
                "children": [
                    {"kind": "element", "name": "hl7:procedure", "min": 0, "max": 1, "mandatory": False,
                     "attributes": [
                         {"kind": "attribute", "name": "negationInd", "optional": True, "value": None, "targets": ["Iso.negationInd"]},
                         {"kind": "attribute", "name": "nullFlavor", "optional": True, "value": None, "targets": ["Iso.nullFlavor"]},
                     ], "codes": [], "fixed": {}, "targets": [], "children": [], "validation_rules": [], "lets": {}},
                    {"kind": "element", "name": "hl7:observation", "min": 0, "max": 1, "mandatory": False,
                     "attributes": [], "codes": [], "fixed": {}, "targets": [], "validation_rules": [], "lets": {},
                     "children": [{"kind": "element", "name": "hl7:value", "datatype": "PQ", "unit": "{score}", "min": 0, "max": 1, "mandatory": False,
                                  "attributes": [], "codes": [], "fixed": {}, "targets": ["Rank.value"], "children": [], "validation_rules": [], "lets": {}}]},
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


if __name__ == "__main__":
    unittest.main()
