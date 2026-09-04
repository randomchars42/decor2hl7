"""CSV ingestion and target-neutral normalization."""

from __future__ import annotations

import csv
import datetime as dt
import math
import re
from pathlib import Path
from typing import Any, Mapping

from .semantics import accepted_values
from .transforms import OMIT, apply_transform, validate_transform

_MISSING = object()
from zoneinfo import ZoneInfo


def _null(flavor: str, raw: Any = None) -> dict[str, Any]:
    value: dict[str, Any] = {"nullFlavor": flavor}
    if raw not in (None, ""):
        value["raw"] = raw
    return value


def is_null(raw: Any, site: Mapping[str, Any]) -> bool:
    if raw is None:
        return True
    text = str(raw).strip()
    options = site.get("input", {})
    if options.get("empty_is_null", True) and not text:
        return True
    literals = {str(value).casefold() for value in options.get("null_values", ["NULL", "NA", "N/A"])}
    return text.casefold() in literals


def _parse_datetime(raw: str, field: Mapping[str, Any], site: Mapping[str, Any]) -> str:
    source = raw.strip()
    if field.get("precision") in {"YMDHM", "YMDHMS"} and len(source) <= 10:
        raise ValueError(f"datetime value {raw!r} has no time of day")
    text = source.replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    value = dt.datetime.fromisoformat(text)
    if value.tzinfo is None:
        zone = str(site.get("timezone") or "Europe/Berlin")
        value = value.replace(tzinfo=ZoneInfo(zone))
    precision = field.get("precision")
    if precision == "YMD":
        return value.date().isoformat()
    if precision in {"YMDHM", "YMDHMS"}:
        timespec = "minutes" if precision == "YMDHM" else "seconds"
        return value.isoformat(timespec=timespec)
    return value.isoformat()


def _parse_date(raw: str) -> str:
    return dt.date.fromisoformat(raw.strip()).isoformat()


def _parse_number(raw: str, site: Mapping[str, Any], integer: bool = False) -> int | float:
    text = raw.strip()
    separator = str(site.get("input", {}).get("decimal_separator") or ".")
    if separator == ",":
        text = text.replace(",", ".")
    number = float(text)
    if integer or number.is_integer():
        return int(number)
    return number


_NUMBER_TOKEN = r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?"
_QUANTITY_RANGE = re.compile(
    rf"^\s*({_NUMBER_TOKEN})\s*(?:\.\.|[-–—])\s*({_NUMBER_TOKEN})(?:\s*(.*?))?\s*$"
)
_QUANTITY_SCALAR = re.compile(
    rf"^\s*({_NUMBER_TOKEN})(?:(?:\s+|(?=[A-Za-zµμ%{{]))(.*?))?\s*$"
)


def _quantity_number(raw: Any, site: Mapping[str, Any], label: str) -> int | float:
    if isinstance(raw, bool):
        raise ValueError(f"quantity {label} must be numeric")
    if isinstance(raw, (int, float)):
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError(f"quantity {label} must be finite")
        return int(raw) if number.is_integer() else number
    text = str(raw).strip()
    if not re.fullmatch(_NUMBER_TOKEN, text):
        raise ValueError(f"quantity {label} {raw!r} is not numeric")
    number = _parse_number(text, site)
    if not math.isfinite(float(number)):
        raise ValueError(f"quantity {label} must be finite")
    return number


def _quantity_unit(raw: Any, fixed: Any) -> str | None:
    unit = str(raw).strip() if raw not in (None, "") else None
    fixed_unit = str(fixed).strip() if fixed not in (None, "") else None
    if unit and fixed_unit and unit != fixed_unit:
        raise ValueError(
            f"quantity unit {unit!r} conflicts with fixed dataset unit {fixed_unit!r}"
        )
    return unit or fixed_unit


