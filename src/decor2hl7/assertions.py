"""Evaluate the XPath subset used by ART-DECOR template assertions.

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

HL7 = "urn:hl7-org:v3"


def _qname(name: str) -> str:
    if name.startswith("hl7:"):
        return f"{{{HL7}}}{name.split(':', 1)[1]}"
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


def _select(path: str, context: ET.Element, root: ET.Element) -> list[Any]:
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
                return [item.get(attr) for item in current if isinstance(item, ET.Element) and item.get(attr) == expected]
            return [item.get(attr_expr) for item in current if isinstance(item, ET.Element) and item.get(attr_expr) is not None]
        qname = _qname(name)
        candidates: list[ET.Element] = []
        for item in current:
            if not isinstance(item, ET.Element): continue
            if descendant and index == 0:
                candidates.extend([node for node in item.iter() if node.tag == qname])
            else:
                candidates.extend([node for node in list(item) if node.tag == qname])
        for predicate in predicates:
            candidates = [node for node in candidates if _eval(predicate, node, root, {}) is True]
        current = candidates
    return current


def _eval(expr: str, context: ET.Element, root: ET.Element, variables: Mapping[str, str]) -> bool | None:
    expr = _strip_outer(re.sub(r"\s+", " ", expr.strip()))
    if not expr:
        return True
    # AKTIN's XQuery uniqueness assertion for the MDRO value sequence.
    if expr.startswith("empty($") and "index-of(" in expr and "@code|$" in expr and "/@nullFlavor" in expr:
        var = re.match(r"empty\(\$([A-Za-z_][A-Za-z0-9_-]*)", expr)
        if not var or var.group(1) not in variables:
            return None
        nodes = _select(variables[var.group(1)], context, root)
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            if not isinstance(node, ET.Element): continue
            key = ("code", node.get("code")) if node.get("code") is not None else ("nullFlavor", node.get("nullFlavor"))
            if key[1] is None: continue
            if key in seen: return False
            seen.add(key)
        return True
    parts = _split_top(expr, "or")
    if parts:
        results = [_eval(part, context, root, variables) for part in parts]
        if any(result is True for result in results): return True
        if all(result is False for result in results): return False
        return None
    parts = _split_top(expr, "and")
    if parts:
        results = [_eval(part, context, root, variables) for part in parts]
        if any(result is False for result in results): return False
        if all(result is True for result in results): return True
        return None
    if expr.startswith("not(") and expr.endswith(")"):
        result = _eval(expr[4:-1], context, root, variables)
        return None if result is None else not result
    match = re.fullmatch(r"count\((.*)\)\s*(<=|>=|=|<|>)\s*(\d+)", expr)
    if match:
        count = len(_select(match.group(1), context, root)); expected = int(match.group(3)); op = match.group(2)
        return {"<=": count <= expected, ">=": count >= expected, "=": count == expected, "<": count < expected, ">": count > expected}[op]
    match = re.fullmatch(r"@([^=\s]+)\s*=\s*(['\"])(.*?)\2", expr)
    if match:
        return context.get(match.group(1)) == match.group(3)
    if "$" in expr or "index-of(" in expr:
        return None
    return bool(_select(expr, context, root))


def evaluate(test: str, context: ET.Element, root: ET.Element, lets: Mapping[str, str] | None = None) -> bool | None:
    return _eval(test, context, root, lets or {})


def validate_contexts(
    root: ET.Element,
    contexts: list[tuple[ET.Element, list[Mapping[str, Any]], Mapping[str, str]]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []; warnings: list[str] = []
    for element, assertions, lets in contexts:
        for assertion in assertions:
            test = str(assertion.get("test") or "")
            result = evaluate(test, element, root, lets)
            label = str(assertion.get("message") or test)
            source = f"{assertion.get('template_id') or '?'}:{assertion.get('element_id') or assertion.get('path') or '?'}"
            if result is False:
                message = f"ART-DECOR assert failed [{source}]: {label} ({test})"
                if str(assertion.get("role") or "error").casefold() == "error": errors.append(message)
                else: warnings.append(message)
            elif result is None:
                message = f"ART-DECOR assert could not be evaluated [{source}]: {test}"
                if str(assertion.get("role") or "error").casefold() == "error":
                    errors.append(message)
                else:
                    warnings.append(message)
    return errors, warnings


def schematron(cda: Mapping[str, Any]) -> str:
    assertions = list(cda.get("assertions", []))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">',
        f'  <sch:ns prefix="hl7" uri="{HL7}"/>',
        '  <sch:pattern id="art-decor-assertions">',
    ]
    for index, assertion in enumerate(assertions, 1):
        path = str(assertion.get("path") or "hl7:ClinicalDocument")
        tid = str(assertion.get("template_id") or "")
        parts = [part for part in path.split("/") if part]
        context = "/".join(parts)
        # Most assertions are on a template root or descendant. Constrain the
        # root when possible without rewriting the authoritative test itself.
        if tid and parts:
            context = f"{context}[ancestor-or-self::*[hl7:templateId/@root='{tid}']]"
        role = escape(str(assertion.get("role") or "error"), quote=True)
        test = escape(str(assertion.get("test") or ""), quote=True)
        message = escape(str(assertion.get("message") or assertion.get("test") or ""))
        lines.append(f'    <sch:rule id="decor-assert-{index}" context="{escape(context, quote=True)}">')
        for name, value in dict(assertion.get("lets", {})).items():
            lines.append(
                f'      <sch:let name="{escape(str(name), quote=True)}" value="{escape(str(value), quote=True)}"/>'
            )
        lines += [f'      <sch:assert role="{role}" test="{test}">{message}</sch:assert>',
                  '    </sch:rule>']
    lines += ['  </sch:pattern>', '</sch:schema>', '']
    return "\n".join(lines)
