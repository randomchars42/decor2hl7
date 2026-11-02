"""One CLI for selection, acquisition, compilation and transformation."""

from __future__ import annotations

import argparse
from contextvars import ContextVar
import datetime as dt
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import __version__
from .i18n import (
    Translator,
    configured_output_language,
    localize_markdown,
    localize_ui,
)
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
    write_bytes,
    write_json,
)


_OUTPUT_LANGUAGE: ContextVar[str] = ContextVar(
    "decor2hl7_output_language", default="en"
)


class _LocalizedArgumentParser(argparse.ArgumentParser):
    """Apply the selected locale to argparse-owned help text."""

    def __init__(
        self, *args: Any, output_language: str | None = None, **kwargs: Any,
    ) -> None:
        self._output_language = output_language
        super().__init__(*args, **kwargs)

    def _language(self) -> str:
        return self._output_language or _OUTPUT_LANGUAGE.get()

    def format_help(self) -> str:
        return localize_ui(super().format_help(), self._language())

    def format_usage(self) -> str:
        return localize_ui(super().format_usage(), self._language())


def _say(message: str) -> None:
    print(localize_ui(message, _OUTPUT_LANGUAGE.get()), file=sys.stderr)


def _out(message: str) -> None:
    print(localize_ui(message, _OUTPUT_LANGUAGE.get()))


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
    path = init_workspace(
        _root(args), args.prefix, args.language, args.output_language
    )
    _say(Translator(args.output_language).text(
        "cli.workspace_initialized", path=path
    ))
    return 0


def _filter(rows: list[dict[str, str]], needle: str | None) -> list[dict[str, str]]:
    if not needle:
        return rows
    value = needle.casefold()
    return [row for row in rows if any(value in str(item).casefold() for item in row.values())]


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """Print a compact terminal table with visibly separated columns."""
    localized_headers = [
        localize_ui(header, _OUTPUT_LANGUAGE.get()) for header in headers
    ]
    widths = [len(header) for header in localized_headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    print("  ".join(
        header.ljust(widths[index])
        for index, header in enumerate(localized_headers)
    ))
    for row in rows:
        print("  ".join(
            value.ljust(widths[index]) for index, value in enumerate(row)
        ))


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
    from .cda.extensions import load_extensions
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
        cda_extensions=load_extensions(
            root / "config" / "cda-extensions.json", transaction
        ),
        cda_core=True,
        validation_packages=True,
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
    if closure.get("crawl_complete") and not closure.get("build_ready", True):
        for error in closure.get("readiness_errors", []):
            _say(f"error: {error}")
    for warning in closure.get("degradation_warnings", []):
        _say(f"warning: {warning}")
    if closure.get("errors"):
        for error in closure.get("errors", []):
            _say(f"error: {error}")
    succeeded = (
        not closure.get("errors")
        and not closure.get("truncated")
        and closure.get("build_ready", True)
    )
    if getattr(args, "fail_on_degraded", False) and closure.get("degraded_resources"):
        _say("error: --fail-on-degraded rejected the degraded retrieval closure")
        succeeded = False
    return 0 if succeeded else 2


def _compiler_inputs(root: Path) -> dict[str, Any]:
    from .compile.artifacts import compiler_inputs

    release = selected_release(root)
    transaction = selected_transaction(root)
    release_dir = release_spec_dir(root, release)
    tx_dir = transaction_spec_dir(root, release, transaction)
    _require(tx_dir / "transaction.xml", "run `decor2hl7 fetch` first")
    return dict(compiler_inputs(release_dir, tx_dir))


def cmd_build(args: argparse.Namespace) -> int:
    from .compile.artifacts import (
        configured_source_rules,
        selected_closure_template_revisions,
        selected_closure_templates,
        write_build_diagnostics,
    )
    from .compile.site import write_code_mapping
    from .cda.compile import write_cda_model
    from .cda.core import core_paths
    from .compile.mapping import write_mapping_model
    from .compile.transaction import write_transaction_model

    root = _root(args)
    settings = load_settings(root)
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
        model_extensions=settings.get("model_extensions"),
    )
    model.setdefault("meta", {})["configured_source_rules"] = (
        configured_source_rules(inputs)
    )
    unavailable = list(inputs.get("unavailable_artifacts", []))
    crawl_degraded = list(inputs.get("crawl_degraded_artifacts", unavailable))
    model.setdefault("meta", {})["artifact_closure"] = {
        "crawl_degraded": bool(crawl_degraded),
        "crawl_degraded_artifacts": [
            str(item.get("request_key") or "artifact")
            for item in crawl_degraded
        ],
        "unavailable_artifacts": [
            str(item.get("request_key") or "artifact") for item in unavailable
        ],
    }
    write_json(model_dir / "model.json", model)
    code_mapping = write_code_mapping(
        model_dir, model, output_language=args.output_language
    )
    cda = write_cda_model(
        inputs["templates"], model_dir, model,
        core_definition_paths=core_paths(release_spec_dir(root, release)),
        cda_extensions=inputs.get("cda_extensions", []),
        strict_specializations=bool(
            getattr(args, "strict_specializations", False)
        ),
    )
    from .conformance import build_conformance_artifacts
    conformance = build_conformance_artifacts(
        release_spec_dir(root, release), model_dir, inputs, release, transaction,
        selected_closure_templates(cda),
        selected_closure_template_revisions(cda),
        output_language=args.output_language,
    )
    from .compile.schematron import attach_constraints
    if any(
        stage.get("phase") == "template-schematron-generation"
        and stage.get("status") == "passed"
        for stage in conformance.get("stages", [])
    ):
        attach_constraints(cda, model_dir / "conformance-validation" / "include")
    else:
        cda["datatype_constraints"] = {
            "version": 1,
            "source": "generated-datatype-schematron",
            "status": "unavailable",
            "rules": {},
        }
        cda["schematron_evidence"] = {
            "source": "generated-template-schematron",
            "constraints": 0,
            "matched": 0,
            "kinds": {},
            "status": "unavailable",
            "datatype_cooccurrence": {
                "source": "generated-datatype-schematron",
                "status": "unavailable",
            },
        }
    cda_mapping = write_mapping_model(
        inputs["mapping_evidence"], model_dir, model, cda,
        output_language=args.output_language,
    )
    diagnostics = write_build_diagnostics(
        model_dir, inputs, cda, model,
        output_language=args.output_language,
    )
    model["meta"]["artifact_closure"].update({
        "degraded": diagnostics["status"] == "degraded",
        "build_degraded": [
            str(item.get("request_key") or "artifact")
            for item in diagnostics.get("build_degraded", [])
        ],
    })
    write_json(model_dir / "model.json", model)
    _say(f"model: {len(model['fields'])} datapoints, {len(model['groups'])} groups")
    _say(f"code mapping defaults: {sum(len(values) for values in code_mapping['fields'].values())} aliases across {len(code_mapping['fields'])} coded fields")
    _say(
        f"CDA: {cda['stats']['reachable_templates']} reachable templates, "
        f"{cda['stats']['targets']} physical named targets, "
        f"{cda['stats'].get('datapoints', 0)} logical mapped datapoints"
    )
    constraint_diagnostics = list(cda.get("constraint_diagnostics", []))
    specialization_diagnostics = [
        row for row in constraint_diagnostics
        if row.get("code") == "spec-constraint-weakening"
    ]
    if specialization_diagnostics:
        _say(
            "warning: "
            f"{len(specialization_diagnostics)} CDA SPEC constraint weakening(s); "
            "explicit child constraints were used; see "
            f"{model_dir / 'build-diagnostics.md'}"
        )
    other_diagnostics = [
        row for row in constraint_diagnostics
        if row.get("code") != "spec-constraint-weakening"
    ]
    if other_diagnostics:
        error_count = sum(
            str(row.get("severity") or "").casefold() in {"fatal", "error"}
            for row in other_diagnostics
        )
        _say(
            "warning: "
            f"{len(other_diagnostics)} owner-rule diagnostic(s), "
            f"{error_count} error-level; see "
            f"{model_dir / 'build-diagnostics.md'}"
        )
    audit_path = model_dir / "mapping-audit.json"
    if audit_path.is_file():
        accepted_path = _cda_mapping_path(root, release, transaction)
        _report_coverage(
            model,
            cda,
            load_json(audit_path),
            cda_mapping,
            load_json(accepted_path) if accepted_path.is_file() else None,
        )
    if diagnostics["status"] == "degraded":
        summary = diagnostics["summary"]
        _say(
            "warning: degraded build: "
            f"{summary['build_degraded']} degraded artifacts affect this build, "
            f"{summary['crawl_degraded']} degraded artifacts in the crawl, "
            f"{summary['unresolved_templates']} unresolved CDA references; "
            f"see {model_dir / 'build-diagnostics.md'}"
        )
    validation_summary = conformance.get("summary", {})
    _say(
        f"conformance validation (report-only, {str(conformance.get('status')).upper()}): "
        f"{validation_summary.get('error', 0)} errors, "
        f"{validation_summary.get('warning', 0)} warnings; "
        f"see {model_dir / 'conformance-validation' / 'build-conformance.md'}"
    )
    if getattr(args, "fail_on_degraded", False) and diagnostics.get("build_degraded"):
        _say(
            "error: --fail-on-degraded rejected the degraded build: "
            f"{diagnostics['summary']['build_degraded']} degraded artifacts "
            "affect this build"
        )
        return 2
    return 0