def _quantity_bound(
    raw: Any,
    shared_unit: str | None,
    fixed_unit: Any,
    site: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        extra = set(raw) - {"value", "unit"}
        if extra or "value" not in raw:
            raise ValueError(
                f"quantity {label} must contain only value and optional unit"
            )
        value = _quantity_number(raw["value"], site, label)
        unit = _quantity_unit(raw.get("unit") or shared_unit, fixed_unit)
    else:
        value = _quantity_number(raw, site, label)
        unit = _quantity_unit(shared_unit, fixed_unit)
    return {"value": value, **({"unit": unit} if unit else {})}


def _parse_quantity(
    raw: Any, field: Mapping[str, Any], site: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the target-neutral scalar/range quantity representation."""
    fixed_unit = field.get("unit")
    if isinstance(raw, Mapping):
        if raw.get("nullFlavor"):
            return dict(raw)
        if "low" in raw or "high" in raw:
            extra = set(raw) - {"low", "high", "unit"}
            if extra or "low" not in raw or "high" not in raw:
                raise ValueError(
                    "quantity range must contain low, high, and optional unit"
                )
            shared = _quantity_unit(raw.get("unit"), fixed_unit)
            low = _quantity_bound(raw["low"], shared, fixed_unit, site, "low")
            high = _quantity_bound(raw["high"], shared, fixed_unit, site, "high")
            low_unit = low.get("unit")
            high_unit = high.get("unit")
            if low_unit and high_unit and low_unit != high_unit:
                raise ValueError(
                    f"quantity range units differ: {low_unit!r} and {high_unit!r}"
                )
            common = low_unit or high_unit
            if common:
                low.setdefault("unit", common)
                high.setdefault("unit", common)
            if low["value"] > high["value"]:
                raise ValueError("quantity range low exceeds high")
            return {"low": low, "high": high}
        extra = set(raw) - {"value", "unit"}
        if extra or "value" not in raw:
            raise ValueError(
                "quantity must contain value and optional unit, or low and high"
            )
        return _quantity_bound(raw, None, fixed_unit, site, "value")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return _quantity_bound(raw, None, fixed_unit, site, "value")

    text = str(raw).strip()
    match = _QUANTITY_RANGE.fullmatch(text)
    if match:
        unit = _quantity_unit(match.group(3), fixed_unit)
        low = _quantity_bound(match.group(1), unit, fixed_unit, site, "low")
        high = _quantity_bound(match.group(2), unit, fixed_unit, site, "high")
        if low["value"] > high["value"]:
            raise ValueError("quantity range low exceeds high")
        return {"low": low, "high": high}
    match = _QUANTITY_SCALAR.fullmatch(text)
    if match:
        return _quantity_bound(
            match.group(1), match.group(2), fixed_unit, site, "value"
        )
    raise ValueError(
        f"quantity value {raw!r} is neither a scalar nor a low-high range"
    )


def _parse_boolean(raw: str, site: Mapping[str, Any]) -> bool:
    options = site.get("input", {})
    true_values = {str(value).casefold() for value in options.get("true_values", ["1", "true", "yes", "ja", "j"])}
    false_values = {str(value).casefold() for value in options.get("false_values", ["0", "false", "no", "nein", "n"])}
    value = raw.strip().casefold()
    if value in true_values:
        return True
    if value in false_values:
        return False
    raise ValueError(f"unrecognized boolean value {raw!r}")


def _canonical_code(
    raw: str,
    field: Mapping[str, Any],
    translations: Mapping[str, Any],
    site: Mapping[str, Any],
) -> Any:
    values = accepted_values(field)
    canonical = translations.get(raw)
    if canonical is None:
        # Raw data that already uses a canonical dataset label or code does not
        # require an explicit translation entry.
        if raw in values:
            canonical = raw
        else:
            for key, info in values.items():
                if str(info.get("code") or "") == raw or str(info.get("display_name") or "").casefold() == raw.casefold():
                    canonical = key
                    break
    if canonical is None:
        flavor = str(site.get("null_flavor", {}).get("unmapped_code") or "OTH")
        return _null(flavor, raw)
    info = values.get(str(canonical))
    if not info:
        return canonical
    if info.get("code"):
        return {
            "raw": raw,
            "canonical": canonical,
            "code": info.get("code"),
            "codeSystem": info.get("code_system"),
            "displayName": info.get("display_name") or canonical,
        }
    # A textual concept-list option is not a CDA code.  Keep it visible as an
    # unmapped terminology value until codes-mapping.json translates it to a
    # canonical entry that actually carries code + codeSystem.
    flavor = str(site.get("null_flavor", {}).get("unmapped_code") or "OTH")
    return _null(flavor, raw)


def _canonical_ordinal(
    raw: str,
    field: Mapping[str, Any],
    translations: Mapping[str, Any],
    site: Mapping[str, Any],
) -> Any:
    """Normalize a numeric ordinal while preserving user code translations.

    DECOR often expresses GCS-like ordinals as labels such as ``"3 auf
    Aufforderung"`` without a terminology code.  The leading integer is the
    payload expected by numeric CDA value targets.  Coded ordinal value sets
    continue through the ordinary canonical-code path.
    """
    values = accepted_values(field)
    if any(isinstance(info, Mapping) and info.get("code") for info in values.values()):
        return _canonical_code(raw, field, translations, site)
    canonical = translations.get(raw, raw)
    text = str(canonical).strip()
    info = values.get(text)
    if info is None:
        for key, candidate in values.items():
            if str(candidate.get("display_name") or "").casefold() == text.casefold():
                text = str(key); break
    match = re.match(r"^\s*([+-]?\d+(?:[.,]\d+)?)", text)
    if match:
        return _parse_number(match.group(1), site, integer=True)
    return _parse_number(text, site, integer=True)


def normalize_value(
    raw: Any,
    field: Mapping[str, Any],
    translations: Mapping[str, Any],
    site: Mapping[str, Any],
) -> Any:
    if is_null(raw, site):
        return None
    kind = str(field.get("type") or "text")
    if kind == "quantity":
        return _parse_quantity(raw, field, site)
    text = str(raw).strip()
    if kind == "code":
        return _canonical_code(text, field, translations, site)
    if kind == "ordinal":
        return _canonical_ordinal(text, field, translations, site)
    if kind == "datetime":
        return _parse_datetime(text, field, site)
    if kind == "date":
        return _parse_date(text)
    if kind in {"decimal", "duration"}:
        return _parse_number(text, site)
    if kind == "integer":
        return _parse_number(text, site, integer=True)
    if kind == "boolean":
        return _parse_boolean(text, site)
    return text


def mapping_locator(value: Any) -> dict[str, Any] | None:
    """Normalize a CSV mapping entry.

    Version-1 ``SOURCE:COLUMN`` strings remain valid.  Object locators add a
    source datatype and a declarative transform without leaking CSV-specific
    representation into the compiled transaction model.
    """
    if isinstance(value, str) and ":" in value:
        source, column = value.split(":", 1)
        return {"source": source, "column": column}
    if isinstance(value, Mapping) and value.get("source") and value.get("column"):
        return {
            "source": str(value["source"]),
            "column": str(value["column"]),
            **({"parse_as": str(value["parse_as"])} if value.get("parse_as") else {}),
            **({"transform": dict(value["transform"])} if isinstance(value.get("transform"), Mapping) else {}),
        }
    return None


def _normalize_transformed(
    value: Any,
    field: Mapping[str, Any],
    translations: Mapping[str, Any],
    site: Mapping[str, Any],
) -> Any:
    if value is OMIT or value is None:
        return None
    kind = str(field.get("type") or "text")
    if kind == "quantity":
        return _parse_quantity(value, field, site)
    if isinstance(value, Mapping):
        return dict(value)
    if kind == "boolean" and isinstance(value, bool):
        return value
    if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if kind in {"decimal", "duration"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return normalize_value(value, field, translations, site)


def normalize_input_value(
    raw: Any,
    field: Mapping[str, Any],
    translations: Mapping[str, Any],
    site: Mapping[str, Any],
    locator: Mapping[str, Any] | None = None,
) -> Any:
    """Parse a source value, optionally transform it, then validate its model shape."""
    locator = locator or {}
    parse_as = str(locator.get("parse_as") or "")
    transform = locator.get("transform")
    if not parse_as and not transform:
        return normalize_value(raw, field, translations, site)
    source_field = dict(field)
    if parse_as:
        source_field["type"] = parse_as
    parsed = normalize_value(raw, source_field, {}, site)
    if parsed is None:
        return None
    for reason in validate_transform(transform):
        raise ValueError(f"invalid input transform: {reason}")
    transformed = apply_transform(parsed, transform)
    return _normalize_transformed(transformed, field, translations, site)


def _source_spec(
    name: str, input_dir: Path, site: Mapping[str, Any]
) -> tuple[Path, str, str | None, Mapping[str, Any] | None, dict[str, str]]:
    raw = site.get("input", {}).get("sources", {}).get(name)
    if isinstance(raw, str):
        return input_dir / raw, "1:1", None, None, {}
    if isinstance(raw, Mapping):
        primary = raw.get("primary") if isinstance(raw.get("primary"), Mapping) else None
        occurrence = raw.get("occurrence_keys", {})
        occurrence_keys = (
            {str(key): str(value) for key, value in occurrence.items()}
            if isinstance(occurrence, Mapping) else {}
        )
        return (
            input_dir / str(raw.get("file") or f"{name}.csv"),
            str(raw.get("cardinality") or "1:1"),
            raw.get("join_column"),
            primary,
            occurrence_keys,
        )
    return input_dir / f"{name}.csv", "1:1", None, None, {}


def _order_rows(rows: list[dict[str, str]], primary: Mapping[str, Any] | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not primary or not primary.get("column"):
        return rows, []
    column = str(primary["column"])
    true_values = {str(value).casefold() for value in primary.get("true_values", ["1", "true", "yes", "ja", "j"])}
    marked = [index for index, row in enumerate(rows) if str(row.get(column) or "").strip().casefold() in true_values]
    if not marked:
        if primary.get("required"):
            return rows, [{
                "severity": "error", "path": column,
                "message": "no primary row is marked",
            }]
        return rows, []
    if len(marked) > 1:
        return rows, [{
            "severity": "error", "path": column,
            "message": f"multiple primary rows ({len(marked)})",
        }]
    first = marked[0]
    ordered = [dict(rows[first])] + [dict(row) for index, row in enumerate(rows) if index != first]
    return ordered, []


def _read_csv(path: Path, site: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding=str(site.get("input", {}).get("encoding") or "utf-8-sig"), newline="") as handle:
        delimiter = site.get("input", {}).get("delimiter")
        if delimiter:
            reader = csv.DictReader(handle, delimiter=str(delimiter))
            return list(reader), list(reader.fieldnames or [])
        sample = handle.read(8192); handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        return list(reader), list(reader.fieldnames or [])


def field_value(record: Mapping[str, Any], path: str, field: Mapping[str, Any]) -> Any:
    """Return a normalized field value, preserving nested occurrence shape."""
    chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
    if not chain:
        return record.get("values", {}).get(path)

    def collect(instances: Mapping[str, Any], depth: int) -> list[Any]:
        repeat = str(chain[depth])
        rows = instances.get(repeat, []) if isinstance(instances, Mapping) else []
        result: list[Any] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                result.append(None); continue
            if depth == len(chain) - 1:
                result.append(row.get("values", {}).get(path))
            else:
                result.append(collect(row.get("instances", {}), depth + 1))
        return result

    return collect(record.get("instances", {}), 0)


def _ensure_occurrence(
    instances: dict[str, list[dict[str, Any]]],
    chain: list[str],
    keys: list[str],
    source: str,
    row_number: int,
) -> dict[str, Any]:
    current = instances
    selected: dict[str, Any] | None = None
    for depth, repeat in enumerate(chain):
        key = keys[depth]
        bucket = current.setdefault(str(repeat), [])
        selected = next((item for item in bucket if str(item.get("key") or "") == key), None)
        if selected is None:
            selected = {
                "key": key, "source": source, "row": row_number,
                "values": {}, "instances": {},
            }
            bucket.append(selected)
        current = selected.setdefault("instances", {})
    assert selected is not None
    return selected

def ingest(
    input_dir: Path,
    model: Mapping[str, Any],
    csv_mapping: Mapping[str, Any],
    codes_mapping: Mapping[str, Any],
    site: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Read configured CSV sources into normalized records.

    Repeating dataset groups are represented as occurrence rows instead of
    independent field lists.  This preserves positional identity when one
    value in an occurrence is absent.
    """
    groups = model.get("groups", {})

    locators = [
        locator for value in csv_mapping.get("fields", {}).values()
        if (locator := mapping_locator(value)) is not None
    ]
    source_name_set = {str(locator["source"]) for locator in locators}
    configured_case_source = site.get("input", {}).get("case_source")
    if configured_case_source:
        source_name_set.add(str(configured_case_source))
    source_names = sorted(source_name_set)
    default_join = str(csv_mapping.get("join", {}).get("column") or site.get("input", {}).get("join_column") or "patient_id")
    source_rows: dict[str, dict[str, Any]] = {}
    mapped_columns: dict[str, set[str]] = {}
    for value in csv_mapping.get("fields", {}).values():
        locator = mapping_locator(value)
        if locator is not None:
            mapped_columns.setdefault(str(locator["source"]), set()).add(str(locator["column"]))
    for name in source_names:
        path, cardinality, source_join, primary, occurrence_keys = _source_spec(name, input_dir, site)
        if cardinality not in {"1:1", "1:n"}:
            raise ValueError(f"source {name!r} has invalid cardinality {cardinality!r}")
        if not path.exists():
            raise FileNotFoundError(f"mapped source {name!r} not found: {path}")
        rows, headers = _read_csv(path, site)
        join = str(source_join or default_join)
        required_columns = set(mapped_columns.get(name, set())) | {join}
        if primary and primary.get("column"):
            required_columns.add(str(primary["column"]))
        required_columns.update(occurrence_keys.values())
        missing_columns = sorted(required_columns - set(headers))
        if missing_columns:
            raise ValueError(f"source {name!r} ({path.name}) is missing required CSV column(s): " + ", ".join(missing_columns))
        grouped: dict[str, list[dict[str, str]]] = {}
        empty_key_rows: list[int] = []
        for row_number, row in enumerate(rows, 2):
            key = str(row.get(join) or "").strip()
            if not key:
                empty_key_rows.append(row_number); continue
            copy = dict(row); copy["__decor2hl7_row__"] = str(row_number)
            grouped.setdefault(key, []).append(copy)
        if empty_key_rows:
            shown = ", ".join(str(value) for value in empty_key_rows[:10]); more = " ..." if len(empty_key_rows) > 10 else ""
            raise ValueError(f"source {name!r} has empty join key {join!r} on row(s) {shown}{more}")
        if cardinality == "1:1":
            duplicates = sorted((key, len(group)) for key, group in grouped.items() if len(group) > 1)
            if duplicates:
                sample = ", ".join(f"{key} ({count} rows)" for key, count in duplicates[:10])
                raise ValueError(f"source {name!r} is configured 1:1 but has duplicate key(s): {sample}")
        source_problems: dict[str, list[dict[str, str]]] = {}
        if cardinality == "1:n" and primary:
            for key, group in list(grouped.items()):
                ordered, row_problems = _order_rows(group, primary); grouped[key] = ordered
                if row_problems: source_problems[key] = row_problems
        source_rows[name] = {"cardinality": cardinality, "rows": grouped, "problems": source_problems, "occurrence_keys": occurrence_keys}
    if not source_names:
        return []
    configured_case = site.get("input", {}).get("case_source")
    if configured_case:
        case_source = str(configured_case)
        if case_source not in source_rows:
            raise ValueError(f"configured case source {case_source!r} is not available")
    else:
        one_to_one = [name for name in source_names if source_rows[name]["cardinality"] == "1:1"]
        if len(one_to_one) == 1: case_source = one_to_one[0]
        elif len(source_names) == 1: case_source = source_names[0]
        else: raise ValueError("multiple CSV sources are mapped; configure site.input.case_source to define the record universe")
    if source_rows[case_source]["cardinality"] != "1:1":
        raise ValueError(f"case source {case_source!r} must have cardinality 1:1")
    keys = list(source_rows[case_source]["rows"]); case_keys = set(keys)
    for name, source_data in source_rows.items():
        if name == case_source: continue
        orphans = sorted(set(source_data["rows"]) - case_keys)
        if orphans:
            raise ValueError(f"source {name!r} contains key(s) absent from case source {case_source!r}: " + ", ".join(orphans[:10]))

    # Repeating groups may span multiple files only when every participating
    # 1:n source supplies explicit occurrence keys for the full repeat chain.
    repeat_sources: dict[str, set[str]] = {}
    for field_path, field in model.get("fields", {}).items():
        chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
        locator = mapping_locator(csv_mapping.get("fields", {}).get(field_path))
        if not chain or locator is None:
            continue
        source = str(locator["source"])
        if source_rows.get(source, {}).get("cardinality") != "1:n":
            continue
        for repeat in chain:
            repeat_sources.setdefault(str(repeat), set()).add(source)
        keys_cfg = source_rows[source].get("occurrence_keys", {})
        if len(chain) > 1:
            missing = [str(repeat) for repeat in chain if str(repeat) not in keys_cfg]
            if missing:
                raise ValueError(
                    f"source {source!r} maps nested repetitions for {field_path!r} but lacks "
                    "occurrence_keys for: " + ", ".join(missing)
                )

    for repeat, sources in repeat_sources.items():
        if len(sources) <= 1:
            continue
        for source in sources:
            if repeat not in source_rows[source].get("occurrence_keys", {}):
                raise ValueError(
                    f"repeating group {repeat!r} spans multiple sources; source {source!r} "
                    "must configure an occurrence key"
                )

    records: list[dict[str, Any]] = []
    for key in keys:
        values: dict[str, Any] = {}
        instances: dict[str, list[dict[str, Any]]] = {}
        problems: list[dict[str, str]] = []
        for source_data in source_rows.values():
            problems.extend(source_data.get("problems", {}).get(key, []))
        for field_path, field in model.get("fields", {}).items():
            locator = mapping_locator(csv_mapping.get("fields", {}).get(field_path))
            mapped_source: str | None = None
            mapped_column: str | None = None
            mapped_rows: list[dict[str, str]] = []
            cardinality = "1:1"
            if locator is not None:
                mapped_source = str(locator["source"])
                mapped_column = str(locator["column"])
                source_data = source_rows.get(mapped_source, {})
                mapped_rows = list(source_data.get("rows", {}).get(key, []))
                cardinality = str(source_data.get("cardinality") or "1:1")
            translations = codes_mapping.get("fields", {}).get(field_path, {})
            chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))

            if chain and mapped_source is not None and mapped_column is not None:
                occurrence_rows = (
                    mapped_rows if cardinality == "1:n" else mapped_rows[:1]
                )
                keys_cfg = source_rows.get(mapped_source, {}).get(
                    "occurrence_keys", {}
                )
                for index, row in enumerate(occurrence_rows):
                    row_number = int(row.get("__decor2hl7_row__") or 0)
                    occurrence_ids: list[str] = []
                    for depth, repeat in enumerate(chain):
                        column_name = keys_cfg.get(str(repeat))
                        if column_name:
                            occurrence_key = str(row.get(column_name) or "").strip()
                            if not occurrence_key:
                                raise ValueError(
                                    f"source {mapped_source!r} has empty occurrence key {column_name!r} "
                                    f"for repeat {repeat!r} on row {row_number}"
                                )
                        elif len(chain) == 1 and len(repeat_sources.get(str(repeat), set())) == 1:
                            occurrence_key = f"#{index}"
                        else:
                            raise ValueError(
                                f"source {mapped_source!r} requires occurrence_keys[{repeat!r}] for {field_path!r}"
                            )
                        occurrence_ids.append(occurrence_key)
                    leaf_key = tuple(occurrence_ids)
                    occurrence = _ensure_occurrence(
                        instances,
                        [str(item) for item in chain],
                        occurrence_ids,
                        mapped_source,
                        row_number,
                    )
                    raw = row.get(mapped_column)
                    try:
                        normalized = normalize_input_value(raw, field, translations, site, locator)
                    except (ValueError, TypeError) as error:
                        problems.append({
                            "severity": "error", "path": f"{field_path}[{index}]",
                            "message": str(error),
                        })
                        normalized = None
                    if normalized is None and field.get("required"):
                        flavor = str(site.get("null_flavor", {}).get("missing_required") or "NI")
                        normalized = _null(flavor)
                    existing = occurrence["values"].get(field_path, _MISSING)
                    if existing is not _MISSING and existing != normalized:
                        raise ValueError(
                            f"source {mapped_source!r} gives conflicting values for occurrence {leaf_key!r} "
                            f"and field {field_path!r}: {existing!r} vs {normalized!r}"
                        )
                    occurrence["values"][field_path] = normalized
                continue

            raw = (
                mapped_rows[0].get(mapped_column)
                if mapped_rows and mapped_column is not None
                else None
            )
            try:
                normalized = (
                    normalize_input_value(raw, field, translations, site, locator)
                    if mapped_source is not None
                    else None
                )
            except (ValueError, TypeError) as error:
                problems.append({"severity": "error", "path": field_path, "message": str(error)})
                normalized = None
            if normalized is not None:
                values[field_path] = normalized
            elif field.get("required") and not chain:
                flavor = str(site.get("null_flavor", {}).get("missing_required") or "NI")
                values[field_path] = _null(flavor)

        records.append({"key": key, "values": values, "instances": instances, "problems": problems})
    return records
