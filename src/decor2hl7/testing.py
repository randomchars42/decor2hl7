"""Workspace-facing synthetic CDA mapping tests.

The generated fixture is deliberately plain CSV + JSON.  It exercises the
same ingestion, normalization, validation, binding, and CDA renderer used in
production, but writes neither production state nor transport output.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .compile.mapping import code_mapping_defaults
from .data import field_value, ingest
from .semantics import accepted_values
from .cda.model import ValueRepresentationKind
from .workspace import load_json, write_json


def json_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower() or "repeat"
    return text[:56]


def _source_name(chain: tuple[str, ...]) -> str:
    label = _slug(chain[-1].rsplit(".", 1)[-1])
    digest = hashlib.sha1("\0".join(chain).encode("utf-8")).hexdigest()[:7]
    return f"repeat-{label}-{digest}"


def _bounded_text(field: Mapping[str, Any], value: str) -> str:
    minimum = int(field.get("min_length") or 0)
    maximum = field.get("max_length")
    if len(value) < minimum:
        value += "x" * (minimum - len(value))
    if maximum is not None:
        value = value[: int(maximum)]
    return value


def synthetic_value(path: str, field: Mapping[str, Any], occurrence: int = 0) -> str:
    """Return a deterministic, parseable value for one model field."""
    kind = str(field.get("type") or "text")
    values = accepted_values(field)
    if values:
        keys = list(values)
        # Repeated terminology fields exercise more than the first member.
        return str(keys[occurrence % len(keys)])
    if kind == "datetime":
        precision = str(field.get("precision") or "")
        return "2026-01-15" if precision == "YMD" else "2026-01-15T10:00:00+01:00"
    if kind == "date":
        return "2026-01-15"
    if kind == "boolean":
        return "true" if occurrence == 0 else "false"
    if kind in {"integer", "count", "ordinal"}:
        low = field.get("min_value")
        high = field.get("max_value")
        # Repeating numeric fields should exercise distinct legal values.  In
        # particular this prevents the generated fixture from manufacturing
        # several occurrences of an order/sequence discriminator with the
        # same value while remaining entirely model- and bound-driven.
        number = (int(low) if low is not None else 1) + occurrence
        if high is not None:
            number = min(number, int(high))
        return str(number)
    if kind in {"quantity", "decimal", "duration"}:
        low = field.get("min_value")
        high = field.get("max_value")
        decimal_number = float(low) if low is not None else 1.0
        if high is not None:
            decimal_number = min(decimal_number, float(high))
        return str(
            int(decimal_number)
            if decimal_number.is_integer()
            else decimal_number
        )
    if kind == "code":
        # An unbound code remains visible as OTH during normalization.  This is
        # preferable to inventing terminology that is absent from the model.
        return "SYNTHETIC"
    prefix = "TEST-ID" if kind == "identifier" else "Synthetic"
    return _bounded_text(field, f"{prefix}-{hashlib.sha1(path.encode()).hexdigest()[:10]}")


def _write_csv(
    path: Path, headers: list[str], rows: Iterable[Mapping[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _mapping_roots(
    cda: Mapping[str, Any], cda_mapping: Mapping[str, Any]
) -> dict[str, str]:
    from .bindings import structure_rules
    from .transforms import cda_target_name, mapping_rules

    roots: dict[str, str] = {}
    names = {
        cda_target_name(rule)
        for selected in cda_mapping.get("fields", {}).values()
        for rule in mapping_rules(selected)
    }
    for structure in structure_rules(cda_mapping):
        if structure.get("target"):
            names.add(str(structure["target"]))
        for branch in structure.get("branches", []):
            if not isinstance(branch, Mapping):
                continue
            if branch.get("target"):
                names.add(cda_target_name(branch))
            constants = branch.get("constants", {})
            if isinstance(constants, Mapping):
                names.update(str(name) for name in constants)
    for name in names:
        target = cda.get("targets", {}).get(name, {})
        fixed = target.get("fixed", {})
        representation = target.get("value_representation", {})
        if (
            isinstance(representation, Mapping)
            and representation.get("kind") == ValueRepresentationKind.IDENTIFIER.value
            and not (
            isinstance(fixed, Mapping) and fixed.get("root")
            )
        ):
            roots[name] = "1.2.276.0.76.999.1"
    return roots


def synthetic_site(
    release: Mapping[str, Any], cda: Mapping[str, Any], cda_mapping: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "version": 1,
        "release": release.get("key"),
        "timezone": "Europe/Berlin",
        "organization": {
            "name": "decor2hl7 synthetic mapping test",
            "oid": "1.2.276.0.76.999.1",
        },
        "identifiers": {
            "document_root": "1.2.276.0.76.999.1.1",
            "patient_root": "1.2.276.0.76.999.1.2",
            "encounter_root": "1.2.276.0.76.999.1.3",
            "roots": _mapping_roots(cda, cda_mapping),
        },
        "null_flavor": {"missing_required": "NI", "unmapped_code": "OTH"},
        "input": {
            "join_column": "case_id",
            "case_source": "cases",
            "encoding": "utf-8-sig",
            "delimiter": ",",
            "decimal_separator": ".",
            "empty_is_null": True,
            "null_values": ["NULL", "NA", "N/A"],
            "sources": {},
        },
        "cda": {"values": {}},
        "state": {"rotate_days": 0},
        "transport": {"url": None, "timeout": 60, "headers": {}},
    }


def setup_fixture(
    test_dir: Path,
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    cda_mapping: Mapping[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Create deterministic CSV/config input for a selected compiled model."""
    managed = [test_dir / "input", test_dir / "config", test_dir / "expected.json"]
    if not force and any(path.exists() for path in managed):
        raise ValueError(f"test fixture already exists: {test_dir}; pass --force to replace generated input/config")

    input_root = test_dir / "input"
    config_root = test_dir / "config"
    out_root = test_dir / "out"
    input_root.mkdir(parents=True, exist_ok=True)
    config_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    fields = model.get("fields", {})
    by_chain: dict[tuple[str, ...], list[str]] = {}
    for path, field in fields.items():
        chain = tuple(str(item) for item in field.get("repeat_chain", []))
        by_chain.setdefault(chain, []).append(str(path))

    csv_fields: dict[str, str] = {}
    site = synthetic_site(release, cda, cda_mapping)

    scalar_paths = sorted(by_chain.pop((), []))
    case_headers = ["case_id", *scalar_paths]
    case_row = {"case_id": "TEST-1"}
    for path in scalar_paths:
        case_row[path] = synthetic_value(path, fields[path])
        csv_fields[path] = f"cases:{path}"
    _write_csv(input_root / "cases.csv", case_headers, [case_row])
    site["input"]["sources"]["cases"] = {
        "file": "cases.csv", "cardinality": "1:1"
    }

    repeat_sources: list[dict[str, Any]] = []
    for chain, paths in sorted(by_chain.items()):
        source = _source_name(chain)
        occurrence_columns = {
            repeat: f"occurrence_{index + 1}" for index, repeat in enumerate(chain)
        }
        headers = ["case_id", *occurrence_columns.values(), *sorted(paths)]
        # Two rows prove repetition; up to four rows also exercise small coded
        # domains such as diagnosis certainty V/A/Z/G without exploding large
        # terminology sets into unwieldy fixtures.
        row_count = max(
            [2, *[
                min(4, len(accepted_values(fields[path])))
                for path in paths if accepted_values(fields[path])
            ]]
        )
        rows: list[dict[str, str]] = []
        for occurrence in range(row_count):
            row = {"case_id": "TEST-1"}
            for index, column in enumerate(occurrence_columns.values()):
                row[column] = f"{index + 1}-{occurrence + 1}"
            for path in sorted(paths):
                row[path] = synthetic_value(path, fields[path], occurrence)
                csv_fields[path] = f"{source}:{path}"
            rows.append(row)
        _write_csv(input_root / f"{source}.csv", headers, rows)
        site["input"]["sources"][source] = {
            "file": f"{source}.csv",
            "cardinality": "1:n",
            "occurrence_keys": occurrence_columns,
        }
        repeat_sources.append({
            "source": source, "repeat_chain": list(chain), "rows": row_count
        })

    csv_mapping = {
        "version": 1,
        "join": {"column": "case_id"},
        "fields": {path: csv_fields[path] for path in fields},
    }
    codes_mapping = code_mapping_defaults(model)
    write_json(config_root / "csv-mapping.json", csv_mapping)
    write_json(config_root / "codes-mapping.json", codes_mapping)
    write_json(config_root / "site.json", site)

    mapped = sorted(
        path for path, selected in cda_mapping.get("fields", {}).items()
        if selected is not None
    )
    expected = {
        "version": 1,
        "release": release.get("key"),
        "transaction": {
            "key": transaction.get("key"),
            "id": transaction.get("id"),
            "effective_date": transaction.get("effective_date"),
        },
        "model_sha256": json_digest(model),
        "cda_sha256": json_digest(cda),
        "cda_mapping_sha256": json_digest(cda_mapping),
        "cases": ["TEST-1"],
        "expected_documents": 1,
        "generated_fields": sorted(fields),
        "mapped_fields": mapped,
        "unmapped_fields": sorted(set(fields) - set(mapped)),
        "repeat_sources": repeat_sources,
        "limitations": [
            "One generated document cannot cover mutually exclusive template branches.",
            "Unbound coded fields use SYNTHETIC and normalize to nullFlavor OTH.",
        ],
    }
    write_json(test_dir / "expected.json", expected)
    return expected


