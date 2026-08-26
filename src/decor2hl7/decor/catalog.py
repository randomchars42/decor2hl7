"""ART-DECOR release and transaction discovery.

Discovery/selection is intentionally separate from specification fetching.
Users choose a release and transaction first; ``fetch`` only consumes that
resolved state.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .client import build_url, get
from .xml import child_text, local, parse_text
from ..workspace import release_key, transaction_key


def parse_releases(xml_text: str) -> list[dict[str, str]]:
    root, _ = parse_text(xml_text)
    rows: list[dict[str, str]] = []
    for node in root.iter():
        if local(node.tag) != "release":
            continue
        rows.append({
            "date": node.get("date") or "",
            "label": node.get("versionLabel") or "",
            "status": node.get("statusCode") or "",
        })
    rows.sort(key=lambda row: row["date"], reverse=True)
    counts = Counter(release_key(row["label"], row["date"]) for row in rows)
    for row in rows:
        base = release_key(row["label"], row["date"])
        row["key"] = base if counts[base] == 1 else f"{base}--{row['date'][:10]}"
    return rows


def parse_transactions(xml_text: str) -> list[dict[str, str]]:
    root, _ = parse_text(xml_text)
    found: dict[tuple[str, str], dict[str, str]] = {}
    for node in root.iter():
        if local(node.tag) != "transaction" or not node.get("id"):
            continue
        ident = node.get("id") or ""
        effective = node.get("effectiveDate") or ""
        name = child_text(node, "name")
        found[(ident, effective)] = {
            "id": ident,
            "effective_date": effective,
            "version_label": node.get("versionLabel") or "",
            "status": node.get("statusCode") or "",
            "name": name,
        }
    rows = sorted(found.values(), key=lambda row: (row["effective_date"], row["id"]), reverse=True)
    counts = Counter(transaction_key(row["name"], row["id"]) for row in rows)
    for row in rows:
        base = transaction_key(row["name"], row["id"])
        if counts[base] == 1:
            row["key"] = base
        else:
            date = row["effective_date"][:10].replace("-", "") or row["version_label"] or "version"
            row["key"] = f"{base}--{date}"
    return rows


def releases(prefix: str, *, ipv4: bool = True) -> list[dict[str, str]]:
    attempts = (
        build_url("ProjectIndex", prefix=prefix, format="xml"),
        build_url("RetrieveProject", prefix=prefix, mode="verbatim", format="xml"),
    )
    last_error: Exception | None = None
    for url in attempts:
        try:
            text = get(url, ipv4=ipv4).decode("utf-8", "replace")
        except OSError as error:
            last_error = error
            continue
        rows = parse_releases(text)
        if rows:
            return rows
    if last_error:
        raise last_error
    return []


def transactions(
    prefix: str,
    release_date: str,
    *,
    language: str = "de-DE",
    ipv4: bool = True,
) -> list[dict[str, str]]:
    # ProjectIndex view=t is the lightweight transaction catalog and accepts a
    # pinned project release.  Fall back to RetrieveProject only for deployments
    # whose index XML omits transaction details needed for a stable selection.
    attempts = (
        build_url(
            "ProjectIndex", prefix=prefix, version=release_date,
            language=language, view="t", format="xml",
        ),
        build_url(
            "RetrieveProject", prefix=prefix, version=release_date,
            language=language, mode="verbatim", format="xml",
        ),
    )
    last_error: Exception | None = None
    for url in attempts:
        try:
            text = get(url, ipv4=ipv4).decode("utf-8", "replace")
        except OSError as error:
            last_error = error
            continue
        rows = parse_transactions(text)
        if rows:
            return rows
    if last_error:
        raise last_error
    return []


def _match(rows: Iterable[dict[str, str]], identifier: str, fields: tuple[str, ...]) -> dict[str, str]:
    rows = list(rows)
    exact = [row for row in rows if any(identifier == row.get(field) for field in fields)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"identifier {identifier!r} is ambiguous")
    folded = identifier.casefold()
    loose = [
        row for row in rows
        if any(folded == str(row.get(field) or "").casefold() for field in fields)
    ]
    if len(loose) == 1:
        return loose[0]
    raise ValueError(f"unknown or ambiguous identifier {identifier!r}; use the KEY printed by the list command")


def select_release(rows: Iterable[dict[str, str]], identifier: str) -> dict[str, str]:
    return _match(rows, identifier, ("key", "label", "date"))


def select_transaction(rows: Iterable[dict[str, str]], identifier: str) -> dict[str, str]:
    return _match(rows, identifier, ("key", "id", "name"))
