"""Compile ART-DECOR CDA templates into a compact executable target model.

The generated ``cda.json`` is the boundary between ART-DECOR and runtime.
ART-DECOR ids remain provenance; runtime assignments use generated target names.

Template ``SPEC`` relationships identify a specialization prototype. The
published child template remains the executable design; its prototype is used
for specialization diagnostics and reviewed branch evidence, not as another
constraint tree to merge. ``include`` remains a transparent constraint group
and ``contains`` expands a referenced template below the containing XML
element.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import re
import unicodedata
import xml.etree.ElementTree as ET

from ..retrieval.xml import (
    KNOWN_PREFIXES,
    child_text,
    clean,
    local,
    parse_text,
    template_namespace_maps,
)
from ..assertions import schematron
from ..workspace import write_json
from .art_decor import inspect_template_constructs, require_supported_constructs
from .datatypes import (
    POLYMORPHIC_COMPLEX_ROOTS,
    base_datatype,
    classify_datatype,
    datatype_definition,
    datatype_inventory,
    expand_datatype,
    value_representation,
)
from .extensions import CdaExtension, normalize_extensions
from .terminology import NULL_FLAVOR_CODE_SYSTEM
from .core import (
    DefinitionIndex,
    element_definition,
    index_definitions,
    resolve_definition,
)
from .model import (
    CdaValueTarget,
    Provenance,
    ValueRepresentation,
    ValueRepresentationKind,
)

TemplateKey = tuple[str, str]
TEMPLATE_PROTOTYPE_RELATIONSHIP = "SPEC"


def _xml_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "1"}


def _typed_value_target(
    name: str,
    path: str,
    representation: ValueRepresentation,
    provenance: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    typed_provenance = tuple(
        Provenance(
            source=str(item.get("source") or "template"),
            template_id=str(item["template_id"]) if item.get("template_id") else None,
            template_effective_date=(
                str(item["template_effective_date"])
                if item.get("template_effective_date") else None
            ),
            element_id=str(item["element_id"]) if item.get("element_id") else None,
            datatype=str(item["datatype"]) if item.get("datatype") else None,
            datatype_part=(
                str(item["datatype_part"]) if item.get("datatype_part") else None
            ),
        )
        for item in provenance
    )
    serial = CdaValueTarget(
        name=name,
        path=path,
        logical_types=representation.logical_types,
        representation=representation,
        provenance=typed_provenance,
    ).to_dict()
    serial.pop("name", None)
    return serial


def _node_value_representation(
    node: Mapping[str, Any],
) -> ValueRepresentation | None:
    """Return the scalar XML slot compiled for one effective CDA node.

    Most scalar encodings are defined by the V3 datatype representation
    policy.  XSD ``mixed`` is itself a machine-readable representation rule:
    it permits a plain character string at the element root even when the
    datatype also exposes structured child parts (for example EN or AD).
    """
    representation = value_representation(
        node.get("representation_datatype") or node.get("datatype")
    )
    allowed_attributes = node.get("representation_attributes")
    if (
        representation is not None
        and isinstance(allowed_attributes, list)
        and representation.attributes
    ):
        allowed = {str(name) for name in allowed_attributes}
        representation = replace(
            representation,
            attributes=tuple(
                name for name in representation.attributes if name in allowed
            ),
        )
    if representation is not None:
        return representation
    # ART-DECOR permits coded constraints to carry the formal vocabulary
    # without repeating the CDA datatype on the element.  The vocabulary is
    # still machine-readable evidence for the CD XML representation; without
    # it, fixed code/codeSystem members could not be rendered at all.
    if (
        node.get("codes")
        or node.get("value_sets")
        or node.get("value_set_bindings")
    ):
        return value_representation("CD")
    if node.get("mixed_content"):
        return ValueRepresentation(
            ValueRepresentationKind.ELEMENT_TEXT, ("text",)
        )
    return None


def _key(template: ET.Element) -> TemplateKey:
    return template.get("id") or "", template.get("effectiveDate") or ""


def _ascii_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return value or "Target"


def _segment(value: str) -> str:
    value = value.replace("hl7:", "").replace("cda:", "")
    return _ascii_name(value.lstrip("@"))


def _xml_key(value: str) -> str:
    """Namespace-prefix-insensitive ART-DECOR design name."""
    if value.startswith("@"):
        return "@" + value[1:].split(":", 1)[-1]
    head, sep, tail = value.partition("[")
    return head.split(":", 1)[-1] + (sep + tail if sep else "")


def _particle_key(value: str) -> str:
    """Return the CDA/XSD particle name behind an ART-DECOR selector.

    ART-DECOR may repeat one XML particle with predicates that select different
    semantic branches.  Those predicates remain part of the compiled template
    identity, but they do not change the particle's CDA/RIM datatype.
    """
    return _xml_key(value).partition("[")[0]


def _template_namespaces(template: ET.Element) -> dict[str, str]:
    raw = template.get("_decor2hl7_namespaces") or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = {}
    return {
        str(prefix): str(uri)
        for prefix, uri in value.items()
        if isinstance(prefix, str) and isinstance(uri, str)
    } if isinstance(value, Mapping) else {}


def _namespace_identity(
    design_name: str, template: ET.Element,
) -> tuple[str | None, str | None]:
    lexical = design_name.lstrip("@").split("[", 1)[0]
    prefix, separator, _ = lexical.partition(":")
    if not separator:
        return None, None
    uri = _template_namespaces(template).get(prefix) or KNOWN_PREFIXES.get(prefix)
    if not uri:
        raise ValueError(
            f"ART-DECOR design name {design_name!r} uses undeclared namespace "
            f"prefix {prefix!r} in template {template.get('id') or '<unknown>'}"
        )
    return prefix, uri


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _maximum(value: str | None) -> int | None | str:
    if value == "*":
        return "*"
    return _int(value)


def _source_key(source: Mapping[str, Any]) -> str:
    template = str(source.get("template_id") or "")
    effective = str(source.get("template_effective_date") or "")
    element_id = source.get("element_id")
    if element_id:
        # ART-DECOR element ids are not necessarily unique inside a template.
        # Expanded includes in particular can reuse the same id for distinct
        # sibling constraints.  The path is therefore part of physical source
        # identity; the id-only form remains available as a deliberately
        # tolerant semantic lookup below.
        return (
            f"{template}@{effective}|ID:{element_id}"
            f"|PATH:{source.get('path') or ''}"
        )
    return f"{template}@{effective}|PATH:{source.get('path') or ''}"


def _revisionless_source_key(source: Mapping[str, Any]) -> str:
    template = str(source.get("template_id") or "")
    element_id = source.get("element_id")
    if element_id:
        return f"{template}|ID:{element_id}|PATH:{source.get('path') or ''}"
    return f"{template}|PATH:{source.get('path') or ''}"


def _tolerant_source_key(source: Mapping[str, Any]) -> str:
    element_id = source.get("element_id")
    if not element_id:
        return ""
    return f"{source.get('template_id') or ''}|ID:{element_id}"


def collect_templates(
    xml_paths: Iterable[Path],
    fallback_paths: Iterable[Path] = (),
    cutoff: str | None = None,
) -> dict[str, list[ET.Element]]:
    """Collect fetched template definitions; live evidence is never build input."""
    fallback_paths = list(fallback_paths)
    if fallback_paths:
        raise ValueError(
            "fallback template inputs are not allowed; fetch exact build artifacts"
        )
    templates: dict[str, list[ET.Element]] = defaultdict(list)
    seen: set[TemplateKey] = set()

    def ingest(paths: Iterable[Path]) -> None:
        for path in sorted(set(paths)):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                root, _ = parse_text(text)
                namespace_maps = template_namespace_maps(text)
            except ET.ParseError:
                continue
            for node in root.iter():
                if local(node.tag) != "template" or not node.get("id"):
                    continue
                if not (node.get("name") or node.get("displayName") or node.get("effectiveDate")):
                    continue
                effective = node.get("effectiveDate") or ""
                key = _key(node)
                if key in seen:
                    continue
                node.set(
                    "_decor2hl7_namespaces",
                    json.dumps(namespace_maps.get(key, {}), sort_keys=True),
                )
                seen.add(key)
                templates[key[0]].append(node)

    ingest(xml_paths)
    for rows in templates.values():
        rows.sort(key=lambda node: node.get("effectiveDate") or "")
    return templates


_NON_EXECUTABLE_TEMPLATE_STATUSES = {"cancelled", "rejected", "retired"}


def _is_executable_template_revision(template: ET.Element) -> bool:
    """Apply the ART-DECOR template lifecycle before resolving references.

    The owner's lifecycle defines cancelled and rejected revisions as never
    published/withdrawn and retired revisions as historical-only. Draft,
    pending, review, and active revisions remain executable design material.
    """
    return str(template.get("statusCode") or "").casefold() not in (
        _NON_EXECUTABLE_TEMPLATE_STATUSES
    )


def select_template_revision(
    templates: dict[str, list[ET.Element]], template_id: str, flexibility: str | None = None
) -> ET.Element | None:
    rows = [
        row for row in templates.get(template_id, [])
        if _is_executable_template_revision(row)
    ]
    if not rows:
        return None
    if flexibility and flexibility != "dynamic":
        exact = [row for row in rows if (row.get("effectiveDate") or "") == flexibility]
        return exact[-1] if exact else None
    return rows[-1]


# Compatibility name for callers outside the CDA compiler. The implementation
# name mirrors the ART-DECOR operation and makes its place in the rule pipeline
# explicit.
select_template = select_template_revision


def _template_relations(template: ET.Element, kinds: set[str] | None = None) -> Iterable[ET.Element]:
    for node in list(template):
        if local(node.tag) != "relationship" or not node.get("template"):
            continue
        if kinds is None or (node.get("type") or "") in kinds:
            yield node


def reachable_templates(
    templates: dict[str, list[ET.Element]],
    start_id: str,
    start_flexibility: str | None = None,
) -> tuple[dict[TemplateKey, ET.Element], list[dict[str, str]]]:
    start = select_template(templates, start_id, start_flexibility)
    if start is None:
        raise ValueError(f"CDA document template {start_id} was not fetched")
    found: dict[TemplateKey, ET.Element] = {}
    missing: dict[tuple[str, str, str], dict[str, str]] = {}
    queue: deque[ET.Element] = deque([start])
    while queue:
        template = queue.popleft()
        key = _key(template)
        if key in found:
            continue
        found[key] = template
        for node in template.iter():
            relation = ""
            reference = ""
            if local(node.tag) == "include" and node.get("ref"):
                relation, reference = "include", node.get("ref") or ""
            elif local(node.tag) == "element" and node.get("contains"):
                relation = (
                    "reviewed-extension"
                    if node.get("_decor2hl7_source") == "reviewed-extension"
                    else "contains"
                )
                reference = node.get("contains") or ""
            if not reference:
                continue
            flexibility = node.get("flexibility") or ""
            target = select_template(templates, reference, flexibility)
            if target is None:
                missing[(relation, reference, flexibility)] = {
                    "relation": relation,
                    "template": reference,
                    "flexibility": flexibility,
                }
            else:
                queue.append(target)
    return found, list(missing.values())


def _unresolved_template_prototypes(
    reachable: Mapping[TemplateKey, ET.Element],
    templates: dict[str, list[ET.Element]],
) -> list[dict[str, Any]]:
    """Report absent first-SPEC editor prototypes without degrading closure."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for template in reachable.values():
        relation = next(iter(_template_relations(
            template, {TEMPLATE_PROTOTYPE_RELATIONSHIP}
        )), None)
        if relation is None:
            continue
        reference = relation.get("template") or ""
        flexibility = relation.get("flexibility") or ""
        if select_template(templates, reference, flexibility) is not None:
            continue
        identity = (reference, flexibility, _key(template)[0])
        if identity in seen:
            continue
        seen.add(identity)
        result.append({
            "relation": TEMPLATE_PROTOTYPE_RELATIONSHIP,
            "template": reference,
            "flexibility": flexibility,
            "used_by": {
                "template": _key(template)[0],
                "effective_date": _key(template)[1],
            },
            "required": False,
            "purpose": "editor-prototype",
        })
    return result


def _value_set_binding(
    node: ET.Element, strength: str | None = None,
) -> dict[str, str] | None:
    value_set = node.get("valueSet") or ""
    if not value_set:
        return None
    binding: dict[str, str] = {
        "id": value_set,
        "effective_date": node.get("vseffectiveDate") or node.get("effectiveDate") or "",
        "flexibility": node.get("flexibility") or "",
    }
    if strength is not None:
        binding["strength"] = {
            "cne": "required", "cwe": "extensible",
        }.get(str(strength).casefold(), str(strength).casefold())
    display_name = clean(node.get("vsdisplayName") or "")
    name = clean(node.get("vsname") or "")
    if display_name:
        binding["display_name"] = display_name
    if name:
        binding["name"] = name
    return binding


def _attribute_fixed_value(attribute: ET.Element) -> str | None:
    """Return an explicit or single-code ART-DECOR attribute constraint."""
    if attribute.get("value") is not None:
        return attribute.get("value")
    codes = {
        str(node.get("code")) for node in list(attribute)
        if local(node.tag) == "vocabulary" and node.get("code") is not None
    }
    return next(iter(codes)) if len(codes) == 1 else None


def _constraints(
    element: ET.Element,
) -> tuple[
    list[str], list[dict[str, str]], list[tuple[str, str, str]], dict[str, str], str | None,
]:
    value_sets: list[str] = []
    value_set_bindings: list[dict[str, str]] = []
    codes: list[tuple[str, str, str]] = []
    fixed: dict[str, str] = {}
    unit: str | None = None
    for node in list(element):
        kind = local(node.tag)
        if kind == "vocabulary":
            binding = _value_set_binding(node, element.get("strength"))
            if binding is not None:
                value_sets.append(binding["id"])
                if binding not in value_set_bindings:
                    value_set_bindings.append(binding)
            if node.get("code"):
                # CS constraints commonly state only the vocabulary code; the
                # code system is implicit in the CDA attribute's domain.  A
                # single such code is still an executable fixed value.
                codes.append((
                    node.get("code") or "",
                    node.get("codeSystem") or "",
                    clean(node.get("displayName") or ""),
                ))
        elif kind == "attribute" and node.get("name") and node.get("value"):
            fixed[node.get("name") or ""] = node.get("value") or ""
        elif kind == "property" and node.get("unit"):
            unit = node.get("unit")
    if fixed.get("code"):
        codes.append((fixed["code"], fixed.get("codeSystem", ""), ""))
    return (
        list(dict.fromkeys(value_sets)), value_set_bindings,
        list(dict.fromkeys(codes)), fixed, unit,
    )


def _property_constraints(element: ET.Element) -> list[dict[str, Any]]:
    """Preserve ART-DECOR property alternatives with owner terminology."""
    properties: list[dict[str, Any]] = []
    for child in list(element):
        if local(child.tag) != "property":
            continue
        rule: dict[str, Any] = {}
        for source, target in (
            ("unit", "unit"), ("currency", "currency"),
            ("value", "value"), ("fractionDigits", "fraction_digits"),
        ):
            if child.get(source) is not None:
                rule[target] = child.get(source)
        for source, target in (
            ("minInclude", "min_include"),
            ("maxInclude", "max_include"),
        ):
            raw = child.get(source)
            if raw is None:
                continue
            try:
                numeric = float(raw)
                rule[target] = int(numeric) if numeric.is_integer() else numeric
            except ValueError:
                rule[target] = raw
        for source, target in (
            ("minLength", "min_length"), ("maxLength", "max_length"),
        ):
            if child.get(source) is not None:
                rule[target] = _int(child.get(source))
        if rule:
            properties.append(rule)
    return properties


