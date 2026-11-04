from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

from decor2hl7.compile.artifacts import (
    compiler_inputs,
    selected_closure_template_revisions,
    selected_closure_templates,
    write_build_diagnostics,
)
from decor2hl7.cda.compile import compile_cda
from decor2hl7.retrieval.artifacts import (
    artifact_problems,
    artifact_record,
    closure_records,
)
from decor2hl7.retrieval.fetch import (
    RequestBudgetExceeded,
    _evidence_references,
    _fetch_want,
    _inventory,
    _payload_matches_request,
    _resolved_effective_date,
    _satisfied,
    fetch_spec,
)
from decor2hl7.retrieval.api import REQUIRED_PATHS
from decor2hl7.workspace import load_json


RELEASE = {"key": "release-v1", "label": "release-v1", "date": "2024-01-02T03:04:05", "status": "final"}


TRANSACTION = {
    "key": "example--1",
    "id": "1.2.3.4.1",
    "effective_date": "2024-01-01T00:00:00",
    "version_label": "v1",
    "status": "active",
    "name": "Example transaction",
}


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()


def api_path(url: str) -> str:
    return urlsplit(url).path


class RetrievalFetchTests(unittest.TestCase):
    def test_fetch_uses_release_cache_and_transaction_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "example--1"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b'<return><project id="9.9" prefix="ext-"/></return>'
                if "/transaction/t/" in path:
                    return b'<dataset id="d" transactionId="t" templateId="doc"><concept id="c" shortName="x" type="group"><name>X</name><contains ref="old" datasetId="9.9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if path.endswith("/project/main-/$extract"):
                    return b'<project><transaction id="t"><representingTemplate ref="doc"/></transaction><dataset id="9.9.1" effectiveDate="2020-01-01"><concept id="old" shortName="old" type="item"><name>Old embedded</name></concept></dataset></project>'
                if path.endswith("/project/main-"):
                    return b'<project><buildingBlockRepository ident="ext-"/></project>'
                if "/dataset/9.9.1/" in path:
                    return b'<dataset id="9.9.1" effectiveDate="2020-01-01"><concept id="old" shortName="old" type="item"><name>Old</name></concept></dataset>'
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026-01-01" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t"},
                    retry_missing=False, max_requests=50, progress=progress.append,
                )
            self.assertTrue((release_dir / "manifest.json").exists())
            self.assertTrue((tx_dir / "transaction.xml").exists())
            self.assertTrue((tx_dir / "closure.json").exists())
            self.assertTrue(any(path.parent.name == "datasets" for path in release_dir.rglob("*.xml")))
            self.assertTrue(any("/dataset/9.9.1/" in api_path(url) for url in calls))
            self.assertTrue(any(path.parent.name == "templates" for path in release_dir.rglob("*.xml")))
            self.assertFalse(result["closure"]["truncated"])
            self.assertTrue(any("API contract" in line and "requesting" in line for line in progress))
            self.assertTrue(any("dataset 9.9.1 @ 2020-01-01" in line for line in progress))
            self.assertTrue(any(line.startswith("fetch: complete:") for line in progress))

            before = len(calls)
            with patch("decor2hl7.retrieval.fetch.get", side_effect=AssertionError("cache miss")):
                fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t"},
                    retry_missing=False, max_requests=50,
                )
            self.assertEqual(len(calls), before)

    def test_fetches_static_template_even_when_present_in_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="2026-01-15T00:00:00"/></transaction>'
                if path.endswith("/project/main-/$extract"):
                    return b'<project><template id="doc" effectiveDate="2026-01-15T00:00:00" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></project>'
                if path.endswith("/project/main-"):
                    return b'<project/>'
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026-01-15T00:00:00" name="Doc"><element name="hl7:ClinicalDocument" id="root"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20, progress=progress.append,
                )

            self.assertTrue(any("/template/doc/" in api_path(url) for url in calls))
            self.assertFalse(result["closure"]["errors"])
            self.assertTrue(result["closure"]["build_ready"])
            self.assertIn(
                "template:doc@2026-01-15T00:00:00",
                result["closure"]["build_resources"],
            )

    def test_fetch_adds_reviewed_cda_extension_to_build_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []
            attachment = {
                "transaction_id": "t", "transaction_effective_date": "2026-03-25",
                "document_template_id": "doc", "document_template_effective_date": "2026",
                "parent_template_id": "section", "parent_template_effective_date": "2024",
                "parent_element_id": "section-root", "element_name": "hl7:entry",
                "template_id": "extra", "template_effective_date": "2024",
                "minimum_multiplicity": 0, "maximum_multiplicity": 1,
                "conformance": "R", "reason": "Reviewed placement",
            }

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="2026"/></transaction>'
                if path.endswith("/project/main-/$extract"):
                    return b"<project/>"
                if path.endswith("/project/main-"):
                    return b"<project/>"
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026" name="Doc"><element name="hl7:ClinicalDocument"/></template></return>'
                if "/template/extra/" in path:
                    return b'<return><template id="extra" effectiveDate="2024" name="Extra"><element name="hl7:observation"/></template></return>'
                raise AssertionError(url)

            transaction = {
                **TRANSACTION,
                "id": "t", "effective_date": "2026-03-25", "key": "tx",
            }
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-", release=RELEASE,
                    transaction=transaction, max_requests=30,
                    cda_extensions=[attachment],
                )
            self.assertTrue(any("/template/extra/" in api_path(url) for url in calls))
            self.assertIn(
                "template:extra@2024", result["closure"]["build_resources"]
            )
            self.assertEqual(result["closure"]["cda_extensions"], [attachment])
            self.assertEqual(
                compiler_inputs(release_dir, tx_dir)["cda_extensions"],
                [attachment],
            )

    def test_dynamic_template_is_fetched_and_frozen_not_taken_from_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="dynamic"/></transaction>'
                if path.endswith("/project/main-/$extract"):
                    return (
                        b'<project>'
                        b'<template id="doc" effectiveDate="2026-02-01T00:00:00" name="ReleasedDoc"><element name="hl7:ClinicalDocument" id="released"/></template>'
                        b'<template id="doc" effectiveDate="2026-05-01T00:00:00" name="FutureDraft"><element name="hl7:ClinicalDocument" id="future"/></template>'
                        b'</project>'
                    )
                if path.endswith("/project/main-"):
                    return b'<project/>'
                if "/template/doc" in path:
                    return b'<return><template id="doc" effectiveDate="2026-02-01T00:00:00" name="ReleasedDoc"><element name="hl7:ClinicalDocument" id="released"/></template></return>'
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20, progress=progress.append,
                )

            self.assertTrue(any("/template/doc" in api_path(url) for url in calls))
            self.assertFalse(result["closure"]["errors"])
            entry = result["manifest"]["resources"]["template:doc"]
            self.assertEqual(entry["resolved_effective_date"], "2026-02-01T00:00:00")
            self.assertTrue(result["closure"]["build_ready"])

    def test_fetch_interrupt_writes_incomplete_closure_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"

            def fake_get(url: str, **_: object) -> bytes:
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b"<return/>"
                if "/transaction/t/" in path:
                    return b'<dataset id="d"><concept id="c"><contains ref="old" datasetId="9.9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if path.endswith("/project/main-/$extract") or path.endswith("/project/main-"):
                    return b'<project><transaction id="t"/></project>'
                if "/dataset/9.9.1/" in path:
                    raise KeyboardInterrupt
                raise AssertionError(url)

            progress: list[str] = []
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                with self.assertRaises(KeyboardInterrupt):
                    fetch_spec(
                        release_dir, tx_dir, prefix="main-",
                        release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                        max_requests=20, progress=progress.append,
                    )

            closure = load_json(tx_dir / "closure.json")
            self.assertFalse(closure["crawl_complete"])
            self.assertTrue(closure["interrupted"])
            self.assertIn("build-interrupted", closure["phase"])
            self.assertIn("dataset:9.9.1@2020-01-01", closure["pending"]["build"])
            self.assertTrue((release_dir / "manifest.json").exists())
            self.assertTrue(any("checkpoint saved" in line for line in progress))
            with self.assertRaisesRegex(ValueError, "crawl is incomplete"):
                closure_records(release_dir, tx_dir)

            # A cache-only rerun settles the pending closure without touching
            # the unavailable server. Uncached dependencies remain explicit
            # degraded inputs and can be retried by a later online fetch.
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("offline fetch attempted HTTP"),
            ) as mocked:
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE,
                    transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    offline=True, max_requests=20,
                )
            self.assertEqual(mocked.call_count, 0)
            self.assertTrue(result["closure"]["crawl_complete"])
            self.assertTrue(result["closure"]["build_ready"])
            self.assertEqual(result["closure"]["recursive_http_requests"], 0)
            self.assertIn(
                "dataset:9.9.1@2020-01-01",
                result["closure"]["unavailable"],
            )

    def test_recursive_request_budget_counts_actual_http_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "project": "first-"}
            budget = {"made": 0, "max": 1}
            def missing(_url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(_url, 404, "missing", Message(), None)
            with patch("decor2hl7.retrieval.fetch.get", side_effect=missing):
                with self.assertRaises(RequestBudgetExceeded):
                    _fetch_want(
                        Path(tmp), manifest, want, owners={}, repositories=["first-", "second-"],
                        language="de-DE", ipv4=True, retry_missing=False, request_budget=budget,
                    )
            self.assertEqual(budget["made"], 1)
            self.assertNotIn("template:1.2.3", manifest["resources"])

    def test_live_evidence_does_not_seed_unrelated_external_crawl(self) -> None:
        root = ET.fromstring('''<project>
          <concept id="relevant"><name>Relevant</name><inherit ref="old" datasetId="9.1" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept>
          <concept id="unrelated"><name>Unrelated</name><inherit ref="other" datasetId="9.2" datasetEffectiveDate="2020-01-01" prefix="ext-"/></concept>
        </project>''')
        refs = _evidence_references(root, {"relevant"})
        self.assertEqual({item["id"] for item in refs if item["kind"] == "concept"}, {"old"})
        self.assertFalse(any(item["kind"] == "dataset" for item in refs))

    def test_fetch_want_adopts_cached_analysis_without_backfilling_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "1.2.3_2025-05-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="1.2.3" effectiveDate="2025-05-01" name="T"><element name="hl7:observation"/></template></return>',
                encoding="utf-8",
            )
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "2025-05-01", "project": "main-"}
            progress: list[str] = []
            with patch(
                "decor2hl7.retrieval.fetch.get",
                return_value=target.read_bytes(),
            ) as mocked:
                path = _fetch_want(
                    release_dir, manifest, want, owners={}, repositories=["main-"],
                    language="de-DE", ipv4=True, retry_missing=False, progress=progress.append,
                )
            self.assertEqual(path, target)
            entry = manifest["resources"]["template:1.2.3@2025-05-01"]
            self.assertEqual(entry["status"], "ok")
            self.assertEqual(entry["file"], "templates/1.2.3_2025-05-01.xml")
            self.assertTrue(entry["sha256"])
            self.assertNotIn("source", entry["representations"])
            self.assertEqual(
                entry["source_warning"], "source representation unavailable"
            )
            self.assertEqual(mocked.call_count, 0)

    def test_exact_request_reuses_matching_frozen_dynamic_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "detail_resource.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="detail" effectiveDate="2025" '
                'name="Detail"><element name="hl7:observation"/></template></return>',
                encoding="utf-8",
            )
            payload = target.read_bytes()
            manifest: dict[str, Any] = {"resources": {
                "template:detail": {
                    "status": "ok",
                    "file": "templates/detail_resource.xml",
                    "project": "profile-",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "requested_effective_date": "dynamic",
                    "resolved_effective_date": "2025",
                    "representations": {
                        "analysis": {
                            "status": "ok",
                            "file": "templates/detail_resource.xml",
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        },
                    },
                    "identity": {
                        "type": "template", "id": "detail",
                        "effective_date": "2025", "project": "profile-",
                    },
                },
            }}
            want = {
                "kind": "template", "id": "detail",
                "effective_date": "2025", "project": "profile-",
            }
            with patch("decor2hl7.retrieval.fetch.get") as mocked:
                path = _fetch_want(
                    release_dir, manifest, want, owners={},
                    repositories=["profile-"], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True,
                )
            self.assertEqual(path, target)
            self.assertEqual(mocked.call_count, 0)
            exact = manifest["resources"]["template:detail@2025"]
            self.assertEqual(exact["status"], "ok")
            self.assertEqual(exact["file"], "templates/detail_resource.xml")
            self.assertEqual(exact["resolved_effective_date"], "2025")

    def test_referenced_codesystem_cache_is_adopted_offline(self) -> None:
        """A cached reference declaration is a cache hit for its own identity.

        A code system a project references rather than defines is published with
        its identity on `ref`, and its analysis form is a project envelope
        carrying no revision. Offline adoption must recognise it instead of
        reporting the cached file as missing, and must recover the revision from
        the cached source form the way a download does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            analysis = release_dir / "codesystems" / "cs_resource.xml"
            analysis.parent.mkdir(parents=True)
            analysis.write_text('<codeSystems><project ident="hl7de-"><codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" displayName="Snomed-CT" language="de-DE"/></project></codeSystems>', encoding="utf-8")
            source = release_dir / "codesystems" / "cs_resource.source.xml"
            source.write_text('<codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" external="true" effectiveDate="2025-04-30T00:00:00" ident="hl7de-"><issueAssociation count="0"/></codeSystem>', encoding="utf-8")
            key = "codesystem:2.16.840.1.113883.6.96"
            manifest: dict[str, Any] = {"resources": {key: {
                "status": "ok",
                "file": "codesystems/cs_resource.xml",
                "project": "hl7de-",
                "requested_effective_date": "dynamic",
                "resolved_effective_date": "",
                "representations": {
                    "analysis": {
                        "status": "ok", "file": "codesystems/cs_resource.xml",
                    },
                    "source": {
                        "status": "ok",
                        "file": "codesystems/cs_resource.source.xml",
                    },
                },
            }}}
            want = {
                "kind": "codesystem", "id": "2.16.840.1.113883.6.96",
                "effective_date": "", "project": "hl7de-",
            }
            with patch("decor2hl7.retrieval.fetch.get") as mocked:
                _fetch_want(
                    release_dir, manifest, want, owners={},
                    repositories=["hl7de-"], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True,
                )
            self.assertEqual(mocked.call_count, 0)
            entry = manifest["resources"][key]
            self.assertEqual(entry["status"], "ok")
            self.assertEqual(
                entry["resolved_effective_date"], "2025-04-30T00:00:00"
            )
            self.assertEqual(
                entry["identity"]["effective_date"], "2025-04-30T00:00:00"
            )

    def test_reference_declaration_cannot_satisfy_another_revision(self) -> None:
        """`ref` proves identity, never a revision the payload does not carry."""
        envelope = '<codeSystems><project ident="hl7de-"><codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" displayName="Snomed-CT" language="de-DE"/></project></codeSystems>'.encode()
        dynamic = {
            "kind": "codesystem", "id": "2.16.840.1.113883.6.96",
            "effective_date": "",
        }
        self.assertTrue(_payload_matches_request(envelope, dynamic))
        self.assertFalse(_payload_matches_request(
            envelope, {**dynamic, "effective_date": "2025-04-30T00:00:00"}
        ))
        dated = '<codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" external="true" effectiveDate="2025-04-30T00:00:00" ident="hl7de-"><issueAssociation count="0"/></codeSystem>'.encode()
        self.assertTrue(_payload_matches_request(
            dated, {**dynamic, "effective_date": "2025-04-30T00:00:00"}
        ))
        self.assertFalse(_payload_matches_request(
            dated, {**dynamic, "effective_date": "2011-01-01T00:00:00"}
        ))
        self.assertFalse(_payload_matches_request(
            envelope, {**dynamic, "id": "2.16.840.1.113883.6.1"}
        ))
        self.assertEqual(
            _resolved_effective_date(dated, dynamic), "2025-04-30T00:00:00"
        )

    def test_fetch_want_redownloads_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "1.2.3_2025-05-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="1.2.3" effectiveDate="2025-05-01" name="Changed"/></return>',
                encoding="utf-8",
            )
            manifest: dict[str, Any] = {"resources": {
                "template:1.2.3@2025-05-01": {
                    "status": "ok",
                    "file": "templates/1.2.3_2025-05-01.xml",
                    "sha256": "not-the-current-digest",
                }
            }}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "2025-05-01", "project": "main-"}
            downloaded = b'<return><template id="1.2.3" effectiveDate="2025-05-01" name="Fresh"/></return>'
            with patch("decor2hl7.retrieval.fetch.get", return_value=downloaded) as mocked:
                path = _fetch_want(
                    release_dir, manifest, want, owners={}, repositories=["main-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                )
            self.assertEqual(path, target)
            self.assertEqual(target.read_bytes(), downloaded)
            self.assertGreaterEqual(mocked.call_count, 1)

    def test_dynamic_fetch_records_and_reuses_resolved_effective_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "template", "id": "1.2.3", "effective_date": "", "project": "main-"}
            calls: list[str] = []
            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                return b'<return><template id="1.2.3" effectiveDate="2025-05-01T00:00:00" name="T"><element name="hl7:observation"/></template></return>'
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(release_dir, manifest, want, owners={}, repositories=["main-"], language="de-DE", ipv4=True, retry_missing=False)
            entry = manifest["resources"]["template:1.2.3"]
            self.assertEqual(entry["requested_effective_date"], "dynamic")
            self.assertEqual(entry["resolved_effective_date"], "2025-05-01T00:00:00")
            assert path is not None
            path.unlink()
            calls.clear()
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                _fetch_want(release_dir, manifest, want, owners={}, repositories=["main-"], language="de-DE", ipv4=True, retry_missing=False)
            self.assertTrue(any("/2025-05-01T00%3A00%3A00/" in url for url in calls))

    def test_dynamic_request_is_not_satisfied_by_arbitrary_frozen_embed(self) -> None:
        inventory = {
            ("valueset", "1.2.3", "2015-01-01"),
            ("template", "4.5.6", ""),
        }
        self.assertFalse(_satisfied(
            {"kind": "valueset", "id": "1.2.3", "effective_date": ""},
            inventory,
        ))
        self.assertTrue(_satisfied(
            {
                "kind": "valueset", "id": "1.2.3",
                "effective_date": "2015-01-01",
            },
            inventory,
        ))
        self.assertTrue(_satisfied(
            {"kind": "template", "id": "4.5.6", "effective_date": ""},
            inventory,
        ))

    def test_artifact_identity_mismatch_is_fatal_but_missing_dependency_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            analysis = release / "templates" / "t.xml"
            analysis.parent.mkdir()
            analysis.write_text('<template id="t" effectiveDate="2007"/>', encoding="utf-8")
            entry = {
                "status": "ok", "file": "templates/t.xml",
                "requested_effective_date": "2005",
                "resolved_effective_date": "2007",
                "identity": {"type": "template", "id": "t", "effective_date": "2007"},
            }
            record = artifact_record(release, "template:t@2005", entry, ["structure"])
            self.assertTrue(any(
                "requested static revision" in item
                for item in artifact_problems(record)
            ))

            transaction = release / "transactions" / "tx"
            transaction.mkdir(parents=True)
            (release / "manifest.json").write_text(
                json.dumps({"resources": {"template:t@2005": entry}}),
                encoding="utf-8",
            )
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True,
                "build_ready": False,
                "readiness_errors": [
                    "required artifact unavailable: template:t@2005"
                ],
                "build_resources": ["template:t@2005"],
                "resource_roles": {"template:t@2005": ["structure"]},
            }), encoding="utf-8")
            records = closure_records(release, transaction)
            self.assertEqual(len(records), 1)
            self.assertTrue(any(
                "requested static revision" in item
                for item in artifact_problems(records[0])
            ))

            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True,
                "build_resources": [],
            }), encoding="utf-8")
            self.assertEqual(closure_records(release, transaction), [])

    def test_compiler_inputs_omit_and_report_missing_auxiliary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            transaction = release / "transactions" / "tx"
            transaction.mkdir(parents=True)
            source = transaction / "transaction.source.xml"
            analysis = transaction / "transaction.xml"
            template = release / "templates" / "doc.xml"
            template.parent.mkdir()
            source.write_text(
                '<transaction id="tx" effectiveDate="2026"><representingTemplate ref="doc"/></transaction>',
                encoding="utf-8",
            )
            analysis.write_text(
                '<dataset transactionId="tx" transactionEffectiveDate="2026" templateId="doc"/>',
                encoding="utf-8",
            )
            template.write_text(
                '<template id="doc" effectiveDate="2026"><element name="hl7:ClinicalDocument"/></template>',
                encoding="utf-8",
            )
            resources = {
                "transaction-source:tx@2026": {
                    "status": "ok",
                    "file": str(source.relative_to(release)),
                    "identity": {"type": "transaction", "id": "tx", "effective_date": "2026"},
                    "requested_effective_date": "2026",
                    "resolved_effective_date": "2026",
                },
                "transaction:tx@2026": {
                    "status": "ok",
                    "file": str(analysis.relative_to(release)),
                    "identity": {"type": "transaction", "id": "tx", "effective_date": "2026"},
                    "requested_effective_date": "2026",
                    "resolved_effective_date": "2026",
                },
                "template:doc@2026": {
                    "status": "ok",
                    "file": str(template.relative_to(release)),
                    "identity": {"type": "template", "id": "doc", "effective_date": "2026"},
                    "requested_effective_date": "2026",
                    "resolved_effective_date": "2026",
                },
                "dataset:missing@2020": {
                    "status": "missing",
                    "identity": {"type": "dataset", "id": "missing", "effective_date": "2020"},
                    "requested_effective_date": "2020",
                },
            }
            from decor2hl7.hashing import sha256_file
            for entry in resources.values():
                if entry.get("file"):
                    entry["sha256"] = sha256_file(release / str(entry["file"]))
            (release / "manifest.json").write_text(
                json.dumps({"resources": resources}), encoding="utf-8"
            )
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True,
                "build_ready": False,
                "build_resources": ["template:doc@2026", "dataset:missing@2020"],
                "evidence_resources": ["template:doc@2026", "dataset:missing@2020"],
                "resource_roles": {
                    "template:doc@2026": ["structure"],
                    "dataset:missing@2020": ["structure"],
                },
            }), encoding="utf-8")

            inputs = compiler_inputs(release, transaction)
            self.assertEqual(inputs["templates"], [template])
            self.assertIn(analysis, inputs["terminology_resources"])
            self.assertEqual(
                [item["request_key"] for item in inputs["unavailable_artifacts"]],
                ["dataset:missing@2020"],
            )
            self.assertNotIn(release / "datasets" / "missing.xml", inputs["model_resources"])

    def test_tolerant_cda_compile_reports_nested_gap_but_requires_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            document = directory / "doc.xml"
            document.write_text('''<template id="doc" effectiveDate="2026" name="Doc">
              <element name="hl7:ClinicalDocument"><include ref="missing" flexibility="2020"/></element>
            </template>''', encoding="utf-8")
            model = {"meta": {"template_id": "doc", "template_effective_date": "2026"}, "fields": {}, "groups": {}}
            compiled = compile_cda([document], model, strict=False)
            self.assertEqual(len(compiled["unresolved_templates"]), 1)
            self.assertEqual(compiled["unresolved_templates"][0]["template"], "missing")
            with self.assertRaisesRegex(ValueError, "document template absent .*not fetched"):
                compile_cda(
                    [],
                    {
                        "meta": {"template_id": "absent"},
                        "fields": {},
                        "groups": {},
                    },
                    strict=False,
                )

    def test_validator_value_sets_follow_the_selected_document_closure(self) -> None:
        """A rule skipped on a branch this document never uses is not degrading.

        The publication transform emits rules for every template the assembled
        specification reaches. Only a rule whose context template is actually
        instantiated in the selected document can affect this build
        (`DEC-010`, `DEC-019`).
        """
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            conformance = model_dir / "conformance-validation"
            conformance.mkdir()
            (conformance / "validator-manifest.json").write_text(
                '{"version": 2, "generation_messages": ["in", "out"], "generation_message_scopes": [{"message": "in", "severity": "error", "value_sets": ["selected-vs"], "context_templates": ["located-template"], "in_selected_closure": true}, {"message": "out", "severity": "error", "value_sets": ["inactive-vs"], "context_templates": ["unlocated-template"], "in_selected_closure": false}]}', encoding="utf-8"
            )
            inputs = {
                "terminology_resources": [],
                "build_artifacts": [],
                "unavailable_artifacts": [
                    {
                        "request_key": "valueset:selected-vs",
                        "type": "valueset", "id": "selected-vs",
                        "status": "missing", "roles": ["formal-terminology"],
                        "reasons": [],
                    },
                    {
                        "request_key": "valueset:inactive-vs",
                        "type": "valueset", "id": "inactive-vs",
                        "status": "missing", "roles": ["formal-terminology"],
                        "reasons": [],
                    },
                ],
            }
            result = write_build_diagnostics(
                model_dir, inputs, {"unresolved_templates": []}, {"fields": {}}
            )
            self.assertEqual(result["summary"]["crawl_degraded"], 2)
            self.assertEqual(
                [item["request_key"] for item in result["build_degraded"]],
                ["valueset:selected-vs"],
            )

    def test_selected_closure_templates_require_a_document_location(self) -> None:
        cda_model = {"targets": {
            "Located.value": {
                "template_id": "located",
                "template_effective_date": "2026-01-02T00:00:00",
                "locations": ["0.1"],
            },
            "Reachable.value": {
                "template_id": "unlocated",
                "template_effective_date": "2025-01-02T00:00:00",
                "locations": [],
            },
        }}
        self.assertEqual(selected_closure_templates(cda_model), {"located"})
        self.assertEqual(
            selected_closure_template_revisions(cda_model),
            {("located", "2026-01-02T00:00:00")},
        )

    def test_fetch_progress_does_not_claim_nonexistent_next_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "concept", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "pmp-"}
            progress: list[str] = []

            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", Message(), None)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=missing):
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "pmp-"}, repositories=["pmp-", "hl7de-"],
                    language="de-DE", ipv4=True, retry_missing=False, progress=progress.append,
                ))
            failure = next(line for line in progress if "HTTP 404" in line)
            self.assertEqual(failure, "fetch: concept 1.2.3.4 @ 2020-01-01: source HTTP 404 via pmp-")
            self.assertFalse(any("trying next source" in line for line in progress))

    def test_settled_missing_is_persisted_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, Any] = {"resources": {}}
            want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "main-"}
            persisted: list[dict[str, object]] = []
            def save() -> None:
                persisted.append(dict(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]))
            def missing(url: str, **_: object) -> bytes:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "missing", Message(), None)
            with patch("decor2hl7.retrieval.fetch.get", side_effect=missing) as mocked:
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "main-"}, repositories=["main-", "pmp-"],
                    language="de-DE", ipv4=True, retry_missing=False, save_manifest=save,
                ))
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue(persisted)
            self.assertTrue(manifest["resources"]["dataset:1.2.3.4@2020-01-01"]["settled"])
            with patch("decor2hl7.retrieval.fetch.get", side_effect=AssertionError("known missing must not retry")):
                self.assertIsNone(_fetch_want(
                    release_dir, manifest, want, owners={"1.2.3": "main-"}, repositories=["main-", "pmp-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                ))

    def test_incomplete_embedded_valueset_does_not_satisfy_fetch_inventory(self) -> None:
        root = ET.fromstring(
            '<dataset><valueSet id="1.2.3" effectiveDate="2020"><conceptList><include ref="4.5.6"/></conceptList></valueSet></dataset>'
        )
        self.assertNotIn(("valueset", "1.2.3", "2020"), _inventory(root))
        root = ET.fromstring(
            '<dataset><valueSet id="1.2.3" effectiveDate="2020"><concept code="A" codeSystem="9"/></valueSet></dataset>'
        )
        self.assertIn(("valueset", "1.2.3", "2020"), _inventory(root))


if __name__ == "__main__":
    unittest.main()