def cmd_validate_cda(args: argparse.Namespace) -> int:
    """Independently validate CDA XML against the pinned schema and rules."""
    from .conformance import validate_cda_documents

    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    documents = [_explicit_path(value) for value in args.files]
    for document in documents:
        _require(document, "CDA document does not exist")
    report = (
        _explicit_path(args.report)
        if args.report else model_dir / "conformance-validation" / "cda-validation"
    )
    result = validate_cda_documents(
        release_spec_dir(root, release), model_dir, documents, report,
        output_language=args.output_language,
    )
    summary = result["summary"]
    print(json.dumps({
        "status": result["status"],
        "errors": summary["error"],
        "warnings": summary["warning"],
        "report": str(report.with_suffix(".md")),
    }, ensure_ascii=False))
    return 1 if result["status"] == "failed" else 0


def cmd_propose_input(args: argparse.Namespace) -> int:
    from .compile.site import write_input_mappings

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
        output_language=args.output_language,
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
        "null_flavor": {"missing_required": "NI"},
        "input": {
            "join_column": join_column,
            "case_source": next(iter(sources)) if len(sources) == 1 else None,
            "encoding": "utf-8-sig",
            "delimiter": None,
            "decimal_separator": ".",
            "empty_is_null": True,
            "null_values": ["NULL", "NA", "N/A"],
            "unit_aliases": {},
            "sources": sources,
            "source_note": (
                "Source file names are relative to the external input root. "
                "For 1:n sources set cardinality to 1:n. Optional primary: "
                "{column, true_values, required} moves one flagged row first; "
                "missing required or duplicate flags are input errors. ODBC "
                "sources may set order_by to an ordered list of columns."
            ),
        },
        "source": {
            "adapter": None,
            "dsn_env": "DECOR2HL7_ODBC_DSN",
            "written_at_column": None,
            "window_days": 90,
            "queries": {name: f"sql/{name}.sql" for name in sources},
            "require_snapshot_advance": True,
        },
        "cda": {
            "values": {},
            "note": (
                "Optional site/static values keyed by names from the generated cda.json; "
                "strings may use {key} and {document_version}."
            ),
        },
        "operation": {"failure_threshold": 0},
        "transport": {
            "adapter": "http-post", "url": None, "timeout": 60, "headers": {},
        },
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


