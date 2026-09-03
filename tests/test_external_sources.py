from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from decor2hl7.retrieval.api import REQUIRED_PATHS
from decor2hl7.retrieval.fetch import _fetch_want, fetch_spec
from decor2hl7.retrieval.artifacts import (
    artifact_integrity_problems, closure_records,
)
from decor2hl7.retrieval.sources import load_source_hints


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()


class ExternalSourceTests(unittest.TestCase):
    def test_configured_alias_and_oid_owners_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sources.json"
            source.write_text(json.dumps({
                "oid_owners": {"1.2.3": "owner-"},
                "artifacts": {"template:bad": {
                    "mode": "alias", "alias_of": "template:good",
                    "reason": "Reviewed correction",
                }},
            }), encoding="utf-8")
            hints = load_source_hints(source)
            self.assertEqual(hints.oid_owners["1.2.3"], "owner-")
            self.assertIn("template:bad", hints.configured_artifacts)
            source.write_text(json.dumps({"artifacts": {"template:bad": {
                "mode": "alias", "alias_of": "template:good",
                "reason": "Reviewed correction", "sha256": "forbidden",
            }}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot contain"):
                load_source_hints(source)
            for invalid in (
                {"mode": "alias", "alias_of": "template:good"},
                {"mode": "alias", "reason": "Reviewed correction"},
                {
                    "mode": "alias", "alias_of": "valueset:good",
                    "reason": "Wrong artifact kind",
                },
            ):
                source.write_text(json.dumps({
                    "artifacts": {"template:bad": invalid}
                }), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "requires|'alias_of'|same artifact kind"
                ):
                    load_source_hints(source)

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
                    owners={}, repositories=["aktin-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                    source_hints=load_source_hints(),
                )
            self.assertIsNotNone(path)
            self.assertTrue(all(published not in url for url in calls))
            resources = manifest["resources"]  # type: ignore[assignment]
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
            manifest: dict[str, object] = {"resources": {
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
                    owners={}, repositories=["aktin-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                    source_hints=load_source_hints(),
                )
            self.assertIsNone(result)
            mocked_get.assert_not_called()
            resources = manifest["resources"]  # type: ignore[assignment]
            self.assertEqual(resources[f"template:{published}"]["status"], "alias")  # type: ignore[index]

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

    def test_dynamic_incomplete_valueset_fetches_frozen_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, object] = {"resources": {}}
            definition = (
                b'<valueSet id="1.2.3" effectiveDate="2025-01-02">'
                b'<conceptList><include codeSystem="9.8.7"/></conceptList></valueSet>'
            )
            expansion = (
                b'<valueSetExpansionSet current="1" count="1">'
                b'<valueSet id="1.2.3" effectiveDate="2025-01-02">'
                b'<conceptList><include codeSystem="9.8.7"/></conceptList>'
                b'</valueSet><expansion><items is="concept" code="A" '
                b'codeSystem="9.8.7"/></expansion></valueSetExpansionSet>'
            )
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                return expansion if "/$expand" in url else definition

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                _fetch_want(
                    release_dir, manifest,
                    {"kind": "valueset", "id": "1.2.3", "effective_date": ""},
                    owners={}, repositories=["term-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                )
            self.assertTrue(any(
                "/valueset/1.2.3/2025-01-02/$expand" in url for url in calls
            ))
            entry = manifest["resources"]["valueset:1.2.3"]  # type: ignore[index]
            self.assertIn("expansion", entry["representations"])
            self.assertEqual(entry["resolved_effective_date"], "2025-01-02")

    def test_partial_frozen_expansion_is_degradation_not_compiler_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, object] = {"resources": {}}
            definition = (
                b'<valueSet id="1.2.3" effectiveDate="2025-01-02">'
                b'<conceptList><include codeSystem="9.8.7"/></conceptList></valueSet>'
            )
            expansion = (
                b'<valueSetExpansionSet current="1" count="2">'
                b'<valueSet id="1.2.3" effectiveDate="2025-01-02"/>'
                b'<expansion><items is="concept" code="A" '
                b'codeSystem="9.8.7"/></expansion></valueSetExpansionSet>'
            )

            def fake_get(url: str, **_: object) -> bytes:
                return expansion if "/$expand" in url else definition

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                _fetch_want(
                    release_dir, manifest,
                    {"kind": "valueset", "id": "1.2.3", "effective_date": ""},
                    owners={}, repositories=["term-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                )
            entry = manifest["resources"]["valueset:1.2.3"]  # type: ignore[index]
            self.assertNotIn("expansion", entry["representations"])
            self.assertIn("expansion-evidence", entry["representations"])
            self.assertEqual(
                entry["expansion_warning"],
                "partial value-set expansion: returned 1 of 2 members",
            )

            # A settled partial response is frozen evidence. Ordinary fetches
            # reuse it without repeatedly calling the server; the explicit
            # retry mode remains the mechanism for refreshing it.
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("settled expansion retried"),
            ) as mocked_get:
                reused = _fetch_want(
                    release_dir, manifest,
                    {"kind": "valueset", "id": "1.2.3", "effective_date": ""},
                    owners={}, repositories=["term-"], language="de-DE",
                    ipv4=True, retry_missing=False,
                )
            mocked_get.assert_not_called()
            self.assertIsNotNone(reused)

    def test_resolution_trace_records_failed_and_successful_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest: dict[str, object] = {"resources": {}}
            payload = (
                b'<template id="1.2.3" effectiveDate="2020" name="Found">'
                b'<element name="hl7:act"/></template>'
            )

            def fake_get(url: str, **_: object) -> bytes:
                if "project=first-" in url:
                    raise HTTPError(url, 404, "missing", {}, None)
                return payload

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                _fetch_want(
                    Path(tmp), manifest,
                    {"kind": "template", "id": "1.2.3", "effective_date": ""},
                    owners={}, repositories=["first-", "second-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                )
            entry = manifest["resources"]["template:1.2.3"]  # type: ignore[index]
            self.assertEqual(entry["projects_considered"], ["first-", "second-"])
            self.assertTrue(any(
                attempt.get("project") == "first-"
                and attempt.get("http_status") == 404
                for attempt in entry["resolution_attempts"]
            ))

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
            release_dir = Path(tmp) / "spec" / "2026.1.2"
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
                if path.endswith("/project/aktin-/$extract"):
                    return b'<project><transaction id="t"/></project>'
                if path.endswith("/project/aktin-"):
                    return b'<project><name>AKTIN</name></project>'
                if "/template/doc/" in path:
                    return (
                        b'<return><template id="doc" effectiveDate="2026-01-01" name="Doc">'
                        b'<relationship type="SPEC" template="1.3.6.1.4.1.19376.1.5.3.1.4.9" flexibility="dynamic"/>'
                        b'<element name="hl7:ClinicalDocument" id="root"/></template></return>'
                    )
                raise AssertionError(url)

            release = {
                "key": "2026.1.2", "label": "2026.1.2",
                "date": "2026-04-27T18:50:33", "status": "final",
            }
            transaction = {
                "key": "tx", "id": "t", "effective_date": "2026-01-01",
                "name": "Test transaction",
            }
            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                fetch_spec(
                    release_dir, tx_dir, prefix="aktin-", release=release,
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
                    release_dir, tx_dir, prefix="aktin-", release=release,
                    transaction=transaction, max_requests=20,
                    source_hints=load_source_hints(),
                )
            self.assertGreater(first_call_count, 0)
            self.assertEqual(mocked.call_count, 0)
            self.assertTrue(result["closure"]["crawl_complete"])
            self.assertTrue(result["closure"]["degraded"])
            self.assertIn(
                "template:1.3.6.1.4.1.19376.1.5.3.1.4.9",
                result["closure"]["waived"],
            )
            self.assertTrue((release_dir / "manifest.json").is_file())

    def test_manifest_reconstruction_rejects_wrong_artifact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            target = release_dir / "templates" / "wanted_2026-01-01.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                '<return><template id="other" effectiveDate="2026-01-01" '
                'name="Wrong"/></return>',
                encoding="utf-8",
            )
            manifest: dict[str, object] = {"resources": {}}
            want = {
                "kind": "template",
                "id": "wanted",
                "effective_date": "2026-01-01",
            }
            with patch(
                "decor2hl7.retrieval.fetch.get",
                side_effect=AssertionError("mismatched orphan should need HTTP"),
            ) as mocked:
                path = _fetch_want(
                    release_dir, manifest, want,
                    owners={}, repositories=[], language="de-DE", ipv4=True,
                    retry_missing=False, offline=True, source_hints={},
                )
            self.assertEqual(mocked.call_count, 0)
            self.assertIsNone(path)
            entry = manifest["resources"]["template:wanted@2026-01-01"]  # type: ignore[index]
            self.assertEqual(entry["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
