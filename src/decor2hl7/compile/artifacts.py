"""Assemble validated compiler inputs from a fetched transaction closure."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, TypedDict

from ..retrieval.artifacts import (
    ArtifactRecord, artifact_integrity_problems, artifact_unavailable_reasons,
    closure_records, form_paths, transaction_record,
)
from ..cda.extensions import CdaExtension, normalize_extensions
from ..workspace import load_json, write_json
from ..retrieval.xml import local


class CompilerInputs(TypedDict):
    transaction: ArtifactRecord
    build_artifacts: list[ArtifactRecord]
    evidence_artifacts: list[ArtifactRecord]
    transaction_source: Path
    transaction_analysis: Path
    model_resources: list[Path]
    terminology_resources: list[Path]
    templates: list[Path]
    mapping_evidence: list[Path]
    cda_extensions: list[CdaExtension]
    unavailable_artifacts: list[dict[str, Any]]
    crawl_degraded_artifacts: list[dict[str, Any]]
    warnings: list[str]


def _required_form(record: ArtifactRecord, name: str) -> Path:
    form = record.get("forms", {}).get(name, {})
    path = form.get("path") if isinstance(form, dict) else None
    if not isinstance(path, Path):
        raise ValueError(
            f"{record.get('request_key', 'artifact')}: required {name} form is unavailable"
        )
    return path


def _unavailable_artifact(record: ArtifactRecord) -> dict[str, Any]:
    requested = record.get("requested", {})
    resolved = record.get("resolved", {})
    return {
        "request_key": str(record.get("request_key") or "artifact"),
        "type": str(requested.get("type") or resolved.get("type") or ""),
        "id": str(requested.get("id") or resolved.get("id") or ""),
        "effective_date": str(requested.get("effective_date") or "dynamic"),
        "status": str(record.get("status") or "unknown"),
        "roles": list(record.get("roles", [])),
        "reasons": artifact_unavailable_reasons(record),
    }


def compiler_inputs(release_dir: Path, transaction_dir: Path) -> CompilerInputs:
    closure = load_json(transaction_dir / "closure.json")
    raw_extensions = closure.get("cda_extensions", [])
    if not isinstance(raw_extensions, list) or not all(
        isinstance(item, Mapping) for item in raw_extensions
    ):
        raise ValueError("closure CDA extensions must contain an array of objects")
    cda_extensions = normalize_extensions(raw_extensions)
    transaction = transaction_record(release_dir, transaction_dir)
    build = closure_records(release_dir, transaction_dir, "build")
    evidence = closure_records(release_dir, transaction_dir, "evidence")
    problems = [
        problem for record in build
        for problem in artifact_integrity_problems(record)
    ]
    if problems:
        raise ValueError("; ".join(problems))

    unavailable = [
        _unavailable_artifact(record) for record in build
        if artifact_unavailable_reasons(record)
    ]
    expansion_degraded = []
    for record in build:
        resolution = record.get("resolution", {})
        forms = record.get("forms", {})
        if not (
            isinstance(resolution, Mapping)
            and resolution.get("expansion_warning")
            and isinstance(forms, Mapping)
            and "expansion" not in forms
        ):
            continue
        resolved = record.get("resolved", {})
        expansion_degraded.append({
            "request_key": str(record.get("request_key") or ""),
            "type": "valueset",
            "id": str(resolved.get("id") or "")
            if isinstance(resolved, Mapping) else "",
            "effective_date": str(resolved.get("effective_date") or "dynamic")
            if isinstance(resolved, Mapping) else "dynamic",
            "status": "partial-expansion",
            "roles": list(record.get("roles") or []),
            "reasons": [str(resolution["expansion_warning"])],
        })
    available = [
        record for record in build
        if not artifact_unavailable_reasons(record)
    ]

    model_kinds = {"dataset", "concept", "valueset", "codesystem"}
    model_resources = form_paths(available, kinds=model_kinds, form="analysis")
    terminology_resources = form_paths(
        available, kinds={"valueset", "codesystem"}, form="analysis"
    )
    # ART-DECOR extracts can carry the exact terminology revision inline in a
    # dataset/concept container.  The model compiler already sees these paths;
    # the validator assembler must see the same frozen embedded resources.
    for path in model_resources:
        if path not in terminology_resources:
            terminology_resources.append(path)
    transaction_analysis = _required_form(transaction, "analysis")
    if transaction_analysis not in terminology_resources:
        terminology_resources.append(transaction_analysis)
    # A validated complete expansion is a first-class representation. The
    # terminology compiler consumes it alongside the extracted definition;
    # partial expansion-evidence is deliberately excluded.
    for path in form_paths(available, kinds={"valueset", "codesystem"}, form="expansion"):
        if path not in terminology_resources:
            terminology_resources.append(path)
    templates = form_paths(available, kinds={"template"}, form="analysis")

    mapping_evidence = [
        _required_form(transaction, "source"),
        _required_form(transaction, "analysis"),
    ]
    for form in ("source", "analysis"):
        for path in form_paths(evidence, form=form):
            if path not in mapping_evidence:
                mapping_evidence.append(path)
    project_evidence = release_dir / "project-evidence.xml"
    if project_evidence.is_file() and project_evidence not in mapping_evidence:
        mapping_evidence.append(project_evidence)

    return {
        "transaction": transaction,
        "build_artifacts": build,
        "evidence_artifacts": evidence,
        "transaction_source": _required_form(transaction, "source"),
        "transaction_analysis": transaction_analysis,
        "model_resources": model_resources,
        "terminology_resources": terminology_resources,
        "templates": templates,
        "mapping_evidence": mapping_evidence,
        "cda_extensions": cda_extensions,
        "unavailable_artifacts": unavailable,
        "crawl_degraded_artifacts": unavailable + expansion_degraded,
        "warnings": [
            reason for artifact in unavailable
            for reason in artifact.get("reasons", [])
        ],
    }


def configured_source_rules(inputs: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return configured retrieval rules whose successful artifacts are inputs."""
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    records = list(inputs.get("build_artifacts", [])) + list(
        inputs.get("evidence_artifacts", [])
    )
    for record in records:
        if not isinstance(record, Mapping) or record.get("status") != "ok":
            continue
        resolution = record.get("resolution", {})
        if not isinstance(resolution, Mapping):
            continue
        rule = ""
        if (
            resolution.get("source_hint_origin") == "configured"
            and resolution.get("identity_corrected")
        ):
            rule = "configured identity alias"
        elif resolution.get("owner_source") == "configured-oid-owner":
            rule = "configured OID-owner override"
        elif resolution.get("source_hint_origin") == "configured":
            rule = "configured artifact source hint"
        if not rule:
            continue
        key = (str(record.get("request_key") or ""), rule)
        if key in seen:
            continue
        seen.add(key)
        requested = record.get("requested", {})
        resolved = record.get("resolved", {})
        result.append({
            "rule": rule,
            "request_key": key[0],
            "requested_id": (
                str(requested.get("id") or "")
                if isinstance(requested, Mapping) else ""
            ),
            "resolved_id": (
                str(resolved.get("id") or "")
                if isinstance(resolved, Mapping) else ""
            ),
        })
    return result


