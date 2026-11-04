"""Evaluate the XPath subset used by ART-DECOR Schematron rules.

The runtime intentionally stays standard-library only.  The evaluator supports
boolean ``and/or/not``, ``count(...)`` comparisons, attribute comparisons and
nested child/descendant selectors with predicates.  It also implements the one
XQuery-style uniqueness assertion used by a selected MDRO template.
All original expressions are additionally emitted as Schematron so an external
standards validator can apply the authoritative expression unchanged.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import escape
from typing import Any, Mapping, TypedDict

from .xmlnames import KNOWN_PREFIXES

HL7 = "urn:hl7-org:v3"


class PathStep(TypedDict):
    name: str
    attribute: bool
    expected: str | None
    predicates: list[Expression]


class Selection(TypedDict):
    descendant: bool
    steps: list[PathStep]


class Expression(TypedDict, total=False):
    kind: str
    children: list[Expression]
    selection: Selection
    operator: str
    limit: int


_NAME = r"[A-Za-z_][\w.-]*(?::[A-Za-z_][\w.-]*)?"
_LITERAL = r"(?:'[^']*'|\"[^\"]*\")"
_UNIQUE = re.compile(
    r"empty\(\$([A-Za-z_][\w-]*)\[count\(index-of\(\$\1/@code\|\$\1/@nullFlavor,"
    r"\./@code\|\./@nullFlavor\)\) > 1\]\)"
)


def _qname(name: str, namespaces: Mapping[str, str]) -> str:
    prefix, separator, local_name = name.partition(":")
    if not separator:
        return name
    uri = namespaces.get(prefix) or KNOWN_PREFIXES.get(prefix)
    if not uri:
        raise ValueError(f"unsupported namespace prefix {prefix!r}")
    return f"{{{uri}}}{local_name}"


def _expression_text(value: str) -> str:
    """Normalize only whitespace outside XPath literals; check delimiters."""
    result: list[str] = []
    stack: list[str] = []
    quote = ""
    for char in value.strip():
        if quote:
            result.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            result.append(char)
        elif char in "([":
            stack.append(char)
            result.append(char)
        elif char in ")]":
            expected = "(" if char == ")" else "["
            if not stack or stack.pop() != expected:
                raise ValueError("unbalanced XPath delimiters")
            result.append(char)
        elif char.isspace():
            if result and result[-1] != " ":
                result.append(" ")
        else:
            result.append(char)
    if quote or stack:
        raise ValueError("unbalanced XPath expression")
    return "".join(result).strip()


def _split_top(expr: str, token: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    quote = ""
    index = 0
    while index < len(expr):
        char = expr[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and expr.startswith(token, index):
            parts.append(expr[start:index].strip())
            index += len(token)
            start = index
            continue
        index += 1
    if parts:
        parts.append(expr[start:].strip())
    return parts


def _strip_outer(expr: str) -> str:
    while expr.startswith("(") and expr.endswith(")"):
        # A temporary top-level token distinguishes (a) or (b) from (a or b).
        depth = 0
        quote = ""
        end = -1
        for index, char in enumerate(expr):
            if quote:
                if char == quote:
                    quote = ""
            elif char in "'\"":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end != len(expr) - 1:
            break
        expr = expr[1:-1].strip()
    return expr


def _parse_selection(
    text: str, variables: Mapping[str, str], namespaces: Mapping[str, str],
) -> Selection:
    descendant = text.startswith("//")
    raw = text[2:] if descendant else text
    segments = _split_top(raw, "/") or [raw]
    steps: list[PathStep] = []
    for index, segment in enumerate(segments):
        attribute = re.fullmatch(rf"@({_NAME})(?:\s*=\s*({_LITERAL}))?", segment)
        if attribute:
            if index != len(segments) - 1:
                raise ValueError("attributes must end an XPath selection")
            literal = attribute.group(2)
            steps.append({"name": _qname(attribute.group(1), namespaces), "attribute": True,
                          "expected": literal[1:-1] if literal else None, "predicates": []})
            continue
        name = re.match(rf"^({_NAME})", segment)
        if not name:
            raise ValueError(f"unsupported XPath step {segment!r}")
        suffix = segment[name.end():].strip()
        predicates: list[Expression] = []
        while suffix:
            if not suffix.startswith("["):
                raise ValueError(f"unsupported XPath step {segment!r}")
            depth = 0
            quote = ""
            end = -1
            for offset, char in enumerate(suffix):
                if quote:
                    if char == quote:
                        quote = ""
                elif char in "'\"":
                    quote = char
                elif char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        end = offset
                        break
            if end < 0:
                raise ValueError("unclosed XPath predicate")
            predicates.append(_parse_expression(suffix[1:end], variables, namespaces))
            suffix = suffix[end + 1:].strip()
        steps.append({"name": _qname(name.group(1), namespaces), "attribute": False,
                      "expected": None, "predicates": predicates})
    return {"descendant": descendant, "steps": steps}


def _parse_expression(
    text: str, variables: Mapping[str, str], namespaces: Mapping[str, str],
) -> Expression:
    expr = _strip_outer(_expression_text(text))
    if not expr:
        raise ValueError("empty XPath expression")
    unique = _UNIQUE.fullmatch(expr)
    if unique:
        variable = unique.group(1)
        if variable not in variables:
            raise ValueError("unknown XPath sequence variable")
        return {"kind": "unique", "selection": _parse_selection(variables[variable], {}, namespaces)}
    for operator in ("or", "and"):
        parts = _split_top(expr, f" {operator} ")
        if parts:
            return {"kind": operator, "children": [_parse_expression(part, variables, namespaces) for part in parts]}
    if expr.startswith("not(") and expr.endswith(")"):
        return {"kind": "not", "children": [_parse_expression(expr[4:-1], variables, namespaces)]}
    count = re.fullmatch(r"count\((.*)\)\s*(<=|>=|=|<|>)\s*(\d+)", expr)
    if count:
        return {"kind": "count", "selection": _parse_selection(count.group(1), variables, namespaces),
                "operator": count.group(2), "limit": int(count.group(3))}
    return {"kind": "path", "selection": _parse_selection(expr, variables, namespaces)}


def _select(selection: Selection, context: ET.Element, root: ET.Element) -> list[Any]:
    current: list[Any] = [root if selection["descendant"] else context]
    for index, step in enumerate(selection["steps"]):
        if step["attribute"]:
            return [item.get(step["name"]) for item in current
                    if isinstance(item, ET.Element) and item.get(step["name"]) is not None
                    and (step["expected"] is None or item.get(step["name"]) == step["expected"])]
        candidates = [node for item in current if isinstance(item, ET.Element)
                      for node in (item.iter() if selection["descendant"] and index == 0 else iter(item))
                      if node.tag == step["name"]]
        for predicate in step["predicates"]:
            candidates = [node for node in candidates if _evaluate(predicate, node, root)]
        current = candidates
    return current


def _evaluate(expression: Expression, context: ET.Element, root: ET.Element) -> bool:
    kind = expression["kind"]
    if kind == "or":
        return any(_evaluate(child, context, root) for child in expression["children"])
    if kind == "and":
        return all(_evaluate(child, context, root) for child in expression["children"])
    if kind == "not":
        return not _evaluate(expression["children"][0], context, root)
    values = _select(expression["selection"], context, root)
    if kind == "count":
        count, limit, operator = len(values), expression["limit"], expression["operator"]
        return {"<=": count <= limit, ">=": count >= limit, "=": count == limit,
                "<": count < limit, ">": count > limit}[operator]
    if kind == "unique":
        keys = [("code", node.get("code")) if node.get("code") is not None else ("nullFlavor", node.get("nullFlavor"))
                for node in values if isinstance(node, ET.Element)
                and (node.get("code") is not None or node.get("nullFlavor") is not None)]
        return len(keys) == len(set(keys))
    return bool(values)


def evaluate(
    test: str, context: ET.Element, root: ET.Element,
    lets: Mapping[str, str] | None = None,
    namespaces: Mapping[str, str] | None = None,
) -> bool | None:
    try:
        expression = _parse_expression(test, lets or {}, namespaces or {})
    except ValueError:
        return None
    return _evaluate(expression, context, root)


def validate_contexts(
    root: ET.Element,
    contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []; warnings: list[str] = []
    for element, rules, lets in contexts:
        for rule in rules:
            test = str(rule.get("test") or "")
            raw_namespaces = rule.get("namespaces", {})
            namespaces = (
                {
                    str(prefix): str(uri)
                    for prefix, uri in raw_namespaces.items()
                }
                if isinstance(raw_namespaces, Mapping) else {}
            )
            result = evaluate(test, element, root, lets, namespaces)
            label = str(rule.get("message") or test)
            source = f"{rule.get('template_id') or '?'}:{rule.get('element_id') or rule.get('path') or '?'}"
            kind = str(rule.get("kind") or "assert").casefold()
            fired = result is True if kind == "report" else result is False
            role = str(rule.get("role") or "error").casefold()
            if fired:
                verb = "reported" if kind == "report" else "failed"
                message = f"ART-DECOR {kind} {verb} [{source}]: {label} ({test})"
                if role in {"fatal", "error"}: errors.append(message)
                else: warnings.append(message)
            elif result is None:
                message = f"ART-DECOR {kind} could not be evaluated [{source}]: {test}"
                if role in {"fatal", "error"}:
                    errors.append(message)
                else:
                    warnings.append(message)
    return errors, warnings


def schematron(cda: Mapping[str, Any]) -> str:
    rules = list(cda.get("validation_rules", []))
    namespace_uris = {"hl7": HL7}
    prefix_pattern = re.compile(
        r"(?<![:\w.-])([A-Za-z_][\w.-]*):(?=[A-Za-z_*])"
    )
    for rule in rules:
        raw_namespaces = rule.get("namespaces", {})
        available = (
            {
                str(prefix): str(uri)
                for prefix, uri in raw_namespaces.items()
            }
            if isinstance(raw_namespaces, Mapping) else {}
        )
        expressions = [
            str(rule.get("path") or ""),
            str(rule.get("test") or ""),
            *(str(value) for value in dict(rule.get("lets", {})).values()),
        ]
        for prefix in {
            match.group(1)
            for expression in expressions
            for match in prefix_pattern.finditer(expression)
        }:
            uri = available.get(prefix) or KNOWN_PREFIXES.get(prefix)
            if uri is None:
                raise ValueError(
                    f"ART-DECOR assertion uses undeclared namespace prefix {prefix!r}"
                )
            previous = namespace_uris.get(prefix)
            if previous is not None and previous != uri:
                raise ValueError(
                    f"ART-DECOR assertions bind namespace prefix {prefix!r} "
                    f"to both {previous!r} and {uri!r}"
                )
            namespace_uris[prefix] = uri
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">',
        *(
            f'  <sch:ns prefix="{escape(prefix, quote=True)}" '
            f'uri="{escape(namespace_uris[prefix], quote=True)}"/>'
            for prefix in sorted(namespace_uris)
        ),
        '  <sch:pattern id="art-decor-assertions">',
    ]
    for index, rule in enumerate(rules, 1):
        path = str(rule.get("path") or "hl7:ClinicalDocument")
        tid = str(rule.get("template_id") or "")
        parts = [part for part in path.split("/") if part]
        context = "/".join(parts)
        # Most assertions are on a template root or descendant. Constrain the
        # root when possible without rewriting the authoritative test itself.
        if tid and parts:
            context = f"{context}[ancestor-or-self::*[hl7:templateId/@root='{tid}']]"
        kind = "report" if str(rule.get("kind") or "assert").casefold() == "report" else "assert"
        role = escape(str(rule.get("role") or "error"), quote=True)
        test = escape(str(rule.get("test") or ""), quote=True)
        message = escape(str(rule.get("message") or rule.get("test") or ""))
        lines.append(f'    <sch:rule id="decor-{kind}-{index}" context="{escape(context, quote=True)}">')
        for name, value in dict(rule.get("lets", {})).items():
            lines.append(
                f'      <sch:let name="{escape(str(name), quote=True)}" value="{escape(str(value), quote=True)}"/>'
            )
        lines += [f'      <sch:{kind} role="{role}" test="{test}">{message}</sch:{kind}>',
                  '    </sch:rule>']
    lines += ['  </sch:pattern>', '</sch:schema>', '']
    return "\n".join(lines)
