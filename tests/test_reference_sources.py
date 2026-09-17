from __future__ import annotations

import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from decor2hl7.retrieval.api import REQUIRED_PATHS
from decor2hl7.retrieval.fetch import (
    _fetch_want, _materialize_external, fetch_spec,
)
from decor2hl7.retrieval.artifacts import (
    artifact_integrity_problems, closure_records,
)
from decor2hl7.retrieval.sources import load_source_hints


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()

class ReferenceSourceTests(unittest.TestCase):
    def test_bundled_catalog_settles_the_reviewed_phase_four_absences(self) -> None:
        """The two settled closure absences stay reviewed, cited and exact."""
        hints = load_source_hints()
        for key in (
            "codesystem:1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00",
            "template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00",
        ):
            with self.subTest(key=key):
                entry = hints[key]
                self.assertEqual(entry["mode"], "waiver")
                # A waiver never claims content, so it can never satisfy a
                # required dependency (`DEC-012`).
                self.assertNotEqual(entry.get("completeness"), "complete")
                self.assertTrue(entry["source_url"].startswith("https://"))
                self.assertTrue(entry["license"])
                self.assertIn("2026-09-03", entry["reason"])

    def test_reviewed_alias_fetches_corrected_identity_and_keeps_both_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, object] = {"resources": {}}
            published = "2.16.840.1.1133883.17.3.10.1.34"
            corrected = "2.16.840.1.113883.17.3.10.1.34"
            payload = (
                f'<template id="{corrected}" effectiveDate="2020" name="Corrected">'
                '<element name="hl7:observation"/></template>'
            ).encode()
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                return payload

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(
                    release_dir, manifest,
                    {"kind": "template", "id": published, "effective_date": ""},
                    owners={}, repositories=["main-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                    source_hints=load_source_hints(),
                )
            self.assertIsNotNone(path)
            self.assertTrue(all(published not in url for url in calls))
            resources = manifest["resources"]
            self.assertEqual(resources[f"template:{published}"]["status"], "alias")  # type: ignore[index]
            self.assertEqual(
                resources[f"template:{published}"]["alias_of"],  # type: ignore[index]
                f"template:{corrected}",
            )
            self.assertEqual(resources[f"template:{corrected}"]["status"], "ok")  # type: ignore[index]

            transaction = release_dir / "transactions" / "tx"
            transaction.mkdir(parents=True)
            (release_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True,
                "build_resources": [
                    f"template:{corrected}", f"template:{published}"
                ],
                "resource_roles": {
                    f"template:{corrected}": ["structure"],
                    f"template:{published}": ["structure"],
                },
            }), encoding="utf-8")
            record = closure_records(release_dir, transaction)[0]
            self.assertEqual(len(closure_records(release_dir, transaction)), 1)
            self.assertEqual(record["resolved"]["id"], corrected)
            self.assertEqual(
                {request["id"] for request in record["requests"]},
                {published, corrected},
            )
            self.assertTrue(record["resolution"]["identity_corrected"])
            self.assertEqual(artifact_integrity_problems(record), [])

    def test_reviewed_alias_does_not_hide_missing_corrected_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            published = "2.16.840.1.1133883.17.3.10.1.34"
            corrected = "2.16.840.1.113883.17.3.10.1.34"
            manifest: dict[str, Any] = {"resources": {
                f"template:{corrected}": {
                    "status": "missing", "settled": True,
                    "identity": {
                        "type": "template", "id": corrected,
                        "effective_date": "dynamic",
                    },
                }
            }}
            with patch("decor2hl7.retrieval.fetch.get") as mocked_get:
                result = _fetch_want(
                    release_dir, manifest,
                    {"kind": "template", "id": published, "effective_date": ""},
                    owners={}, repositories=["main-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                    source_hints=load_source_hints(),
                )
            self.assertIsNone(result)
            mocked_get.assert_not_called()
            resources = manifest["resources"]
            self.assertEqual(resources[f"template:{published}"]["status"], "alias")

            transaction = release_dir / "transactions" / "tx"
            transaction.mkdir(parents=True)
            (release_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True,
                "build_resources": [f"template:{published}"],
                "resource_roles": {f"template:{published}": ["structure"]},
            }), encoding="utf-8")
            self.assertEqual(
                closure_records(release_dir, transaction)[0]["status"], "missing"
            )

    def test_builtin_materializes_without_http_in_offline_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, object] = {"resources": {}}
            want = {
                "kind": "codesystem",
                "id": "1.2.276.0.76.5.401",
                "effective_date": "",
                "role": "expansion-support",
            }
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("builtin attempted HTTP"),
            ) as mocked:
                path = _fetch_want(
                    release_dir, manifest, want,
                    owners={}, repositories=[], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True,
                    source_hints=load_source_hints(),
                )
            self.assertEqual(mocked.call_count, 0)
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())
            entry = manifest["resources"]["codesystem:1.2.276.0.76.5.401"]  # type: ignore[index]
            self.assertEqual(entry["status"], "ok")
            self.assertEqual(entry["origin"], "bundled-supplement")
            self.assertEqual(entry["completeness"], "complete")

    def test_builtin_reconstructs_deleted_manifest_without_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            want = {
                "kind": "codesystem",
                "id": "1.2.276.0.76.5.401",
                "effective_date": "",
            }
            first: dict[str, object] = {"resources": {}}
            path = _fetch_want(
                release_dir, first, want,
                owners={}, repositories=[], language="de-DE", ipv4=True,
                retry_missing=False, offline=True,
                source_hints=load_source_hints(),
            )
            self.assertIsNotNone(path)

            reconstructed: dict[str, object] = {"resources": {}}
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("reconstruction attempted HTTP"),
            ) as mocked:
                reused = _fetch_want(
                    release_dir, reconstructed, want,
                    owners={}, repositories=[], language="de-DE", ipv4=True,
                    retry_missing=False, offline=False,
                    source_hints=load_source_hints(),
                )
            self.assertEqual(mocked.call_count, 0)
            self.assertEqual(reused, path)
            entry = reconstructed["resources"]["codesystem:1.2.276.0.76.5.401"]  # type: ignore[index]
            self.assertEqual(entry["origin"], "bundled-supplement")

    def test_waiver_is_offline_and_remains_visibly_non_successful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest: dict[str, object] = {"resources": {}}
            want = {
                "kind": "template",
                "id": "1.3.6.1.4.1.19376.1.5.3.1.4.9",
                "effective_date": "",
                "role": "structure",
            }
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("waiver attempted HTTP"),
            ) as mocked:
                path = _fetch_want(
                    Path(tmp), manifest, want,
                    owners={}, repositories=[], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True,
                    source_hints=load_source_hints(),
                )
            self.assertEqual(mocked.call_count, 0)
            self.assertIsNone(path)
            entry = manifest["resources"]["template:1.3.6.1.4.1.19376.1.5.3.1.4.9"]  # type: ignore[index]
            self.assertEqual(entry["status"], "waived")
            self.assertTrue(entry["settled"])
            self.assertIn("Provisional", entry["reason"])

    def test_fetch_rebuilds_deleted_manifest_from_spec_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = urlsplit(url).path
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b'<return><project id="9.9" prefix="ext-"/></return>'
                if "/transaction/t/" in path:
                    return b'<transaction id="t"><representingTemplate ref="doc" flexibility="2026-01-01"/></transaction>'
                if path.endswith("/project/main-/$extract"):
                    return b'<project><transaction id="t"/></project>'
                if path.endswith("/project/main-"):
                    return b'<project><name>Example project</name></project>'
                if "/template/doc/" in path:
                    return (
                        b'<return><template id="doc" effectiveDate="2026-01-01" name="Doc">'
                        b'<relationship type="SPEC" template="1.3.6.1.4.1.19376.1.5.3.1.4.9" flexibility="dynamic"/>'
                        b'<element name="hl7:ClinicalDocument" id="root"/></template></return>'
                    )
                raise AssertionError(url)

            release = {
                "key": "release-v1", "label": "release-v1",
                "date": "2024-01-02T03:04:05", "status": "final",
            }
            transaction = {
                "key": "tx", "id": "t", "effective_date": "2026-01-01",
                "name": "Test transaction",
            }
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                fetch_spec(
                    release_dir, tx_dir, prefix="main-", release=release,
                    transaction=transaction, max_requests=20,
                    source_hints=load_source_hints(),
                )
            first_call_count = len(calls)
            (release_dir / "manifest.json").unlink()

            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("existing spec file was downloaded again"),
            ) as mocked:
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-", release=release,
                    transaction=transaction, max_requests=20,
                    source_hints=load_source_hints(),
                )
            self.assertGreater(first_call_count, 0)
            self.assertEqual(mocked.call_count, 0)
            self.assertTrue(result["closure"]["crawl_complete"])
            self.assertFalse(result["closure"]["degraded"])
            self.assertIn(
                "template:1.3.6.1.4.1.19376.1.5.3.1.4.9",
                result["closure"]["waived"],
            )
            self.assertIn(
                "template-prototype",
                result["closure"]["resource_roles"][
                    "template:1.3.6.1.4.1.19376.1.5.3.1.4.9"
                ],
            )
            self.assertNotIn(
                "template:1.3.6.1.4.1.19376.1.5.3.1.4.9",
                result["closure"]["build_resources"],
            )
            self.assertTrue((release_dir / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