def _fixed_text(element: ET.Element) -> str | None:
    """Return an ART-DECOR fixed element text constraint, if present."""
    for node in list(element):
        if local(node.tag) != "text":
            continue
        value = "".join(node.itertext()).strip()
        if value:
            return value
    return None


def _description(element: ET.Element) -> str | None:
    for node in list(element):
        if local(node.tag) == "desc":
            value = clean(" ".join("".join(node.itertext()).split()))
            if value:
                return value
    return None


def _raw_targets(reachable: dict[TemplateKey, ET.Element]) -> list[dict[str, Any]]:
    """All addressable constraints used for evidence and provenance.

    Elements without ART-DECOR element ids are intentionally retained.  Their
    template-local path is a perfectly usable generated address.
    """
    rows: list[dict[str, Any]] = []
    for tkey, template in reachable.items():
        template_name = _ascii_name(
            template.get("name") or template.get("displayName") or tkey[0].split(".")[-1]
        )
        display = clean(template.get("displayName") or child_text(template, "name") or template_name)
        template_description = _description(template)

        # A template-level attribute constrains the element selected by the
        # template context. Keep it in the evidence registry even though its
        # XML owner is supplied by the including/containing template.
        for direct in list(template):
            if local(direct.tag) != "attribute" or not direct.get("name"):
                continue
            name = direct.get("name") or "attribute"
            namespace_prefix, namespace_uri = _namespace_identity(
                "@" + name, template
            )
            value = _attribute_fixed_value(direct)
            rows.append({
                "template_id": tkey[0],
                "template_effective_date": tkey[1],
                "template_name": template_name,
                "template_display_name": display,
                "template_description": template_description,
                "kind": "attribute",
                "element_id": direct.get("id"),
                "element_name": "@" + name,
                "namespace_prefix": namespace_prefix,
                "namespace_uri": namespace_uri,
                "path": "@" + name,
                "datatype": direct.get("datatype"),
                "value_sets": [
                    node.get("valueSet") or "" for node in list(direct)
                    if local(node.tag) == "vocabulary" and node.get("valueSet")
                ],
                "value_set_bindings": [
                    binding for node in list(direct)
                    if local(node.tag) == "vocabulary"
                    for binding in [_value_set_binding(node)]
                    if binding is not None
                ],
                "codes": [],
                "fixed": {"value": value} if value is not None else {},
                "fixed_text": None,
                "description": None,
                "conformance": None,
                "prohibited": False,
                "unit": None,
                "renderable": False,
                "context": _template_context(template),
            })

        def walk(parent: ET.Element, path: tuple[str, ...] = ()) -> None:
            for child in list(parent):
                kind = local(child.tag)
                current = path
                if kind == "element":
                    name = child.get("name") or "element"
                    namespace_prefix, namespace_uri = _namespace_identity(
                        name, template
                    )
                    current = path + (name,)
                    value_sets, value_set_bindings, codes, fixed, unit = _constraints(child)
                    rows.append({
                        "template_id": tkey[0],
                        "template_effective_date": tkey[1],
                        "template_name": template_name,
                        "template_display_name": display,
                        "template_description": template_description,
                        "kind": "element",
                        "element_id": child.get("id"),
                        "element_name": name,
                        "namespace_prefix": namespace_prefix,
                        "namespace_uri": namespace_uri,
                        "path": "/".join(current),
                        "datatype": child.get("datatype"),
                        "value_sets": value_sets,
                        "value_set_bindings": value_set_bindings,
                        "codes": [
                            {
                                "code": code,
                                "code_system": code_system,
                                **({"display_name": display_name} if display_name else {}),
                            }
                            for code, code_system, display_name in codes
                        ],
                        "fixed": fixed,
                        "fixed_text": _fixed_text(child),
                        "description": _description(child),
                        "conformance": child.get("conformance"),
                        "prohibited": child.get("conformance") == "NP",
                        "unit": unit or fixed.get("unit"),
                        "properties": _property_constraints(child),
                        "binding_strength": {
                            "cne": "required", "cwe": "extensible",
                        }.get(
                            str(child.get("strength") or "required").casefold(),
                            str(child.get("strength") or "required").casefold(),
                        ),
                        "renderable": False,
                    })
                    # Attributes are writable targets too, even where ART-DECOR
                    # did not assign an element id (e.g. some negation flags).
                    for direct in list(child):
                        if local(direct.tag) != "attribute" or not direct.get("name"):
                            continue
                        aname = "@" + (direct.get("name") or "attribute")
                        attribute_prefix, attribute_uri = _namespace_identity(
                            aname, template
                        )
                        attribute_value = _attribute_fixed_value(direct)
                        rows.append({
                            "template_id": tkey[0],
                            "template_effective_date": tkey[1],
                            "template_name": template_name,
                            "template_display_name": display,
                            "template_description": template_description,
                            "kind": "attribute",
                            "element_id": direct.get("id"),
                            "element_name": aname,
                            "namespace_prefix": attribute_prefix,
                            "namespace_uri": attribute_uri,
                            "path": "/".join(current + (aname,)),
                            "datatype": direct.get("datatype"),
                            "value_sets": [
                                v.get("valueSet") or "" for v in list(direct)
                                if local(v.tag) == "vocabulary" and v.get("valueSet")
                            ],
                            "value_set_bindings": [
                                binding for v in list(direct)
                                if local(v.tag) == "vocabulary"
                                for binding in [_value_set_binding(v)]
                                if binding is not None
                            ],
                            "codes": [],
                            "fixed": {"value": attribute_value} if attribute_value is not None else {},
                            "fixed_text": None,
                            "description": None,
                            "conformance": child.get("conformance"),
                            "prohibited": child.get("conformance") == "NP",
                        "unit": None,
                        "properties": _property_constraints(direct),
                        "renderable": False,
                        })
                walk(child, current)

        walk(template)
    return rows


