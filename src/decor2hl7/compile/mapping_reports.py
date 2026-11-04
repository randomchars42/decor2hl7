"""Presentation of completed mapping decisions; never selects a target."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping
from ..i18n import message as _msg
from .mapping_decisions import (
    gap_reopening_evidence_label, mapping_coverage, mapping_qualification,
)


@dataclass(frozen=True)
class ReportContext:
    model: Mapping[str, Any]
    cda: Mapping[str, Any]
    proposal: Mapping[str, Any]
    details: Mapping[str, dict[str, Any]]


def target_datatype(cda: Mapping[str, Any], name: str) -> str:
    return str(cda.get("targets", {}).get(name, {}).get("datatype") or "—")


def evidence(candidate: Mapping[str, Any]) -> str:
    return " → ".join(str(item) for item in candidate.get("chain", [])) or str(candidate.get("kind") or "—")


def reason_for(path: str, detail: Mapping[str, Any]) -> str:
    primary = detail.get("primary")
    if primary:
        blocked = detail.get("runtime_blocked")
        if blocked:
            if str(blocked).startswith("REQUIRED_COMPANION("):
                companions = detail.get("required_companions", [])
                return (
                    "The best CDA target is supported by mapping evidence, but a "
                    "non-null compound value also requires the companion target(s) "
                    + ", ".join(f"`{item}`" for item in companions)
                    + ". No source mapping currently supplies that companion."
                )
            return (
                "The best CDA target is supported by mapping evidence, but it is shared "
                "with another dataset field and therefore needs an explicit rule before execution."
            )
        if detail.get("structural_rule"):
            return (
                "The CDA target is supported by mapping evidence and the shared occurrence "
                f"semantics are made explicit by structural rule `{detail['structural_rule']}`."
            )
        if primary.get("kind") == "OPEN_CODED_DOMAIN":
            return (
                "The source declares an unconstrained coded domain. Inside the "
                "mapped container, one unique coded target binds an OTH exception "
                "and exposes originalText, so unmatched wording has a formal "
                "target representation without inventing a terminology crosswalk."
            )
        mapping = primary.get("mapping")
        if isinstance(mapping, Mapping) and mapping.get("mode") == "presence":
            return (
                "Exact source terminology identifies an optional ART-DECOR statement "
                "whose clinical payload is fixed by the template. Boolean true activates "
                "that statement and false omits it."
            )
        if primary.get("mapping") is not None:
            return (
                "The datapoint and CDA target represent the same information with different "
                "representations, so a declarative transform is required."
            )
        kind = str(primary.get("kind") or "")
        reasons = {
            "XPATH": "An explicit ART-DECOR implementation XPath identifies this CDA target.",
            "TA": "A formal template association connects the datapoint or one of its formal origins to this CDA element.",
            "STATIC_ASSOC": "An ART-DECOR static association connects the datapoint to this CDA element.",
            "STATIC_ASSOC_SLOT": (
                "An ART-DECOR static association identifies a CDA/RIM base slot, "
                "which resolves uniquely in the mapped target context."
            ),
            "TERM+VS": "Terminology locates the CDA template and compatible value-set evidence identifies the target.",
            "TERM+DT": "Terminology locates the CDA template and datatype compatibility identifies its unique payload.",
            "TERM": "Compatible terminology provides an indirect bridge to this CDA target.",
            "NAME": "A unique semantic template-name match provides the bridge to this CDA target.",
            "DESC": "Published descriptions provide a semantic bridge to this CDA target.",
            "TRANSFORM": "CDA semantics match, but the dataset value must be transformed before rendering.",
        }
        text = reasons.get(kind, "The available ART-DECOR evidence identifies this as the best CDA target.")
        if primary.get("confidence") == "WEAK":
            text += " The evidence is indirect, so the selection should be reviewed."
        qualification = mapping_qualification(detail, primary)
        if qualification.startswith("MULTIPLE("):
            text += " Another actionable target has a comparable score."
        if primary.get("warnings"):
            text += " Warning: " + "; ".join(str(item) for item in primary["warnings"]) + "."
        return text
    if detail.get("context"):
        return (
            "No executable CDA element could be established; the nearest mapped structural "
            "group supplies only contextual placement."
        )
    if detail.get("alternatives"):
        return "Candidate evidence exists, but none is safe enough to become an executable mapping automatically."
    return (_msg('markdown.no_usable_cda_target_evidence_for_datapoint'))


def status_for(model_fields: Mapping[str, Any], fields: Mapping[str, Any], path: str, detail: Mapping[str, Any]) -> str:
    primary = detail.get("primary")
    if not primary:
        return "PARTIAL · CONTEXT · NOT EXECUTABLE" if detail.get("context") else "NO · NOT EXECUTABLE"
    qualification = mapping_qualification(detail, primary)
    blocked = str(detail.get("runtime_blocked") or "")
    if blocked.startswith("REQUIRED_COMPANION("):
        execution = "REQUIRES COMPANION"
    elif blocked:
        execution = "REQUIRES RULE"
    elif (
        isinstance(primary.get("mapping"), Mapping)
        and primary.get("mapping", {}).get("mode") == "presence"
    ):
        execution = "PRESENCE RULE"
    elif primary.get("mapping") is not None:
        execution = "TRANSFORM"
    elif path in model_fields and fields.get(path) is not None:
        execution = "EXECUTABLE"
    else:
        execution = "EVIDENCE ONLY"
    return f"YES · {primary.get('confidence')} · {qualification} · {execution}"


def candidate_rows(path: str, detail: Mapping[str, Any], limit: int) -> list[tuple[Mapping[str, Any], str]]:
    rows: list[tuple[Mapping[str, Any], str]] = []
    primary = detail.get("primary")
    if primary:
        result = "SELECTED"
        blocked = str(detail.get("runtime_blocked") or "")
        if blocked.startswith("REQUIRED_COMPANION("):
            result = "CANDIDATE / REQUIRES COMPANION"
        elif blocked:
            result = "SELECTED / REQUIRES RULE"
        elif (
            isinstance(primary.get("mapping"), Mapping)
            and primary.get("mapping", {}).get("mode") == "presence"
        ):
            result = "SELECTED / PRESENCE RULE"
        elif primary.get("mapping") is not None:
            result = "SELECTED / TRANSFORM"
        rows.append((primary, result))
    for alt in detail.get("alternatives", []):
        if len(rows) >= limit:
            break
        rows.append((
            alt,
            "suggested / no formal bridge" if alt.get("suggested") else
            "alternative" if alt.get("actionable") else "evidence only",
        ))
    if not rows and detail.get("context"):
        context = detail["context"]
        rows.append(({
            "target": context.get("target"), "confidence": "CONTEXT",
            "chain": context.get("chain", []), "actionable": False, "score": 0,
            "warnings": [],
        }, "context only"))
    return rows


def field_section(context: ReportContext, path: str, *, detailed: bool) -> list[str]:
    model_fields, fields = context.model.get("fields", {}), context.proposal["fields"]
    cda, details = context.cda, context.details
    field = model_fields[path]
    detail = details[path]
    primary = detail.get("primary")
    short = str(field.get("concept") or "").rsplit(".", 1)[-1]
    heading = f"## {field.get('name') or path}" + (f" [{short}]" if short else "")
    out = [heading, "", f"`{path}`", "", f"**{status_for(model_fields, fields, path, detail)}**", ""]
    if primary:
        selected = detail.get("selected")
        if selected is None:
            selected = primary.get("mapping") if primary.get("mapping") is not None else primary.get("target")
        if str(detail.get("runtime_blocked") or "").startswith(
            "REQUIRED_COMPANION("
        ):
            out += ["**Candidate:**", "", f"`{primary.get('target')}` `[{target_datatype(cda, str(primary.get('target')))}]`", ""]
        elif (
            isinstance(primary.get("mapping"), Mapping)
            and primary.get("mapping", {}).get("mode") == "presence"
        ):
            out += ["**Selected:**", "", f"`{primary.get('target')}` `[{target_datatype(cda, str(primary.get('target')))}]` as a conditional presence rule", ""]
        elif primary.get("mapping") is not None:
            out += ["**Selected:**", "", f"`{primary.get('target')}` `[{target_datatype(cda, str(primary.get('target')))}]` with declarative transform", ""]
        else:
            out += ["**Selected:**", "", f"`{primary.get('target')}` `[{target_datatype(cda, str(primary.get('target')))}]`", ""]
        if detail.get("structural_rule"):
            out += ["**Structural rule:**", "", f"`{detail['structural_rule']}`", ""]
    elif detail.get("context"):
        out += ["**Context:**", "", f"`{detail['context'].get('target')}`", ""]
    else:
        out += ["**Selected:** none", ""]

    out += ["**Reason:**", "", reason_for(path, detail), ""]
    gap = detail.get("gap")
    if isinstance(gap, Mapping):
        reopening_items = []
        for item in gap.get("reopens_with", []):
            label = gap_reopening_evidence_label(item)
            reopening_items.append(
                label if label != str(item) else f"`{item}`"
            )
        reopening = ", ".join(dict.fromkeys(reopening_items)) \
            or "none currently recorded"
        out += [
            f"**Gap:** `{gap.get('gate')}:{gap.get('kind')}` — "
            f"reopens with: {reopening}",
            "",
        ]

    rows = candidate_rows(path, detail, 8 if detailed else 5)
    if rows:
        if detailed:
            out += ["### Candidates", "", "| Target | Datatype | Confidence | Evidence | Score | Result |", "|---|---|---|---|---:|---|"]
        else:
            out += ["**Candidates:**", "", "| Target | Datatype | Confidence | Evidence | Result |", "|---|---|---|---|---|"]
        for candidate, result in rows:
            name = str(candidate.get("target") or "—").replace("|", "\\|")
            confidence_text = str(candidate.get("confidence") or "—")
            evidence_text = evidence(candidate).replace("|", "\\|")
            dtype = target_datatype(cda, str(candidate.get("target") or ""))
            if detailed:
                out.append(f"| `{name}` | `{dtype}` | {confidence_text} | {evidence_text} | {candidate.get('score', 0)} | {result} |")
            else:
                out.append(f"| `{name}` | `{dtype}` | {confidence_text} | {evidence_text} | {result} |")
        out.append("")

    if detailed and primary:
        target = cda.get("targets", {}).get(primary.get("target"), {})
        out += ["### Evidence chain", ""]
        concept = str(field.get("concept") or "")
        if concept:
            out.append(f"- Dataset concept: `{concept}`")
        out.append(f"- Bridge: `{evidence(primary)}`")
        if primary.get("via") and str(primary.get("via")) != concept:
            via_name = f" — {primary.get('via_name')}" if primary.get("via_name") else ""
            out.append(f"- Via concept: `{primary.get('via')}`{via_name}")
        if target.get("template_id"):
            out.append(
                f"- Template: `{target.get('template_name') or ''}` — `{target.get('template_id')}` "
                f"@ `{target.get('template_effective_date') or 'dynamic'}`"
            )
        if target.get("element_id") or target.get("element_name"):
            out.append(f"- Element: `{target.get('element_name') or ''}` — `{target.get('element_id') or ''}`")
        if target.get("path"):
            out.append(f"- CDA path: `{target.get('path')}`")
        if target.get("datatype"):
            out.append(f"- CDA datatype: `{target.get('datatype')}`")
        if primary.get("warnings"):
            out.append("- Warnings: " + "; ".join(str(item) for item in primary["warnings"]))
        out.append("")

    qualification = mapping_qualification(detail, primary) if primary else ""
    suggestions: list[str] = []
    if not primary:
        if detail.get("alternatives"):
            suggestions.append("Review the candidates and set the intended target in `cda-mapping.json`, or leave the field explicitly `null`.")
        elif detail.get("context"):
            suggestions.append("Use the contextual target to navigate the CDA structure, then choose an actual value-bearing element or leave the field unmapped.")
        else:
            suggestions.append("Find the intended CDA representation manually or leave the field explicitly `null`.")
    else:
        if detail.get("runtime_blocked"):
            if str(detail.get("runtime_blocked")).startswith(
                "REQUIRED_COMPANION("
            ):
                suggestions.append(
                    "Map the required companion for the same occurrence before enabling this candidate."
                )
            else:
                suggestions.append("Define an explicit merge/repetition rule before enabling this mapping.")
        if primary.get("confidence") == "WEAK":
            suggestions.append("Verify the selected target because the evidence is indirect.")
        if qualification.startswith("MULTIPLE("):
            suggestions.append("Compare the similarly ranked candidates before accepting the selection.")
        if primary.get("mapping") is not None:
            suggestions.append("Verify the generated transform and its value mapping before use.")
    if suggestions:
        out += ["**Suggested action:**", "", " ".join(suggestions), ""]
    return out


def render_mapping_analysis(
    model: Mapping[str, Any], cda: Mapping[str, Any], proposal: Mapping[str, Any],
    details: dict[str, dict[str, Any]], group_results: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    groups, model_fields = model.get("groups", {}), model.get("fields", {})
    fields, structures = proposal["fields"], proposal["structures"]
    all_details = {**group_results, **details}
    context = ReportContext(model, cda, proposal, details)







    all_coverage = Counter(mapping_coverage(detail) for detail in all_details.values())
    item_coverage = Counter(mapping_coverage(detail) for detail in details.values())
    group_coverage = Counter(mapping_coverage(detail) for detail in group_results.values())
    required_paths = [path for path, field in model_fields.items() if field.get("required")]
    required_coverage = Counter(mapping_coverage(details[path]) for path in required_paths)
    qualifications: Counter[str] = Counter()
    location_ambiguities = 0
    for detail in all_details.values():
        primary = detail.get("primary")
        if primary:
            qualifications[mapping_qualification(detail, primary)] += 1
            target = cda.get("targets", {}).get(primary["target"], {})
            if len(target.get("locations", [])) > 1:
                location_ambiguities += 1
        elif detail.get("context"):
            qualifications["PARTIAL"] += 1
        else:
            qualifications["NO_CDA"] += 1

    confidence = Counter(
        detail["primary"]["confidence"] if detail.get("primary") else "NO"
        for detail in all_details.values()
    )
    bridge = Counter(
        detail["primary"]["kind"] if detail.get("primary") else "NONE"
        for detail in all_details.values()
    )

    report_lines = [
        (_msg('markdown.cda_mapping')),
        "",
        _msg('markdown.this_is_the_working_report_for_completing_cda'),
        "",
        _msg('markdown.legend_yes_concrete_cda_evidence_partial_structural_context'),
        "",
    ]
    field_order = [path for path in model.get("order", []) if path in model_fields]
    if not field_order:
        field_order = sorted(model_fields)
    for path in field_order:
        report_lines.extend(field_section(context, path, detailed=False))

    detail_lines = [
        (_msg('markdown.cda_mapping_details')),
        "",
        _msg('markdown.this_is_the_evidence_appendix_for_cda_mapping'),
        "",
        f"{_msg('markdown.target_cda_template')} `{cda.get('document_template', {}).get('id')}` @ `{cda.get('document_template', {}).get('effective_date')}`",
        f"{_msg('markdown.transaction')} `{model.get('meta', {}).get('transaction_id')}` ({model.get('meta', {}).get('name') or ''})",
        "",
        "```text",
        f"{_msg('markdown.dataset_datapoints')}  {len(all_details):>4}",
        f"{_msg('markdown.cda_covered')}         {all_coverage['YES']:>4}",
        f"{_msg('markdown.partial')}             {all_coverage['PARTIAL']:>4}",
        f"{_msg('markdown.not_covered')}         {all_coverage['NO']:>4}",
        "",
        f"Items:      YES {item_coverage['YES']}, PARTIAL {item_coverage['PARTIAL']}, NO {item_coverage['NO']}",
        f"Groups:     YES {group_coverage['YES']}, PARTIAL {group_coverage['PARTIAL']}, NO {group_coverage['NO']}",
        f"{_msg('markdown.required_items')} YES {required_coverage['YES']}, PARTIAL {required_coverage['PARTIAL']}, NO {required_coverage['NO']}",
        "",
        f"Reachable templates:  {cda.get('stats', {}).get('reachable_templates', 0):>4}",
        f"{_msg('markdown.named_cda_targets')}    {cda.get('stats', {}).get('targets', 0):>4}",
        f"{_msg('markdown.renderable_targets')}   {cda.get('stats', {}).get('renderable_targets', 0):>4}",
        f"{_msg('markdown.evidence_linked_items')}{sum((bool(details[path].get('primary') or details[path].get('alternatives')) for path in model_fields)):>5}",
        f"{_msg('markdown.executable_proposal')}  {sum((value is not None for value in fields.values())):>4}",
        f"{_msg('markdown.unresolved_templates')} {len(cda.get('unresolved_templates', [])):>4}",
        "```",
        "",
        (_msg('markdown.summary_by_evidence')),
        "",
        (_msg('markdown.qualification')),
        "",
    ]
    for key in ("EXACT", "INDIRECT", "PARTIAL", "NO_CDA"):
        if qualifications[key]:
            detail_lines.append(f"- {key}: {qualifications[key]}")
    for key in sorted(k for k in qualifications if k.startswith("MULTIPLE(")):
        detail_lines.append(f"- {key}: {qualifications[key]}")
    if location_ambiguities:
        detail_lines.append(f"- LOCATION_AMBIGUITY: {location_ambiguities}")
    detail_lines += ["", (_msg('markdown.primary_evidence')), ""]
    for key, count in bridge.most_common():
        detail_lines.append(f"- {key}: {count}")
    detail_lines += ["", (_msg('markdown.confidence')), ""]
    for key in ("STRONG", "MEDIUM", "WEAK", "NO"):
        if confidence[key]:
            detail_lines.append(f"- {key}: {confidence[key]}")
    detail_lines.append("")

    if structures:
        detail_lines += [(_msg('markdown.executable_structural_rules')), ""]
        for name, rule in structures.items():
            detail_lines.append(f"- `{name}` — `{rule.get('type')}`")
            for item in rule.get("evidence", []):
                detail_lines.append(f"  - {item}")
        detail_lines.append("")

    if cda.get("unresolved_templates"):
        detail_lines += ["## Unresolved template references", ""]
        for unresolved in cda.get("unresolved_templates", []):
            relation = unresolved.get("relation") or "REF"
            template = unresolved.get("template") or ""
            flexibility = unresolved.get("flexibility") or "dynamic"
            detail_lines.append(f"- `{relation}` → `{template}` @ `{flexibility}`")
        detail_lines.append("")

    from .reports import render_accepted_cda_mappings_markdown
    detail_lines.extend(
        render_accepted_cda_mappings_markdown(model, cda, proposal)
        .rstrip()
        .splitlines()
    )
    detail_lines.append("")

    detail_lines += [(_msg('markdown.datapoint_analysis')), ""]
    for path in field_order:
        detail_lines.extend(field_section(context, path, detailed=True))

    if group_results:
        detail_lines += [(_msg('markdown.structural_group_context')), ""]
        group_order = [path for path in model.get("order", []) if path in group_results]
        if not group_order:
            group_order = sorted(group_results)
        for path in group_order:
            group = groups[path]
            detail = group_results[path]
            short = str(group.get("concept") or "").rsplit(".", 1)[-1]
            detail_lines += [
                f"## {group.get('name') or path}" + (f" [{short}]" if short else ""),
                "",
                f"`{path}`",
                "",
            ]
            if detail.get("primary"):
                primary = detail["primary"]
                detail_lines += [
                    f"**YES · {primary.get('confidence')} · {mapping_qualification(detail, primary)}**",
                    "",
                    f"→ `{primary.get('target')}`",
                    "",
                    f"Evidence: `{evidence(primary)}`",
                    "",
                ]
            elif detail.get("context"):
                detail_lines += ["**PARTIAL · CONTEXT**", "", f"→ `{detail['context'].get('target')}`", ""]
            else:
                detail_lines += ["**NO**", ""]

    return (
        "\n".join(report_lines) + "\n",
        "\n".join(detail_lines) + "\n",
    )

