"""Transport emitted documents through a bounded, site-selected adapter."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from . import __version__
from .workspace import load_json
from .i18n import Translator


SendResult = tuple[bool, str]
SendAdapter = Callable[[Path, Mapping[str, Any]], SendResult]
ConfigResult = tuple[dict[str, Any] | None, str]
ConfigValidator = Callable[[Mapping[str, Any], bool], ConfigResult]


def _http_post(path: Path, config: Mapping[str, Any]) -> SendResult:
    payload = path.read_bytes()
    headers = {
        "Content-Type": "application/xml; charset=utf-8",
        "User-Agent": f"decor2hl7/{__version__}",
    }
    headers.update({str(key): str(value) for key, value in config["headers"].items()})
    request = urllib.request.Request(
        str(config["url"]), data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=int(config["timeout"])) as response:
            status = getattr(response, "status", 200)
            return 200 <= status < 300, f"HTTP {status}"
    except OSError as error:
        return False, str(error)


def _http_post_config(config: Mapping[str, Any], require_destination: bool) -> ConfigResult:
    url = config.get("url")
    if require_destination and (not isinstance(url, str) or not url.strip()):
        return None, "transport.url is not configured"
    try:
        parsed = urlsplit(url if isinstance(url, str) else "")
        scheme = parsed.scheme
        hostname = parsed.hostname
    except ValueError:
        scheme = ""
        hostname = None
    if (require_destination or url not in (None, "")) and (scheme not in {"http", "https"} or not hostname):
        return None, "transport.url must be an absolute HTTP or HTTPS URL"

    timeout = config.get("timeout", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        return None, "transport.timeout must be a positive integer"

    headers = config.get("headers", {})
    if not isinstance(headers, Mapping):
        return None, "transport.headers must be an object"
    normalized_headers: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not key or "\r" in key or "\n" in key:
            return None, "transport header names must be non-empty single-line strings"
        if not isinstance(value, (str, int, float, bool)):
            return None, f"transport.headers.{key} must be a scalar value"
        text = str(value)
        if "\r" in text or "\n" in text:
            return None, f"transport.headers.{key} must be a single-line value"
        normalized_headers[key] = text

    return {
        "adapter": "http-post",
        "url": url,
        "timeout": timeout,
        "headers": normalized_headers,
    }, ""


def _spool_destination(path: Path, config: Mapping[str, Any]) -> Path:
    root = Path(str(config["directory"]))
    sidecar = path.with_suffix(".json")
    try:
        timestamp = load_json(sidecar)["prepared_at"]
        prepared = dt.datetime.fromisoformat(timestamp)
        if prepared.tzinfo is None:
            raise ValueError("missing timezone")
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError(Translator().text("ui.spool_invalid_prepared_at", path=sidecar)) from error
    return root / prepared.astimezone(dt.timezone.utc).strftime("%Y-%m") / path.stem


def _identical_publication(final: Path, files: list[Path]) -> bool:
    return final.is_dir() and all(
        (final / item.name).is_file()
        and (final / item.name).read_bytes() == item.read_bytes()
        for item in files
    ) and sorted(item.name for item in final.iterdir()) == sorted(item.name for item in files)


def _spool(path: Path, config: Mapping[str, Any]) -> SendResult:
    try:
        final = _spool_destination(path, config)
    except (ValueError, OSError) as error:
        return False, str(error)
    sidecar = path.with_suffix(".json")
    files = [path, *([sidecar] if sidecar.is_file() else [])]
    if final.exists():
        if _identical_publication(final, files):
            return True, f"already published at {final}"
        return False, f"spool destination already exists with different content: {final}"

    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.stem}-", dir=final.parent))
    try:
        for item in files:
            destination = temporary / item.name
            with destination.open("wb") as handle:
                handle.write(item.read_bytes()); handle.flush(); os.fsync(handle.fileno())
        temporary.rename(final)
        return True, f"published at {final}"
    except OSError as error:
        shutil.rmtree(temporary, ignore_errors=True)
        return False, str(error)


def _spool_config(config: Mapping[str, Any], require_destination: bool) -> ConfigResult:
    directory = config.get("directory")
    if (require_destination or directory not in (None, "")) and (not isinstance(directory, str) or not directory.strip()):
        return None, "transport.directory is not configured"
    return {"adapter": "spool", "directory": directory}, ""


_ADAPTERS: dict[
    str, tuple[frozenset[str], ConfigValidator, SendAdapter]
] = {
    "http-post": (
        frozenset({"adapter", "url", "timeout", "headers"}),
        _http_post_config,
        _http_post,
    ),
    "spool": (
        frozenset({"adapter", "directory"}),
        _spool_config,
        _spool,
    ),
}


def adapter_names() -> tuple[str, ...]:
    """Return the closed set of configured adapter names."""
    return tuple(sorted(_ADAPTERS))


def _configured_adapter(
    site: Mapping[str, Any], *, require_destination: bool = True,
) -> tuple[SendAdapter | None, Mapping[str, Any] | None, str]:
    value = site.get("transport", {})
    if not isinstance(value, Mapping):
        return None, None, "transport must be an object"
    name = value.get("adapter", "http-post")
    if not isinstance(name, str) or name not in _ADAPTERS:
        available = ", ".join(adapter_names())
        return None, None, f"unknown transport.adapter {name!r}; available: {available}"

    allowed, validate, adapter = _ADAPTERS[name]
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        return (
            None,
            None,
            f"unsupported transport option(s) for {name}: {', '.join(unknown)}",
        )
    config, error = validate(value, require_destination)
    return (adapter, config, "") if config is not None else (None, None, error)


def configured_name(site: Mapping[str, Any]) -> str:
    value = site.get("transport", {})
    return str(value.get("adapter") or "http-post") if isinstance(value, Mapping) else ""


def configuration_error(site: Mapping[str, Any], *, require_destination: bool = True) -> str:
    """Validate the selected closed adapter contract without performing I/O."""
    adapter, config, error = _configured_adapter(site, require_destination=require_destination)
    return error if adapter is None or config is None else ""


def send(
    path: Path, site: Mapping[str, Any], *, workspace: Path | None = None,
) -> SendResult:
    """Send one document through the configured, built-in adapter."""
    adapter, config, error = _configured_adapter(site)
    if adapter is None or config is None:
        return False, error
    if configured_name(site) == "spool" and workspace is not None:
        configured = Path(str(config["directory"])).expanduser()
        if not configured.is_absolute():
            configured = workspace / configured
        config = {**config, "directory": str(configured.resolve())}
    return adapter(path, config)


def is_published(path: Path, site: Mapping[str, Any], *, workspace: Path) -> bool:
    """Inspect an existing local handover without publishing anything new."""
    if configured_name(site) != "spool":
        return False
    _, config, error = _configured_adapter(site)
    if config is None:
        raise ValueError(error)
    directory = Path(str(config["directory"])).expanduser()
    if not directory.is_absolute():
        directory = workspace / directory
    config = {**config, "directory": str(directory.resolve())}
    final = _spool_destination(path, config)
    sidecar = path.with_suffix(".json")
    return _identical_publication(final, [path, *([sidecar] if sidecar.is_file() else [])])