def _present(value: Any) -> bool:
    if isinstance(value, list):
        return any(_present(item) for item in value)
    return value is not None


def run_fixture(
    test_dir: Path,
    out_dir: Path,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    cda_mapping: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    """Run an isolated fixture and write machine- and human-readable results."""
    from . import cda as cda_runtime
    from . import validate
    from .bindings import build_assignments, structure_rules, target_default_values
    from .transforms import cda_target_name, mapping_rules

    config_dir = test_dir / "config"
    expected = load_json(test_dir / "expected.json")
    csv_mapping = load_json(config_dir / "csv-mapping.json")
    codes_mapping = load_json(config_dir / "codes-mapping.json")
    site = load_json(config_dir / "site.json")

    errors = validate.verify_compiled_cda(cda)
    errors.extend(validate.check_config(
        model, cda, csv_mapping, cda_mapping, codes_mapping, site
    ))
    records: list[dict[str, Any]] = []
    summary = {"records": 0, "errors": 0, "warnings": 0}
    if not errors:
        records = ingest(test_dir / "input", model, csv_mapping, codes_mapping, site)
        summary = validate.validate_records(records, model)

    out_dir.mkdir(parents=True, exist_ok=True)
    documents: list[str] = []
    render_warnings: dict[str, list[str]] = {}
    exercised: set[str] = set()
    assigned_targets: set[str] = set()
    if not errors and summary["errors"] == 0:
        for record in records:
            key = str(record.get("key") or "record")
            for path, field in model.get("fields", {}).items():
                if _present(field_value(record, path, field)):
                    exercised.add(path)
            try:
                assignments, _ = build_assignments(
                    record, model, cda, cda_mapping, site
                )
                assigned_targets.update(assignments)
                payload, warnings = cda_runtime.emit(
                    record, model, cda, cda_mapping, site, document_version=1
                )
                filename = f"{_slug(key)}.xml"
                (out_dir / filename).write_bytes(payload)
                documents.append(filename)
                render_warnings[key] = warnings
            except ValueError as error:
                errors.append(f"{key}: {error}")

    expected_count = int(expected.get("expected_documents") or 0)
    if len(documents) != expected_count:
        errors.append(
            f"expected {expected_count} CDA document(s), generated {len(documents)}"
        )
    missing_exercise = sorted(set(expected.get("mapped_fields", [])) - exercised)
    if missing_exercise:
        errors.append(
            f"{len(missing_exercise)} mapped field(s) were not exercised by generated input"
        )
    selected_target_names = {
        cda_target_name(rule)
        for selected in cda_mapping.get("fields", {}).values()
        for rule in mapping_rules(selected)
    }
    for structure in structure_rules(cda_mapping):
        if structure.get("target"):
            selected_target_names.add(str(structure["target"]))
        for branch in structure.get("branches", []):
            if not isinstance(branch, Mapping):
                continue
            if branch.get("target"):
                selected_target_names.add(cda_target_name(branch))
            constants = branch.get("constants", {})
            if isinstance(constants, Mapping):
                selected_target_names.update(str(name) for name in constants)
    configured_defaults = set(target_default_values(cda, cda_mapping))
    selected_target_names.update(configured_defaults)
    unassigned_targets = sorted(
        selected_target_names - assigned_targets - configured_defaults
    )
    test_warnings = [item for values in render_warnings.values() for item in values]
    if expected.get("cda_mapping_sha256") != json_digest(cda_mapping):
        test_warnings.append(
            "The CDA mapping changed after setup-test; this run exercised the current mapping. "
            "Rerun setup-test --force to refresh fixture provenance."
        )
    if unassigned_targets:
        test_warnings.append(
            f"{len(unassigned_targets)} selected target branch(es) were not assigned in this synthetic scenario: "
            + ", ".join(unassigned_targets)
        )

    result = {
        "version": 1,
        "status": "PASS" if not errors and summary["errors"] == 0 else "FAIL",
        "documents": documents,
        "input_summary": summary,
        "configuration_errors": errors,
        "render_warnings": render_warnings,
        "test_warnings": test_warnings,
        "coverage": {
            "generated_fields": len(expected.get("generated_fields", [])),
            "mapped_fields": len(expected.get("mapped_fields", [])),
            "exercised_fields": len(exercised),
            "mapped_fields_not_exercised": missing_exercise,
            "selected_targets": len(selected_target_names),
            "assigned_targets": len(assigned_targets),
            "configured_target_defaults": sorted(configured_defaults),
            "selected_targets_not_assigned": unassigned_targets,
        },
        "provenance": {
            "model_sha256": json_digest(model),
            "cda_sha256": json_digest(cda),
            "cda_mapping_sha256": json_digest(cda_mapping),
            "fixture_cda_mapping_sha256": expected.get("cda_mapping_sha256"),
        },
    }
    write_json(out_dir / "results.json", result)
    lines = [
        "# CDA mapping test", "", f"**{result['status']}**", "",
        f"- Generated documents: {len(documents)}/{expected_count}",
        f"- Model fields represented in CSV: {len(expected.get('generated_fields', []))}",
        f"- CDA-mapped fields: {len(expected.get('mapped_fields', []))}",
        f"- Fields exercised after normalization: {len(exercised)}", "",
    ]
    if errors:
        lines.extend(["## Errors", ""] + [f"- {item}" for item in errors] + [""])
    if test_warnings:
        lines.extend(["## Warnings", ""] + [f"- {item}" for item in test_warnings] + [""])
    lines.extend([
        "## Scope", "",
        "This test uses the production ingestion, normalization, validation, binding, and CDA rendering code.",
        "It does not write production state and never invokes transport.", "",
    ])
    (out_dir / "results.md").write_text("\n".join(lines), encoding="utf-8")
    return result, 0 if result["status"] == "PASS" else 1
