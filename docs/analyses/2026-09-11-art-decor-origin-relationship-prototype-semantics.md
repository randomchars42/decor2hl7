# ART-DECOR origin, relationship, and prototype semantics — 2026-09-11

## Scope

This analysis records the implementation and before/after comparison requested
after the local `test-workplace` was refreshed and declared authoritative. It
separates ART-DECOR owner mechanisms from decor2hl7 decisions and deliberately
does not infer semantics from relationship names alone.

The baseline files were captured from the same local code branch before this
implementation. The corrected files were generated from the refreshed local
workspace after a full `fetch --retry-missing`. The comparison therefore covers
both the semantic correction and the dynamic-reference acquisition bug that the
correction exposed.

## Evidence used

The owner evidence is:

1. pinned DECOR-core 2.2.28
   `test-workplace/spec/2026.1.2/validation/decor-core/2.2.28/DECOR.xsd`;
2. ART-DECOR API 3.10.1 `modules/library/util-lib.xqm`, specifically
   `getOriginalForConcept` and `getFullConcept`;
3. ART-DECOR API 3.10.1 `modules/library/util-template-lib.xqm`, specifically
   `getExpandedTemplate` and the editor prototype assembly;
4. the fetched transaction, project evidence, templates, terminology, and
   closure under `test-workplace/spec/2026.1.2`; and
5. the generated model, CDA model, proposal, audit, and conformance artifacts
   under
   `test-workplace/model/2026.1.2/notaufnahmeregister--60`.

DECOR.xsd defines object relationships as implicit, unchecked hints and
enumerates `REPL`, `SPEC`, `GEN`, `COPY`, `ADAPT`, `EQUIV`, `VERSION`, `BACKWD`,
and `DRIV`. `INHERIT` and `ORIGINAL` are not relationship types in this enum.
The formal concept-origin constructs are the XML elements `inherit` and
`contains`; `originalId` is metadata in compiled responses.

## Owner mechanisms implemented

### Concepts

`getOriginalForConcept` recursively follows only `inherit` or `contains` and
requires a unique referenced concept. `getFullConcept` distinguishes the
terminal original from the stored/current concept: semantic properties and
associations come from the original, stored descendants come from the current
concept, and transaction use supplies cardinality.

The compiler now mirrors that split:

- `inherit`, `contains`, and `originalId` are the only formal-origin edges;
- the terminal original supplies name, description, datatype/value domain, and
  semantic associations;
- the selected concept retains identity, path, short name, and transaction
  cardinality;
- `contains` grafts only the stored descendants of its resolved referenced
  concept; and
- every generic `relationship:<TYPE>` remains a direct, non-recursive,
  non-executable review edge.

There is no generic `ADAPT` operation. In particular, the code no longer reads
ADAPT as “copy the referenced concept then override local leaves.” The owner
implementation exposes no such compilation algorithm or relationship
precedence order.

### Compiled terminal-original SPEC

`getFullConcept` can emit a synthetic `relationship type="SPEC"` pointing to
the terminal original when an indirect formal origin means that the original
is not adjacent. That output is not ordinary SPEC inheritance.

For a missing literal `contains` alias, decor2hl7 resolves in this order:

1. exact literal `contains` target;
2. exact compiled `originalId`; then
3. one synthetic terminal-original SPEC whose effective date, dataset id,
   dataset effective date, project prefix, and concept type corroborate the
   adjacent formal `contains` metadata.

The third step is a bounded repair for the compiled representation. An ordinary
SPEC, ADAPT, EQUIV, COPY, VERSION, or other relationship cannot graft a subtree.

### Templates

`getExpandedTemplate` recursively expands executable `include`/`contains`
structure. It does not recursively execute template relationships. The editor
code selects the first SPEC relationship as a prototype that supplies potential
elements and attributes to activate while editing.

The CDA compiler therefore:

