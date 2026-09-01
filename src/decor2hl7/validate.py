"""Validation of configuration, compiled CDA constraints and normalized records."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .semantics import accepted_values
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import xml.etree.ElementTree as ET

from .assertions import evaluate as evaluate_assertion
from .bindings import (
    for_each_target_positions,
    covered_shared_claims,
    structure_rules,
    validate_structures,
    validate_target_defaults,
)
from .data import mapping_locator
from .retrieval.xml import local, parse_file
from .semantics import direct_compatibility, transformed_compatibility, identifier_root_for_target, valid_oid
from .transforms import mapping_rules, validate_transform
from .cda.model import ValueRepresentationKind


def check_site(site: Mapping[str, Any], cda: Mapping[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    timezone = str(site.get("timezone") or "")
    if timezone:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            errors.append(f"site: unknown timezone {timezone!r}")
    identifiers = site.get("identifiers", {})
    if isinstance(identifiers, Mapping):
        for key in ("document_root", "patient_root", "encounter_root"):
            value = identifiers.get(key)
            if value not in (None, "") and not valid_oid(value):
                errors.append(f"site: identifiers.{key} is not a valid OID: {value!r}")
        roots = identifiers.get("roots", {})
        if roots is not None and not isinstance(roots, Mapping):
            errors.append("site: identifiers.roots must be an object")
        elif isinstance(roots, Mapping):
            for name, value in roots.items():
                if not valid_oid(value):
                    errors.append(f"site: identifiers.roots[{name!r}] is not a valid OID: {value!r}")
    organization = site.get("organization", {})
    if isinstance(organization, Mapping) and organization.get("oid") not in (None, ""):
        if not valid_oid(organization.get("oid")):
            errors.append(f"site: organization.oid is not a valid OID: {organization.get('oid')!r}")
    input_cfg = site.get("input", {})
    if isinstance(input_cfg, Mapping):
        sources = input_cfg.get("sources", {})
        if sources is not None and not isinstance(sources, Mapping):
            errors.append("site: input.sources must be an object")
        elif isinstance(sources, Mapping):
            for name, spec in sources.items():
                if isinstance(spec, Mapping):
                    cardinality = str(spec.get("cardinality") or "1:1")
                    if cardinality not in {"1:1", "1:n"}:
                        errors.append(f"site: input.sources.{name}.cardinality must be 1:1 or 1:n")
                    occurrence_keys = spec.get("occurrence_keys", {})
                    if occurrence_keys is not None and not isinstance(occurrence_keys, Mapping):
                        errors.append(f"site: input.sources.{name}.occurrence_keys must be an object")
                    elif isinstance(occurrence_keys, Mapping):
                        for repeat, column in occurrence_keys.items():
                            if not str(repeat).strip() or not str(column).strip():
                                errors.append(f"site: input.sources.{name}.occurrence_keys must map non-empty repeat paths to columns")
    if cda is not None:
        targets = cda.get("targets", {})
        values = site.get("cda", {}).get("values", {})
        if values is not None and not isinstance(values, Mapping):
            errors.append("site: cda.values must be an object")
        elif isinstance(values, Mapping):
            for name in values:
                target = targets.get(name)
                if not target or not target.get("writable") or len(target.get("locations", [])) != 1:
                    errors.append(f"site: cda.values references unknown/prohibited/ambiguous target {name!r}")
    return errors


def check_config(
    model: Mapping[str, Any], cda: Mapping[str, Any], csv_mapping: Mapping[str, Any],
    cda_mapping: Mapping[str, Any], codes_mapping: Mapping[str, Any] | None = None,
    site: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    model_identity = model.get("meta", {})
    expected_identity = {
        "dataset_id": model_identity.get("dataset_id"),
        "transaction_id": model_identity.get("transaction_id"),
        "effective_date": model_identity.get("transaction_effective_date"),
    }
    for name, mapping in (("csv-mapping", csv_mapping), ("cda-mapping", cda_mapping)):
        configured_identity = mapping.get("model", {})
        if not isinstance(configured_identity, Mapping):
            errors.append(f"{name}: model identity must be an object")
            continue
        for key, expected in expected_identity.items():
            configured = configured_identity.get(key)
            if configured not in (None, "") and expected not in (None, "") and configured != expected:
                errors.append(
                    f"{name}: {key} {configured!r} does not match compiled model {expected!r}"
                )
    configured_target = cda_mapping.get("target", {})
    compiled_template = cda.get("document_template", {})
    if isinstance(configured_target, Mapping) and isinstance(compiled_template, Mapping):
        configured_template = configured_target.get("template")
        expected_template = compiled_template.get("name")
        if (
            configured_template not in (None, "")
            and expected_template not in (None, "")
            and configured_template != expected_template
        ):
            errors.append(
                f"cda-mapping: target template {configured_template!r} does not match "
                f"compiled CDA {expected_template!r}"
            )
    fields = set(model.get("fields", {}))
    for name, mapping in (("csv-mapping", csv_mapping), ("cda-mapping", cda_mapping)):
        mapped = set(mapping.get("fields", {}))
        for missing in sorted(fields - mapped):
            errors.append(f"{name}: missing model field {missing}")
        for extra in sorted(mapped - fields):
            errors.append(f"{name}: unknown model field {extra}")
    targets = cda.get("targets", {})
    datapoints = cda.get("datapoints", {})
    structures_by_id = {
        str(rule.get("id") or ""): rule
        for rule in structure_rules(cda_mapping)
    }
    claims: dict[str, list[str]] = defaultdict(list)
    for path, value in cda_mapping.get("fields", {}).items():
        field = model.get("fields", {}).get(path, {})
        for rule in mapping_rules(value):
            target_name = str(rule["target"])
            cda_target_name = str(rule.get("cda_target") or target_name)
            if isinstance(datapoints, Mapping) and datapoints:
                datapoint = datapoints.get(target_name)
                if not isinstance(datapoint, Mapping):
                    errors.append(
                        f"cda-mapping: {path} references unknown logical CDA "
                        f"datapoint {target_name}"
                    )
                    continue
                modeled_target = str(datapoint.get("cda_target") or "")
                if modeled_target and modeled_target != cda_target_name:
                    errors.append(
                        f"cda-mapping: {path} logical datapoint {target_name} resolves "
                        f"to {modeled_target}, not {cda_target_name}"
                    )
                    continue
                cda_target_name = modeled_target or cda_target_name
            target = targets.get(cda_target_name)
            if target is None:
                errors.append(
                    f"cda-mapping: {path} references unknown CDA target {cda_target_name}"
                )
                continue
            if rule.get("mode") not in {None, "fallback"}:
                errors.append(
                    f"cda-mapping: {path} -> {target_name}: unknown assignment mode "
                    f"{rule.get('mode')!r}"
                )
            if rule.get("mode") != "fallback":
                claims[cda_target_name].append(path)
            if target.get("prohibited") or not target.get("writable"):
                errors.append(
                    f"cda-mapping: {path} references prohibited/non-renderable "
                    f"target {cda_target_name}"
                )
            locations = target.get("locations", [])
            if len(locations) != 1:
                errors.append(f"cda-mapping: {path} target {cda_target_name} has {len(locations)} physical locations")
            transform = rule.get("transform")
            for reason in validate_transform(transform):
                errors.append(f"cda-mapping: {path} -> {target_name}: {reason}")
            compatibility_field = field
            structure_name = rule.get("structure")
            structure = structures_by_id.get(str(structure_name or ""), {})
            if structure.get("type") in {"fan_out", "repeat_by_discriminator"}:
                compatibility_field = dict(field)
                chain = list(
                    field.get("repeat_chain")
                    or ([] if not field.get("repeat") else [field.get("repeat")])
                )
                compatibility_field["repeat_chain"] = chain + [
                    f"repeat_by_discriminator:{structure_name}"
                ]
            compatible, reasons = transformed_compatibility(
                compatibility_field, target, transform
            )
            if for_each_target_positions(field, target, cda, cda_mapping) is not None:
                reasons = [
                    reason for reason in reasons
                    if not reason.startswith("dataset has ")
                ]
                compatible = not reasons
            if not compatible:
                wording = "not directly executable" if not transform else "not executable with configured transform"
                errors.append(f"cda-mapping: {path} -> {target_name} is {wording}: " + "; ".join(reasons))
            representation = target.get("value_representation", {})
            if (
                isinstance(representation, Mapping)
                and representation.get("kind") == ValueRepresentationKind.IDENTIFIER.value
                and site is not None
            ):
                if not identifier_root_for_target(cda_target_name, target, site):
                    errors.append(f"cda-mapping: {path} -> {target_name} is an II without a fixed/configured root")
    for target_name, paths in sorted(claims.items()):
        covered = covered_shared_claims(cda_mapping).get(target_name, set())
        if len(paths) > 1 and covered != set(paths):
            errors.append(f"cda-mapping: target {target_name} is assigned by multiple model fields without an explicit rule: " + ", ".join(sorted(paths)))
    for path, value in csv_mapping.get("fields", {}).items():
        if value is not None and mapping_locator(value) is None:
            errors.append(f"csv-mapping: {path} must be SOURCE:COLUMN, a locator object, or null")
        locator = mapping_locator(value)
        if locator is not None:
            parse_as = locator.get("parse_as")
            if parse_as and parse_as not in {
                "string", "text", "identifier", "datetime", "date", "boolean",
                "code", "quantity", "decimal", "integer", "count", "ordinal", "duration",
            }:
                errors.append(f"csv-mapping: {path} has unknown parse_as {parse_as!r}")
            for reason in validate_transform(locator.get("transform")):
                errors.append(f"csv-mapping: {path}: {reason}")
    if codes_mapping is not None:
        for path in sorted(set(codes_mapping.get("fields", {})) - fields):
            errors.append(f"codes-mapping: unknown model field {path}")
        for path, translations in codes_mapping.get("fields", {}).items():
            field = model.get("fields", {}).get(path, {})
            canonical = set(accepted_values(field))
            if not isinstance(translations, Mapping):
                errors.append(f"codes-mapping: {path} must contain a JSON object")
                continue
            for raw, value in translations.items():
                if value is not None and str(value) not in canonical:
                    errors.append(f"codes-mapping: {path} maps {raw!r} to unknown canonical value {value!r}")
    if site is not None:
        errors.extend(check_site(site, cda))
    errors.extend(validate_target_defaults(cda, cda_mapping))
    errors.extend(validate_structures(model, cda, cda_mapping))
    return errors


def verify_compiled_cda(cda: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    document = cda.get("document", [])
    roots = [node for node in document if node.get("kind") == "element"]
    if len(roots) != 1:
        errors.append(f"compiled CDA must contain exactly one document root, found {len(roots)}")
    locations: dict[str, Mapping[str, Any]] = {}
    def walk(nodes: list[Mapping[str, Any]], prefix: tuple[int, ...] = ()) -> None:
        for index, node in enumerate(nodes):
            here = prefix + (index,); key = ".".join(map(str, here)); locations[key] = node
            prohibited = str(node.get("conformance") or "").upper() == "NP"
            if prohibited and (node.get("mandatory") or int(node.get("min") or 0) > 0):
                errors.append(f"compiled CDA node {key} is NP but also required")
            for attr_index, attr in enumerate(node.get("attributes", [])):
                attr_key = ".".join(map(str, here + (100000 + attr_index,))); locations[attr_key] = attr
                if attr.get("optional") is False and attr.get("value") is None and not attr.get("targets"):
                    errors.append(f"compiled CDA required attribute {attr_key} has neither fixed value nor target")
            walk(list(node.get("children", [])), here)
    walk(list(document))
    for name, target in cda.get("targets", {}).items():
        target_locations = list(target.get("locations", []))
        for location in target_locations:
            if str(location) not in locations:
                errors.append(f"CDA target {name} references missing location {location}")
        if target.get("prohibited") and target.get("renderable"):
            errors.append(f"CDA target {name} is prohibited but marked renderable")
        if target.get("fixed_text") is not None and target.get("renderable"):
            errors.append(f"CDA target {name} has fixed text but is marked renderable")
        if (
            target.get("kind") == "attribute"
            and target.get("fixed", {}).get("value") is not None
            and target.get("renderable")
            and not target.get("conditional_fixed")
        ):
            errors.append(f"CDA target {name} is a fixed attribute but marked renderable")
        if target.get("renderable") and len(target_locations) != 1:
            errors.append(f"CDA target {name} is renderable but has {len(target_locations)} physical locations")
        if target.get("writable") and not target.get("value_representation"):
            errors.append(f"CDA target {name} is writable without a compiled value representation")
        if target.get("writable") and len(target_locations) != 1:
            errors.append(f"CDA value target {name} has {len(target_locations)} physical locations")
        if target.get("writable") and not target.get("logical_types"):
            errors.append(f"CDA value target {name} has no compiled logical types")
    # Error-level ART-DECOR assertions must be executable by the built-in
    # validator.  Evaluate them against an empty context only to distinguish
    # supported syntax from unsupported syntax; True/False is irrelevant here.
    dummy_root = ET.Element("{urn:hl7-org:v3}ClinicalDocument")
    dummy_context = ET.SubElement(dummy_root, "{urn:hl7-org:v3}observation")
    for assertion in cda.get("assertions", []):
        if str(assertion.get("role") or "error").casefold() != "error":
            continue
        result = evaluate_assertion(
            str(assertion.get("test") or ""), dummy_context, dummy_root, assertion.get("lets", {})
        )
        if result is None:
            errors.append(
                "compiled CDA contains unsupported error-level ART-DECOR assert: "
                + str(assertion.get("test") or "")
            )
    return errors


def verify_compiled_against_artdecor(cda: Mapping[str, Any], xml_paths: Iterable[Path]) -> list[str]:
    """Independent check of explicit source constraints without invoking the compiler."""
    source_by_id: dict[tuple[str, str, str, str], ET.Element] = {}
    source_assertions: dict[tuple[str, str, str, str, str, str], dict[str, str]] = {}
    templates: set[tuple[str, str]] = set()
    for path in sorted(set(xml_paths)):
        try:
            root, _ = parse_file(path)
        except (ET.ParseError, OSError):
            continue
        for template in root.iter():
            if local(template.tag) != "template" or not template.get("id"):
                continue
            tid, eff = template.get("id") or "", template.get("effectiveDate") or ""
            templates.add((tid, eff))
            def collect(parent: ET.Element, parent_path: tuple[str, ...] = ()) -> None:
                for node in list(parent):
                    kind = local(node.tag)
                    current_path = parent_path
                    if kind == "element":
                        current_path = parent_path + (node.get("name") or "element",)
                    elif kind == "attribute" and node.get("name"):
                        current_path = parent_path + ("@" + (node.get("name") or "attribute"),)
                    physical_path = "/".join(current_path)
                    if kind in {"element", "attribute"} and node.get("id"):
                        source_by_id[(tid, eff, node.get("id") or "", physical_path)] = node
                    if kind == "element":
                        lets = {
                            child.get("name") or "": child.get("value") or ""
                            for child in list(node)
                            if local(child.tag) == "let" and child.get("name") and child.get("value")
                        }
                        for assertion in list(node):
                            if local(assertion.tag) != "assert" or not assertion.get("test"):
                                continue
                            key = (
                                tid, eff, node.get("id") or "", physical_path,
                                assertion.get("test") or "", assertion.get("role") or "error",
                            )
                            source_assertions[key] = lets
                    collect(node, current_path)

            collect(template)
    errors: list[str] = []
    doc = cda.get("document_template", {})
    doc_key = (str(doc.get("id") or ""), str(doc.get("effective_date") or ""))
    if doc_key not in templates:
        errors.append(f"source verification: document template {doc_key[0]}@{doc_key[1]} not found")
    for name, target in cda.get("targets", {}).items():
        element_id = str(target.get("element_id") or "")
        if not element_id:
            continue
        key = (
            str(target.get("template_id") or ""),
            str(target.get("template_effective_date") or ""),
            element_id,
            str(target.get("path") or ""),
        )
        source = source_by_id.get(key)
        if source is None:
            continue
        explicit_type = source.get("datatype")
        if explicit_type and str(target.get("datatype") or "") != explicit_type:
            errors.append(f"source verification: {name} datatype {target.get('datatype')!r} != explicit {explicit_type!r}")
        if local(source.tag) == "element":
            if source.get("conformance") == "NP" and not target.get("prohibited"):
                errors.append(f"source verification: {name} ignores explicit NP conformance")
            fixed_text = None; fixed: dict[str, str] = {}
            for child in list(source):
                if local(child.tag) == "text":
                    text = "".join(child.itertext()).strip()
                    if text: fixed_text = text
                elif local(child.tag) == "attribute" and child.get("name") and child.get("value"):
                    fixed[child.get("name") or ""] = child.get("value") or ""
            if fixed_text is not None and target.get("fixed_text") != fixed_text:
                errors.append(f"source verification: {name} lost explicit fixed text {fixed_text!r}")
            for attr_name, attr_value in fixed.items():
                if str(target.get("fixed", {}).get(attr_name) or "") != attr_value:
                    errors.append(f"source verification: {name} lost fixed @{attr_name}={attr_value!r}")
        elif local(source.tag) == "attribute":
            source_value = source.get("value")
            if source_value is None:
                codes = {
                    str(node.get("code")) for node in list(source)
                    if local(node.tag) == "vocabulary" and node.get("code") is not None
                }
                source_value = next(iter(codes)) if len(codes) == 1 else None
            if (
                source_value is not None
                and str(target.get("fixed", {}).get("value") or "") != str(source_value)
            ):
                errors.append(
                    f"source verification: {name} lost fixed attribute value {source_value!r}"
                )

    compiled_by_source: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    def structural(nodes: list[Mapping[str, Any]]) -> None:
        for node in nodes:
            for source in node.get("sources", []):
                source_key = (
                    str(source.get("template_id") or ""),
                    str(source.get("template_effective_date") or ""),
                    str(source.get("element_id") or ""),
                    str(source.get("path") or ""),
                )
                if source_key[2]:
                    compiled_by_source[source_key].append(node)
            structural(list(node.get("children", [])))
    structural(list(cda.get("document", [])))
    for key, source_lets in source_assertions.items():
        source_key = key[:4]
        compiled_nodes = compiled_by_source.get(source_key, [])
        if not compiled_nodes:
            # The source element itself is not part of the effective specialized
            # document (for example a parent-only prototype choice). Its assert
            # is therefore not an effective runtime constraint.
            continue
        match = next((
            node for node in compiled_nodes
            if any(
                str(item.get("test") or "") == key[4]
                and str(item.get("role") or "error") == key[5]
                for item in node.get("asserts", [])
            )
        ), None)
        if match is None:
            errors.append(
                f"source verification: lost ART-DECOR assert {key[4]!r} from {key[0]}@{key[1]}:{key[2]}"
            )
            continue
        compiled_lets = match.get("lets", {}) if isinstance(match.get("lets"), Mapping) else {}
        for let_name, let_value in source_lets.items():
            if str(compiled_lets.get(let_name) or "") != let_value:
                errors.append(
                    f"source verification: ART-DECOR assert {key[4]!r} lost let ${let_name}={let_value!r}"
                )
    return errors


def _problem(severity: str, path: str, message: str) -> dict[str, str]:
    return {"severity": severity, "path": path, "message": message}


def validate_record(record: Mapping[str, Any], model: Mapping[str, Any]) -> list[dict[str, str]]:
    problems = list(record.get("problems", []))

    def occurrence_values(path: str, field: Mapping[str, Any]) -> list[tuple[str, Any]]:
        chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
        if not chain:
            return [(path, record.get("values", {}).get(path))]
        out: list[tuple[str, Any]] = []
        def walk(instances: Mapping[str, Any], depth: int, coords: tuple[int, ...]) -> None:
            rows = instances.get(str(chain[depth]), []) if isinstance(instances, Mapping) else []
            for index, row in enumerate(rows if isinstance(rows, list) else []):
                current = coords + (index,)
                if not isinstance(row, Mapping):
                    out.append((path + "".join(f"[{i}]" for i in current), None)); continue
                if depth == len(chain) - 1:
                    out.append((path + "".join(f"[{i}]" for i in current), row.get("values", {}).get(path)))
                else:
                    walk(row.get("instances", {}), depth + 1, current)
        walk(record.get("instances", {}), 0, ())
        return out

    for path, field in model.get("fields", {}).items():
        occurrences = occurrence_values(path, field)
        if not occurrences and field.get("required") and not field.get("repeat_chain"):
            problems.append(_problem("error", path, "required field is absent after normalization"))
            continue
        check_values: list[tuple[str, Any]] = []
        for item_path, item in occurrences:
            if item is None:
                if field.get("required"):
                    problems.append(_problem("error", item_path, "required field is absent after normalization"))
                continue
            check_values.append((item_path, item))
        maximum = field.get("max")
        if maximum is not None and not field.get("repeat_chain") and len(check_values) > int(maximum):
            problems.append(_problem("error", path, f"{len(check_values)} values exceed maximum {maximum}"))
        for item_path, item in check_values:
            if isinstance(item, Mapping) and item.get("nullFlavor"):
                problems.append(_problem("warning", item_path, f"represented as nullFlavor {item['nullFlavor']}")); continue
            if isinstance(item, (int, float)):
                if field.get("min_value") is not None and item < field["min_value"]:
                    problems.append(_problem("error", item_path, f"{item} is below minimum {field['min_value']}"))
                if field.get("max_value") is not None and item > field["max_value"]:
                    problems.append(_problem("error", item_path, f"{item} is above maximum {field['max_value']}"))
            if isinstance(item, str):
                if field.get("min_length") is not None and len(item) < field["min_length"]:
                    problems.append(_problem("error", item_path, "value is shorter than minimum length"))
                if field.get("max_length") is not None and len(item) > field["max_length"]:
                    problems.append(_problem("error", item_path, "value is longer than maximum length"))
    return problems

def validate_records(records: list[dict[str, Any]], model: Mapping[str, Any]) -> dict[str, int]:
    counts = {"records": len(records), "errors": 0, "warnings": 0}
    for record in records:
        problems = validate_record(record, model); record["problems"] = problems
        counts["errors"] += sum(problem["severity"] == "error" for problem in problems)
        counts["warnings"] += sum(problem["severity"] == "warning" for problem in problems)
    return counts
