from __future__ import annotations

import csv
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from decor2hl7.cli import (
    _merge_mapping_configuration_notes,
    _prune_absent_pending, _prune_stale_pending, main,
)
from decor2hl7.workspace import (
    load_json, set_release, set_transaction, transaction_mapping_dir,
    transaction_model_dir, transaction_site_dir, transaction_test_dir, write_json,
)

RELEASES = [{"key": "2026.1.2", "label": "2026.1.2", "date": "2026-04-27T18:50:33", "status": "final"}]
TRANSACTIONS = [{
    "key": "notaufnahmeregister--60", "id": "2.16.840.1.113883.2.6.60.3.4.60",
    "effective_date": "2026-03-25T00:00:00", "version_label": "2026",
    "status": "active", "name": "Notaufnahmeregister Transitionsversion",
}]


class CliTests(unittest.TestCase):
    def test_fetch_fail_on_degraded_is_an_explicit_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            result = {"closure": {
                "summary": {}, "build_resources": [], "evidence_resources": [],
                "errors": [], "truncated": False, "build_ready": True,
                "degraded_resources": ["valueset:1.2.3"],
                "degradation_warnings": ["dependency unavailable: valueset:1.2.3"],
            }}
            with patch(
                "decor2hl7.retrieval.fetch.fetch_spec", return_value=result
            ):
                self.assertEqual(main(["--root", str(root), "fetch"]), 0)
                self.assertEqual(main([
                    "--root", str(root), "fetch", "--fail-on-degraded",
                ]), 2)

    def test_build_fail_on_degraded_gates_on_the_consulted_closure(self) -> None:
        """CI gates on what this build consumes, not on the whole crawl.

        `fetch --fail-on-degraded` can only judge the retrieval closure. Whether
        a gap is actually consulted is known after compilation, so the build
        gate reads `build_degraded` (`DEC-010`).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model: dict[str, Any] = {"meta": {}, "fields": {}, "groups": {}}
            diagnostics: dict[str, Any] = {
                "status": "complete", "build_degraded": [],
                "summary": {
                    "build_degraded": 0, "crawl_degraded": 4,
                    "unresolved_templates": 0,
                },
            }
            cda_model = {"stats": {
                "reachable_templates": 0, "targets": 0, "datapoints": 0,
            }}
            with (
                patch("decor2hl7.cli._compiler_inputs", return_value={
                    "transaction_source": root, "transaction_analysis": root,
                    "model_resources": [], "terminology_resources": [],
                    "templates": [], "mapping_evidence": [], "cda_extensions": [],
                    "unavailable_artifacts": [], "build_artifacts": [],
                    "evidence_artifacts": [],
                }),
                patch(
                    "decor2hl7.compile.transaction.write_transaction_model",
                    return_value=model,
                ),
                patch(
                    "decor2hl7.compile.site.write_code_mapping",
                    return_value={"fields": {}},
                ),
                patch(
                    "decor2hl7.cda.compile.write_cda_model", return_value=cda_model
                ),
                patch(
                    "decor2hl7.compile.mapping.write_mapping_model",
                    return_value={"fields": {}},
                ),
                patch(
                    "decor2hl7.conformance.build_conformance_artifacts",
                    return_value={"status": "passed", "summary": {}},
                ),
                patch(
                    "decor2hl7.compile.artifacts.write_build_diagnostics",
                    return_value=diagnostics,
                ) as write_diagnostics,
            ):
                self.assertEqual(main([
                    "--root", str(root), "build", "--fail-on-degraded",
                ]), 0)
                diagnostics["status"] = "degraded"
                diagnostics["build_degraded"] = [{"request_key": "valueset:1.2.3"}]
                diagnostics["summary"]["build_degraded"] = 1
                write_diagnostics.return_value = diagnostics
                self.assertEqual(main(["--root", str(root), "build"]), 0)
                self.assertEqual(main([
                    "--root", str(root), "build", "--fail-on-degraded",
                ]), 2)

    def test_generated_mapping_notes_refresh_without_replacing_user_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposed = root / "proposed.json"
            current = root / "current.json"
            write_json(proposed, {"configuration_notes": [{
                "generated": True, "source": "config/sources.json",
                "note": "Current generated note",
            }]})
            write_json(current, {"fields": {}, "configuration_notes": [
                {"note": "Reviewer note"},
                {"generated": True, "note": "Stale generated note"},
            ]})
            self.assertEqual(
                _merge_mapping_configuration_notes(proposed, current), 1
            )
            self.assertEqual(load_json(current)["configuration_notes"], [
                {"note": "Reviewer note"},
                {
                    "generated": True, "source": "config/sources.json",
                    "note": "Current generated note",
                },
            ])

    def test_build_completes_with_reported_auxiliary_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            source = root / "transaction.source.xml"
            analysis = root / "transaction.xml"
            template = root / "template.xml"
            source.write_text('''<transaction id="tx" effectiveDate="2026">
              <representingTemplate ref="doc" flexibility="2026">
                <concept ref="c" minimumMultiplicity="0" maximumMultiplicity="1"/>
              </representingTemplate>
            </transaction>''', encoding="utf-8")
            analysis.write_text('''<dataset transactionId="tx" transactionEffectiveDate="2026"
                templateId="doc" templateEffectiveDate="2026">
              <concept id="c" shortName="note" type="item">
                <name>Note</name><valueDomain type="string"/>
              </concept>
            </dataset>''', encoding="utf-8")
            template.write_text('''<template id="doc" effectiveDate="2026" name="Doc">
              <element name="hl7:ClinicalDocument">
                <include ref="old-entry" flexibility="2005"/>
              </element>
            </template>''', encoding="utf-8")
            unavailable = [{
                "request_key": "dataset:old@2005", "type": "dataset",
                "status": "missing", "roles": ["structure"],
                "reasons": ["dataset:old@2005: artifact status is missing"],
            }]
            inputs = {
                "transaction_source": source,
                "transaction_analysis": analysis,
                "model_resources": [],
                "terminology_resources": [],
                "templates": [template],
                "mapping_evidence": [source, analysis, template],
                "unavailable_artifacts": unavailable,
                "crawl_degraded_artifacts": unavailable + [{
                    "request_key": "valueset:partial",
                    "type": "valueset", "status": "partial-expansion",
                    "roles": ["formal-terminology"], "reasons": ["partial"],
                }],
                "warnings": unavailable[0]["reasons"],
            }
            stderr = StringIO()
            with patch("decor2hl7.cli._compiler_inputs", return_value=inputs), redirect_stderr(stderr):
                self.assertEqual(main(["--root", str(root), "build"]), 0)
            model_dir = transaction_model_dir(root)
            diagnostics = load_json(model_dir / "build-diagnostics.json")
            self.assertEqual(diagnostics["status"], "degraded")
            self.assertEqual(diagnostics["summary"]["unavailable_artifacts"], 1)
            self.assertEqual(diagnostics["summary"]["crawl_degraded"], 2)
            self.assertEqual(diagnostics["summary"]["unresolved_templates"], 1)
            model = load_json(model_dir / "model.json")
            self.assertEqual(
                model["meta"]["artifact_closure"]["crawl_degraded_artifacts"],
                ["dataset:old@2005", "valueset:partial"],
            )
            self.assertIn("warning: degraded build", stderr.getvalue())

    def test_symmetric_release_and_transaction_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            with patch("decor2hl7.retrieval.catalog.releases", return_value=RELEASES):
                self.assertEqual(main(["--root", str(root), "set-version", "2026.1.2"]), 0)
            settings = load_json(root / "decor2hl7.json")
            self.assertEqual(settings["release"]["key"], "2026.1.2")
            self.assertIsNone(settings["transaction"])
            with patch("decor2hl7.retrieval.catalog.transactions", return_value=TRANSACTIONS):
                self.assertEqual(main(["--root", str(root), "set-transaction", "notaufnahmeregister--60"]), 0)
            settings = load_json(root / "decor2hl7.json")
            self.assertEqual(settings["transaction"]["key"], "notaufnahmeregister--60")
            # Set commands still have no artifact-directory side effects.
            self.assertFalse((root / "spec" / "2026.1.2").exists())


    def test_selection_lists_put_key_first_and_use_verb_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            out = StringIO()
            with patch("decor2hl7.retrieval.catalog.releases", return_value=RELEASES), redirect_stdout(out):
                self.assertEqual(main(["--root", str(root), "list-versions"]), 0)
            lines = out.getvalue().splitlines()
            self.assertTrue(lines[0].startswith("KEY"))
            self.assertTrue(lines[1].startswith("2026.1.2"))

            with patch("decor2hl7.retrieval.catalog.releases", return_value=RELEASES):
                self.assertEqual(main(["--root", str(root), "set-version", "2026.1.2"]), 0)
            out = StringIO()
            with patch("decor2hl7.retrieval.catalog.transactions", return_value=TRANSACTIONS), redirect_stdout(out):
                self.assertEqual(main(["--root", str(root), "list-transactions"]), 0)
            lines = out.getvalue().splitlines()
            self.assertTrue(lines[0].startswith("KEY"))
            self.assertTrue(lines[1].startswith("notaufnahmeregister--60"))

    def test_keyboard_interrupt_exits_130_without_traceback(self) -> None:
        err = StringIO()
        with patch("decor2hl7.cli.cmd_init", side_effect=KeyboardInterrupt), redirect_stderr(err):
            self.assertEqual(main(["init"]), 130)
        self.assertEqual(err.getvalue().strip(), "aborted by user")

    def test_input_commands_accept_external_input_root_and_build_is_uncoupled(self) -> None:
        from decor2hl7.cli import parser
        propose = parser().parse_args(["propose-input", "--input", "/tmp/input"])
        self.assertEqual(propose.input, "/tmp/input")
        self.assertEqual(propose.join_column, "patient_id")
        transform = parser().parse_args(["transform", "--input", "/tmp/input"])
        self.assertEqual(transform.input, "/tmp/input")
        run = parser().parse_args(["run", "--input", "/tmp/input"])
        self.assertEqual(run.input, "/tmp/input")
        check_input = parser().parse_args(["check-input", "--input", "/tmp/input"])
        self.assertEqual(check_input.input, "/tmp/input")
        build = parser().parse_args(["build"])
        self.assertFalse(hasattr(build, "input"))
        self.assertFalse(hasattr(build, "join_column"))
        check = parser().parse_args(["check"])
        self.assertFalse(hasattr(check, "input"))
        test = parser().parse_args(["test-cda-mapping", "--out", "/tmp/results"])
        self.assertEqual(test.out, "/tmp/results")
        self.assertTrue(hasattr(test, "cda_mapping"))
        fetch = parser().parse_args(["fetch", "--offline"])
        self.assertTrue(fetch.offline)
        self.assertFalse(fetch.retry_missing)
        conformance = parser().parse_args([
            "validate-cda", "document.xml", "--report", "/tmp/conformance",
        ])
        self.assertEqual(conformance.files, ["document.xml"])
        self.assertEqual(conformance.report, "/tmp/conformance")

    def test_propose_input_writes_only_csv_and_code_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            source.mkdir()
            (source / "cases.csv").write_text(
                "patient_id;Aufnahmezeitpunkt;Triage\n1;2026-01-01T12:00:00;rot\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model_dir = transaction_model_dir(root)
            model_dir.mkdir(parents=True)
            write_json(model_dir / "model.json", {
                "meta": {
                    "dataset_id": "dataset",
                    "transaction_id": TRANSACTIONS[0]["id"],
                    "transaction_effective_date": TRANSACTIONS[0]["effective_date"],
                },
                "fields": {
                    "aufnahme.aufnahmezeitpunkt": {
                        "name": "Aufnahmezeitpunkt",
                        "type": "datetime",
                    },
                    "aufnahme.triage": {
                        "name": "Triage",
                        "type": "code",
                        "accepted_values": {
                            "rot": {"code": "R", "display_name": "Rot"},
                            "orange": {"code": "O", "display_name": "Orange"},
                        },
                    },
                },
            })

            self.assertEqual(
                main(["--root", str(root), "propose-input", "--input", str(source)]),
                0,
            )
            proposal_dir = transaction_site_dir(root)
            csv_proposal = load_json(proposal_dir / "csv-mapping.proposed.json")
            code_proposal = load_json(proposal_dir / "codes-mapping.proposed.json")
            self.assertEqual(csv_proposal["fields"]["aufnahme.aufnahmezeitpunkt"], "cases:Aufnahmezeitpunkt")
            self.assertEqual(csv_proposal["fields"]["aufnahme.triage"], "cases:Triage")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["rot"], "rot")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["R"], "rot")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["orange"], "orange")
            self.assertEqual(code_proposal["fields"]["aufnahme.triage"]["O"], "orange")
            self.assertFalse((model_dir / "cda-mapping.proposed.json").exists())
            self.assertEqual(main(["--root", str(root), "init-site-config"]), 0)
            site = load_json(root / "site" / "2026.1.2" / "site.json")
            self.assertEqual(site["input"]["case_source"], "cases")
            self.assertEqual(site["input"]["sources"]["cases"]["file"], "cases.csv")
            self.assertEqual(site["transport"]["adapter"], "http-post")

    def test_init_site_config_adds_defaults_without_overwriting_user_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            site_dir = transaction_site_dir(root)
            write_json(site_dir / "csv-mapping.proposed.json", {"version": 1, "fields": {}})
            write_json(site_dir / "codes-mapping.proposed.json", {
                "version": 1,
                "fields": {"triage": {"R": "rot", "O": "orange", "unknown": None}},
            })
            write_json(site_dir / "codes-mapping.json", {
                "version": 1,
                "fields": {"triage": {"R": "custom"}},
            })
            (site_dir / "csv-mapping.md").write_text("# CSV guide", encoding="utf-8")
            model_dir = transaction_model_dir(root)
            model_dir.mkdir(parents=True)
            (model_dir / "codes-mapping.md").write_text(
                "# Model code guide", encoding="utf-8"
            )

            self.assertEqual(main(["--root", str(root), "init-site-config"]), 0)
            configured = load_json(site_dir / "codes-mapping.json")
            self.assertEqual(configured["fields"]["triage"]["R"], "custom")
            self.assertEqual(configured["fields"]["triage"]["O"], "orange")
            self.assertNotIn("unknown", configured["fields"]["triage"] )
            self.assertEqual(
                (site_dir / "codes-mapping.md").read_text(), "# Model code guide"
            )

    def test_initializers_never_overwrite_user_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model = transaction_model_dir(root)
            model.mkdir(parents=True)
            write_json(model / "model.json", {"fields": {"a": {"type": "text"}}})
            write_json(model / "cda.json", {"document": [], "targets": {}})
            write_json(model / "mapping-audit.json", {"fields": {}})
            (model / "cda-mapping.proposed.json").write_text('{"fields":{"a":"Doc.value"}}')
            (model / "cda-mapping.proposed.md").write_text(
                "# CDA guide", encoding="utf-8"
            )
            (model / "cda-mapping-details.md").write_text("# CDA details", encoding="utf-8")
            (model / "cda-mapping-trees.md").write_text("# CDA trees", encoding="utf-8")
            (model / "cda-mapping-trees-extended.md").write_text(
                "# Extended CDA trees", encoding="utf-8"
            )
            site_dir = transaction_site_dir(root)
            site_dir.mkdir(parents=True)
            (site_dir / "csv-mapping.proposed.json").write_text('{"fields":{"a":"cases:a"}}')
            (site_dir / "codes-mapping.proposed.json").write_text('{"fields":{}}')
            (site_dir / "csv-mapping.md").write_text("# CSV guide", encoding="utf-8")
            (site_dir / "codes-mapping.md").write_text("# Code guide", encoding="utf-8")
            self.assertEqual(main(["--root", str(root), "init-cda-mapping"]), 0)
            self.assertEqual(main(["--root", str(root), "init-site-config"]), 0)
            config = site_dir / "csv-mapping.json"
            config.write_text('{"user":true}')
            self.assertEqual(main(["--root", str(root), "init-cda-mapping"]), 0)
            self.assertEqual(main(["--root", str(root), "init-site-config"]), 0)
            self.assertEqual(load_json(config), {"user": True})
            self.assertTrue((root / "site" / "2026.1.2" / "site.json").exists())
            mapping_dir = transaction_mapping_dir(root)
            self.assertTrue((mapping_dir / "mapping-lock.json").exists())
            self.assertEqual((mapping_dir / "cda-mapping.md").read_text(), "# CDA guide")
            self.assertEqual((mapping_dir / "cda-mapping-details.md").read_text(), "# CDA details")
            self.assertEqual((mapping_dir / "cda-mapping-trees.md").read_text(), "# CDA trees")
            self.assertEqual(
                (mapping_dir / "cda-mapping-trees-extended.md").read_text(),
                "# Extended CDA trees",
            )
            self.assertEqual((site_dir / "codes-mapping.md").read_text(), "# Code guide")
            self.assertFalse((mapping_dir / "codes-mapping.md").exists())

    def test_init_cda_mapping_reset_replaces_review_and_refreshes_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model_dir = transaction_model_dir(root)
            model_dir.mkdir(parents=True)
            write_json(model_dir / "model.json", {
                "meta": {"transaction_id": TRANSACTIONS[0]["id"]},
                "fields": {"a": {"type": "text"}}, "groups": {},
            })
            write_json(model_dir / "cda.json", {
                "document": [], "targets": {}, "validation_rules": [],
                "unresolved_templates": [],
            })
            write_json(model_dir / "mapping-audit.json", {"fields": {}})
            proposal = {"version": 7, "fields": {"a": None}}
            write_json(model_dir / "cda-mapping.proposed.json", proposal)
            for guide in (
                "cda-mapping.proposed.md", "cda-mapping-details.md",
                "cda-mapping-trees.md", "cda-mapping-trees-extended.md",
            ):
                (model_dir / guide).write_text("# guide", encoding="utf-8")

            self.assertEqual(main(["--root", str(root), "init-cda-mapping"]), 0)
            mapping_dir = transaction_mapping_dir(root)
            mapping_path = mapping_dir / "cda-mapping.json"
            lock_path = mapping_dir / "mapping-lock.json"
            old_lock = load_json(lock_path)
            write_json(mapping_path, {"version": 7, "fields": {"a": "reviewed"}})
            write_json(model_dir / "model.json", {
                "meta": {"transaction_id": TRANSACTIONS[0]["id"]},
                "fields": {"a": {"type": "text", "description": "changed"}},
                "groups": {},
            })

            self.assertEqual(main(["--root", str(root), "init-cda-mapping"]), 0)
            self.assertEqual(load_json(mapping_path)["fields"]["a"], "reviewed")
            self.assertEqual(load_json(lock_path), old_lock)

            self.assertEqual(main([
                "--root", str(root), "init-cda-mapping", "--reset",
            ]), 0)
            self.assertEqual(load_json(mapping_path), proposal)
            self.assertNotEqual(load_json(lock_path)["model_sha256"], old_lock["model_sha256"])

    def test_setup_and_run_cda_mapping_test_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model_dir = transaction_model_dir(root)
            model_dir.mkdir(parents=True)
            model: dict[str, Any] = {
                "meta": {"transaction_id": TRANSACTIONS[0]["id"]},
                "groups": {},
                "fields": {"case.note": {"name": "Note", "type": "text", "repeat_chain": []}},
            }
            cda = {
                "document": [{
                    "kind": "element", "name": "hl7:ClinicalDocument", "min": 1, "max": 1,
                    "attributes": [], "children": [{
                        "kind": "element", "name": "hl7:text", "datatype": "ST",
                        "min": 0, "max": 1, "attributes": [], "children": [],
                        "targets": ["Document.note"],
                    }], "targets": [],
                }],
                "targets": {
                    "Document.note": {
                        "renderable": True, "prohibited": False, "locations": ["0.0"],
                        "writable": True, "logical_types": ["text"],
                        "value_representation": {
                            "kind": "element_text", "logical_types": ["text"],
                        },
                        "datatype": "ST", "path": "hl7:ClinicalDocument/hl7:text",
                        "repeat_ancestors": [],
                    }
                },
                "validation_rules": [], "unresolved_templates": [],
            }
            mapping = {"version": 2, "fields": {"case.note": "Document.note"}, "structures": {}}
            write_json(model_dir / "model.json", model)
            write_json(model_dir / "cda.json", cda)
            write_json(model_dir / "cda-mapping.proposed.json", mapping)
            (model_dir / "cda-mapping.proposed.md").write_text(
                "# CDA guide", encoding="utf-8"
            )
            (model_dir / "cda-mapping-details.md").write_text("# CDA details", encoding="utf-8")
            (model_dir / "cda-mapping-trees.md").write_text("# CDA trees", encoding="utf-8")
            (model_dir / "cda-mapping-trees-extended.md").write_text(
                "# Extended CDA trees", encoding="utf-8"
            )
            self.assertEqual(main(["--root", str(root), "init-cda-mapping"]), 0)
            with patch("decor2hl7.cli._compiler_inputs", return_value={"templates": []}), patch(
                "decor2hl7.validate.verify_compiled_against_artdecor", return_value=[]
            ):
                self.assertEqual(main(["--root", str(root), "check-cda-mapping"]), 0)
            self.assertEqual(main(["--root", str(root), "setup-test"]), 0)
            fixture = transaction_test_dir(root)
            self.assertTrue((fixture / "input" / "cases.csv").exists())
            self.assertTrue((fixture / "config" / "site.json").exists())
            self.assertTrue((fixture / "expected.json").exists())
            external_out = root / "review-results"
            self.assertEqual(main([
                "--root", str(root), "test-cda-mapping", "--out", str(external_out)
            ]), 0)
            self.assertTrue((external_out / "test-1.xml").exists())
            self.assertEqual(load_json(external_out / "results.json")["status"], "PASS")
            self.assertFalse((root / "out" / RELEASES[0]["key"] / TRANSACTIONS[0]["key"]).exists())
            self.assertEqual(list((root / "state").iterdir()), [])

            scenario = root / "authored-scenario"
            (scenario / "input").mkdir(parents=True)
            write_json(scenario / "scenario.json", {
                "version": 1,
                "name": "two-authored-cases",
                "release": RELEASES[0]["key"],
                "transaction": {
                    "key": TRANSACTIONS[0]["key"],
                    "id": TRANSACTIONS[0]["id"],
                    "effective_date": TRANSACTIONS[0]["effective_date"],
                },
                "input": {
                    "join_column": "case_id",
                    "case_source": "cases",
                    "sources": {
                        "cases": {"file": "cases.csv", "cardinality": "1:1"},
                    },
                },
                "expected": {
                    "cases": ["CASE-A", "CASE-B"],
                    "documents": 2,
                    "coverage": {"all_mapped_except": []},
                    "case_fields": {
                        "CASE-A": {"present": ["case.note"]},
                        "CASE-B": {"present": ["case.note"]},
                    },
                },
            })
            (scenario / "input" / "cases.csv").write_text(
                "case_id,case.note\nCASE-A,First authored note\n"
                "CASE-B,Second authored note\n",
                encoding="utf-8",
            )
            self.assertEqual(main([
                "--root", str(root), "setup-test", "--force",
                "--scenario", str(scenario),
            ]), 0)
            expected = load_json(fixture / "expected.json")
            self.assertEqual(expected["cases"], ["CASE-A", "CASE-B"])
            self.assertEqual(expected["scenario"]["name"], "two-authored-cases")
            authored_out = root / "authored-results"
            self.assertEqual(main([
                "--root", str(root), "test-cda-mapping", "--out", str(authored_out)
            ]), 0)
            authored = load_json(authored_out / "results.json")
            self.assertEqual(authored["status"], "PASS")
            self.assertEqual(
                authored["documents"], ["case-a.xml", "case-b.xml"]
            )
            self.assertEqual(authored["scenario"]["name"], "two-authored-cases")

    def test_check_cda_mapping_reports_site_requirement_as_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["--root", str(root), "init"]), 0)
            set_release(root, RELEASES[0])
            set_transaction(root, TRANSACTIONS[0])
            model_dir = transaction_model_dir(root)
            model_dir.mkdir(parents=True)
            model = {
                "meta": {"transaction_id": TRANSACTIONS[0]["id"]},
                "groups": {}, "fields": {},
            }
            leaf = {
                "kind": "element", "name": "hl7:confidentialityCode",
                "datatype": "CE", "min": 1, "max": 1,
                "mandatory": True, "conformance": "M",
                "attributes": [], "children": [], "fixed": {},
                "targets": ["Header.confidentialityCode"],
            }
            cda = {
                "document": [{
                    "kind": "element", "name": "hl7:ClinicalDocument",
                    "min": 1, "max": 1, "mandatory": True,
                    "attributes": [], "children": [leaf], "fixed": {},
                    "targets": [],
                }],
                "targets": {"Header.confidentialityCode": {
                    **leaf,
                    "name": "Header.confidentialityCode",
                    "locations": ["0.0"], "renderable": True,
                    "writable": True, "prohibited": False,
                    "logical_types": ["code"],
                    "value_representation": {
                        "kind": "coded", "attributes": ["code"],
                        "scalar_attribute": "code",
                    },
                }},
                "validation_rules": [], "unresolved_templates": [],
            }
            mapping = {
                "version": 8, "fields": {}, "structures": {},
                "site_requirements": {"Header.confidentialityCode": {
                    "channel": "values",
                    "reason": "Confidentiality is deployment policy.",
                }},
            }
            write_json(model_dir / "model.json", model)
            write_json(model_dir / "cda.json", cda)
            write_json(model_dir / "mapping-audit.json", {"fields": {}})
            write_json(model_dir / "cda-mapping.proposed.json", mapping)
            for guide in (
                "cda-mapping.proposed.md", "cda-mapping-details.md",
                "cda-mapping-trees.md", "cda-mapping-trees-extended.md",
            ):
                (model_dir / guide).write_text("# guide", encoding="utf-8")
            self.assertEqual(main(["--root", str(root), "init-cda-mapping"]), 0)

            output = StringIO()
            with redirect_stdout(output), patch(
                "decor2hl7.cli._compiler_inputs", return_value={"templates": []}
            ), patch(
                "decor2hl7.validate.verify_compiled_against_artdecor",
                return_value=[],
            ):
                result = main(["--root", str(root), "check-cda-mapping"])

            self.assertEqual(result, 0)
            self.assertIn("CDA site requirements: 1", output.getvalue())
            self.assertIn(
                "site config required: "
                "cda.values['Header.confidentialityCode']",
                output.getvalue(),
            )
            self.assertIn("CDA mapping: OK", output.getvalue())

    def test_authored_scenario_identity_is_pinned_to_the_selected_spec(self) -> None:
        from decor2hl7.testing import setup_fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = root / "scenario"
            (scenario / "input").mkdir(parents=True)
            write_json(scenario / "scenario.json", {
                "version": 1,
                "name": "wrong-release",
                "release": "2025.0.0",
                "transaction": {
                    "key": TRANSACTIONS[0]["key"],
                    "id": TRANSACTIONS[0]["id"],
                    "effective_date": TRANSACTIONS[0]["effective_date"],
                },
                "input": {
                    "case_source": "cases",
                    "sources": {"cases": {"file": "cases.csv"}},
                },
                "expected": {"cases": ["CASE-A"]},
            })
            (scenario / "input" / "cases.csv").write_text(
                "case_id,case.note\nCASE-A,Note\n", encoding="utf-8"
            )
            model = {"groups": {}, "fields": {
                "case.note": {"type": "text", "repeat_chain": []},
            }}
            mapping = {"fields": {"case.note": None}}
            fixture = root / "fixture"
            setup_fixture(
                fixture, RELEASES[0], TRANSACTIONS[0], model,
                {"targets": {}}, mapping,
            )
            original_input = (fixture / "input/cases.csv").read_text()
            with self.assertRaisesRegex(ValueError, "scenario identity mismatch"):
                setup_fixture(
                    fixture, RELEASES[0], TRANSACTIONS[0], model,
                    {"targets": {}}, mapping,
                    scenario_dir=scenario, force=True,
                )
            self.assertEqual(
                (fixture / "input/cases.csv").read_text(), original_input
            )

    def test_authored_scenario_copies_explicit_repeat_sources(self) -> None:
        from decor2hl7.testing import setup_fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = root / "scenario"
            (scenario / "input").mkdir(parents=True)
            write_json(scenario / "scenario.json", {
                "version": 1,
                "name": "repeat-cases",
                "release": RELEASES[0]["key"],
                "transaction": {
                    "key": TRANSACTIONS[0]["key"],
                    "id": TRANSACTIONS[0]["id"],
                    "effective_date": TRANSACTIONS[0]["effective_date"],
                },
                "input": {
                    "case_source": "cases",
                    "sources": {
                        "cases": {"file": "cases.csv", "cardinality": "1:1"},
                        "events": {
                            "file": "events.csv", "cardinality": "1:n",
                            "occurrence_keys": {"events": "event_id"},
                        },
                    },
                },
                "expected": {
                    "cases": ["CASE-A", "CASE-B"], "documents": 2,
                },
            })
            (scenario / "input/cases.csv").write_text(
                "case_id,case.note\nCASE-A,One\nCASE-B,Two\n", encoding="utf-8"
            )
            (scenario / "input/events.csv").write_text(
                "case_id,event_id,events.value\nCASE-A,1,Alpha\n"
                "CASE-A,2,Beta\nCASE-B,1,Gamma\n",
                encoding="utf-8",
            )
            model = {
                "groups": {"events": {"repeating": True}},
                "fields": {
                    "case.note": {"type": "text", "repeat_chain": []},
                    "events.value": {
                        "type": "text", "repeat_chain": ["events"],
                    },
                },
            }
            fixture = root / "fixture"
            expected = setup_fixture(
                fixture, RELEASES[0], TRANSACTIONS[0], model,
                {"targets": {}},
                {"fields": {"case.note": None, "events.value": None}},
                scenario_dir=scenario,
            )
            csv_mapping = load_json(fixture / "config/csv-mapping.json")
            site = load_json(fixture / "config/site.json")
            self.assertEqual(csv_mapping["fields"], {
                "case.note": "cases:case.note",
                "events.value": "events:events.value",
            })
            self.assertEqual(site["input"]["sources"]["events"], {
                "file": "events.csv", "cardinality": "1:n",
                "occurrence_keys": {"events": "event_id"},
            })
            self.assertEqual(expected["repeat_sources"], [{
                "source": "events", "repeat_chains": ["events"], "rows": 3,
            }])

    def test_force_refuses_to_delete_unmarked_input_directories(self) -> None:
        from decor2hl7.testing import setup_fixture

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "not-a-fixture"
            (fixture / "input").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "without a decor2hl7 fixture"):
                setup_fixture(
                    fixture, RELEASES[0], TRANSACTIONS[0],
                    {"groups": {}, "fields": {}}, {"targets": {}},
                    {"fields": {}}, force=True,
                )
            self.assertTrue((fixture / "input").is_dir())

    def test_synthetic_repeat_fixture_exercises_small_code_domain(self) -> None:
        from decor2hl7.testing import setup_fixture

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            model: dict[str, Any] = {
                "groups": {"diagnoses": {"repeating": True}},
                "fields": {
                    "diagnoses.certainty": {
                        "type": "code", "repeat_chain": ["diagnoses"],
                        "accepted_values": {
                            key: {"code": key, "code_system": "1.2.3"}
                            for key in ("V", "A", "Z", "G")
                        },
                    },
                    "diagnoses.leading": {
                        "type": "boolean", "repeat_chain": ["diagnoses"]
                    },
                    "diagnoses.sequence": {
                        "type": "integer", "min_value": 1,
                        "repeat_chain": ["diagnoses"],
                    },
                },
            }
            expected = setup_fixture(
                fixture, RELEASES[0], TRANSACTIONS[0], model,
                {"targets": {}},
                {"fields": {path: None for path in model["fields"]}},
            )
            source = expected["repeat_sources"][0]["source"]
            with (fixture / "input" / f"{source}.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual([row["diagnoses.certainty"] for row in rows], ["V", "A", "Z", "G"])
            self.assertEqual(rows[0]["diagnoses.leading"], "true")
            self.assertTrue(all(row["diagnoses.leading"] == "false" for row in rows[1:]))
            self.assertEqual(
                [row["diagnoses.sequence"] for row in rows], ["1", "2", "3", "4"]
            )

    def test_stale_pending_output_is_pruned_when_source_changes_or_reverts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            xml = out / "case-v2.xml"
            sidecar = out / "case-v2.json"
            xml.write_text("<old/>", encoding="utf-8")
            write_json(sidecar, {"state_key": "tx::case", "fingerprint": "old"})
            removed = _prune_stale_pending(out, "tx::case", "current")
            self.assertEqual(removed, 1)
            self.assertFalse(xml.exists())
            self.assertFalse(sidecar.exists())


    def test_absent_pending_output_is_pruned_but_sent_artifact_is_kept(self) -> None:
        from decor2hl7 import state
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            state_path = root / "state"
            out.mkdir()
            (out / "pending.xml").write_text("<pending/>", encoding="utf-8")
            write_json(out / "pending.json", {"state_key": "tx::gone", "fingerprint": "new"})
            (out / "sent.xml").write_text("<sent/>", encoding="utf-8")
            write_json(out / "sent.json", {"state_key": "tx::sent", "fingerprint": "same"})
            state.record_sent(state_path, key="tx::sent", digest="same", document_version=1, file="sent.xml", spec_version="v")
            removed = _prune_absent_pending(out, set(), state_path)
            self.assertEqual(removed, 1)
            self.assertFalse((out / "pending.xml").exists())
            self.assertTrue((out / "sent.xml").exists())



if __name__ == "__main__":
    unittest.main()
