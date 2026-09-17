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

    def test_waiver_retains_the_recorded_resolution_trace(self) -> None:
        """Settling an absence must not erase the attempts that proved it."""
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            key = "codesystem:1.2.3@2019-12-30T00:00:00"
            manifest: dict[str, Any] = {"resources": {key: {
                "status": "missing",
                "settled": True,
                "projects_considered": ["main-", "hl7de-"],
                "resolution_attempts": [
                    {"project": "main-", "form": "source", "http_status": 404},
                    {"project": "hl7de-", "form": "source", "http_status": 404},
                ],
            }}}
            want = {
                "kind": "codesystem", "id": "1.2.3",
                "effective_date": "2019-12-30T00:00:00",
                "mode": "waiver", "reason": "Reviewed settled absence",
                "source_url": "https://example.invalid/publication",
                "source_version": "Publication 1.0",
                "license": "Public publication",
            }
            handled, path = _materialize_external(
                release_dir, manifest, want, key=key,
                relative="codesystems/1.2.3.xml",
            )
            self.assertTrue(handled)
            self.assertIsNone(path)
            entry = manifest["resources"][key]
            self.assertEqual(entry["status"], "waived")
            self.assertEqual(entry["projects_considered"], ["main-", "hl7de-"])
            self.assertEqual(len(entry["resolution_attempts"]), 2)
            self.assertEqual(entry["reason"], "Reviewed settled absence")

    def test_external_catalog_entries_require_reviewable_provenance(self) -> None:
        """A builtin or waiver is only auditable with its source and terms.

        `DEC-012` accepts an external supplement or a settled absence only when
        the entry itself records where the claim comes from, which revision it
        describes and under which terms it may be carried.
        """
        complete = {
            "mode": "waiver",
            "source_url": "https://example.invalid/publication",
            "source_version": "Publication 1.0, 2026-01-01",
            "license": "Public publication; carried as evidence only",
            "reason": "Reviewed settled absence",
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sources.json"
            source.write_text(
                json.dumps({"artifacts": {"template:absent": complete}}),
                encoding="utf-8",
            )
            self.assertIn("template:absent", load_source_hints(source))
            for missing in ("source_url", "source_version", "license", "reason"):
                entry = {
                    name: value for name, value in complete.items()
                    if name != missing
                }
                source.write_text(
                    json.dumps({"artifacts": {"template:absent": entry}}),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "requires"):
                    load_source_hints(source)
            source.write_text(
                json.dumps({"artifacts": {"template:absent": {
                    **complete, "completeness": "mostly",
                }}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported completeness"):
                load_source_hints(source)

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
                    raise HTTPError(url, 404, "missing", Message(), None)
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
