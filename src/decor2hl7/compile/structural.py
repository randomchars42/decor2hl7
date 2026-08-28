"""Infer reusable occurrence rules from model/CDA cardinality evidence."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from ..retrieval.xml import child_text, local, parse_file
from ..transforms import selected_cda_targets


def value_set_members(xml_paths: Iterable[Path]) -> dict[str, list[dict[str, str]]]:
    """Collect exact coded members used to prove discriminator rules."""
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in sorted(set(xml_paths)):
        try:
            root, _ = parse_file(path)
        except ET.ParseError:
            continue
        for value_set in root.iter():
            if local(value_set.tag) != "valueSet" or not value_set.get("id"):
                continue
            oid = value_set.get("id") or ""
            for concept in value_set.iter():
                if local(concept.tag) not in {"concept", "items"}:
                    continue
                code = concept.get("code") or ""
                system = concept.get("codeSystem") or ""
                if not code or not system:
                    continue
                display = concept.get("displayName") or child_text(concept, "name") or code
                row = {"code": code, "codeSystem": system, "displayName": display}
                if row not in result[oid]:
                    result[oid].append(row)
    return result


def _side_of(path: str, field: Mapping[str, Any]) -> str | None:
    text = " ".join(
        str(value or "") for value in (
            path, field.get("name"), field.get("description"), field.get("short_name"),
        )
    ).casefold()
    if re.search(r"(?:^|[^a-z])(rechts|right)(?:[^a-z]|$)", text):
        return "right"
    if re.search(r"(?:^|[^a-z])(links|left)(?:[^a-z]|$)", text):
        return "left"
    return None


def _side_member(
    members: Iterable[Mapping[str, str]], side: str
) -> dict[str, str] | None:
    for member in members:
        code = str(member.get("code") or "").casefold()
        label = str(member.get("displayName") or "").casefold()
        if side == "right" and (code == "r" or "right" in label or "rechts" in label):
            return dict(member)
        if side == "left" and (code == "l" or "left" in label or "links" in label):
            return dict(member)
    return None


def rule_id(prefix: str, target: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", target.casefold()).strip("-")
    return f"{prefix}-{slug}"[:120]


def occurrence_target(target: str, branch: str) -> str:
    """Name one logical occurrence of a repeatable CDA schema target."""
    head, separator, tail = target.partition(".")
    label = re.sub(r"[^a-z0-9]+", "_", branch.casefold()).strip("_")
    return f"{head}_{label}{separator}{tail}" if separator else f"{target}_{label}"


def fanout_rule(
    paths: list[str],
    target_name: str,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    value_sets: Mapping[str, list[dict[str, str]]],
) -> tuple[str, dict[str, Any]] | None:
    target = cda.get("targets", {}).get(target_name, {})
    fields = model.get("fields", {})
    depths = {len(fields.get(path, {}).get("repeat_chain", [])) for path in paths}
    if len(depths) != 1 or len(target.get("repeat_ancestors", [])) != next(iter(depths)) + 1:
        return None
    sides = {path: _side_of(path, fields.get(path, {})) for path in paths}
    if set(sides.values()) != {"left", "right"} or len(paths) != 2:
        return None
    parent_path = str(target.get("path") or "").rsplit("/", 1)[0]
    discriminator: tuple[str, dict[str, str], dict[str, str]] | None = None
    for name, candidate in cda.get("targets", {}).items():
        if name == target_name or not candidate.get("renderable"):
            continue
        if candidate.get("repeat_ancestors", []) != target.get("repeat_ancestors", []):
            continue
        if str(candidate.get("path") or "").rsplit("/", 1)[0] != parent_path:
            continue
        members = [
            member for oid in candidate.get("value_sets", [])
            for member in value_sets.get(str(oid), [])
        ]
        left = _side_member(members, "left")
        right = _side_member(members, "right")
        if left and right:
            discriminator = str(name), left, right
            break
    if discriminator is None:
        return None
    discriminator_name, left, right = discriminator
    rule_name = rule_id("fan-out", target_name)
    branches = []
    for side in ("right", "left"):
        path = next(path for path, value in sides.items() if value == side)
        branches.append({
            "source": path,
            "target": occurrence_target(target_name, side),
            "cda_target": target_name,
            "branch": side,
            "constants": {discriminator_name: right if side == "right" else left},
        })
    return rule_name, {
        "type": "fan_out",
        "evidence": [
            "shared repeatable CDA value target",
            "one additional CDA repeat level",
            f"required side discriminator {discriminator_name}",
        ],
        "branches": branches,
    }


def coalesce_rule(
    paths: list[str], target_name: str, model: Mapping[str, Any], cda: Mapping[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    target = cda.get("targets", {}).get(target_name, {})
    fields = model.get("fields", {})
    if target.get("repeat_ancestors") or any(
        fields.get(path, {}).get("repeat_chain") for path in paths
    ):
        return None
    types = {str(fields.get(path, {}).get("type") or "") for path in paths}
    if len(types) != 1 or types.pop() not in {
        "datetime", "date", "integer", "decimal", "text", "identifier",
    }:
        return None
    rule_name = rule_id("coalesce", target_name)
    return rule_name, {
        "type": "coalesce",
        "sources": list(paths),
        "target": target_name,
        "policy": "equal_or_error",
        "evidence": ["shared singleton CDA target", "compatible source datatypes"],
    }


def for_each_rules(
    model: Mapping[str, Any], cda: Mapping[str, Any], fields: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    targets = cda.get("targets", {})
    for group_path, group in model.get("groups", {}).items():
        if not group.get("repeating"):
            continue
        members = [
            path for path, field in model.get("fields", {}).items()
            if group_path in field.get("repeat_chain", []) and fields.get(path) is not None
        ]
        if not members:
            continue
        depths = [
            model["fields"][path].get("repeat_chain", []).index(group_path)
            for path in members
        ]
        if len(set(depths)) != 1:
            continue
        source_depth = depths[0]
        repeat_locations: set[str] = set()
        for path in members:
            selected = selected_cda_targets(fields[path])
            if not selected:
                continue
            ancestors = targets.get(selected[0], {}).get("repeat_ancestors", [])
            if source_depth >= len(ancestors):
                break
            repeat_locations.add(str(ancestors[source_depth]))
        else:
            if len(repeat_locations) != 1:
                continue
            location = next(iter(repeat_locations))
            anchor = next((
                name for name, target in targets.items()
                if target.get("locations") == [location]
            ), location)
            rule_name = rule_id("for-each", group_path)
            result[rule_name] = {
                "type": "for_each",
                "source_group": group_path,
                "target_repeat": anchor,
                "evidence": ["matching source and CDA repeat depth"],
            }
    return result
