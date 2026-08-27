"""Small helpers for the slightly irregular XML exported by ART-DECOR."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

KNOWN_PREFIXES = {
    "hl7": "urn:hl7-org:v3",
    "cda": "urn:hl7-org:v3",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xml": "http://www.w3.org/XML/1998/namespace",
    "pharm": "urn:ihe:pharm",
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


def parse_file(path: Path) -> tuple[ET.Element, list[str]]:
    return parse_text(path.read_text(encoding="utf-8", errors="replace"))
