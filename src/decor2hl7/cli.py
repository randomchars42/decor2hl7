"""One CLI for selection, acquisition, compilation and transformation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import __version__
from .workspace import (
    copy_if_missing,
    init_workspace,
    load_json,
    load_settings,
    input_dir,
    release_site_dir,
    release_spec_dir,
    selected_release,
    selected_transaction,
    set_release,
    set_transaction,
    state_dir,
    transaction_mapping_dir,
    transaction_model_dir,
    transaction_out_dir,
    transaction_site_dir,
    transaction_spec_dir,
    transaction_test_dir,
    write_json,
)


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve()


def _require(path: Path, hint: str = "") -> Path:
    if path.exists():
        return path
    message = f"missing {path}"
    if hint:
        message += f"\n  {hint}"
    raise ValueError(message)


def _explicit_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve()


def _cda_mapping_path(
    root: Path,
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
    override: str | Path | None = None,
) -> Path:
    if override is None:
        return transaction_mapping_dir(root, release, transaction) / "cda-mapping.json"
    path = _explicit_path(override)
    return path / "cda-mapping.json" if path.is_dir() or not path.suffix else path


def _site_paths(
    root: Path,
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
    override: str | Path | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Return bundle dir, CSV mapping, code mapping and site JSON paths.

    The default workspace keeps release-wide site.json one level above the
    transaction-specific CSV/code mappings.  An explicit bundle path keeps all
    three files together, which makes a local or test configuration portable.
    """
    if override is None:
        bundle = transaction_site_dir(root, release, transaction)
        return (
            bundle,
            bundle / "csv-mapping.json",
            bundle / "codes-mapping.json",
            release_site_dir(root, release) / "site.json",
        )
    path = _explicit_path(override)
    if path.suffix:
        bundle = path.parent
        site = path
    else:
        bundle = path
        site = bundle / "site.json"
    return bundle, bundle / "csv-mapping.json", bundle / "codes-mapping.json", site


