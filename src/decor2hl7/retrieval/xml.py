"""Small helpers for the slightly irregular XML exported by ART-DECOR."""

from __future__ import annotations

from io import StringIO
import re
import xml.etree.ElementTree as ET
from pathlib import Path

KNOWN_PREFIXES = {
    "hl7": "urn:hl7-org:v3",
    "cda": "urn:hl7-org:v3",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xml": "http://www.w3.org/XML/1998/namespace",
    "pharm": "urn:ihe:pharm",
    "pharmhl7": "urn:hl7-org:pharm",
    "art": "urn:art-decor:example",
}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if local(child.tag) == name:
            return clean("".join(child.itertext()))
    return ""


def repair_namespaces(text: str) -> tuple[str, list[str]]:
    """Bind prefixes that some ART-DECOR exports use without declaring."""
    start = text.find("<")
    while start >= 0 and text.startswith(("<?", "<!"), start):
        end = text.find(">", start)
        if end < 0:
            return text, []
        start = text.find("<", end + 1)
    if start < 0:
        return text, []
    end = text.find(">", start)
    if end < 0:
        return text, []
    head = text[start:end]
    used = set(re.findall(r"(?:<|</|\s)([A-Za-z_][\w.-]*):[\w.-]+", text))
    declared = set(re.findall(r"xmlns:([A-Za-z_][\w.-]*)\s*=", head))
    missing = sorted(prefix for prefix in used - declared if prefix in KNOWN_PREFIXES)
    if not missing:
        return text, []
    declarations = "".join(
        f' xmlns:{prefix}="{KNOWN_PREFIXES[prefix]}"' for prefix in missing
    )
    return text[:end] + declarations + text[end:], missing


def parse_text(text: str) -> tuple[ET.Element, list[str]]:
    repaired, repairs = repair_namespaces(text)
    return ET.fromstring(repaired), repairs


def template_namespace_maps(text: str) -> dict[tuple[str, str], dict[str, str]]:
    """Return the in-scope prefix bindings for each exact template.

    ART-DECOR stores XML design names such as ``pharmhl7:formCode`` in
    attribute values.  ElementTree correctly parses the surrounding XML but
    does not resolve prefixes embedded in those strings.  Capture the lexical
    namespace scope before that information is lost so the CDA compiler can
    retain expanded QName identity for rendering and validation.
    """
    repaired, _ = repair_namespaces(text)
    pending: dict[str, str] = {}
    scopes: list[dict[str, str]] = []
    result: dict[tuple[str, str], dict[str, str]] = {}
    for event, item in ET.iterparse(
        StringIO(repaired), events=("start-ns", "start", "end")
    ):
        if event == "start-ns":
            prefix, uri = item
            pending[str(prefix or "")] = str(uri)
            continue
        if event == "start":
            scope = dict(scopes[-1]) if scopes else {}
            scope.update(pending)
            pending.clear()
            scopes.append(scope)
            if local(item.tag) == "template" and item.get("id"):
                result[(
                    item.get("id") or "",
                    item.get("effectiveDate") or "",
                )] = dict(scope)
            continue
        scopes.pop()
    return result


def parse_file(path: Path) -> tuple[ET.Element, list[str]]:
    return parse_text(path.read_text(encoding="utf-8", errors="replace"))
