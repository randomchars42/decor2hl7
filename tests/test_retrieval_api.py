from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from decor2hl7.cda.extensions import load_extensions
from decor2hl7.retrieval.catalog import parse_releases, parse_transactions, transactions
from decor2hl7.retrieval.references import display_references, hard_references
from decor2hl7.retrieval import api as retrieval_api
from decor2hl7.retrieval.api import REQUIRED_PATHS, artifact_representations
from decor2hl7.retrieval.sources import apply_source_hint, load_source_hints
from decor2hl7.workspace import transaction_key


RELEASE = {"key": "release-v1", "label": "release-v1", "date": "2024-01-02T03:04:05", "status": "final"}


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()


def api_path(url: str) -> str:
    return urlsplit(url).path


class RetrievalApiTests(unittest.TestCase):
    def test_openapi_contract_validation_reports_shape_and_missing_operations(self) -> None:
        validated = retrieval_api.validate_openapi(API_CONTRACT)
        self.assertEqual(validated["title"], "Test API")
        self.assertEqual(validated["version"], "3.10.2")
        self.assertEqual(validated["required_paths"], sorted(REQUIRED_PATHS))

        for payload, message in (
            (b"[]", "JSON object"),
            (b"{}", "no paths object"),
            (b'{"paths": {}}', "missing required operations"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    retrieval_api.validate_openapi(payload)

    def test_api_url_builders_quote_paths_and_keep_query_ownership_separate(self) -> None:
        base = "https://example.invalid/api/"
        self.assertEqual(
            retrieval_api.openapi_url(base),
            "https://example.invalid/api/modules/library/api.json",
        )
        self.assertEqual(
            retrieval_api.projects_url(base_url=base),
            "https://example.invalid/api/project",
        )
        self.assertIn(
            "/project/main%20%2F%20one",
            retrieval_api.project_url("main / one", base_url=base),
        )
        publication = retrieval_api.publications_url("main-", base_url=base)
        self.assertTrue(publication.endswith("/project/main-/$publication"))

        transaction_catalog = retrieval_api.transactions_url(
            "main-", "2024-01-02", language="en-US", base_url=base
        )
        self.assertEqual(
            parse_qs(urlsplit(transaction_catalog).query),
            {
                "project": ["main-"],
                "release": ["2024-01-02"],
                "language": ["en-US"],
            },
        )

        extract = retrieval_api.project_extract_url(
            "main-", language="en-US", release="2024-01-02", base_url=base
        )
        extract_query = parse_qs(urlsplit(extract).query)
        self.assertEqual(extract_query["release"], ["2024-01-02"])
        self.assertEqual(extract_query["language"], ["en-US"])
        self.assertEqual(extract_query["mode"], ["verbatim"])

        rows = retrieval_api.transaction_representations(
            "1.2/3", "2024-01-01T00:00:00",
            project="main-", release="2024-01-02", language="en-US",
            base_url=base,
        )
        self.assertEqual([row["form"] for row in rows], ["source", "analysis"])
        self.assertIn("transaction/1.2%2F3/", rows[0]["url"])
        self.assertEqual(parse_qs(urlsplit(rows[0]["url"]).query)["prefix"], ["main-"])
        self.assertEqual(parse_qs(urlsplit(rows[1]["url"]).query)["project"], ["main-"])

        expansion = retrieval_api.valueset_expansion_url(
            "1.2/3", "2024-01-01", project="term-", language="en-US",
            base_url=base,
        )
        self.assertIn("valueset/1.2%2F3/2024-01-01/$expand", expansion)
        self.assertEqual(parse_qs(urlsplit(expansion).query)["expand"], ["true"])

    def test_dynamic_dataset_and_concept_requests_use_only_supported_forms(self) -> None:
        dataset = artifact_representations(
            {"kind": "dataset", "id": "1.2.3", "effective_date": ""},
            project="external-", main_project="main-", release="2024-01-02",
            language="en-US",
        )
        self.assertEqual([row["form"] for row in dataset], ["source"])
        self.assertNotIn("release=", dataset[0]["url"])

        concept = artifact_representations(
            {
                "kind": "concept", "id": "4.5.6", "effective_date": "2024-02-03",
                "dataset": "1.2.3", "dataset_effective_date": "2024-01-01",
            },
            project="main-", main_project="main-", release="2024-01-02",
            language="en-US",
        )
        self.assertEqual([row["form"] for row in concept], ["source", "analysis"])
        source_query = parse_qs(urlsplit(concept[0]["url"]).query)
        analysis_query = parse_qs(urlsplit(concept[1]["url"]).query)
        self.assertEqual(source_query["transactionId"], ["1.2.3"])
        self.assertEqual(source_query["associations"], ["true"])
        self.assertEqual(analysis_query["datasetOrTransactionId"], ["1.2.3"])

    def test_catalog_keys_are_human_readable_and_stable(self) -> None:
        releases = parse_releases('''<return><release date="2024-01-02T03:04:05" versionLabel="release-v1" statusCode="final"/></return>''')
        self.assertEqual(releases[0]["key"], "release-v1")
        rows = parse_transactions('''<project><transaction id="1.2.3.4.1" effectiveDate="2024-01-01T00:00:00" versionLabel="2026"><name>Example transaction</name></transaction></project>''')
        self.assertEqual(rows[0]["key"], "example--1")
        self.assertEqual(transaction_key(rows[0]["name"], rows[0]["id"]), rows[0]["key"])

    def test_transaction_catalog_uses_current_api_transaction_view(self) -> None:
        calls: list[str] = []
        def fake_get(url: str, **_: object) -> bytes:
            calls.append(url)
            return b'<return><transaction id="1.2.3" effectiveDate="2026-01-01T00:00:00" versionLabel="2026"><name>Example</name></transaction></return>'
        with patch("decor2hl7.retrieval.catalog.get", side_effect=fake_get):
            rows = transactions("main-", "2024-01-02T03:04:05", ipv4=True)
        self.assertEqual(rows[0]["id"], "1.2.3")
        self.assertEqual(len(calls), 1)
        self.assertTrue(api_path(calls[0]).endswith("/transaction"))
        self.assertIn("project=main-", calls[0])
        self.assertIn("release=2024-01-02T03%3A04%3A05", calls[0])

    def test_template_api_retains_source_and_expanded_analysis_forms(self) -> None:
        rows = artifact_representations(
            {
                "kind": "template", "id": "1.2.3",
                "effective_date": "2025-05-01T00:00:00",
            },
            project="main-", main_project="main-", release=RELEASE["date"],
            language="de-DE",
        )
        self.assertEqual([row["form"] for row in rows], ["source", "analysis"])
        self.assertIn("/template/1.2.3/2025-05-01T00%3A00%3A00/$extract", rows[0]["url"])
        self.assertNotIn("tree=expand", rows[0]["url"])
        self.assertIn("tree=expand", rows[1]["url"])
        self.assertFalse(any("/decor/services/" in row["url"] for row in rows))
        self.assertFalse(any("expandedxml" in row["url"] for row in rows))

    def test_external_source_hint_supplies_exact_repository_identity(self) -> None:
        resolved = apply_source_hint(
            {
                "kind": "template",
                "id": "1.3.6.1.4.1.19376.1.9.1.3.1",
                "effective_date": "",
                "project": "",
            },
            load_source_hints(),
        )
        self.assertEqual(resolved["project"], "ch-pharm-")
        self.assertEqual(resolved["effective_date"], "2019-08-27T16:13:43")
        self.assertTrue(resolved["api_base"].endswith("/exist/apps/api"))

    def test_cda_extensions_are_exact_and_transaction_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cda-extensions.json"
            attachment = {
                "transaction_id": "tx", "transaction_effective_date": "2026",
                "document_template_id": "doc", "document_template_effective_date": "2026.1",
                "parent_template_id": "section", "parent_template_effective_date": "2024",
                "parent_element_id": "section-root", "element_name": "hl7:entry",
                "template_id": "entry", "template_effective_date": "2024",
                "minimum_multiplicity": 0, "maximum_multiplicity": 1,
                "conformance": "r", "reason": "Reviewed placement",
            }
            path.write_text(json.dumps({
                "format": 1,
                "attachments": [attachment, {**attachment, "transaction_id": "other"}],
            }), encoding="utf-8")
            selected = load_extensions(
                path, {"id": "tx", "effective_date": "2026"}
            )
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["conformance"], "R")
            self.assertEqual(selected[0]["template_id"], "entry")
            missing_maximum = dict(attachment)
            missing_maximum.pop("maximum_multiplicity")
            path.write_text(json.dumps({
                "format": 1, "attachments": [missing_maximum],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "maximum_multiplicity"):
                load_extensions(
                    path,
                    {"id": "tx", "effective_date": "2026"},
                )

            branch = {
                "operation": "select_spec_branch",
                "transaction_id": "tx", "transaction_effective_date": "2026",
                "document_template_id": "doc",
                "document_template_effective_date": "2026.1",
                "parent_template_id": "medication",
                "parent_template_effective_date": "2024",
                "parent_element_id": "medication-root",
                "element_name": "hl7:consumable",
                "template_id": "detail", "template_effective_date": "2024",
                "replaces_template_id": "simple",
                "replaces_template_effective_date": "2023",
                "reason": "Reviewed richer branch",
            }
            path.write_text(json.dumps({
                "format": 1, "attachments": [branch],
            }), encoding="utf-8")
            self.assertEqual(
                load_extensions(
                    path, {"id": "tx", "effective_date": "2026"}
                ),
                [branch],
            )

    def test_reference_project_is_inferred_from_art_decor_link(self) -> None:
        root = ET.fromstring('''<template>
          <include ref="1.2.3" flexibility="dynamic"
            href="https://art-decor.org/exist/apps/api/project/ad1bbr-/template/1.2.3"/>
          <vocabulary codeSystem="2.16.840.1.113883.5.25"
            url="https://art-decor.org/exist/apps/api/codesystem/2.16.840.1.113883.5.25?project=ad1bbr-"/>
        </template>''')
        template = next(
            row for row in hard_references(root) if row["kind"] == "template"
        )
        codesystem = next(
            row for row in display_references(root) if row["kind"] == "codesystem"
        )
        self.assertEqual(template["project"], "ad1bbr-")
        self.assertEqual(codesystem["project"], "ad1bbr-")


if __name__ == "__main__":
    unittest.main()
