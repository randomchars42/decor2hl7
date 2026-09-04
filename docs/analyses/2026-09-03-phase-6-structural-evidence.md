# Phase 6: structural reopening, polymorphic time and Schematron evidence

Date: 2026-09-03  
Baseline: local `main` at `a1982fa` (phase-5 implementation at `4473eca`)  
Reference: `test-workplace`, release `2026.1.2`, transaction
`notaufnahmeregister--60`

## Scope and outcome

Phase 6 was evaluated in the order B0, B3, C1, C6. Three changes are useful and
implemented:

1. distinguish structural-container reopening evidence from genuine datatype
   component evidence and search compatible descendants at any depth;
2. expose the concrete XSD branches of the reviewed polymorphic root
   `SXCM_TS`; and
3. retain a bounded subset of the just-generated template Schematron as
   supporting-only mapping evidence.

C6's optional project-level terminology-association ingestion is not
implemented. Its measured contribution is eight group-only associations and
zero field coverage, so the extra precedence/provenance surface is not
beneficial now.

No selected mapping is added by this phase. The accepted reference headline
stays:

```text
Model: 120 datapoints · ✓ mapped 95 dp → 97 leaves · ! suggested 5 dp → 5 leaves · × no target 20 dp · ○ no source 368 leaves
```

## B0 — structural reopening evidence

Before the change, `_unresolved_reason` called any non-writable typed context
with children `datatype_component_available`. All current instances were in
fact structural CDA/RIM classes:

| Context classification | Fields | Groups |
|---|---:|---:|
| `structural` | 19 | 18 |
| `datatype` / `alias` | 0 | 0 |

The audit now emits `physical:structural_container` for those 37 nodes. A true
datatype/alias container retains `physical:datatype_component` and its direct
component list.

For structural containers, `reopens_with` searches writable descendants at any
depth, ranks payload-compatible and explicit ART-DECOR leaves ahead of generic
datatype plumbing, then orders by depth and stable name and caps the result at
20. This is evidence only: it does not enter `_candidates` and cannot create a
selection. Medication quantity gaps now name the active UV subordinate
administration `doseQuantity` and `rateQuantity` leaves directly; analogous
code, text, boolean and timing fields receive type-appropriate descendants.

## B3 — datatype/RIM completeness findings

### 1. `SXCM_TS` polymorphism was missing and is fixed

The pinned CDA datatype XSD defines these direct extensions:

| Root | Concrete direct subtype | Declared parts |
|---|---|---|
| `SXCM_TS` | `IVL_TS` | `low`, `width`, `high`, `center` |
| `SXCM_TS` | `PIVL_TS` | `phase`, `period` |
| `SXCM_TS` | `EIVL_TS` | `event`, `offset` |
| `SXCM_TS` | `SXPR_TS` | `comp` |

`DefinitionIndex` now records reverse XSD extension relationships and abstract
types. A reviewed trigger set in `cda/datatypes.py` contains only `SXCM_TS`;
the existence of an XSD subtype is deliberately insufficient to expand a root
throughout the document.

The reference contains 66 located `SXCM_TS` nodes. Sixty-four are generated
`useablePeriod` plumbing and are excluded. The prohibited outer medication
time remains non-executable. The one mapping-relevant beneficiary is:

```text
UVSubordinateadministration.substanceAdministration.effectiveTime_xsi_type_SXPR_TS.comp
```

It retains `min: 2`, `max: unbounded`, and gains 23 named descendant targets,
including:

```text
…comp_as_IVL_TS.low
…comp_as_IVL_TS.high
…comp_as_PIVL_TS.period
…comp_as_EIVL_TS.event
…comp_as_EIVL_TS.offset
```

The subtype wrapper is transparent in XML. A descendant assignment sets
`xsi:type` on the existing `<comp>` element; two incompatible subtype choices
in one occurrence fail. The `EIVL_TS` event companion requirement is retained
on its dependent descendants. No `useablePeriod_as_*` target is generated.

This opens the physical structure required by the later medication timing rule;
it does not implement that rule or select a source-to-subtype mapping.

### 2. `IVL_TS/@value` is legal

