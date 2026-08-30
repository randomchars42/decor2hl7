from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from decor2hl7.retrieval.api import REQUIRED_PATHS
from decor2hl7.retrieval.fetch import _fetch_want, fetch_spec
from decor2hl7.retrieval.sources import load_source_hints


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()


class ExternalSourceTests(unittest.TestCase):
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
