"""Small HTTP client used while acquiring specification artifacts.

ART-DECOR is intentionally accessed through IPv4 by default.  The IPv6 route
used during development was dramatically slower.  The override is scoped to
this client; global socket resolution is never monkey-patched.
"""

from __future__ import annotations

import http.client
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import __version__
from typing import Any

DEFAULT_API_BASE = "https://art-decor.org/exist/apps/api"
RETRY_STATUS = {429, 500, 502, 503, 504}
FINAL_STATUS = {400, 401, 403, 404, 405, 410}


def build_url(
    path: str,
    *,
    base_url: str = DEFAULT_API_BASE,
    **params: str | bool | int | None,
) -> str:
    """Build a URL below a current API base.

    Path segments containing artifact identifiers or effective dates are
    quoted by :mod:`decor2hl7.retrieval.api`; this function deliberately only
    owns base/path joining and query encoding.
    """
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    return f"{url}?{query}" if query else url


def _connect_ipv4(
    address: tuple[str, int],
    timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,  # type: ignore[attr-defined]
    source_address: tuple[str, int] | None = None,
) -> socket.socket:
    host, port = address
    last: OSError | None = None
    for family, kind, proto, _, sockaddr in socket.getaddrinfo(
        host, port, socket.AF_INET, socket.SOCK_STREAM
    ):
        handle: socket.socket | None = None
        try:
            handle = socket.socket(family, kind, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
                handle.settimeout(timeout)
            if source_address:
                handle.bind(source_address)
            handle.connect(sockaddr)
            return handle
        except OSError as error:
            last = error
            if handle is not None:
                handle.close()
    raise last or OSError(f"could not connect to {host}:{port} over IPv4")


class _IPv4HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_ipv4


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_ipv4


class _IPv4HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_IPv4HTTPConnection, req)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


def opener(ipv4: bool = True) -> urllib.request.OpenerDirector:
    if not ipv4:
        return urllib.request.build_opener()
    return urllib.request.build_opener(_IPv4HTTPHandler(), _IPv4HTTPSHandler())


def get(
    url: str,
    *,
    timeout: int = 300,
    retries: int = 3,
    delay: float = 0.5,
    ipv4: bool = True,
    accept: str = "application/xml",
) -> bytes:
    agent = f"decor2hl7/{__version__}"
    contact = os.environ.get("DECOR2HL7_CONTACT")
    if contact:
        agent += f" contact:{contact}"
    request = urllib.request.Request(
        url, headers={"User-Agent": agent, "Accept": accept}
    )
    transport = opener(ipv4)
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        if delay:
            time.sleep(delay * (2**attempt if attempt else 1))
        try:
            with transport.open(request, timeout=timeout) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            last = error
            if error.code in FINAL_STATUS:
                raise
            if error.code not in RETRY_STATUS or attempt + 1 >= retries:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
            if attempt + 1 >= retries:
                raise
    raise OSError(str(last) if last else "request failed")
