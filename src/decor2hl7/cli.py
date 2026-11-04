"""One CLI for selection, acquisition, compilation and transformation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .runtime_config import _root, _require, _explicit_path, _cda_mapping_path, _site_paths, _runtime_files
from .runtime import cmd_transform, cmd_send, cmd_run, cmd_extract_source, cmd_run_source, cmd_status
from .ui import say as _say, out as _out
from .i18n import OUTPUT_LANGUAGE as _OUTPUT_LANGUAGE
from . import __version__
from .bundle import admit_mapping, mapping_lock as _mapping_lock
from .i18n import (
    message as _msg, localized,
    Translator,
    configured_output_language,
)
from .workspace import (
    copy_if_missing,
    init_workspace,
    load_json,
    load_settings,
    input_dir,
    release_spec_dir,
    selected_release,
    selected_transaction,
    set_release,
    set_transaction,
    transaction_model_dir,
    transaction_spec_dir,
    transaction_test_dir,
    write_json,
)


class _LocalizedHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage: str | None, actions: Iterable[argparse.Action], groups: Iterable[argparse._MutuallyExclusiveGroup], prefix: str | None = None) -> None:
        super().add_usage(usage, actions, groups, prefix=prefix or self._usage_prefix)

    def __init__(self, prog: str, *, language: str) -> None:
        super().__init__(prog)
        self._usage_prefix = Translator(language).text("ui.usage") + " "


class _LocalizedArgumentParser(argparse.ArgumentParser):
    """Construct argparse labels in their language before formatting."""
    def __init__(self, *args: Any, output_language: str | None = None, **kwargs: Any) -> None:
        language = output_language or _OUTPUT_LANGUAGE.get()
        translator = Translator(language)
        kwargs["formatter_class"] = lambda prog: _LocalizedHelpFormatter(prog, language=language)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = translator.text("ui.positional_arguments").removesuffix(":")
        self._optionals.title = translator.text("ui.options").removesuffix(":")
        self.add_argument("-h", "--help", action="help", help=translator.text("cli.help"))


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
        (header) for header in headers
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
    _print_table(("KEY", (_msg('ui.selected')), "LABEL", "RELEASE_DATE", (_msg('ui.status'))), table)
    if rows:
        _say((_msg('ui.select_with') + ' decor2hl7 set-version <KEY>'))
    return 0 if rows else 1


def cmd_set_version(args: argparse.Namespace) -> int:
    from .retrieval.catalog import releases, select_release

    root = _root(args)
    prefix, _, ipv4, api_base = _network(root, args.ipv6)
    row = select_release(
        releases(prefix, ipv4=ipv4, base_url=api_base), args.identifier
    )
    set_release(root, row)
    _say(f"{_msg('ui.selected_release')} {row['key']} ({row['date']})")
    _say((_msg('ui.transaction_selection_cleared') + ' run `decor2hl7 list-transactions`'))
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
    _print_table(("KEY", (_msg('ui.selected')), "VERSION", "EFFECTIVE_DATE", (_msg('ui.status')), "NAME", "OID"), table)
    if rows:
        _say((_msg('ui.select_with') + ' decor2hl7 set-transaction <KEY>'))
    return 0 if rows else 1


def cmd_set_transaction(args: argparse.Namespace) -> int:
    from .retrieval.catalog import select_transaction

    root = _root(args)
    row = select_transaction(_transaction_rows(root, args.ipv6), args.identifier)
    set_transaction(root, row)
    _say(
        f"{_msg('ui.selected_transaction')} {row['key']} ({row['id']} @ {row['effective_date'] or 'dynamic'})"
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
        f"{_msg('ui.transaction_closure')} {len(closure.get('build_resources', []))} {_msg('ui.build_resources')}, {len(closure.get('evidence_resources', []))} {_msg('ui.evidence_resources')}"
    )
    if closure.get("truncated"):
        _say((_msg('ui.warning') + ' closure stopped at --max-requests; increase the limit and rerun fetch'))
    if closure.get("crawl_complete") and not closure.get("build_ready", True):
        for error in closure.get("readiness_errors", []):
            _say(f"{_msg('ui.error')} {error}")
    for warning in closure.get("degradation_warnings", []):
        _say(f"{_msg('ui.warning')} {warning}")
    if closure.get("errors"):
        for error in closure.get("errors", []):
            _say(f"{_msg('ui.error')} {error}")
    succeeded = (
        not closure.get("errors")
        and not closure.get("truncated")
        and closure.get("build_ready", True)
    )
    if getattr(args, "fail_on_degraded", False) and closure.get("degraded_resources"):
        _say((_msg('ui.error') + ' --fail-on-degraded rejected the degraded retrieval closure'))
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
    _say(f"{_msg('ui.code_mapping_defaults')} {sum((len(values) for values in code_mapping['fields'].values()))} {_msg('ui.aliases_across')} {len(code_mapping['fields'])} {_msg('ui.coded_fields')}")
    _say(
        f"CDA: {cda['stats']['reachable_templates']} {_msg('ui.reachable_templates')}, {cda['stats']['targets']} {_msg('ui.physical_named_targets')}, {cda['stats'].get('datapoints', 0)} {_msg('ui.logical_mapped_datapoints')}"
    )
    constraint_diagnostics = list(cda.get("constraint_diagnostics", []))
    specialization_diagnostics = [
        row for row in constraint_diagnostics
        if row.get("code") == "spec-constraint-weakening"
    ]
    if specialization_diagnostics:
        _say(
            f"{_msg('ui.warning')} {len(specialization_diagnostics)} CDA SPEC constraint weakening(s); explicit child constraints were used; see {model_dir / 'build-diagnostics.md'}"
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
            f"{_msg('ui.warning')} {len(other_diagnostics)} owner-rule diagnostic(s), {error_count} error-level; see {model_dir / 'build-diagnostics.md'}"
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
            f"{_msg('ui.warning')} degraded build: {summary['build_degraded']} degraded artifacts affect this build, {summary['crawl_degraded']} degraded artifacts in the crawl, {summary['unresolved_templates']} unresolved CDA references; see {model_dir / 'build-diagnostics.md'}"
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
            f"{_msg('ui.error')} --fail-on-degraded rejected the degraded build: {diagnostics['summary']['build_degraded']} degraded artifacts affect this build"
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
    _say(f"{_msg('ui.csv_mapped_proposal')} {sum((value is not None for value in proposals['csv']['fields'].values()))}/{len(model.get('fields', {}))}")
    _say(f"{_msg('ui.input_mapping_proposals_written_to')} {proposal_dir}")
    _say(f"{_msg('ui.input_snapshot_inspected')} {source_root}")
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
            "source_note": Translator().text("cli.input_source_note"),
        },
        "source": {
            "adapter": None,
            "dsn_env": "DECOR2HL7_ODBC_DSN",
            "database": None,
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


@localized
def _copy_generated_guide(
    source: Path,
    destination: Path,
    *,
    output_language: str = "en",
) -> None:
    """Keep generated, read-only guidance beside the configuration it explains."""
    source = _require(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    original = source.read_text(encoding="utf-8")
    content = (original)
    if source.resolve() == destination.resolve() and content == original:
        _say((_msg('ui.kept')) + str(destination))
        return
    destination.write_text(content, encoding="utf-8")
    _say((_msg('ui.updated')) + str(destination))


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


@localized
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
            _copy_generated_guide(
                source, destination.parent / guide_name,
                output_language=output_language,
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
        generated_details.find((_msg('markdown.accepted_mappings') + '\n')),
        generated_details.find("# Akzeptierte mappings\n"),
    )
    analysis_candidates = [
        generated_details.find((_msg('markdown.datapoint_analysis') + '\n')),
        generated_details.find("# Datapoint-Analyse\n"),
    ]
    analysis_start = next(
        (index for index in analysis_candidates if index >= 0), -1
    )
    if 0 <= accepted_start < analysis_start:
        accepted = render_accepted_cda_mappings_markdown(
            model, cda, mapping, output_language=output_language
        ).rstrip()
        rendered["cda-mapping-details.md"] = (generated_details[:accepted_start]
                + accepted
                + "\n\n# Generated proposal evidence\n\n"
                + ('The following audit explains what the compiler could establish without reviewer decisions. It may therefore show a reviewed mapping above as unselected or non-executable in the ' + _msg('ui.generated') + 'proposal.\n\n')
                + generated_details[analysis_start:])
    else:
        rendered["cda-mapping-details.md"] = generated_details

    for guide_name, content in rendered.items():
        target = destination.parent / guide_name
        target.write_text(content, encoding="utf-8")
        _say((_msg('ui.updated')) + str(target))


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
        _say((_msg('ui.reset')) + str(destination))
    else:
        created = copy_if_missing(source, destination)
    if created:
        _say((_msg('ui.created')) + str(destination))
    elif not reset:
        from .compile.mapping import _mapping_configuration_notes
        audit = load_json(_require(model_dir / "mapping-audit.json"))
        notes = _merge_mapping_configuration_notes(
            source,
            destination,
            generated_notes=_mapping_configuration_notes(
                load_json(destination), audit, model, cda
            ),
        )
        changes = []
        if notes:
            changes.append(f"refreshed {notes} configuration note(s)")
        suffix = f" ({'; '.join(changes)})" if changes else ""
        _say((_msg('ui.kept')) + str(destination) + suffix)
        from .compile.mapping import mapping_field_delta
        delta = mapping_field_delta(load_json(destination), load_json(source))
        _report_coverage(
            model, cda, audit, load_json(source), load_json(destination)
        )
        for path in delta["lost"]:
            _say((_msg('ui.review')) + str(path))
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
        _say(((_msg('ui.updated')) if reset else (_msg('ui.created'))) + str(lock))
    else:
        _say((_msg('ui.kept')) + str(lock))
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
            _say((_msg('ui.created')) + str(destination))
        elif name == "codes-mapping":
            added = _merge_code_mapping_defaults(source, destination)
            suffix = f" (+{added} generated defaults)" if added else ""
            _say((_msg('ui.kept')) + str(destination) + suffix)
        else:
            _say((_msg('ui.kept')) + str(destination))
        guide_source = proposal_dir / f"{name}.md"
        _copy_generated_guide(
            guide_source,
            destination.with_suffix(".md"),
            output_language=args.output_language,
        )
    if not site.exists():
        csv_proposal = load_json(proposal_dir / "csv-mapping.proposed.json")
        write_json(site, _site_scaffold(root, release, transaction, csv_proposal))
        _say(f"{_msg('ui.created')}{site}")
    else:
        _say(f"{_msg('ui.kept')}{site}")
    return 0


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
        _out((_msg('ui.cda_source_endpoint_parity_unavailable')))
        return
    _out(
        f"CDA source endpoint parity: {parity.get('compiled', 0)}/{parity.get('declared', 0)} compiled; {len(parity.get('fixed_structural_attributes', []))} {_msg('ui.fixed_structural')}; {len(parity.get('reviewed_branch_replacements', []))} {_msg('ui.reviewed_replacements')}; {len(parity.get('unexpected_missing', []))} {_msg('ui.unexpected_missing')}"
    )


def cmd_check(args: argparse.Namespace) -> int:
    from . import source, validate
    from .bindings import required_unmapped_null_flavor
    from .cda.narrative import narrative_blocks
    from .retrieval.fetch import verify_manifest

    root = _root(args)
    release = selected_release(root)
    runtime_bundle = _runtime_files(
        root, args.cda_mapping, args.site_config
    )
    model, cda = runtime_bundle.model, runtime_bundle.cda
    csv_mapping, codes_mapping = runtime_bundle.csv_mapping, runtime_bundle.codes_mapping
    cda_mapping, site = runtime_bundle.cda_mapping, runtime_bundle.site
    errors = verify_manifest(release_spec_dir(root, release))
    errors.extend(validate.verify_compiled_cda(cda))
    errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    source_errors, parity = _verify_compiled_sources(root, cda)
    errors.extend(source_errors)
    source_config = site.get("source", {})
    if isinstance(source_config, Mapping) and source_config.get("adapter") in ("odbc", "sqlite"):
        bundle, _, _, site_path = _site_paths(
            root, release, selected_transaction(root), args.site_config
        )
        query_problems = source.query_errors(site, bundle)
        errors.extend(query_problems)
        if not query_problems and not validate.check_site(site, cda):
            try:
                source.check_connection(site, site_path.parent, output_language=args.output_language)
                _out(Translator(args.output_language).text(
                    "cli.source_connection_ok", adapter=source_config["adapter"],
                ))
            except ValueError as error:
                errors.append(str(error))
    _out(f"{_msg('ui.model_datapoints')} {len(model.get('fields', {}))}")
    _out(f"CSV mapped: {sum(value is not None for value in csv_mapping.get('fields', {}).values())}")
    _out(f"CDA mapped: {sum(value is not None for value in cda_mapping.get('fields', {}).values())}")
    _out(f"CDA narrative-only mapped: {len(narrative_blocks(cda_mapping))}")
    _out(f"CDA target defaults: {len(cda_mapping.get('target_defaults', {}))}")
    try:
        completion_flavor = required_unmapped_null_flavor(cda_mapping)
    except ValueError:
        completion_flavor = "invalid"
    _out(f"{_msg('ui.required_unmapped_cda_leaves')} nullFlavor={completion_flavor}")
    _out(f"{_msg('ui.cda_unresolved_templates')} {len(cda.get('unresolved_templates', []))}")
    _print_source_parity(parity)
    closure = model.get("meta", {}).get("artifact_closure", {})
    unavailable = closure.get("unavailable_artifacts", []) if isinstance(closure, Mapping) else []
    if isinstance(unavailable, list) and unavailable:
        _out(f"build {_msg('ui.warning')} {len(unavailable)} {_msg('ui.unavailable_dependency_artifacts')}")
    if errors:
        _out((_msg('ui.configuration_errors')))
        for message in errors:
            _out(f"  - {message}")
        return 1
    _out((_msg('ui.configuration_ok')))
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
    try:
        admit_mapping(mapping_path, release, transaction, model, cda)
    except ValueError as error:
        errors.append(str(error))
    _out(f"CDA mapped: {sum(value is not None for value in cda_mapping.get('fields', {}).values())}")
    _out(f"CDA narrative-only mapped: {len(narrative_blocks(cda_mapping))}")
    _out(f"CDA target defaults: {len(cda_mapping.get('target_defaults', {}))}")
    _print_source_parity(parity)
    site_requirements = cda_mapping.get("site_requirements", {})
    site_requirements = (
        site_requirements if isinstance(site_requirements, Mapping) else {}
    )
    _out(f"{_msg('ui.cda_site_requirements')} {len(site_requirements)}")
    for name, rule in sorted(site_requirements.items()):
        channel = (
            str(rule.get("channel") or "?")
            if isinstance(rule, Mapping) else "?"
        )
        _out(f"{_msg('ui.site_config_required')} cda.{channel}[{name!r}]")
    try:
        completion_flavor = required_unmapped_null_flavor(cda_mapping)
    except ValueError:
        completion_flavor = "invalid"
    _out(f"{_msg('ui.required_unmapped_cda_leaves')} nullFlavor={completion_flavor}")
    _out(f"mapping: {mapping_path}")
    if errors:
        _out((_msg('ui.cda_mapping_errors')))
        for message in errors:
            _out(f"  - {message}")
        return 1
    _out((_msg('ui.cda_mapping_ok')))
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
    _say(f"{_msg('ui.test_fixture')} {test_dir}")
    if args.scenario:
        _say(f"{_msg('ui.authored_scenario_set')} {expected['scenario']['name']}")
    _say(f"{_msg('ui.generated')}{len(expected['generated_fields'])} {_msg('ui.model_datapoint_columns')}")
    _say(f"{_msg('ui.cda_mapped_fields_covered_by_input')} {len(expected['mapped_fields'])}")
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
    runtime_bundle = _runtime_files(
        root, args.cda_mapping, args.site_config
    )
    model, cda = runtime_bundle.model, runtime_bundle.cda
    csv_mapping, codes_mapping = runtime_bundle.csv_mapping, runtime_bundle.codes_mapping
    cda_mapping, site = runtime_bundle.cda_mapping, runtime_bundle.site
    errors = validate.verify_compiled_cda(cda)
    errors.extend(validate.check_config(model, cda, csv_mapping, cda_mapping, codes_mapping, site))
    if errors:
        _out((_msg('ui.configuration_errors')))
        for error in errors:
            _out(f"  - {error}")
        return 1
    records = data.ingest(source_root, model, csv_mapping, codes_mapping, site)
    summary = validate.validate_records(records, model)
    _out(f"{_msg('ui.input')} {source_root}")
    _out(f"{_msg('ui.records')} {summary['records']}")
    _out(f"{_msg('ui.errors')} {summary['errors']}")
    _out(f"{_msg('ui.warnings')} {summary['warnings']}")
    for record in records:
        for problem in record.get("problems", []):
            key = record.get("key", "?")
            _out(f"  {problem.get('severity', 'error')}: {key}: {problem.get('path', '')}: {problem.get('message', '')}")
    return 0 if summary["errors"] == 0 else 1


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
    p.add_argument("--version", action="version", version=__version__, help=t("ui.show_program_s_version_number_and_exit"))
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
