from __future__ import annotations

import os
import socket
import unittest
import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from unittest.mock import patch

from decor2hl7.retrieval import client


class _Response:
    def __init__(self, payload: bytes = b"payload", status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Transport:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[int] = []

    def open(self, request: urllib.request.Request, *, timeout: int) -> _Response:
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if not isinstance(outcome, _Response):
            raise AssertionError(f"unexpected test outcome {outcome!r}")
        return outcome


class _Socket:
    def __init__(self, *, connect_error: OSError | None = None) -> None:
        self.connect_error = connect_error
        self.events: list[tuple[str, object]] = []
        self.closed = False

    def settimeout(self, timeout: object) -> None:
        self.events.append(("timeout", timeout))

    def bind(self, address: tuple[str, int]) -> None:
        self.events.append(("bind", address))

    def connect(self, address: tuple[str, int]) -> None:
        self.events.append(("connect", address))
        if self.connect_error is not None:
            raise self.connect_error

    def close(self) -> None:
        self.closed = True


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid", code, "test response", Message(), None
    )


class RetrievalClientTests(unittest.TestCase):
    def test_build_url_normalizes_slashes_and_omits_empty_parameters(self) -> None:
        url = client.build_url(
            "/artifact",
            base_url="https://example.invalid/api/",
            project="main-",
            empty="",
            disabled=False,
            count=2,
        )
        self.assertEqual(
            url,
            "https://example.invalid/api/artifact?project=main-&count=2",
        )

    def test_get_returns_bytes_and_sets_bounded_request_headers(self) -> None:
        transport = _Transport([_Response(b"result")])
        with patch.object(client, "opener", return_value=transport), patch.dict(
            os.environ, {"DECOR2HL7_CONTACT": "ops@example.invalid"}
        ):
            result = client.get(
                "https://example.invalid/api", timeout=17, retries=1,
                delay=0, ipv4=False, accept="application/json",
            )

        self.assertEqual(result, b"result")
        self.assertEqual(transport.timeouts, [17])
        headers = dict(transport.requests[0].header_items())
        self.assertEqual(headers["Accept"], "application/json")
        self.assertIn("decor2hl7/", headers["User-agent"])
        self.assertIn("contact:ops@example.invalid", headers["User-agent"])

    def test_get_retries_transient_http_status_but_not_final_status(self) -> None:
        transient = _Transport([_http_error(503), _Response(b"recovered")])
        with patch.object(client, "opener", return_value=transient):
            self.assertEqual(
                client.get(
                    "https://example.invalid/api", retries=2, delay=0
                ),
                b"recovered",
            )
        self.assertEqual(len(transient.requests), 2)

        final = _Transport([_http_error(404), _Response(b"must not be used")])
        with patch.object(client, "opener", return_value=final):
            with self.assertRaises(urllib.error.HTTPError):
                client.get(
                    "https://example.invalid/api", retries=3, delay=0
                )
        self.assertEqual(len(final.requests), 1)

    def test_get_retries_network_errors_and_raises_the_last_one(self) -> None:
        transport = _Transport([
            urllib.error.URLError("first"),
            urllib.error.URLError("second"),
        ])
        with patch.object(client, "opener", return_value=transport):
            with self.assertRaisesRegex(urllib.error.URLError, "second"):
                client.get(
                    "https://example.invalid/api", retries=2, delay=0
                )
        self.assertEqual(len(transport.requests), 2)

    def test_opener_scopes_ipv4_handlers_to_the_requested_client(self) -> None:
        sentinel = urllib.request.OpenerDirector()
        with patch(
            "decor2hl7.retrieval.client.urllib.request.build_opener",
            return_value=sentinel,
        ) as build_opener:
            self.assertIs(client.opener(ipv4=False), sentinel)
            build_opener.assert_called_once_with()
            build_opener.reset_mock()

            self.assertIs(client.opener(ipv4=True), sentinel)
            handlers: tuple[Any, ...] = build_opener.call_args.args
            self.assertEqual(len(handlers), 2)
            self.assertEqual(
                {type(handler).__name__ for handler in handlers},
                {"_IPv4HTTPHandler", "_IPv4HTTPSHandler"},
            )

    def test_ipv4_connection_closes_failed_sockets_and_returns_the_first_success(self) -> None:
        first = _Socket(connect_error=OSError("first address failed"))
        second = _Socket()
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.2", 443)),
        ]
        with patch(
            "decor2hl7.retrieval.client.socket.getaddrinfo",
            return_value=addresses,
        ), patch(
            "decor2hl7.retrieval.client.socket.socket",
            side_effect=[first, second],
        ):
            connected = client._connect_ipv4(
                ("example.invalid", 443), timeout=5,
                source_address=("192.0.2.10", 0),
            )

        self.assertIs(connected, second)
        self.assertTrue(first.closed)
        self.assertFalse(second.closed)
        self.assertEqual(second.events, [
            ("timeout", 5),
            ("bind", ("192.0.2.10", 0)),
            ("connect", ("192.0.2.2", 443)),
        ])


if __name__ == "__main__":
    unittest.main()
