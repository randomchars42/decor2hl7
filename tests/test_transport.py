from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from decor2hl7 import transport


class _Response:
    status = 202

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class TransportTests(unittest.TestCase):
    def test_http_post_adapter_sends_one_xml_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / "document.xml"
            document.write_bytes(b"<ClinicalDocument/>")
            site = {"transport": {
                "adapter": "http-post",
                "url": "https://receiver.example/cda",
                "timeout": 17,
                "headers": {"Authorization": "Bearer test"},
            }}

            with patch(
                "decor2hl7.transport.urllib.request.urlopen",
                return_value=_Response(),
            ) as urlopen:
                result = transport.send(document, site)

            self.assertEqual(result, (True, "HTTP 202"))
            request = urlopen.call_args.args[0]
            self.assertEqual(request.full_url, "https://receiver.example/cda")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.data, b"<ClinicalDocument/>")
            self.assertEqual(request.get_header("Authorization"), "Bearer test")
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 17)

    def test_legacy_configuration_defaults_to_http_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / "document.xml"
            document.write_bytes(b"<ClinicalDocument/>")
            site = {"transport": {
                "url": "http://receiver.example/cda", "timeout": 60, "headers": {},
            }}
            with patch(
                "decor2hl7.transport.urllib.request.urlopen",
                return_value=_Response(),
            ):
                self.assertEqual(transport.send(document, site), (True, "HTTP 202"))

    def test_unknown_adapter_is_rejected_before_io(self) -> None:
        missing = Path("does-not-exist.xml")
        with patch("decor2hl7.transport.urllib.request.urlopen") as urlopen:
            ok, message = transport.send(
                missing, {"transport": {"adapter": "receiver-v1"}}
            )
        self.assertFalse(ok)
        self.assertIn("unknown transport.adapter 'receiver-v1'", message)
        urlopen.assert_not_called()

    def test_adapter_rejects_options_outside_its_contract(self) -> None:
        missing = Path("does-not-exist.xml")
        with patch("decor2hl7.transport.urllib.request.urlopen") as urlopen:
            ok, message = transport.send(missing, {"transport": {
                "adapter": "http-post",
                "url": "https://receiver.example/cda",
                "batch_size": 10,
            }})
        self.assertFalse(ok)
        self.assertEqual(
            message, "unsupported transport option(s) for http-post: batch_size"
        )
        urlopen.assert_not_called()

    def test_http_post_configuration_is_validated_before_io(self) -> None:
        cases = [
            ({"url": "file:///tmp/out"}, "absolute HTTP or HTTPS URL"),
            ({"url": "https://[invalid"}, "absolute HTTP or HTTPS URL"),
            ({"url": "https://receiver.example", "timeout": 0}, "positive integer"),
            ({"url": "https://receiver.example", "headers": []}, "must be an object"),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                with patch("decor2hl7.transport.urllib.request.urlopen") as urlopen:
                    ok, message = transport.send(
                        Path("does-not-exist.xml"), {"transport": config}
                    )
                self.assertFalse(ok)
                self.assertIn(expected, message)
                urlopen.assert_not_called()
