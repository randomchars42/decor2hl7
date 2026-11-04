"""Input-to-document execution, pending handover and committed lineage."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence
from . import __version__
from .hashing import json_digest as _json_digest
from .pending import read_pending
from .contracts import RuntimeBundle, SiteConfig, site_config
from .i18n import message as _msg, Translator, OUTPUT_LANGUAGE as _OUTPUT_LANGUAGE
from .ui import say as _say
from .runtime_config import _require, _explicit_path, _site_paths, _runtime_files, _safe_key
from .workspace import (selected_release, selected_transaction, state_dir, transaction_out_dir,
                        input_dir, load_json, write_json, write_bytes)

def _state_key(transaction: Mapping[str, Any], record_key: str) -> str:
    # Transaction identity, not release identity: a later release of the same
    # transaction should still detect unchanged/corrected source records.
    return f"{transaction['id']}::{record_key}"


def _prune_stale_pending(out_dir: Path, state_key: str, fingerprint: str, state_path: Path) -> int:
    """Remove only uncommitted artifacts for an older source state."""
    from .state import delivered_artifacts

    committed = delivered_artifacts(state_path)
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
        if (state_key, info.get("document_version"), info.get("fingerprint")) in committed:
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
    committed = state.delivered_artifacts(state_path)
    for sidecar in out_dir.glob("*.json"):
        try:
            info = load_json(sidecar)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        stream_key = str(info.get("state_key") or "")
        if not stream_key or stream_key in current_keys:
            continue
        if (stream_key, info.get("document_version"), info.get("fingerprint")) in committed:
            continue
        xml = sidecar.with_suffix(".xml")
        if xml.exists():
            xml.unlink()
        sidecar.unlink()
        removed += 1
    return removed


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


def _reuse_pending_document(path: Path, expected: Mapping[str, Any]) -> bool:
    """Preserve the exact handover bytes until delivery has been committed."""
    sidecar = path.with_suffix(".json")
    if not path.is_file() or not sidecar.is_file():
        return False
    info = read_pending(path)
    if any(info.get(key) != value for key, value in expected.items()):
        raise ValueError(Translator(_OUTPUT_LANGUAGE.get()).text(
            "cli.pending_metadata_inconsistent", path=path,
        ))
    return True


def _recover_spool_publications(
    root: Path, out_dir: Path, site: Mapping[str, Any],
    site_config_override: str | Path | None,
    cda_mapping_override: str | Path | None,
    runtime_bundle: RuntimeBundle,
) -> int:
    from . import state, transport

    if transport.configured_name(site) != "spool":
        return 0
    recovered = 0
    for path in sorted(out_dir.glob("*.xml")):
        sidecar = path.with_suffix(".json")
        if not sidecar.is_file():
            continue
        info = read_pending(path)
        stream_key = str(info.get("state_key") or "")
        disposition, version = state.classify(state_dir(root), stream_key, str(info.get("fingerprint") or ""))
        if disposition == "UNCHANGED" or info.get("document_version") != version:
            continue
        if transport.is_published(path, site, workspace=root):
            # This records a handover that already happened. Do it before
            # pruning, even if today's source changed or the case is absent.
            sent, failed = _send_paths(
                root, [path], site_config_override, cda_mapping_override,
                runtime_bundle=runtime_bundle,
            )
            if failed:
                raise ValueError(Translator(_OUTPUT_LANGUAGE.get()).text(
                    "cli.spool_recovery_failed", path=path,
                ))
            recovered += sent
    return recovered


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
    runtime_bundle: RuntimeBundle | None = None,
) -> tuple[list[Path], dict[str, int]]:
    from .cda.render import emit
    from . import data, state, validate

    release = selected_release(root)
    transaction = selected_transaction(root)
    bundle = runtime_bundle or _runtime_files(
        root, cda_mapping_override, site_config_override
    )
    model, cda = bundle.model, bundle.cda
    csv_mapping, codes_mapping = bundle.csv_mapping, bundle.codes_mapping
    cda_mapping, site = bundle.cda_mapping, bundle.site
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
    recovered = (
        _recover_spool_publications(
            root, out_dir, site, site_config_override, cda_mapping_override, bundle
        )
        if not dry_run else 0
    )
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
            _prune_stale_pending(out_dir, stream_key, digest, state_path)
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
            raise ValueError(_msg('ui.committed_identity_missing', stream_key=stream_key))
        stem = f"{_safe_key(raw_key)}-v{document_version}"
        xml_path = out_dir / f"{stem}.xml"
        identity = _document_identity(raw_key, document_version, site)
        artifact = {
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
        }
        if _reuse_pending_document(xml_path, artifact):
            emitted.append(xml_path)
            continue
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
        write_bytes(xml_path, payload)
        write_json(out_dir / f"{stem}.json", {
            **artifact,
            "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
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
        "recovered": recovered,
    }


def _new_run_id() -> str:
    return (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-" + uuid.uuid4().hex[:8]
    )


def _failure_threshold(site: SiteConfig) -> int:
    operation = site.get("operation") or {}
    return operation.get("failure_threshold") or 0


def transform_documents(
    root: Path, *, input_override: str | Path | None = None,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None,
) -> int:
    from . import state

    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(state_dir(root), run_id, kind="transform")
        try:
            runtime_bundle = _runtime_files(
                root, cda_mapping_override, site_config_override
            )
            emitted, summary = _transform(
                root, input_override, cda_mapping_override, site_config_override,
                run_id=run_id, runtime_bundle=runtime_bundle,
            )
            threshold = _failure_threshold(runtime_bundle.site)
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
    cda_mapping_override: str | Path | None = None,
    *, runtime_bundle: RuntimeBundle | None = None,
) -> tuple[int, int]:
    from . import state, transport

    release = selected_release(root)
    transaction = selected_transaction(root)
    bundle = runtime_bundle or _runtime_files(
        root, cda_mapping_override, site_config_override
    )
    site = bundle.site
    error = transport.configuration_error(site)
    if error:
        raise ValueError(error)
    out_dir = transaction_out_dir(root, release, transaction)
    candidates = paths if paths is not None else sorted(out_dir.glob("*.xml"))
    sent = failed = 0
    for path in candidates:
        sidecar_path = path.with_suffix(".json")
        if not sidecar_path.exists():
            _say(f"{_msg('ui.skip')}{path.name}: no sidecar")
            failed += 1
            continue
        try:
            info = read_pending(path)
        except ValueError as error:
            _say(str(error))
            failed += 1
            continue
        if info["transaction"] != transaction or info["release"] != release["key"]:
            _say(_msg("ui.pending_bundle_mismatch", path=path))
            failed += 1
            continue
        raw_key = str(info["key"])
        stream_key = str(info["state_key"])
        disposition, expected_version = state.classify(
            state_dir(root), stream_key, str(info["fingerprint"])
        )
        if disposition == "UNCHANGED":
            continue
        document_version = int(info["document_version"])
        expected_identity = _document_identity(raw_key, document_version, site)
        if document_version != expected_version:
            _say(
                f"{_msg('ui.send_failed')}{path.name}: artifact version {document_version} does not match next committed version {expected_version}"
            )
            failed += 1
            continue
        if (
            info.get("document_id") != expected_identity["document_id"]
            or info.get("set_id") != expected_identity["set_id"]
        ):
            _say(f"{_msg('ui.send_failed')}{path.name}: artifact CDA identity is missing or inconsistent")
            failed += 1
            continue
        if document_version > 1:
            committed_previous = state.previous_document(state_dir(root), stream_key)
            if committed_previous is None:
                raise ValueError(_msg('ui.committed_identity_missing', stream_key=stream_key))
            if info.get("previous_document") != committed_previous:
                _say(f"{_msg('ui.send_failed')}{path.name}: replacement lineage does not match committed state")
                failed += 1
                continue
        ok, message = transport.send(path, site, workspace=root)
        if not ok:
            _say(f"{_msg('ui.send_failed')}{path.name}: {message}")
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


def send_documents(
    root: Path, *, files: Sequence[str] = (),
    site_config_override: str | Path | None = None,
) -> int:
    from . import state

    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(state_dir(root), run_id, kind="send")
        try:
            sent, failed = _send_paths(
                root, [Path(value) for value in files] if files else None,
                site_config_override,
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


def run_documents(
    root: Path, *, input_override: str | Path | None = None,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None, send: bool = False,
) -> int:
    from . import state

    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(state_dir(root), run_id, kind="run")
        try:
            runtime_bundle = _runtime_files(
                root, cda_mapping_override, site_config_override
            )
            if send:
                from .transport import configuration_error
                site = runtime_bundle.site
                error = configuration_error(site)
                if error:
                    raise ValueError(error)
            emitted, summary = _transform(
                root, input_override, cda_mapping_override, site_config_override,
                run_id=run_id, runtime_bundle=runtime_bundle,
            )
            print(json.dumps(summary, ensure_ascii=False))
            failed = 0
            if send:
                sent, failed = _send_paths(
                    root, emitted, site_config_override, cda_mapping_override,
                    runtime_bundle=runtime_bundle,
                )
                print(json.dumps({"sent": sent, "failed": failed}))
            threshold = _failure_threshold(runtime_bundle.site)
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
    if send:
        return 0 if ok else 2
    _say((_msg('ui.documents_were_emitted_but_not_sent_pass_send')))
    return 0 if ok else 2


def _source_site(
    root: Path,
    site_config_override: str | Path | None,
) -> tuple[Path, Path, SiteConfig]:
    from . import source, validate

    release = selected_release(root)
    transaction = selected_transaction(root)
    bundle, _, _, site_path = _site_paths(
        root, release, transaction, site_config_override
    )
    site = site_config(load_json(_require(site_path, "run `decor2hl7 init-site-config`")))
    errors = validate.check_site(site)
    errors.extend(source.query_errors(site, bundle))
    if errors:
        raise ValueError(
            "source runtime configuration is invalid:\n"
            + "\n".join("  " + item for item in errors)
        )
    return bundle, site_path.parent, site


def extract_source_snapshot(
    root: Path, *, output_path: str | Path, since: dt.date | None = None,
    site_config_override: str | Path | None = None, output_language: str = "en",
) -> int:
    from . import source, state

    bundle, config_dir, site = _source_site(root, site_config_override)
    output = _explicit_path(output_path)
    run_id = _new_run_id()
    with state.workspace_lock(state_dir(root)):
        state.start_run(
            state_dir(root), run_id, kind="extract-source",
            snapshot_path=str(output),
        )
        try:
            manifest = source.extract(
                site, bundle, output, since=since,
                config_dir=config_dir, output_language=output_language,
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


def run_source(
    root: Path, *, since: dt.date | None = None,
    snapshot_output: str | Path | None = None,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None, limit: int | None = None,
    dry_run: bool = False, send: bool = False, output_language: str = "en",
) -> int:
    from . import source, state

    bundle, config_dir, site = _source_site(root, site_config_override)
    if dry_run and send:
        raise ValueError("--dry-run and --send cannot be combined")
    runtime_bundle = _runtime_files(
        root, cda_mapping_override, site_config_override
    )
    if send:
        from .transport import configuration_error
        error = configuration_error(site)
        if error:
            raise ValueError(error)
    run_id = _new_run_id()
    snapshot = (
        _explicit_path(snapshot_output)
        if snapshot_output else state_dir(root) / "snapshots" / run_id
    )
    with state.workspace_lock(state_dir(root)):
        state.start_run(
            state_dir(root), run_id, kind="run-source",
            snapshot_path=str(snapshot),
        )
        manifest: dict[str, Any] | None = None
        source_stream: str | None = None
        try:
            manifest = source.extract(
                site, bundle, snapshot, since=since,
                config_dir=config_dir, output_language=output_language,
            )
            source_config = site.get("source", {})
            require_advance = (
                bool(source_config.get("require_snapshot_advance", True))
                if isinstance(source_config, Mapping) else True
            )
            maximum = manifest.get("snapshot_max_ts")
            transaction = selected_transaction(root)
            source_stream = _json_digest({
                "transaction": {
                    "id": transaction["id"],
                    "effective_date": transaction.get("effective_date"),
                },
                "source_identity_sha256": manifest["source_identity_sha256"],
            })
            previous_maximum = state.last_snapshot_max_ts(state_dir(root), source_stream)
            if not dry_run and require_advance and previous_maximum is not None:
                if maximum is None or str(maximum) <= previous_maximum:
                    raise ValueError(
                        "source snapshot has not advanced: last completed "
                        f"maximum {previous_maximum!r}, current {maximum!r}"
                    )

            snapshot_evidence = {"path": str(snapshot), **manifest}
            emitted, summary = _transform(
                root, snapshot, cda_mapping_override, site_config_override,
                run_id=run_id, limit=limit, dry_run=dry_run,
                source_snapshot=snapshot_evidence,
                prune_absent=False, runtime_bundle=runtime_bundle,
            )
            print(json.dumps(summary, ensure_ascii=False))
            sent = failed = 0
            if send:
                sent, failed = _send_paths(
                    root, emitted, site_config_override, cda_mapping_override,
                    runtime_bundle=runtime_bundle,
                )
                print(json.dumps({"sent": sent, "failed": failed}))
            threshold = _failure_threshold(site)
            failure_count = int(summary["invalid"]) + failed
            ok = failure_count <= threshold
            status = (
                "failed" if not ok else
                "inspected" if dry_run else
                "partial" if limit is not None else
                "completed" if send else "transformed"
            )
            state.finish_run(
                state_dir(root), run_id, status=status,
                summary={
                    **summary, "sent": sent, "delivery_failed": failed,
                },
                snapshot_path=str(snapshot),
                snapshot_max_ts=(str(maximum) if maximum is not None else None),
                source_stream=source_stream,
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
                source_stream=source_stream,
            )
            raise
    if not send and not dry_run:
        _say("documents were emitted but not delivered; pass --send for handover")
    return 0 if ok else 2


def runtime_status(
    root: Path,
) -> int:
    from . import state

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