def _safe_key(value: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "record"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{base}--{digest}"


def _network(root: Path, ipv6_override: bool = False) -> tuple[str, str, bool, str]:
    from .retrieval.client import DEFAULT_API_BASE

    settings = load_settings(root)
    prefix = str(settings.get("prefix") or "aktin-")
    language = str(settings.get("language") or "de-DE")
    configured = bool((settings.get("network") or {}).get("ipv4", True))
    api_base = str((settings.get("api") or {}).get("base_url") or DEFAULT_API_BASE)
    return prefix, language, False if ipv6_override else configured, api_base


def cmd_init(args: argparse.Namespace) -> int:
    path = init_workspace(_root(args), args.prefix, args.language)
    _say(f"workspace initialized: {path}")
    return 0


def _filter(rows: list[dict[str, str]], needle: str | None) -> list[dict[str, str]]:
    if not needle:
        return rows
    value = needle.casefold()
    return [row for row in rows if any(value in str(item).casefold() for item in row.values())]


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """Print a compact terminal table with visibly separated columns."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def cmd_list_versions(args: argparse.Namespace) -> int:
    from .retrieval.catalog import releases

    root = _root(args)
    prefix, _, ipv4, api_base = _network(root, args.ipv6)
    rows = _filter(
        releases(prefix, ipv4=ipv4, base_url=api_base), args.filter
    )
    selected = load_settings(root).get("release") or {}
    table = [
        (row["key"], "*" if row["key"] == selected.get("key") else "",
         row["label"], row["date"], row["status"])
        for row in rows
    ]
    _print_table(("KEY", "SELECTED", "LABEL", "RELEASE_DATE", "STATUS"), table)
    if rows:
        _say("select with: decor2hl7 set-version <KEY>")
    return 0 if rows else 1


def cmd_set_version(args: argparse.Namespace) -> int:
    from .retrieval.catalog import releases, select_release

    root = _root(args)
    prefix, _, ipv4, api_base = _network(root, args.ipv6)
    row = select_release(
        releases(prefix, ipv4=ipv4, base_url=api_base), args.identifier
    )
    set_release(root, row)
    _say(f"selected release: {row['key']} ({row['date']})")
    _say("transaction selection cleared; run `decor2hl7 list-transactions`")
    return 0


def _transaction_rows(root: Path, ipv6: bool = False) -> list[dict[str, str]]:
    from .retrieval.catalog import transactions

    release = selected_release(root)
    prefix, language, ipv4, api_base = _network(root, ipv6)
    return transactions(
        prefix, str(release["date"]), language=language, ipv4=ipv4,
        base_url=api_base,
    )


def cmd_list_transactions(args: argparse.Namespace) -> int:
    root = _root(args)
    rows = _filter(_transaction_rows(root, args.ipv6), args.filter)
    selected = load_settings(root).get("transaction") or {}
    table = [
        (row["key"], "*" if row["key"] == selected.get("key") else "",
         row["version_label"], row["effective_date"], row["status"], row["name"], row["id"])
        for row in rows
    ]
    _print_table(("KEY", "SELECTED", "VERSION", "EFFECTIVE_DATE", "STATUS", "NAME", "OID"), table)
    if rows:
        _say("select with: decor2hl7 set-transaction <KEY>")
    return 0 if rows else 1


def cmd_set_transaction(args: argparse.Namespace) -> int:
    from .retrieval.catalog import select_transaction

    root = _root(args)
    row = select_transaction(_transaction_rows(root, args.ipv6), args.identifier)
    set_transaction(root, row)
    _say(
        f"selected transaction: {row['key']} "
        f"({row['id']} @ {row['effective_date'] or 'dynamic'})"
    )
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from .retrieval.fetch import fetch_spec
    from .retrieval.sources import load_source_hints

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    prefix, language, ipv4, api_base = _network(root, args.ipv6)
    result = fetch_spec(
        release_spec_dir(root, release),
        transaction_spec_dir(root, release, transaction),
        prefix=prefix,
        release=release,
        transaction=transaction,
        language=language,
        ipv4=ipv4,
        retry_missing=args.retry_missing,
        offline=args.offline,
        max_requests=args.max_requests,
        progress=_say,
        api_base=api_base,
        source_hints=load_source_hints(root / "config" / "sources.json"),
    )
    closure = result["closure"]
    summary = closure.get("summary", {})
    _say(
        f"selected transaction fetch: {summary.get('ok', 0)} cached/ok, "
        f"{summary.get('missing', 0)} missing, "
        f"{summary.get('unavailable', 0)} unavailable, "
        f"{summary.get('waived', 0)} waived, "
        f"{summary.get('partial', 0)} partial, "
        f"{summary.get('error', 0)} errors"
    )
    _say(
        f"transaction closure: {len(closure.get('build_resources', []))} build resources, "
        f"{len(closure.get('evidence_resources', []))} evidence resources"
    )
    if closure.get("truncated"):
        _say("warning: closure stopped at --max-requests; increase the limit and rerun fetch")
    if closure.get("crawl_complete", closure.get("complete")) and not closure.get("build_ready", True):
        for error in closure.get("readiness_errors", []):
            _say(f"error: {error}")
    for warning in closure.get("degradation_warnings", []):
        _say(f"warning: {warning}")
    if closure.get("errors"):
        for error in closure.get("errors", []):
            _say(f"error: {error}")
    return 0 if (
        not closure.get("errors")
        and not closure.get("truncated")
        and closure.get("build_ready", True)
    ) else 2


def _build_inputs(root: Path) -> tuple[Path, list[Path], list[Path], list[Path], list[Path]]:
    """Compatibility tuple backed by the typed compiler input contract."""
    inputs = _compiler_inputs(root)
    return (
        inputs["transaction_analysis"],
        inputs["model_resources"],
        inputs["templates"],
        [],
        inputs["mapping_evidence"],
    )


def _compiler_inputs(root: Path) -> dict[str, Any]:
    from .compile.artifacts import compiler_inputs

    release = selected_release(root)
    transaction = selected_transaction(root)
    release_dir = release_spec_dir(root, release)
    tx_dir = transaction_spec_dir(root, release, transaction)
    _require(tx_dir / "transaction.xml", "run `decor2hl7 fetch` first")
    return dict(compiler_inputs(release_dir, tx_dir))


def cmd_build(args: argparse.Namespace) -> int:
    from .compile.artifacts import write_build_diagnostics
    from .compile.mapping import write_code_mapping
    from .compile.cda import write_cda_model
    from .compile.mapping import write_mapping_model
    from .compile.transaction import write_transaction_model

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    inputs = _compiler_inputs(root)
    model_dir = transaction_model_dir(root, release, transaction)
    model_dir.mkdir(parents=True, exist_ok=True)
    model = write_transaction_model(
        inputs["transaction_source"],
        inputs["transaction_analysis"],
        inputs["model_resources"],
        inputs["terminology_resources"],
        model_dir,
    )
    unavailable = list(inputs.get("unavailable_artifacts", []))
    model.setdefault("meta", {})["artifact_closure"] = {
        "degraded": bool(unavailable),
        "unavailable_artifacts": [
            str(item.get("request_key") or "artifact") for item in unavailable
        ],
    }
    write_json(model_dir / "model.json", model)
    code_mapping = write_code_mapping(model_dir, model)
    cda = write_cda_model(inputs["templates"], model_dir, model)
    cda_mapping = write_mapping_model(
        inputs["mapping_evidence"], model_dir, model, cda
    )
    diagnostics = write_build_diagnostics(model_dir, inputs, cda)
    _say(f"model: {len(model['fields'])} datapoints, {len(model['groups'])} groups")
    _say(f"code mapping defaults: {sum(len(values) for values in code_mapping['fields'].values())} aliases across {len(code_mapping['fields'])} coded fields")
    _say(
        f"CDA: {cda['stats']['reachable_templates']} reachable templates, "
        f"{cda['stats']['targets']} physical named targets, "
        f"{cda['stats'].get('datapoints', 0)} logical mapped datapoints"
    )
    _say(f"CDA mapped proposal: {sum(value is not None for value in cda_mapping['fields'].values())}/{len(model['fields'])}")
    if diagnostics["status"] == "degraded":
        summary = diagnostics["summary"]
        _say(
            "warning: degraded build: "
            f"{summary['unavailable_artifacts']} unavailable artifacts, "
            f"{summary['unresolved_templates']} unresolved CDA references; "
            f"see {model_dir / 'build-diagnostics.md'}"
        )
    return 0


def cmd_propose_input(args: argparse.Namespace) -> int:
    from .compile.mapping import write_input_mappings

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    model = load_json(_require(model_dir / "model.json", "run `decor2hl7 build` first"))
    source_root = input_dir(root, args.input, required=True)
    proposal_dir, _, _, _ = _site_paths(
        root, release, transaction, getattr(args, "site_config", None)
    )
    proposal_dir.mkdir(parents=True, exist_ok=True)
    proposals = write_input_mappings(
        proposal_dir,
        source_root,
        model,
        join_column=args.join_column or "patient_id",
    )
    _say(f"CSV mapped proposal: {sum(value is not None for value in proposals['csv']['fields'].values())}/{len(model.get('fields', {}))}")
    _say(f"input mapping proposals written to: {proposal_dir}")
    _say(f"input snapshot inspected: {source_root}")
    return 0


def _site_scaffold(
    root: Path, release: Mapping[str, Any], transaction: Mapping[str, Any],
    csv_mapping: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .data import mapping_locator

    sources: dict[str, Any] = {}
    if csv_mapping is not None:
        for value in csv_mapping.get("fields", {}).values():
            locator = mapping_locator(value)
            if locator is not None:
                name = str(locator["source"])
                sources.setdefault(name, {"file": f"{name}.csv", "cardinality": "1:1"})
    configured_input = input_dir(root, required=False)
    if configured_input is not None and configured_input.is_dir():
        for path in sorted(configured_input.glob("*.csv")):
            sources.setdefault(path.stem, {"file": path.name, "cardinality": "1:1"})
    join_column = str(
        (csv_mapping or {}).get("join", {}).get("column") or "patient_id"
    )
    return {
        "version": 1,
        "release": release.get("key"),
        "timezone": "Europe/Berlin",
        "organization": {"name": None, "oid": None},
        "identifiers": {"document_root": None, "patient_root": None, "encounter_root": None, "roots": {}},
        "null_flavor": {"missing_required": "NI", "unmapped_code": "OTH"},
        "input": {
            "join_column": join_column,
            "case_source": next(iter(sources)) if len(sources) == 1 else None,
            "encoding": "utf-8-sig",
            "delimiter": None,
            "decimal_separator": ".",
            "empty_is_null": True,
            "null_values": ["NULL", "NA", "N/A"],
            "sources": sources,
            "source_note": (
                "Source file names are relative to the external input root. "
                "For 1:n sources set cardinality to 1:n. Optional primary: "
                "{column, true_values, required} moves one flagged row first; "
                "missing required or duplicate flags are input errors."
            ),
        },
        "cda": {
            "values": {},
            "note": (
                "Optional site/static values keyed by names from the generated cda.json; "
                "strings may use {key} and {document_version}."
            ),
        },
        "state": {"rotate_days": 90},
        "transport": {"url": None, "timeout": 60, "headers": {}},
    }


def _merge_code_mapping_defaults(source: Path, destination: Path) -> int:
    """Add newly generated non-null code defaults without changing user choices."""
    proposed = load_json(source)
    current = load_json(destination)
    proposed_fields = proposed.get("fields", {})
    current_fields = current.setdefault("fields", {})
    added = 0
    for path, proposed_values in proposed_fields.items():
        if not isinstance(proposed_values, Mapping):
            continue
        current_values = current_fields.setdefault(path, {})
        if not isinstance(current_values, dict):
            continue
        for raw, canonical in proposed_values.items():
            if canonical is None or raw in current_values:
                continue
            current_values[raw] = canonical
            added += 1
    if added:
        write_json(destination, current)
    return added


def _copy_generated_guide(source: Path, destination: Path) -> None:
    """Keep generated, read-only guidance beside the configuration it explains."""
    source = _require(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        _say("kept    " + str(destination))
        return
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    _say("updated " + str(destination))


def _mapping_lock(
    release: Mapping[str, Any], transaction: Mapping[str, Any],
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "version": 1,
        "release": {"key": release.get("key"), "date": release.get("date")},
        "transaction": {
            "key": transaction.get("key"), "id": transaction.get("id"),
            "effective_date": transaction.get("effective_date"),
        },
        "model_sha256": _json_digest(model),
        "cda_sha256": _json_digest(cda),
        # Informational provenance.  Reviewers may edit the mapping after it is
        # initialized; each test result records the actual tested hash.
        "mapping_sha256_at_creation": _json_digest(mapping),
    }


def cmd_init_cda_mapping(args: argparse.Namespace) -> int:
    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    source = _require(
        model_dir / "cda-mapping.proposed.json", "run `decor2hl7 build` first"
    )
    destination = _cda_mapping_path(
        root, release, transaction, getattr(args, "cda_mapping", None)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if copy_if_missing(source, destination):
        _say("created " + str(destination))
    else:
        _say("kept    " + str(destination))
    for guide_name in ("cda-mapping.md", "cda-mapping-details.md"):
        _copy_generated_guide(model_dir / guide_name, destination.parent / guide_name)
    model = load_json(_require(model_dir / "model.json"))
    cda = load_json(_require(model_dir / "cda.json"))
    mapping = load_json(destination)
    lock = destination.parent / "mapping-lock.json"
    if not lock.exists():
        write_json(lock, _mapping_lock(release, transaction, model, cda, mapping))
        _say("created " + str(lock))
    else:
        _say("kept    " + str(lock))
    return 0


def cmd_init_site_config(args: argparse.Namespace) -> int:
    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    proposal_dir, csv_destination, codes_destination, site = _site_paths(
        root, release, transaction, getattr(args, "site_config", None)
    )
    model_dir = transaction_model_dir(root, release, transaction)
    proposal_dir.mkdir(parents=True, exist_ok=True)
    for name, destination in (
        ("csv-mapping", csv_destination), ("codes-mapping", codes_destination)
    ):
        source = _require(
            proposal_dir / f"{name}.proposed.json",
            "run `decor2hl7 propose-input --input PATH` first",
        )
        if copy_if_missing(source, destination):
            _say("created " + str(destination))
        elif name == "codes-mapping":
            added = _merge_code_mapping_defaults(source, destination)
            suffix = f" (+{added} generated defaults)" if added else ""
            _say("kept    " + str(destination) + suffix)
        else:
            _say("kept    " + str(destination))
        guide_source = proposal_dir / f"{name}.md"
        if name == "codes-mapping" and not guide_source.exists():
            guide_source = model_dir / "codes-mapping.md"
        _copy_generated_guide(guide_source, destination.with_suffix(".md"))
    if not site.exists():
        csv_proposal = load_json(proposal_dir / "csv-mapping.proposed.json")
        write_json(site, _site_scaffold(root, release, transaction, csv_proposal))
        _say(f"created {site}")
    else:
        _say(f"kept    {site}")
    return 0


def _runtime_files(
    root: Path,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None,
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    _, csv_path, codes_path, site_path = _site_paths(
        root, release, transaction, site_config_override
    )
    mapping_path = _cda_mapping_path(
        root, release, transaction, cda_mapping_override
    )
    model = load_json(_require(model_dir / "model.json", "run `decor2hl7 build`"))
    cda = load_json(_require(model_dir / "cda.json", "run `decor2hl7 build`"))
    csv_mapping = load_json(_require(csv_path, "run `decor2hl7 init-site-config`"))
    codes_mapping = load_json(_require(codes_path, "run `decor2hl7 init-site-config`"))
    cda_mapping = load_json(_require(mapping_path, "run `decor2hl7 init-cda-mapping`"))
    site = load_json(_require(site_path, "run `decor2hl7 init-site-config`"))
    return model, cda, csv_mapping, codes_mapping, cda_mapping, site


def cmd_check(args: argparse.Namespace) -> int:
    from . import validate
    from .bindings import required_unmapped_null_flavor
    from .retrieval.fetch import verify_manifest

    root = _root(args)
    release = selected_release(root)
    model, cda, csv_mapping, codes_mapping, cda_mapping, site = _runtime_files(
        root, args.cda_mapping, args.site_config
    )
    errors = verify_manifest(release_spec_dir(root, release))
    errors.extend(validate.verify_compiled_cda(cda))
    errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    try:
        inputs = _compiler_inputs(root)
        errors.extend(
            validate.verify_compiled_against_artdecor(cda, inputs["templates"])
        )
    except ValueError as error:
        errors.append(str(error))
    print(f"model datapoints: {len(model.get('fields', {}))}")
    print(f"CSV mapped: {sum(value is not None for value in csv_mapping.get('fields', {}).values())}")
    print(f"CDA mapped: {sum(value is not None for value in cda_mapping.get('fields', {}).values())}")
    print(f"CDA target defaults: {len(cda_mapping.get('target_defaults', {}))}")
    try:
        completion_flavor = required_unmapped_null_flavor(cda_mapping)
    except ValueError:
        completion_flavor = "invalid"
    print(f"required unmapped CDA leaves: nullFlavor={completion_flavor}")
    print(f"CDA unresolved templates: {len(cda.get('unresolved_templates', []))}")
    closure = model.get("meta", {}).get("artifact_closure", {})
    unavailable = closure.get("unavailable_artifacts", []) if isinstance(closure, Mapping) else []
    if unavailable:
        print(f"build warning: {len(unavailable)} unavailable dependency artifacts")
    if errors:
        print("configuration errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("configuration: OK")
    return 0


def cmd_check_cda_mapping(args: argparse.Namespace) -> int:
    """Validate the shareable dataset-to-CDA bundle without site CSV input."""
    from . import validate
    from .bindings import required_unmapped_null_flavor
    from .compile.mapping import code_mapping_defaults
    from .testing import synthetic_site

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    model = load_json(_require(model_dir / "model.json", "run `decor2hl7 build`"))
    cda = load_json(_require(model_dir / "cda.json", "run `decor2hl7 build`"))
    mapping_path = _cda_mapping_path(root, release, transaction, args.cda_mapping)
    cda_mapping = load_json(_require(mapping_path, "run `decor2hl7 init-cda-mapping`"))
    neutral_csv = {
        "version": 1,
        "join": {"column": "case_id"},
        "fields": {path: None for path in model.get("fields", {})},
    }
    site = synthetic_site(release, cda, cda_mapping)
    errors = validate.verify_compiled_cda(cda)
    errors.extend(validate.check_config(
        model, cda, neutral_csv, cda_mapping, code_mapping_defaults(model), site
    ))
    try:
        inputs = _compiler_inputs(root)
        errors.extend(validate.verify_compiled_against_artdecor(cda, inputs["templates"]))
    except ValueError as error:
        errors.append(str(error))
    lock_path = mapping_path.parent / "mapping-lock.json"
    if lock_path.exists():
        lock = load_json(lock_path)
        if lock.get("model_sha256") != _json_digest(model):
            errors.append("mapping-lock.json was created for a different compiled dataset model")
        if lock.get("cda_sha256") != _json_digest(cda):
            errors.append("mapping-lock.json was created for a different compiled CDA model")
        locked_tx = lock.get("transaction", {})
        if isinstance(locked_tx, Mapping) and locked_tx.get("id") != transaction.get("id"):
            errors.append("mapping-lock.json names a different transaction OID")
    else:
        errors.append("mapping-lock.json is missing beside cda-mapping.json")
    print(f"CDA mapped: {sum(value is not None for value in cda_mapping.get('fields', {}).values())}")
    print(f"CDA target defaults: {len(cda_mapping.get('target_defaults', {}))}")
    try:
        completion_flavor = required_unmapped_null_flavor(cda_mapping)
    except ValueError:
        completion_flavor = "invalid"
    print(f"required unmapped CDA leaves: nullFlavor={completion_flavor}")
    print(f"mapping: {mapping_path}")
    if errors:
        print("CDA mapping errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("CDA mapping: OK")
    return 0


def cmd_setup_test(args: argparse.Namespace) -> int:
    from .testing import setup_fixture

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    model = load_json(_require(model_dir / "model.json", "run `decor2hl7 build`"))
    cda = load_json(_require(model_dir / "cda.json", "run `decor2hl7 build`"))
    mapping_path = _cda_mapping_path(root, release, transaction, args.cda_mapping)
    cda_mapping = load_json(_require(mapping_path, "run `decor2hl7 init-cda-mapping`"))
    test_dir = (
        _explicit_path(args.test_dir) if args.test_dir
        else transaction_test_dir(root, release, transaction)
    )
    expected = setup_fixture(
        test_dir, release, transaction, model, cda, cda_mapping, force=args.force
    )
    _say(f"test fixture: {test_dir}")
    _say(f"generated {len(expected['generated_fields'])} model datapoint columns")
    _say(f"CDA-mapped fields covered by input: {len(expected['mapped_fields'])}")
    return 0


def cmd_test_cda_mapping(args: argparse.Namespace) -> int:
    from .testing import run_fixture

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    model = load_json(_require(model_dir / "model.json", "run `decor2hl7 build`"))
    cda = load_json(_require(model_dir / "cda.json", "run `decor2hl7 build`"))
    mapping_path = _cda_mapping_path(root, release, transaction, args.cda_mapping)
    cda_mapping = load_json(_require(mapping_path, "run `decor2hl7 init-cda-mapping`"))
    test_dir = (
        _explicit_path(args.test_dir) if args.test_dir
        else transaction_test_dir(root, release, transaction)
    )
    _require(test_dir / "expected.json", "run `decor2hl7 setup-test` first")
    out_dir = _explicit_path(args.out) if args.out else test_dir / "out"
    result, status = run_fixture(test_dir, out_dir, model, cda, cda_mapping)
    print(json.dumps({
        "status": result["status"],
        "documents": len(result["documents"]),
        "results": str(out_dir / "results.md"),
    }, ensure_ascii=False))
    return status


def cmd_check_input(args: argparse.Namespace) -> int:
    from . import data, validate

    root = _root(args)
    source_root = input_dir(root, args.input, required=True)
    assert source_root is not None
    model, cda, csv_mapping, codes_mapping, cda_mapping, site = _runtime_files(
        root, args.cda_mapping, args.site_config
    )
    errors = validate.verify_compiled_cda(cda)
    errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    if errors:
        print("configuration errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    records = data.ingest(source_root, model, csv_mapping, codes_mapping, site)
    summary = validate.validate_records(records, model)
    print(f"input: {source_root}")
    print(f"records: {summary['records']}")
    print(f"errors: {summary['errors']}")
    print(f"warnings: {summary['warnings']}")
    for record in records:
        for problem in record.get("problems", []):
            key = record.get("key", "?")
            print(f"  {problem.get('severity', 'error')}: {key}: {problem.get('path', '')}: {problem.get('message', '')}")
    return 0 if summary["errors"] == 0 else 1


def _state_key(transaction: Mapping[str, Any], record_key: str) -> str:
    # Transaction identity, not release identity: a later release of the same
    # transaction should still detect unchanged/corrected source records.
    return f"{transaction['id']}::{record_key}"


def _prune_stale_pending(out_dir: Path, state_key: str, fingerprint: str) -> int:
    """Remove pending artifacts for an older source state of the same record."""
    removed = 0
    if not out_dir.exists():
        return removed
    for sidecar in out_dir.glob("*.json"):
        try:
            info = load_json(sidecar)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if str(info.get("state_key") or "") != state_key:
            continue
        if str(info.get("fingerprint") or "") == fingerprint:
            continue
        xml = sidecar.with_suffix(".xml")
        if xml.exists():
            xml.unlink()
        sidecar.unlink()
        removed += 1
    return removed


def _prune_absent_pending(out_dir: Path, current_keys: set[str], state_path: Path) -> int:
    """Remove unsent artifacts whose source record is no longer present."""
    from . import state

    removed = 0
    if not out_dir.exists():
        return removed
    for sidecar in out_dir.glob("*.json"):
        try:
            info = load_json(sidecar)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        stream_key = str(info.get("state_key") or "")
        if not stream_key or stream_key in current_keys:
            continue
        disposition, _ = state.classify(state_path, stream_key, str(info.get("fingerprint") or ""))
        if disposition == "UNCHANGED":
            continue  # already sent; keep the generated document as an audit artifact
        xml = sidecar.with_suffix(".xml")
        if xml.exists():
            xml.unlink()
        sidecar.unlink()
        removed += 1
    return removed


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _transformation_context(
    release: Mapping[str, Any], transaction: Mapping[str, Any], model: Mapping[str, Any],
    cda: Mapping[str, Any], cda_mapping: Mapping[str, Any], site: Mapping[str, Any],
) -> dict[str, Any]:
    relevant_site = {
        "identifiers": site.get("identifiers", {}),
        "null_flavor": site.get("null_flavor", {}),
        "cda": site.get("cda", {}),
    }
    return {
        "decor2hl7": __version__,
        "release": {"key": release.get("key"), "date": release.get("date")},
        "transaction": {"id": transaction.get("id"), "effective_date": transaction.get("effective_date")},
        "model": _json_digest(model), "cda": _json_digest(cda),
        "cda_mapping": _json_digest(cda_mapping), "site": _json_digest(relevant_site),
    }


def _transform(
    root: Path,
    input_override: str | Path | None = None,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None,
) -> tuple[list[Path], dict[str, int]]:
    from . import cda as cda_runtime
    from . import data, state, validate

    release = selected_release(root)
    transaction = selected_transaction(root)
    model, cda, csv_mapping, codes_mapping, cda_mapping, site = _runtime_files(
        root, cda_mapping_override, site_config_override
    )
    config_errors = validate.verify_compiled_cda(cda)
    config_errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    if config_errors:
        raise ValueError("configuration is invalid:\n" + "\n".join("  " + item for item in config_errors))
    source_root = input_dir(root, input_override, required=True)
    assert source_root is not None
    records = data.ingest(source_root, model, csv_mapping, codes_mapping, site)
    validation = validate.validate_records(records, model)
    out_dir = transaction_out_dir(root, release, transaction)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[Path] = []
    skipped_unchanged = skipped_invalid = 0
    state_path = state_dir(root)
    current_keys = {_state_key(transaction, str(record["key"])) for record in records}
    _prune_absent_pending(out_dir, current_keys, state_path)
    transformation_context = _transformation_context(release, transaction, model, cda, cda_mapping, site)
    for record in records:
        raw_key = str(record["key"])
        stream_key = _state_key(transaction, raw_key)
        digest = state.fingerprint(record, transformation_context)
        # Invalidate an older pending representation even when the current
        # record is invalid and therefore cannot be emitted.
        _prune_stale_pending(out_dir, stream_key, digest)
        if any(problem.get("severity") == "error" for problem in record.get("problems", [])):
            skipped_invalid += 1
            continue
        disposition, document_version = state.classify(state_path, stream_key, digest)
        if disposition == "UNCHANGED":
            skipped_unchanged += 1
            continue
        payload, render_problems = cda_runtime.emit(
            record, model, cda, cda_mapping, site, document_version=document_version
        )
        stem = f"{_safe_key(raw_key)}-v{document_version}"
        xml_path = out_dir / f"{stem}.xml"
        xml_path.write_bytes(payload)
        write_json(out_dir / f"{stem}.json", {
            "key": raw_key,
            "state_key": stream_key,
            "fingerprint": digest,
            "document_version": document_version,
            "release": release.get("key"),
            "transaction": transaction,
            "source_status": disposition,
            "validation": record.get("problems", []),
            "render_warnings": render_problems,
        })
        emitted.append(xml_path)
    return emitted, {
        **validation,
        "emitted": len(emitted),
        "unchanged": skipped_unchanged,
        "invalid": skipped_invalid,
    }


def cmd_transform(args: argparse.Namespace) -> int:
    emitted, summary = _transform(
        _root(args), args.input, args.cda_mapping, args.site_config
    )
    print(json.dumps(summary, ensure_ascii=False))
    for path in emitted:
        print(path)
    return 0 if summary["invalid"] == 0 else 2


def _send_paths(
    root: Path, paths: list[Path] | None = None,
    site_config_override: str | Path | None = None,
) -> tuple[int, int]:
    from . import state, transport

    release = selected_release(root)
    transaction = selected_transaction(root)
    _, _, _, site_path = _site_paths(
        root, release, transaction, site_config_override
    )
    site = load_json(_require(site_path, "run `decor2hl7 init-site-config`"))
    out_dir = transaction_out_dir(root, release, transaction)
    candidates = paths or sorted(out_dir.glob("*.xml"))
    sent = failed = 0
    for path in candidates:
        sidecar_path = path.with_suffix(".json")
        if not sidecar_path.exists():
            _say(f"skip {path.name}: no sidecar")
            continue
        info = load_json(sidecar_path)
        stream_key = str(info.get("state_key") or _state_key(transaction, str(info["key"])))
        disposition, _ = state.classify(state_dir(root), stream_key, str(info["fingerprint"]))
        if disposition == "UNCHANGED":
            continue
        ok, message = transport.send(path, site)
        if not ok:
            _say(f"send failed {path.name}: {message}")
            failed += 1
            continue
        state.record_sent(
            state_dir(root), key=stream_key, digest=str(info["fingerprint"]),
            document_version=int(info["document_version"]), file=str(path),
            spec_version=str(release["key"]),
        )
        _say(f"sent {path.name}: {message}")
        sent += 1
    state.rotate(state_dir(root), int(site.get("state", {}).get("rotate_days") or 0))
    return sent, failed


def cmd_send(args: argparse.Namespace) -> int:
    sent, failed = _send_paths(
        _root(args), [Path(value) for value in args.files] if args.files else None,
        args.site_config,
    )
    print(json.dumps({"sent": sent, "failed": failed}))
    return 0 if failed == 0 else 2


def cmd_run(args: argparse.Namespace) -> int:
    root = _root(args)
    emitted, summary = _transform(
        root, args.input, args.cda_mapping, args.site_config
    )
    print(json.dumps(summary, ensure_ascii=False))
    if args.send:
        sent, failed = _send_paths(root, emitted, args.site_config)
        print(json.dumps({"sent": sent, "failed": failed}))
        return 0 if failed == 0 and summary["invalid"] == 0 else 2
    _say("documents were emitted but not sent; pass --send to transmit them")
    return 0 if summary["invalid"] == 0 else 2


def cmd_status(args: argparse.Namespace) -> int:
    from . import state

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    current = state.load_state(state_dir(root))
    out_dir = transaction_out_dir(root, release, transaction)
    pending = 0
    for sidecar_path in out_dir.glob("*.json") if out_dir.exists() else []:
        info = load_json(sidecar_path)
        stream_key = str(info.get("state_key") or _state_key(transaction, str(info.get("key"))))
        disposition, _ = state.classify(state_dir(root), stream_key, str(info.get("fingerprint")))
        pending += disposition != "UNCHANGED"
    print(json.dumps({
        "sent_documents": len(current.get("documents", {})),
        "pending_documents": pending,
        "release": release.get("key"),
        "transaction": transaction.get("key"),
    }, ensure_ascii=False, indent=2))
    return 0


def _add_network_override(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ipv6", action="store_true",
        help="diagnostic override; ART-DECOR uses IPv4 by default",
    )


def _add_runtime_config_overrides(
    parser: argparse.ArgumentParser, *, cda: bool = True, site: bool = True
) -> None:
    if cda:
        parser.add_argument(
            "--cda-mapping",
            help="cda-mapping.json (or its directory); overrides the selected workspace bundle",
        )
    if site:
        parser.add_argument(
            "--site-config",
            help="site config bundle directory (or site.json); CSV/code mappings are read beside it",
        )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="decor2hl7")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--root", default=".", help="workspace root (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("init", help="create the workspace skeleton")
    q.add_argument("--prefix", default="aktin-")
    q.add_argument("--language", default="de-DE")
    q.set_defaults(func=cmd_init)

    q = sub.add_parser("list-versions", help="list ART-DECOR project release keys")
    q.add_argument("filter", nargs="?", help="optional text filter")
    _add_network_override(q)
    q.set_defaults(func=cmd_list_versions)

    q = sub.add_parser("set-version", help="select an ART-DECOR release by KEY from `list-versions`")
    q.add_argument("identifier")
    _add_network_override(q)
    q.set_defaults(func=cmd_set_version)

    q = sub.add_parser("list-transactions", help="list transaction keys for the selected release")
    q.add_argument("filter", nargs="?", help="optional text filter")
    _add_network_override(q)
    q.set_defaults(func=cmd_list_transactions)

    q = sub.add_parser("set-transaction", help="select a transaction by KEY from `list-transactions`")
    q.add_argument("identifier")
    _add_network_override(q)
    q.set_defaults(func=cmd_set_transaction)

    q = sub.add_parser("fetch", help="fetch the selected transaction specification to closure")
    fetch_network = q.add_mutually_exclusive_group()
    fetch_network.add_argument("--retry-missing", action="store_true")
    fetch_network.add_argument(
        "--offline", action="store_true",
        help="use cached specification files only; make no HTTP requests",
    )
    q.add_argument("--max-requests", type=int, default=1500)
    _add_network_override(q)
    q.set_defaults(func=cmd_fetch)

    q = sub.add_parser("build", help="compile ART-DECOR models and CDA mapping proposal")
    q.set_defaults(func=cmd_build)

    q = sub.add_parser("propose-input", help="inspect CSV input and propose CSV/code mappings")
    q.add_argument("--input", help="CSV input directory; overrides aktin.json input.directory")
    q.add_argument("--join-column", default="patient_id")
    _add_runtime_config_overrides(q, cda=False)
    q.set_defaults(func=cmd_propose_input)

    q = sub.add_parser("init-cda-mapping", help="initialize the shareable dataset-to-CDA mapping bundle")
    _add_runtime_config_overrides(q, site=False)
    q.set_defaults(func=cmd_init_cda_mapping)

    q = sub.add_parser("init-site-config", help="initialize local CSV/code/site configuration")
    _add_runtime_config_overrides(q, cda=False)
    q.set_defaults(func=cmd_init_site_config)

    q = sub.add_parser("check", help="check downloads, compiled models and configuration")
    _add_runtime_config_overrides(q)
    q.set_defaults(func=cmd_check)

    q = sub.add_parser("check-cda-mapping", help="validate a shareable CDA mapping without site input")
    _add_runtime_config_overrides(q, site=False)
    q.set_defaults(func=cmd_check_cda_mapping)

    q = sub.add_parser("setup-test", help="generate isolated synthetic CSV/config mapping test input")
    q.add_argument("--test-dir", help="test fixture directory; defaults to test/<release>/<transaction>")
    q.add_argument("--force", action="store_true", help="replace generated input/config/expected files")
    _add_runtime_config_overrides(q, site=False)
    q.set_defaults(func=cmd_setup_test)

    q = sub.add_parser("test-cda-mapping", help="run the isolated CDA mapping fixture")
    q.add_argument("--test-dir", help="test fixture directory; defaults to test/<release>/<transaction>")
    q.add_argument("--out", help="result directory; defaults to the fixture's out directory")
    _add_runtime_config_overrides(q, site=False)
    q.set_defaults(func=cmd_test_cda_mapping)

    q = sub.add_parser("check-input", help="validate the external CSV input snapshot without emitting CDA")
    q.add_argument("--input", help="CSV input directory; overrides aktin.json input.directory")
    _add_runtime_config_overrides(q)
    q.set_defaults(func=cmd_check_input)

    q = sub.add_parser("transform", help="read, normalize, validate and emit changed documents")
    q.add_argument("--input", help="CSV input directory; overrides aktin.json input.directory")
    _add_runtime_config_overrides(q)
    q.set_defaults(func=cmd_transform)

    q = sub.add_parser("send", help="send emitted documents not already recorded as sent")
    q.add_argument("files", nargs="*")
    _add_runtime_config_overrides(q, cda=False)
    q.set_defaults(func=cmd_send)

    q = sub.add_parser("run", help="perform the runtime pipeline")
    q.add_argument("--input", help="CSV input directory; overrides aktin.json input.directory")
    q.add_argument("--send", action="store_true")
    _add_runtime_config_overrides(q)
    q.set_defaults(func=cmd_run)

    q = sub.add_parser("status", help="show sent/pending document state")
    q.set_defaults(func=cmd_status)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _say("aborted by user")
        return 130
    except (OSError, ValueError) as error:
        _say(f"error: {error}")
        return 2