def _copy_generated_guide(
    source: Path,
    destination: Path,
    *,
    output_language: str = "en",
    protected_values: Iterable[Any] = (),
) -> None:
    """Keep generated, read-only guidance beside the configuration it explains."""
    source = _require(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    original = source.read_text(encoding="utf-8")
    content = localize_markdown(
        original, output_language, protected_values=protected_values
    )
    if source.resolve() == destination.resolve() and content == original:
        _say("kept    " + str(destination))
        return
    destination.write_text(content, encoding="utf-8")
    _say("updated " + str(destination))


def _mapping_decisions_differ(
    current: Mapping[str, Any], proposed: Mapping[str, Any],
) -> bool:
    """Return whether reviewer-owned executable choices differ from proposal."""
    return any(
        current.get(key, {}) != proposed.get(key, {})
        for key in (
            "fields", "structures", "defaults", "target_defaults",
            "site_requirements", "field_reviews", "narratives",
        )
    )


def _write_mapping_guides(
    model_dir: Path,
    destination: Path,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    proposal: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    output_language: str = "en",
) -> None:
    """Write guides for the actual reviewed mapping, retaining proposal evidence."""
    if not _mapping_decisions_differ(mapping, proposal):
        guide_sources = {
            "cda-mapping.md": "cda-mapping.proposed.md",
            "cda-mapping-details.md": "cda-mapping-details.md",
            "cda-mapping-trees.md": "cda-mapping-trees.md",
            "cda-mapping-trees-extended.md": "cda-mapping-trees-extended.md",
        }
        for guide_name, source_name in guide_sources.items():
            source = model_dir / source_name
            if guide_name == "cda-mapping.md" and not source.exists():
                # Older generated workspaces used the reviewed-bundle filename
                # for the proposal guide. Allow one refresh before the next build.
                source = model_dir / "cda-mapping.md"
            _copy_generated_guide(
                source, destination.parent / guide_name,
                output_language=output_language,
                protected_values=(model, cda, mapping, audit),
            )
        return

    from .compile.reports import (
        render_accepted_cda_mappings_markdown,
        render_cda_mapping_extended_trees_markdown,
        render_cda_mapping_markdown,
        render_cda_mapping_trees_markdown,
    )

    rendered = {
        "cda-mapping.md": render_cda_mapping_markdown(
            model, cda, mapping, audit, output_language=output_language
        ),
        "cda-mapping-trees.md": render_cda_mapping_trees_markdown(
            model, cda, mapping, audit, output_language=output_language
        ),
        "cda-mapping-trees-extended.md": render_cda_mapping_extended_trees_markdown(
            model, cda, mapping, audit, output_language=output_language
        ),
    }
    generated_details = _require(
        model_dir / "cda-mapping-details.md"
    ).read_text(encoding="utf-8")
    accepted_start = max(
        generated_details.find("# Accepted mappings\n"),
        generated_details.find("# Akzeptierte mappings\n"),
    )
    analysis_candidates = [
        generated_details.find("# Datapoint analysis\n"),
        generated_details.find("# Datapoint-Analyse\n"),
    ]
    analysis_start = next(
        (index for index in analysis_candidates if index >= 0), -1
    )
    if 0 <= accepted_start < analysis_start:
        accepted = render_accepted_cda_mappings_markdown(
            model, cda, mapping, output_language=output_language
        ).rstrip()
        rendered["cda-mapping-details.md"] = localize_markdown(
            (
                generated_details[:accepted_start]
                + accepted
                + "\n\n# Generated proposal evidence\n\n"
                + "The following audit explains what the compiler could establish "
                "without reviewer decisions. It may therefore show a reviewed "
                "mapping above as unselected or non-executable in the generated "
                "proposal.\n\n"
                + generated_details[analysis_start:]
            ),
            output_language,
            protected_values=(model, cda, mapping, proposal, audit),
        )
    else:
        rendered["cda-mapping-details.md"] = generated_details

    for guide_name, content in rendered.items():
        target = destination.parent / guide_name
        target.write_text(content, encoding="utf-8")
        _say("updated " + str(target))


def _merge_mapping_configuration_notes(
    source: Path,
    destination: Path,
    *,
    generated_notes: list[dict[str, Any]] | None = None,
) -> int:
    """Refresh generated provenance notes without changing reviewed mappings."""
    proposed = load_json(source)
    current = load_json(destination)
    proposed_notes = (
        generated_notes
        if generated_notes is not None
        else proposed.get("configuration_notes", [])
    )
    current_notes = current.get("configuration_notes", [])
    generated = [
        dict(item) for item in proposed_notes
        if isinstance(item, Mapping) and item.get("generated") is True
    ] if isinstance(proposed_notes, list) else []
    retained = [
        item for item in current_notes
        if not (isinstance(item, Mapping) and item.get("generated") is True)
    ] if isinstance(current_notes, list) else []
    merged = retained + generated
    if merged != current_notes:
        current["configuration_notes"] = merged
        write_json(destination, current)
    return len(generated)


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


def _report_coverage(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    audit: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
) -> None:
    from .compile.reports import coverage_headline_counts, format_coverage_headline

    if baseline is not None:
        _say(
            "coverage  baseline: "
            + format_coverage_headline(
                coverage_headline_counts(model, cda, baseline, audit),
                markdown=False,
            )
        )
    _say(
        "coverage  current:  "
        + format_coverage_headline(
            coverage_headline_counts(model, cda, current, audit),
            markdown=False,
        )
    )


def cmd_init_cda_mapping(args: argparse.Namespace) -> int:
    root = _root(args)
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    source = _require(
        model_dir / "cda-mapping.proposed.json", "run `decor2hl7 build` first"
    )
    model = load_json(_require(model_dir / "model.json"))
    cda = load_json(_require(model_dir / "cda.json"))
    destination = _cda_mapping_path(
        root, release, transaction, getattr(args, "cda_mapping", None)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    reset = bool(getattr(args, "reset", False))
    if reset:
        write_json(destination, load_json(source))
        created = False
        _say("reset   " + str(destination))
    else:
        created = copy_if_missing(source, destination)
    if created:
        _say("created " + str(destination))
    elif not reset:
        from .compile.mapping import (
            _mapping_configuration_notes, migrate_mapping_target_identities,
        )
        current_mapping = load_json(destination)
        previous_identities = current_mapping.get("target_identities")
        target_migrations = migrate_mapping_target_identities(
            current_mapping, load_json(source), cda
        )
        if (
            target_migrations
            or current_mapping.get("target_identities") != previous_identities
        ):
            write_json(destination, current_mapping)
        audit = load_json(_require(model_dir / "mapping-audit.json"))
        notes = _merge_mapping_configuration_notes(
            source,
            destination,
            generated_notes=_mapping_configuration_notes(
                load_json(destination), audit, model, cda
            ),
        )
        changes = []
        if target_migrations:
            changes.append(f"migrated {target_migrations} CDA target reference(s)")
        if notes:
            changes.append(f"refreshed {notes} configuration note(s)")
        suffix = f" ({'; '.join(changes)})" if changes else ""
        _say("kept    " + str(destination) + suffix)
        from .compile.mapping import mapping_field_delta
        delta = mapping_field_delta(load_json(destination), load_json(source))
        _report_coverage(
            model, cda, audit, load_json(source), load_json(destination)
        )
        for path in delta["lost"]:
            _say("review  " + str(path))
    mapping = load_json(destination)
    proposal = load_json(source)
    audit = (
        load_json(_require(model_dir / "mapping-audit.json"))
        if _mapping_decisions_differ(mapping, proposal)
        else {"fields": {}, "groups": {}}
    )
    _write_mapping_guides(
        model_dir, destination, model, cda, mapping, proposal, audit,
        output_language=args.output_language,
    )
    lock = destination.parent / "mapping-lock.json"
    if reset or not lock.exists():
        write_json(lock, _mapping_lock(release, transaction, model, cda, mapping))
        _say(("updated " if reset else "created ") + str(lock))
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
    model_path = model_dir / "model.json"
    model = load_json(model_path) if model_path.is_file() else {}
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
        _copy_generated_guide(
            guide_source,
            destination.with_suffix(".md"),
            output_language=args.output_language,
            protected_values=(model, load_json(source)),
        )
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


def _verify_compiled_sources(
    root: Path, cda: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    """Run setup-time source checks without importing them into runtime validation."""
    from .cda.parity import (
        declared_endpoint_parity,
        endpoint_parity_errors,
        verify_compiled_against_artdecor,
    )
    from .compile.artifacts import selected_closure_templates

    try:
        inputs = _compiler_inputs(root)
        template_paths = inputs["templates"]
        errors = verify_compiled_against_artdecor(cda, template_paths)
        parity = declared_endpoint_parity(
            template_paths, cda, selected_closure_templates(cda)
        )
        errors.extend(endpoint_parity_errors(parity))
        return errors, parity
    except ValueError as error:
        return [str(error)], None


def _print_source_parity(parity: Mapping[str, Any] | None) -> None:
    if parity is None:
        _out("CDA source endpoint parity: unavailable")
        return
    _out(
        "CDA source endpoint parity: "
        f"{parity.get('compiled', 0)}/{parity.get('declared', 0)} compiled; "
        f"{len(parity.get('fixed_structural_attributes', []))} fixed structural; "
        f"{len(parity.get('reviewed_branch_replacements', []))} reviewed replacements; "
        f"{len(parity.get('unexpected_missing', []))} unexpected missing"
    )


def cmd_check(args: argparse.Namespace) -> int:
    from . import source, validate
    from .bindings import required_unmapped_null_flavor
    from .cda.narrative import narrative_blocks
    from .retrieval.fetch import verify_manifest

    root = _root(args)
    release = selected_release(root)
    model, cda, csv_mapping, codes_mapping, cda_mapping, site = _runtime_files(
        root, args.cda_mapping, args.site_config
    )
    errors = verify_manifest(release_spec_dir(root, release))
    errors.extend(validate.verify_compiled_cda(cda))
    errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    source_errors, parity = _verify_compiled_sources(root, cda)
    errors.extend(source_errors)
    source_config = site.get("source", {})
    if isinstance(source_config, Mapping) and source_config.get("adapter") == "odbc":
        bundle, _, _, _ = _site_paths(
            root, release, selected_transaction(root), args.site_config
        )
        query_problems = source.query_errors(site, bundle)
        errors.extend(query_problems)
        if not query_problems and not validate.check_site(site, cda):
            try:
                source.check_connection(site)
                _out("ODBC source connection: OK")
            except ValueError as error:
                errors.append(str(error))
    _out(f"model datapoints: {len(model.get('fields', {}))}")
    _out(f"CSV mapped: {sum(value is not None for value in csv_mapping.get('fields', {}).values())}")
    _out(f"CDA mapped: {sum(value is not None for value in cda_mapping.get('fields', {}).values())}")
    _out(f"CDA narrative-only mapped: {len(narrative_blocks(cda_mapping))}")
    _out(f"CDA target defaults: {len(cda_mapping.get('target_defaults', {}))}")
    try:
        completion_flavor = required_unmapped_null_flavor(cda_mapping)
    except ValueError:
        completion_flavor = "invalid"
    _out(f"required unmapped CDA leaves: nullFlavor={completion_flavor}")
    _out(f"CDA unresolved templates: {len(cda.get('unresolved_templates', []))}")
    _print_source_parity(parity)
    closure = model.get("meta", {}).get("artifact_closure", {})
    unavailable = closure.get("unavailable_artifacts", []) if isinstance(closure, Mapping) else []
    if unavailable:
        _out(f"build warning: {len(unavailable)} unavailable dependency artifacts")
    if errors:
        _out("configuration errors:")
        for message in errors:
            _out(f"  - {message}")
        return 1
    _out("configuration: OK")
    return 0


def cmd_check_cda_mapping(args: argparse.Namespace) -> int:
    """Validate the shareable dataset-to-CDA bundle without site CSV input."""
    from . import validate
    from .bindings import required_unmapped_null_flavor
    from .compile.site import code_mapping_defaults
    from .cda.narrative import narrative_blocks
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
        model, cda, neutral_csv, cda_mapping, code_mapping_defaults(model), site,
        require_site_configuration=False,
    ))
    source_errors, parity = _verify_compiled_sources(root, cda)
    errors.extend(source_errors)
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
    _out(f"CDA mapped: {sum(value is not None for value in cda_mapping.get('fields', {}).values())}")
    _out(f"CDA narrative-only mapped: {len(narrative_blocks(cda_mapping))}")
    _out(f"CDA target defaults: {len(cda_mapping.get('target_defaults', {}))}")
    _print_source_parity(parity)
    site_requirements = cda_mapping.get("site_requirements", {})
    site_requirements = (
        site_requirements if isinstance(site_requirements, Mapping) else {}
    )
    _out(f"CDA site requirements: {len(site_requirements)}")
    for name, rule in sorted(site_requirements.items()):
        channel = (
            str(rule.get("channel") or "?")
            if isinstance(rule, Mapping) else "?"
        )
        _out(f"site config required: cda.{channel}[{name!r}]")
    try:
        completion_flavor = required_unmapped_null_flavor(cda_mapping)
    except ValueError:
        completion_flavor = "invalid"
    _out(f"required unmapped CDA leaves: nullFlavor={completion_flavor}")
    _out(f"mapping: {mapping_path}")
    if errors:
        _out("CDA mapping errors:")
        for message in errors:
            _out(f"  - {message}")
        return 1
    _out("CDA mapping: OK")
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
        test_dir, release, transaction, model, cda, cda_mapping,
        force=args.force,
        scenario_dir=_explicit_path(args.scenario) if args.scenario else None,
    )
    _say(f"test fixture: {test_dir}")
    if args.scenario:
        _say(f"authored scenario set: {expected['scenario']['name']}")
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
    result, status = run_fixture(
        test_dir, out_dir, model, cda, cda_mapping,
        output_language=args.output_language,
    )
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
    model, cda, csv_mapping, codes_mapping, cda_mapping, site = _runtime_files(
        root, args.cda_mapping, args.site_config
    )
    errors = validate.verify_compiled_cda(cda)
    errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    if errors:
        _out("configuration errors:")
        for error in errors:
            _out(f"  - {error}")
        return 1
    records = data.ingest(source_root, model, csv_mapping, codes_mapping, site)
    summary = validate.validate_records(records, model)
    _out(f"input: {source_root}")
    _out(f"records: {summary['records']}")
    _out(f"errors: {summary['errors']}")
    _out(f"warnings: {summary['warnings']}")
    for record in records:
        for problem in record.get("problems", []):
            key = record.get("key", "?")
            _out(f"  {problem.get('severity', 'error')}: {key}: {problem.get('path', '')}: {problem.get('message', '')}")
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
    current = state.load_state(state_path)
    for sidecar in out_dir.glob("*.json"):
        try:
            info = load_json(sidecar)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        stream_key = str(info.get("state_key") or "")
        if not stream_key or stream_key in current_keys:
            continue
        disposition, _ = state.classify_loaded(
            current, stream_key, str(info.get("fingerprint") or "")
        )
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


