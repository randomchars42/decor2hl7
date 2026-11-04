"""Workspace-facing synthetic and authored CDA mapping tests.

The generated fixture is deliberately plain CSV + JSON.  It exercises the
same ingestion, normalization, validation, binding, and CDA renderer used in
production, but writes neither production state nor transport output.
"""

from __future__ import annotations

from .hashing import json_digest as json_digest

import csv
import hashlib
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping

from .compile.site import code_mapping_defaults
from .data import field_value, ingest
from .domain import accepted_values
from .i18n import message as _msg, localized
from .cda.model import ValueRepresentationKind
from .cda.narrative import narrative_blocks, narrative_source_rules
from .workspace import load_json, write_json


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
        # An unbound code remains target-neutral during normalization. A
        # reviewed CDA transform may later choose a target representation.
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


def _replace_managed_fixture(
    test_dir: Path, managed: Iterable[Path], *, force: bool,
) -> None:
    existing = [path for path in managed if path.exists()]
    if existing and not force:
        raise ValueError(
            f"test fixture already exists: {test_dir}; pass --force to replace "
            "fixture input/config"
        )
    if not force:
        return
    resolved = test_dir.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise ValueError(f"refusing to replace an unsafe test fixture path: {resolved}")
    expected_path = test_dir / "expected.json"
    generated_directories = [
        path for path in existing if path.name in {"input", "config"}
    ]
    if generated_directories:
        try:
            contract = load_json(expected_path)
        except (OSError, ValueError, json.JSONDecodeError):
            contract = {}
        if not isinstance(contract, Mapping):
            contract = {}
        if not (
            contract.get("version") == 1
            and isinstance(contract.get("transaction"), Mapping)
            and isinstance(contract.get("generated_fields"), list)
        ):
            raise ValueError(
                f"refusing to replace input/config without a decor2hl7 "
                f"fixture contract at {expected_path}"
            )
    for path in existing:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


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


