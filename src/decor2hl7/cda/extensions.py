"""Reviewed attachments of exact CDA templates to open template slots.

ART-DECOR ``context`` metadata and an open template do not identify which
standalone entry template belongs at a particular document location.  This
module reads the explicit, transaction-scoped bridge used when that placement
has been reviewed outside the upstream ART-DECOR containment graph.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, TypedDict


class CdaExtension(TypedDict):
    transaction_id: str
    transaction_effective_date: str
    document_template_id: str
    document_template_effective_date: str
    parent_template_id: str
    parent_template_effective_date: str
    parent_element_id: str
    element_name: str
    template_id: str
    template_effective_date: str
    minimum_multiplicity: int
    maximum_multiplicity: int | str
    conformance: str
    reason: str


_REQUIRED_TEXT = (
    "transaction_id",
    "transaction_effective_date",
    "document_template_id",
    "document_template_effective_date",
    "parent_template_id",
    "parent_template_effective_date",
    "parent_element_id",
    "element_name",
    "template_id",
    "template_effective_date",
    "conformance",
    "reason",
)
_CONFORMANCE = {"O", "R", "M", "C"}


def _multiplicity(value: Any, *, maximum: bool, label: str) -> int | str:
    if maximum and value == "*":
        return "*"
    invalid_number = (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < (1 if maximum else 0)
    )
    if invalid_number:
        expected = (
            "a positive integer or '*'" if maximum else "a non-negative integer"
        )
        raise ValueError(f"CDA extension {label!r} must be {expected}")
    return value


def normalize_extensions(rows: Iterable[Mapping[str, Any]]) -> list[CdaExtension]:
    """Validate and canonicalize reviewed extension attachment records."""
    result: list[CdaExtension] = []
    seen: set[tuple[str, ...]] = set()
    for index, raw in enumerate(rows):
        missing = [
            name for name in _REQUIRED_TEXT
            if not str(raw.get(name) or "").strip()
        ]
        missing.extend(
            name for name in ("minimum_multiplicity", "maximum_multiplicity")
            if name not in raw
        )
        if missing:
            raise ValueError(
                f"CDA extension attachment {index} is missing: {', '.join(missing)}"
            )
        minimum = _multiplicity(
            raw.get("minimum_multiplicity"), maximum=False,
            label="minimum_multiplicity",
        )
        maximum = _multiplicity(
            raw.get("maximum_multiplicity"), maximum=True,
            label="maximum_multiplicity",
        )
        if not isinstance(minimum, int):
            raise AssertionError("minimum multiplicity normalization returned '*'")
        if isinstance(maximum, int) and maximum < minimum:
            raise ValueError(
                f"CDA extension attachment {index} has maximum_multiplicity "
                "below minimum_multiplicity"
            )
        conformance = str(raw.get("conformance") or "").strip().upper()
        if conformance not in _CONFORMANCE:
            raise ValueError(
                f"CDA extension attachment {index} has unsupported conformance "
                f"{conformance!r}"
            )
        row = CdaExtension(
            transaction_id=str(raw.get("transaction_id") or "").strip(),
            transaction_effective_date=str(
                raw.get("transaction_effective_date") or ""
            ).strip(),
            document_template_id=str(raw.get("document_template_id") or "").strip(),
            document_template_effective_date=str(
                raw.get("document_template_effective_date") or ""
            ).strip(),
            parent_template_id=str(raw.get("parent_template_id") or "").strip(),
            parent_template_effective_date=str(
                raw.get("parent_template_effective_date") or ""
            ).strip(),
            parent_element_id=str(raw.get("parent_element_id") or "").strip(),
            element_name=str(raw.get("element_name") or "").strip(),
            template_id=str(raw.get("template_id") or "").strip(),
            template_effective_date=str(
                raw.get("template_effective_date") or ""
            ).strip(),
            minimum_multiplicity=minimum,
            maximum_multiplicity=maximum,
            conformance=conformance,
            reason=str(raw.get("reason") or "").strip(),
        )
        identity = (
            row["transaction_id"], row["transaction_effective_date"],
            row["document_template_id"], row["document_template_effective_date"],
            row["parent_template_id"], row["parent_template_effective_date"],
            row["parent_element_id"], row["element_name"],
            row["template_id"], row["template_effective_date"],
        )
        if identity in seen:
            raise ValueError(
                f"duplicate CDA extension attachment for {row['template_id']} "
                f"at {row['parent_template_id']}#{row['parent_element_id']}"
            )
        seen.add(identity)
        result.append(row)
    return result


def load_extensions(
    path: Path | None, transaction: Mapping[str, str],
) -> list[CdaExtension]:
    """Load attachments for the exact selected transaction.

    Other transaction records may coexist in the same acquisition-wide file,
    but every record is validated so stale malformed policy is visible.
    """
    if path is None or not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    if document.get("format") != 1:
        raise ValueError(f"{path} must declare CDA extension format 1")
    attachments = document.get("attachments", [])
    if not isinstance(attachments, list) or not all(
        isinstance(item, Mapping) for item in attachments
    ):
        raise ValueError(f"{path} 'attachments' must contain an array of objects")
    normalized = normalize_extensions(attachments)
    transaction_id = str(transaction.get("id") or "")
    transaction_effective = str(transaction.get("effective_date") or "")
    return [
        row for row in normalized
        if row["transaction_id"] == transaction_id
        and row["transaction_effective_date"] == transaction_effective
    ]
