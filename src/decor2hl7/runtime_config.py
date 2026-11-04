"""Resolve the selected workspace files and admit a reviewed runtime bundle."""
from __future__ import annotations
import argparse
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping
from .bundle import admit_mapping
from .contracts import (RuntimeBundle, dataset_model, cda_model, input_mapping,
                        code_mapping, target_mapping, site_config)
from .workspace import (selected_release, selected_transaction, transaction_model_dir,
                        transaction_mapping_dir, transaction_site_dir, release_site_dir, load_json)

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


def _runtime_files(
    root: Path,
    cda_mapping_override: str | Path | None = None,
    site_config_override: str | Path | None = None,
) -> RuntimeBundle:
    release = selected_release(root)
    transaction = selected_transaction(root)
    model_dir = transaction_model_dir(root, release, transaction)
    _, csv_path, codes_path, site_path = _site_paths(
        root, release, transaction, site_config_override
    )
    mapping_path = _cda_mapping_path(
        root, release, transaction, cda_mapping_override
    )
    model = dataset_model(load_json(_require(model_dir / "model.json", "run `decor2hl7 build`")))
    cda = cda_model(load_json(_require(model_dir / "cda.json", "run `decor2hl7 build`")))
    csv_mapping = input_mapping(load_json(_require(csv_path, "run `decor2hl7 init-site-config`")))
    codes_mapping = code_mapping(load_json(_require(codes_path, "run `decor2hl7 init-site-config`")))
    cda_mapping = target_mapping(load_json(_require(mapping_path, "run `decor2hl7 init-cda-mapping`")))
    site = site_config(load_json(_require(site_path, "run `decor2hl7 init-site-config`")))
    admit_mapping(mapping_path, release, transaction, model, cda)
    return RuntimeBundle(model, cda, csv_mapping, codes_mapping, cda_mapping, site)