def _copy_scenario_input(
    scenario_dir: Path,
    input_root: Path,
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
    model: Mapping[str, Any],
    site: dict[str, Any],
) -> tuple[dict[str, str | None], dict[str, Any], list[dict[str, Any]]]:
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
    locations: dict[str, list[str]] = {}
    source_files: list[tuple[str, Path]] = []
    copied_sources: dict[str, Any] = {}
    repeat_sources: list[dict[str, Any]] = []
    source_case_ids: dict[str, list[str]] = {}
    case_rows: list[dict[str, str]] = []
    case_join_column = join_column

    for raw_name, raw_spec in sources.items():
        name = str(raw_name)
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
        if any(item[0] == relative_text for item in source_files):
            raise ValueError(f"scenario CSV file is configured more than once: {relative_text}")
        source_files.append((relative_text, source))
        target = input_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

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
        copied_sources[name] = source_spec

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
        source_case_ids[name] = row_case_ids
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
        for path in source_model_fields:
            locations.setdefault(str(path), []).append(name)
        if name == case_source:
            case_rows = rows
            case_join_column = source_join
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
    slugs = [_slug(case) for case in actual_cases]
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
        site["cda"][key] = dict(scenario_values)

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

    site_input = site["input"]
    for key in (
        "encoding", "delimiter", "decimal_separator", "empty_is_null",
        "null_values", "unit_aliases",
    ):
        if key in input_cfg:
            site_input[key] = input_cfg[key]
    site_input["join_column"] = join_column
    site_input["case_source"] = case_source
    site_input["sources"] = copied_sources
    scenario_meta = {
        "name": str(manifest.get("name") or scenario_dir.name),
        "source": str(scenario_dir.resolve()),
        "sha256": _scenario_digest(manifest, source_files),
        "expected": dict(expected_cfg),
        "codes": {
            str(path): dict(translations)
            for path, translations in code_cfg.items()
        },
    }
    return csv_fields, scenario_meta, repeat_sources


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
        "null_flavor": {"missing_required": "NI"},
        "input": {
            "join_column": "case_id",
            "case_source": "cases",
            "encoding": "utf-8-sig",
            "delimiter": ",",
            "decimal_separator": ".",
            "empty_is_null": True,
            "null_values": ["NULL", "NA", "N/A"],
            "unit_aliases": {},
            "sources": {},
        },
        "cda": {"values": {}, "fallback_if_active": {}},
        "transport": {
            "adapter": "http-post", "url": None, "timeout": 60, "headers": {},
        },
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
    scenario_dir: Path | None = None,
) -> dict[str, Any]:
    """Create generated or authored CSV/config input for a compiled model."""
    managed = [test_dir / "input", test_dir / "config", test_dir / "expected.json"]
    input_root = test_dir / "input"
    config_root = test_dir / "config"
    out_root = test_dir / "out"
    fields = model.get("fields", {})
    site = synthetic_site(release, cda, cda_mapping)
    scenario_meta: dict[str, Any] | None = None
    repeat_sources: list[dict[str, Any]] = []
    if scenario_dir is not None:
        # Validate and stage the complete authored source before replacing an
        # existing fixture, so a malformed new scenario cannot destroy the
        # last usable one even when --force was explicit.
        with tempfile.TemporaryDirectory(prefix="decor2hl7-scenario-") as tmp:
            staged_input = Path(tmp) / "input"
            csv_fields, scenario_meta, repeat_sources = _copy_scenario_input(
                scenario_dir.resolve(), staged_input,
                release, transaction, model, site,
            )
            _replace_managed_fixture(test_dir, managed, force=force)
            input_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged_input, input_root, dirs_exist_ok=True)
        expected_cfg = scenario_meta["expected"]
        expected_cases = list(expected_cfg["cases"])
        expected_documents = int(
            expected_cfg.get("documents", len(expected_cases))
        )
    else:
        _replace_managed_fixture(test_dir, managed, force=force)
        input_root.mkdir(parents=True, exist_ok=True)
        by_chain: dict[tuple[str, ...], list[str]] = {}
        for path, field in fields.items():
            chain = tuple(str(item) for item in field.get("repeat_chain", []))
            by_chain.setdefault(chain, []).append(str(path))

        generated_csv_fields: dict[str, str | None] = {}
        scalar_paths = sorted(by_chain.pop((), []))
        case_headers = ["case_id", *scalar_paths]
        case_row = {"case_id": "TEST-1"}
        for path in scalar_paths:
            case_row[path] = synthetic_value(path, fields[path])
            generated_csv_fields[path] = f"cases:{path}"
        _write_csv(input_root / "cases.csv", case_headers, [case_row])
        site["input"]["sources"]["cases"] = {
            "file": "cases.csv", "cardinality": "1:1"
        }

        for chain, paths in sorted(by_chain.items()):
            source = _source_name(chain)
            occurrence_columns = {
                repeat: f"occurrence_{index + 1}"
                for index, repeat in enumerate(chain)
            }
            headers = ["case_id", *occurrence_columns.values(), *sorted(paths)]
            # Two rows prove repetition; up to four rows also exercise small
            # coded domains such as diagnosis certainty V/A/Z/G without
            # exploding large terminology sets into unwieldy fixtures.
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
                    generated_csv_fields[path] = f"{source}:{path}"
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
        csv_fields = generated_csv_fields
        expected_cases = ["TEST-1"]
        expected_documents = 1

    config_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)
    csv_mapping = {
        "version": 1,
        "join": {"column": str(site["input"].get("join_column") or "case_id")},
        "fields": {path: csv_fields.get(path) for path in fields},
    }
    codes_mapping = code_mapping_defaults(model)
    if scenario_meta is not None:
        codes_mapping.setdefault("fields", {}).update(scenario_meta["codes"])
    write_json(config_root / "csv-mapping.json", csv_mapping)
    write_json(config_root / "codes-mapping.json", codes_mapping)
    write_json(config_root / "site.json", site)

    all_mapped = sorted({
        path for path, selected in cda_mapping.get("fields", {}).items()
        if selected is not None
    } | set(narrative_source_rules(cda_mapping)))
    coverage = (
        scenario_meta["expected"].get("coverage", "all-mapped")
        if scenario_meta is not None else "all-mapped"
    )
    if coverage == "all-mapped":
        mapped = all_mapped
    elif (
        isinstance(coverage, Mapping)
        and isinstance(coverage.get("all_mapped_except"), list)
    ):
        excluded = [str(path) for path in coverage["all_mapped_except"]]
        unknown = sorted(set(excluded) - set(all_mapped))
        if unknown:
            raise ValueError(
                "scenario expected.coverage.all_mapped_except contains "
                "unselected model path(s): " + ", ".join(unknown)
            )
        mapped = sorted(set(all_mapped) - set(excluded))
    elif isinstance(coverage, list) and all(
        isinstance(path, str) and path in all_mapped for path in coverage
    ):
        mapped = sorted(coverage)
    else:
        raise ValueError(
            "scenario expected.coverage must be 'all-mapped', an "
            "all_mapped_except object, or a list of selected model paths"
        )
    generated_fields = sorted(
        path for path, locator in csv_fields.items() if locator is not None
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
        "cases": expected_cases,
        "expected_documents": expected_documents,
        "generated_fields": generated_fields,
        "mapped_fields": mapped,
        "unmapped_fields": sorted(set(fields) - set(all_mapped)),
        "repeat_sources": repeat_sources,
        "limitations": (
            list(scenario_meta["expected"].get("limitations", []))
            if scenario_meta is not None else [
                "One generated document cannot cover mutually exclusive template branches.",
                "Unbound coded fields use target-neutral SYNTHETIC wording.",
            ]
        ),
    }
    if scenario_meta is not None:
        expected["scenario"] = {
            key: scenario_meta[key] for key in ("name", "source", "sha256")
        }
        expected["case_fields"] = dict(
            scenario_meta["expected"].get("case_fields", {})
        )
    write_json(test_dir / "expected.json", expected)
    return expected


