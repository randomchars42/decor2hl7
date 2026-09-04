"""Extract mapping-supporting constraints from generated template Schematron."""

from __future__ import annotations

from collections import Counter
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


def attach_constraints(cda: dict[str, Any], include_dir: Path) -> dict[str, Any]:
    """Attach uniquely cross-referenced constraints to compiled CDA targets."""
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
    summary = {
        "source": "generated-template-schematron",
        "constraints": len(constraints),
        "matched": matched,
        "kinds": dict(sorted(Counter(
            str(item.get("kind") or "") for item in constraints
        ).items())),
    }
    cda["schematron_evidence"] = summary
    return summary