def _name_targets(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    leaf_bases = [f"{row['template_name']}.{_segment(row['element_name'])}" for row in rows]
    leaf_counts = Counter(
        base for row, base in zip(rows, leaf_bases)
        if not row.get("datatype_derived")
    )
    candidates: list[str] = []
    for row, base in zip(rows, leaf_bases):
        if not row.get("datatype_derived") and leaf_counts[base] == 1:
            candidates.append(base)
        else:
            path = ".".join(_segment(part) for part in row["path"].split("/"))
            candidates.append(f"{row['template_name']}.{path}")
    candidate_counts = Counter(candidates)
    targets: dict[str, dict[str, Any]] = {}
    for row, candidate in zip(rows, candidates):
        if candidate_counts[candidate] > 1:
            # Same constraint name in several reachable revisions.  Effective
            # date is more useful to a human than another OID suffix.
            effective = re.sub(r"[^0-9]", "", str(row.get("template_effective_date") or ""))[:8]
            if effective:
                candidate = f"{candidate}@{effective}"
        if candidate in targets:
            element_tail = str(row.get("element_id") or "target").split(".")[-1]
            candidate = f"{candidate}@{element_tail}"
        serial = dict(row)
        serial["source_key"] = _source_key(row)
        serial["locations"] = []
        targets[candidate] = serial
    return targets


def _source(template: ET.Element, path: str, element_id: str | None) -> dict[str, Any]:
    return {
        "template_id": template.get("id") or "",
        "template_effective_date": template.get("effectiveDate") or "",
        "element_id": element_id,
        "path": path,
    }


def _define_variable_lets(variable: ET.Element) -> dict[str, str]:
    """Expand ART-DECOR ``defineVariable`` as the owner Schematron does."""
    name = str(variable.get("name") or "")
    if not name:
        return {}
    path = str(variable.get("path") or "")
    code = next(
        (child for child in list(variable) if local(child.tag) == "code"),
        None,
    )
    use = next(
        (child for child in list(variable) if local(child.tag) == "use"),
        None,
    )
    selector = ""
    if code is not None and (code.get("code") or code.get("codeSystem")):
        selector = "[hl7:code"
        if code.get("code"):
            selector += f"[@code='{code.get('code')}']"
        if code.get("codeSystem"):
            selector += f"[@codeSystem='{code.get('codeSystem')}']"
        selector += "]"
    use_path = str(use.get("path") or "") if use is not None else ""
    raw_name = f"temp1_{name}"
    lets = {raw_name: f"{path}{selector}/{use_path}"}
    datatype = str(use.get("as") or "") if use is not None else ""
    if datatype == "INT":
        lets[name] = (
            f"if (${raw_name} castable as xs:integer) then "
            f"(${raw_name} cast as xs:integer) else false"
        )
    elif datatype == "CE":
        lets[name] = f"${raw_name}"
    elif datatype == "TS.JULIAN":
        date_name = f"temp2_{name}"
        typed_name = f"temp3_{name}"
        lets[date_name] = (
            f"concat(substring(${raw_name}, 1, 4), '-', "
            f"substring(${raw_name}, 5, 2), '-', substring(${raw_name}, 7, 2))"
        )
        lets[typed_name] = (
            f"if (${date_name} castable as xs:date) then "
            f"(${date_name} cast as xs:date) else false"
        )
        lets[name] = (
            f"days-from-duration(${typed_name} - xs:date('1858-11-17'))"
        )
    elif datatype == "TS":
        lets[name] = f"${raw_name}"
    else:
        lets[name] = "false"
    return lets


def _local_rule_content(
    parent: ET.Element,
    template: ET.Element,
    path: str,
    element_id: str | None,
) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile owner-defined validation and free-form rules in source order."""
    lets: dict[str, str] = {}
    rules: list[dict[str, Any]] = []
    definitions: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    for child in list(parent):
        kind = local(child.tag)
        if kind == "let" and child.get("name") and child.get("value"):
            lets[str(child.get("name"))] = str(child.get("value"))
        elif kind == "defineVariable" and child.get("name"):
            expanded = _define_variable_lets(child)
            lets.update(expanded)
            definitions.append({
                "name": str(child.get("name") or ""),
                "path": str(child.get("path") or ""),
                "expanded_lets": expanded,
                "code": next((
                    dict(item.attrib) for item in list(child)
                    if local(item.tag) == "code"
                ), None),
                "use": next((
                    dict(item.attrib) for item in list(child)
                    if local(item.tag) == "use"
                ), None),
            })
        elif kind in {"assert", "report"} and child.get("test"):
            rules.append({
                "kind": kind,
                "test": child.get("test") or "",
                "role": child.get("role") or "error",
                "message": clean("".join(child.itertext())),
                **({"flag": child.get("flag")} if child.get("flag") else {}),
                **({"see": child.get("see")} if child.get("see") else {}),
                "template_id": template.get("id") or "",
                "template_effective_date": template.get("effectiveDate") or "",
                "element_id": element_id or "",
                "path": path,
                "namespaces": _template_namespaces(template),
            })
        elif kind == "constraint":
            text = clean("".join(child.itertext()))
            constraints.append({
                "kind": "constraint",
                "language": (
                    child.get("{http://www.w3.org/XML/1998/namespace}lang")
                    or child.get("language") or ""
                ),
                "text": text,
                "normative_terms": sorted(set(
                    term for term in ("SHALL NOT", "MUST NOT", "SHALL", "MUST", "SHOULD", "MAY")
                    if term in text.upper()
                )),
                "machine_test": None,
                "template_id": template.get("id") or "",
                "template_effective_date": template.get("effectiveDate") or "",
                "element_id": element_id or "",
                "path": path,
            })
    return lets, rules, definitions, constraints


def _parse_attribute(attribute: ET.Element, template: ET.Element, path: str) -> dict[str, Any]:
    name = attribute.get("name") or "attribute"
    namespace_prefix, namespace_uri = _namespace_identity(name, template)
    bindings = [
        binding for node in list(attribute)
        if local(node.tag) == "vocabulary"
        for binding in [_value_set_binding(node, attribute.get("strength"))]
        if binding is not None
    ]
    valuesets = list(dict.fromkeys(binding["id"] for binding in bindings))
    _, _, _, textual_constraints = _local_rule_content(
        attribute, template, path, attribute.get("id")
    )
    return {
        "kind": "attribute",
        "name": name,
        "namespace_prefix": namespace_prefix,
        "namespace_uri": namespace_uri,
        "id": attribute.get("id"),
        "datatype": attribute.get("datatype"),
        "value": _attribute_fixed_value(attribute),
        "optional": (
            attribute.get("isOptional") == "true"
            if attribute.get("isOptional") is not None else None
        ),
        "value_sets": valuesets,
        "value_set_bindings": bindings,
        "properties": _property_constraints(attribute),
        "textual_constraints": textual_constraints,
        "sources": [_source(template, path, attribute.get("id"))],
        "provenance": [{
            "source": "template",
            **_source(template, path, attribute.get("id")),
        }],
        "targets": [],
    }


def _parse_element(
    element: ET.Element,
    template: ET.Element,
    path: tuple[str, ...],
    inherited_closed: bool = False,
) -> dict[str, Any]:
    name = element.get("name") or "hl7:element"
    xsi_type_match = re.search(
        r"\[@xsi:type\s*=\s*(['\"])([^'\"]+)\1\]", name
    )
    namespace_prefix, namespace_uri = _namespace_identity(name, template)
    current = path + (name,)
    current_path = "/".join(current)
    is_closed = inherited_closed or _xml_true(element.get("isClosed"))
    source_kind = element.get("_decor2hl7_source") or "template"
    value_sets, value_set_bindings, codes, fixed, unit = _constraints(element)
    children: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    lets, validation_rules, variable_definitions, textual_constraints = (
        _local_rule_content(element, template, current_path, element.get("id"))
    )
    for child in list(element):
        kind = local(child.tag)
        if kind == "attribute" and child.get("name"):
            attributes.append(_parse_attribute(child, template, current_path + "/@" + (child.get("name") or "attribute")))
        elif kind == "element":
            children.append(_parse_element(child, template, current, is_closed))
        elif kind == "choice":
            children.append(_parse_choice(
                child, template, current, is_closed
            ))
        elif kind == "include" and child.get("ref"):
            children.append(_parse_include(
                child, template, current, is_closed
            ))
    return {
        "kind": "element",
        "name": name,
        "namespace_prefix": namespace_prefix,
        "namespace_uri": namespace_uri,
        "template_name": _ascii_name(
            template.get("name") or template.get("displayName")
            or (template.get("id") or "").split(".")[-1]
        ),
        "template_display_name": clean(
            template.get("displayName") or child_text(template, "name")
            or template.get("name") or ""
        ),
        "template_description": _description(template),
        "id": element.get("id"),
        "datatype": element.get("datatype"),
        **(
            {"xsi_type": xsi_type_match.group(2)}
            if xsi_type_match else {}
        ),
        "min": _int(element.get("minimumMultiplicity")),
        "max": _maximum(element.get("maximumMultiplicity")),
        "mandatory": (
            _xml_true(element.get("isMandatory"))
            if element.get("isMandatory") is not None else None
        ),
        "conformance": element.get("conformance"),
        "conditional": str(element.get("conformance") or "").upper() == "C",
        "is_closed": is_closed,
        "reviewed_extension": source_kind == "reviewed-extension",
        "reviewed_spec_branch": source_kind == "reviewed-spec-branch",
        "fixed": fixed,
        "fixed_text": _fixed_text(element),
        "description": _description(element),
        "value_sets": value_sets,
        "value_set_bindings": value_set_bindings,
        "codes": [
            {
                "code": code,
                "code_system": code_system,
                **({"display_name": display_name} if display_name else {}),
            }
            for code, code_system, display_name in codes
        ],
        "unit": unit or fixed.get("unit"),
        "properties": _property_constraints(element),
        "binding_strength": {
            "cne": "required", "cwe": "extensible",
        }.get(
            str(element.get("strength") or "required").casefold(),
            str(element.get("strength") or "required").casefold(),
        ),
        "attributes": attributes,
        "children": children,
        "contains": element.get("contains"),
        "contains_flexibility": element.get("flexibility"),
        "origin": _source(template, current_path, element.get("id")),
        "sources": [_source(template, current_path, element.get("id"))],
        "provenance": [{
            "source": source_kind,
            **_source(template, current_path, element.get("id")),
            **(
                {"reason": element.get("_decor2hl7_reason") or ""}
                if source_kind in {"reviewed-extension", "reviewed-spec-branch"}
                else {}
            ),
        }],
        "targets": [],
        "validation_rules": validation_rules,
        # Compatibility for existing cda.json consumers; canonical code uses
        # validation_rules because both assert and report are executable.
        "asserts": validation_rules,
        "lets": lets,
        "variable_definitions": variable_definitions,
        "textual_constraints": textual_constraints,
    }


def _parse_include(
    include: ET.Element,
    template: ET.Element,
    path: tuple[str, ...],
    inherited_closed: bool = False,
) -> dict[str, Any]:
    current_path = "/".join(path)
    lets, validation_rules, variable_definitions, textual_constraints = (
        _local_rule_content(include, template, current_path, include.get("id"))
    )
    return {
        "kind": "include",
        "ref": include.get("ref") or "",
        "flexibility": include.get("flexibility"),
        "min": _int(include.get("minimumMultiplicity")),
        "max": _maximum(include.get("maximumMultiplicity")),
        "mandatory": (
            _xml_true(include.get("isMandatory"))
            if include.get("isMandatory") is not None else None
        ),
        "conformance": include.get("conformance"),
        "conditional": str(include.get("conformance") or "").upper() == "C",
        # An include without its own multiplicity is an inline constraint
        # group. Its contained XML particles retain their own cardinalities;
        # the transparent wrapper must not suppress them at runtime.
        "transparent_inline": include.get("minimumMultiplicity") is None,
        "is_closed": inherited_closed or _xml_true(include.get("isClosed")),
        "children": [],
        "validation_rules": validation_rules,
        "asserts": validation_rules,
        "lets": lets,
        "variable_definitions": variable_definitions,
        "textual_constraints": textual_constraints,
    }


def _parse_choice(
    choice: ET.Element,
    template: ET.Element,
    path: tuple[str, ...],
    inherited_closed: bool = False,
) -> dict[str, Any]:
    """Retain an ART-DECOR choice as one bounded transparent particle."""
    children: list[dict[str, Any]] = []
    for branch in list(choice):
        kind = local(branch.tag)
        if kind == "element":
            children.append(_parse_element(
                branch, template, path, inherited_closed
            ))
        elif kind == "include" and branch.get("ref"):
            children.append(_parse_include(
                branch, template, path, inherited_closed
            ))
        elif kind == "choice":
            children.append(_parse_choice(
                branch, template, path, inherited_closed
            ))
    current_path = "/".join(path)
    source = _source(template, current_path, None)
    lets, validation_rules, variable_definitions, textual_constraints = (
        _local_rule_content(choice, template, current_path, None)
    )
    return {
        "kind": "choice",
        "min": _int(choice.get("minimumMultiplicity")),
        "max": _maximum(choice.get("maximumMultiplicity")),
        "mandatory": (
            _xml_true(choice.get("isMandatory"))
            if choice.get("isMandatory") is not None else None
        ),
        "conformance": choice.get("conformance"),
        "conditional": str(choice.get("conformance") or "").upper() == "C",
        "transparent_inline": False,
        "is_closed": inherited_closed or _xml_true(choice.get("isClosed")),
        "children": children,
        "origin": source,
        "sources": [source],
        "provenance": [{"source": "template-choice", **source}],
        "targets": [],
        "validation_rules": validation_rules,
        "asserts": validation_rules,
        "lets": lets,
        "variable_definitions": variable_definitions,
        "textual_constraints": textual_constraints,
    }


def _template_context(template: ET.Element) -> dict[str, str] | None:
    context = next(
        (node for node in list(template) if local(node.tag) == "context"),
        None,
    )
    if context is None:
        return None
    return {
        key: str(context.get(key) or "")
        for key in ("id", "path") if context.get(key) is not None
    }


def _template_context_attributes(template: ET.Element) -> list[dict[str, Any]]:
    """Compile attributes whose owner is selected by the template context."""
    return [
        _parse_attribute(
            child, template, "@" + str(child.get("name") or "attribute")
        )
        for child in list(template)
        if local(child.tag) == "attribute" and child.get("name")
    ]


def _direct_template_rules(template: ET.Element) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    template_closed = _xml_true(template.get("isClosed"))
    for child in list(template):
        kind = local(child.tag)
        if kind == "element":
            result.append(_parse_element(child, template, (), template_closed))
        elif kind == "choice":
            result.append(_parse_choice(child, template, (), template_closed))
        elif kind == "include" and child.get("ref"):
            result.append(_parse_include(child, template, (), template_closed))
    return result


def _direct_template(template: ET.Element) -> list[dict[str, Any]]:
    """Compatibility wrapper for tests and extension validation."""
    return _direct_template_rules(template)


def _merge_context_attribute(
    owner: dict[str, Any], attribute: Mapping[str, Any],
) -> None:
    """Apply one template-context attribute to its concrete XML owner."""
    key = _xml_key(str(attribute.get("name") or ""))
    existing = next(
        (
            item for item in owner.get("attributes", [])
            if _xml_key(str(item.get("name") or "")) == key
        ),
        None,
    )
    if existing is None:
        owner.setdefault("attributes", []).append(deepcopy(dict(attribute)))
        return
    old_value = existing.get("value")
    new_value = attribute.get("value")
    if old_value is not None and new_value is not None and old_value != new_value:
        raise ValueError(
            "conflicting ART-DECOR context attributes @"
            f"{attribute.get('name')}: {old_value!r} != {new_value!r}"
        )
    for name in ("datatype", "value", "optional"):
        if existing.get(name) is None and attribute.get(name) is not None:
            existing[name] = deepcopy(attribute.get(name))
    existing["value_sets"] = list(dict.fromkeys(
        list(existing.get("value_sets", []))
        + list(attribute.get("value_sets", []))
    ))
    existing["value_set_bindings"] = list(existing.get(
        "value_set_bindings", []
    )) + [
        deepcopy(item) for item in attribute.get("value_set_bindings", [])
        if item not in existing.get("value_set_bindings", [])
    ]
    existing["sources"] = _unique_sources(
        list(existing.get("sources", [])) + list(attribute.get("sources", []))
    )
    existing.setdefault("provenance", []).extend(
        deepcopy(list(attribute.get("provenance", [])))
    )


def _apply_document_template_context(
    document: list[dict[str, Any]], template: ET.Element,
) -> None:
    """Apply rules located at the representing template's own context."""
    attributes = _template_context_attributes(template)
    roots = list(_transparent_element_children(document))
    root_path = str(
        (roots[0].get("origin") or {}).get("path")
        if roots else ""
    )
    lets, rules, definitions, constraints = _local_rule_content(
        template, template, root_path, None
    )
    if not any((attributes, lets, rules, definitions, constraints)):
        return
    if len(roots) != 1:
        raise ValueError(
            "document template context rules require exactly one root "
            f"element; found {len(roots)}"
        )
    for attribute in attributes:
        _merge_context_attribute(roots[0], attribute)
    roots[0].setdefault("lets", {}).update(lets)
    roots[0].setdefault("validation_rules", []).extend(rules)
    roots[0]["asserts"] = roots[0]["validation_rules"]
    roots[0].setdefault("variable_definitions", []).extend(definitions)
    roots[0].setdefault("textual_constraints", []).extend(constraints)


def _unique_sources(sources: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source in sources:
        key = (
            str(source.get("template_id") or ""),
            str(source.get("template_effective_date") or ""),
            str(source.get("element_id") or ""),
            str(source.get("path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(source))
    return out


def _sequence_key(node: Mapping[str, Any]) -> tuple[str, str]:
    if node.get("kind") == "element":
        key = _xml_key(str(node.get("name") or ""))
        # Repeated CDA wrappers (component, entry, entryRelationship, ...) are
        # semantically distinguished by the template they contain.  Matching
        # only by sibling position causes constraints from the wrong section or
        # entry to leak across template versions.
        if node.get("contains"):
            key += "|contains:" + str(node.get("contains"))
        return "element", key
    return "include", str(node.get("ref") or "")


def _constraint_limit(value: Any) -> float | None:
    if value == "*":
        return float("inf")
    if isinstance(value, int):
        return float(value)
    return None


def _spec_constraint_diagnostics(
    parent: Mapping[str, Any],
    child: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Describe explicit child occurrence constraints that broaden a SPEC parent."""
    changes: list[dict[str, Any]] = []
    parent_min = parent.get("min")
    child_min = child.get("min")
    if (
        isinstance(parent_min, int)
        and isinstance(child_min, int)
        and child_min < parent_min
    ):
        changes.append({
            "property": "minimumMultiplicity",
            "parent": parent_min,
            "child": child_min,
        })

    parent_max = _constraint_limit(parent.get("max"))
    child_max = _constraint_limit(child.get("max"))
    if (
        parent_max is not None
        and child_max is not None
        and child_max > parent_max
    ):
        changes.append({
            "property": "maximumMultiplicity",
            "parent": parent.get("max"),
            "child": child.get("max"),
        })

    if bool(parent.get("mandatory")) and not bool(effective.get("mandatory")):
        changes.append({
            "property": "mandatory",
            "parent": True,
            "child": False,
        })
    if not changes:
        return []

    parent_origin = dict(parent.get("origin", {}))
    child_origin = dict(child.get("origin", {}))
    parent_identity = str(parent_origin.get("template_id") or "parent template")
    child_identity = str(child_origin.get("template_id") or "specialized template")
    path = str(
        child_origin.get("path")
        or child.get("name")
        or (
            f"include:{child.get('ref')}"
            if child.get("kind") == "include" else None
        )
        or "template item"
    )
    summary = ", ".join(
        f"{change['property']} {change['parent']} -> {change['child']}"
        for change in changes
    )
    return [{
        "code": "spec-constraint-weakening",
        "severity": "warning",
        "policy": "explicit-child-constraint-authoritative",
        "message": (
            f"{child_identity} weakens SPEC parent {parent_identity} at {path} "
            f"({summary}); using the explicit child constraint"
        ),
        "path": path,
        "parent": parent_origin,
        "child": child_origin,
        "changes": changes,
    }]


def _unique_constraint_diagnostics(
    diagnostics: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for diagnostic in diagnostics:
        serial = dict(diagnostic)
        key = json.dumps(serial, sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(serial)
    return result


def _extract_constraint_diagnostics(
    nodes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for node in nodes:
        diagnostics.extend(node.pop("_constraint_diagnostics", []))
        diagnostics.extend(_extract_constraint_diagnostics(node.get("children", [])))
    return _unique_constraint_diagnostics(diagnostics)


def _owner_rule_diagnostics(
    nodes: Iterable[Mapping[str, Any]],
    inherited_rules: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Expose free-form and conditional rules that cannot be inferred safely.

    ART-DECOR defines ``constraint`` as free-form markup, whereas executable
    conditions are expressed with Schematron ``assert``/``report``.  The
    compiler therefore preserves prose but never translates English into an
    invented XPath expression.
    """
    diagnostics: list[dict[str, Any]] = []
    parent_rules = list(inherited_rules)
    for node in nodes:
        rules = list(node.get("validation_rules", node.get("asserts", [])))
        textual = list(node.get("textual_constraints", []))
        for constraint in textual:
            normative = list(constraint.get("normative_terms", []))
            diagnostics.append({
                "code": "textual-constraint-not-executable",
                "severity": (
                    "warning"
                    if any(term.startswith(("SHALL", "MUST")) for term in normative)
                    else "info"
                ),
                "policy": "preserve-owner-free-form-markup",
                "message": (
                    "ART-DECOR <constraint> is free-form markup and has no "
                    "machine test; it is preserved without inferring XPath: "
                    + str(constraint.get("text") or "")
                ),
                "path": str(constraint.get("path") or ""),
                "source": dict(constraint),
            })

        if str(node.get("conformance") or "").upper() == "C":
            name = str(node.get("name") or "")
            local_name = name.split("[", 1)[0].split(":", 1)[-1]
            related_rules = [
                rule for rule in parent_rules + rules
                if local_name and local_name in str(rule.get("test") or "")
            ]
            evidence: list[str] = []
            if "[" in name:
                evidence.append("element-name-predicate")
            if textual:
                evidence.append("textual-constraint")
            if related_rules:
                evidence.append("schematron-rule")
            source = dict(node.get("origin") or {})
            if not evidence:
                diagnostics.append({
                    "code": "conditional-conformance-condition-missing",
                    "severity": "error",
                    "policy": "owner-conformance-C-requires-stated-condition",
                    "message": (
                        "ART-DECOR conformance C requires a stated condition, "
                        f"but none is attached to {name or node.get('kind')}"
                    ),
                    "path": str(source.get("path") or name),
                    "source": source,
                })
            elif not related_rules:
                diagnostics.append({
                    "code": "conditional-conformance-not-machine-enforced",
                    "severity": "warning",
                    "policy": "do-not-infer-condition-from-prose-or-selector",
                    "message": (
                        "ART-DECOR conformance C has stated condition evidence "
                        f"({', '.join(evidence)}) but no associated executable "
                        "assert/report; presence remains input-activated"
                    ),
                    "path": str(source.get("path") or name),
                    "source": source,
                    "condition_evidence": evidence,
                })

        child_parent_rules = parent_rules + rules
        diagnostics.extend(_owner_rule_diagnostics(
            list(node.get("children", [])), child_parent_rules
        ))
        for attribute in node.get("attributes", []):
            for constraint in attribute.get("textual_constraints", []):
                diagnostics.append({
                    "code": "textual-constraint-not-executable",
                    "severity": "warning" if any(
                        term.startswith(("SHALL", "MUST"))
                        for term in constraint.get("normative_terms", [])
                    ) else "info",
                    "policy": "preserve-owner-free-form-markup",
                    "message": (
                        "ART-DECOR <constraint> is free-form markup and has no "
                        "machine test; it is preserved without inferring XPath: "
                        + str(constraint.get("text") or "")
                    ),
                    "path": str(constraint.get("path") or ""),
                    "source": dict(constraint),
                })
    return _unique_constraint_diagnostics(diagnostics)


def _prototype_constraint_diagnostics(
    prototype: list[dict[str, Any]], current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare explicitly matching nodes without merging the prototype.

    ART-DECOR uses the first SPEC relationship as an editor prototype. The
    stored specialized template is the executable design. This comparison
    keeps non-monotonic explicit constraints visible while leaving omitted
    prototype properties and nodes omitted.
    """
    parent_occ: dict[tuple[str, str], list[int]] = defaultdict(list)
    parent_by_id: dict[str, list[int]] = defaultdict(list)
    for index, node in enumerate(prototype):
        parent_occ[_sequence_key(node)].append(index)
        if node.get("kind") == "element" and node.get("id"):
            parent_by_id[str(node.get("id"))].append(index)

    used: set[int] = set()
    result: list[dict[str, Any]] = []
    for node in current:
        key = _sequence_key(node)
        choices = [index for index in parent_occ.get(key, []) if index not in used]
        match = choices[0] if choices else None
        if match is None and node.get("kind") == "element" and node.get("id"):
            by_id = [index for index in parent_by_id.get(str(node.get("id")), []) if index not in used]
            if by_id:
                match = by_id[0]
        if match is None:
            continue
        used.add(match)
        parent_node = prototype[match]
        result.extend(_spec_constraint_diagnostics(parent_node, node, node))
        result.extend(_prototype_constraint_diagnostics(
            list(parent_node.get("children", [])),
            list(node.get("children", [])),
        ))
    return result

def _effective_template(
    template: ET.Element,
    templates: dict[str, list[ET.Element]],
    memo: dict[TemplateKey, list[dict[str, Any]]],
    stack: tuple[TemplateKey, ...] = (),
) -> list[dict[str, Any]]:
    key = _key(template)
    if key in memo:
        return deepcopy(memo[key])
    effective = _direct_template_rules(template)
    # The owner implementation uses the first SPEC relationship as the editor
    # prototype. It does not expand SPEC in getExpandedTemplate. Preserve the
    # same order and use the prototype only to diagnose explicit broadening.
    relation = next(iter(_template_relations(
        template, {TEMPLATE_PROTOTYPE_RELATIONSHIP}
    )), None)
    if relation is not None:
        prototype = select_template(
            templates,
            relation.get("template") or "",
            relation.get("flexibility"),
        )
        if prototype is not None and _key(prototype) not in stack + (key,):
            diagnostics = _prototype_constraint_diagnostics(
                _direct_template_rules(prototype), effective
            )
            if diagnostics and effective:
                effective[0]["_constraint_diagnostics"] = (
                    _unique_constraint_diagnostics(diagnostics)
                )
    memo[key] = deepcopy(effective)
    return effective


def _compiled_element_matches(
    nodes: Iterable[Mapping[str, Any]], element_id: str,
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for node in nodes:
        if node.get("kind") == "element" and node.get("id") == element_id:
            result.append(node)
        result.extend(_compiled_element_matches(
            list(node.get("children", [])), element_id
        ))
    return result


def _direct_source_elements(
    parent: ET.Element,
) -> list[tuple[ET.Element, int, ET.Element]]:
    """Return direct ART-DECOR element children, flattening one choice."""
    result: list[tuple[ET.Element, int, ET.Element]] = []
    for index, child in enumerate(list(parent)):
        if local(child.tag) == "element":
            result.append((parent, index, child))
        elif local(child.tag) == "choice":
            result.extend(
                (child, branch_index, branch)
                for branch_index, branch in enumerate(list(child))
                if local(branch.tag) == "element"
            )
    return result


def _resolved_containment_key(
    element: ET.Element, templates: dict[str, list[ET.Element]],
) -> TemplateKey | None:
    reference = element.get("contains") or ""
    if not reference:
        return None
    target = select_template(templates, reference, element.get("flexibility"))
    return _key(target) if target is not None else None


def _spec_choice_branch(
    parent: ET.Element,
    templates: dict[str, list[ET.Element]],
    extension: CdaExtension,
) -> tuple[ET.Element, TemplateKey]:
    """Find one exact target/replaced choice pair in the parent's SPEC chain."""
    wanted = (extension["template_id"], extension["template_effective_date"])
    replaced = (
        extension["replaces_template_id"],
        extension["replaces_template_effective_date"],
    )
    matches: list[tuple[ET.Element, TemplateKey]] = []
    queue = deque(
        target
        for relation in _template_relations(parent, {"SPEC"})
        for target in [select_template(
            templates,
            relation.get("template") or "",
            relation.get("flexibility"),
        )]
        if target is not None
    )
    seen: set[TemplateKey] = set()
    while queue:
        ancestor = queue.popleft()
        ancestor_key = _key(ancestor)
        if ancestor_key in seen:
            continue
        seen.add(ancestor_key)
        hosts = [
            node for node in ancestor.iter()
            if local(node.tag) == "element"
            and node.get("id") == extension["parent_element_id"]
        ]
        for host in hosts:
            for choice in list(host):
                if local(choice.tag) != "choice":
                    continue
                branches = [
                    branch for branch in list(choice)
                    if local(branch.tag) == "element"
                    and branch.get("name") == extension["element_name"]
                ]
                if not any(
                    _resolved_containment_key(branch, templates) == replaced
                    for branch in branches
                ):
                    continue
                matches.extend(
                    (branch, ancestor_key)
                    for branch in branches
                    if _resolved_containment_key(branch, templates) == wanted
                )
        queue.extend(
            target
            for relation in _template_relations(ancestor, {"SPEC"})
            for target in [select_template(
                templates,
                relation.get("template") or "",
                relation.get("flexibility"),
            )]
            if target is not None
        )
    if len(matches) != 1:
        raise ValueError(
            "reviewed CDA SPEC branch must resolve one exact sibling choice "
            f"between {replaced[0]}@{replaced[1]} and "
            f"{wanted[0]}@{wanted[1]}; found {len(matches)}"
        )
    return matches[0]


def _select_reviewed_spec_branch(
    parent: ET.Element,
    templates: dict[str, list[ET.Element]],
    extension: CdaExtension,
) -> None:
    source_hosts = [
        node for node in parent.iter()
        if local(node.tag) == "element"
        and node.get("id") == extension["parent_element_id"]
    ]
    if len(source_hosts) != 1:
        raise ValueError(
            f"CDA extension parent element {extension['parent_element_id']} "
            "must occur directly in the reviewed parent template"
        )
    replaced = (
        extension["replaces_template_id"],
        extension["replaces_template_effective_date"],
    )
    current = [
        item for item in _direct_source_elements(source_hosts[0])
        if item[2].get("name") == extension["element_name"]
        and _resolved_containment_key(item[2], templates) == replaced
    ]
    if len(current) != 1:
        raise ValueError(
            "reviewed CDA SPEC branch must replace one exact explicit "
            f"containment {replaced[0]}@{replaced[1]}; found {len(current)}"
        )
    prototype, prototype_key = _spec_choice_branch(
        parent, templates, extension
    )
    container, index, old = current[0]
    replacement = deepcopy(prototype)
    replacement.set("flexibility", extension["template_effective_date"])
    replacement.set("_decor2hl7_source", "reviewed-spec-branch")
    replacement.set("_decor2hl7_reason", extension["reason"])
    replacement.set("_decor2hl7_spec_template_id", prototype_key[0])
    replacement.set("_decor2hl7_spec_template_effective_date", prototype_key[1])
    container.remove(old)
    container.insert(index, replacement)


def _apply_reviewed_extensions(
    templates: dict[str, list[ET.Element]],
    document_id: str,
    document_effective: str | None,
    explicit_reachable: Mapping[TemplateKey, ET.Element],
    extensions: Iterable[CdaExtension],
) -> list[CdaExtension]:
    """Apply reviewed exact open-template and SPEC-choice overlays."""
    applied: list[CdaExtension] = []
    memo: dict[TemplateKey, list[dict[str, Any]]] = {}
    for extension in extensions:
        if (
            extension["document_template_id"] != document_id
            or extension["document_template_effective_date"]
            != str(document_effective or "")
        ):
            raise ValueError(
                "CDA extension document identity does not match the selected "
                f"template: {extension['document_template_id']}@"
                f"{extension['document_template_effective_date']}"
            )
        parent_key = (
            extension["parent_template_id"],
            extension["parent_template_effective_date"],
        )
        target_key = (
            extension["template_id"], extension["template_effective_date"],
        )
        if select_template(templates, *target_key) is None:
            raise ValueError(
                "CDA extension target template was not fetched exactly: "
                f"{target_key[0]}@{target_key[1]}"
            )
        if parent_key not in explicit_reachable:
            raise ValueError(
                "CDA extension parent is not explicitly reachable from the "
                f"selected document: {parent_key[0]}@{parent_key[1]}"
            )
        parent = select_template(templates, *parent_key)
        if parent is None:
            raise ValueError(
                f"CDA extension parent template was not fetched: "
                f"{parent_key[0]}@{parent_key[1]}"
            )
        effective_parent = _effective_template(parent, templates, memo)
        effective_matches = _compiled_element_matches(
            effective_parent, extension["parent_element_id"]
        )
        if len(effective_matches) != 1:
            raise ValueError(
                f"CDA extension parent element {extension['parent_element_id']} "
                f"resolved {len(effective_matches)} times in "
                f"{parent_key[0]}@{parent_key[1]}"
            )
        if effective_matches[0].get("is_closed"):
            raise ValueError(
                "CDA extension cannot attach below closed element "
                f"{parent_key[0]}@{parent_key[1]}#"
                f"{extension['parent_element_id']}"
            )
        if extension.get("operation") == "select_spec_branch":
            _select_reviewed_spec_branch(parent, templates, extension)
            applied.append(extension)
            memo.clear()
            continue
        if any(
            child.get("kind") == "element"
            and child.get("name") == extension["element_name"]
            and child.get("contains") == extension["template_id"]
            for child in effective_matches[0].get("children", [])
        ):
            raise ValueError(
                f"CDA extension {extension['template_id']} is already explicitly "
                f"contained by {parent_key[0]}@{parent_key[1]}"
            )
        source_matches = [
            node for node in parent.iter()
            if local(node.tag) == "element"
            and node.get("id") == extension["parent_element_id"]
        ]
        if len(source_matches) != 1:
            raise ValueError(
                f"CDA extension parent element {extension['parent_element_id']} "
                "must occur directly in the reviewed parent template"
            )
        host = source_matches[0]
        synthetic_id = (
            "decor2hl7-extension:"
            f"{extension['parent_element_id']}:"
            f"{extension['template_id']}@{extension['template_effective_date']}"
        )
        child = ET.Element("element", {
            "name": extension["element_name"],
            "id": synthetic_id,
            "contains": extension["template_id"],
            "flexibility": extension["template_effective_date"],
            "minimumMultiplicity": str(extension["minimum_multiplicity"]),
            "maximumMultiplicity": str(extension["maximum_multiplicity"]),
            "conformance": extension["conformance"],
            "_decor2hl7_source": "reviewed-extension",
            "_decor2hl7_reason": extension["reason"],
        })
        host.append(child)
        applied.append(extension)
        memo.clear()
    return applied


def _final_min(value: Any) -> int:
    return int(value) if isinstance(value, int) else 0


def _final_max(value: Any) -> int | None:
    if value == "*":
        return None
    return int(value) if isinstance(value, int) else 1


def _expand_nodes(
    nodes: list[dict[str, Any]],
    templates: dict[str, list[ET.Element]],
    memo: dict[TemplateKey, list[dict[str, Any]]],
    stack: tuple[TemplateKey, ...],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in nodes:
        node = deepcopy(raw)
        if node.get("kind") == "include":
            target = select_template(
                templates, str(node.get("ref") or ""), node.get("flexibility")
            )
            node["min"] = _final_min(node.get("min"))
            node["max"] = _final_max(node.get("max"))
            node["mandatory"] = bool(node.get("mandatory"))
            node["children"] = []
            if target is not None and _key(target) not in stack:
                effective = _effective_template(target, templates, memo)
                target_lets, target_rules, target_variables, target_constraints = (
                    _local_rule_content(
                        target,
                        target,
                        str((_template_context(target) or {}).get("path") or ""),
                        None,
                    )
                )
                node["template_id"] = target.get("id")
                node["template_effective_date"] = target.get("effectiveDate")
                node["template_status_code"] = target.get("statusCode")
                node["context"] = _template_context(target)
                node["attributes"] = _template_context_attributes(target)
                node.setdefault("lets", {}).update(target_lets)
                node.setdefault("validation_rules", []).extend(target_rules)
                node["asserts"] = node["validation_rules"]
                node.setdefault("variable_definitions", []).extend(target_variables)
                node.setdefault("textual_constraints", []).extend(target_constraints)
                node["children"] = _expand_nodes(
                    effective, templates, memo, stack + (_key(target),)
                )
            out.append(node)
            continue

        node["min"] = _final_min(node.get("min"))
        node["max"] = _final_max(node.get("max"))
        node["mandatory"] = bool(node.get("mandatory"))
        node["children"] = _expand_nodes(
            list(node.get("children", [])), templates, memo, stack
        )
        reference = node.get("contains")
        if reference:
            target = select_template(
                templates,
                str(reference),
                node.get("contains_flexibility"),
            )
            if target is not None and _key(target) not in stack:
                effective = _effective_template(target, templates, memo)
                contained = _expand_nodes(
                    effective, templates, memo, stack + (_key(target),)
                )
                _require_contained_root(contained)
                target_lets, target_rules, target_variables, target_constraints = (
                    _local_rule_content(
                        target,
                        target,
                        str((_template_context(target) or {}).get("path") or ""),
                        None,
                    )
                )
                node["children"].append({
                    "kind": "template",
                    "ref": target.get("id"),
                    "template_id": target.get("id"),
                    "template_effective_date": target.get("effectiveDate"),
                    "min": 0,
                    "max": 1,
                    "mandatory": False,
                    "transparent_inline": True,
                    "template_status_code": target.get("statusCode"),
                    "context": _template_context(target),
                    "attributes": _template_context_attributes(target),
                    "children": contained,
                    "validation_rules": target_rules,
                    "asserts": target_rules,
                    "lets": target_lets,
                    "variable_definitions": target_variables,
                    "textual_constraints": target_constraints,
                })
        out.append(node)
    return out


def _require_contained_root(nodes: list[dict[str, Any]]) -> bool:
    """Make a ``contains`` template's concrete root present with its owner."""
    for node in nodes:
        if node.get("kind") == "element":
            if str(node.get("conformance") or "").upper() != "NP":
                node["min"] = max(1, int(node.get("min") or 0))
            return True
        if node.get("kind") in {"include", "template", "choice"} and _require_contained_root(
            list(node.get("children", []))
        ):
            node["transparent_inline"] = True
            return True
    return False


def _model_source(
    node: Mapping[str, Any], path: str, part: str, source: str = "datatype",
) -> dict[str, Any]:
    raw_origin = node.get("origin")
    origin: Mapping[str, Any] = (
        raw_origin if isinstance(raw_origin, Mapping) else {}
    )
    return {
        "template_id": str(origin.get("template_id") or ""),
        "template_effective_date": str(origin.get("template_effective_date") or ""),
        "element_id": None,
        "path": path,
        "source": source,
        "datatype": str(node.get("datatype") or ""),
        "datatype_part": part,
    }


def _datatype_source(node: Mapping[str, Any], path: str, part: str) -> dict[str, Any]:
    return _model_source(node, path, part)


def _datatype_child(
    parent: Mapping[str, Any], name: str, datatype: str,
    minimum: int, maximum: int | None, path: str,
) -> dict[str, Any]:
    source = _datatype_source(parent, path, name)
    return {
        "kind": "element",
        "name": name,
        "template_name": parent.get("template_name"),
        "template_display_name": parent.get("template_display_name"),
        "template_description": parent.get("template_description"),
        "id": None,
        "datatype": datatype,
        "min": minimum,
        "max": maximum,
        "mandatory": False,
        "conformance": None,
        "fixed": {},
        "fixed_text": None,
        "value_sets": [],
        "value_set_bindings": [],
        "codes": [],
        "unit": None,
        "attributes": [],
        "children": [],
        "contains": None,
        "contains_flexibility": None,
        "origin": source,
        # Sources address this physical node.  Ancestor evidence belongs in
        # provenance only; treating it as another source key aliases children
        # and attributes back onto the ancestor target.
        "sources": [source],
        "provenance": [source] + (
            list(parent.get("provenance", [])) if parent.get("model_derived") else []
        ),
        "targets": [],
        "asserts": [],
        "lets": {},
        "datatype_derived": True,
        "datatype_expansion_depth": int(parent.get("datatype_expansion_depth") or 0) + 1,
    }


def _datatype_attribute(
    parent: Mapping[str, Any], name: str, datatype: str, optional: bool, path: str,
) -> dict[str, Any]:
    source = _datatype_source(parent, path, "@" + name)
    return {
        "kind": "attribute",
        "name": name,
        "id": None,
        "datatype": datatype,
        "value": None,
        "optional": optional,
        "value_sets": [],
        "value_set_bindings": [],
        "sources": [source],
        "provenance": [source] + (
            list(parent.get("provenance", [])) if parent.get("model_derived") else []
        ),
        "targets": [],
        "datatype_derived": True,
    }


def _expand_datatype_structure(
    nodes: list[dict[str, Any]], definitions: Mapping[str, Any] | None = None,
    stack: tuple[str, ...] = (),
) -> None:
    """Overlay explicit template constraints on recursively expanded datatypes."""
    def schema_datatype(name: str) -> Any | None:
        """Resolve a declared datatype flavour to its nearest pinned XSD type."""
        current = name
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            if current in (definitions or {}):
                resolved = resolve_definition(  # type: ignore[arg-type]
                    definitions, current,
                )
                return resolved if resolved.category == "datatype" else None
            if classify_datatype(current) not in {"datatype", "alias"}:
                return None
            current = str(datatype_definition(current).base or "")
        return None

    def representation_type(name: str) -> str | None:
        current = name
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            if classify_datatype(current) in {"datatype", "alias"}:
                policy = expand_datatype(current)
                if policy.value_representation is not None:
                    return current
            definition = (definitions or {}).get(current)
            current = str(definition.base or "") if definition is not None else ""
        return None

    for node in nodes:
        if node.get("kind") != "element":
            _expand_datatype_structure(
                list(node.get("children", [])), definitions, stack
            )
            continue
        declared = str(node.get("datatype") or "")
        classification = classify_datatype(declared)
        schema_definition = schema_datatype(declared)
        if schema_definition is not None:
            classification = "datatype"
            node["representation_attributes"] = [
                attribute.name for attribute in schema_definition.attributes
            ]
            if schema_definition.mixed:
                node["mixed_content"] = True
        if classification == "unsupported":
            raise ValueError(
                f"unsupported HL7 V3 datatype {declared!r} at {node.get('origin', {}).get('path') or node.get('name')}"
            )
        normalized = declared.upper()
        representation_name = representation_type(declared)
        representation_definition = (
            expand_datatype(representation_name) if representation_name else None
        )
        if representation_name:
            node["representation_datatype"] = representation_name
        if (
            representation_definition is not None
            and representation_definition.non_null_required_parts
        ):
            node["non_null_required_parts"] = list(
                representation_definition.non_null_required_parts
            )
        current_path = str(node.get("origin", {}).get("path") or node.get("name") or "")
        if representation_definition is not None or schema_definition is not None:
            represented_attributes = set(
                representation_definition.value_representation.attributes
                if representation_definition is not None
                and representation_definition.value_representation is not None else ()
            )
            if (
                representation_definition is not None
                and representation_definition.value_representation is not None
                and representation_definition.value_representation.attribute
            ):
                represented_attributes.add(
                    representation_definition.value_representation.attribute
                )
            existing_attributes: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in node.get("attributes", []):
                existing_attributes[
                    _particle_key("@" + str(item.get("name") or ""))
                ].append(item)
            attributes = (
                schema_definition.attributes if schema_definition is not None
                else representation_definition.attributes  # type: ignore[union-attr]
            )
            for attribute in attributes:
                if attribute.name in represented_attributes:
                    continue
                key = _particle_key("@" + attribute.name)
                if key in existing_attributes:
                    for existing in existing_attributes[key]:
                        existing.setdefault("datatype", attribute.datatype)
                        existing.setdefault("provenance", []).append({
                            **_datatype_source(node, current_path + "/@" + attribute.name, "@" + attribute.name),
                            "source": "template + datatype",
                        })
                else:
                    derived_attribute = _datatype_attribute(
                        node, attribute.name, attribute.datatype, attribute.optional,
                        current_path + "/@" + attribute.name,
                    )
                    if attribute.name in node.get("fixed", {}):
                        derived_attribute["value"] = node["fixed"][attribute.name]
                    node.setdefault("attributes", []).append(derived_attribute)
            existing_children: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in node.get("children", []):
                if item.get("kind") == "element":
                    existing_children[
                        _particle_key(str(item.get("name") or ""))
                    ].append(item)
            if (
                normalized not in stack
                # A derived node that already has a scalar XML representation
                # is a writable boundary.  Complex nodes continue through the
                # XSD graph until such a boundary or a schema cycle is reached.
                and not (
                    node.get("datatype_derived")
                    and representation_definition is not None
                    and representation_definition.value_representation is not None
                )
            ):
                parts = (
                    schema_definition.parts if schema_definition is not None
                    else representation_definition.parts  # type: ignore[union-attr]
                )
                for part in parts:
                    key = _particle_key(part.name)
                    part_path = current_path + "/" + part.name
                    if key in existing_children:
                        for child in existing_children[key]:
                            if not child.get("datatype"):
                                child["datatype"] = part.datatype
                            child.setdefault("provenance", []).append({
                                **_datatype_source(node, part_path, part.name),
                                "source": "template + datatype",
                            })
                    else:
                        child = _datatype_child(
                            node, part.name, part.datatype,
                            part.minimum, part.maximum, part_path,
                        )
                        node.setdefault("children", []).append(child)
                        existing_children[key].append(child)
                _order_children_by_model(node, parts)
        _expand_datatype_structure(
            list(node.get("children", [])),
            definitions,
            stack + ((normalized,) if normalized else ()),
        )


def _materialize_polymorphic_structure(
    nodes: list[dict[str, Any]], definitions: DefinitionIndex,
) -> None:
    """Expose reviewed complex datatype choices below one physical element.

    The wrapper is transparent XML structure. Its children remain ordinary
    compiled datatype nodes, while the renderer consumes the wrapper's generic
    ``xsi_type`` metadata on the already-created parent element.
    """
    subtypes = getattr(definitions, "subtypes", {})
    abstract_types: set[str] = definitions.abstract_types

    def visit(items: list[dict[str, Any]]) -> None:
        for node in items:
            existing_children = list(node.get("children", []))
            visit(existing_children)
            if node.get("kind") != "element":
                continue
            declared = str(node.get("datatype") or "").upper()
            if declared not in POLYMORPHIC_COMPLEX_ROOTS:
                continue
            origin = node.get("origin", {})
            path = str(origin.get("path") or node.get("name") or "")
            if node.get("datatype_derived") and "@xsi:type" not in path:
                continue
            for subtype in sorted(subtypes.get(declared, set())):
                if subtype in abstract_types or subtype not in definitions:
                    continue
                definition = resolve_definition(definitions, subtype)
                branch_path = path + f"_as_{_ascii_name(subtype)}"
                branch_source = {
                    **_model_source(
                        {**node, "datatype": declared}, branch_path, subtype,
                        source="hl7-datatype-choice",
                    ),
                    "datatype": declared,
                    "datatype_part": subtype,
                }
                branch_parent = {
                    **node,
                    "datatype": subtype,
                    "origin": {**dict(origin), "path": branch_path},
                    "model_derived": True,
                    "provenance": list(node.get("provenance", []))
                    + [branch_source],
                }
                children = [
                    _datatype_child(
                        branch_parent, part.name, part.datatype,
                        part.minimum, part.maximum,
                        branch_path + "/" + part.name,
                    )
                    for part in definition.parts
                ]
                if str(node.get("conformance") or "").upper() == "NP":
                    for child in children:
                        child["conformance"] = "NP"
                _expand_datatype_structure(children, definitions, (subtype,))
                policy = expand_datatype(subtype)
                node.setdefault("children", []).append({
                    "kind": "datatype_choice",
                    "datatype": subtype,
                    "declared_datatype": declared,
                    "xsi_type": subtype,
                    "min": 0,
                    "max": 1,
                    "mandatory": False,
                    "conformance": node.get("conformance"),
                    "children": children,
                    "origin": branch_source,
                    "sources": [branch_source],
                    "provenance": [branch_source],
                    "targets": [],
                    "asserts": [],
                    "lets": {},
                    "requirement_owner": branch_path,
                    "non_null_required_parts": list(
                        policy.non_null_required_parts
                    ),
                })

    visit(nodes)


def _normalize_prohibited_subtrees(
    nodes: Sequence[dict[str, Any]], *, inherited: bool = False,
) -> None:
    """Make prohibition effective for every synthesized descendant.

    ART-DECOR may prohibit a particle whose CDA datatype or RIM class has
    required children. Those children describe a value that cannot exist at
    this document location; retaining their local cardinalities would make the
    compiled tree self-contradictory and expose unreachable writable targets.
    """
    for node in nodes:
        prohibited = inherited or (
            str(node.get("conformance") or "").upper() == "NP"
        )
        if prohibited:
            node["conformance"] = "NP"
            node["min"] = 0
            node["mandatory"] = False
        _normalize_prohibited_subtrees(
            node.get("children", []), inherited=prohibited
        )


def _transparent_element_children(
    nodes: Iterable[dict[str, Any]],
) -> Iterable[dict[str, Any]]:
    """Yield XML children through non-XML template expansion wrappers.

    ``include`` and ``contains`` retain transparent nodes in the compiled tree
    so their template identity and occurrence metadata remain reviewable.  They
    do not create an XML level, however, so a CDA/RIM particle supplied by a
    referenced template is already a child of the surrounding XML element.
    """
    for node in nodes:
        if node.get("kind") == "element":
            yield node
        elif node.get("kind") in {"include", "template", "choice"}:
            yield from _transparent_element_children(
                list(node.get("children", []))
            )


def _first_xml_particle(node: Mapping[str, Any]) -> str | None:
    """Return the first concrete XML particle below one compiled child."""
    if node.get("kind") == "element":
        return _particle_key(str(node.get("name") or ""))
    if node.get("kind") in {"include", "template", "choice", "datatype_choice"}:
        for child in node.get("children", []):
            particle = _first_xml_particle(child)
            if particle:
                return particle
    return None


def _order_children_by_model(
    node: dict[str, Any], parts: Iterable[Any],
) -> None:
    """Record the normative CDA/XSD particle order for rendering.

    ART-DECOR templates occasionally list particles in documentation order
    rather than the XSD sequence. The compiled list itself remains in source
    order because physical locations and stable target names are based on its
    indices; the renderer consumes this separate ordering annotation.
    """
    order = {
        _particle_key(str(part.name)): index
        for index, part in enumerate(parts)
    }
    fallback = len(order)
    for index, child in enumerate(node.get("children", [])):
        child["render_order"] = order.get(
            _first_xml_particle(child) or "", fallback + index
        )


def _annotate_null_flavor_exceptions(
    targets: Mapping[str, dict[str, Any]], model: Mapping[str, Any],
) -> None:
    """Retain the legal nullFlavor exceptions of bound target value sets.

    Value-set members are not construction defaults. Exception membership is
    nevertheless an executable profile constraint: it tells the renderer
    which nullFlavor may legally complete a required, otherwise empty value.
    """
    value_sets = model.get("value_sets", {})
    if not isinstance(value_sets, Mapping):
        return
    for target in targets.values():
        exception_sets: list[set[str]] = []
        for binding in target.get("value_set_bindings", []):
            if not isinstance(binding, Mapping) or not binding.get("id"):
                continue
            strength = str(binding.get("strength") or "required").casefold()
            if strength not in {"required", "cne"}:
                continue
            oid = str(binding["id"])
            effective = str(binding.get("effective_date") or "")
            exact = value_sets.get(f"{oid}@{effective}") if effective else None
            candidates = (
                [exact]
                if isinstance(exact, Mapping)
                else [
                    value for key, value in value_sets.items()
                    if str(key).startswith(oid + "@")
                    and isinstance(value, Mapping)
                ]
            )
            for candidate in candidates:
                codes = candidate.get("codes", {})
                exceptions = {
                    str(code)
                    for code in candidate.get("exceptions", [])
                    if isinstance(codes, Mapping)
                    and isinstance(codes.get(str(code)), Mapping)
                    and str(codes[str(code)].get("code_system") or "")
                    == NULL_FLAVOR_CODE_SYSTEM
                }
                if exceptions:
                    exception_sets.append(exceptions)
        if exception_sets:
            target["null_flavor_exceptions"] = sorted(
                set.intersection(*exception_sets)
            )


def _required_binding_constraints(
    targets: Mapping[str, dict[str, Any]], model: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Compile required bindings once and reference them from target leaves."""
    value_sets = model.get("value_sets", {})
    if not isinstance(value_sets, Mapping):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for target in targets.values():
        keys: list[str] = []
        for binding in target.get("value_set_bindings", []):
            if not isinstance(binding, Mapping) or not binding.get("id"):
                continue
            strength = str(binding.get("strength") or "required").casefold()
            if strength not in {"required", "cne"}:
                continue
            oid = str(binding["id"])
            effective = str(binding.get("effective_date") or "")
            exact_key = f"{oid}@{effective}" if effective else ""
            selected_key = exact_key if exact_key in value_sets else ""
            if not selected_key and not effective:
                candidates = sorted(
                    str(key) for key in value_sets
                    if str(key).startswith(oid + "@")
                )
                selected_key = candidates[-1] if candidates else ""
            identity = selected_key or f"{oid}@{effective}"
            entry = value_sets.get(selected_key, {}) if selected_key else {}
            codes = entry.get("codes", {}) if isinstance(entry, Mapping) else {}
            registry.setdefault(identity, {
                "id": oid,
                "effective_date": effective,
                "resolved_effective_date": (
                    str(entry.get("effective_date") or "")
                    if isinstance(entry, Mapping) else ""
                ),
                "resolved": bool(isinstance(codes, Mapping) and codes),
                "members": sorted(
                    {
                        (str(code), str(info.get("code_system") or ""))
                        for code, info in codes.items()
                        if isinstance(info, Mapping)
                    }
                ),
            })
            keys.append(identity)
        if keys:
            target["required_binding_constraints"] = list(dict.fromkeys(keys))
    return registry


def _expand_cda_model_structure(
    nodes: list[dict[str, Any]], definitions: dict[str, Any],
    stack: tuple[str, ...] = (),
    parent_definition: Any | None = None,
    ancestor_closed: bool = False,
) -> None:
    """Overlay ART-DECOR constraints on CDA structural class definitions."""
    for node in nodes:
        if node.get("kind") != "element":
            nested_closed = ancestor_closed or bool(node.get("is_closed"))
            _expand_cda_model_structure(
                list(node.get("children", [])), definitions, stack,
                parent_definition, nested_closed,
            )
            continue
        is_closed = ancestor_closed or bool(node.get("is_closed"))
        node["is_closed"] = is_closed
        definition = element_definition(
            definitions,
            str(node.get("name") or ""),
            declared_type=str(node.get("datatype") or ""),
            parent=parent_definition,
        )
        # Materialize the direct CDA/RIM content model of every explicit
        # ART-DECOR node.  A generated structural child remains a navigation
        # container until a template constrains it; recursively unfolding the
        # complete CDA grammar would produce the entire cyclic RIM graph.
        # Datatype children are expanded recursively in the following pass.
        if node.get("model_derived"):
            definition = None
        if definition is not None and definition.category != "structural":
            definition = None
        current_path = str(
            node.get("origin", {}).get("path") or node.get("name") or ""
        )
        if definition is not None and definition.name not in stack:
            existing_children: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in _transparent_element_children(
                list(node.get("children", []))
            ):
                existing_children[
                    _particle_key(str(item.get("name") or ""))
                ].append(item)
            if node.get("reviewed_extension"):
                allowed = {_particle_key(part.name) for part in definition.parts}
                node["extension_contained_roots_valid"] = all(
                    key in allowed for key in existing_children
                )
            for part in definition.parts:
                part_path = current_path + "/" + part.name
                key = _particle_key(part.name)
                source = _model_source(node, part_path, part.name, "cda-rim")
                if key in existing_children:
                    for child in existing_children[key]:
                        if child.get("reviewed_extension"):
                            child["extension_slot_valid"] = True
                            child["extension_slot_maximum"] = part.maximum
                        if not child.get("datatype"):
                            child["datatype"] = part.datatype
                        if str(child.get("conformance") or "").upper() != "NP":
                            child["min"] = max(
                                int(child.get("min") or 0), part.minimum
                            )
                            current_max = child.get("max")
                            if (
                                not child.get("reviewed_extension")
                                and part.maximum is not None
                                and (
                                    current_max is None
                                    or current_max == "*"
                                    or int(current_max) > part.maximum
                                )
                            ):
                                child["max"] = part.maximum
                        child.setdefault("provenance", []).append({
                            **source, "source": "template + cda-rim",
                        })
                elif not is_closed and not node.get("reviewed_extension"):
                    # The reviewed ``contains`` edge selects the wrapper's
                    # concrete CDA root.  Do not turn the other core choice
                    # branches into writable alternatives at that occurrence.
                    child = _datatype_child(
                        node, part.name, part.datatype, part.minimum, part.maximum,
                        part_path,
                    )
                    child["datatype_derived"] = False
                    child["model_derived"] = True
                    child["origin"] = source
                    child["sources"] = [source]
                    child["provenance"] = [source]
                    node.setdefault("children", []).append(child)
                    existing_children[key].append(child)
            for choice_index, alternatives in enumerate(
                definition.required_choices
            ):
                selected = [
                    child
                    for name in alternatives
                    for child in existing_children.get(_particle_key(name), [])
                    if not child.get("model_derived")
                    and str(child.get("conformance") or "").upper() != "NP"
                ]
                if len(selected) == 1:
                    # The XSD requires one alternative and the ART-DECOR
                    # template selected exactly one concrete branch.  Preserve
                    # that group-derived requirement without making the other
                    # XSD alternatives appear as template endpoints.
                    selected[0]["min"] = max(
                        1, int(selected[0].get("min") or 0)
                    )
                    selected[0]["cda_required_choice"] = {
                        "definition": definition.name,
                        "index": choice_index,
                        "alternatives": list(alternatives),
                    }
            _order_children_by_model(node, definition.parts)
            existing_attributes = {
                _particle_key("@" + str(item.get("name") or "")): item
                for item in node.get("attributes", [])
            }
            for attribute in definition.attributes:
                key = _particle_key("@" + attribute.name)
                path = current_path + "/@" + attribute.name
                source = _model_source(node, path, "@" + attribute.name, "cda-rim")
                if key in existing_attributes:
                    existing = existing_attributes[key]
                    if not existing.get("datatype"):
                        existing["datatype"] = attribute.datatype
                    if (
                        existing.get("value") is None
                        and (attribute.fixed is not None or attribute.default is not None)
                    ):
                        existing["value"] = (
                            attribute.fixed
                            if attribute.fixed is not None else attribute.default
                        )
                    existing["optional"] = bool(
                        existing.get("optional", True) and attribute.optional
                    )
                    existing.setdefault("provenance", []).append({
                        **source, "source": "template + cda-rim",
                    })
                elif not is_closed:
                    item = _datatype_attribute(
                        node, attribute.name, attribute.datatype,
                        attribute.optional, path,
                    )
                    item["datatype_derived"] = False
                    item["model_derived"] = True
                    item["origin"] = source
                    item["sources"] = [source]
                    item["provenance"] = [source]
                    item["value"] = attribute.fixed or attribute.default
                    node.setdefault("attributes", []).append(item)
        _expand_cda_model_structure(
            list(node.get("children", [])), definitions,
            stack + ((definition.name,) if definition is not None else ()),
            definition or parent_definition, is_closed,
        )


def _validate_reviewed_extension_slots(nodes: Iterable[Mapping[str, Any]]) -> None:
    """Reject reviewed attachments that CDA core cannot place unambiguously."""
    for parent in nodes:
        children = list(_transparent_element_children(
            list(parent.get("children", []))
        ))
        by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for child in children:
            by_name[_particle_key(str(child.get("name") or ""))].append(child)
        for siblings in by_name.values():
            extensions = [item for item in siblings if item.get("reviewed_extension")]
            if extensions and parent.get("is_closed"):
                raise ValueError(
                    "reviewed CDA extension cannot attach below closed element "
                    f"{parent.get('name')}"
                )
            for extension in extensions:
                if any(
                    sibling is not extension
                    and sibling.get("contains") == extension.get("contains")
                    for sibling in siblings
                ):
                    raise ValueError(
                        f"CDA extension {extension.get('contains')} is already "
                        f"explicitly contained below {parent.get('name')}"
                    )
                if not extension.get("extension_slot_valid"):
                    raise ValueError(
                        "reviewed CDA extension does not match a CDA core child "
                        f"of {parent.get('name')}: {extension.get('name')}"
                    )
                maximum = extension.get("extension_slot_maximum")
                declared_maximum = extension.get("max")
                if isinstance(maximum, int) and (
                    declared_maximum == "*"
                    or (
                        isinstance(declared_maximum, int)
                        and declared_maximum > maximum
                    )
                ):
                    raise ValueError(
                        "reviewed CDA extension multiplicity exceeds the CDA "
                        f"core limit for {parent.get('name')}/"
                        f"{extension.get('name')}"
                    )
                if isinstance(maximum, int) and len(siblings) > maximum:
                    raise ValueError(
                        "reviewed CDA extension exceeds the CDA core occurrence "
                        f"limit for {parent.get('name')}/{extension.get('name')}"
                    )
                contained = list(_transparent_element_children(
                    list(extension.get("children", []))
                ))
                if len(contained) != 1:
                    raise ValueError(
                        "reviewed CDA extension target must expose exactly one "
                        f"template root below {extension.get('name')}"
                    )
                if not extension.get("extension_contained_roots_valid"):
                    raise ValueError(
                        "reviewed CDA extension contains a template root that is "
                        f"not legal below {extension.get('name')}"
                    )
        _validate_reviewed_extension_slots(list(parent.get("children", [])))


def _raw_datatype_targets(document: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(nodes: Iterable[Mapping[str, Any]]) -> None:
        for node in nodes:
            if node.get("kind") == "element" and (
                node.get("datatype_derived") or node.get("model_derived")
            ):
                origin = node.get("origin", {})
                rows.append({
                    "template_id": origin.get("template_id"),
                    "template_effective_date": origin.get("template_effective_date"),
                    "template_name": node.get("template_name") or "Datatype",
                    "template_display_name": node.get("template_display_name") or "HL7 datatype",
                    "template_description": node.get("template_description"),
                    "kind": "element",
                    "element_id": None,
                    "element_name": node.get("name"),
                    "path": origin.get("path"),
                    "datatype": node.get("datatype"),
                    "value_sets": list(node.get("value_sets", [])),
                    "value_set_bindings": list(node.get("value_set_bindings", [])),
                    "codes": list(node.get("codes", [])),
                    "fixed": dict(node.get("fixed", {})),
                    "fixed_text": node.get("fixed_text"),
                    "description": node.get("description"),
                    "conformance": node.get("conformance"),
                    "prohibited": False,
                    "unit": node.get("unit"),
                    "renderable": False,
                    "provenance": list(node.get("provenance", [])),
                    "datatype_derived": True,
                })
            for attribute in node.get("attributes", []):
                if not (attribute.get("datatype_derived") or attribute.get("model_derived")):
                    continue
                origin = (attribute.get("sources") or [{}])[0]
                rows.append({
                    "template_id": origin.get("template_id"),
                    "template_effective_date": origin.get("template_effective_date"),
                    "template_name": node.get("template_name") or "Datatype",
                    "template_display_name": node.get("template_display_name") or "HL7 datatype",
                    "template_description": node.get("template_description"),
                    "kind": "attribute",
                    "element_id": None,
                    "element_name": "@" + str(attribute.get("name") or "attribute"),
                    "path": origin.get("path"),
                    "datatype": attribute.get("datatype"),
                    "value_sets": list(attribute.get("value_sets", [])),
                    "value_set_bindings": list(attribute.get("value_set_bindings", [])),
                    "codes": [],
                    "fixed": {},
                    "fixed_text": None,
                    "description": None,
                    "conformance": node.get("conformance"),
                    "prohibited": False,
                    "unit": None,
                    "renderable": False,
                    "provenance": list(attribute.get("provenance", [])),
                    "datatype_derived": True,
                })
            walk(child for child in node.get("children", []) if isinstance(child, Mapping))

    walk(document)
    return rows


def _target_lookup(targets: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = defaultdict(list)
    for name, target in targets.items():
        lookup[str(target.get("source_key") or "")].append(name)
        lookup[_revisionless_source_key(target)].append(name)
        # Element-id source resolution is intentionally version tolerant.
        if target.get("element_id"):
            lookup[_tolerant_source_key(target)].append(name)
    return lookup


def _lookup_source_targets(
    lookup: Mapping[str, list[str]], source: Mapping[str, Any]
) -> list[str]:
    """Resolve one physical source, falling back to id-only evidence.

    Exact path identity must win whenever it exists.  Using the id-only index
    first aliases distinct sibling constraints when an ART-DECOR publisher
    reused an element id in a single template.
    """
    exact = list(lookup.get(_source_key(source), []))
    if exact:
        return exact
    revisionless = list(lookup.get(_revisionless_source_key(source), []))
    if revisionless:
        return revisionless
    tolerant = _tolerant_source_key(source)
    return list(lookup.get(tolerant, [])) if tolerant else []


def _annotate_targets(
    document: list[dict[str, Any]], targets: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    lookup = _target_lookup(targets)
    source_index: dict[str, list[str]] = defaultdict(list)
    physical_occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def annotate(
        nodes: list[dict[str, Any]],
        location: tuple[int, ...] = (),
        repeat_ancestors: tuple[tuple[int, ...], ...] = (),
        target_ancestors: tuple[str, ...] = (),
    ) -> None:
        for index, node in enumerate(nodes):
            here = location + (index,)
            maximum = node.get("max")
            repeats_here = maximum is None or (isinstance(maximum, int) and maximum > 1)
            node_repeat_ancestors = repeat_ancestors + ((here,) if repeats_here else ())
            node_repeatable = bool(node_repeat_ancestors)
            own_name: str | None = None
            if node.get("kind") == "element":
                names: list[str] = []
                origin = node.get("origin") or {}
                origin_key = _source_key(origin) if origin else ""
                for source in node.get("sources", []):
                    key = _source_key(source)
                    for name in _lookup_source_targets(lookup, source):
                        if name not in names:
                            names.append(name)
                        if key == origin_key and own_name is None:
                            own_name = name
                if own_name is None and names:
                    own_name = names[0]
                node["targets"] = names
                node["target"] = own_name
                if own_name and own_name in targets:
                    target = targets[own_name]
                    prohibited = str(node.get("conformance") or "").upper() == "NP"
                    target["prohibited"] = prohibited
                    target["conformance"] = node.get("conformance")
                    # Preserve the effective DEC-021 openness predicate on the
                    # flattened target used by mapping analysis.  This is the
                    # same inherited value that governs CDA/RIM expansion and
                    # reviewed extension attachment validation.
                    target["is_closed"] = bool(node.get("is_closed"))
                    target["locations"].append(".".join(map(str, here)))
                    # For an element target, repetition of the target element
                    # itself is its cardinality, not an additional enclosing
                    # occurrence dimension. Only repeating *ancestors* must
                    # correspond to dataset repeat_chain levels. Children and
                    # attributes inherit this node as an ancestor below.
                    target["repeatable"] = bool(node_repeatable)
                    target["repeat_ancestors"] = [".".join(map(str, item)) for item in repeat_ancestors]
                    # Fixed element text is a template constraint, not a writable
                    # application slot.  Keep the target for provenance/evidence
                    # but do not allow mappings or site values to override it.
                    representation = _node_value_representation(node)
                    serialized_representation = (
                        representation.to_dict() if representation is not None else None
                    )
                    if (
                        serialized_representation is not None
                        and _xml_key(str(node.get("name") or "")) == "value"
                    ):
                        declared_type = str(node.get("datatype") or "").upper().split(".", 1)[0]
                        if declared_type and declared_type != "ANY":
                            serialized_representation["xsi_type"] = declared_type
                    target["value_representation"] = serialized_representation
                    target["logical_types"] = []
                    if representation is not None:
                        typed = _typed_value_target(
                            own_name,
                            str(target.get("path") or ""),
                            representation,
                            node.get("provenance", []),
                        )
                        if serialized_representation is not None and serialized_representation.get("xsi_type"):
                            typed["value_representation"]["xsi_type"] = serialized_representation["xsi_type"]
                        target.update(typed)
                    # A composite value representation may contain both the
                    # source-controlled scalar slot and template-controlled
                    # companion metadata.  For example, PQ writes the number
                    # to @value while a template commonly fixes @unit.  Only a
                    # fixed scalar slot makes the value target non-writable;
                    # fixed companion attributes are retained by the renderer.
                    scalar_attribute = (
                        serialized_representation.get("scalar_attribute")
                        if serialized_representation else None
                    ) or (
                        serialized_representation.get("attribute")
                        if serialized_representation else None
                    )
                    fixed_representation = bool(
                        scalar_attribute
                        and scalar_attribute in node.get("fixed", {})
                    ) or bool(
                        serialized_representation
                        and serialized_representation.get("kind") == "coded"
                        and len(node.get("codes", [])) == 1
                    )
                    target["writable"] = bool(
                        representation is not None
                        and not prohibited and node.get("fixed_text") is None
                        and not fixed_representation
                    )
                    # Structural nodes remain addressable repeat anchors even
                    # when they are not scalar value targets.
                    target["renderable"] = not prohibited and node.get("fixed_text") is None
                    # The concrete node carries effective SPEC constraints.
                    for key in (
                        "datatype", "value_sets", "value_set_bindings", "binding_strength",
                        "codes", "fixed", "fixed_text", "unit", "properties",
                        "min", "max", "mandatory", "system_value", "content_role",
                    ):
                        target[key] = deepcopy(node.get(key))
                    target["has_children"] = bool(node.get("children"))
                    target["permits_null_flavor"] = any(
                        str(attribute.get("name") or "").split(":", 1)[-1]
                        == "nullFlavor"
                        and attribute.get("optional") is not False
                        and attribute.get("value") in (None, "")
                        for attribute in node.get("attributes", [])
                    )
                    target["provenance"] = deepcopy(node.get("provenance", []))
                if own_name:
                    physical_occurrences[own_name].append({
                        "node": node,
                        "target": deepcopy(targets[own_name]),
                        "location": ".".join(map(str, here)),
                        "repeatable": bool(node_repeatable),
                        "repeat_ancestors": [
                            ".".join(map(str, item)) for item in repeat_ancestors
                        ],
                        "target_ancestors": target_ancestors,
                    })
                    for source in node.get("sources", []):
                        key = _source_key(source)
                        if own_name not in source_index[key]:
                            source_index[key].append(own_name)
                        revisionless = _revisionless_source_key(source)
                        if own_name not in source_index[revisionless]:
                            source_index[revisionless].append(own_name)
                        tolerant = _tolerant_source_key(source)
                        if tolerant:
                            if own_name not in source_index[tolerant]:
                                source_index[tolerant].append(own_name)

                for attr_index, attr in enumerate(node.get("attributes", [])):
                    attr_names: list[str] = []
                    attr_origin = (attr.get("sources") or [{}])[-1]
                    attr_origin_key = _source_key(attr_origin)
                    own_attr: str | None = None
                    for source in attr.get("sources", []):
                        key = _source_key(source)
                        for name in _lookup_source_targets(lookup, source):
                            if name not in attr_names:
                                attr_names.append(name)
                            if key == attr_origin_key and own_attr is None:
                                own_attr = name
                    if own_attr is None and attr_names:
                        own_attr = attr_names[0]
                    attr["targets"] = attr_names
                    attr["target"] = own_attr
                    if own_attr and own_attr in targets:
                        target = targets[own_attr]
                        prohibited = str(node.get("conformance") or "").upper() == "NP"
                        target["prohibited"] = prohibited
                        target["conformance"] = node.get("conformance")
                        target["locations"].append(".".join(map(str, here + (100000 + attr_index,))))
                        target["repeatable"] = bool(node_repeatable)
                        target["repeat_ancestors"] = [".".join(map(str, item)) for item in node_repeat_ancestors]
                        fixed_value = attr.get("value")
                        representation = value_representation(
                            attr.get("datatype"), attribute_name=str(attr.get("name") or "")
                        )
                        if representation is None:
                            raise ValueError(
                                "unsupported CDA attribute datatype "
                                f"{attr.get('datatype')!r} on {own_attr!r}"
                            )
                        target["value_representation"] = representation.to_dict()
                        target.update(_typed_value_target(
                            own_attr,
                            str(target.get("path") or ""),
                            representation,
                            attr.get("provenance", []),
                        ))
                        conditional_fixed = bool(
                            fixed_value is not None
                            and attr.get("optional") is True
                        )
                        attr["conditional_fixed"] = conditional_fixed
                        target["conditional_fixed"] = conditional_fixed
                        # A fixed optional attribute constrains the value only
                        # when the attribute is present.  It remains a legal
                        # mapping endpoint (for example @nullFlavor="NI"), but
                        # the renderer must omit it when no value is assigned
                        # and reject any assigned value other than the fixed
                        # one.  Required fixed attributes are still supplied
                        # entirely by the template and are not writable.
                        target["writable"] = not prohibited and (
                            fixed_value is None or conditional_fixed
                        )
                        target["renderable"] = target["writable"]
                        target["datatype"] = attr.get("datatype")
                        target["value_sets"] = deepcopy(attr.get("value_sets", []))
                        target["value_set_bindings"] = deepcopy(
                            attr.get("value_set_bindings", [])
                        )
                        target["fixed"] = {"value": fixed_value} if fixed_value is not None else {}
                        target["min"] = 0 if attr.get("optional") is not False else 1
                        target["max"] = 1
                        target["mandatory"] = attr.get("optional") is False
                        target["has_children"] = False
                        target["provenance"] = deepcopy(attr.get("provenance", []))
                        for key in ("system_value", "content_role"):
                            if attr.get(key):
                                target[key] = deepcopy(attr[key])
                    if own_attr:
                        physical_occurrences[own_attr].append({
                            "node": attr,
                            "target": deepcopy(targets[own_attr]),
                            "location": ".".join(
                                map(str, here + (100000 + attr_index,))
                            ),
                            "repeatable": bool(node_repeatable),
                            "repeat_ancestors": [
                                ".".join(map(str, item))
                                for item in node_repeat_ancestors
                            ],
                            "target_ancestors": target_ancestors
                            + ((own_name,) if own_name else ()),
                        })
                        for source in attr.get("sources", []):
                            key = _source_key(source)
                            if own_attr not in source_index[key]:
                                source_index[key].append(own_attr)
                            revisionless = _revisionless_source_key(source)
                            if own_attr not in source_index[revisionless]:
                                source_index[revisionless].append(own_attr)
                            tolerant = _tolerant_source_key(source)
                            if tolerant:
                                if own_attr not in source_index[tolerant]:
                                    source_index[tolerant].append(own_attr)
            annotate(
                list(node.get("children", [])),
                here,
                node_repeat_ancestors,
                target_ancestors + ((own_name,) if own_name else ()),
            )

    annotate(document)

    # A reusable included/contained template may occur at several physical
    # positions in one effective document.  Its template-local target remains
    # intentionally ambiguous, but each occurrence can still be addressed
    # safely when a distinct containing-template target anchors it.  These
    # aliases are compiled facts: runtime and mapping policy do not inspect XML
    # paths or know particular template ids.
    for base_name, occurrences in physical_occurrences.items():
        if len(occurrences) <= 1 or base_name not in targets:
            continue
        base = targets[base_name]
        base_template_id = str(base.get("template_id") or "")
        aliases: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for occurrence in occurrences:
            anchor = next((
                ancestor for ancestor in reversed(
                    tuple(str(item) for item in occurrence["target_ancestors"])
                )
                if str(targets.get(ancestor, {}).get("template_id") or "")
                != base_template_id
            ), "")
            if not anchor:
                aliases = []
                break
            alias = f"{anchor}::{base_name}"
            if alias in seen or alias in targets:
                aliases = []
                break
            seen.add(alias)
            aliases.append((alias, occurrence))
        if len(aliases) != len(occurrences):
            continue
        for alias, occurrence in aliases:
            target = deepcopy(occurrence["target"])
            target.update({
                "locations": [occurrence["location"]],
                "repeatable": occurrence["repeatable"],
                "repeat_ancestors": occurrence["repeat_ancestors"],
                "occurrence_of": base_name,
                "occurrence_anchor": alias.split("::", 1)[0],
            })
            targets[alias] = target
            occurrence["node"].setdefault("targets", []).append(alias)
    return dict(source_index)


def _annotate_non_null_requirements(
    document: list[dict[str, Any]], targets: dict[str, dict[str, Any]],
) -> None:
    """Attach normative compound-datatype companion requirements to targets.

    The CDA XSD intentionally permits some combinations that the V3 datatype
    rules reject.  Requirements are compiled from datatype policy onto the
    concrete target tree so mapping and runtime code can stay independent of
    datatype names and XML paths.
    """

    Requirement = tuple[str, str, bool]

    def target_name(node: Mapping[str, Any]) -> str:
        return str(node.get("target") or node.get("requirement_owner") or "")

    def visit_node(
        node: dict[str, Any], inherited: tuple[Requirement, ...],
    ) -> None:
        own_name = target_name(node)
        active = [
            (owner, required, satisfied or own_name == required)
            for owner, required, satisfied in inherited
        ]
        for part in node.get("non_null_required_parts", []):
            matches = [
                child for child in node.get("children", [])
                if child.get("kind") == "element"
                and _particle_key(str(child.get("name") or ""))
                == _particle_key(str(part))
                and target_name(child)
            ]
            if len(matches) == 1 and own_name:
                active.append((own_name, target_name(matches[0]), False))

        requirements = sorted({
            required for _, required, satisfied in active if not satisfied
        })
        if own_name in targets and requirements:
            targets[own_name]["non_null_requires"] = requirements
            targets[own_name]["non_null_requirement_owners"] = {
                required: sorted({
                    owner for owner, candidate, satisfied in active
                    if candidate == required and not satisfied
                })
                for required in requirements
            }

        for attr in node.get("attributes", []):
            attr_name = target_name(attr)
            if attr_name not in targets:
                continue
            applicable = {
                required for owner, required, satisfied in active
                if not satisfied and not (
                    str(attr.get("name") or "") == "nullFlavor"
                    and owner == own_name
                )
            }
            if applicable:
                targets[attr_name]["non_null_requires"] = sorted(applicable)
                targets[attr_name]["non_null_requirement_owners"] = {
                    required: sorted({
                        owner for owner, candidate, satisfied in active
                        if candidate == required and not satisfied
                    })
                    for required in sorted(applicable)
                }

        for child in node.get("children", []):
            visit_node(child, tuple(active))

    for node in document:
        visit_node(node, ())

    # Occurrence-qualified aliases are created before datatype companion
    # requirements are attached. Preserve the base target's conservative
    # dependency on each alias as well. A required ambiguous base target may
    # make such an alias review-only, but it must never become less constrained
    # merely because its physical occurrence was qualified.
    for target in targets.values():
        base_name = str(target.get("occurrence_of") or "")
        base = targets.get(base_name, {})
        if not isinstance(base, Mapping):
            continue
        for key in (
            "non_null_requires", "non_null_requirement_owners",
        ):
            if key in base:
                target[key] = deepcopy(base[key])


def _annotate_quantity_range_targets(
    document: list[dict[str, Any]], targets: dict[str, dict[str, Any]],
) -> None:
    """Compile interval-bound target names into quantity representations.

    The runtime must not infer CDA structure from datatype names or XPath
    suffixes.  Once physical targets are known, the compiler can safely record
    which direct children carry the low and high values of a quantity target.
    """

    def visit(node: dict[str, Any]) -> None:
        own_name = str(node.get("target") or "")
        target = targets.get(own_name, {})
        representation = target.get("value_representation", {})
        if (
            node.get("kind") == "element"
            and isinstance(representation, dict)
            and representation.get("kind")
            == ValueRepresentationKind.QUANTITY.value
        ):
            parts: dict[str, str] = {}
            for part in ("low", "high"):
                matches = [
                    child for child in node.get("children", [])
                    if child.get("kind") == "element"
                    and _particle_key(str(child.get("name") or "")) == part
                    and child.get("target") in targets
                ]
                if len(matches) != 1:
                    continue
                child_name = str(matches[0]["target"])
                child_target = targets[child_name]
                child_representation = child_target.get(
                    "value_representation", {}
                )
                if (
                    child_target.get("writable")
                    and len(child_target.get("locations", [])) == 1
                    and isinstance(child_representation, Mapping)
                    and child_representation.get("kind")
                    == ValueRepresentationKind.QUANTITY.value
                ):
                    parts[part] = child_name
            if set(parts) == {"low", "high"}:
                representation["range_targets"] = parts
        for child in node.get("children", []):
            visit(child)

    for node in document:
        visit(node)


def _materialize_polymorphic_targets(
    document: list[dict[str, Any]],
    targets: dict[str, dict[str, Any]],
    source_index: dict[str, list[str]],
) -> None:
    """Expose typed scalar choices for an abstract ``ANY`` element.

    CDA requires a concrete ``xsi:type`` when an abstract value is written.
    The choices are derived from the same datatype representation policy used
    for ordinary targets; the renderer consumes the compiled representation
    and remains unaware of particular templates or clinical classes.
    """
    scalar_types = ("ST", "CD", "PQ", "TS", "BL", "II", "INT")

    def visit(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            own_name = str(node.get("target") or "")
            if (
                node.get("kind") == "element"
                and str(node.get("datatype") or "").upper() == "ANY"
                and own_name in targets
            ):
                original = targets[own_name]
                for datatype in scalar_types:
                    representation = value_representation(datatype)
                    if representation is None:
                        continue
                    name = f"{own_name}_as_{_ascii_name(datatype)}"
                    if name in targets:
                        raise ValueError(f"duplicate polymorphic CDA target {name!r}")
                    target = deepcopy(original)
                    serialized = representation.to_dict()
                    serialized["xsi_type"] = datatype
                    target.update(_typed_value_target(
                        name,
                        str(original.get("path") or ""),
                        representation,
                        node.get("provenance", []),
                    ))
                    target.update({
                        "datatype": datatype,
                        "declared_datatype": "ANY",
                        "polymorphic": True,
                        "value_representation": serialized,
                        "logical_types": list(representation.logical_types),
                        "writable": bool(
                            not original.get("prohibited")
                            and node.get("fixed_text") is None
                        ),
                        "renderable": bool(not original.get("prohibited")),
                    })
                    target["provenance"] = deepcopy(node.get("provenance", [])) + [{
                        "source": "hl7-datatype-choice",
                        "template_id": str(original.get("template_id") or ""),
                        "template_effective_date": str(
                            original.get("template_effective_date") or ""
                        ),
                        "element_id": original.get("element_id"),
                        "path": str(original.get("path") or ""),
                        "datatype": "ANY",
                        "datatype_part": datatype,
                    }]
                    targets[name] = target
                    node.setdefault("targets", []).append(name)
                    for source in node.get("sources", []):
                        for key in {
                            _source_key(source),
                            _revisionless_source_key(source),
                            _tolerant_source_key(source),
                        }:
                            if key and name not in source_index.setdefault(key, []):
                                source_index[key].append(name)
            visit(list(node.get("children", [])))

    visit(document)


def _compiled_content_roles(
    nodes: list[dict[str, Any]], element_path: tuple[str, ...] = (),
) -> None:
    """Annotate specification-defined values supplied by document production.

    These roles are compiled once from the effective CDA hierarchy.  Rendering
    consumes only the role metadata and therefore has no datatype or template
    name dispatch of its own.
    """
    for node in nodes:
        path = element_path
        if node.get("kind") == "element":
            raw = str(node.get("name") or "").split(":", 1)[-1]
            raw = raw.split("[", 1)[0]
            path = element_path + (raw,)
            datatype = str(node.get("datatype") or "")
            if (
                classify_datatype(datatype) in {"datatype", "alias"}
                and base_datatype(datatype) == "II"
                and (node.get("mandatory") or int(node.get("min") or 0) >= 1)
                and not node.get("fixed")
            ):
                node["system_value"] = "generated_identifier"
            if path == ("ClinicalDocument", "id"):
                node["system_value"] = "document_identifier"
            elif path == ("ClinicalDocument", "setId"):
                node["system_value"] = "document_set_identifier"
            elif path == ("ClinicalDocument", "versionNumber"):
                node["system_value"] = "document_version_number"
            elif path == ("ClinicalDocument", "effectiveTime"):
                node["system_value"] = "document_generation_time"
            elif path == ("ClinicalDocument", "author", "time"):
                node["system_value"] = "document_generation_time"
            elif path == (
                "ClinicalDocument", "custodian", "assignedCustodian",
                "representedCustodianOrganization", "id",
            ):
                node["system_value"] = "custodian_organization_identifier"
            elif path == (
                "ClinicalDocument", "custodian", "assignedCustodian",
                "representedCustodianOrganization", "name",
            ):
                node["system_value"] = "custodian_organization_name"
            elif len(path) >= 2 and path[-2:] == ("section", "title"):
                node["content_role"] = "section_title"
            elif len(path) >= 2 and path[-2:] == ("section", "text"):
                node["content_role"] = "section_narrative"
            representation = _node_value_representation(node)
            if (
                "section" in element_path
                and raw == "text"
                and representation is not None
                and representation.kind == ValueRepresentationKind.ELEMENT_TEXT
            ):
                for child in node.get("children", []):
                    child_name = str(child.get("name") or "").split(":", 1)[-1]
                    child_name = child_name.split("[", 1)[0]
                    required_child = bool(
                        child.get("mandatory") or int(child.get("min") or 0) >= 1
                    )
                    required_value = next((
                        attribute
                        for attribute in child.get("attributes", [])
                        if str(attribute.get("name") or "").split(":", 1)[-1]
                        == "value"
                        and attribute.get("optional") is False
                        and attribute.get("value") is None
                    ), None)
                    if (
                        child_name != "reference"
                        or not required_child
                        or required_value is None
                    ):
                        continue
                    # CDA entry text commonly carries its value by reference to
                    # human-readable section narrative. The required fragment
                    # URI is document-production infrastructure, not a second
                    # clinical mapping endpoint.
                    node["content_role"] = "linked_narrative"
                    child["content_role"] = "narrative_reference"
                    child["system_value"] = "generated_narrative_reference"
                    required_value["content_role"] = "narrative_reference"
                    required_value["system_value"] = (
                        "generated_narrative_reference"
                    )
                    break
            if (
                representation is not None
                and representation.kind == ValueRepresentationKind.CODED
            ):
                for child in node.get("children", []):
                    child_name = str(child.get("name") or "").split(":", 1)[-1]
                    child_name = child_name.split("[", 1)[0]
                    child_representation = value_representation(
                        child.get("representation_datatype")
                        or child.get("datatype")
                    )
                    if (
                        child_name == "originalText"
                        and child_representation is not None
                        and child_representation.kind
                        == ValueRepresentationKind.ELEMENT_TEXT
                    ):
                        # The datatype definition, rather than the renderer,
                        # owns the fact that a coded value's source wording is
                        # serialized in this companion text node.
                        child["content_role"] = "coded_original_text"
        _compiled_content_roles(list(node.get("children", [])), path)


def _annotate_linked_narrative_targets(
    document: list[dict[str, Any]], targets: dict[str, dict[str, Any]],
) -> None:
    """Resolve compiled entry-text roles to one section and reference target.

    The content-role pass runs before physical target names exist. This pass
    records the exact target relationship after annotation so runtime can
    execute it without interpreting template ids, datatype names, or paths.
    """
    def local_name(node: Mapping[str, Any]) -> str:
        value = str(node.get("name") or "").split(":", 1)[-1]
        return value.split("[", 1)[0]

    def annotate_section(
        section: dict[str, Any], section_location: tuple[int, ...],
    ) -> None:
        narratives: list[dict[str, Any]] = []
        links: list[tuple[dict[str, Any], tuple[int, ...]]] = []

        def scan(
            nodes: list[dict[str, Any]], location: tuple[int, ...],
            ancestors: tuple[tuple[dict[str, Any], tuple[int, ...]], ...],
        ) -> None:
            for index, node in enumerate(nodes):
                here = location + (index,)
                if node is not section and local_name(node) == "section":
                    continue
                if node.get("content_role") == "section_narrative":
                    narratives.append(node)
                if node.get("content_role") == "linked_narrative":
                    owner_location = next((
                        ancestor_location
                        for ancestor, ancestor_location in reversed(ancestors)
                        if local_name(ancestor) in {"entry", "entryRelationship"}
                    ), section_location)
                    links.append((node, owner_location))
                scan(
                    list(node.get("children", [])), here,
                    ancestors + ((node, here),),
                )

        scan(
            list(section.get("children", [])), section_location,
            ((section, section_location),),
        )
        narrative_names = {
            str(node.get("target") or "") for node in narratives
            if node.get("target")
        }
        if len(narrative_names) != 1:
            return
        narrative_name = next(iter(narrative_names))
        narrative_target = targets.get(narrative_name, {})
        if len(narrative_target.get("locations", [])) != 1:
            return
        section_repeats = list(narrative_target.get("repeat_ancestors", []))

        for node, owner_location in links:
            source_name = str(node.get("target") or "")
            source_target = targets.get(source_name, {})
            reference_nodes = [
                child for child in node.get("children", [])
                if child.get("content_role") == "narrative_reference"
            ]
            reference_names = {
                str(attribute.get("target") or "")
                for child in reference_nodes
                for attribute in child.get("attributes", [])
                if attribute.get("content_role") == "narrative_reference"
                and attribute.get("target")
            }
            if (
                not source_name
                or len(source_target.get("locations", [])) != 1
                or len(reference_names) != 1
            ):
                continue
            reference_name = next(iter(reference_names))
            reference_target = targets.get(reference_name, {})
            source_repeats = list(source_target.get("repeat_ancestors", []))
            reference_repeats = list(
                reference_target.get("repeat_ancestors", [])
            )
            if (
                len(reference_target.get("locations", [])) != 1
                or source_repeats != reference_repeats
                or source_repeats[:len(section_repeats)] != section_repeats
            ):
                continue
            source_target["narrative_link"] = {
                "reference_target": reference_name,
                "section_narrative_target": narrative_name,
                "owner_location": ".".join(map(str, owner_location)),
                "occurrence_depth": len(reference_repeats),
                "section_occurrence_depth": len(section_repeats),
            }
            reference_target["narrative_source_target"] = source_name
            reference_target["section_narrative_target"] = narrative_name

    def visit(
        nodes: list[dict[str, Any]], location: tuple[int, ...] = (),
    ) -> None:
        for index, node in enumerate(nodes):
            here = location + (index,)
            if local_name(node) == "section":
                annotate_section(node, here)
            visit(list(node.get("children", [])), here)

    visit(document)



def compile_cda(
    xml_paths: Iterable[Path],
    model: dict[str, Any],
    fallback_paths: Iterable[Path] = (),
    cutoff: str | None = None,
    *,
    strict: bool = True,
    strict_specializations: bool = False,
    core_definition_paths: Iterable[Path] = (),
    value_set_paths: Iterable[Path] = (),
    cda_extensions: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    # Retained for API compatibility. ValueSet resources no longer turn
    # ART-DECOR example members into executable construction defaults.
    del value_set_paths
    template_id = str(model.get("meta", {}).get("template_id") or "")
    if not template_id:
        raise ValueError("model has no representing CDA template")
    template_effective = str(model.get("meta", {}).get("template_effective_date") or "") or None
    xml_paths = list(xml_paths)
    templates = collect_templates(xml_paths, fallback_paths, cutoff)
    extensions = normalize_extensions(cda_extensions)
    for extension in extensions:
        if (
            extension["transaction_id"]
            != str(model.get("meta", {}).get("transaction_id") or "")
            or extension["transaction_effective_date"]
            != str(model.get("meta", {}).get("transaction_effective_date") or "")
        ):
            raise ValueError(
                "CDA extension transaction identity does not match the compiled model"
            )
    explicit_reachable, _ = reachable_templates(
        templates, template_id, template_effective
    )
    applied_extensions = _apply_reviewed_extensions(
        templates, template_id, template_effective,
        explicit_reachable, extensions,
    )
    reachable, missing = reachable_templates(templates, template_id, template_effective)
    source_construct_coverage = inspect_template_constructs(reachable.values())
    require_supported_constructs(source_construct_coverage)
    unresolved_prototypes = _unresolved_template_prototypes(
        reachable, templates
    )
    if strict and missing:
        formatted = ", ".join(
            f"{row.get('relation')} {row.get('template')} @ {row.get('flexibility') or 'dynamic'}"
            for row in missing[:10]
        )
        raise ValueError(f"CDA template closure is incomplete: {formatted}")
    selected = select_template(templates, template_id, template_effective)
    if selected is None:
        raise ValueError(f"document template {template_id} missing")
    memo: dict[TemplateKey, list[dict[str, Any]]] = {}
    effective = _effective_template(selected, templates, memo)
    document = _expand_nodes(effective, templates, memo, (_key(selected),))
    _apply_document_template_context(document, selected)
    specialization_diagnostics = _extract_constraint_diagnostics(document)
    if strict_specializations and specialization_diagnostics:
        messages = "; ".join(
            str(item.get("message") or item.get("code") or "SPEC weakening")
            for item in specialization_diagnostics[:10]
        )
        raise ValueError(f"CDA SPEC constraint weakening: {messages}")
    constraint_diagnostics = _unique_constraint_diagnostics(
        specialization_diagnostics + _owner_rule_diagnostics(document)
    )
    definitions = index_definitions(core_definition_paths)
    if applied_extensions and not definitions:
        raise ValueError(
            "reviewed CDA extensions require the pinned CDA core definitions"
        )
    if definitions:
        _expand_cda_model_structure(document, definitions)
        _validate_reviewed_extension_slots(document)
    inventory = datatype_inventory(document)
    if inventory["unsupported"]:
        raise ValueError(
            "unsupported HL7 V3 datatype(s) in effective CDA template: "
            + ", ".join(inventory["unsupported"])
        )
    _expand_datatype_structure(document, definitions)
    if definitions:
        _materialize_polymorphic_structure(document, definitions)
    _normalize_prohibited_subtrees(document)
    _compiled_content_roles(document)
    targets = _name_targets(
        _raw_targets(reachable) + _raw_datatype_targets(document)
    )
    # A document-level template's root is necessarily present even where the
    # design omits explicit multiplicity on the root ClinicalDocument element.
    for node in document:
        if node.get("kind") == "element":
            node["min"] = max(1, int(node.get("min") or 0))
            node["mandatory"] = True
            break
    source_index = _annotate_targets(document, targets)
    _annotate_null_flavor_exceptions(targets, model)
    terminology_constraints = _required_binding_constraints(targets, model)
    _annotate_non_null_requirements(document, targets)
    _materialize_polymorphic_targets(document, targets, source_index)
    _annotate_quantity_range_targets(document, targets)
    _annotate_linked_narrative_targets(document, targets)
    validation_rules: list[dict[str, Any]] = []
    textual_constraints: list[dict[str, Any]] = []
    variable_definitions: list[dict[str, Any]] = []
    def collect_validation_rules(
        nodes: Sequence[Mapping[str, Any]], prefix: tuple[int, ...] = (),
    ) -> None:
        for index, node in enumerate(nodes):
            here = prefix + (index,)
            for rule in node.get("validation_rules", node.get("asserts", [])):
                validation_rules.append({
                    **dict(rule),
                    "location": ".".join(map(str, here)),
                    "lets": deepcopy(dict(node.get("lets", {}))),
                })
            textual_constraints.extend(
                deepcopy(list(node.get("textual_constraints", [])))
            )
            variable_definitions.extend(
                deepcopy(list(node.get("variable_definitions", [])))
            )
            for attribute in node.get("attributes", []):
                textual_constraints.extend(
                    deepcopy(list(attribute.get("textual_constraints", [])))
                )
            collect_validation_rules(list(node.get("children", [])), here)
    collect_validation_rules(document)
    # A generated target is directly writable only when it resolves to exactly
    # one physical node in the effective document.  Keep ambiguous targets in
    # the registry for evidence/provenance, but make them non-renderable so no
    # caller can accidentally emit the value twice.
    for target in targets.values():
        if len(target.get("locations", [])) != 1:
            target["renderable"] = False
            target["writable"] = False
    def constraint_counts(nodes: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
        elements = 0
        attributes = 0
        for node in nodes:
            if node.get("kind") == "attribute":
                attributes += 1
            else:
                elements += 1
            nested_elements, nested_attributes = constraint_counts(
                list(node.get("children", []))
            )
            elements += nested_elements
            attributes += nested_attributes + len(node.get("attributes", []))
        return elements, attributes
    element_count, attribute_count = constraint_counts(document)
    return {
        "version": 5,
        "format": "cda",
        "document_template": {
            "id": template_id,
            "effective_date": selected.get("effectiveDate"),
            "name": selected.get("name"),
            "display_name": selected.get("displayName"),
            "description": _description(selected),
        },
        "reviewed_extensions": applied_extensions,
        "constraint_diagnostics": constraint_diagnostics,
        "source_construct_coverage": source_construct_coverage,
        "targets": targets,
        # Filled after dataset-to-CDA mapping has established logical target
        # occurrences.  ``targets`` remains the physical template constraint
        # registry; ``datapoints`` is the writable model-facing interface.
        "datapoints": {},
        "source_index": source_index,
        "validation_rules": validation_rules,
        # Backwards-compatible field name retained for older readers. Entries
        # carry an explicit kind and may therefore be assert or report.
        "assertions": validation_rules,
        "textual_constraints": textual_constraints,
        "variable_definitions": variable_definitions,
        "terminology_constraints": terminology_constraints,
        "document": document,
        "unresolved_templates": missing,
        "unresolved_template_prototypes": unresolved_prototypes,
        "datatype_inventory": inventory,
        "cda_model": {
            "definitions": len(definitions),
            "source": "HL7 CDA R2 normative XSD" if definitions else None,
        },
        "compiled_defaults": 0,
        "stats": {
            "reachable_templates": len(reachable),
            "reviewed_extensions": len(applied_extensions),
            "targets": len(targets),
            "renderable_targets": sum(bool(target.get("renderable")) for target in targets.values()),
            "writable_value_targets": sum(bool(target.get("writable")) for target in targets.values()),
            "validation_rules": len(validation_rules),
            "assertions": sum(
                str(rule.get("kind") or "assert") == "assert"
                for rule in validation_rules
            ),
            "reports": sum(
                str(rule.get("kind") or "assert") == "report"
                for rule in validation_rules
            ),
            "textual_constraints": len(textual_constraints),
            "variable_definitions": len(variable_definitions),
            "constraint_diagnostics": len(constraint_diagnostics),
            "source_constructs": sum(
                source_construct_coverage.get("constructs", {}).values()
            ),
            "unresolved_template_prototypes": len(unresolved_prototypes),
            "elements": element_count,
            "attributes": attribute_count,
        },
    }


def write_cda(
    xml_paths: Iterable[Path],
    model_dir: Path,
    model: dict[str, Any],
    fallback_paths: Iterable[Path] = (),
    cutoff: str | None = None,
    *,
    strict_specializations: bool = False,
) -> dict[str, Any]:
    cda = compile_cda(
        xml_paths, model, fallback_paths, cutoff,
        strict_specializations=strict_specializations,
    )
    write_json(model_dir / "cda.json", cda)
    (model_dir / "cda-assertions.sch").write_text(schematron(cda), encoding="utf-8")
    return cda


def compile_cda_model(
    templates: Iterable[Path], model: dict[str, Any], *,
    strict_specializations: bool = False,
) -> dict[str, Any]:
    """Compile all available exact templates and report closure gaps."""
    return compile_cda(
        templates, model, strict=False,
        strict_specializations=strict_specializations,
    )


def write_cda_model(
    templates: Iterable[Path], model_dir: Path, model: dict[str, Any],
    core_definition_paths: Iterable[Path] = (),
    value_set_paths: Iterable[Path] = (),
    cda_extensions: Iterable[Mapping[str, Any]] = (),
    strict_specializations: bool = False,
) -> dict[str, Any]:
    """Write ``cda.json`` while retaining unresolved nested references."""
    cda = compile_cda(
        templates, model, strict=False,
        strict_specializations=strict_specializations,
        core_definition_paths=core_definition_paths,
        value_set_paths=value_set_paths,
        cda_extensions=cda_extensions,
    )
    write_json(model_dir / "cda.json", cda)
    (model_dir / "cda-assertions.sch").write_text(
        schematron(cda), encoding="utf-8"
    )
    return cda
