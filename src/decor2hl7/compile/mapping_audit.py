"""Serialize the final mapping decision state independently of its reports."""
from __future__ import annotations
from collections import Counter
from ..contracts import MappingAudit, mapping_audit
from typing import Any, Mapping
from .mapping_decisions import mapping_coverage


def _audit_candidate(
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    # Matching carries the complete compiled target in ``node``. Persist the
    # stable identity/evidence instead of duplicating that target snapshot.
    return {str(key): value for key, value in candidate.items() if key != "node"}


def _audit_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected": detail.get("selected"),
        "primary": _audit_candidate(detail.get("primary")),
        "alternatives": [
            _audit_candidate(candidate)
            for candidate in detail.get("alternatives", [])
        ],
        "context": detail.get("context"),
        **(
            {"runtime_blocked": detail["runtime_blocked"]}
            if detail.get("runtime_blocked") else {}
        ),
        **(
            {"required_companions": list(detail["required_companions"])}
            if detail.get("required_companions") else {}
        ),
        **(
            {"unresolved_reason": detail["unresolved_reason"]}
            if detail.get("unresolved_reason") else {}
        ),
        **(
            {"gap": dict(detail["gap"])}
            if detail.get("gap") else {}
        ),
        **(
            {"possible_targets": dict(detail["possible_targets"])}
            if detail.get("possible_targets") else {}
        ),
        **(
            {"structural_rule": detail["structural_rule"]}
            if detail.get("structural_rule") else {}
        ),
        **(
            {"shared_target_winner": True}
            if detail.get("shared_target_winner") else {}
        ),
    }


def build_mapping_audit(
    model: Mapping[str, Any], cda: Mapping[str, Any], proposal: Mapping[str, Any],
    details: Mapping[str, dict[str, Any]], group_results: Mapping[str, dict[str, Any]],
) -> MappingAudit:
    all_details = {**group_results, **details}
    all_coverage = Counter(mapping_coverage(detail) for detail in all_details.values())
    item_coverage = Counter(mapping_coverage(detail) for detail in details.values())
    group_coverage = Counter(mapping_coverage(detail) for detail in group_results.values())
    confidence = Counter(detail["primary"]["confidence"] if detail.get("primary") else "NO" for detail in all_details.values())
    bridge = Counter(detail["primary"]["kind"] if detail.get("primary") else "NONE" for detail in all_details.values())
    fields, structures = proposal["fields"], proposal["structures"]
    audit: dict[str, Any] = {
        "version": 2,
        "model": dict(proposal["model"]),
        "target": dict(proposal["target"]),
        "fields": {
            path: _audit_detail(detail) for path, detail in details.items()
        },
        "groups": {
            path: _audit_detail(detail) for path, detail in group_results.items()
        },
        "structures": structures,
        "unresolved_templates": list(cda.get("unresolved_templates", [])),
        "summary": {
            "datapoints": len(all_details),
            "coverage": dict(all_coverage),
            "field_coverage": dict(item_coverage),
            "group_coverage": dict(group_coverage),
            "confidence": dict(confidence),
            "primary_evidence": dict(bridge),
            "executable_fields": sum(value is not None for value in fields.values()),
            "shared_target_blocks": sum(
                str(detail.get("runtime_blocked") or "").startswith((
                    "SHARED(", "WEAKER_SHARED_TARGET(",
                ))
                for detail in details.values()
            ),
            "required_companion_blocks": sum(
                str(detail.get("runtime_blocked") or "").startswith(
                    "REQUIRED_COMPANION("
                )
                for detail in details.values()
            ),
            "gaps": dict(Counter(
                f"{gap['gate']}:{gap['kind']}"
                for detail in all_details.values()
                for gap in [detail.get("gap")]
                if isinstance(gap, Mapping)
            )),
            "structural_rules": Counter(
                str(rule.get("type") or "unknown") for rule in structures.values()
            ),
        },
    }
    from .reports import coverage_headline_counts
    audit["summary"]["coverage_headline"] = coverage_headline_counts(
        model, cda, proposal, audit
    )
    return mapping_audit(audit)