def _effect(artifact: Mapping[str, Any]) -> str:
    kind = str(artifact.get("type") or "artifact")
    if kind in {"dataset", "concept"}:
        return "Dataset containment or descriptive enrichment may be incomplete."
    if kind in {"valueset", "codesystem"}:
        return "Affected formal code membership or expansion remains incomplete."
    if kind == "template":
        return "Affected CDA constraints and writable targets are omitted."
    return "Evidence from this dependency is unavailable."


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


_VALUE_SET_MESSAGE = re.compile(r"\bvalue set ([0-9][0-9.]*):")


def selected_closure_templates(cda: Mapping[str, Any]) -> set[str]:
    """Return the templates instantiated at a location of the selected document.

    A compiled CDA model carries every template the assembled specification
    makes reachable, including branches of referenced projects that the selected
    document never instantiates.  Only a template with at least one located
    target contributes constraints to the selected document, so only that set
    defines the closure a generated validator rule can affect.
    """
    result: set[str] = set()
    targets = cda.get("targets", {})
    for target in targets.values() if isinstance(targets, Mapping) else ():
        if not isinstance(target, Mapping) or not target.get("locations"):
            continue
        identifier = str(target.get("template_id") or "")
        if identifier:
            result.add(identifier)
    return result


def selected_closure_template_revisions(
    cda: Mapping[str, Any],
) -> set[tuple[str, str]]:
    """Return exact template revisions instantiated in the selected document."""
    result: set[tuple[str, str]] = set()
    targets = cda.get("targets", {})
    for target in targets.values() if isinstance(targets, Mapping) else ():
        if not isinstance(target, Mapping) or not target.get("locations"):
            continue
        identifier = str(target.get("template_id") or "")
        effective = str(target.get("template_effective_date") or "")
        if identifier and effective:
            result.add((identifier, effective))
    return result


