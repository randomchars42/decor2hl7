"""Infer reusable occurrence rules from model/CDA cardinality evidence."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

from ..retrieval.xml import child_text, local, parse_file
from ..retrieval.expansion import normalized_value_sets
from ..cda.semantics import binding_strength
from ..transforms import mapping_rules, selected_cda_targets


ValueSetKey = str | tuple[str, str]


def value_set_members(
    xml_paths: Iterable[Path],
) -> dict[ValueSetKey, list[dict[str, Any]]]:
    """Index coded members by value-set OID *and* effective version.

    The plain OID key indexes the latest version; specification-driven rules
    use the tuple key and never mix revisions.
    """
    exact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    identities: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for path in sorted(set(xml_paths)):
        try:
            root, _ = parse_file(path)
        except ET.ParseError:
            continue
        value_sets = (
            normalized_value_sets(root)
            if local(root.tag) == "valueSetExpansionSet"
            else [
                node for node in root.iter()
                if local(node.tag) == "valueSet"
            ]
        )
        for value_set in value_sets:
            if local(value_set.tag) != "valueSet" or not value_set.get("id"):
                continue
            oid = value_set.get("id") or ""
            effective = value_set.get("effectiveDate") or ""
            for concept in value_set.iter():
                kind = local(concept.tag)
                if kind == "items":
                    kind = str(concept.get("is") or "concept")
                if kind not in {"concept", "exception"}:
                    continue
                if str(concept.get("type") or "").upper() == "A":
                    continue
                code = concept.get("code") or ""
                system = concept.get("codeSystem") or ""
                if not code or not system:
                    continue
                display = concept.get("displayName") or child_text(concept, "name") or code
                designations = [
                    {
                        "displayName": item.get("displayName") or "",
                        "language": item.get("language") or "",
                    }
                    for item in concept.iter()
                    if local(item.tag) == "designation" and item.get("displayName")
                ]
                row: dict[str, Any] = {
                    "code": code,
                    "codeSystem": system,
                    "displayName": display,
                    "kind": kind,
                    "designations": designations,
                    "valueSet": oid,
                    "valueSetEffectiveDate": effective,
                }
                identity = oid, effective, code, system
                previous = identities.get(identity)
                if previous is None:
                    exact[(oid, effective)].append(row)
                    identities[identity] = row
                else:
                    # Source items and analysis concepts represent the same
                    # exact member. Keep every designation without creating
                    # competing discriminator candidates. Exceptions remain
                    # exceptions across representations.
                    if kind == "exception":
                        previous["kind"] = kind
                    if display != previous["displayName"]:
                        designations = [
                            {"displayName": display, "language": ""},
                            *designations,
                        ]
                    for designation in designations:
                        if designation not in previous["designations"]:
                            previous["designations"].append(designation)
    result: dict[ValueSetKey, list[dict[str, Any]]] = {}
    for key, values in exact.items():
        result[key] = list(values)
    by_oid: dict[str, list[str]] = defaultdict(list)
    for oid, effective in exact:
        by_oid[oid].append(effective)
    for oid, versions in by_oid.items():
        selected = max(versions)
        result[oid] = list(exact[(oid, selected)])
    return result


def _tokens(value: str) -> set[str]:
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-zÄÖÜäöüß]+", value)
        if len(token) >= 2
    }


def _member_tokens(member: Mapping[str, Any]) -> set[str]:
    values = [str(member.get("displayName") or "")]
    values.extend(
        str(item.get("displayName") or "")
        for item in member.get("designations", [])
        if isinstance(item, Mapping)
    )
    return set().union(*(_tokens(value) for value in values))


def members_for_target(
    target: Mapping[str, Any],
    value_sets: Mapping[ValueSetKey, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    declared_bindings = [
        item for item in (target.get("value_set_bindings") or [])
        if isinstance(item, Mapping) and item.get("id")
    ]
    bindings = [
        item for item in declared_bindings
        if binding_strength(item) == "required"
    ]
    if bindings:
        # One discriminator binding is expected.  Ambiguous simultaneous
        # bindings cannot prove a unique coded discriminator.
        if len(bindings) != 1:
            return [], None
        binding = {
            "id": str(bindings[0].get("id") or ""),
            "effective_date": str(bindings[0].get("effective_date") or ""),
        }
        key: ValueSetKey = (
            binding["id"], binding["effective_date"]
        ) if binding["effective_date"] else binding["id"]
        members = [dict(item) for item in value_sets.get(key, [])]
        resolved_versions = {
            str(item.get("valueSetEffectiveDate") or "") for item in members
        }
        if not binding["effective_date"] and len(resolved_versions) == 1:
            binding["effective_date"] = resolved_versions.pop()
        return members, binding
    if declared_bindings:
        # Extensible, preferred, and example bindings are terminology hints;
        # they cannot prove a structural discriminator or closed code gate.
        return [], None
    return [], None


def _facet_assignments(
    paths: list[str], fields: Mapping[str, Any], members: list[dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    source_tokens = {
        path: _tokens(" ".join(str(value or "") for value in (
            path, fields.get(path, {}).get("name"),
            fields.get(path, {}).get("description"),
            fields.get(path, {}).get("short_name"),
        )))
        for path in paths
    }
    common = set.intersection(*source_tokens.values()) if source_tokens else set()
    facets = {path: tokens - common for path, tokens in source_tokens.items()}
    candidates: dict[str, dict[str, Any]] = {}
    for path, tokens in facets.items():
        ranked = [
            (len(tokens & _member_tokens(member)), member)
            for member in members
        ]
        best = max((score for score, _ in ranked), default=0)
        selected = [dict(member) for score, member in ranked if score == best and score > 0]
        if len(selected) != 1:
            return None
        candidates[path] = selected[0]
    if len({str(item.get("code")) for item in candidates.values()}) != len(paths):
        return None
    return candidates


def _branch_labels(members: Sequence[Mapping[str, Any]]) -> list[str]:
    english_tokens: list[set[str]] = []
    for member in members:
        english = [
            item for item in member.get("designations", [])
            if isinstance(item, Mapping)
            and str(item.get("language") or "").casefold().startswith("en")
        ]
        english_tokens.append(
            _tokens(str(english[0].get("displayName") or "")) if english else set()
        )
    common = set.intersection(*english_tokens) if english_tokens and all(english_tokens) else set()
    result: list[str] = []
    for member, tokens in zip(members, english_tokens):
        facet = sorted(tokens - common, key=lambda value: (len(value), value))
        result.append(facet[0] if facet else str(member.get("code") or "occurrence"))
    return result


def rule_id(prefix: str, target: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", target.casefold()).strip("-")
    return f"{prefix}-{slug}"[:120]


def occurrence_target(target: str, branch: str) -> str:
    """Name one logical occurrence of a repeatable CDA schema target."""
    head, separator, tail = target.partition(".")
    label = re.sub(r"[^a-z0-9]+", "_", branch.casefold()).strip("_")
    return f"{head}_{label}{separator}{tail}" if separator else f"{target}_{label}"


def _normalized_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _example_templates(
    xml_paths: Iterable[Path],
) -> dict[tuple[str, str], list[ET.Element]]:
    result: dict[tuple[str, str], list[ET.Element]] = defaultdict(list)
    for path in sorted(set(xml_paths)):
        try:
            root, _ = parse_file(path)
        except ET.ParseError:
            continue
        for template in root.iter():
            if local(template.tag) != "template":
                continue
            template_id = str(template.get("id") or "")
            effective = str(template.get("effectiveDate") or "")
            if not template_id or not effective:
                continue
            examples = [
                child for child in list(template)
                if local(child.tag) == "example"
                and str(child.get("type") or "neutral") == "neutral"
            ]
            if examples:
                result[(template_id, effective)].extend(examples)
    return result


def _example_root(example: ET.Element, target_path: str) -> ET.Element | None:
    root_name = target_path.split("/", 1)[0].split(":", 1)[-1]
    matches = [node for node in list(example) if local(node.tag) == root_name]
    return matches[0] if len(matches) == 1 else None


def _example_element(root: ET.Element, target_path: str) -> ET.Element | None:
    parts = [part.split(":", 1)[-1] for part in target_path.split("/")]
    if (
        not parts
        or local(root.tag) != parts[0]
        or any(part.startswith("@") for part in parts)
    ):
        return None
    current = root
    for part in parts[1:]:
        matches = [child for child in list(current) if local(child.tag) == part]
        if len(matches) != 1:
            return None
        current = matches[0]
    return current


def _inside_context(
    target: Mapping[str, Any], context: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(context, Mapping):
        return False
    context_node = context.get("node", {})
    if not isinstance(context_node, Mapping):
        return False
    target_locations = list(target.get("locations", []))
    context_locations = list(context_node.get("locations", []))
    if len(target_locations) != 1 or len(context_locations) != 1:
        return False
    target_location = str(target_locations[0])
    context_location = str(context_locations[0])
    return target_location == context_location or target_location.startswith(
        context_location + "."
    )


def _caption_match(field: Mapping[str, Any], caption: str) -> int:
    caption_key = _normalized_phrase(caption)
    scores = []
    for key in ("name", "short_name"):
        phrase = _normalized_phrase(str(field.get(key) or ""))
        # Long, category-specific names are required.  A generic word such as
        # "allergy" must not select every example in the template.
        if len(phrase) >= 10 and phrase in caption_key:
            scores.append(len(phrase))
    return max(scores, default=0)


def _directly_maps_to(mapping: Any, target: str) -> bool:
    rules = mapping_rules(mapping)
    return (
        len(rules) == 1
        and target in selected_cda_targets(mapping)
        and not rules[0].get("structure")
    )


def boolean_example_discriminator_rules(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    xml_paths: Iterable[Path],
    contexts: Mapping[str, Mapping[str, Any] | None],
    field_mappings: Mapping[str, Any],
    value_sets: Mapping[ValueSetKey, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Derive boolean-negation occurrences from exact neutral examples.

    The rule is deliberately narrow.  A boolean field name must uniquely match
    a neutral example caption inside its mapped CDA context; that example must
    contain an exact member of one required, bound coded discriminator.  The
    source terminology code is not used as the target discriminator.
    """
    examples = _example_templates(xml_paths)
    fields = model.get("fields", {})
    targets = cda.get("targets", {})
    candidates: dict[
        tuple[str, str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)

    for path, field in fields.items():
        if (
            str(field.get("type") or "") != "boolean"
            or field_mappings.get(path) is not None
        ):
            continue
        context = contexts.get(path)
        depth = len(field.get("repeat_chain", []))
        matches: list[dict[str, Any]] = []
        for negation_name, negation in targets.items():
            if (
                not negation.get("writable")
                or str(negation.get("path") or "").rsplit("/", 1)[-1]
                != "@negationInd"
                or len(negation.get("repeat_ancestors", [])) != depth + 1
                or not _inside_context(negation, context)
            ):
                continue
            template_key = (
                str(negation.get("template_id") or ""),
                str(negation.get("template_effective_date") or ""),
            )
            template_examples = examples.get(template_key, [])
            if not template_examples:
                continue
            for discriminator_name, discriminator in targets.items():
                if (
                    discriminator_name == negation_name
                    or not discriminator.get("writable")
                    or discriminator.get("repeat_ancestors", [])
                    != negation.get("repeat_ancestors", [])
                    or str(discriminator.get("template_id") or "")
                    != template_key[0]
                    or str(discriminator.get("template_effective_date") or "")
                    != template_key[1]
                    or int(discriminator.get("min") or 0) < 1
                    or discriminator.get("max") != 1
                ):
                    continue
                members, binding = members_for_target(discriminator, value_sets)
                if not members or binding is None:
                    continue
                by_code = {
                    (
                        str(member.get("code") or ""),
                        str(member.get("codeSystem") or ""),
                    ): member
                    for member in members
                }
                for example in template_examples:
                    caption = str(example.get("caption") or "")
                    score = _caption_match(field, caption)
                    if not score:
                        continue
                    example_root = _example_root(
                        example, str(negation.get("path") or "")
                    )
                    if example_root is None:
                        continue
                    encoded = _example_element(
                        example_root, str(discriminator.get("path") or "")
                    )
                    if encoded is None:
                        continue
                    member = by_code.get((
                        str(encoded.get("code") or ""),
                        str(encoded.get("codeSystem") or ""),
                    ))
                    if member is None:
                        continue
                    literal = str(
                        example_root.get("negationInd") or "false"
                    ).casefold()
                    if literal not in {"true", "false"}:
                        continue
                    matches.append({
                        "path": str(path),
                        "negation_target": str(negation_name),
                        "discriminator_target": str(discriminator_name),
                        "template": {
                            "id": template_key[0],
                            "effective_date": template_key[1],
                        },
                        "binding": binding,
                        "member": dict(member),
                        "caption": caption,
                        "example_negation": literal == "true",
                        "score": score,
                    })
        if not matches:
            continue
        best_score = max(int(item["score"]) for item in matches)
        selected = [item for item in matches if int(item["score"]) == best_score]
        unique = {
            (
                str(item["negation_target"]),
                str(item["discriminator_target"]),
                str(item["member"].get("code") or ""),
                str(item["member"].get("codeSystem") or ""),
            )
            for item in selected
        }
        if len(unique) != 1:
            continue
        item = selected[0]
        group = (
            str(item["negation_target"]),
            str(item["discriminator_target"]),
            str(item["template"]["id"]),
            str(item["template"]["effective_date"]),
        )
        candidates[group].append(item)

    result: dict[str, dict[str, Any]] = {}
    for (
        negation_name, discriminator_name, template_id, effective_date,
    ), selected in candidates.items():
        if len(selected) < 2:
            continue
        discriminator_codes = {
            (
                str(item["member"].get("code") or ""),
                str(item["member"].get("codeSystem") or ""),
            )
            for item in selected
        }
        if len(discriminator_codes) != len(selected):
            continue
        mapped_discriminator_sources = [
            str(path) for path, mapping in field_mappings.items()
            if _directly_maps_to(mapping, discriminator_name)
        ]
        if len(mapped_discriminator_sources) > 1:
            continue
        rule_name = rule_id("repeat-by-example-discriminator", negation_name)
        branch_names = {
            str(item["path"]): re.sub(
                r"[^a-z0-9]+",
                "-",
                str(
                    fields.get(str(item["path"]), {}).get("short_name")
                    or str(item["path"]).rsplit(".", 1)[-1]
                ).casefold(),
            ).strip("-")
            for item in selected
        }
        if len(set(branch_names.values())) != len(selected):
            continue
        branches = []
        selections: dict[str, dict[str, Any]] = {}
        for item in selected:
            path = str(item["path"])
            branch = branch_names[path]
            logical_target = occurrence_target(negation_name, branch)
            branches.append({
                "source": path,
                "target": logical_target,
                "cda_target": negation_name,
                "branch": branch,
                "transform": {"type": "not"},
                "constants": {discriminator_name: item["member"]},
            })
            selections[path] = {
                "mapping": {
                    "target": logical_target,
                    "cda_target": negation_name,
                    "structure": rule_name,
                    "branch": branch,
                    "transform": {"type": "not"},
                },
                **item,
            }
        result[rule_name] = {
            "rule": {
                "type": "repeat_by_discriminator",
                "discriminator": {
                    "target": discriminator_name,
                    "value_set": dict(selected[0]["binding"]),
                    "members": [item["member"] for item in selected],
                    "evidence_level": "STRONG",
                },
                "coalesce_existing_discriminator": bool(
                    mapped_discriminator_sources
                ),
                "existing_discriminator_sources": mapped_discriminator_sources,
                "evidence": [
                    f"neutral ART-DECOR examples in {template_id}@{effective_date}",
                    "unique category-specific example caption matches",
                    "inverse boolean-to-negationInd semantics",
                    f"exact bound discriminator {discriminator_name}",
                    *(
                        ["coalesce an equal explicit discriminator occurrence"]
                        if mapped_discriminator_sources else []
                    ),
                ],
                "branches": branches,
            },
            "selections": selections,
        }
    return result


def _schematron_unique_codes(
    cda: Mapping[str, Any], discriminator_target: Mapping[str, Any],
) -> set[str]:
    leaf = str(discriminator_target.get("path") or "").rsplit("/", 1)[-1]
    leaf = leaf.split(":", 1)[-1]
    result: set[str] = set()
    for assertion in cda.get("validation_rules", []):
        if not isinstance(assertion, Mapping):
            continue
        test = str(assertion.get("test") or "")
        compact = re.sub(r"\s+", "", test)
        if leaf not in test or "count(" not in compact or not re.search(r"(?:<=|&lt;=)1", compact):
            continue
        result.update(
            code for quote, code in re.findall(
                r"@code\s*=\s*(['\"])([^'\"]+)\1", test
            )
        )
    for constraint in discriminator_target.get("schematron_constraints", []):
        if (
            isinstance(constraint, Mapping)
            and constraint.get("kind") == "fixed_value"
            and str(constraint.get("path") or "").endswith("/@code")
            and constraint.get("value")
        ):
            result.add(str(constraint["value"]))
    return result


def _schematron_cardinality(
    target: Mapping[str, Any], kind: str, *, unpredicated: bool = False,
) -> list[int]:
    return [
        int(item["value"])
        for item in target.get("schematron_constraints", [])
        if isinstance(item, Mapping)
        and item.get("kind") == kind
        and isinstance(item.get("value"), int)
        and (not unpredicated or "[" not in str(item.get("path") or ""))
    ]


def _repeat_upper_bound(
    cda: Mapping[str, Any], location: str,
) -> int | None:
    bounds: list[int] = []
    for target in cda.get("targets", {}).values():
        if location not in {str(item) for item in target.get("locations", [])}:
            continue
        maximum = target.get("max")
        if isinstance(maximum, int):
            bounds.append(maximum)
        bounds.extend(_schematron_cardinality(
            target, "max_occurs", unpredicated=True,
        ))
    return min(bounds) if bounds else None


def repeat_by_discriminator_rule(
    paths: list[str],
    target_name: str,
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    value_sets: Mapping[ValueSetKey, list[dict[str, Any]]],
) -> tuple[str, dict[str, Any]] | None:
    target = cda.get("targets", {}).get(target_name, {})
    fields = model.get("fields", {})
    depths = {len(fields.get(path, {}).get("repeat_chain", [])) for path in paths}
    if len(depths) != 1 or len(target.get("repeat_ancestors", [])) != next(iter(depths)) + 1:
        return None
    repeated_location = str(target.get("repeat_ancestors", [])[-1])
    upper_bound = _repeat_upper_bound(cda, repeated_location)
    if upper_bound is not None and len(paths) > upper_bound:
        return None
    parent_path = str(target.get("path") or "").rsplit("/", 1)[0]
    discriminator: tuple[
        str, dict[str, str], dict[str, dict[str, Any]],
    ] | None = None
    for name, candidate in cda.get("targets", {}).items():
        if name == target_name or not candidate.get("renderable"):
            continue
        if candidate.get("repeat_ancestors", []) != target.get("repeat_ancestors", []):
            continue
        if str(candidate.get("path") or "").rsplit("/", 1)[0] != parent_path:
            continue
        required = int(candidate.get("min") or 0) >= 1 or bool(
            _schematron_cardinality(candidate, "required")
        )
        maximum_one = candidate.get("max") == 1 or any(
            value <= 1
            for value in _schematron_cardinality(candidate, "max_occurs")
        )
        if not required or not maximum_one:
            continue
        members, binding = members_for_target(candidate, value_sets)
        assignments = _facet_assignments(paths, fields, members)
        unique_codes = _schematron_unique_codes(cda, candidate)
        selected_codes = {
            str(member.get("code") or "")
            for member in (assignments or {}).values()
        }
        if unique_codes and not selected_codes <= unique_codes:
            continue
        if assignments and binding:
            discriminator = str(name), binding, assignments
            break
    if discriminator is None:
        return None
    discriminator_name, binding, assignments = discriminator
    rule_name = rule_id("repeat-by-discriminator", target_name)
    branches = []
    selected_members = [assignments[path] for path in paths]
    for path, branch in zip(paths, _branch_labels(selected_members)):
        member = assignments[path]
        branches.append({
            "source": path,
            "target": occurrence_target(target_name, branch),
            "cda_target": target_name,
            "branch": branch,
            "constants": {discriminator_name: member},
        })
    return rule_name, {
        "type": "repeat_by_discriminator",
        "discriminator": {
            "target": discriminator_name,
            "value_set": binding,
            "members": selected_members,
            "evidence_level": "STRONG",
        },
        "evidence": [
            "shared repeatable CDA value target",
            "one additional CDA repeat level",
            f"required coded discriminator {discriminator_name}",
            "unique terminology designation match",
            *( ["Schematron uniqueness by discriminator code"]
               if _schematron_unique_codes(
                   cda, cda.get("targets", {}).get(discriminator_name, {})
               ) else [] ),
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


def _section_entry_for_each_rules(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    group_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    targets = cda.get("targets", {})
    # A repeated dataset container may describe statements collected in one CDA
    # section.  In that shape the source has one repeat level while value targets
    # have two: the shared section and its repeated entry.  Infer the entry
    # boundary only when the mapped parent/child groups and cardinalities identify
    # one unique section -> entry -> singular-statement path.
    groups = model.get("groups", {})
    for group_path, group in groups.items():
        rule_name = rule_id("for-each", str(group_path))
        if rule_name in result or not group.get("repeating"):
            continue
        parent_result = group_results.get(str(group_path), {})
        parent_primary = parent_result.get("primary")
        if not isinstance(parent_primary, Mapping):
            continue
        parent_target = targets.get(str(parent_primary.get("target") or ""), {})
        parent_locations = list(parent_target.get("locations", []))
        if (
            not parent_target.get("renderable")
            or len(parent_locations) != 1
            or not parent_target.get("repeatable")
            or not str(parent_target.get("path") or "").endswith("hl7:section")
        ):
            continue
        parent_location = str(parent_locations[0])
        anchors: set[str] = set()
        child_targets: set[str] = set()
        for child_path, child in groups.items():
            if child.get("parent") != group_path or child.get("repeating"):
                continue
            child_result = group_results.get(str(child_path), {})
            child_primary = child_result.get("primary")
            if not isinstance(child_primary, Mapping):
                continue
            child_target_name = str(child_primary.get("target") or "")
            child_target = targets.get(child_target_name, {})
            if (
                not child_target.get("renderable")
                or child_target.get("max") != 1
            ):
                continue
            ancestors = [str(value) for value in child_target.get("repeat_ancestors", [])]
            if len(ancestors) != 2 or ancestors[0] != parent_location:
                continue
            anchor_location = ancestors[1]
            anchor_names = [
                str(name) for name, target in targets.items()
                if target.get("renderable")
                and target.get("locations") == [anchor_location]
                and str(target.get("path") or "").endswith("/hl7:entry")
            ]
            if len(anchor_names) == 1:
                anchors.add(anchor_names[0])
                child_targets.add(child_target_name)
        if len(anchors) != 1 or len(child_targets) != 1:
            continue
        result[rule_name] = {
            "type": "for_each",
            "source_group": group_path,
            "target_repeat": next(iter(anchors)),
            "evidence": [
                "repeated dataset group mapped to a CDA section",
                "one singular child group mapped below one repeated CDA entry",
                "shared section container with occurrence-aligned entries",
            ],
        }
    return result


def for_each_rules(
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    fields: Mapping[str, Any],
    group_results: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    # The section/entry shape is more specific than positional field-depth
    # matching and must remain stable when later steps add medication fields.
    result = _section_entry_for_each_rules(model, cda, group_results or {})
    targets = cda.get("targets", {})
    for group_path, group in model.get("groups", {}).items():
        rule_name = rule_id("for-each", str(group_path))
        if rule_name in result or not group.get("repeating"):
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
            anchors = [
                name for name, target in targets.items()
                if target.get("locations") == [location]
                and target.get("renderable") is True
                and target.get("repeatable") is True
            ]
            if len(anchors) != 1:
                continue
            anchor = anchors[0]
            result[rule_name] = {
                "type": "for_each",
                "source_group": group_path,
                "target_repeat": anchor,
                "evidence": ["matching source and CDA repeat depth"],
            }
    return result
