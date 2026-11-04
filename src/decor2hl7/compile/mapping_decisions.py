"""Shared mapping decision labels; no proposal mutation or text rendering."""
from __future__ import annotations
from typing import Any, Mapping

_ASSOCIATION_REQUEST_PREFIX = "association:"


def association_request(path: str) -> str:
    return f"{_ASSOCIATION_REQUEST_PREFIX}{path}"


def gap_reopening_evidence_label(value: Any) -> str:
    """Render a reopening key without repeating the current source path."""
    text = str(value)
    if (
        text.startswith(_ASSOCIATION_REQUEST_PREFIX)
        and text[len(_ASSOCIATION_REQUEST_PREFIX):]
    ):
        return "upstream association or reviewed semantic bridge"
    return text


def mapping_coverage(detail: Mapping[str, Any]) -> str:
    if detail.get("primary"):
        return "YES"
    if detail.get("context"):
        return "PARTIAL"
    return "NO"


def mapping_qualification(
    detail: Mapping[str, Any], primary: Mapping[str, Any]
) -> str:
    close = {
        alt["target"] for alt in detail.get("alternatives", [])
        if alt.get("actionable") and alt["target"] != primary["target"]
        and alt["score"] >= primary["score"] - 5
    }
    if close:
        return f"MULTIPLE({len(close) + 1})"
    indirect_tokens = {
        "inherit^-1", "contains^-1", "originalId^-1",
        "TA_VERSION", "TA_SPEC",
        "OPEN_CODED_DOMAIN", "ART_DECOR_EXAMPLE",
    }
    if primary.get("confidence") == "STRONG" and not any(
        token in indirect_tokens
        or str(token).startswith("OPEN_CODED_DOMAIN(")
        or str(token).startswith("ART_DECOR_EXAMPLE(")
        for token in primary.get("chain", [])
    ):
        return "EXACT"
    return "INDIRECT"
