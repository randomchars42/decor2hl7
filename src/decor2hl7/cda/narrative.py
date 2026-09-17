"""Checked CDA section-narrative rules and runtime presentation.

Structured mappings remain the source of clinical meaning.  This module adds
human-readable presentation for those mappings and implements the separate,
reviewed ``narratives`` bridge for source facts that have no defensible
structured CDA target.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from ..bindings import (
    for_each_target_positions,
    is_fallback_if_active,
    physical_target_name,
    structure_rules,
)
from ..data import field_value
from ..transforms import OMIT, apply_transform, mapping_rules
from ..value_format import (
    preferred_mapping_value,
    range_quantities,
    scalar_quantity,
)


def narrative_blocks(mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return normalized reviewed narrative blocks in configuration order."""
    result: list[dict[str, Any]] = []
    configured = mapping.get("narratives", {})
    if not isinstance(configured, Mapping):
        return result
    for target, specification in configured.items():
        if not isinstance(specification, Mapping):
            continue
        blocks = specification.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if isinstance(block, Mapping):
                result.append({"section_target": str(target), **dict(block)})
    return result


def narrative_source_rules(
    mapping: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Index reviewed narrative blocks by dataset source path."""
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in narrative_blocks(mapping):
        source = str(block.get("source") or "")
        if source:
            result[source].append(block)
    return dict(result)


def validate_narratives(
    model: Mapping[str, Any], cda: Mapping[str, Any], mapping: Mapping[str, Any]
) -> list[str]:
    """Validate the intentionally small reviewed narrative-only contract."""
    configured = mapping.get("narratives", {})
    if not isinstance(configured, Mapping):
        return ["cda-mapping: narratives must be an object"]

    fields = model.get("fields", {})
    mapped_fields = mapping.get("fields", {})
    reviews = mapping.get("field_reviews", {})
    targets = cda.get("targets", {})
    errors: list[str] = []
    seen_sources: dict[str, str] = {}
    for raw_target, specification in configured.items():
        section_target = str(raw_target)
        prefix = f"cda-mapping: narratives[{section_target!r}]"
        if not isinstance(specification, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        unknown = set(specification) - {"blocks"}
        if unknown:
            errors.append(f"{prefix} has unknown keys {sorted(unknown)!r}")
        target = targets.get(section_target)
        if not isinstance(target, Mapping):
            errors.append(f"{prefix} references unknown CDA target")
        else:
            if (
                not target.get("writable")
                or target.get("prohibited")
                or len(target.get("locations", [])) != 1
            ):
                errors.append(
                    f"{prefix} must reference one writable, unambiguous CDA target"
                )
            if target.get("content_role") != "section_narrative":
                errors.append(f"{prefix} target is not a compiled section narrative")
            representation = target.get("value_representation", {})
            if not isinstance(representation, Mapping) or (
                representation.get("kind") != "element_text"
                or "text" not in target.get("logical_types", [])
            ):
                errors.append(f"{prefix} target is not a writable text value")
            if target.get("repeat_ancestors"):
                errors.append(
                    f"{prefix} cannot target a repeated section in narrative rule version 1"
                )

        blocks = specification.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            errors.append(f"{prefix}.blocks must be a non-empty list")
            continue
        for index, block in enumerate(blocks):
            block_prefix = f"{prefix}.blocks[{index}]"
            if not isinstance(block, Mapping):
                errors.append(f"{block_prefix} must be an object")
                continue
            allowed = {
                "type", "source", "source_repeat", "label", "reason",
                "decision", "reviewed_at",
            }
            unknown = set(block) - allowed
            if unknown:
                errors.append(
                    f"{block_prefix} has unknown keys {sorted(unknown)!r}"
                )
            kind = str(block.get("type") or "")
            if kind not in {"fact", "for_each"}:
                errors.append(f"{block_prefix}.type must be fact or for_each")
            source = str(block.get("source") or "")
            field = fields.get(source) if isinstance(fields, Mapping) else None
            if not isinstance(field, Mapping):
                errors.append(f"{block_prefix}.source references unknown model field {source!r}")
                continue
            previous = seen_sources.get(source)
            if previous is not None:
                errors.append(
                    f"{block_prefix}.source duplicates the narrative rule at {previous}"
                )
            else:
                seen_sources[source] = block_prefix
            if isinstance(mapped_fields, Mapping) and mapped_fields.get(source) is not None:
                errors.append(
                    f"{block_prefix}.source must remain null in fields; narrative rules "
                    "do not replace structured mappings"
                )
            if isinstance(reviews, Mapping) and source in reviews:
                errors.append(
                    f"{block_prefix}.source conflicts with field_reviews[{source!r}]"
                )
            for key in ("label", "reason"):
                if not isinstance(block.get(key), str) or not str(block.get(key)).strip():
                    errors.append(f"{block_prefix}.{key} must be non-empty text")
            for key in ("decision", "reviewed_at"):
                if key in block and (
                    not isinstance(block.get(key), str) or not str(block.get(key)).strip()
                ):
                    errors.append(f"{block_prefix}.{key} must be non-empty text")

            repeat_chain = [str(item) for item in field.get("repeat_chain", [])]
            source_repeat = str(block.get("source_repeat") or "")
            if kind == "fact":
                if repeat_chain:
                    errors.append(f"{block_prefix}.source is repeated; use for_each")
                if source_repeat:
                    errors.append(f"{block_prefix}.source_repeat is only valid for for_each")
            elif kind == "for_each":
                if not source_repeat:
                    errors.append(f"{block_prefix}.source_repeat is required")
                elif repeat_chain != [source_repeat]:
                    errors.append(
                        f"{block_prefix}.source must have repeat_chain [{source_repeat!r}]"
                    )
    return errors


def _present(value: Any) -> bool:
    if value is None or value is OMIT:
        return False
    if isinstance(value, list):
        return any(_present(item) for item in value)
    return True


def _leaves(value: Any, prefix: tuple[int, ...] = ()) -> list[tuple[tuple[int, ...], Any]]:
    if isinstance(value, list):
        return [
            result
            for index, item in enumerate(value)
            for result in _leaves(item, prefix + (index,))
        ]
    return [(prefix, value)] if _present(value) else []


def _transformed_occurrences(
    value: Any, transform: Mapping[str, Any] | None, *, presence: bool = False,
) -> set[tuple[int, ...]]:
    if presence:
        return {
            occurrence for occurrence, item in _leaves(value)
            if bool(item)
        }
    transformed = apply_transform(value, transform)
    return {occurrence for occurrence, _item in _leaves(transformed)}


def _value_at(value: Any, occurrence: tuple[int, ...]) -> Any:
    current = value
    for index in occurrence:
        if not isinstance(current, list) or index >= len(current):
            return None
        current = current[index]
    return current


def _wording(value: Any, language: str) -> str:
    if isinstance(value, bool):
        if language.lower().startswith("de"):
            return "Ja" if value else "Nein"
        return "Yes" if value else "No"
    if isinstance(value, Mapping):
        bounds = range_quantities(value)
        if bounds is not None:
            low_bound, high_bound = bounds
            if (
                low_bound is not None
                and high_bound is not None
                and low_bound[1] == high_bound[1]
            ):
                unit = low_bound[1]
                return (
                    f"{low_bound[0]}–{high_bound[0]}"
                    + (f" {unit}" if unit else "")
                )
            low = value.get("low")
            high = value.get("high")
            low_text = _wording(low, language) if low is not None else ""
            high_text = _wording(high, language) if high is not None else ""
            if low_text and high_text:
                return f"{low_text}–{high_text}"
            return low_text or high_text
        scalar = scalar_quantity(value)
        if scalar is not None:
            unit = scalar[1].strip()
            return str(scalar[0]) + (f" {unit}" if unit else "")
        preferred = preferred_mapping_value(
            value, ("displayName", "display_name", "raw", "canonical", "code")
        )
        if preferred is not None:
            return str(preferred)
        return ""
    return "" if value in (None, "") else str(value)


def _language(site: Mapping[str, Any]) -> str:
    cda_config = site.get("cda", {})
    values = cda_config.get("values", {}) if isinstance(cda_config, Mapping) else {}
    if isinstance(values, Mapping):
        for name, value in values.items():
            if "language" in str(name).lower() and isinstance(value, str) and value:
                return value
    return "en"


def _local_name(name: Any) -> str:
    return str(name or "").split(":", 1)[-1].split("[", 1)[0]


def _section_index(cda: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    sections: list[dict[str, Any]] = []
    target_sections: dict[str, int] = {}

    def walk(nodes: list[Mapping[str, Any]], section_id: int | None = None) -> None:
        for node in nodes:
            current = section_id
            if node.get("kind") == "element" and _local_name(node.get("name")) == "section":
                current = len(sections)
                sections.append({
                    "targets": [], "title_target": "", "narrative_target": "",
                    "label": "Section",
                })
            if current is not None:
                names = [str(name) for name in node.get("targets", [])]
                for attribute in node.get("attributes", []):
                    names.extend(str(name) for name in attribute.get("targets", []))
                for name in names:
                    target_sections[name] = current
                    sections[current]["targets"].append(name)
                    target = cda.get("targets", {}).get(name, {})
                    role = target.get("content_role") if isinstance(target, Mapping) else None
                    if role == "section_title":
                        sections[current]["title_target"] = name
                    elif role == "section_narrative":
                        sections[current]["narrative_target"] = name
                    if _local_name(node.get("name")) == "section" and isinstance(target, Mapping):
                        sections[current]["label"] = str(
                            target.get("template_display_name")
                            or target.get("template_name") or "Section"
                        )
            walk(list(node.get("children", [])), current)

    walk(list(cda.get("document", [])))
    return sections, target_sections


def _coalesce_winners(
    record: Mapping[str, Any], model: Mapping[str, Any], structure: Mapping[str, Any]
) -> dict[str, set[tuple[int, ...]]]:
    specs: list[dict[str, Any]] = []
    for item in structure.get("sources", []):
        if isinstance(item, str):
            specs.append({"source": item})
        elif isinstance(item, Mapping) and item.get("source"):
            specs.append(dict(item))
    values: list[dict[tuple[int, ...], Any]] = []
    for spec in specs:
        source = str(spec["source"])
        raw = field_value(record, source, model.get("fields", {}).get(source, {}))
        transformed = apply_transform(raw, spec.get("transform"))
        values.append(dict(_leaves(transformed)))
    result: dict[str, set[tuple[int, ...]]] = {
        str(spec["source"]): set() for spec in specs
    }
    occurrences = sorted({occurrence for by_occurrence in values for occurrence in by_occurrence})
    policy = str(structure.get("policy") or "equal_or_error")
    for occurrence in occurrences:
        candidates = [
            (index, by_occurrence[occurrence])
            for index, by_occurrence in enumerate(values)
            if occurrence in by_occurrence
        ]
        if not candidates:
            continue
        if policy == "earliest":
            winner = min(candidates, key=lambda item: item[1])[0]
        elif policy == "latest":
            winner = max(candidates, key=lambda item: item[1])[0]
        else:
            winner = candidates[0][0]
        result[str(specs[winner]["source"])].add(occurrence)
    return result


def _pack_occurrences(values: Mapping[tuple[int, ...], Any], depth: int) -> Any:
    if depth == 0:
        return values.get(())

    def build(prefix: tuple[int, ...]) -> Any:
        if len(prefix) == depth:
            return values.get(prefix)
        indices = {
            occurrence[len(prefix)] for occurrence in values
            if occurrence[:len(prefix)] == prefix
        }
        if not indices:
            return None
        return [build(prefix + (index,)) for index in range(max(indices) + 1)]

    return build(())


def build_section_narratives(
    record: Mapping[str, Any],
    model: Mapping[str, Any],
    cda: Mapping[str, Any],
    mapping: Mapping[str, Any],
    assignments: Mapping[str, Any],
    explicit_names: set[str],
    site: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build occurrence-shaped titles and structured narrative values."""
    sections, target_sections = _section_index(cda)
    targets = cda.get("targets", {})
    language = _language(site)
    states: dict[tuple[int, tuple[int, ...]], dict[str, Any]] = {}

    def state(section_id: int, section_occurrence: tuple[int, ...]) -> dict[str, Any]:
        return states.setdefault((section_id, section_occurrence), {
            "__section_narrative__": True,
            "paragraphs": [],
            "facts": [],
            "repeated_facts": [],
            "entry_links": [],
        })

    # Only genuine mapped values activate optional sections. Site completion
    # wrappers are deliberately ignored here.
    for name in explicit_names:
        value = assignments.get(name)
        target = targets.get(name, {})
        section_id = target_sections.get(name)
        if (
            section_id is None or is_fallback_if_active(value)
            or not isinstance(target, Mapping) or target.get("system_value")
        ):
            continue
        section = sections[section_id]
        narrative_name = str(section.get("narrative_target") or "")
        section_depth = len(targets.get(narrative_name, {}).get("repeat_ancestors", []))
        target_depth = len(target.get("repeat_ancestors", []))
        for occurrence, _item in _leaves(value):
            aligned = occurrence + (0,) * max(0, target_depth - len(occurrence))
            state(section_id, aligned[:section_depth])

    structures = {str(item.get("id") or ""): item for item in structure_rules(mapping)}
    coalesce = {
        name: _coalesce_winners(record, model, structure)
        for name, structure in structures.items()
        if structure.get("type") == "coalesce"
    }
    added: set[tuple[int, tuple[int, ...], str, tuple[int, ...]]] = set()

    def add_source(
        source: str,
        label: str,
        value: Any,
        occurrences: set[tuple[int, ...]],
        section_id: int,
        target_name: str,
        *, paragraph: bool = False,
        activate: bool = False,
    ) -> None:
        field = model.get("fields", {}).get(source, {})
        source_depth = len(field.get("repeat_chain", []))
        target = targets.get(target_name, {})
        narrative_name = str(sections[section_id].get("narrative_target") or "")
        section_depth = len(targets.get(narrative_name, {}).get("repeat_ancestors", []))
        positions = for_each_target_positions(field, target, cda, mapping)
        for occurrence in sorted(occurrences):
            if len(occurrence) < source_depth:
                occurrence = occurrence + (0,) * (source_depth - len(occurrence))
            if positions is not None and len(positions) == source_depth:
                source_by_target = {target_position: index for index, target_position in enumerate(positions)}
                section_occurrence = tuple(
                    occurrence[source_by_target[index]] if index in source_by_target else 0
                    for index in range(section_depth)
                )
                used = {source_by_target[index] for index in range(section_depth) if index in source_by_target}
                local_occurrence = tuple(
                    item for index, item in enumerate(occurrence) if index not in used
                )
            else:
                section_occurrence = occurrence[:section_depth]
                local_occurrence = occurrence[section_depth:]
            key = (section_id, section_occurrence, source, local_occurrence)
            if key in added:
                continue
            if not activate and (section_id, section_occurrence) not in states:
                continue
            text = _wording(_value_at(value, occurrence), language)
            if not text:
                continue
            added.add(key)
            current = state(section_id, section_occurrence)
            if paragraph and not local_occurrence:
                current["paragraphs"].append({"source": source, "text": text})
            elif local_occurrence:
                current["repeated_facts"].append({
                    "source": source, "occurrence": list(local_occurrence),
                    "repeat_chain": [
                        str(item) for index, item in enumerate(field.get("repeat_chain", []))
                        if index not in used
                    ] if positions is not None and len(positions) == source_depth else [
                        str(item) for item in field.get("repeat_chain", [])[section_depth:]
                    ],
                    "label": label, "value": text,
                })
            else:
                current["facts"].append({
                    "source": source, "label": label, "value": text,
                })

    for source, selection in mapping.get("fields", {}).items():
        if selection is None:
            continue
        field = model.get("fields", {}).get(source, {})
        raw = field_value(record, str(source), field)
        if not _present(raw):
            continue
        label = str(field.get("name") or str(source).rsplit(".", 1)[-1])
        for rule in mapping_rules(selection):
            target_name = physical_target_name(cda, rule)
            section_id = target_sections.get(target_name)
            if section_id is None or target_name not in explicit_names:
                continue
            structure_name = str(rule.get("structure") or "")
            structure = structures.get(structure_name, {})
            occurrences = _transformed_occurrences(
                raw, rule.get("transform"), presence=rule.get("mode") == "presence"
            )
            if structure.get("type") == "coalesce":
                occurrences &= coalesce.get(structure_name, {}).get(str(source), set())
            if not occurrences:
                continue
            paragraph = (
                not structure_name
                and target_name == sections[section_id].get("narrative_target")
            )
            add_source(
                str(source), label, raw, occurrences, section_id, target_name,
                paragraph=paragraph,
            )

    # Narrative-only facts are exact, reviewed additions. They may activate
    # their owning section, unlike site completion fallbacks.
    for block in narrative_blocks(mapping):
        source = str(block.get("source") or "")
        target_name = str(block.get("section_target") or "")
        section_id = target_sections.get(target_name)
        field = model.get("fields", {}).get(source, {})
        if section_id is None or not isinstance(field, Mapping):
            continue
        raw = field_value(record, source, field)
        occurrences = {occurrence for occurrence, _item in _leaves(raw)}
        add_source(
            source, str(block.get("label") or field.get("name") or source),
            raw, occurrences, section_id, target_name, activate=True,
        )

    narrative_values: dict[str, Any] = {}
    title_values: dict[str, Any] = {}
    for section_id, section in enumerate(sections):
        narrative_name = str(section.get("narrative_target") or "")
        if not narrative_name:
            continue
        depth = len(targets.get(narrative_name, {}).get("repeat_ancestors", []))
        by_occurrence = {
            occurrence: value for (owner, occurrence), value in states.items()
            if owner == section_id
        }
        if not by_occurrence:
            continue
        label = str(section.get("label") or "Section")
        for value in by_occurrence.values():
            if not value["paragraphs"] and not value["facts"] and not value["repeated_facts"]:
                value["paragraphs"].append({"text": label})
        narrative_values[narrative_name] = _pack_occurrences(by_occurrence, depth)
        title_name = str(section.get("title_target") or "")
        if title_name:
            title_target = targets.get(title_name, {})
            title = str(
                title_target.get("fixed_text")
                if isinstance(title_target, Mapping)
                and title_target.get("fixed_text") is not None
                else label
            )
            title_values[title_name] = _pack_occurrences(
                {occurrence: title for occurrence in by_occurrence}, depth
            )
    return title_values, narrative_values
