"""Validation of configuration, compiled CDA constraints and normalized records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .domain import accepted_values, logical_values
from .i18n import Translator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import xml.etree.ElementTree as ET

from .assertions import evaluate as evaluate_assertion
from .bindings import (
    required_construction_gaps,
    for_each_target_positions,
    covered_shared_claims,
    non_null_requirement_satisfied,
    presence_target_complete,
    structure_rules,
    site_requirement_targets,
    validate_site_requirements,
    validate_structures,
    validate_target_defaults,
)
from .data import field_required_in_scope, mapping_locator
from .cooccurrence import (
    cooccurrence_problem_message, datatype_cooccurrence_problems,
    unavoidable_targets_problems,
)
from .cda.semantics import (
    direct_compatibility, identifier_root_for_target,
    transformed_compatibility, valid_oid,
)
from .transforms import mapping_rules, validate_transform
from .cda.model import ValueRepresentationKind
from .cda.narrative import validate_narratives
from .cda.terminology import (
    coded_fallback_rule_errors,
    reviewed_coded_map_rule_errors,
)


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
        unit_aliases = input_cfg.get("unit_aliases", {})
        if unit_aliases is not None and not isinstance(unit_aliases, Mapping):
            errors.append("site: input.unit_aliases must be an object")
        elif isinstance(unit_aliases, Mapping):
            for source, target in unit_aliases.items():
                if not str(source).strip() or not str(target).strip():
                    errors.append(
                        "site: input.unit_aliases must map non-empty unit "
                        "spellings to non-empty UCUM units"
                    )
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
                    order_by = spec.get("order_by", [])
                    if not isinstance(order_by, list) or not all(
                        isinstance(column, str) and column.strip()
                        for column in order_by
                    ):
                        errors.append(
                            f"site: input.sources.{name}.order_by must be a list of non-empty column names"
                        )
    source_cfg = site.get("source", {})
    if source_cfg is not None and not isinstance(source_cfg, Mapping):
        errors.append("site: source must be an object")
    elif isinstance(source_cfg, Mapping):
        adapter = source_cfg.get("adapter")
        allowed_source_keys = {
            "adapter", "dsn_env", "database", "written_at_column", "window_days",
            "queries", "require_snapshot_advance",
        }
        unknown = sorted(str(key) for key in source_cfg if key not in allowed_source_keys)
        if unknown:
            errors.append("site: unsupported source option(s): " + ", ".join(unknown))
        if adapter not in (None, "odbc", "sqlite"):
            errors.append(Translator().text("ui.source_adapter_invalid"))
        if adapter in ("odbc", "sqlite"):
            if adapter == "sqlite" and (
                not isinstance(source_cfg.get("database"), str)
                or not str(source_cfg.get("database")).strip()
            ):
                errors.append(Translator().text("ui.sqlite_database_required"))
            required = ("dsn_env", "written_at_column") if adapter == "odbc" else ("written_at_column",)
            for key in required:
                if not isinstance(source_cfg.get(key), str) or not str(source_cfg.get(key)).strip():
                    errors.append(f"site: source.{key} must be a non-empty string")
            days = source_cfg.get("window_days", 90)
            if isinstance(days, bool) or not isinstance(days, int) or days < 1:
                errors.append("site: source.window_days must be a positive integer")
            queries = source_cfg.get("queries")
            if not isinstance(queries, Mapping):
                errors.append("site: source.queries must be an object")
            else:
                configured_sources = (
                    input_cfg.get("sources", {})
                    if isinstance(input_cfg, Mapping) else {}
                )
                expected = set(configured_sources) if isinstance(configured_sources, Mapping) else set()
                actual = set(queries)
                for name in sorted(expected - actual):
                    errors.append(f"site: source.queries is missing {name!r}")
                for name in sorted(actual - expected):
                    errors.append(f"site: source.queries references unknown input source {name!r}")
                for name, path in queries.items():
                    if not isinstance(path, str) or not path.strip():
                        errors.append(f"site: source.queries[{name!r}] must be a non-empty path")
            advance = source_cfg.get("require_snapshot_advance", True)
            if not isinstance(advance, bool):
                errors.append("site: source.require_snapshot_advance must be boolean")
    operation = site.get("operation", {})
    if operation is not None and not isinstance(operation, Mapping):
        errors.append("site: operation must be an object")
    elif isinstance(operation, Mapping):
        threshold = operation.get("failure_threshold", 0)
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
            errors.append("site: operation.failure_threshold must be a non-negative integer")
    if cda is not None:
        targets = cda.get("targets", {})
        cda_config = site.get("cda", {})
        for key in ("values", "fallback_if_active"):
            values = (
                cda_config.get(key, {})
                if isinstance(cda_config, Mapping) else {}
            )
            if values is not None and not isinstance(values, Mapping):
                errors.append(f"site: cda.{key} must be an object")
            elif isinstance(values, Mapping):
                for name in values:
                    target = targets.get(name)
                    if not target or not target.get("writable") or len(target.get("locations", [])) != 1:
                        errors.append(
                            f"site: cda.{key} references unknown/prohibited/"
                            f"ambiguous target {name!r}"
                        )
    return errors


def check_config(
    model: Mapping[str, Any], cda: Mapping[str, Any], csv_mapping: Mapping[str, Any],
    cda_mapping: Mapping[str, Any], codes_mapping: Mapping[str, Any] | None = None,
    site: Mapping[str, Any] | None = None,
    *, require_site_configuration: bool = True,
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
    field_reviews = cda_mapping.get("field_reviews", {})
    if not isinstance(field_reviews, Mapping):
        errors.append("cda-mapping: field_reviews must be an object")
    else:
        allowed_review_keys = {
            "status", "reason", "decision", "reviewed_at", "evidence",
        }
        for path, review in field_reviews.items():
            if path not in fields:
                errors.append(
                    f"cda-mapping: field_reviews references unknown model field {path}"
                )
                continue
            if not isinstance(review, Mapping):
                errors.append(
                    f"cda-mapping: field_reviews[{path!r}] must be an object"
                )
                continue
            if review.get("status") != "intentionally_unmapped":
                errors.append(
                    f"cda-mapping: field_reviews[{path!r}] has unsupported "
                    f"status {review.get('status')!r}"
                )
            if not isinstance(review.get("reason"), str) or not str(
                review.get("reason") or ""
            ).strip():
                errors.append(
                    f"cda-mapping: field_reviews[{path!r}] requires a reason"
                )
            extra = set(review) - allowed_review_keys
            if extra:
                errors.append(
                    f"cda-mapping: field_reviews[{path!r}] has unknown keys "
                    + ", ".join(sorted(map(str, extra)))
                )
            if cda_mapping.get("fields", {}).get(path) is not None:
                errors.append(
                    f"cda-mapping: field_reviews[{path!r}] is intentionally "
                    "unmapped but fields contains a mapping"
                )
    targets = cda.get("targets", {})
    datapoints = cda.get("datapoints", {})
    structures_by_id = {
        str(rule.get("id") or ""): rule
        for rule in structure_rules(cda_mapping)
    }
    claims: dict[str, list[str]] = defaultdict(list)
    configured_targets: set[str] = set()
    configured_target_modes: dict[str, bool] = {}
    for path, value in cda_mapping.get("fields", {}).items():
        field = model.get("fields", {}).get(path, {})
        for rule in mapping_rules(value):
            target_name = str(rule["target"])
            cda_target_name = str(rule.get("cda_target") or target_name)
            if isinstance(datapoints, Mapping) and datapoints:
                datapoint = datapoints.get(target_name)
                if not isinstance(datapoint, Mapping):
                    # The mapping guide also exposes reviewed physical targets
                    # which are intentionally absent from generated logical
                    # proposal datapoints. They remain subject to the complete
                    # physical target, type, and conformance validation below.
                    if target_name in targets:
                        if cda_target_name != target_name:
                            errors.append(
                                f"cda-mapping: {path} physical target "
                                f"{target_name} resolves to itself, not "
                                f"{cda_target_name}"
                            )
                            continue
                        cda_target_name = target_name
                    else:
                        errors.append(
                            f"cda-mapping: {path} references unknown logical CDA "
                            f"datapoint {target_name}"
                        )
                        continue
                else:
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
            mode = rule.get("mode")
            if mode not in {
                None, "fallback", "fallback_if_active", "if_active", "presence",
            }:
                errors.append(
                    f"cda-mapping: {path} -> {target_name}: unknown assignment mode "
                    f"{rule.get('mode')!r}"
                )
            if mode not in {"fallback", "fallback_if_active"}:
                claims[cda_target_name].append(path)
            configured_targets.add(cda_target_name)
            configured_target_modes[cda_target_name] = bool(
                configured_target_modes.get(cda_target_name, True)
                and mode == "presence"
            )
            valid_presence_target = bool(
                mode == "presence" and target.get("renderable")
                and target.get("has_children") and not target.get("prohibited")
                and presence_target_complete(cda, target)
            )
            if target.get("prohibited") or (
                not target.get("writable") and not valid_presence_target
            ):
                errors.append(
                    f"cda-mapping: {path} references prohibited/non-renderable "
                    f"target {cda_target_name}"
                )
            locations = target.get("locations", [])
            if len(locations) != 1:
                errors.append(f"cda-mapping: {path} target {cda_target_name} has {len(locations)} physical locations")
            transform = rule.get("transform")
            for transform_reason in validate_transform(transform):
                errors.append(
                    f"cda-mapping: {path} -> {target_name}: {transform_reason}"
                )
            if (
                isinstance(transform, Mapping)
                and transform.get("type") == "coded_fallback"
            ):
                for transform_reason in coded_fallback_rule_errors(
                    transform, target, targets,
                    cda.get("terminology_constraints", {}),
                ):
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: "
                        + transform_reason
                    )
            if (
                isinstance(transform, Mapping)
                and transform.get("type") == "reviewed_coded_map"
            ):
                for transform_reason in reviewed_coded_map_rule_errors(
                    transform, field, target, targets,
                    cda.get("terminology_constraints", {}),
                ):
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: "
                        + transform_reason
                    )
            if mode == "presence":
                if str(field.get("type") or "") != "boolean":
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: presence mode requires a boolean source"
                    )
                continue
            if mode in {"fallback_if_active", "if_active"}:
                review_reason = rule.get("reason")
                if not isinstance(review_reason, str) or not review_reason.strip():
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: "
                        f"{mode} requires a non-empty review reason"
                    )
            if mode == "if_active":
                active_if = str(rule.get("active_if") or "")
                guard = targets.get(active_if)
                if not active_if or not isinstance(guard, Mapping):
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: if_active "
                        "requires one exact active_if CDA target"
                    )
                elif active_if == cda_target_name:
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: if_active "
                        "cannot guard itself"
                    )
                elif list(guard.get("repeat_ancestors") or []) != list(
                    target.get("repeat_ancestors") or []
                ):
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: if_active "
                        "guard and value must have the same occurrence shape"
                    )
            if mode == "fallback_if_active":
                target_required = bool(target.get("mandatory")) or int(
                    target.get("min") or 0
                ) >= 1
                if not target_required:
                    errors.append(
                        f"cda-mapping: {path} -> {target_name}: "
                        "fallback_if_active requires a target that is mandatory "
                        "inside its active branch"
                    )
            compatibility_field = field
            structure_name = rule.get("structure")
            structure = structures_by_id.get(str(structure_name or ""), {})
            if structure.get("type") == "repeat_by_discriminator":
                compatibility_field = dict(field)
                chain = list(
                    field.get("repeat_chain")
                    or ([] if not field.get("repeat") else [field.get("repeat")])
                )
                compatibility_field["repeat_chain"] = chain + [
                    f"repeat_by_discriminator:{structure_name}"
                ]
            compatible: bool
            reasons: list[str]
            if (
                structure.get("type") == "compose_coded"
                and str(structure.get("target") or "") == cda_target_name
                and any(
                    isinstance(source, Mapping)
                    and str(source.get("source") or "") == str(path)
                    for source in structure.get("sources", [])
                )
            ):
                # The structure owns the role-specific transforms and composes
                # their outputs into one coded datatype.  Validating either
                # source directly against that final coded target would reject
                # the display-name text before composition.
                compatible, reasons = True, []
            else:
                compatible, reasons = transformed_compatibility(
                    compatibility_field, target, transform
                )
            if for_each_target_positions(field, target, cda, cda_mapping) is not None:
                reasons = [
                    compatibility_reason
                    for compatibility_reason in reasons
                    if not compatibility_reason.startswith("dataset has ")
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
    for target_name, problems in unavoidable_targets_problems(
        cda, configured_target_modes,
    ).items():
        for problem in problems:
            errors.append(
                f"cda-mapping: target {target_name} is not admissible: "
                + cooccurrence_problem_message(problem)
            )
    site_cda = site.get("cda", {}) if isinstance(site, Mapping) else {}
    site_targets = {
        str(name)
        for key in ("values", "fallback_if_active")
        for name in (
            site_cda.get(key, {})
            if isinstance(site_cda, Mapping)
            and isinstance(site_cda.get(key, {}), Mapping)
            else {}
        )
    }
    declared_site_targets = site_requirement_targets(cda, cda_mapping)
    supplied_targets = configured_targets | site_targets | declared_site_targets
    for target_name in sorted(configured_targets | declared_site_targets):
        for required_target in map(
            str, targets.get(target_name, {}).get("non_null_requires", [])
        ):
            if not non_null_requirement_satisfied(
                cda, required_target, supplied_targets
            ):
                errors.append(
                    f"cda-mapping: target {target_name} requires a non-null "
                    f"companion at {required_target}"
                )
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
            canonical = set(accepted_values(field)) | set(logical_values(field))
            formal = field.get("formal_terminology", {})
            formal_status = (
                str(formal.get("status") or "")
                if isinstance(formal, Mapping) else ""
            )
            coded_domain = field.get("coded_domain", {})
            coded_status = (
                str(coded_domain.get("status") or "")
                if isinstance(coded_domain, Mapping) else ""
            )
            if not isinstance(translations, Mapping):
                errors.append(f"codes-mapping: {path} must contain a JSON object")
                continue
            for raw, value in translations.items():
                explicit_unbound_code = (
                    not canonical
                    and field.get("type") == "code"
                    and formal_status in {"", "unbound", "unconstrained"}
                    and coded_status not in {"referenced", "unresolved"}
                    and isinstance(value, Mapping)
                    and isinstance(value.get("code"), str)
                    and bool(value.get("code"))
                    and isinstance(value.get("codeSystem"), str)
                    and bool(value.get("codeSystem"))
                    and all(
                        key in {"code", "codeSystem", "displayName"}
                        and isinstance(item, str)
                        for key, item in value.items()
                    )
                )
                if (
                    value is not None
                    and str(value) not in canonical
                    and not explicit_unbound_code
                ):
                    errors.append(f"codes-mapping: {path} maps {raw!r} to unknown canonical value {value!r}")
    if site is not None:
        errors.extend(check_site(site, cda))
        site_cda = site.get("cda", {})
        site_values = {
            str(name): value
            for key in ("values", "fallback_if_active")
            for name, value in (
                site_cda.get(key, {}).items()
                if isinstance(site_cda, Mapping)
                and isinstance(site_cda.get(key, {}), Mapping)
                else []
            )
        }
        if isinstance(site_values, Mapping):
            for problem in datatype_cooccurrence_problems(cda, site_values):
                errors.append(
                    f"site: cda.values[{problem.get('target')!r}] is not admissible: "
                    + cooccurrence_problem_message(problem)
                )
    errors.extend(validate_site_requirements(
        cda, cda_mapping, site,
        require_configured=require_site_configuration,
    ))
    errors.extend(validate_target_defaults(cda, cda_mapping))
    errors.extend(validate_structures(model, cda, cda_mapping))
    errors.extend(validate_narratives(model, cda, cda_mapping))
    errors.extend(
        f"cda-mapping: {problem}"
        for problem in required_construction_gaps(cda, cda_mapping, site)
    )
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
            if node.get("kind") == "choice":
                minimum = int(node.get("min") or 0)
                maximum = node.get("max")
                alternatives = list(node.get("children", []))
                if minimum < 0 or (
                    isinstance(maximum, int) and maximum < minimum
                ):
                    errors.append(
                        f"compiled CDA choice {key} has invalid bounds "
                        f"{minimum}..{maximum}"
                    )
                if not alternatives and minimum:
                    errors.append(
                        f"compiled CDA choice {key} requires alternatives but has none"
                    )
                invalid = [
                    str(child.get("kind") or "") for child in alternatives
                    if child.get("kind") not in {"element", "include", "choice"}
                ]
                if invalid:
                    errors.append(
                        f"compiled CDA choice {key} has invalid alternatives: "
                        + ", ".join(invalid)
                    )
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
    # Error-level ART-DECOR validation rules must be executable by the built-in
    # validator.  Evaluate them against an empty context only to distinguish
    # supported syntax from unsupported syntax; True/False is irrelevant here.
    dummy_root = ET.Element("{urn:hl7-org:v3}ClinicalDocument")
    dummy_context = ET.SubElement(dummy_root, "{urn:hl7-org:v3}observation")
    for rule in cda.get("validation_rules", []):
        if str(rule.get("role") or "error").casefold() not in {"fatal", "error"}:
            continue
        result = evaluate_assertion(
            str(rule.get("test") or ""), dummy_context, dummy_root, rule.get("lets", {})
        )
        if result is None:
            errors.append(
                "compiled CDA contains unsupported error-level ART-DECOR "
                f"{rule.get('kind') or 'assert'}: {rule.get('test') or ''}"
            )
    return errors


def _problem(severity: str, path: str, message: str) -> dict[str, str]:
    return {"severity": severity, "path": path, "message": message}


def validate_record(record: Mapping[str, Any], model: Mapping[str, Any]) -> list[dict[str, str]]:
    problems = list(record.get("problems", []))

    def occurrence_values(
        path: str, field: Mapping[str, Any],
    ) -> list[tuple[str, Any, Mapping[str, Any]]]:
        chain = list(field.get("repeat_chain") or ([] if not field.get("repeat") else [field.get("repeat")]))
        if not chain:
            scope = record.get("values", {})
            return [(path, scope.get(path), scope)]
        out: list[tuple[str, Any, Mapping[str, Any]]] = []
        def walk(instances: Mapping[str, Any], depth: int, coords: tuple[int, ...]) -> None:
            rows = instances.get(str(chain[depth]), []) if isinstance(instances, Mapping) else []
            for index, row in enumerate(rows if isinstance(rows, list) else []):
                current = coords + (index,)
                if not isinstance(row, Mapping):
                    out.append((path + "".join(f"[{i}]" for i in current), None, {})); continue
                if depth == len(chain) - 1:
                    scope = row.get("values", {})
                    out.append((
                        path + "".join(f"[{i}]" for i in current),
                        scope.get(path), scope,
                    ))
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
        for item_path, item, scope in occurrences:
            if item is None:
                if field_required_in_scope(path, field, scope, model):
                    problems.append(_problem("error", item_path, "required field is absent after normalization"))
                continue
            check_values.append((item_path, item))
        maximum = field.get("max")
        if maximum is not None and not field.get("repeat_chain") and len(check_values) > int(maximum):
            problems.append(_problem("error", path, f"{len(check_values)} values exceed maximum {maximum}"))
        for item_path, item in check_values:
            if isinstance(item, Mapping) and item.get("nullFlavor"):
                problems.append(_problem("warning", item_path, f"represented as nullFlavor {item['nullFlavor']}")); continue
            numeric_values: list[tuple[str, int | float]] = []
            if str(field.get("type") or "") == "quantity" and isinstance(item, Mapping):
                if "value" in item and set(item) <= {"value", "unit"}:
                    value = item.get("value")
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        numeric_values.append((item_path, value))
                    else:
                        problems.append(_problem("error", item_path, "quantity value is not numeric"))
                elif set(item) <= {"low", "high"} and set(item) == {"low", "high"}:
                    bounds: dict[str, int | float] = {}
                    for label in ("low", "high"):
                        bound = item.get(label)
                        value = bound.get("value") if isinstance(bound, Mapping) else None
                        if (
                            isinstance(bound, Mapping)
                            and set(bound) <= {"value", "unit"}
                            and isinstance(value, (int, float))
                            and not isinstance(value, bool)
                        ):
                            bounds[label] = value
                            numeric_values.append((f"{item_path}.{label}", value))
                        else:
                            problems.append(_problem(
                                "error", f"{item_path}.{label}",
                                "quantity range bound is not a numeric quantity",
                            ))
                    if set(bounds) == {"low", "high"} and bounds["low"] > bounds["high"]:
                        problems.append(_problem(
                            "error", item_path, "quantity range low exceeds high",
                        ))
                else:
                    problems.append(_problem(
                        "error", item_path,
                        "quantity must contain value, or low and high",
                    ))
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                numeric_values.append((item_path, item))
            for numeric_path, numeric in numeric_values:
                if field.get("min_value") is not None and numeric < field["min_value"]:
                    problems.append(_problem("error", numeric_path, f"{numeric} is below minimum {field['min_value']}"))
                if field.get("max_value") is not None and numeric > field["max_value"]:
                    problems.append(_problem("error", numeric_path, f"{numeric} is above maximum {field['max_value']}"))
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
