"""Evaluate the XPath subset used by ART-DECOR Schematron rules.

The runtime intentionally stays standard-library only.  The evaluator supports
boolean ``and/or/not``, ``count(...)`` comparisons, attribute comparisons and
nested child/descendant selectors with predicates.  It also implements the one
XQuery-style uniqueness assertion currently used by the AKTIN MDRO template.
All original expressions are additionally emitted as Schematron so an external
standards validator can apply the authoritative expression unchanged.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import escape
from typing import Any, Mapping

from .retrieval.xml import KNOWN_PREFIXES

HL7 = "urn:hl7-org:v3"


def _qname(name: str, namespaces: Mapping[str, str]) -> str:
    prefix, separator, local_name = name.partition(":")
    if separator:
        uri = namespaces.get(prefix) or KNOWN_PREFIXES.get(prefix)
        if uri:
            return f"{{{uri}}}{local_name}"
    return name


def _strip_outer(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0; quote = None; valid = True
        for index, char in enumerate(expr):
            if quote:
                if char == quote: quote = None
                continue
            if char in "'\"": quote = char; continue
            if char == "(": depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(expr) - 1:
                    valid = False; break
        if not valid or depth != 0: break
        expr = expr[1:-1].strip()
    return expr


def _split_top(expr: str, word: str) -> list[str]:
    parts: list[str] = []
    start = 0; paren = bracket = 0; quote: str | None = None; i = 0
    token = f" {word} "
    while i < len(expr):
        char = expr[i]
        if quote:
            if char == quote: quote = None
            i += 1; continue
        if char in "'\"": quote = char; i += 1; continue
        if char == "(": paren += 1
        elif char == ")": paren -= 1
        elif char == "[": bracket += 1
        elif char == "]": bracket -= 1
        if paren == 0 and bracket == 0 and expr.startswith(token, i):
            parts.append(expr[start:i].strip()); i += len(token); start = i; continue
        i += 1
    if parts:
        parts.append(expr[start:].strip())
    return parts


def _split_path(path: str) -> tuple[bool, list[str]]:
    descendant = path.strip().startswith("//")
    text = path.strip()[2:] if descendant else path.strip()
    parts: list[str] = []
    start = 0; bracket = 0; quote: str | None = None
    for i, char in enumerate(text):
        if quote:
            if char == quote: quote = None
            continue
        if char in "'\"": quote = char; continue
        if char == "[": bracket += 1
        elif char == "]": bracket -= 1
        elif char == "/" and bracket == 0:
            parts.append(text[start:i].strip()); start = i + 1
    if text[start:].strip(): parts.append(text[start:].strip())
    return descendant, parts


def _segment(segment: str) -> tuple[str, list[str]]:
    segment = segment.strip()
    if "[" not in segment:
        return segment, []
    name = segment.split("[", 1)[0].strip()
    predicates: list[str] = []
    i = len(name); start = None; depth = 0; quote: str | None = None
    while i < len(segment):
        char = segment[i]
        if quote:
            if char == quote: quote = None
        elif char in "'\"": quote = char
        elif char == "[":
            if depth == 0: start = i + 1
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0 and start is not None:
                predicates.append(segment[start:i].strip()); start = None
        i += 1
    return name, predicates


def _select(
    path: str, context: ET.Element, root: ET.Element,
    namespaces: Mapping[str, str],
) -> list[Any]:
    descendant, segments = _split_path(path)
    if not segments:
        return []
    current: list[Any] = [root if descendant else context]
    for index, raw_segment in enumerate(segments):
        name, predicates = _segment(raw_segment)
        if name.startswith("@"):
            attr_expr = name[1:]
            m = re.fullmatch(r"([^=\s]+)\s*=\s*(['\"])(.*?)\2", attr_expr)
            if m:
                attr, expected = m.group(1), m.group(3)
                qname = _qname(attr, namespaces)
                return [item.get(qname) for item in current if isinstance(item, ET.Element) and item.get(qname) == expected]
            qname = _qname(attr_expr, namespaces)
            return [item.get(qname) for item in current if isinstance(item, ET.Element) and item.get(qname) is not None]
        qname = _qname(name, namespaces)
        candidates: list[ET.Element] = []
        for item in current:
            if not isinstance(item, ET.Element): continue
            if descendant and index == 0:
                candidates.extend([node for node in item.iter() if node.tag == qname])
            else:
                candidates.extend([node for node in list(item) if node.tag == qname])
        for predicate in predicates:
            candidates = [
                node for node in candidates
                if _eval(predicate, node, root, {}, namespaces) is True
            ]
        current = candidates
    return current


def _eval(
    expr: str, context: ET.Element, root: ET.Element,
    variables: Mapping[str, str], namespaces: Mapping[str, str],
) -> bool | None:
    expr = _strip_outer(re.sub(r"\s+", " ", expr.strip()))
    if not expr:
        return True
    # AKTIN's XQuery uniqueness assertion for the MDRO value sequence.
    if expr.startswith("empty($") and "index-of(" in expr and "@code|$" in expr and "/@nullFlavor" in expr:
        var = re.match(r"empty\(\$([A-Za-z_][A-Za-z0-9_-]*)", expr)
        if not var or var.group(1) not in variables:
            return None
        nodes = _select(variables[var.group(1)], context, root, namespaces)
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            if not isinstance(node, ET.Element): continue
            value = node.get("code")
            name = "code"
            if value is None:
                name, value = "nullFlavor", node.get("nullFlavor")
            if value is None: continue
            key = (name, value)
            if key in seen: return False
            seen.add(key)
        return True
    parts = _split_top(expr, "or")
    if parts:
        results = [
            _eval(part, context, root, variables, namespaces) for part in parts
        ]
        if any(result is True for result in results): return True
        if all(result is False for result in results): return False
        return None
    parts = _split_top(expr, "and")
    if parts:
        results = [
            _eval(part, context, root, variables, namespaces) for part in parts
        ]
        if any(result is False for result in results): return False
        if all(result is True for result in results): return True
        return None
    if expr.startswith("not(") and expr.endswith(")"):
        result = _eval(expr[4:-1], context, root, variables, namespaces)
        return None if result is None else not result
    match = re.fullmatch(r"count\((.*)\)\s*(<=|>=|=|<|>)\s*(\d+)", expr)
    if match:
        count = len(_select(match.group(1), context, root, namespaces)); expected = int(match.group(3)); op = match.group(2)
        return {"<=": count <= expected, ">=": count >= expected, "=": count == expected, "<": count < expected, ">": count > expected}[op]
    match = re.fullmatch(r"@([^=\s]+)\s*=\s*(['\"])(.*?)\2", expr)
    if match:
        return context.get(_qname(match.group(1), namespaces)) == match.group(3)
    if "$" in expr or "index-of(" in expr:
        return None
    return bool(_select(expr, context, root, namespaces))


def evaluate(
    test: str, context: ET.Element, root: ET.Element,
    lets: Mapping[str, str] | None = None,
    namespaces: Mapping[str, str] | None = None,
) -> bool | None:
    return _eval(test, context, root, lets or {}, namespaces or {})


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
