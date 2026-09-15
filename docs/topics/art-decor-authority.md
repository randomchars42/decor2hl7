# ART-DECOR authority and rule composition

This page answers which ART-DECOR constructs define executable behavior and
where decor2hl7 deliberately supplements them. The core principle is that owner
constructs keep their owner-defined meanings; a local decision may add a
separately identified rule but may not reinterpret an owner construct.

Related decisions: DEC-003, DEC-026, DEC-027, DEC-028, DEC-031, DEC-037, and
DEC-039.

## Owner rules for dataset concepts

The selected transaction controls concept selection, transaction usage, and
cardinality. Formal concept `<inherit>` and `<contains>` chains resolve to one
terminal original. The terminal original supplies semantic properties such as
name, description, datatype, value domain, and associations; the current stored
concept supplies descendants; the transaction supplies usage and cardinality.
Revisions and unrelated historical children are never unioned.

An ART-DECOR `<relationship>` is an implicit, unchecked relationship. Its type
(`REPL`, `SPEC`, `GEN`, `COPY`, `ADAPT`, `EQUIV`, `VERSION`, `BACKWD`, `DRIV`,
or another declared value) is retained as provenance, but it does not establish
inheritance, containment, concept identity, or an executable mapping. This
restriction also applies indirectly: relationship-neighbour labels cannot
locate a mapping target or strengthen a candidate into an automatic selection.

Some analysis responses expose an unavailable literal `contains` alias. The
compiler may locate the stored subtree through an explicit `originalId`, or
through the single synthetic terminal-original `relationship type="SPEC"`
created by ART-DECOR's `getFullConcept`, but only when the adjacent formal
`contains` metadata agrees on dataset, project, identity, and revision. This is
a representation repair for the formal origin, not ordinary relationship
semantics.

## Owner rules for templates

Template `<include>` and element `@contains` form the executable recursive
constraint closure. Their wrappers preserve provenance and occurrence identity
but add no XML level.

A template's first `relationship type="SPEC"` is editor-prototype evidence. The
current template compiles from its own stored constraints; omitted prototype
elements, attributes, cardinalities, vocabulary, assertions, and includes are
not inherited. Matching explicit child constraints may be compared with the
prototype and reported when they broaden it. `build --strict-specializations`
turns such a diagnostic into an error.

Dynamic references are resolved through their direct endpoint and frozen to the
returned revision. A dated definition embedded elsewhere does not satisfy a
dynamic request, and another revision never satisfies an exact request.

## Executable owner grammar

The CDA compiler classifies every admitted template-design child before
composition:

- structure: `element`, `attribute`, bounded `choice`, `include`, and context;
- validation: property, vocabulary, text constraints, variables, `assert`, and
  `report`;
- non-executable evidence: examples, descriptions, comments, classification,
  purpose/copyright, FHIR annotations, and relationships;
- prose: free-form `<constraint>` content is retained but not converted into
  invented XPath.

Unknown executable content is fatal rather than silently ignored. Required
vocabulary bindings constrain values; extensible, preferred, and example
bindings remain advisory. Choice bounds, datatype flavours, ranges, lengths,
timestamp precision, assertion polarity, and severity are preserved with their
owner meanings.

ART-DECOR `<example>` fragments are instance illustrations. They never become
fixed values or absent-source defaults. An exact neutral example may contribute
bounded mapping evidence for a discriminator only when target structure,
terminology membership, source-category correspondence, and occurrence
semantics are independently proven.

## decor2hl7 supplements

Local additions remain explicit and exact:

- `config/cda-extensions.json` may attach one exact template to a legal open
  parent slot, or select one exact sibling branch shown by the parent's first
  SPEC prototype. It records transaction, document, parent, element, target
  revisions, multiplicity, and review reason.
- The source catalog may supply exact owner hints, complete package-local
  supplements, absence waivers, or reviewed malformed-identity aliases. Each is
  separately identified and retains provenance.
- `cda-mapping.json` may record a reviewed semantic bridge, structural rule,
  default, intentional null, or site requirement. It cannot change the fetched
  transaction, dataset model, or physical CDA constraint model.

These mechanisms are project policy, not claims about ART-DECOR. Their compiled
provenance uses distinct names such as `reviewed-extension` and
`terminal-original-SPEC`.

## Verification

The executable rules are concentrated in
`compile/transaction.py`, `cda/art_decor.py`, `cda/compile.py`,
`retrieval/references.py`, and `compile/mapping.py`. Regression tests verify
formal-origin resolution, relationship exclusion, prototype diagnostics,
reviewed overlays, example handling, and exact revision behavior.

Open owner or publication questions are listed in
[`../open-boundaries.md`](../open-boundaries.md).
