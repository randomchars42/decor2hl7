"""Extract mapping-supporting constraints from generated template Schematron."""

from __future__ import annotations

from ..contracts import cda_model, json_object

from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping
import re
import xml.etree.ElementTree as ET


SCH = "{http://purl.oclc.org/dsdl/schematron}"
_OWNER = re.compile(r"^template-((?:\d+\.)+\d+)-(.+)$")
_COUNT = re.compile(r"^\s*count\((.*)\)\s*(>=|<=)\s*(\d+)\s*$", re.DOTALL)
_FIXED = re.compile(
    r"^\s*string\(@([A-Za-z_][\w:.-]*)\)\s*=\s*\(\s*(['\"])(.*?)\2\s*\)\s*$",
    re.DOTALL,
)
_PREDICATE_VALUE = re.compile(
    r"@([A-Za-z_][\w:.-]*)\s*=\s*(['\"])(.*?)\2", re.DOTALL,
)
_VOCABULARY = re.compile(r"(?:^|/)voc-((?:\d+\.)+\d+)-(?:[^/'\"]+)\.xml")
_DATATYPE_SELECTOR = re.compile(
    r"(?:@[A-Za-z_][\w.-]*|hl7:(?:[A-Za-z_][\w.-]*|\*))"
)


def _effective_key(value: Any) -> str:
    text = str(value or "")
    return "" if text.casefold() == "dynamic" else "".join(re.findall(r"\d", text))[:8]


def split_xpath(value: str) -> list[str]:
    """Split at top-level slashes while preserving predicates and literals."""
    result: list[str] = []
    start = 0
    depth = 0
    quote = ""
    for index, character in enumerate(value):
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth = max(0, depth - 1)
        elif character == "/" and depth == 0:
            if value[start:index].strip():
                result.append(value[start:index].strip())
            start = index + 1
    if value[start:].strip():
        result.append(value[start:].strip())
    return result


def _step(value: str) -> str:
    value = value.strip()
    if value.startswith("@"):
        return "@" + value[1:].split(":", 1)[-1]
    value = value.split("[", 1)[0]
    return value.split(":", 1)[-1]


def _constraint(
    kind: str, context: str, path: str, owner: tuple[str, str],
    **values: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "context": context,
        "path": path,
        "template_id": owner[0],
        "template_effective_date": owner[1],
        **values,
    }