def _document_identity(
    record_key: str, document_version: int, site: Mapping[str, Any],
) -> dict[str, Any]:
    root = str(site.get("identifiers", {}).get("document_root") or "")
    return {
        "document_id": {
            "root": root, "extension": f"{record_key}-{document_version}",
        },
        "set_id": {"root": root, "extension": record_key},
        "version": document_version,
    }


def _quarantine_record(
    root: Path, run_id: str, record: Mapping[str, Any], *,
    stage: str, problems: Sequence[Any], document_version: int | None = None,
) -> None:
    key = str(record.get("key") or "unknown")
    directory = state_dir(root) / "quarantine" / run_id
    stem = _safe_key(key)
    write_json(directory / f"{stem}.json", {
        "key": key,
        "stage": stage,
        "document_version": document_version,
        "problems": list(problems),
        "record": dict(record),
    })


def _transform(
    root: Path,
    input_override: str | Path | None = None,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None,
    *,
    run_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    source_snapshot: Mapping[str, Any] | None = None,
    prune_absent: bool = True,
) -> tuple[list[Path], dict[str, int]]:
    from .cda.render import emit
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
    records = data.ingest(source_root, model, csv_mapping, codes_mapping, site)
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        records = records[:limit]
    validation = validate.validate_records(records, model)
    out_dir = transaction_out_dir(root, release, transaction)
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[Path] = []
    skipped_unchanged = skipped_invalid = quarantined = 0
    run_id = run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    state_path = state_dir(root)
    current_state = state.load_state(state_path)
    current_keys = {_state_key(transaction, str(record["key"])) for record in records}
    if not dry_run and prune_absent and limit is None:
        _prune_absent_pending(out_dir, current_keys, state_path)
    transformation_context = _transformation_context(release, transaction, model, cda, cda_mapping, site)
    for record in records:
        raw_key = str(record["key"])
        stream_key = _state_key(transaction, raw_key)
        digest = state.fingerprint(record, transformation_context)
        # Invalidate an older pending representation even when the current
        # record is invalid and therefore cannot be emitted.
        if not dry_run:
            _prune_stale_pending(out_dir, stream_key, digest)
        if any(problem.get("severity") == "error" for problem in record.get("problems", [])):
            skipped_invalid += 1
            if not dry_run:
                _quarantine_record(
                    root, run_id, record, stage="input-validation",
                    problems=list(record.get("problems", [])),
                )
                quarantined += 1
            continue
        disposition, document_version = state.classify_loaded(
            current_state, stream_key, digest
        )
        if disposition == "UNCHANGED":
            skipped_unchanged += 1
            continue
        if dry_run:
            emitted.append(Path(f"{_safe_key(raw_key)}-v{document_version}.xml"))
            continue
        previous = state.previous_document_loaded(current_state, stream_key)
        if disposition == "CHANGED" and previous is None:
            # Legacy JSON state did not persist CDA identities. The identifiers
            # were deterministic, so reconstruct the direct predecessor once.
            previous = _document_identity(raw_key, document_version - 1, site)
        try:
            payload, render_problems = emit(
                record, model, cda, cda_mapping, site,
                document_version=document_version,
                previous_document=previous if disposition == "CHANGED" else None,
            )
        except ValueError as error:
            skipped_invalid += 1
            quarantined += 1
            _quarantine_record(
                root, run_id, record, stage="cda-render",
                problems=[str(error)], document_version=document_version,
            )
            continue
        stem = f"{_safe_key(raw_key)}-v{document_version}"
        xml_path = out_dir / f"{stem}.xml"
        identity = _document_identity(raw_key, document_version, site)
        write_bytes(xml_path, payload)
        write_json(out_dir / f"{stem}.json", {
            "key": raw_key,
            "state_key": stream_key,
            "fingerprint": digest,
            "document_version": document_version,
            "release": release.get("key"),
            "transaction": transaction,
            "source_status": disposition,
            "document_id": identity["document_id"],
            "set_id": identity["set_id"],
            "previous_document": previous if disposition == "CHANGED" else None,
            "source_snapshot": dict(source_snapshot) if source_snapshot is not None else None,
            "validation": record.get("problems", []),
            "render_warnings": render_problems,
        })
        emitted.append(xml_path)
    return emitted, {
        **validation,
        "emitted": len(emitted),
        "unchanged": skipped_unchanged,
        "invalid": skipped_invalid,
        "quarantined": quarantined,
    }