- builds reachability only through direct selected templates, `include`,
  `contains`, and reviewed extensions;
- compiles the stored child template as the executable constraint tree;
- never fills omitted child nodes or properties from SPEC, VERSION, COPY, or
  another relationship;
- fetches the first SPEC and its hard dependencies as analysis/prototype
  evidence;
- compares matching explicit child/prototype nodes for weakening diagnostics;
  and
- reports an unavailable prototype separately and non-fatally.

DEC-028 remains a decor2hl7 reviewed configuration mechanism: it may select one
exact sibling branch proved by the first SPEC prototype, but only when the
mapping explicitly asks for it. The refreshed reference mapping does not enable
the medication branch overlay.

### Dynamic references

An undated/dynamic request must be resolved and frozen by its direct ART-DECOR
endpoint. A dated object embedded in another analysis response no longer
satisfies that request. Exact dated requests may still use the identical
embedded revision. This corrected several previously incomplete value domains
after `fetch --retry-missing`.

### No indirect relationship promotion

Marking the direct association candidate review-only was insufficient. Two
indirect compiler paths also had to be closed:

- contextual leaf matching now traverses labels only through formal origins,
  producing `FORMAL_ORIGIN_LABEL(...)`, never through relationships; and
- a relationship-blocked candidate cannot locate a template for a generated
  semantic transform.

Generated Schematron support already respected the relationship block. The
repeat-occurrence fallback was also restricted to the ordinary payload target
pool so removing a relationship candidate cannot promote document plumbing such
as `realmCode`.

## decor2hl7 decisions that remain

The following are explicit project rules, not owner-defined ART-DECOR
relationship semantics:

- the fully corroborated terminal-original-SPEC repair described above;
- DEC-015 projection of a formal static association to one unique active
  CDA/RIM owner-particle slot;
- DEC-028 reviewed sibling-branch selection;
- non-fatal prototype availability and explicit weakening diagnostics;
- candidate scoring, datatype/occurrence admissibility, exact-name and
  exact-ValueSet bridges, and other mapping-proposal rules; and
- conversion of a coded enumeration to `negationInd` only when its complete
  non-unknown domain is exactly one positive and one negative state, optionally
  plus unknown. Multi-valued clinical domains are not collapsed to polarity.

These rules are named as compiler evidence or decisions rather than being
presented as meanings of ADAPT, SPEC, EQUIV, COPY, or VERSION.

## Authoritative fetch/build result

The completed fetch closure contains 172 build resources and 518 evidence
resources. It reports 498 resolved/cached, 21 optional missing, one waived, no
unavailable, no partial, and no errors. The remaining degraded terminology is
ValueSet `1.2.276.0.76.11.53` (dynamic and dated views) and its waived DIVI
CodeSystem `1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`.

The build remains usable but degraded. Six unavailable first-SPEC prototypes
are informational; there are no unresolved executable templates. The two
constraint diagnostics are explicit child/prototype weakening comparisons.

The separate full conformance report remains failed because DECOR-core
Schematron applied to the broad source project extract reports 381 errors,
1,780 warnings, and 536 information messages. Template-validator generation is
degraded with 88 messages, 57 outside the selected document closure, but its
executable probe passes. These results neither authorize relationship execution
nor add prototype constraints to the CDA model.

## Before/after structure

| Measure | Baseline | Corrected | Difference |
|---|---:|---:|---:|
| Dataset fields | 120 | 120 | 0 |
| Dataset groups | 57 | 57 | 0 |
| Reachable CDA templates | 311 | 119 | -192 |
| CDA targets | 36,015 | 31,289 | -4,726 |
| Renderable targets | 29,390 | 29,159 | -231 |
| Writable value targets | 27,199 | 26,974 | -225 |
| CDA elements | 9,667 | 9,607 | -60 |
| CDA attributes | 22,601 | 22,430 | -171 |
| Assertions | 13 | 12 | -1 |
| Constraint diagnostics | 3 | 2 | -1 |
| CDA datapoints | 97 | 88 | -9 |
| Unresolved executable templates | 1 | 0 | -1 |
| Unresolved editor prototypes | 0 | 6 | +6 |

