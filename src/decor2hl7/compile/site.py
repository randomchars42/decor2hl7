"""Propose site-local CSV and input-code mappings from a compiled model."""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from ..domain import accepted_values
from ..workspace import write_json


def _norm(value: str) -> str:
    value = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _headers(input_dir: Path | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if input_dir is None or not input_dir.exists():
        return out
    for path in sorted(input_dir.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(handle, dialect)
            out[path.stem] = next(reader, [])
    return out


def _best_column(
    path: str,
    field: Mapping[str, Any],
    headers: Mapping[str, list[str]],
) -> tuple[str | None, float, list[tuple[float, str]]]:
    needles = {_norm(path.rsplit(".", 1)[-1]), _norm(str(field.get("name") or ""))}
    scored: list[tuple[float, str]] = []
    for source, columns in headers.items():
        for column in columns:
            norm = _norm(column)
            if not norm:
                continue
            score = max(
                difflib.SequenceMatcher(None, needle, norm).ratio()
                for needle in needles
                if needle
            )
            if norm in needles:
                score = 1.0
            scored.append((score, f"{source}:{column}"))
    scored.sort(reverse=True)
    if not scored:
        return None, 0.0, []
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    selected = (
        best[1]
        if best[0] >= 0.78 and (best[0] - second >= 0.05 or best[0] == 1.0)
        else None
    )
    return selected, best[0], scored[:5]


def csv_mapping_proposal(
    model: Mapping[str, Any],
    input_dir: Path | None,
    join_column: str,
) -> tuple[dict[str, Any], str]:
    headers = _headers(input_dir)
    fields: dict[str, Any] = {}
    detail: dict[str, tuple[float, list[tuple[float, str]]]] = {}
    for path, field in model.get("fields", {}).items():
        selected, score, candidates = _best_column(path, field, headers)
        value: Any = selected
        semantic_text = " ".join(
            str(field.get(key) or "")
            for key in (
                "name",
                "short_name",
                "description",
                "comment",
                "implementation",
            )
        ).casefold()
        boolean_rank = (
            selected is not None
            and str(field.get("type") or "") == "integer"
            and (field.get("min_value") is None or float(field.get("min_value")) >= 1)
            and (
                "führende" in semantic_text
                or "fuehrende" in semantic_text
                or "hauptdiagnose" in semantic_text
            )
            and (
                "sequenz" in semantic_text
                or "rank" in semantic_text
                or "führende" in semantic_text
            )
        )
        if boolean_rank and selected:
            observed = {
                item.casefold()
                for item in _read_column_values(input_dir, selected)
                if item.strip()
            }
            boolean_literals = {
                "0",
                "1",
                "true",
                "false",
                "yes",
                "no",
                "ja",
                "nein",
                "j",
                "n",
            }
            if observed and observed <= boolean_literals:
                source, column = selected.split(":", 1)
                value = {
                    "source": source,
                    "column": column,
                    "parse_as": "boolean",
                    "transform": {
                        "type": "enum",
                        "select": "value",
                        "map": {"true": 1, "false": None},
                    },
                }
        fields[path] = value
        detail[path] = score, candidates
    proposal = {
        "version": 2,
        "model": {
            "dataset_id": model.get("meta", {}).get("dataset_id"),
            "transaction_id": model.get("meta", {}).get("transaction_id"),
            "effective_date": model.get("meta", {}).get(
                "transaction_effective_date"
            ),
        },
        "join": {"column": join_column},
        "fields": fields,
    }
    lines = [
        "# CSV-to-dataset mapping",
        "",
        "Edit `csv-mapping.json`. Each row connects one dataset datapoint to one",
        "input column; parsing is shown only when it changes the input value.",
        "",
        f"Mapped automatically: **{sum(value is not None for value in fields.values())}/{len(fields)}**.",
        "",
        "| Dataset datapoint | CSV source and column | Parsing or review note |",
        "|---|---|---|",
    ]
    for path, field in model.get("fields", {}).items():
        value = fields[path]
        if value:
            display = (
                f"{value.get('source')}:{value.get('column')}"
                if isinstance(value, Mapping)
                else str(value)
            )
            parsing = (
                f"Parse as `{value.get('parse_as')}` and apply "
                f"`{value.get('transform', {}).get('type')}` transform"
                if isinstance(value, Mapping) and value.get("parse_as")
                else "Direct"
            )
            lines.append(
                f"| {field.get('name') or path} (`{path}`) | `{display}` | "
                f"{parsing} |"
            )
        else:
            alternatives = ", ".join(
                f"{name} ({candidate_score:.2f})"
                for candidate_score, name in detail[path][1][:3]
            ) or "none"
            lines.append(
                f"| {field.get('name') or path} (`{path}`) | — | "
                f"Review candidates: {alternatives} |"
            )
    lines += [
        "",
        "Candidate scores are suggestions only. Unmapped rows remain `null` in the JSON",
        "until a user chooses a source column.",
        "",
    ]
    return proposal, "\n".join(lines) + "\n"


def _read_column_values(input_dir: Path | None, locator: str) -> set[str]:
    source, column = locator.split(":", 1)
    if input_dir is None:
        return set()
    path = input_dir / f"{source}.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return {
            str(row.get(column, "")).strip()
            for row in csv.DictReader(handle, dialect=dialect)
            if str(row.get(column, "")).strip()
        }


def _code_mapping_defaults_for_field(field: Mapping[str, Any]) -> dict[str, str]:
    """Return model-derived raw aliases for one coded field."""
    values = accepted_values(field)
    candidates: dict[str, set[str]] = defaultdict(set)
    canonical_names = {str(value) for value in values}

    def add(alias: Any, canonical: Any) -> None:
        alias_text = str(alias or "").strip()
        canonical_text = str(canonical or "").strip()
        if alias_text and canonical_text in canonical_names:
            candidates[alias_text].add(canonical_text)

    for canonical, raw_info in values.items():
        canonical_text = str(canonical)
        info = raw_info if isinstance(raw_info, Mapping) else {}
        add(canonical_text, canonical_text)

        code = str(info.get("code") or "").strip()
        if code:
            add(code, canonical_text)

        display = str(info.get("display_name") or "").strip()
        if display and display != canonical_text:
            add(display, canonical_text)
        for synonym in info.get("synonyms", []):
            add(synonym, canonical_text)

    logical_domain = field.get("logical_domain", {})
    logical_options = (
        logical_domain.get("options", {})
        if isinstance(logical_domain, Mapping)
        else {}
    )
    if isinstance(logical_options, Mapping):
        for label, raw_option in logical_options.items():
            option = raw_option if isinstance(raw_option, Mapping) else {}
            association = option.get("terminology_association", {})
            if not isinstance(association, Mapping):
                continue
            add(label, association.get("canonical"))
            for synonym in option.get("synonyms", []):
                add(synonym, association.get("canonical"))

    defaults: dict[str, str] = {}
    for alias, destinations in candidates.items():
        if alias in canonical_names:
            defaults[alias] = alias
        elif len(destinations) == 1:
            defaults[alias] = next(iter(destinations))
    return defaults


def code_mapping_defaults(model: Mapping[str, Any]) -> dict[str, Any]:
    """Build the input-independent code mapping scaffold from the model."""
    fields: dict[str, dict[str, str]] = {}
    for path, field in model.get("fields", {}).items():
        values = accepted_values(field)
        has_terminology_codes = any(
            isinstance(info, Mapping) and bool(info.get("code"))
            for info in values.values()
        )
        if field.get("type") not in {"code", "ordinal"} and not has_terminology_codes:
            continue
        if not values:
            continue
        fields[path] = _code_mapping_defaults_for_field(field)
    return {"version": 1, "fields": fields}


def codes_mapping_proposal(
    model: Mapping[str, Any],
    csv_mapping: Mapping[str, Any],
    input_dir: Path | None,
) -> tuple[dict[str, Any], str]:
    proposal = code_mapping_defaults(model)
    fields: dict[str, dict[str, str | None]] = {
        path: dict(values) for path, values in proposal["fields"].items()
    }
    lines = [
        "# Input-value-to-dataset-code mapping",
        "",
        "Edit `codes-mapping.json`. Canonical dataset values are accepted unchanged;",
        "the tables therefore show only aliases that require translation and unresolved",
        "input values observed in the CSV files. An unresolved value in a finite domain",
        "is an input error; source normalization does not choose an HL7 missing-data code.",
        "",
    ]

    for path, translations in fields.items():
        field = model.get("fields", {}).get(path, {})
        values = accepted_values(field)
        locator = csv_mapping.get("fields", {}).get(path)
        locator_text: str | None
        if (
            isinstance(locator, Mapping)
            and locator.get("source")
            and locator.get("column")
        ):
            locator_text = f"{locator['source']}:{locator['column']}"
        else:
            locator_text = locator if isinstance(locator, str) else None
        raw_values = (
            _read_column_values(input_dir, locator_text) if locator_text else set()
        )

        by_norm: dict[str, str] = {}
        by_code: dict[str, str] = {}
        for canonical, raw_info in values.items():
            canonical_text = str(canonical)
            info = raw_info if isinstance(raw_info, Mapping) else {}
            by_norm.setdefault(_norm(canonical_text), canonical_text)
            display = str(info.get("display_name") or "").strip()
            if display:
                by_norm.setdefault(_norm(display), canonical_text)
            code = str(info.get("code") or "").strip()
            if code:
                by_code.setdefault(code, canonical_text)

        for raw in sorted(raw_values):
            translations.setdefault(raw, by_code.get(raw) or by_norm.get(_norm(raw)))

        observed_mapped = sum(translations.get(raw) is not None for raw in raw_values)
        lines.append(f"## {field.get('name') or path}")
        lines.append("")
        lines.append(
            f"`{path}` — "
            f"{sum(raw == canonical for raw, canonical in translations.items())} "
            f"canonical values accepted directly; {observed_mapped}/{len(raw_values)} "
            "observed input values mapped."
        )
        lines.append("")
        shown = [
            (raw, canonical)
            for raw, canonical in translations.items()
            if canonical is None or raw != canonical
        ]
        if shown:
            lines += [
                "| Input value | Dataset value |",
                "|---|---|",
            ]
            for raw, destination_value in shown:
                destination = (
                    f"`{destination_value}`"
                    if destination_value
                    else "**UNRESOLVED — outside executable dataset domain**"
                )
                lines.append(f"| `{raw}` | {destination} |")
        else:
            lines.append("No aliases require configuration.")
        lines.append("")

    return {"version": 1, "fields": fields}, "\n".join(lines) + "\n"


def write_code_mapping(model_dir: Path, model: Mapping[str, Any]) -> dict[str, Any]:
    """Write the model-derived code mapping before any CSV inspection."""
    proposal, report = codes_mapping_proposal(model, {"fields": {}}, None)
    write_json(model_dir / "codes-mapping.proposed.json", proposal)
    (model_dir / "codes-mapping.md").write_text(report, encoding="utf-8")
    return proposal


def write_input_mappings(
    output_dir: Path,
    input_dir: Path,
    model: Mapping[str, Any],
    *,
    join_column: str = "patient_id",
) -> dict[str, Any]:
    """Inspect one CSV snapshot and write only input-side mapping proposals."""
    csv_proposal, csv_report = csv_mapping_proposal(model, input_dir, join_column)
    code_proposal, code_report = codes_mapping_proposal(
        model, csv_proposal, input_dir
    )
    write_json(output_dir / "csv-mapping.proposed.json", csv_proposal)
    write_json(output_dir / "codes-mapping.proposed.json", code_proposal)
    (output_dir / "csv-mapping.md").write_text(csv_report, encoding="utf-8")
    (output_dir / "codes-mapping.md").write_text(code_report, encoding="utf-8")
    return {"csv": csv_proposal, "codes": code_proposal}
