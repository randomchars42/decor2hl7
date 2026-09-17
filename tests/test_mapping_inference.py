from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping

from decor2hl7 import validate
from decor2hl7.bindings import build_assignments, validate_structures
from decor2hl7.compile import mapping as mapping_compiler
from decor2hl7.compile.structural import (
    boolean_example_discriminator_rules,
    coalesce_rule,
    for_each_rules,
    repeat_by_discriminator_rule,
    value_set_members,
)
from decor2hl7.cda.compile import compile_cda
from decor2hl7.cda import render as cda
from decor2hl7.cda.datatypes import value_representation
from decor2hl7.cda.parity import declared_endpoint_parity, endpoint_parity_errors
from decor2hl7.compile.reports import render_accepted_cda_mappings_markdown
from decor2hl7.cda.semantics import direct_compatibility
from decor2hl7.workspace import load_json


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


def mapping_proposal(
    model: Mapping[str, Any],
    cda_model: Mapping[str, Any],
    xml_paths: Iterable[Path],
) -> tuple[dict[str, Any], str]:
    proposal, _, report, _ = mapping_compiler.cda_mapping_audit(
        model, cda_model, xml_paths
    )
    return proposal, report


class MappingInferenceTests(unittest.TestCase):
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
            proposal, report = mapping_proposal(model, target, [project])
            _, _, _, details = mapping_compiler.cda_mapping_audit(
                model, target, [project]
            )
            self.assertEqual(proposal["fields"]["foo"], "ExampleDocument.value")
            self.assertIn("TA", report)
            self.assertIn("Reason", report)
            self.assertIn("Candidates", report)
            self.assertNotIn("Evidence chain", report)
            self.assertIn("Evidence chain", details)
            self.assertIn("Dataset concept: `c`", details)
            output = Path(tmp) / "model"
            output.mkdir()
            (output / "cda-mapping.md").write_text(
                "# stale legacy proposal guide", encoding="utf-8"
            )
            mapping_compiler.write_cda_mapping([project], output, model, target)
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
            decisions = (output / "cda-mapping.proposed.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("Abridged configuration excerpt", decisions)
            self.assertFalse((output / "cda-mapping.md").exists())
            self.assertTrue((output / "cda-mapping-trees.md").is_file())
            self.assertTrue((output / "cda-mapping-trees-extended.md").is_file())

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
            proposal, _ = mapping_proposal(model, target, [project])
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
        }, "validation_rules": [
            {"test": "count(hl7:targetSiteCode[@code='R']) &lt;= 1"},
            {"test": "count(hl7:targetSiteCode[@code='L']) &lt;= 1"},
        ]}
        inferred = repeat_by_discriminator_rule(
            ["vitals.pupil_right", "vitals.pupil_left"], "Pupil.value",
            pupil_model, pupil_cda,
            {("eye-sides", "2015-11-17"): [
                {"code": "R", "codeSystem": "1.2.276.0.76.3.1.195.5.48", "displayName": "Auge rechts", "designations": [{"language": "en-US", "displayName": "Right eye"}]},
                {"code": "L", "codeSystem": "1.2.276.0.76.3.1.195.5.48", "displayName": "Auge links", "designations": [{"language": "en-US", "displayName": "Left eye"}]},
            ]},
        )
        self.assertIsNotNone(inferred)
        assert inferred is not None
        _, repetition = inferred
        self.assertEqual(repetition["type"], "repeat_by_discriminator")
        self.assertEqual(
            [branch["target"] for branch in repetition["branches"]],
            ["Pupil_right.value", "Pupil_left.value"],
        )
        self.assertEqual(
            {branch["cda_target"] for branch in repetition["branches"]},
            {"Pupil.value"},
        )
        self.assertEqual(
            [
                branch["constants"]["Pupil.targetSiteCode"]["code"]
                for branch in repetition["branches"]
            ],
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
                "value_set_bindings": [{
                    "id": "certainty-vs", "strength": "required",
                }],
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

        coalesced = coalesce_rule(
            ["encounter.admission", "encounter.documentation"], "Encounter.low",
            {"fields": {
                "encounter.admission": {"type": "datetime", "repeat_chain": []},
                "encounter.documentation": {"type": "datetime", "repeat_chain": []},
            }},
            {"targets": {"Encounter.low": {"repeat_ancestors": []}}},
        )
        assert coalesced is not None
        self.assertEqual(coalesced[1]["policy"], "equal_or_error")

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

        coded_target = {
            "writable": True,
            "datatype": "CE",
            "path": "hl7:act/hl7:code",
            "logical_types": ["code"],
            "repeat_ancestors": [],
            "value_sets": ["1.2.3"],
            "value_set_bindings": [{"id": "1.2.3", "strength": "required"}],
            "value_representation": {"kind": "coded"},
            "schematron_constraints": [{
                "kind": "required", "path": "hl7:code", "value": 1,
            }],
        }
        unresolved_field = {
            "type": "code",
            "repeat_chain": [],
            "value_sets": ["1.2.3"],
            "formal_terminology": {"status": "unresolved"},
        }
        unresolved = mapping_compiler._candidate(
            "Act.code", coded_target, ["VS(1.2.3)"], "WEAK", 55,
            kind="VS", actionable=False,
            warnings=["source ValueSet membership is unresolved"],
        )
        rows = strengthen(
            unresolved_field,
            [unresolved],
            {"targets": {"Act.code": coded_target}},
            None,
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["actionable"])

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
        cda_model: dict[str, Any] = {
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
        proposal, _ = mapping_proposal(
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
        incomplete, _ = mapping_proposal(
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
                "fixed": {"classCode": "DOCCLIN"}, "targets": [], "validation_rules": [], "lets": {},
                "children": [{
                    "kind": "element", "name": "hl7:observation", "min": 0,
                    "max": 1, "mandatory": False, "attributes": [], "codes": [],
                    "fixed": {}, "targets": ["Contact.observation"],
                    "validation_rules": [], "lets": {}, "children": [{
                        "kind": "element", "name": "hl7:code", "min": 1,
                        "max": 1, "mandatory": True, "attributes": [],
                        "codes": [{"code": "FLN-13", "code_system": "1.2.3"}],
                        "fixed": {}, "targets": ["Contact.code"], "children": [],
                        "validation_rules": [], "lets": {},
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
        rules = for_each_rules(
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
            for_each_rules(
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
                "validation_rules": [],
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
                    "validation_rules": [], "lets": {}, "children": [
                        {
                            "kind": "element", "name": "hl7:code", "datatype": "CD",
                            "min": 0, "max": 1, "mandatory": False,
                            "attributes": [], "codes": [], "fixed": {},
                            "targets": ["Active.code"], "target": "Active.code",
                            "validation_rules": [], "lets": {}, "children": [],
                        },
                        {
                            "kind": "element", "name": "hl7:name", "datatype": "EN",
                            "min": 0, "max": 1, "mandatory": False,
                            "attributes": [], "codes": [], "fixed": {},
                            "targets": ["Active.name"], "target": "Active.name",
                            "validation_rules": [], "lets": {}, "children": [],
                        },
                    ],
                }],
            }
            proposal, report = mapping_proposal(
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
                "validation_rules": [], "unresolved_templates": [],
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
            self.assertEqual(
                endpoint_parity_errors(parity),
                [
                    "source parity: declared endpoint t:missing is missing "
                    "from the compiled CDA surface"
                ],
            )

    def test_endpoint_parity_errors_ignores_malformed_diagnostics(self) -> None:
        self.assertEqual(endpoint_parity_errors({"unexpected_missing": {}}), [])
        self.assertEqual(
            endpoint_parity_errors({"unexpected_missing": [None, {}]}),
            [
                "source parity: declared endpoint ?:? is missing from the "
                "compiled CDA surface"
            ],
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
                validate_structures(model, cda_model, cda_mapping), []
            )


if __name__ == "__main__":
    unittest.main()