def _new_run_id() -> str:
    return (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-" + uuid.uuid4().hex[:8]
    )


def _failure_threshold(
    root: Path,
    cda_mapping_override: str | Path | None,
    site_config_override: str | Path | None,
) -> int:
    *_, site = _runtime_files(
        root, cda_mapping_override, site_config_override
    )
    operation = site.get("operation", {})
    return int(operation.get("failure_threshold") or 0) if isinstance(operation, Mapping) else 0


def cmd_transform(args: argparse.Namespace) -> int:
    from . import state

    root = _root(args)
    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(state_dir(root), run_id, kind="transform")
        try:
            emitted, summary = _transform(
                root, args.input, args.cda_mapping, args.site_config,
                run_id=run_id,
            )
            threshold = _failure_threshold(root, args.cda_mapping, args.site_config)
            ok = int(summary["invalid"]) <= threshold
            state.finish_run(
                state_dir(root), run_id,
                status="completed" if ok else "failed", summary=summary,
            )
        except BaseException as error:
            state.finish_run(
                state_dir(root), run_id, status="failed", error=str(error),
            )
            raise
    print(json.dumps(summary, ensure_ascii=False))
    for path in emitted:
        print(path)
    return 0 if ok else 2


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
    candidates = paths if paths is not None else sorted(out_dir.glob("*.xml"))
    sent = failed = 0
    for path in candidates:
        sidecar_path = path.with_suffix(".json")
        if not sidecar_path.exists():
            _say(f"skip {path.name}: no sidecar")
            continue
        info = load_json(sidecar_path)
        raw_key = str(info["key"])
        stream_key = str(info.get("state_key") or _state_key(transaction, raw_key))
        disposition, expected_version = state.classify(
            state_dir(root), stream_key, str(info["fingerprint"])
        )
        if disposition == "UNCHANGED":
            continue
        document_version = int(info["document_version"])
        expected_identity = _document_identity(raw_key, document_version, site)
        if document_version != expected_version:
            _say(
                f"send failed {path.name}: artifact version {document_version} "
                f"does not match next committed version {expected_version}"
            )
            failed += 1
            continue
        if (
            info.get("document_id") != expected_identity["document_id"]
            or info.get("set_id") != expected_identity["set_id"]
        ):
            _say(f"send failed {path.name}: artifact CDA identity is missing or inconsistent")
            failed += 1
            continue
        if document_version > 1:
            committed_previous = state.previous_document(state_dir(root), stream_key)
            if committed_previous is None:
                committed_previous = _document_identity(raw_key, document_version - 1, site)
            if info.get("previous_document") != committed_previous:
                _say(f"send failed {path.name}: replacement lineage does not match committed state")
                failed += 1
                continue
        ok, message = transport.send(path, site, workspace=root)
        if not ok:
            _say(f"send failed {path.name}: {message}")
            failed += 1
            continue
        delivery_status = (
            "published" if transport.configured_name(site) == "spool" else "sent"
        )
        state.record_delivery(
            state_dir(root), key=stream_key, digest=str(info["fingerprint"]),
            document_version=document_version, file=str(path),
            spec_version=str(release["key"]), status=delivery_status,
            document_id=(
                info.get("document_id")
                if isinstance(info.get("document_id"), Mapping) else None
            ),
            set_id=(
                info.get("set_id")
                if isinstance(info.get("set_id"), Mapping) else None
            ),
            previous=(
                info.get("previous_document")
                if isinstance(info.get("previous_document"), Mapping) else None
            ),
        )
        _say(f"delivered {path.name}: {message}")
        sent += 1
    return sent, failed


