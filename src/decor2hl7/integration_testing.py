"""Assemble independent runtime rehearsals from reviewed artifacts and scenarios."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import tempfile
from typing import Any

from .bundle import admit_mapping
from .compile.artifacts import compiler_inputs
from .contracts import cda_model, dataset_model, target_mapping
from .hashing import json_digest, sha256_file
from .i18n import message as _msg
from .retrieval.fetch import verify_manifest
from .runtime_config import cda_mapping_path, require_path
from .scenario import packaged_scenario
from .sqlite_fixture import create_source
from .testing import setup_fixture
from . import validate
from .workspace import (
    load_json, load_settings, release_site_dir, release_spec_dir,
    selected_release, selected_transaction, transaction_mapping_dir,
    transaction_model_dir, transaction_site_dir, transaction_spec_dir, write_json,
)


def setup_integration_test(
    root: Path, output: Path, *, scenario: str = "valid-reference-cases",
    written_at: str = "2026-06-01T12:00:00Z",
    cda_mapping_override: str | Path | None = None,
    receiver_url: str | None = None,
) -> dict[str, Any]:
    """Stage a fresh synthetic SQLite source and independent reviewed workspace.

    No source site configuration, runtime state, or delivery output is copied.
    Publication follows complete scenario, bundle, source and site admission.
    """
    root, output = root.resolve(), output.expanduser().resolve()
    if output.exists():
        raise ValueError(_msg("cli.integration_output_exists", path=output))
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError(_msg("cli.integration_output_overlap"))
    release, transaction = selected_release(root), selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    model = dataset_model(load_json(require_path(model_dir / "model.json")))
    cda = cda_model(load_json(require_path(model_dir / "cda.json")))
    mapping_path = cda_mapping_path(root, release, transaction, cda_mapping_override)
    mapping = target_mapping(load_json(require_path(mapping_path)))
    admit_mapping(mapping_path, release, transaction, model, cda)
    scenario_path = Path(scenario).expanduser()
    if not scenario_path.is_dir():
        scenario_path = packaged_scenario(release["key"], transaction["key"], scenario)
    scenario_path = scenario_path.resolve()
    if output.is_relative_to(scenario_path) or scenario_path.is_relative_to(output):
        raise ValueError(_msg("cli.integration_output_overlap"))
    spec_dir = release_spec_dir(root, release)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as tmp:
        staging = Path(tmp) / "test"
        staging.mkdir()
        shutil.copytree(scenario_path, staging / "scenario")
        fixture = staging / "fixture"
        expected = setup_fixture(
            fixture, release, transaction, model, cda, mapping,
            scenario_dir=staging / "scenario",
        )
        # Provenance paths are relative to this generated test directory; no
        # temporary or installation path is needed to run it later.
        expected["scenario"]["source"] = "scenario"
        write_json(fixture / "expected.json", expected)
        workspace = staging / "workspace"
        bundle = transaction_site_dir(workspace, release, transaction)
        evidence = create_source(fixture, bundle, written_at=written_at)
        database = staging / "input" / "source.sqlite"
        database.parent.mkdir()
        (bundle / "source.sqlite").rename(database)
        site = load_json(bundle / "site.json")
        site_dir = release_site_dir(workspace, release)
        site["source"]["database"] = os.path.relpath(database, site_dir)
        # This window is only for fixed synthetic input. Instructions also use
        # an explicit lower bound so runs remain repeatable as time advances.
        site["source"]["window_days"] = 36500
        site["transport"] = {"adapter": "spool", "directory": "spool"}
        if receiver_url is not None:
            site["transport"] = {
                "adapter": "http-post", "url": receiver_url, "timeout": 120,
                "headers": {"Content-Type": "text/xml; charset=utf-8", "Accept": "text/xml"},
            }
        (bundle / "site.json").unlink()
        write_json(site_dir / "site.json", site)
        errors = validate.verify_compiled_cda(cda)
        errors.extend(validate.check_config(
            model, cda, load_json(bundle / "csv-mapping.json"), mapping,
            load_json(bundle / "codes-mapping.json"), site,
        ))
        if errors:
            raise ValueError(_msg("cli.integration_invalid", details="\n".join(errors)))
        errors = verify_manifest(spec_dir)
        if errors:
            raise ValueError(_msg("cli.integration_invalid", details="\n".join(errors)))
        compiler_inputs(spec_dir, transaction_spec_dir(root, release, transaction))

        settings = load_settings(root)
        settings["input"] = {"directory": "../fixture/input"}
        write_json(workspace / "decor2hl7.json", settings)
        shutil.copytree(spec_dir, release_spec_dir(workspace, release))
        target_model = transaction_model_dir(workspace, release, transaction)
        target_model.mkdir(parents=True)
        for name in ("model.json", "cda.json"):
            shutil.copyfile(model_dir / name, target_model / name)
        if (model_dir / "conformance-validation").is_dir():
            shutil.copytree(model_dir / "conformance-validation", target_model / "conformance-validation")
        target_mapping_dir = transaction_mapping_dir(workspace, release, transaction)
        target_mapping_dir.mkdir(parents=True)
        for source, name in ((mapping_path, "cda-mapping.json"), (mapping_path.parent / "mapping-lock.json", "mapping-lock.json")):
            shutil.copyfile(source, target_mapping_dir / name)
        if (root / "config").is_dir():
            shutil.copytree(root / "config", workspace / "config")

        for path, original in (
            (target_model / "model.json", model),
            (target_model / "cda.json", cda),
            (target_mapping_dir / "cda-mapping.json", mapping),
        ):
            if json_digest(load_json(path)) != json_digest(original):
                raise ValueError(_msg("cli.integration_source_changed"))
        admit_mapping(target_mapping_dir / "cda-mapping.json", release, transaction, model, cda)
        copied_spec = release_spec_dir(workspace, release)
        errors = verify_manifest(copied_spec)
        if errors:
            raise ValueError(_msg("cli.integration_invalid", details="\n".join(errors)))
        compiler_inputs(copied_spec, transaction_spec_dir(workspace, release, transaction))

        prefix = ["decor2hl7", "--root", str(output / "workspace")]
        since = evidence["written_at"][:10]
        commands = {
            "check": shlex.join([*prefix, "check"]),
            "prepare": shlex.join([*prefix, "run-source", "--since", since]),
            "publish": shlex.join([*prefix, "run-source", "--since", since, "--send"]),
            "status": shlex.join([*prefix, "status"]),
        }
        receiver_note = _msg("markdown.integration_receiver_note") if receiver_url else ""
        (staging / "README.md").write_text(_msg(
            "markdown.integration_instructions", check=commands["check"],
            prepare=commands["prepare"], publish=commands["publish"],
            status=commands["status"], receiver_note=receiver_note,
        ), encoding="utf-8")
        result = {
            "version": 1, "synthetic": True,
            "release": release, "transaction": transaction,
            **evidence,
            "workspace": "workspace", "database": "input/source.sqlite",
            "fixture": "fixture", "transport": site["transport"],
            "model_sha256": json_digest(model), "cda_sha256": json_digest(cda),
            "mapping_sha256": json_digest(mapping),
            "files": {
                str(path.relative_to(staging)): sha256_file(path)
                for path in sorted(staging.rglob("*")) if path.is_file()
            },
        }
        write_json(staging / "integration-test.json", result)
        if output.exists():
            raise ValueError(_msg("cli.integration_output_exists", path=output))
        staging.rename(output)
    return result