def _assertion_constraints(
    context: str, test: str, owner: tuple[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counted = _COUNT.fullmatch(test)
    path = ""
    if counted:
        path, operator, raw_bound = counted.groups()
        bound = int(raw_bound)
        if operator == ">=" and bound >= 1:
            rows.append(_constraint("required", context, path, owner, value=bound))
        elif operator == "<=":
            rows.append(_constraint("max_occurs", context, path, owner, value=bound))
    else:
        fixed = _FIXED.fullmatch(test)
        if fixed:
            attribute, _, value = fixed.groups()
            rows.append(_constraint(
                "fixed_value", context, "@" + attribute, owner, value=value,
            ))
        elif re.fullmatch(r"\s*@([A-Za-z_][\w:.-]*)\s*", test):
            rows.append(_constraint(
                "attribute_required", context, test.strip(), owner, value=1,
            ))

    if path:
        for match in _PREDICATE_VALUE.finditer(path):
            # Only predicates on the selected trailing step describe that
            # target. Nested templateId predicates identify a contained branch
            # and must not become fixed attributes on its structural parent.
            if path[:match.start()].count("[") - path[:match.start()].count("]") != 1:
                continue
            attribute, _, value = match.groups()
            attribute = attribute.split(":", 1)[-1]
            kind = "xsi_type" if attribute == "type" and "xsi:type" in path else "fixed_value"
            rows.append(_constraint(
                kind, context, (
                    path.rsplit("[", 1)[0]
                    if kind == "xsi_type"
                    else path.rsplit("[", 1)[0] + "/@" + attribute
                ),
                owner, value=value,
            ))
        for value_set in _VOCABULARY.findall(path):
            rows.append(_constraint(
                "value_set", context, path, owner, value_set=value_set,
            ))
    return rows


def read_constraints(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Read the supported constraint subset from template pattern files."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for path in sorted(set(paths)):
        if path.name.startswith(("DTr1_", "voc-")) or path.suffix != ".sch":
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        match = _OWNER.fullmatch(str(root.get("id") or ""))
        if match is None:
            continue
        owner = match.group(1), match.group(2)
        for rule in root.findall(f".//{SCH}rule"):
            context = str(rule.get("context") or "")
            if not context:
                continue
            for assertion in rule.findall(f"./{SCH}assert"):
                test = str(assertion.get("test") or "")
                for row in _assertion_constraints(context, test, owner):
                    key = (
                        row["kind"], row["context"], row["path"],
                        row.get("value"), row.get("value_set"), *owner,
                    )
                    if key not in seen:
                        seen.add(key)
                        result.append(row)
    return result


def _strip_outer_parentheses(value: str) -> str:
    """Remove parentheses only when they enclose the complete expression."""
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        complete = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    complete = False
                    break
                if depth < 0:
                    complete = False
                    break
        if not complete or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def _split_top_level(value: str, operator: str) -> list[str] | None:
    """Split a tiny XPath subset without accepting nested XPath syntax."""
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return None
        if depth == 0:
            if operator == "|" and character == "|":
                parts.append(value[start:index].strip())
                start = index + 1
            elif operator == "and" and value.startswith("and", index):
                before = value[index - 1] if index else " "
                after_index = index + 3
                after = value[after_index] if after_index < len(value) else " "
                if not (before.isalnum() or before in "_.-") and not (
                    after.isalnum() or after in "_.-"
                ):
                    parts.append(value[start:index].strip())
                    start = after_index
                    index = after_index - 1
        index += 1
    if depth != 0:
        return None
    parts.append(value[start:].strip())
    return parts if all(parts) else None


def _datatype_forbidden_clauses(test: str) -> list[list[str]]:
    """Compile a strict presence-only ``not(A and B)`` XPath subset.

    Each returned row is a forbidden conjunction. Parenthesized unions are
    expanded, so ``not(@value and (hl7:low|hl7:high))`` becomes two clauses.
    No XPath is evaluated and anything outside this grammar is ignored.
    """
    matched = re.fullmatch(r"\s*not\s*\((.*)\)\s*", test, re.DOTALL)
    if matched is None:
        return []
    expression = _strip_outer_parentheses(matched.group(1))
    terms = _split_top_level(expression, "and")
    if terms is None or len(terms) < 2:
        return []
    groups: list[list[str]] = []
    for term in terms:
        alternatives = _split_top_level(_strip_outer_parentheses(term), "|")
        if alternatives is None:
            return []
        selectors = [_strip_outer_parentheses(item) for item in alternatives]
        if not selectors or any(
            _DATATYPE_SELECTOR.fullmatch(selector) is None
            for selector in selectors
        ):
            return []
        groups.append(selectors)
    # Keep the accepted language deliberately small and bounded even if a
    # future upstream file contains a large union expression.
    count = 1
    for group in groups:
        count *= len(group)
    if count > 32:
        return []
    result: list[list[str]] = []
    for values in product(*groups):
        clause = list(dict.fromkeys(values))
        if len(clause) >= 2 and clause not in result:
            result.append(clause)
    return result


def read_datatype_cooccurrences(
    paths: Iterable[Path],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Read and inherit the supported datatype Schematron constraint subset."""
    direct: dict[str, list[dict[str, Any]]] = {}
    parents: dict[str, list[str]] = {}
    files = 0
    rules_seen = 0
    assertions = 0
    error_assertions = 0
    supported_assertions = 0
    for path in sorted(set(paths)):
        if not path.name.startswith("DTr1_") or path.suffix != ".sch":
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        files += 1
        rules = [node for node in root.iter() if node.tag == f"{SCH}rule"]
        for rule in rules:
            datatype = str(rule.get("id") or "")
            if not datatype:
                continue
            rules_seen += 1
            direct.setdefault(datatype, [])
            inherited = parents.setdefault(datatype, [])
            for extension in rule.findall(f"./{SCH}extends"):
                parent = str(extension.get("rule") or "")
                if parent and parent not in inherited:
                    inherited.append(parent)
            for assertion in rule.findall(f"./{SCH}assert"):
                assertions += 1
                if str(assertion.get("role") or "error").casefold() != "error":
                    continue
                error_assertions += 1
                test = str(assertion.get("test") or "")
                clauses = _datatype_forbidden_clauses(test)
                if not clauses:
                    continue
                supported_assertions += 1
                for selectors in clauses:
                    row = {
                        "selectors": selectors,
                        "test": test,
                        "declared_in": datatype,
                        "source": path.name,
                    }
                    if row not in direct[datatype]:
                        direct[datatype].append(row)

    unresolved: set[tuple[str, str]] = set()
    cycles: set[tuple[str, ...]] = set()
    memo: dict[str, list[dict[str, Any]]] = {}

    def inherited_constraints(
        datatype: str, trail: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        if datatype in memo:
            return memo[datatype]
        if datatype in trail:
            cycles.add(trail[trail.index(datatype):] + (datatype,))
            return []
        result: list[dict[str, Any]] = []
        for parent in parents.get(datatype, []):
            if parent not in direct:
                unresolved.add((datatype, parent))
                continue
            for row in inherited_constraints(parent, trail + (datatype,)):
                if row not in result:
                    result.append(row)
        for row in direct.get(datatype, []):
            if row not in result:
                result.append(row)
        memo[datatype] = result
        return result

    compiled = {
        datatype: inherited_constraints(datatype)
        for datatype in sorted(direct)
        if inherited_constraints(datatype)
    }
    summary = {
        "source": "generated-datatype-schematron",
        "files": files,
        "rules": rules_seen,
        "assertions": assertions,
        "error_assertions": error_assertions,
        "supported_assertions": supported_assertions,
        "unsupported_error_assertions": error_assertions - supported_assertions,
        "compiled_clauses": sum(len(rows) for rows in compiled.values()),
        "constrained_datatypes": len(compiled),
        "unresolved_extends": [
            {"datatype": datatype, "parent": parent}
            for datatype, parent in sorted(unresolved)
        ],
        "inheritance_cycles": [list(cycle) for cycle in sorted(cycles)],
    }
    return compiled, summary


def _matched_targets(
    constraint: Mapping[str, Any],
    target_index: Mapping[tuple[str, str], list[tuple[str, str, list[str]]]],
) -> list[str]:
    owner = str(constraint.get("template_id") or "")
    effective = _effective_key(constraint.get("template_effective_date"))
    query = split_xpath(str(constraint.get("context") or ""))
    relative = split_xpath(str(constraint.get("path") or ""))
    query.extend(relative)
    query_steps = [_step(item) for item in query if _step(item) not in {"", "*"}]
    if not query_steps:
        return []
    scored: list[tuple[int, str, str]] = []
    for name, target_effective, target_steps in target_index.get(
        (owner, query_steps[-1]), []
    ):
        if effective and target_effective and effective != target_effective:
            continue
        suffix = 0
        for left, right in zip(reversed(query_steps), reversed(target_steps)):
            if left != right:
                break
            suffix += 1
        scored.append((suffix, "/".join(target_steps), name))
    if not scored:
        return []
    best = max(score for score, _, _ in scored)
    paths = {path for score, path, _ in scored if score == best}
    if len(paths) != 1:
        return []
    return sorted(name for score, _, name in scored if score == best)


def attach_constraints(raw_cda: object, include_dir: Path) -> dict[str, Any]:
    """Attach uniquely cross-referenced constraints to compiled CDA targets."""
    cda = cda_model(raw_cda)
    constraints = read_constraints(include_dir.glob("*.sch")) if include_dir.is_dir() else []
    targets = cda.get("targets", {})
    target_index: dict[tuple[str, str], list[tuple[str, str, list[str]]]] = {}
    for name, target in targets.items():
        steps = [
            _step(item) for item in split_xpath(str(target.get("path") or ""))
            if _step(item)
        ]
        if not steps:
            continue
        key = str(target.get("template_id") or ""), steps[-1]
        target_index.setdefault(key, []).append((
            str(name), _effective_key(target.get("template_effective_date")), steps,
        ))
    matched = 0
    for constraint in constraints:
        names = _matched_targets(constraint, target_index)
        if not names:
            continue
        matched += 1
        payload = {
            key: constraint[key]
            for key in ("kind", "context", "path", "value", "value_set")
            if constraint.get(key) not in (None, "")
        }
        for name in names:
            evidence = targets[name].setdefault("schematron_constraints", [])
            if payload not in evidence:
                evidence.append(payload)
    datatype_rules, datatype_summary = read_datatype_cooccurrences(
        include_dir.glob("DTr1_*.sch") if include_dir.is_dir() else []
    )
    cda["datatype_constraints"] = json_object({
        "version": 1,
        "source": "generated-datatype-schematron",
        "rules": datatype_rules,
    })
    summary = {
        "source": "generated-template-schematron",
        "constraints": len(constraints),
        "matched": matched,
        "kinds": dict(sorted(Counter(
            str(item.get("kind") or "") for item in constraints
        ).items())),
        "datatype_cooccurrence": datatype_summary,
    }
    cda["schematron_evidence"] = json_object(summary)
    return summary
