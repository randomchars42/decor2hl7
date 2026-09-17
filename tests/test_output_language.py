from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from decor2hl7.cli import main, parser
from decor2hl7.compile.artifacts import write_build_diagnostics
from decor2hl7.compile.mapping import cda_mapping_audit
from decor2hl7.compile.reports import (
    render_accepted_cda_mappings_markdown,
    render_cda_mapping_extended_trees_markdown,
    render_cda_mapping_markdown,
    render_cda_mapping_trees_markdown,
    write_readable_cda,
)
from decor2hl7.compile.site import csv_mapping_proposal
from decor2hl7.conformance import write_conformance_report
from decor2hl7.testing import run_fixture
from decor2hl7.workspace import load_json, write_json


class OutputLanguageTests(unittest.TestCase):
    def test_workspace_language_localizes_cli_help_and_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stderr = StringIO()
            with redirect_stderr(stderr):
                status = main([
                    "--root", str(root),
                    "--output-language", "de-DE",
                    "init",
                ])
            self.assertEqual(status, 0)
            self.assertEqual(
                load_json(root / "decor2hl7.json")["output"],
                {"language": "de"},
            )
            self.assertIn("workspace initialisiert", stderr.getvalue())
            self.assertIn("workspace-Struktur anlegen", parser("de").format_help())

            stdout = StringIO()
            with redirect_stdout(stdout), self.assertRaises(SystemExit):
                main(["--root", str(root), "--help"])
            self.assertIn("workspace-Struktur anlegen", stdout.getvalue())
            self.assertIn("Optionen:", stdout.getvalue())

    def test_mapping_reports_localize_prose_but_keep_technical_terms(self) -> None:
        model: dict[str, Any] = {
            "fields": {
                "finding": {
                    "name": (
                        "Clinical leaf — No target-specific defaults are configured."
                    ),
                    "description": "Owner description",
                },
            },
            "order": ["finding"],
        }
        cda: dict[str, Any] = {
            "document": [],
            "targets": {},
            "datapoints": {},
            "document_template": {"name": "ClinicalDocument"},
        }
        mapping = {"fields": {"finding": None}}
        audit: dict[str, Any] = {"fields": {"finding": {}}}

        reports = (
            render_cda_mapping_markdown(
                model, cda, mapping, audit, output_language="de"
            ),
            render_cda_mapping_trees_markdown(
                model, cda, mapping, audit, output_language="de"
            ),
            render_cda_mapping_extended_trees_markdown(
                model, cda, mapping, audit, output_language="de"
            ),
            render_accepted_cda_mappings_markdown(
                model, cda, mapping, output_language="de"
            ),
        )
        combined = "\n".join(reports)
        self.assertIn("Dataset-to-CDA mapping-Entscheidungen", combined)
        self.assertIn(
            "Clinical leaf — No target-specific defaults are configured.", combined
        )
        self.assertIn("CDA leaf", combined)
        self.assertNotIn("Blatt", combined)

    def test_mapping_analysis_language_does_not_change_semantic_outputs(self) -> None:
        model: dict[str, Any] = {
            "meta": {},
            "fields": {"finding": {"name": "Clinical leaf", "type": "text"}},
            "groups": {},
            "order": ["finding"],
        }
        cda: dict[str, Any] = {
            "document": [],
            "targets": {},
            "datapoints": {},
            "document_template": {"name": "ClinicalDocument"},
            "stats": {},
            "unresolved_templates": [],
        }
        english = cda_mapping_audit(model, cda, [], output_language="en")
        german = cda_mapping_audit(model, cda, [], output_language="de")
        self.assertEqual(english[:2], german[:2])
        self.assertNotEqual(english[2:], german[2:])
        self.assertIn("Clinical leaf", german[2])
        self.assertNotIn("Blatt", "\n".join(german[2:]))

    def test_all_other_markdown_families_accept_the_output_language(self) -> None:
        model: dict[str, Any] = {
            "meta": {},
            "fields": {"finding": {"name": "Owner leaf", "type": "text"}},
        }
        english_proposal, english_site = csv_mapping_proposal(
            model, None, "case_id", output_language="en"
        )
        german_proposal, german_site = csv_mapping_proposal(
            model, None, "case_id", output_language="de"
        )
        self.assertEqual(english_proposal, german_proposal)
        self.assertIn("CSV-to-dataset mapping", german_site)
        self.assertIn("Owner leaf", german_site)
        self.assertNotEqual(english_site, german_site)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostics = write_build_diagnostics(
                root,
                {"unavailable_artifacts": []},
                {"unresolved_templates": []},
                output_language="de",
            )
            self.assertEqual(diagnostics["status"], "complete")
            self.assertIn(
                "Build-Diagnostik",
                (root / "build-diagnostics.md").read_text(encoding="utf-8"),
            )

            conformance = write_conformance_report(
                root / "conformance",
                scope="build",
                diagnostics=[],
                stages=[{"phase": "packages", "status": "passed", "detail": "ok"}],
                policy="report-only",
                output_language="de",
            )
            self.assertEqual(conformance["status"], "passed")
            self.assertIn(
                "Conformance-Validierung",
                (root / "conformance.md").read_text(encoding="utf-8"),
            )

            cda: dict[str, Any] = {
                "document": [],
                "targets": {},
                "document_template": {},
                "stats": {},
            }
            _xml, readable = write_readable_cda(
                root, cda, {"summary": {}}, output_language="de"
            )
            self.assertIn(
                "Erweitertes CDA template",
                readable.read_text(encoding="utf-8"),
            )

    def test_mapping_test_result_markdown_is_localized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test_dir = root / "test"
            config = test_dir / "config"
            config.mkdir(parents=True)
            write_json(test_dir / "expected.json", {
                "documents": 0,
                "generated_fields": [],
                "mapped_fields": [],
                "cda_mapping_sha256": None,
            })
            write_json(config / "csv-mapping.json", {
                "version": 2, "join": {"column": "case_id"}, "fields": {},
            })
            write_json(config / "codes-mapping.json", {"version": 1, "fields": {}})
            write_json(config / "site.json", {"version": 1})
            out = root / "out"

            result, _status = run_fixture(
                test_dir,
                out,
                {"fields": {}},
                {"document": [], "targets": {}, "validation_rules": []},
                {"fields": {}, "structures": {}},
                output_language="de",
            )
            self.assertIn(result["status"], {"PASS", "FAIL"})
            report = (out / "results.md").read_text(encoding="utf-8")
            self.assertIn("CDA mapping-Test", report)
            self.assertIn("## Umfang", report)
            self.assertNotIn("Blatt", report)


if __name__ == "__main__":
    unittest.main()
