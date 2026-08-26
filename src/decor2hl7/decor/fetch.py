"""Fetch a recursively closed ART-DECOR specification.

The release is the cache scope; a transaction owns only ``transaction.xml``
and ``closure.json``. Shared datasets/templates/value sets/concepts are stored
once below ``spec/<release>/`` and may be reused by other transactions in the
same release.

The pinned project + transaction define build truth. An unpinned project
snapshot is fetched once as *evidence only*: it may provide historical
associations/lineage for mapping analysis but never changes model/template
selection.
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, TypedDict

from .client import FINAL_STATUS, build_url, get
from .xml import local, parse_text
from ..workspace import load_json, write_json


class Want(TypedDict, total=False):
    kind: str
    id: str
    effective_date: str
    prefix: str
    dataset: str


SERVICES: dict[str, tuple[str, str, str]] = {
    "dataset": ("RetrieveDataSet", "id", "effectiveDate"),
    "concept": ("RetrieveConcept", "conceptId", "conceptEffectiveDate"),
    "template": ("RetrieveTemplate", "id", "effectiveDate"),
    "valueset": ("RetrieveValueSet", "id", "effectiveDate"),
}
KIND_ORDER = {"dataset": 0, "template": 1, "valueset": 2, "concept": 3}


class RequestBudgetExceeded(RuntimeError):
    """Recursive fetch stopped before another HTTP attempt could be made."""


Progress = Callable[[str], None]


def _emit(progress: Progress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _resource_label(want: Mapping[str, str]) -> str:
    effective = want.get("effective_date") or "dynamic"
    return f"{want.get('kind', 'resource')} {want.get('id', '?')} @ {effective}"


def _size_text(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "resource"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _key(want: Mapping[str, str]) -> str:
    effective = want.get("effective_date") or ""
    suffix = f"@{effective}" if effective else ""
    return f"{want['kind']}:{want['id']}{suffix}"


def _filename(want: Mapping[str, str]) -> str:
    stamp = _safe(want.get("effective_date") or "")
    name = _safe(want["id"])
    if stamp:
        name += f"_{stamp}"
    directory = {
        "dataset": "datasets",
        "template": "templates",
        "valueset": "valuesets",
        "concept": "concepts",
    }[want["kind"]]
    return f"{directory}/{name}.xml"


def classify_payload(payload: bytes) -> tuple[str, str]:
    """Return ``ok``, ``empty`` or ``unparseable`` for a service response."""
    if not payload.strip():
        return "empty", "zero bytes"
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError) as error:
        return "unparseable", str(error)
    if len(list(root)) == 0 and not (root.text or "").strip():
        return "empty", f"<{local(root.tag)}/> with no content"
    return "ok", ""


def _parse(path: Path) -> ET.Element | None:
    try:
        return parse_text(path.read_text(encoding="utf-8", errors="replace"))[0]
    except (ET.ParseError, OSError):
        return None


def references(root: ET.Element) -> list[Want]:
    """Extract typed references from one ART-DECOR XML tree."""
    found: dict[tuple[str, str, str, str], Want] = {}

    def add(kind: str, ident: str | None, effective: str | None = None,
            prefix: str | None = None, dataset: str | None = None) -> None:
        if not ident or kind not in SERVICES:
            return
        want: Want = {
            "kind": kind,
            "id": ident,
            "effective_date": "" if effective in (None, "dynamic") else str(effective),
            "prefix": prefix or "",
        }
        if dataset:
            want["dataset"] = dataset
        found[(kind, ident, want["effective_date"], want["prefix"])] = want

    stack: list[tuple[ET.Element, tuple[str, ...]]] = [(root, ())]
    while stack:
        node, ancestors = stack.pop()
        tag = local(node.tag)
        for child in node:
            stack.append((child, ancestors + (tag,)))

        if tag == "include" and node.get("ref"):
            in_valueset = any(item in {"valueSet", "conceptList", "questionnaire"} for item in ancestors[-4:])
            add("valueset" if in_valueset else "template", node.get("ref"), node.get("flexibility"))
            continue
        if tag == "answerValueSet":
            add("valueset", node.get("ref"), node.get("flexibility"))
            continue
        if tag in {"inherit", "relationship", "contains"}:
            dataset = node.get("datasetId")
            add("dataset", dataset, node.get("datasetEffectiveDate"), node.get("prefix"))
            # Prefer the dataset when it is known; the concept remains useful as
            # evidence but does not need its own HTTP call.
            if not dataset:
                add("concept", node.get("ref"), node.get("effectiveDate") or node.get("flexibility"), node.get("prefix"))
            add("template", node.get("template"), node.get("flexibility"), node.get("prefix"))
        elif tag == "element":
            add("template", node.get("contains"), node.get("flexibility"))
        elif tag == "representingTemplate":
            add("template", node.get("ref"), node.get("flexibility"))
            add("dataset", node.get("sourceDataset"), node.get("sourceDatasetFlexibility"))
        elif tag == "valueSet":
            if node.get("ref"):
                add("valueset", node.get("ref"), node.get("flexibility"))
            elif node.get("id"):
                add("valueset", node.get("id"), node.get("effectiveDate"))
        elif tag == "vocabulary":
            add("valueset", node.get("valueSet"), node.get("flexibility"))
        elif tag == "templateAssociation":
            add("template", node.get("templateId"), node.get("effectiveDate"))
        if node.get("templateId") and tag in {"dataset", "transaction"}:
            add("template", node.get("templateId"), node.get("templateEffectiveDate"))
    return list(found.values())




def _valueset_complete(node: ET.Element) -> bool:
    for child in node.iter():
        if local(child.tag) in {"concept", "exception"} and child.get("code") and child.get("codeSystem"):
            return True
    return False


def _inventory(root: ET.Element | None) -> set[tuple[str, str, str]]:
    """Resources already embedded in an XML document (kind, id, effectiveDate)."""
    result: set[tuple[str, str, str]] = set()
    if root is None:
        return result
    tags = {"dataset": "dataset", "concept": "concept", "template": "template", "valueSet": "valueset"}
    for node in root.iter():
        kind = tags.get(local(node.tag))
        ident = node.get("id")
        if not kind or not ident:
            continue
        if kind == "template" and not (node.get("name") or node.get("displayName") or node.get("effectiveDate")):
            continue
        if kind == "valueset" and not _valueset_complete(node):
            continue
        result.add((kind, ident, node.get("effectiveDate") or ""))
    return result


def _satisfied(want: Mapping[str, str], have: set[tuple[str, str, str]]) -> bool:
    kind, ident, effective = want["kind"], want["id"], want.get("effective_date") or ""
    if effective:
        return (kind, ident, effective) in have
    return any(k == kind and i == ident for k, i, _ in have)

def _matching_embedded(roots: Iterable[ET.Element | None], want: Mapping[str, str]) -> list[ET.Element]:
    tag_for = {"dataset": "dataset", "concept": "concept", "template": "template", "valueset": "valueSet"}
    wanted_tag = tag_for.get(want.get("kind", ""))
    if not wanted_tag:
        return []
    rows: list[ET.Element] = []
    effective = want.get("effective_date") or ""
    for root in roots:
        if root is None:
            continue
        for node in root.iter():
            if local(node.tag) != wanted_tag or node.get("id") != want.get("id"):
                continue
            if effective and (node.get("effectiveDate") or "") != effective:
                continue
            if wanted_tag == "template" and not (node.get("name") or node.get("displayName") or node.get("effectiveDate")):
                continue
            rows.append(node)
    if effective or len(rows) <= 1:
        return rows
    rows.sort(key=lambda node: node.get("effectiveDate") or "")
    return rows[-1:]


def _evidence_references(root: ET.Element, relevant_ids: set[str]) -> list[Want]:
    """External evidence references relevant to the selected transaction only.

    The complete live *main* project is already available locally for lineage
    and templateAssociation analysis.  This function deliberately avoids
    recursively harvesting dependencies of unrelated live-project content.
    """
    found: dict[str, Want] = {}
    for node in root.iter():
        kind = local(node.tag)
        selected = False
        if kind == "concept" and node.get("id"):
            linked = {node.get("id") or ""}
            for child in list(node):
                if local(child.tag) in {"inherit", "relationship"}:
                    linked.update(filter(None, (child.get("ref"), child.get("originalId"))))
            selected = bool(linked & relevant_ids)
        elif kind == "templateAssociation":
            selected = any(
                local(child.tag) == "concept" and (child.get("ref") or "") in relevant_ids
                for child in list(node)
            )
        elif kind == "template" and node.get("id"):
            selected = (node.get("id") or "") in relevant_ids
        if not selected:
            continue
        for want in references(node):
            found[_key(want)] = want
    return list(found.values())


def _resolved_effective_date(payload: bytes, want: Mapping[str, str]) -> str:
    try:
        root, _ = parse_text(payload.decode("utf-8", "replace"))
    except (ET.ParseError, ValueError):
        return ""
    tag_for = {"dataset": "dataset", "concept": "concept", "template": "template", "valueset": "valueSet"}
    wanted_tag = tag_for.get(want.get("kind", ""))
    rows: list[str] = []
    for node in root.iter():
        if wanted_tag and local(node.tag) == wanted_tag and node.get("id") == want.get("id"):
            if node.get("effectiveDate"):
                rows.append(node.get("effectiveDate") or "")
    if not rows and root.get("effectiveDate"):
        rows.append(root.get("effectiveDate") or "")
    return max(rows) if rows else ""


def _repositories(*roots: ET.Element | None, own: str) -> list[str]:
    result = [own]
    for root in roots:
        if root is None:
            continue
        for node in root.iter():
            if local(node.tag) == "buildingBlockRepository" and node.get("ident"):
                ident = node.get("ident") or ""
                if ident and ident not in result:
                    result.append(ident)
    return result


def _project_directory(root: ET.Element | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if root is None:
        return result
    for node in root.iter():
        ident = node.get("id")
        prefix = node.get("prefix") or node.get("ident")
        if ident and prefix and ident not in result:
            result[ident] = prefix
    return result


def _owner(identifier: str, directory: Mapping[str, str]) -> str:
    best = ""
    for project_id in directory:
        if identifier == project_id or identifier.startswith(project_id + "."):
            if len(project_id) > len(best):
                best = project_id
    return directory.get(best, "") if best else ""


def _candidate_prefixes(want: Mapping[str, str], owners: Mapping[str, str], repositories: Iterable[str]) -> list[str]:
    owner = _owner(want["id"], owners)
    result: list[str] = []
    # ProjectIndex ownership beats stale prefixes embedded in historical refs.
    for value in (owner, want.get("prefix") or "", *repositories):
        if value and value not in result:
            result.append(value)
    return result or [""]


def _urls(want: Mapping[str, str], prefix: str, language: str) -> list[str]:
    service, id_param, date_param = SERVICES[want["kind"]]
    params = {
        id_param: want["id"],
        date_param: want.get("effective_date") or None,
        "prefix": prefix or None,
        "language": language,
        "format": "expandedxml" if want["kind"] == "template" else "xml",
    }
    urls = [build_url(service, **params)]
    # Compatibility fallback for older ART-DECOR deployments that accepted the
    # historical templateId parameter while examples/documentation use id.
    if want["kind"] == "template":
        compat = dict(params)
        compat.pop("id", None)
        compat["templateId"] = want["id"]
        urls.append(build_url(service, **compat))
    return urls


def _existing_cache_payload(target: Path, old: Mapping[str, Any]) -> bytes | None:
    """Return a usable on-disk cache payload, even if the manifest is stale.

    A valid file is enough to reconstruct a missing/stale manifest entry.  If an
    existing successful manifest entry carries a checksum, however, a checksum
    mismatch is treated as a modified/corrupt cache entry and forces a fresh
    download rather than silently blessing the changed bytes.
    """
    if not target.is_file():
        return None
    try:
        payload = target.read_bytes()
    except OSError:
        return None
    status, _detail = classify_payload(payload)
    if status != "ok":
        return None
    expected = str(old.get("sha256") or "")
    if old.get("status") == "ok" and expected and _digest(payload) != expected:
        return None
    return payload


def _fetch_direct(
    release_dir: Path,
    manifest: dict[str, Any],
    *,
    key: str,
    relative_file: str,
    url: str,
    ipv4: bool,
    retry_missing: bool,
    progress: Progress | None = None,
    label: str | None = None,
) -> Path | None:
    resources = manifest.setdefault("resources", {})
    old = resources.get(key, {})
    target = release_dir / relative_file
    display = label or key
    existing = _existing_cache_payload(target, old)
    if existing is not None:
        resources[key] = {
            **old,
            "status": "ok",
            "file": relative_file,
            "url": old.get("url") or url,
            "bytes": len(existing),
            "sha256": _digest(existing),
        }
        repaired = old.get("status") != "ok" or old.get("file") != relative_file
        suffix = " (manifest repaired)" if repaired else ""
        _emit(progress, f"fetch: {display}: cached{suffix}")
        return target
    if old.get("status") == "missing" and not retry_missing:
        _emit(progress, f"fetch: {display}: known missing")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    _emit(progress, f"fetch: {display}: requesting")
    try:
        payload = get(url, ipv4=ipv4)
    except urllib.error.HTTPError as error:
        status_name = "missing" if error.code in FINAL_STATUS else "error"
        resources[key] = {
            "status": status_name,
            "url": url,
            "http_status": error.code,
        }
        _emit(progress, f"fetch: {display}: {status_name} (HTTP {error.code})")
        return None
    except OSError as error:
        resources[key] = {"status": "error", "url": url, "error": str(error)}
        _emit(progress, f"fetch: {display}: error ({error})")
        return None
    status, detail = classify_payload(payload)
    if status == "empty":
        resources[key] = {"status": "missing", "url": url, "detail": detail}
        _emit(progress, f"fetch: {display}: missing ({detail})")
        return None
    target.write_bytes(payload)
    stored_status = "ok" if status == "ok" else "error"
    resources[key] = {
        "status": stored_status,
        "file": relative_file,
        "url": url,
        "bytes": len(payload),
        "sha256": _digest(payload),
        **({"detail": detail} if detail else {}),
    }
    _emit(progress, f"fetch: {display}: {stored_status} ({_size_text(len(payload))})")
    return target


def _fetch_want(
    release_dir: Path,
    manifest: dict[str, Any],
    want: Want,
    *,
    owners: Mapping[str, str],
    repositories: Iterable[str],
    language: str,
    ipv4: bool,
    retry_missing: bool,
    request_budget: dict[str, int] | None = None,
    progress: Progress | None = None,
) -> Path | None:
    key = _key(want)
    old = manifest.setdefault("resources", {}).get(key, {})
    relative = str(old.get("file") or _filename(want))
    target = release_dir / relative
    display = _resource_label(want)
    existing = _existing_cache_payload(target, old)
    if existing is not None:
        resolved_date = _resolved_effective_date(existing, want)
        requested_date = want.get("effective_date") or ""
        # A static dependency must not accidentally adopt another revision that
        # happens to have the expected filename. Dynamic dependencies may adopt
        # whatever revision the valid cached response actually contains.
        if not requested_date or not resolved_date or resolved_date == requested_date:
            manifest["resources"][key] = {
                **old,
                "status": "ok",
                "file": relative,
                "bytes": len(existing),
                "sha256": _digest(existing),
                "requested_effective_date": requested_date or "dynamic",
                "resolved_effective_date": resolved_date or old.get("resolved_effective_date", ""),
            }
            repaired = old.get("status") != "ok" or old.get("file") != relative
            suffix = " (manifest repaired)" if repaired else ""
            _emit(progress, f"fetch: {display}: cached{suffix}")
            return target
    if old.get("status") == "missing" and not retry_missing:
        _emit(progress, f"fetch: {display}: known missing")
        return None

    request_want: Want = dict(want)
    if not request_want.get("effective_date") and old.get("resolved_effective_date"):
        request_want["effective_date"] = str(old["resolved_effective_date"])

    attempts: list[dict[str, Any]] = []
    for prefix in _candidate_prefixes(request_want, owners, repositories):
        resolved = dict(request_want)
        resolved["prefix"] = prefix
        for url in _urls(resolved, prefix, language):
            if request_budget is not None:
                if request_budget.get("made", 0) >= request_budget.get("max", 0):
                    raise RequestBudgetExceeded
                request_budget["made"] = request_budget.get("made", 0) + 1
            count = request_budget.get("made", 0) if request_budget is not None else 0
            maximum = request_budget.get("max", 0) if request_budget is not None else 0
            budget = f" [{count}/{maximum}]" if maximum else ""
            _emit(progress, f"fetch: {display}: requesting via {prefix or '?'}{budget}")
            try:
                payload = get(url, ipv4=ipv4)
            except urllib.error.HTTPError as error:
                attempts.append({"prefix": prefix, "url": url, "http_status": error.code})
                _emit(progress, f"fetch: {display}: HTTP {error.code} via {prefix or '?'}; trying next source")
                continue
            except OSError as error:
                attempts.append({"prefix": prefix, "url": url, "error": str(error)})
                _emit(progress, f"fetch: {display}: {error} via {prefix or '?'}; trying next source")
                continue
            status, detail = classify_payload(payload)
            if status == "empty":
                attempts.append({"prefix": prefix, "url": url, "error": detail})
                _emit(progress, f"fetch: {display}: empty response via {prefix or '?'}; trying next source")
                continue
            target = release_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            stored_status = "ok" if status == "ok" else "error"
            resolved_date = _resolved_effective_date(payload, want)
            manifest["resources"][key] = {
                "status": stored_status,
                "file": relative,
                "url": url,
                "repository": prefix,
                "bytes": len(payload),
                "sha256": _digest(payload),
                "requested_effective_date": want.get("effective_date") or "dynamic",
                "resolved_effective_date": resolved_date,
                **({"detail": detail} if detail else {}),
            }
            resolved_note = f", resolved {resolved_date}" if not want.get("effective_date") and resolved_date else ""
            _emit(progress, f"fetch: {display}: {stored_status} via {prefix or '?'} ({_size_text(len(payload))}{resolved_note})")
            return target
    settled = bool(attempts) and all(
        item.get("http_status") in FINAL_STATUS or item.get("error", "").startswith("<")
        for item in attempts
    )
    final_status = "missing" if settled else "error"
    manifest["resources"][key] = {
        "status": final_status,
        "attempts": attempts,
    }
    _emit(progress, f"fetch: {display}: {final_status} after {len(attempts)} attempt(s)")
    return None


def verify_manifest(release_dir: Path) -> list[str]:
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"missing {manifest_path}"]
    manifest = load_json(manifest_path)
    errors: list[str] = []
    for key, entry in manifest.get("resources", {}).items():
        if entry.get("status") != "ok" or not entry.get("file"):
            continue
        path = release_dir / str(entry["file"])
        if not path.exists():
            errors.append(f"{key}: missing downloaded file {entry['file']}")
        elif entry.get("sha256") and _digest(path.read_bytes()) != entry["sha256"]:
            errors.append(f"{key}: checksum mismatch for {entry['file']}")
    return errors


def closure_paths(release_dir: Path, transaction_dir: Path, role: str = "build") -> list[Path]:
    """Resolve resource paths recorded for a transaction closure."""
    closure = load_json(transaction_dir / "closure.json")
    manifest = load_json(release_dir / "manifest.json")
    keys = closure.get(f"{role}_resources", [])
    result: list[Path] = []
    for key in keys:
        entry = manifest.get("resources", {}).get(key, {})
        if entry.get("status") == "ok" and entry.get("file"):
            path = release_dir / str(entry["file"])
            if path.exists():
                result.append(path)
    return result


def fetch_spec(
    release_dir: Path,
    transaction_dir: Path,
    *,
    prefix: str,
    release: Mapping[str, str],
    transaction: Mapping[str, str],
    language: str = "de-DE",
    ipv4: bool = True,
    retry_missing: bool = False,
    max_requests: int = 1500,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Fetch the selected transaction and recursively close its dependencies."""
    release_dir.mkdir(parents=True, exist_ok=True)
    transaction_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {
        "format": 1,
        "release": dict(release),
        "prefix": prefix,
        "resources": {},
    }
    manifest["release"] = dict(release)
    manifest["prefix"] = prefix

    release_date = release.get("date") or ""
    tx_id = transaction.get("id") or ""
    tx_effective = transaction.get("effective_date") or ""

    project_url = build_url(
        "RetrieveProject", prefix=prefix, version=release_date,
        language=language, mode="verbatim", format="xml"
    )
    pinned = _fetch_direct(
        release_dir, manifest, key=f"project:{prefix}@{release_date}",
        relative_file="project.xml", url=project_url, ipv4=ipv4,
        retry_missing=retry_missing, progress=progress,
        label=f"release project {release.get('key') or release_date or '?'}",
    )
    evidence_url = build_url(
        "RetrieveProject", prefix=prefix, language=language,
        mode="verbatim", format="xml"
    )
    evidence = _fetch_direct(
        release_dir, manifest, key=f"project-evidence:{prefix}",
        relative_file="project-evidence.xml", url=evidence_url, ipv4=ipv4,
        retry_missing=retry_missing, progress=progress,
        label=f"live evidence project {prefix}",
    )
    index_url = build_url("ProjectIndex", format="xml", language=language)
    project_index = _fetch_direct(
        release_dir, manifest, key="project-index", relative_file="project-index.xml",
        url=index_url, ipv4=ipv4, retry_missing=retry_missing, progress=progress,
        label="global project index",
    )
    tx_url = build_url(
        "RetrieveTransaction", id=tx_id, effectiveDate=tx_effective or None,
        prefix=prefix, version=release_date, language=language, format="xml"
    )
    tx_path = _fetch_direct(
        release_dir, manifest,
        key=f"transaction:{tx_id}@{tx_effective}",
        relative_file=str((transaction_dir / "transaction.xml").relative_to(release_dir)),
        url=tx_url, ipv4=ipv4, retry_missing=retry_missing, progress=progress,
        label=f"transaction {transaction.get('key') or tx_id or '?'}",
    )
    root_errors: list[str] = []
    if pinned is None:
        root_errors.append("selected release project could not be fetched")
    if tx_path is None:
        root_errors.append("selected transaction could not be fetched")

    build_roots = [_parse(path) for path in (pinned, tx_path) if path]
    evidence_roots = [_parse(evidence)] if evidence else []
    owners = _project_directory(_parse(project_index) if project_index else None)
    repositories = _repositories(*(build_roots + evidence_roots), own=prefix)

    build_queue: deque[Want] = deque()
    tx_root = _parse(tx_path) if tx_path else None
    if tx_root is not None:
        build_queue.extend(references(tx_root))
    # Some deployments expose representingTemplate metadata only on the
    # transaction object inside RetrieveProject. Seed only that transaction,
    # never the whole pinned project.
    pinned_root = _parse(pinned) if pinned else None
    if pinned_root is not None:
        for node in pinned_root.iter():
            if local(node.tag) == "transaction" and node.get("id") == tx_id:
                build_queue.extend(references(node))

    roles: dict[str, set[str]] = {"build": set(), "evidence": set()}
    visited: dict[str, set[str]] = {"build": set(), "evidence": set()}
    # Only count embedded resources as "already available" when the later
    # compiler actually receives the container that holds them.  The selected
    # transaction is a model input for every resource kind; the pinned project
    # is a CDA/template input, but its datasets/value sets/concepts are not fed
    # wholesale into model compilation (doing so would mix unrelated project
    # history into the selected transaction).  Those non-template dependencies
    # therefore still need their own targeted download.
    build_have: set[tuple[str, str, str]] = set()
    if tx_root is not None:
        build_have.update(_inventory(tx_root))
    if pinned_root is not None:
        build_have.update(
            item for item in _inventory(pinned_root) if item[0] == "template"
        )
    evidence_have = set(build_have)
    for root in evidence_roots:
        evidence_have.update(_inventory(root))
    have_by_role = {"build": build_have, "evidence": evidence_have}
    request_budget = {"made": 0, "max": max(0, int(max_requests))}
    resources_considered = 0
    budget_exhausted = False

    def crawl(queue: deque[Want], role: str, embedded_roots: list[ET.Element | None]) -> None:
        nonlocal resources_considered, budget_exhausted
        _emit(progress, f"fetch: resolving {role} dependency closure ({len(queue)} initial reference(s))")
        while queue and not budget_exhausted:
            rows = list(queue)
            queue.clear()
            rows.sort(key=lambda item: (KIND_ORDER.get(item["kind"], 9), item.get("prefix", ""), item["id"]))
            for row_index, want in enumerate(rows):
                key = _key(want)
                if key in visited[role]:
                    continue
                embedded = _matching_embedded(embedded_roots, want)
                if _satisfied(want, have_by_role[role]):
                    visited[role].add(key)
                    for node in embedded:
                        queue.extend(references(node))
                    continue
                resources_considered += 1
                try:
                    path = _fetch_want(
                        release_dir, manifest, want, owners=owners,
                        repositories=repositories, language=language,
                        ipv4=ipv4, retry_missing=retry_missing,
                        request_budget=request_budget, progress=progress,
                    )
                except RequestBudgetExceeded:
                    # Preserve this resource and the remainder of the current
                    # batch for a later fetch run.
                    for pending in reversed(rows[row_index:]):
                        queue.appendleft(pending)
                    budget_exhausted = True
                    return
                visited[role].add(key)
                roles[role].add(key)
                if path is None:
                    continue
                root = _parse(path)
                if root is not None:
                    have_by_role[role].update(_inventory(root))
                    queue.extend(references(root))

    crawl(build_queue, "build", build_roots)

    # The unpinned project is fetched only for the selected/main project.  Its
    # local history is consumed directly by mapping; recursive external evidence
    # is restricted to concepts/templates already relevant to this transaction.
    relevant_ids: set[str] = set()
    if tx_root is not None:
        relevant_ids.update(ident for _, ident, _ in _inventory(tx_root))
    for key in visited["build"] | roles["build"]:
        try:
            relevant_ids.add(key.split(":", 1)[1].split("@", 1)[0])
        except IndexError:
            pass
    evidence_queue: deque[Want] = deque()
    for root in evidence_roots:
        if root is not None:
            evidence_queue.extend(_evidence_references(root, relevant_ids))
    crawl(evidence_queue, "evidence", build_roots + evidence_roots)

    current_keys = roles["build"] | roles["evidence"]
    current_errors = sorted(
        key for key in current_keys
        if manifest.get("resources", {}).get(key, {}).get("status") == "error"
    )
    current_missing = sorted(
        key for key in current_keys
        if manifest.get("resources", {}).get(key, {}).get("status") == "missing"
    )
    closure = {
        "format": 1,
        "release": dict(release),
        "transaction": dict(transaction),
        "build_resources": sorted(roles["build"]),
        "evidence_resources": sorted(roles["evidence"] | roles["build"]),
        "missing": current_missing,
        "errors": current_errors + root_errors,
        "root_status": {
            "project": "ok" if pinned is not None else "missing",
            "transaction": "ok" if tx_path is not None else "missing",
            "project_evidence": "ok" if evidence is not None else "missing",
            "project_index": "ok" if project_index is not None else "missing",
        },
        "summary": {
            "ok": sum(manifest.get("resources", {}).get(key, {}).get("status") == "ok" for key in current_keys)
                  + int(pinned is not None) + int(tx_path is not None),
            "missing": len(current_missing),
            "error": len(current_errors) + len(root_errors),
        },
        "resources_considered": resources_considered,
        "recursive_http_requests": request_budget["made"],
        "truncated": budget_exhausted or bool(build_queue or evidence_queue),
    }
    write_json(transaction_dir / "closure.json", closure)

    manifest["summary"] = {
        "resources": len(manifest.get("resources", {})),
        "ok": sum(1 for row in manifest.get("resources", {}).values() if row.get("status") == "ok"),
        "missing": sum(1 for row in manifest.get("resources", {}).values() if row.get("status") == "missing"),
        "error": sum(1 for row in manifest.get("resources", {}).values() if row.get("status") == "error"),
    }
    write_json(manifest_path, manifest)
    _emit(
        progress,
        "fetch: complete: "
        f"{closure['summary']['ok']} ok/cached, "
        f"{closure['summary']['missing']} missing, "
        f"{closure['summary']['error']} error(s), "
        f"{closure['recursive_http_requests']} recursive HTTP request(s)",
    )
    return {"manifest": manifest, "closure": closure}