def cmd_send(args: argparse.Namespace) -> int:
    from . import state

    root = _root(args)
    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(state_dir(root), run_id, kind="send")
        try:
            sent, failed = _send_paths(
                root, [Path(value) for value in args.files] if args.files else None,
                args.site_config,
            )
            state.finish_run(
                state_dir(root), run_id,
                status="completed" if failed == 0 else "failed",
                summary={"sent": sent, "failed": failed},
            )
        except BaseException as error:
            state.finish_run(
                state_dir(root), run_id, status="failed", error=str(error),
            )
            raise
    print(json.dumps({"sent": sent, "failed": failed}))
    return 0 if failed == 0 else 2


def cmd_run(args: argparse.Namespace) -> int:
    from . import state

    root = _root(args)
    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(state_dir(root), run_id, kind="run")
        try:
            emitted, summary = _transform(
                root, args.input, args.cda_mapping, args.site_config,
                run_id=run_id,
            )
            print(json.dumps(summary, ensure_ascii=False))
            failed = 0
            if args.send:
                sent, failed = _send_paths(root, emitted, args.site_config)
                print(json.dumps({"sent": sent, "failed": failed}))
            threshold = _failure_threshold(root, args.cda_mapping, args.site_config)
            failure_count = int(summary["invalid"]) + failed
            ok = failure_count <= threshold
            state.finish_run(
                state_dir(root), run_id,
                status="completed" if ok else "failed",
                summary={**summary, "delivery_failed": failed},
            )
        except BaseException as error:
            state.finish_run(
                state_dir(root), run_id, status="failed", error=str(error),
            )
            raise
    if args.send:
        return 0 if ok else 2
    _say("documents were emitted but not sent; pass --send to transmit them")
    return 0 if ok else 2


def _source_site(
    root: Path,
    site_config_override: str | Path | None,
) -> tuple[Path, dict[str, Any]]:
    from . import source, validate

    release = selected_release(root)
    transaction = selected_transaction(root)
    bundle, _, _, site_path = _site_paths(
        root, release, transaction, site_config_override
    )
    site = load_json(_require(site_path, "run `decor2hl7 init-site-config`"))
    errors = validate.check_site(site)
    errors.extend(source.query_errors(site, bundle))
    if errors:
        raise ValueError(
            "source runtime configuration is invalid:\n"
            + "\n".join("  " + item for item in errors)
        )
    return bundle, site


def _parse_since(value: str | None) -> dt.date | None:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("--since must use YYYY-MM-DD") from error


def cmd_extract_source(args: argparse.Namespace) -> int:
    from . import source, state

    root = _root(args)
    bundle, site = _source_site(root, args.site_config)
    output = _explicit_path(args.output)
    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(
            state_dir(root), run_id, kind="extract-source",
            snapshot_path=str(output),
        )
        try:
            manifest = source.extract(
                site, bundle, output, since=_parse_since(args.since)
            )
            state.finish_run(
                state_dir(root), run_id, status="extracted",
                summary=manifest, snapshot_path=str(output),
                snapshot_max_ts=(
                    str(manifest["snapshot_max_ts"])
                    if manifest.get("snapshot_max_ts") is not None else None
                ),
            )
        except BaseException as error:
            state.finish_run(
                state_dir(root), run_id, status="failed",
                snapshot_path=str(output), error=str(error),
            )
            raise
    print(json.dumps({"snapshot": str(output), **manifest}, ensure_ascii=False))
    return 0


