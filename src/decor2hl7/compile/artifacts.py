"""Assemble validated compiler inputs from a fetched transaction closure."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, TypedDict

from ..retrieval.artifacts import (
    ArtifactRecord, artifact_integrity_problems, artifact_unavailable_reasons,
    closure_records, form_paths, transaction_record,
)
from ..workspace import write_json


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
    unavailable_artifacts: list[dict[str, Any]]
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
    available = [
        record for record in build
        if not artifact_unavailable_reasons(record)
    ]

    model_kinds = {"dataset", "concept", "valueset", "codesystem"}
    model_resources = form_paths(available, kinds=model_kinds, form="analysis")
    terminology_resources = form_paths(
        available, kinds={"valueset", "codesystem"}, form="analysis"
    )
    # Expansion is a first-class representation. The terminology compiler may
    # consume it alongside the extracted definition; duplicate paths collapse.
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
        "transaction_analysis": _required_form(transaction, "analysis"),
        "model_resources": model_resources,
        "terminology_resources": terminology_resources,
        "templates": templates,
        "mapping_evidence": mapping_evidence,
        "unavailable_artifacts": unavailable,
        "warnings": [
            reason for artifact in unavailable
            for reason in artifact.get("reasons", [])
        ],
    }


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


def write_build_diagnostics(
    model_dir: Path,
    inputs: Mapping[str, Any],
    cda: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the exact omissions made by a tolerant compiler run."""
    unavailable = list(inputs.get("unavailable_artifacts", []))
    unresolved = list(cda.get("unresolved_templates", []))
    diagnostics = {
        "version": 1,
        "status": "degraded" if unavailable or unresolved else "complete",
        "policy": {
            "substitute_revisions": False,
            "missing_dependencies": "omit-and-report",
            "missing_document_template": "fatal",
            "identity_mismatch": "fatal",
        },
        "unavailable_artifacts": unavailable,
        "unresolved_templates": unresolved,
        "summary": {
            "unavailable_artifacts": len(unavailable),
            "unresolved_templates": len(unresolved),
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
    if unavailable:
        lines += [
            "## Unavailable artifacts",
            "",
            "| Artifact | Roles | Status | Build effect |",
            "|---|---|---|---|",
        ]
        for artifact in unavailable:
            lines.append(
                "| `{}` | {} | {} | {} |".format(
                    _cell(artifact.get("request_key")),
                    _cell(", ".join(artifact.get("roles", []))),
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
    if not unavailable and not unresolved:
        lines += ["No dependency gaps were detected.", ""]
    (model_dir / "build-diagnostics.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return diagnostics
