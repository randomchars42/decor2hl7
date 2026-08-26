"""Transport emitted documents.  The default implementation is generic HTTP POST."""

from __future__ import annotations

import urllib.request
from pathlib import Path

from . import __version__
from typing import Any, Mapping


def send(path: Path, site: Mapping[str, Any]) -> tuple[bool, str]:
    config = site.get("transport", {})
    url = config.get("url")
    if not url:
        return False, "transport.url is not configured"
    payload = path.read_bytes()
    headers = {"Content-Type": "application/xml; charset=utf-8", "User-Agent": f"decor2hl7/{__version__}"}
    headers.update({str(key): str(value) for key, value in config.get("headers", {}).items()})
    request = urllib.request.Request(str(url), data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=int(config.get("timeout") or 60)) as response:
            status = getattr(response, "status", 200)
            return 200 <= status < 300, f"HTTP {status}"
    except OSError as error:
        return False, str(error)