def cmd_run_source(args: argparse.Namespace) -> int:
    from . import source, state

    root = _root(args)
    bundle, site = _source_site(root, args.site_config)
    if args.dry_run and args.send:
        raise ValueError("--dry-run and --send cannot be combined")
    run_id = _new_run_id()
    snapshot = (
        _explicit_path(args.snapshot_output)
        if args.snapshot_output else state_dir(root) / "snapshots" / run_id
    )
    with state.workspace_lock(state_dir(root)):
        state.start_run(
            state_dir(root), run_id, kind="run-source",
            snapshot_path=str(snapshot),
        )
        manifest: dict[str, Any] | None = None
        try:
            manifest = source.extract(
                site, bundle, snapshot, since=_parse_since(args.since)
            )
            source_config = site.get("source", {})
            require_advance = (
                bool(source_config.get("require_snapshot_advance", True))
                if isinstance(source_config, Mapping) else True
            )
            maximum = manifest.get("snapshot_max_ts")
            previous_maximum = state.last_snapshot_max_ts(state_dir(root))
            if not args.dry_run and require_advance and previous_maximum is not None:
                if maximum is None or str(maximum) <= previous_maximum:
                    raise ValueError(
                        "source snapshot has not advanced: last completed "
                        f"maximum {previous_maximum!r}, current {maximum!r}"
                    )

            snapshot_evidence = {"path": str(snapshot), **manifest}
            emitted, summary = _transform(
                root, snapshot, args.cda_mapping, args.site_config,
                run_id=run_id, limit=args.limit, dry_run=args.dry_run,
                source_snapshot=snapshot_evidence,
                prune_absent=False,
            )
            print(json.dumps(summary, ensure_ascii=False))
            sent = failed = 0
            if args.send:
                sent, failed = _send_paths(root, emitted, args.site_config)
                print(json.dumps({"sent": sent, "failed": failed}))
            threshold = int(
                site.get("operation", {}).get("failure_threshold") or 0
            ) if isinstance(site.get("operation", {}), Mapping) else 0
            failure_count = int(summary["invalid"]) + failed
            ok = failure_count <= threshold
            status = (
                "failed" if not ok else
                "inspected" if args.dry_run else
                "partial" if args.limit is not None else
                "completed" if args.send else "transformed"
            )
            state.finish_run(
                state_dir(root), run_id, status=status,
                summary={
                    **summary, "sent": sent, "delivery_failed": failed,
                },
                snapshot_path=str(snapshot),
                snapshot_max_ts=(str(maximum) if maximum is not None else None),
            )
        except BaseException as error:
            state.finish_run(
                state_dir(root), run_id, status="failed",
                snapshot_path=str(snapshot),
                snapshot_max_ts=(
                    str(manifest["snapshot_max_ts"])
                    if manifest and manifest.get("snapshot_max_ts") is not None
                    else None
                ),
                error=str(error),
            )
            raise
    if not args.send and not args.dry_run:
        _say("documents were emitted but not delivered; pass --send for handover")
    return 0 if ok else 2


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
        disposition, _ = state.classify_loaded(
            current, stream_key, str(info.get("fingerprint"))
        )
        pending += disposition != "UNCHANGED"
    print(json.dumps({
        "delivered_documents": len(current.get("documents", {})),
        "sent_documents": len(current.get("documents", {})),
        "pending_documents": pending,
        "recent_runs": state.recent_runs(state_dir(root), 5),
        "release": release.get("key"),
        "transaction": transaction.get("key"),
    }, ensure_ascii=False, indent=2))
    return 0


def _add_network_override(
    parser: argparse.ArgumentParser, translator: Translator,
) -> None:
    parser.add_argument(
        "--ipv6", action="store_true",
        help=translator.text("cli.ipv6_help"),
    )


def _add_runtime_config_overrides(
    parser: argparse.ArgumentParser,
    translator: Translator,
    *,
    cda: bool = True,
    site: bool = True,
) -> None:
    if cda:
        parser.add_argument(
            "--cda-mapping",
            help=translator.text("cli.cda_mapping_help"),
        )
    if site:
        parser.add_argument(
            "--site-config",
            help=translator.text("cli.site_config_help"),
        )