def _present(value: Any) -> bool:
    if isinstance(value, list):
        return any(_present(item) for item in value)
    return value is not None


def _case_field_expectation_errors(
    record: Mapping[str, Any],
    model: Mapping[str, Any],
    expectation: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    key = str(record.get("key") or "record")
    for path in expectation.get("present", []):
        field = model.get("fields", {}).get(str(path), {})
        if not _present(field_value(record, str(path), field)):
            errors.append(f"{key}: expected model field {path} to be present")
    for path in expectation.get("absent", []):
        field = model.get("fields", {}).get(str(path), {})
        if _present(field_value(record, str(path), field)):
            errors.append(f"{key}: expected model field {path} to be absent")
    return errors


def _case_template_expectation_errors(
    key: str, payload: bytes, expectation: Mapping[str, Any],
) -> list[str]:
    root = ET.fromstring(payload)
    template_ids = {
        str(node.get("root"))
        for node in root.iter("{urn:hl7-org:v3}templateId")
        if node.get("root")
    }
    errors: list[str] = []
    for identity in expectation.get("present_templates", []):
        if str(identity) not in template_ids:
            errors.append(f"{key}: expected CDA template {identity} to be present")
    for identity in expectation.get("absent_templates", []):
        if str(identity) in template_ids:
            errors.append(f"{key}: expected CDA template {identity} to be absent")
    return errors


@localized
def run_fixture(
    test_dir: Path,
    out_dir: Path,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    cda_mapping: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> tuple[dict[str, Any], int]:
    """Run an isolated fixture and write machine- and human-readable results."""
    from .cda.render import emit
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
        actual_cases = [str(record.get("key") or "") for record in records]
        expected_cases = [str(item) for item in expected.get("cases", [])]
        if actual_cases != expected_cases:
            errors.append(
                f"expected cases {expected_cases!r}, ingested {actual_cases!r}"
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    documents: list[str] = []
    render_warnings: dict[str, list[str]] = {}
    exercised: set[str] = set()
    assigned_targets: set[str] = set()
    if not errors and summary["errors"] == 0:
        for record in records:
            key = str(record.get("key") or "record")
            raw_expectation = expected.get("case_fields", {}).get(key, {})
            expectation = (
                raw_expectation if isinstance(raw_expectation, Mapping) else {}
            )
            errors.extend(_case_field_expectation_errors(
                record, model, expectation
            ))
            for path, field in model.get("fields", {}).items():
                if _present(field_value(record, path, field)):
                    exercised.add(path)
            try:
                assignments, _ = build_assignments(
                    record, model, cda, cda_mapping, site
                )
                assigned_targets.update(assignments)
                payload, warnings = emit(
                    record, model, cda, cda_mapping, site, document_version=1
                )
                errors.extend(_case_template_expectation_errors(
                    key, payload, expectation
                ))
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
            f"{len(missing_exercise)} mapped field(s) were not exercised by fixture input"
        )
    selected_target_names = {
        cda_target_name(rule)
        for selected in cda_mapping.get("fields", {}).values()
        for rule in mapping_rules(selected)
    }
    selected_target_names.update(
        str(block.get("section_target") or "")
        for block in narrative_blocks(cda_mapping)
        if block.get("section_target")
    )
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
        fixture_kind = "authored scenario set" if expected.get("scenario") else "synthetic scenario"
        test_warnings.append(
            f"{len(unassigned_targets)} selected target branch(es) were not assigned in this "
            f"{fixture_kind}: "
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
    if isinstance(expected.get("scenario"), Mapping):
        result["scenario"] = dict(expected["scenario"])
    write_json(out_dir / "results.json", result)
    lines = [(_msg('markdown.cda_mapping_test')), "", f"**{result['status']}**", ""]
    if isinstance(expected.get("scenario"), Mapping):
        lines.append(f"- {_msg('markdown.authored_scenario_set')} {expected['scenario'].get('name')}")
    lines.extend([
        f"- {_msg('markdown.generated_documents')} {len(documents)}/{expected_count}",
        f"- {_msg('markdown.model_fields_represented_in_csv')} {len(expected.get('generated_fields', []))}",
        f"- {_msg('markdown.cda_mapped_fields')} {len(expected.get('mapped_fields', []))}",
        f"- {_msg('markdown.fields_exercised_after_normalization')} {len(exercised)}", "",
    ])
    if errors:
        lines.extend([(_msg('markdown.errors')), ""] + [f"- {item}" for item in errors] + [""])
    if test_warnings:
        lines.extend([(_msg('markdown.warnings')), ""] + [f"- {item}" for item in test_warnings] + [""])
    lines.extend([
        (_msg('markdown.scope')), "",
        (_msg('markdown.this_test_uses_the_production_ingestion_normalization_validation')),
        (_msg('markdown.it_does_not_write_production_state_and_never')), "",
    ])
    (out_dir / "results.md").write_text(
        ("\n".join(lines)),
        encoding="utf-8",
    )
    return result, 0 if result["status"] == "PASS" else 1
