"""Authored scenario admission and input preparation.

Validation builds a complete plan without copying files or changing site values.
The fixture owner applies the plan only after admission succeeds.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .workspace import load_json


def case_filename_key(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower() or "repeat"
    return text[:56]


@dataclass(frozen=True)
class ScenarioSource:
    name: str
    relative: str
    path: Path
    specification: dict[str, Any]
    case_ids: list[str]
    rows: list[dict[str, str]]
    join_column: str
    fields: set[str]
    repeats: list[dict[str, Any]]


@dataclass(frozen=True)
class ScenarioInput:
    fields: dict[str, str | None]
    metadata: dict[str, Any]
    repeats: list[dict[str, Any]]
    files: list[tuple[str, Path]]
    input_config: dict[str, Any]
    cda_config: dict[str, Any]


def _scenario_file(root: Path, value: Any, label: str) -> tuple[Path, Path]:
    relative = Path(str(value or ""))
    if not str(value or "").strip() or relative.is_absolute():
        raise ValueError(f"scenario {label} must be a non-empty relative path")
    source = (root / relative).resolve()
    try:
        source.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"scenario {label} escapes its input directory") from error
    if not source.is_file():
        raise ValueError(f"scenario {label} does not exist: {source}")
    return source, relative


def _scenario_digest(
    manifest: Mapping[str, Any], files: Iterable[tuple[str, Path]],
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    for relative, path in sorted(files):
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _scenario_identity_errors(
    manifest: Mapping[str, Any],
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if manifest.get("release") != release.get("key"):
        errors.append(
            f"release {manifest.get('release')!r} does not match selected "
            f"{release.get('key')!r}"
        )
    configured = manifest.get("transaction", {})
    if not isinstance(configured, Mapping):
        return [*errors, "transaction identity must be an object"]
    for key, label in (
        ("key", "key"), ("id", "OID"), ("effective_date", "effective date"),
    ):
        if configured.get(key) != transaction.get(key):
            errors.append(
                f"transaction {label} {configured.get(key)!r} does not match "
                f"selected {transaction.get(key)!r}"
            )
    return errors


def _read_source(
    name: str, raw_spec: Any, scenario_input: Path,
    model_fields: Mapping[str, Any], model_groups: Mapping[str, Any],
    case_source: str, join_column: str, encoding: str, delimiter: str,
) -> ScenarioSource:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError(
            f"scenario source name {name!r} must contain only letters, "
            "digits, dot, underscore, or hyphen"
        )
    if not isinstance(raw_spec, Mapping):
        raise ValueError(f"scenario input.sources.{name} must be an object")
    source, relative = _scenario_file(
        scenario_input, raw_spec.get("file"), f"input.sources.{name}.file"
    )
    if source.suffix.lower() != ".csv":
        raise ValueError(f"scenario source {name!r} must be a CSV file")
    relative_text = relative.as_posix()

    cardinality = str(raw_spec.get("cardinality") or "1:1")
    if cardinality not in {"1:1", "1:n"}:
        raise ValueError(
            f"scenario input.sources.{name}.cardinality must be 1:1 or 1:n"
        )
    if name == case_source and cardinality != "1:1":
        raise ValueError("scenario case source must have cardinality 1:1")
    occurrence_keys = raw_spec.get("occurrence_keys", {})
    if occurrence_keys is not None and not isinstance(occurrence_keys, Mapping):
        raise ValueError(
            f"scenario input.sources.{name}.occurrence_keys must be an object"
        )
    if isinstance(occurrence_keys, Mapping):
        invalid_repeat_chains = [
            str(path) for path in occurrence_keys
            if not isinstance(model_groups.get(str(path)), Mapping)
            or not model_groups[str(path)].get("repeating")
        ]
        if invalid_repeat_chains:
            raise ValueError(
                f"scenario source {name!r} has unknown or non-repeating "
                "occurrence path(s): " + ", ".join(invalid_repeat_chains)
            )
    source_spec = dict(raw_spec)
    source_spec["file"] = relative_text

    with source.open(encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if len(headers) != len(set(headers)):
        raise ValueError(f"scenario source {name!r} has duplicate CSV columns")
    source_join = str(raw_spec.get("join_column") or join_column)
    if source_join not in headers:
        raise ValueError(
            f"scenario source {name!r} is missing join column {source_join!r}"
        )
    row_case_ids = [
        str(row.get(source_join) or "").strip() for row in rows
    ]
    if any(not case_id for case_id in row_case_ids):
        raise ValueError(
            f"scenario source {name!r} contains an empty case identifier"
        )
    if cardinality == "1:1" and len(row_case_ids) != len(set(row_case_ids)):
        raise ValueError(
            f"scenario 1:1 source {name!r} contains duplicate case identifiers"
        )
    metadata_columns = {source_join}
    if isinstance(occurrence_keys, Mapping):
        metadata_columns.update(str(value) for value in occurrence_keys.values())
    primary = raw_spec.get("primary", {})
    if isinstance(primary, Mapping) and primary.get("column"):
        metadata_columns.add(str(primary["column"]))
    unknown = sorted(set(headers) - metadata_columns - set(model_fields))
    if unknown:
        raise ValueError(
            f"scenario source {name!r} has unknown model column(s): "
            + ", ".join(unknown)
        )
    source_model_fields = set(headers) & set(model_fields)
    source_repeat_chain = (
        [str(path) for path in occurrence_keys]
        if isinstance(occurrence_keys, Mapping) else []
    )
    misplaced_fields = sorted(
        str(path) for path in source_model_fields
        if [
            str(item)
            for item in model_fields[str(path)].get("repeat_chain", [])
        ] != source_repeat_chain
    )
    if misplaced_fields:
        raise ValueError(
            f"scenario source {name!r} has field(s) outside its declared "
            "repeat chain: " + ", ".join(misplaced_fields)
        )
    repeat_sources: list[dict[str, Any]] = []
    if cardinality == "1:n":
        if not occurrence_keys:
            raise ValueError(
                f"scenario 1:n source {name!r} requires occurrence_keys"
            )
        occurrence_columns = [
            str(value) for value in occurrence_keys.values()
        ]
        if len(occurrence_columns) != len(set(occurrence_columns)):
            raise ValueError(
                f"scenario source {name!r} reuses an occurrence-key column"
            )
        missing_occurrence_columns = sorted(
            set(occurrence_columns) - set(headers)
        )
        if missing_occurrence_columns:
            raise ValueError(
                f"scenario source {name!r} is missing occurrence-key "
                "column(s): " + ", ".join(missing_occurrence_columns)
            )
        occurrence_identities = [
            (
                row_case_ids[index],
                *(str(row.get(column) or "").strip()
                  for column in occurrence_columns),
            )
            for index, row in enumerate(rows)
        ]
        if any(not all(identity) for identity in occurrence_identities):
            raise ValueError(
                f"scenario source {name!r} contains an empty occurrence key"
            )
        if len(occurrence_identities) != len(set(occurrence_identities)):
            raise ValueError(
                f"scenario source {name!r} contains duplicate occurrences"
            )
        repeat_sources.append({
            "source": name,
            "repeat_chains": sorted(
                str(key) for key in occurrence_keys
            ) if isinstance(occurrence_keys, Mapping) else [],
            "rows": len(rows),
        })

    return ScenarioSource(
        name, relative_text, source, source_spec, row_case_ids, rows,
        source_join, source_model_fields, repeat_sources,
    )


def _expected_cases(
    manifest: Mapping[str, Any], actual_cases: list[str],
    model_fields: Mapping[str, Any],
) -> dict[str, Any]:
    expected_cfg = manifest.get("expected", {})
    if not isinstance(expected_cfg, Mapping):
        raise ValueError("scenario expected must be an object")
    expected_cases = expected_cfg.get("cases")
    if not isinstance(expected_cases, list) or not all(
        isinstance(item, str) and item for item in expected_cases
    ):
        raise ValueError("scenario expected.cases must be a list of case identifiers")
    if actual_cases != expected_cases:
        raise ValueError(
            f"scenario case rows {actual_cases!r} do not match expected.cases "
            f"{expected_cases!r}"
        )
    expected_documents = expected_cfg.get("documents", len(expected_cases))
    if (
        not isinstance(expected_documents, int)
        or isinstance(expected_documents, bool)
        or expected_documents != len(expected_cases)
    ):
        raise ValueError(
            "scenario expected.documents must equal the number of expected cases"
        )
    case_fields = expected_cfg.get("case_fields", {})
    if not isinstance(case_fields, Mapping):
        raise ValueError("scenario expected.case_fields must be an object")
    unknown_case_expectations = sorted(set(case_fields) - set(actual_cases))
    if unknown_case_expectations:
        raise ValueError(
            "scenario expected.case_fields names unknown case(s): "
            + ", ".join(unknown_case_expectations)
        )
    for case, expectation in case_fields.items():
        if not isinstance(expectation, Mapping):
            raise ValueError(f"scenario case expectation {case!r} must be an object")
        for key in ("present", "absent"):
            paths = expectation.get(key, [])
            if not isinstance(paths, list) or not all(
                isinstance(item, str) and item in model_fields for item in paths
            ):
                raise ValueError(
                    f"scenario expected.case_fields.{case}.{key} must contain "
                    "known model paths"
                )
        present = {str(item) for item in expectation.get("present", [])}
        absent = {str(item) for item in expectation.get("absent", [])}
        if present & absent:
            raise ValueError(
                f"scenario expected.case_fields.{case} marks the same model "
                "path present and absent"
            )
        for key in ("present_templates", "absent_templates"):
            identities = expectation.get(key, [])
            if not isinstance(identities, list) or not all(
                isinstance(item, str) and item for item in identities
            ):
                raise ValueError(
                    f"scenario expected.case_fields.{case}.{key} must contain "
                    "non-empty template identifiers"
                )
        present_templates = {
            str(item) for item in expectation.get("present_templates", [])
        }
        absent_templates = {
            str(item) for item in expectation.get("absent_templates", [])
        }
        if present_templates & absent_templates:
            raise ValueError(
                f"scenario expected.case_fields.{case} marks the same CDA "
                "template present and absent"
            )
    return dict(expected_cfg)


def _scenario_policy(
    manifest: Mapping[str, Any], model_fields: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    site_cfg = manifest.get("site", {})
    if not isinstance(site_cfg, Mapping):
        raise ValueError("scenario site must be an object")
    scenario_cda = site_cfg.get("cda", {})
    if not isinstance(scenario_cda, Mapping):
        raise ValueError("scenario site.cda must be an object")
    for key in ("values", "fallback_if_active"):
        scenario_values = scenario_cda.get(key, {})
        if not isinstance(scenario_values, Mapping):
            raise ValueError(f"scenario site.cda.{key} must be an object")

    code_cfg = manifest.get("codes", {})
    if not isinstance(code_cfg, Mapping):
        raise ValueError("scenario codes must be an object")
    for path, translations in code_cfg.items():
        field = model_fields.get(str(path))
        if not isinstance(field, Mapping) or field.get("type") != "code":
            raise ValueError(
                f"scenario codes references non-coded model field {path!r}"
            )
        if not isinstance(translations, Mapping) or not all(
            isinstance(raw, str)
            and raw
            and (
                isinstance(canonical, str) and bool(canonical)
                or isinstance(canonical, Mapping)
                and isinstance(canonical.get("code"), str)
                and bool(canonical.get("code"))
                and isinstance(canonical.get("codeSystem"), str)
                and bool(canonical.get("codeSystem"))
                and all(
                    key in {"code", "codeSystem", "displayName"}
                    and isinstance(value, str)
                    for key, value in canonical.items()
                )
            )
            for raw, canonical in translations.items()
        ):
            raise ValueError(
                f"scenario codes.{path} must map non-empty strings to a "
                "non-empty canonical string or an explicit code object"
            )
    return dict(scenario_cda), {str(path): dict(value) for path, value in code_cfg.items()}


def read_scenario(
    scenario_dir: Path, release: Mapping[str, Any],
    transaction: Mapping[str, Any], model: Mapping[str, Any],
) -> ScenarioInput:
    manifest_path = scenario_dir / "scenario.json"
    if not manifest_path.is_file():
        raise ValueError(f"scenario manifest is missing: {manifest_path}")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ValueError("scenario.json must contain an object")
    if manifest.get("version") != 1:
        raise ValueError("scenario.json version must be 1")
    identity_errors = _scenario_identity_errors(manifest, release, transaction)
    if identity_errors:
        raise ValueError("scenario identity mismatch: " + "; ".join(identity_errors))

    input_cfg = manifest.get("input", {})
    if not isinstance(input_cfg, Mapping):
        raise ValueError("scenario input must be an object")
    sources = input_cfg.get("sources", {})
    if not isinstance(sources, Mapping) or not sources:
        raise ValueError("scenario input.sources must be a non-empty object")
    case_source = str(input_cfg.get("case_source") or "")
    if not case_source or case_source not in sources:
        raise ValueError("scenario input.case_source must name a configured source")
    join_column = str(input_cfg.get("join_column") or "case_id")
    encoding = str(input_cfg.get("encoding") or "utf-8-sig")
    delimiter = str(input_cfg.get("delimiter") or ",")
    if len(delimiter) != 1:
        raise ValueError("scenario input.delimiter must be one character")

    scenario_input = scenario_dir / "input"
    if not scenario_input.is_dir():
        raise ValueError(f"scenario input directory is missing: {scenario_input}")
    model_fields = model.get("fields", {})
    if not isinstance(model_fields, Mapping):
        raise ValueError("compiled model fields must be an object")
    model_groups = model.get("groups", {})
    if not isinstance(model_groups, Mapping):
        raise ValueError("compiled model groups must be an object")
    admitted = [
        _read_source(
            str(name), spec, scenario_input, model_fields, model_groups,
            case_source, join_column, encoding, delimiter,
        )
        for name, spec in sources.items()
    ]
    source_files: list[tuple[str, Path]] = []
    locations: dict[str, list[str]] = {}
    for source in admitted:
        if any(relative == source.relative for relative, _ in source_files):
            raise ValueError(
                f"scenario CSV file is configured more than once: {source.relative}"
            )
        source_files.append((source.relative, source.path))
        for path in source.fields:
            locations.setdefault(path, []).append(source.name)
    case_input = next(source for source in admitted if source.name == case_source)
    case_rows, case_join_column = case_input.rows, case_input.join_column
    source_case_ids = {source.name: source.case_ids for source in admitted}
    duplicate_fields = {
        path: names for path, names in locations.items() if len(names) != 1
    }
    if duplicate_fields:
        details = ", ".join(
            f"{path} ({', '.join(names)})"
            for path, names in sorted(duplicate_fields.items())
        )
        raise ValueError(f"scenario maps model fields from multiple sources: {details}")
    csv_fields: dict[str, str | None] = {
        str(path): (
            f"{locations[str(path)][0]}:{path}"
            if str(path) in locations else None
        )
        for path in model_fields
    }

    actual_cases = [
        str(row.get(case_join_column) or "").strip() for row in case_rows
    ]
    if not actual_cases or any(not key for key in actual_cases):
        raise ValueError("scenario case source must contain non-empty case identifiers")
    if len(set(actual_cases)) != len(actual_cases):
        raise ValueError("scenario case source contains duplicate case identifiers")
    slugs = [case_filename_key(case) for case in actual_cases]
    if len(set(slugs)) != len(slugs):
        raise ValueError(
            "scenario case identifiers collide when converted to CDA filenames"
        )
    known_cases = set(actual_cases)
    for name, case_ids in source_case_ids.items():
        unknown_cases = sorted(set(case_ids) - known_cases)
        if unknown_cases:
            raise ValueError(
                f"scenario source {name!r} references unknown case(s): "
                + ", ".join(unknown_cases)
            )
    expected_cfg = _expected_cases(manifest, actual_cases, model_fields)
    cda_config, codes = _scenario_policy(manifest, model_fields)
    input_config = {
        key: input_cfg[key]
        for key in (
            "encoding", "delimiter", "decimal_separator", "empty_is_null",
            "null_values", "unit_aliases",
        ) if key in input_cfg
    }
    input_config.update({
        "join_column": join_column,
        "case_source": case_source,
        "sources": {source.name: source.specification for source in admitted},
    })
    metadata = {
        "name": str(manifest.get("name") or scenario_dir.name),
        "source": str(scenario_dir.resolve()),
        "sha256": _scenario_digest(manifest, source_files),
        "expected": expected_cfg,
        "codes": codes,
    }
    return ScenarioInput(
        csv_fields, metadata,
        [repeat for source in admitted for repeat in source.repeats],
        source_files, input_config, cda_config,
    )


def prepare_scenario_input(
    scenario_dir: Path, input_root: Path, release: Mapping[str, Any],
    transaction: Mapping[str, Any], model: Mapping[str, Any], site: dict[str, Any],
) -> ScenarioInput:
    plan = read_scenario(scenario_dir, release, transaction, model)
    for relative, source in plan.files:
        target = input_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    site["input"].update(plan.input_config)
    for key in ("values", "fallback_if_active"):
        site["cda"][key] = dict(plan.cda_config.get(key, {}))
    return plan
