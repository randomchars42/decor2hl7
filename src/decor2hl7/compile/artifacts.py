"""Assemble validated compiler inputs from a fetched transaction closure."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from ..retrieval.artifacts import (
    ArtifactRecord, artifact_problems, closure_records, form_paths,
    transaction_record,
)


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


def _required_form(record: ArtifactRecord, name: str) -> Path:
    form = record.get("forms", {}).get(name, {})
    path = form.get("path") if isinstance(form, dict) else None
    if not isinstance(path, Path):
        raise ValueError(
            f"{record.get('request_key', 'artifact')}: required {name} form is unavailable"
        )
    return path


def compiler_inputs(release_dir: Path, transaction_dir: Path) -> CompilerInputs:
    transaction = transaction_record(release_dir, transaction_dir)
    build = closure_records(release_dir, transaction_dir, "build")
    evidence = closure_records(
        release_dir, transaction_dir, "evidence", require_ready=False
    )
    problems = [problem for record in build for problem in artifact_problems(record)]
    if problems:
        raise ValueError("; ".join(problems))

    model_kinds = {"dataset", "concept", "valueset", "codesystem"}
    model_resources = form_paths(build, kinds=model_kinds, form="analysis")
    terminology_resources = form_paths(
        build, kinds={"valueset", "codesystem"}, form="analysis"
    )
    # Expansion is a first-class representation. The terminology compiler may
    # consume it alongside the extracted definition; duplicate paths collapse.
    for path in form_paths(build, kinds={"valueset", "codesystem"}, form="expansion"):
        if path not in terminology_resources:
            terminology_resources.append(path)
    templates = form_paths(build, kinds={"template"}, form="analysis")

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
    }