The dataset field and group key sets are identical. Twenty-four fields differ
only in compiled terminology/association content: dynamic value sets are now
frozen from direct endpoints, and association scopes now distinguish
`selected-concept`, `original-concept`, and `related-concept`. One group differs
only in the explicit medication `contains_resolved_to` and
`contains_resolution` provenance.

The large CDA reduction is expected: relationship parents are no longer
reachable executable templates and their omitted constraints are no longer
merged into stored child templates.

## Generated mapping comparison

The baseline proposal selected 94/120 fields. The corrected proposal selects
85/120 fields (87 leaves because two fields have compound mappings). The
separately reviewed `mapping/cda-mapping.json` still selects 98/120; it is not
silently rewritten from the generated proposal.

Ten baseline fields are no longer generated:

| Field | Baseline dependence |
|---|---|
| Final diagnosis free text | `SPEC → TA_VERSION` |
| Final diagnosis primary ICD-10 | `SPEC → TA_VERSION → Schematron` |
| Admission time | `SPEC → inherit^-1 → TA` |
| Medication route | `SPEC → STATIC_ASSOC → CDA_RIM_SLOT → Schematron` |
| Medication dosage narrative | `SPEC → STATIC_ASSOC → CDA_RIM_SLOT → Schematron` |
| Medication product code | `SPEC → SPEC^-1 → STATIC_ASSOC → CDA_RIM_SLOT` |
| Medication product name | `SPEC → inherit^-1 → STATIC_ASSOC → CDA_RIM_SLOT` |
| First physician contact time | `SPEC → inherit^-1 → TA` |
| Postal code | contextual label reached through SPEC/ADAPT neighbours |
| Patient identifier | `SPEC → inherit^-1 → TA` |

All ten losses depended on a generic relationship, directly or through a label
neighbour. Each remains visible where a concrete review candidate exists; none
is executable solely from that evidence.

One mapping is newly generated:

- insurance relationship identifier maps to the active payer
  `associatedEntity/id` through
  `originalId → inherit^-1 → STATIC_ASSOC → CDA_RIM_SLOT`.

This gain contains only formal-origin edges and the DEC-015 unique structural
projection. It is supported by the fetched artifacts, but the final projection
is still a documented compiler rule rather than a direct active-template
association.

Eleven retained selections have changed serialized targets or evidence. Most
are the same active payload with prototype-derived target aliases removed or
with stronger direct ValueSet/name evidence after the complete fetch. Boolean
statement fields may now use an explicit child `negationInd` instead of
prototype-derived structural presence. No retained multi-valued code is reduced
to `negationInd`; a regression test covers this boundary.

## Medication result

The Medikamentöse Therapie subtree remains 25 item datapoints under eight named
groups. The count is unchanged because the formal `contains` still resolves to
concept `2.16.840.1.113883.3.1937.777.75.2.1.482` and grafts that concept's
stored descendants. It does not rely on ADAPT or ordinary SPEC semantics.

The generated medication mapping changes from five fields to one:

- retained: dosage `Sequenznummer → Medikation.sequenceNumber`;
- review-only/not generated: product name, product code, dosage narrative, and
  route, because their paths crossed generic relationships.

The reviewed mapping still contains those five explicit choices against the
simple medication branch. That is a policy/configuration distinction, not
evidence that the proposal may treat relationships as formal origins.

## Supersession

This analysis supersedes the compiler-semantics and mapping-count conclusions
in the earlier 2026-09-11 medication analyses and the relationship-as-identity
parts of `2026-09-06-association-identity-lineage.md`. Their historical source
inventories remain useful; their earlier executable relationship assumptions do
not describe current behavior.
