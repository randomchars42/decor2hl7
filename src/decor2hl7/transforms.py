"""Small declarative value transforms for model-to-CDA mappings.

Transforms are intentionally data-only and side-effect free.  Mapping files may
use a direct target name or a rule object::

    {"target": "SomeTarget", "transform": {"type": "enum", "map": {"yes": false}}}

A field may map to several rule objects when one source value controls several
CDA constraints (for example ``negationInd`` plus ``nullFlavor``).
"""
from __future__ import annotations

from typing import Any, Mapping

OMIT = object()


class _ReviewedCodedMapAuthorization:
    """In-memory capability created only by the reviewed coded-map transform."""


_REVIEWED_CODED_MAP_AUTHORIZATION = _ReviewedCodedMapAuthorization()
_REVIEWED_CODED_MAP_MARKER = "__decor2hl7_reviewed_coded_map__"


def mapping_rules(value: Any) -> list[dict[str, Any]]:
    """Normalize a mapping value to rule dictionaries.

    Direct strings are the concise form; objects carry transforms and structure.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            out.append({"target": item})
        elif isinstance(item, Mapping) and item.get("target"):
            out.append(dict(item))
    return out


def cda_target_name(rule: Mapping[str, Any]) -> str:
    """Return the physical CDA target behind a logical target occurrence.

    Most mappings use the same name for both.  Structural mappings may expose
    distinct reviewable occurrences such as ``Pupilsize_right.value`` and
    ``Pupilsize_left.value`` while both are rendered through the repeatable
    schema target ``Pupilsize.value``.
    """
    return str(rule.get("cda_target") or rule.get("target") or "")


def selected_cda_targets(value: Any) -> list[str]:
    """Return physical CDA targets selected by one mapping value."""
    return [cda_target_name(rule) for rule in mapping_rules(value)]


def _selected_value(value: Any, transform: Mapping[str, Any]) -> Any:
    """Select the part of a normalized value used as a transform key.

    The old implicit order is retained when ``select`` is absent.  If a known
    logical choice has no formal terminology code, normalization preserves its
    canonical/raw label; use that label as the final implicit key. An explicit selector is
    important for terminology transforms:
    a user-facing canonical label may change while the formal code (for example
    ``A`` or ``Z``) does not.
    """
    selector = str(transform.get("select") or "")
    if selector:
        if selector == "value":
            return value
        if not isinstance(value, Mapping):
            return None
        aliases = {
            "display_name": ("display_name", "displayName"),
            "displayName": ("displayName", "display_name"),
        }
        for key in aliases.get(selector, (selector,)):
            if value.get(key) is not None:
                return value.get(key)
        return None
    if isinstance(value, Mapping):
        return (
            value.get("canonical")
            or value.get("displayName")
            or value.get("display_name")
            or value.get("code")
            or value.get("raw")
        )
    return value


def _table_value(table: Mapping[Any, Any], key: Any) -> tuple[bool, Any]:
    candidates = [key, str(key)]
    if isinstance(key, bool):
        candidates.extend([str(key).lower(), "1" if key else "0"])
    for candidate in candidates:
        try:
            if candidate in table:
                return True, table[candidate]
        except TypeError:
            continue
    return False, None


def _wording(value: Any) -> Any:
    """Return the portable human wording of one normalized scalar value."""
    if isinstance(value, Mapping):
        if "low" in value or "high" in value:
            low = value.get("low", {})
            high = value.get("high", {})
            if isinstance(low, Mapping) and isinstance(high, Mapping):
                low_value = low.get("value")
                high_value = high.get("value")
                unit = low.get("unit") or high.get("unit")
                if low_value is not None and high_value is not None:
                    return (
                        f"{low_value}-{high_value}"
                        + (f" {unit}" if unit else "")
                    )
        if "value" in value:
            scalar = value.get("value")
            if scalar is not None:
                unit = value.get("unit")
                return f"{scalar}" + (f" {unit}" if unit else "")
        return next((
            value.get(key) for key in (
                "raw", "canonical", "displayName", "display_name", "code",
            )
            if value.get(key) not in (None, "")
        ), None)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _reviewed_coded_map(value: Any, transform: Mapping[str, Any]) -> Any:
    """Apply one finite, concept-identity-pinned reviewed code mapping.

    Human labels are used only to locate the exact source concept identity
    recorded in ``source_options``. The actual conversion table is keyed by
    those owner concept identities. Configuration validation proves complete
    source-option coverage and the exact target binding before runtime.
    """
    source_options = transform.get("source_options", {})
    cases = transform.get("map", {})
    if not isinstance(source_options, Mapping) or not isinstance(cases, Mapping):
        raise ValueError(
            "reviewed_coded_map requires source_options and an object map"
        )
    source_label = _selected_value(value, {"select": "canonical"})
    found, concept_id = _table_value(source_options, source_label)
    if not found or concept_id in (None, ""):
        raise ValueError(
            f"reviewed_coded_map has no source concept for {source_label!r}"
        )
    case = cases.get(str(concept_id))
    if not isinstance(case, Mapping) or not isinstance(case.get("value"), Mapping):
        raise ValueError(
            f"reviewed_coded_map has no target value for source concept {concept_id!r}"
        )
    result = dict(case["value"])
    raw = value
    if isinstance(value, Mapping):
        raw = next((
            value.get(key) for key in (
                "raw", "canonical", "displayName", "display_name", "code",
            )
            if value.get(key) not in (None, "")
        ), None)
    if raw not in (None, ""):
        result["raw"] = raw

    binding = transform.get("value_set", {})
    binding = binding if isinstance(binding, Mapping) else {}
    binding_key = "@".join((
        str(binding.get("id") or ""),
        str(binding.get("effective_date") or ""),
    ))
    payload = (
        str(result.get("nullFlavor") or ""),
        str(result.get("code") or ""),
        str(result.get("codeSystem") or ""),
    )
    result[_REVIEWED_CODED_MAP_MARKER] = {
        "authorization": _REVIEWED_CODED_MAP_AUTHORIZATION,
        "binding": binding_key,
        "payload": payload,
    }
    return result


def reviewed_coded_map_binding(value: Any) -> str:
    """Return the exact binding authorized by a genuine transformed value.

    The identity-only sentinel cannot be supplied through JSON site/default
    configuration. The payload comparison also prevents an authorized value
    from being changed after the transform.
    """
    if not isinstance(value, Mapping):
        return ""
    marker = value.get(_REVIEWED_CODED_MAP_MARKER)
    if (
        not isinstance(marker, Mapping)
        or marker.get("authorization") is not _REVIEWED_CODED_MAP_AUTHORIZATION
    ):
        return ""
    actual = (
        str(value.get("nullFlavor") or ""),
        str(value.get("code") or ""),
        str(value.get("codeSystem") or ""),
    )
    if tuple(marker.get("payload") or ()) != actual:
        return ""
    return str(marker.get("binding") or "")


def _scalar(value: Any, transform: Mapping[str, Any]) -> Any:
    kind = str(transform.get("type") or "identity")
    if kind == "identity":
        return value
    if kind == "enum":
        table = transform.get("map", {})
        if not isinstance(table, Mapping):
            raise ValueError("enum transform requires an object map")
        key = _selected_value(value, transform)
        found, result = _table_value(table, key)
        if not found and "default" in transform:
            result = transform.get("default")
            found = True
        if not found:
            return OMIT
        return OMIT if result is None else result
    if kind == "ordinal":
        table = transform.get("map", {})
        key = _selected_value(value, transform)
        found, raw = _table_value(table, key) if isinstance(table, Mapping) else (False, None)
        if found:
            if raw is None:
                return OMIT
            return int(raw) if str(raw).lstrip("+-").isdigit() else float(raw)
        if isinstance(value, (int, float)):
            return value
        raise ValueError(f"ordinal transform has no score for {key!r}")
    if kind == "not":
        if isinstance(value, bool):
            return not value
        raise ValueError("not transform requires a boolean value")
    if kind == "code_system":
        code_system = str(transform.get("code_system") or "")
        if not code_system:
            raise ValueError("code_system transform requires code_system")
        code = _selected_value(
            value, {**dict(transform), "select": transform.get("select") or "raw"}
        )
        if code in (None, "") and isinstance(value, Mapping):
            code = value.get("code")
        if code in (None, ""):
            return OMIT
        coded_result: dict[str, Any] = {
            "code": str(code),
            "codeSystem": code_system,
        }
        if isinstance(value, Mapping):
            display = value.get("displayName") or value.get("display_name")
            if display:
                coded_result["displayName"] = display
            if value.get("raw") is not None:
                coded_result["raw"] = value.get("raw")
        return coded_result
    if kind == "coded_fallback":
        configured_allowed = transform.get("allowed", [])
        allowed = [
            item for item in configured_allowed
            if isinstance(item, Mapping)
        ] if isinstance(configured_allowed, list) else []
        code = value.get("code") if isinstance(value, Mapping) else None
        system = None
        if isinstance(value, Mapping):
            system = value.get("codeSystem") or value.get("code_system")
        matches = [
            item for item in allowed
            if str(item.get("code") or "") == str(code or "")
            and str(item.get("codeSystem") or "") == str(system or "")
        ]
        if code not in (None, "") and system not in (None, "") and len(matches) == 1:
            result = {
                key: matches[0][key]
                for key in ("code", "codeSystem", "displayName")
                if matches[0].get(key) not in (None, "")
            }
            if isinstance(value, Mapping) and value.get("raw") not in (None, ""):
                result["raw"] = value["raw"]
            return result
        raw = value
        if isinstance(value, Mapping):
            raw = next((
                value.get(key) for key in (
                    "raw", "canonical", "displayName", "display_name", "code",
                )
                if value.get(key) not in (None, "")
            ), None)
        result = {
            "nullFlavor": str(transform.get("null_flavor") or "OTH"),
        }
        if raw not in (None, ""):
            result["raw"] = raw
        return result
    if kind == "coded_only":
        if not isinstance(value, Mapping):
            return OMIT
        code = value.get("code")
        system = value.get("codeSystem") or value.get("code_system")
        if code in (None, "") or system in (None, ""):
            return OMIT
        result = {"code": str(code), "codeSystem": str(system)}
        display = value.get("displayName") or value.get("display_name")
        if display not in (None, ""):
            result["displayName"] = display
        if value.get("raw") not in (None, ""):
            result["raw"] = value["raw"]
        return result
    if kind == "coded_or_original_text":
        if isinstance(value, Mapping):
            code = value.get("code")
            system = value.get("codeSystem") or value.get("code_system")
            if code not in (None, "") and system not in (None, ""):
                result = {
                    "code": str(code), "codeSystem": str(system),
                }
                display = value.get("displayName") or value.get("display_name")
                if display not in (None, ""):
                    result["displayName"] = display
                raw = _wording(value)
                if raw not in (None, ""):
                    result["raw"] = raw
                return result
        raw = _wording(value)
        if raw in (None, ""):
            return OMIT
        return {
            "nullFlavor": str(transform.get("null_flavor") or "OTH"),
            "raw": str(raw),
        }
    if kind == "narrative":
        if transform.get("only_if_uncoded") and isinstance(value, Mapping):
            if value.get("code") and (
                value.get("codeSystem") or value.get("code_system")
            ):
                return OMIT
        wording = _wording(value)
        if wording in (None, ""):
            return OMIT
        return str(transform.get("prefix") or "") + str(wording)
    if kind == "reviewed_coded_map":
        return _reviewed_coded_map(value, transform)
    raise ValueError(f"unknown mapping transform {kind!r}")


def apply_transform(value: Any, transform: Mapping[str, Any] | None) -> Any:
    """Apply a transform recursively while preserving repetition shape."""
    if not transform:
        return value
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            transformed = apply_transform(item, transform) if item is not None else OMIT
            out.append(None if transformed is OMIT else transformed)
        return out
    if value is None:
        return OMIT
    return _scalar(value, transform)


def validate_transform(transform: Any) -> list[str]:
    if transform is None:
        return []
    if not isinstance(transform, Mapping):
        return ["transform must be an object"]
    kind = str(transform.get("type") or "")
    if kind not in {
        "identity", "enum", "ordinal", "not", "code_system",
        "coded_fallback", "coded_only", "coded_or_original_text",
        "narrative", "reviewed_coded_map",
    }:
        return [f"unknown transform type {kind!r}"]
    if kind in {"enum", "ordinal"} and not isinstance(transform.get("map"), Mapping):
        return [f"{kind} transform requires an object map"]
    if kind == "code_system" and not str(transform.get("code_system") or ""):
        return ["code_system transform requires code_system"]
    if kind == "coded_fallback":
        allowed = transform.get("allowed")
        if not isinstance(allowed, list) or not all(
            isinstance(item, Mapping)
            and item.get("code")
            and item.get("codeSystem")
            for item in allowed
        ):
            return ["coded_fallback transform requires coded allowed members"]
        if not str(transform.get("null_flavor") or ""):
            return ["coded_fallback transform requires null_flavor"]
    if kind == "coded_or_original_text" and not str(
        transform.get("null_flavor") or ""
    ):
        return ["coded_or_original_text transform requires null_flavor"]
    if kind == "reviewed_coded_map":
        binding = transform.get("value_set")
        if (
            not isinstance(binding, Mapping)
            or not str(binding.get("id") or "")
            or not str(binding.get("effective_date") or "")
        ):
            return [
                "reviewed_coded_map requires one exact value_set id and effective_date"
            ]
        reason = transform.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return ["reviewed_coded_map requires a non-empty review reason"]
        source_options = transform.get("source_options")
        if (
            not isinstance(source_options, Mapping)
            or not source_options
            or not all(
                str(label) and str(concept_id)
                for label, concept_id in source_options.items()
            )
            or len({str(value) for value in source_options.values()})
            != len(source_options)
        ):
            return [
                "reviewed_coded_map requires unique source label-to-concept identities"
            ]
        cases = transform.get("map")
        if not isinstance(cases, Mapping):
            return ["reviewed_coded_map requires an object map"]
        expected = {str(value) for value in source_options.values()}
        if {str(key) for key in cases} != expected:
            return [
                "reviewed_coded_map map must cover exactly every configured source concept"
            ]
        for concept_id, case in cases.items():
            if not isinstance(case, Mapping):
                return [
                    f"reviewed_coded_map case {concept_id!r} must be an object"
                ]
            case_reason = case.get("reason")
            if not isinstance(case_reason, str) or not case_reason.strip():
                return [
                    f"reviewed_coded_map case {concept_id!r} requires a review reason"
                ]
            output = case.get("value")
            if not isinstance(output, Mapping):
                return [
                    f"reviewed_coded_map case {concept_id!r} requires an object value"
                ]
            flavor = str(output.get("nullFlavor") or "")
            code = str(output.get("code") or "")
            system = str(output.get("codeSystem") or "")
            if bool(flavor) == bool(code or system) or bool(code) != bool(system):
                return [
                    f"reviewed_coded_map case {concept_id!r} must contain either "
                    "nullFlavor or both code and codeSystem"
                ]
    selector = transform.get("select")
    if selector is not None and selector not in {
        "value", "canonical", "code", "displayName", "display_name",
        "raw",
    }:
        return [f"unknown transform selector {selector!r}"]
    return []