def _selected_value_sets(model: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    fields = model.get("fields", {})
    for field in fields.values() if isinstance(fields, Mapping) else ():
        if not isinstance(field, Mapping):
            continue
        formal = field.get("formal_terminology", {})
        if not isinstance(formal, Mapping) or formal.get("status") not in {
            "bound", "unresolved",
        }:
            continue
        references = formal.get("value_sets", [])
        for reference in references if isinstance(references, list) else ():
            if isinstance(reference, Mapping) and reference.get("id"):
                result.add(str(reference["id"]))
            elif isinstance(reference, str) and reference:
                result.add(reference)
    return result


def _validator_value_sets(model_dir: Path) -> set[str]:
    """Return value sets a generated rule inside the selected closure needs.

    The validator assembler classifies every generation message against the
    selected document closure (`DEC-019`).  A message emitted for a template the
    selected document never instantiates reports an upstream gap in a branch
    this build does not use, and must not degrade the build status.
    """
    path = model_dir / "conformance-validation" / "validator-manifest.json"
    if not path.is_file():
        return set()
    manifest = load_json(path)
    scopes = manifest.get("generation_message_scopes")
    result: set[str] = set()
    if isinstance(scopes, list):
        for scope in scopes:
            if not isinstance(scope, Mapping) or not scope.get("in_selected_closure"):
                continue
            value_sets = scope.get("value_sets", [])
            for identifier in value_sets if isinstance(value_sets, list) else ():
                if identifier:
                    result.add(str(identifier))
        return result
    messages = manifest.get("generation_messages", [])
    for message in messages if isinstance(messages, list) else ():
        result.update(_VALUE_SET_MESSAGE.findall(str(message)))
    return result


def _terminology_dependencies(
    inputs: Mapping[str, Any],
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    value_set_refs: dict[str, set[str]] = {}
    code_system_refs: dict[str, set[str]] = {}
    for path in inputs.get("terminology_resources", []):
        if not isinstance(path, Path) or not path.is_file():
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        for value_set in root.iter():
            if local(value_set.tag) != "valueSet" or not value_set.get("id"):
                continue
            ident = str(value_set.get("id"))
            values = value_set_refs.setdefault(ident, set())
            systems = code_system_refs.setdefault(ident, set())
            for node in value_set.iter():
                if local(node.tag) != "include":
                    continue
                if node.get("ref"):
                    values.add(str(node.get("ref")))
                if node.get("codeSystem"):
                    systems.add(str(node.get("codeSystem")))
    expanded: set[str] = set()
    for record in inputs.get("build_artifacts", []):
        if not isinstance(record, Mapping):
            continue
        resolved = record.get("resolved", {})
        forms = record.get("forms", {})
        if (
            isinstance(resolved, Mapping)
            and resolved.get("type") == "valueset"
            and resolved.get("id")
            and isinstance(forms, Mapping)
            and "expansion" in forms
        ):
            expanded.add(str(resolved["id"]))
    return value_set_refs, code_system_refs, expanded


def _build_degraded_artifacts(
    model_dir: Path,
    inputs: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
) -> list[dict[str, Any]]:
    active_value_sets = _selected_value_sets(model) | _validator_value_sets(model_dir)
    value_set_refs, code_system_refs, expanded = _terminology_dependencies(inputs)
    active_code_systems: set[str] = set()
    queue = list(active_value_sets)
    visited: set[str] = set()
    while queue:
        ident = queue.pop()
        if ident in visited:
            continue
        visited.add(ident)
        if ident in expanded:
            continue
        active_code_systems.update(code_system_refs.get(ident, set()))
        queue.extend(value_set_refs.get(ident, set()) - visited)

    unresolved_templates = {
        str(item.get("template") or "")
        for item in cda.get("unresolved_templates", [])
        if isinstance(item, Mapping) and item.get("template")
    }
    result: list[dict[str, Any]] = []
    matched_templates: set[str] = set()
    for record in inputs.get("build_artifacts", []):
        if not isinstance(record, Mapping):
            continue
        resolved = record.get("resolved", {})
        resolution = record.get("resolution", {})
        forms = record.get("forms", {})
        if not (
            isinstance(resolved, Mapping)
            and resolved.get("type") == "valueset"
            and str(resolved.get("id") or "") in active_value_sets
            and isinstance(resolution, Mapping)
            and resolution.get("expansion_warning")
            and isinstance(forms, Mapping)
            and "expansion" not in forms
        ):
            continue
        result.append({
            "request_key": str(record.get("request_key") or ""),
            "type": "valueset",
            "id": str(resolved.get("id") or ""),
            "effective_date": str(resolved.get("effective_date") or "dynamic"),
            "status": "partial-expansion",
            "roles": list(record.get("roles") or []),
            "reasons": [str(resolution["expansion_warning"])],
            "consulted_by": "selected-field-or-validator-value-set",
        })
    for artifact in inputs.get("unavailable_artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        kind = str(artifact.get("type") or "")
        ident = str(artifact.get("id") or "")
        consulted_by = ""
        if kind == "valueset" and ident in active_value_sets:
            consulted_by = "selected-field-or-validator-value-set"
        elif kind == "codesystem" and ident in active_code_systems:
            consulted_by = "selected-value-set-expansion"
        elif kind == "template" and ident in unresolved_templates:
            consulted_by = "cda-template-compiler"
            matched_templates.add(ident)
        if consulted_by:
            result.append({**dict(artifact), "consulted_by": consulted_by})

    for item in cda.get("unresolved_templates", []):
        if not isinstance(item, Mapping):
            continue
        ident = str(item.get("template") or "")
        if not ident or ident in matched_templates:
            continue
        effective = str(item.get("flexibility") or "dynamic")
        result.append({
            "request_key": f"template:{ident}"
            + (f"@{effective}" if effective != "dynamic" else ""),
            "type": "template",
            "id": ident,
            "effective_date": effective,
            "status": "unresolved",
            "roles": ["structure"],
            "reasons": ["CDA template compiler could not resolve this relation"],
            "consulted_by": "cda-template-compiler",
        })
    return result


def write_build_diagnostics(
    model_dir: Path,
    inputs: Mapping[str, Any],
    cda: Mapping[str, Any],
    model: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the exact omissions made by a tolerant compiler run."""
    unavailable = list(inputs.get("unavailable_artifacts", []))
    crawl_degraded = list(inputs.get("crawl_degraded_artifacts", unavailable))
    unresolved = list(cda.get("unresolved_templates", []))
    constraint_diagnostics = list(cda.get("constraint_diagnostics", []))
    build_degraded = _build_degraded_artifacts(
        model_dir, inputs, model or {}, cda
    )
    diagnostics = {
        "version": 2,
        "status": "degraded" if build_degraded else "complete",
        "policy": {
            "substitute_revisions": False,
            "missing_dependencies": "omit-and-report",
            "missing_document_template": "fatal",
            "identity_mismatch": "fatal",
            "spec_constraint_weakening": "explicit-child-constraint-and-warning",
        },
        "crawl_degraded": crawl_degraded,
        "build_degraded": build_degraded,
        # Compatibility name retained for consumers of format 1.
        "unavailable_artifacts": unavailable,
        "unresolved_templates": unresolved,
        "constraint_diagnostics": constraint_diagnostics,
        "summary": {
            "unavailable_artifacts": len(unavailable),
            "crawl_degraded": len(crawl_degraded),
            "build_degraded": len(build_degraded),
            "unresolved_templates": len(unresolved),
            "constraint_diagnostics": len(constraint_diagnostics),
        },
    }
    write_json(model_dir / "build-diagnostics.json", diagnostics)

    lines = [
        "# Build diagnostics",
        "",
        f"**Status:** {str(diagnostics['status']).upper()}",
        "",
        "The compiler used only downloaded artifacts with their exact requested "
        "identity. It did not replace a missing revision with another revision.",
        "",
    ]
    if crawl_degraded:
        lines += [
            "## Degraded artifacts (crawl)",
            "",
            "| Artifact | Roles | Status | Build effect |",
            "|---|---|---|---|",
        ]
        for artifact in crawl_degraded:
            lines.append(
                "| `{}` | {} | {} | {} |".format(
                    _cell(artifact.get("request_key")),
                    _cell(", ".join(artifact.get("roles", []))),
                    _cell(artifact.get("status")),
                    _cell(_effect(artifact)),
                )
            )
        lines.append("")
    if build_degraded:
        lines += [
            "## Degraded artifacts affecting this build",
            "",
            "| Artifact | Consulted by | Status | Build effect |",
            "|---|---|---|---|",
        ]
        for artifact in build_degraded:
            lines.append(
                "| `{}` | {} | {} | {} |".format(
                    _cell(artifact.get("request_key")),
                    _cell(artifact.get("consulted_by")),
                    _cell(artifact.get("status")),
                    _cell(_effect(artifact)),
                )
            )
        lines.append("")
    if unresolved:
        lines += [
            "## Unresolved CDA template references",
            "",
            "| Relation | Template | Requested revision |",
            "|---|---|---|",
        ]
        for row in unresolved:
            lines.append(
                "| {} | `{}` | `{}` |".format(
                    _cell(row.get("relation")),
                    _cell(row.get("template")),
                    _cell(row.get("flexibility") or "dynamic"),
                )
            )
        lines.append("")
    if constraint_diagnostics:
        lines += [
            "## CDA constraint diagnostics",
            "",
            "| Severity | Code | Template path | Detail |",
            "|---|---|---|---|",
        ]
        for diagnostic in constraint_diagnostics:
            lines.append(
                "| {} | `{}` | `{}` | {} |".format(
                    _cell(diagnostic.get("severity") or "warning"),
                    _cell(diagnostic.get("code")),
                    _cell(diagnostic.get("path")),
                    _cell(diagnostic.get("message")),
                )
            )
        lines.append("")
    if not crawl_degraded and not unresolved:
        lines += ["No dependency gaps were detected.", ""]
    (model_dir / "build-diagnostics.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return diagnostics