`IVL_TS` inherits the `TS` scalar representation through
`IVL_TS → SXCM_TS → TS`. The writable `@value` shorthand is therefore expected.
The pinned CDA model has no constraint prohibiting it merely because a template
also declares `width`. No compiler exception is added.

### 3. Explicit `width` does not drop inherited children

The draft's premise was disproved against the current generated model. Active
template `1.2.276.0.76.10.4040@2015-09-18` declares a required `width`, but its
open `IVL_TS` also compiles writable inherited `low`, `high`, and `center`
targets at the same physical occurrence. This is the intended `DEC-014` rule:
an explicit child refines that particle but does not close or prohibit omitted
XSD siblings. The remaining Ereigniseintritt question is semantic choice, not a
datatype-expansion defect.

### 4. MRI region remains blocked upstream

The active MRI statement has no `targetSiteCode`, `approachSiteCode`, or other
region-bearing particle. Its only writable clinical value already represents
the performed indicator. No local structural expansion can supply a region
without inventing a profile constraint.

## C1 — generated Schematron constraint evidence

The generated `conformance-validation/include` tree contains 226 template
patterns after excluding `DTr1_*` datatype support and `voc-*` snapshots. The
research census found 14,043 assertions over 5,530 rule contexts; 2,427 contexts
belong to in-closure template owners, and the reviewed owner-plus-trailing-step
matcher reaches 78.2% of those contexts.

`compile/schematron.py` now extracts only:

- required and maximum occurrences;
- fixed values and required attributes;
- ValueSet document references; and
- concrete `xsi:type` choices.

It splits XPath at bracket depth zero while respecting quoted literals, so the
slash in `doc('include/voc-….xml')` is not treated as a path separator. Pattern
identity supplies the owning template; `@see` is never read. The current
normalized/deduplicated reference result is 8,404 constraints, 6,692 of which
cross-reference to compiled targets. This normalized count is lower than the
raw assertion-category census because the same ValueSet or fixed predicate can
occur in both minimum and maximum assertions.

Build order is deliberately:

```text
compile model/CDA → generate exact conformance artifacts
                  → attach current Schematron evidence → mapping analysis
```

When generation does not complete, `cda.json` records the evidence as
unavailable; the mapper never consumes an old include directory. A
`SCHEMATRON_CONSTRAINT` contributor can strengthen only an existing WEAK or
MEDIUM bridge after direct compatibility passes. An empty input candidate set
always produces an empty output candidate set.

`repeat_by_discriminator` may use the attached ValueSet/fixed-code evidence and
unpredicated maximum bounds. Predicate-specific counts are branch limits, not
aggregate repeat limits, and are excluded from the latter calculation. This
distinction preserves the two pupil branches beneath the shared organizer
component.

## C6 — terminology-association audit

The fetched tree contains 4,188 `terminologyAssociation` nodes:

| Parent | Count | Read by the compiler |
|---|---:|---|
| `concept/concept` | 2,729 | yes |
| `concept/valueSet` | 669 | no |
| `decor/terminology` | 643 | no |
| `representingTemplate/concept` | 95 | yes |
| `dataset/concept` | 52 | yes |

Resolving the 643 project-level rows against the selected dataset gives the
funnel `643 → 70 selected subjects → 8 not already compiled`. All eight are
plain code associations on groups. Five affected groups already have placement;
the remaining blood-pressure group fails a physical target gate. Field coverage
therefore changes by zero.

The optional parser extension is deferred. Nested concept associations retain
their current precedence, and inherited-concept association policy remains the
separate later C2 question.

Of the 24 ValueSets bound by selected fields, only CEDIS
`1.2.276.0.76.11.61` is hierarchical. It is a presenting-complaint taxonomy,
not an ordered scale, so no `ordinal` transform is derived.

## Verification contract

Regression coverage includes:

- direct-only evidence for a genuine datatype container;
- deep, compatible reopening evidence for a structural container;
- exact `SXCM_TS` subtypes from the reverse XSD index;
- rendered `xsi:type` on one physical element and no `useablePeriod` branches;
- parsing and target cross-reference for all supported Schematron kinds;
- the guard that Schematron never creates a sole candidate; and
- unchanged reference mapping coverage and existing compound/repetition rules.

No CI workflow is added; verification remains the repository's local
`make check`, reference build, baseline comparison, and reproducibility checks.