def parser(output_language: str = "en") -> argparse.ArgumentParser:
    translator = Translator(output_language)
    t = translator.text
    p = _LocalizedArgumentParser(
        prog="decor2hl7", output_language=output_language
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--root", default=".", help=t("cli.root_help"))
    p.add_argument(
        "--output-language",
        metavar="LANG",
        help=t("cli.output_language_help"),
    )
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("init", help=t("cli.init_help"))
    q.add_argument("--prefix", default="aktin-", help=t("cli.prefix_help"))
    q.add_argument(
        "--language", default="de-DE", help=t("cli.init_source_language_help")
    )
    q.set_defaults(func=cmd_init)

    q = sub.add_parser("list-versions", help=t("cli.list_versions_help"))
    q.add_argument("filter", nargs="?", help=t("cli.filter_help"))
    _add_network_override(q, translator)
    q.set_defaults(func=cmd_list_versions)

    q = sub.add_parser("set-version", help=t("cli.set_version_help"))
    q.add_argument("identifier", help=t("cli.identifier_help"))
    _add_network_override(q, translator)
    q.set_defaults(func=cmd_set_version)

    q = sub.add_parser("list-transactions", help=t("cli.list_transactions_help"))
    q.add_argument("filter", nargs="?", help=t("cli.filter_help"))
    _add_network_override(q, translator)
    q.set_defaults(func=cmd_list_transactions)

    q = sub.add_parser("set-transaction", help=t("cli.set_transaction_help"))
    q.add_argument("identifier", help=t("cli.identifier_help"))
    _add_network_override(q, translator)
    q.set_defaults(func=cmd_set_transaction)

    q = sub.add_parser("fetch", help=t("cli.fetch_help"))
    fetch_network = q.add_mutually_exclusive_group()
    fetch_network.add_argument(
        "--retry-missing", action="store_true", help=t("cli.retry_missing_help")
    )
    fetch_network.add_argument(
        "--offline", action="store_true",
        help=t("cli.offline_help"),
    )
    q.add_argument(
        "--max-requests", type=int, default=1500,
        help=t("cli.max_requests_help"),
    )
    q.add_argument(
        "--fail-on-degraded", action="store_true",
        help=t("cli.fetch_degraded_help"),
    )
    _add_network_override(q, translator)
    q.set_defaults(func=cmd_fetch)

    q = sub.add_parser("build", help=t("cli.build_help"))
    q.add_argument(
        "--fail-on-degraded", action="store_true",
        help=t("cli.build_degraded_help"),
    )
    q.add_argument(
        "--strict-specializations", action="store_true",
        help=t("cli.strict_specializations_help"),
    )
    q.set_defaults(func=cmd_build)

    q = sub.add_parser("propose-input", help=t("cli.propose_input_help"))
    q.add_argument("--input", help=t("cli.input_help"))
    q.add_argument(
        "--join-column", default="patient_id", help=t("cli.join_column_help")
    )
    _add_runtime_config_overrides(q, translator, cda=False)
    q.set_defaults(func=cmd_propose_input)

    q = sub.add_parser("init-cda-mapping", help=t("cli.init_mapping_help"))
    _add_runtime_config_overrides(q, translator, site=False)
    q.add_argument(
        "--reset", action="store_true",
        help=t("cli.reset_help"),
    )
    q.set_defaults(func=cmd_init_cda_mapping)

    q = sub.add_parser("init-site-config", help=t("cli.init_site_help"))
    _add_runtime_config_overrides(q, translator, cda=False)
    q.set_defaults(func=cmd_init_site_config)

    q = sub.add_parser("check", help=t("cli.check_help"))
    _add_runtime_config_overrides(q, translator)
    q.set_defaults(func=cmd_check)

    q = sub.add_parser("check-cda-mapping", help=t("cli.check_mapping_help"))
    _add_runtime_config_overrides(q, translator, site=False)
    q.set_defaults(func=cmd_check_cda_mapping)

    q = sub.add_parser(
        "setup-test",
        help=t("cli.setup_test_help"),
    )
    q.add_argument("--test-dir", help=t("cli.test_dir_help"))
    q.add_argument(
        "--scenario",
        help=t("cli.scenario_help"),
    )
    q.add_argument("--force", action="store_true", help=t("cli.force_help"))
    _add_runtime_config_overrides(q, translator, site=False)
    q.set_defaults(func=cmd_setup_test)

    q = sub.add_parser("test-cda-mapping", help=t("cli.test_mapping_help"))
    q.add_argument("--test-dir", help=t("cli.test_dir_help"))
    q.add_argument("--out", help=t("cli.out_help"))
    _add_runtime_config_overrides(q, translator, site=False)
    q.set_defaults(func=cmd_test_cda_mapping)

    q = sub.add_parser(
        "validate-cda",
        help=t("cli.validate_cda_help"),
    )
    q.add_argument("files", nargs="+", help=t("cli.files_help"))
    q.add_argument("--report", help=t("cli.report_help"))
    q.set_defaults(func=cmd_validate_cda)

    q = sub.add_parser("check-input", help=t("cli.check_input_help"))
    q.add_argument("--input", help=t("cli.input_help"))
    _add_runtime_config_overrides(q, translator)
    q.set_defaults(func=cmd_check_input)

    q = sub.add_parser("extract-source", help=t("cli.extract_source_help"))
    q.add_argument("--output", required=True, help=t("cli.snapshot_output_help"))
    q.add_argument("--since", help=t("cli.since_help"))
    _add_runtime_config_overrides(q, translator, cda=False)
    q.set_defaults(func=cmd_extract_source)

    q = sub.add_parser("transform", help=t("cli.transform_help"))
    q.add_argument("--input", help=t("cli.input_help"))
    _add_runtime_config_overrides(q, translator)
    q.set_defaults(func=cmd_transform)

    q = sub.add_parser("send", help=t("cli.send_help"))
    q.add_argument("files", nargs="*")
    _add_runtime_config_overrides(q, translator, cda=False)
    q.set_defaults(func=cmd_send)

    q = sub.add_parser("run", help=t("cli.run_help"))
    q.add_argument("--input", help=t("cli.input_help"))
    q.add_argument("--send", action="store_true", help=t("cli.send_flag_help"))
    _add_runtime_config_overrides(q, translator)
    q.set_defaults(func=cmd_run)

    q = sub.add_parser("run-source", help=t("cli.run_source_help"))
    q.add_argument("--since", help=t("cli.since_help"))
    q.add_argument("--snapshot-output", help=t("cli.snapshot_output_help"))
    q.add_argument("--limit", type=int, help=t("cli.limit_help"))
    q.add_argument("--dry-run", action="store_true", help=t("cli.dry_run_help"))
    q.add_argument("--send", action="store_true", help=t("cli.send_flag_help"))
    _add_runtime_config_overrides(q, translator)
    q.set_defaults(func=cmd_run_source)

    q = sub.add_parser("status", help=t("cli.status_help"))
    q.set_defaults(func=cmd_status)
    return p


def _bootstrap_output_language(argv: Sequence[str] | None) -> str:
    values = list(sys.argv[1:] if argv is None else argv)
    bootstrap = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    bootstrap.add_argument("--root", default=".")
    bootstrap.add_argument("--output-language")
    known, _unknown = bootstrap.parse_known_args(values)
    root = Path(known.root).resolve()
    path = root / "decor2hl7.json"
    settings = load_json(path) if path.is_file() else None
    return configured_output_language(settings, known.output_language)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        output_language = _bootstrap_output_language(argv)
    except (OSError, ValueError) as error:
        _say(Translator().text("cli.error", message=error))
        return 2
    token = _OUTPUT_LANGUAGE.set(output_language)
    try:
        args = parser(output_language).parse_args(argv)
        args.output_language = output_language
        translator = Translator(output_language)
        try:
            return int(args.func(args))
        except KeyboardInterrupt:
            _say(translator.text("cli.aborted"))
            return 130
        except (OSError, RuntimeError, ValueError) as error:
            _say(translator.text("cli.error", message=error))
            return 2
    finally:
        _OUTPUT_LANGUAGE.reset(token)
