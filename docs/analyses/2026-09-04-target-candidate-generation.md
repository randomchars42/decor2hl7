# Generating reviewable CDA target candidates for unmapped datapoints

Date: 2026-09-04. Repository `0a6250b`. Release `2026.1.2`, transaction
`notaufnahmeregister--60`, reference workspace coverage `95/120`.

Goal: emit a complete CDA. Human review of the remaining datapoints is accepted;
what is missing is the input to that review — a per-datapoint list of physically
admissible CDA leaves, short enough to scan and annotated enough to decide from.

This analysis establishes that the list is generatable from existing compiled
data, gives the measured filter funnel, and reconciles the compiled target
inventory with the endpoints the AKTIN implementation guide presents.

## 1. The inventory already exists

The AKTIN IG document-template page
(`aktin-cda-ig-20260427T185033/tmp-1.2.276.0.76.3.1.195.10.93-…html`) renders a
hierarchical element tree with, per element: name, datatype, cardinality,
conformance, constraint text and a sample instance, plus 31 contained templates.

`cda.json` already holds exactly that, compiled: 25 075 targets carrying `path`,
`datatype`, `min`/`max`, `conformance`, `description`, `template_id`,
`template_display_name`, `value_sets`, `codes`, `locations`, `writable`,
`is_closed` and `non_null_requires`. Nothing has to be scraped from the IG or
re-derived. The problem is filtering and scoping, not acquisition.

## 2. Why no usable list exists today

`_reportable_cda_target` (`compile/reports.py`) is a **coverage-headline**
filter: it produces the `○ no source 368 leaves` term. It excludes every target
flagged `datatype_derived`, which correctly removes ~16 500 datatype plumbing
leaves (`code.originalText.compression`, `code.qualifier.name.nullFlavor`) — but
it also removes **CDA/RIM structural children**, which are legitimate manual
targets.

The insurance case is the clearest instance:
`…195.10.4.associatedEntity.id` is `writable: true`,
`logical_types: ["identifier"]`, one document location — and
`datatype_derived: true`, so it never appears in any generated list.

The data already separates the two cases. Provenance `source` is `cda-rim` for a
RIM structural child and `datatype` for datatype plumbing. Reusing the headline
filter as a candidate filter is the defect; the fix is a second, purpose-built
filter.

## 3. The measured funnel

| Stage | Filter | Remaining |
|---|---|---:|
| 0 | all compiled targets | 25 075 |
| 1 | physically admissible: `writable`, exactly one location, not `prohibited`, not `fixed` / `conditional_fixed`, no `system_value` | 16 966 |
| 2 | payload not plumbing: keep non-derived leaves **and** `source: cda-rim` children; drop `source: datatype`; drop the CDA-infrastructure deny-list; drop already-selected targets | **594** |
| 3 | context scoping: descendants of the datapoint's selected container location (`gap.context.node.locations[0]`) | 15–259 |
| 4 | type compatibility: model `type` against compiled `logical_types` | **median 9, max 34** |

All **20** context-bearing unmapped datapoints receive a non-empty list.

The five that receive none are correctly excluded: secondary ICD-10, the three
medication timestamps and the EIVL offset already *have* a target and are
`runtime_blocked` (`SHARED` / `REQUIRED_COMPANION`). They need a rule, not a
target list.

### 3.1 Genericity must be decided by role, not frequency

A frequency rule ("an element name occurring on ≥20 templates is generic")
was tried and **rejected**: it deletes `hl7:value`, which occurs on 59 targets
precisely because every observation has one, and which is the correct answer for
the X-ray statements. Use a fixed CDA-infrastructure deny-list instead —
`hl7:realmCode`, `hl7:typeId`, `hl7:templateId`, `hl7:languageCode`,
`hl7:setId`, `hl7:versionNumber`, `hl7:confidentialityCode`,
`hl7:priorityCode`, `hl7:reference`, `hl7:statusCode`, `@nullFlavor`,
`@classCode`, `@moodCode`, `@typeCode`, `@determinerCode`,
`@contextControlCode`. This is target-neutral CDA infrastructure knowledge, not
clinical inference.

### 3.2 Presentation: group by contained template, print IG columns

Grouped by contained template, the largest list (X-ray Untersuchungsregion, 34
candidates across ~19 templates) surfaces the right rows at the top of their
groups:

```
Röntgen-Thorax durchgeführt        hl7:observation/hl7:value            CE  1..1  R
Röntgen-Becken durchgeführt        hl7:observation/hl7:value            CE  1..1  R
Röntgen-Extremitäten durchgeführt  hl7:observation/hl7:value            CE  1..1  R
CDA Procedure                      hl7:procedure/hl7:approachSiteCode   CD  0..1  -
```

These are the five reachable fixed-code X-ray statements that
`2026-09-02-seven-active-profile-gaps.md` identified by hand. The generator
reproduces the manual analysis, which is the acceptance test for it.

Per candidate, carry what a reviewer needs to decide: template display name and
OID, path, datatype, cardinality, conformance, `description`, bound value sets,
plus three decision flags already present in the model — `non_null_requires`
(selecting it obliges a companion, `DEC-020`), whether a repeatable ancestor
means an occurrence rule is required, and whether another datapoint already
claims the target.

## 4. Reconciling the IG endpoints with the compiled leaves

The IG shows on the order of a couple of thousand declared endpoints; the
compiler holds 25 075 targets. The difference is **expansion, not divergence**,
and it decomposes exactly.

### 4.1 Layer census

| Provenance | Targets | Shown in the IG |
|---|---:|---|
| `datatype` only | 14 402 | no — the IG prints the datatype name and links its definition |
| none recorded (roots, derived nodes) | 4 634 | n/a |
| `cda-rim` (+`datatype`) | 4 404 | no — RIM overlay under an open template |
| `template` (+ combinations) | ~1 610 | **yes — this is the IG surface** |
| `hl7-datatype-choice` (polymorphic `xsi:type`) | 18 | no — the IG shows the choice, not one row per branch |

Targets carrying an ART-DECOR `element_id`: **5 992**, over 3 724 distinct ids —
the multiplicity being one target per reachable template *revision*
(`@20230130`, `@20170430`) and per contained instance. Of the 18 859 targets
holding a document location, 1 391 are declared.

The four multipliers, in order of size:

1. **Datatype expansion** (`DEC-013`) — every declared element of a complex
   datatype is expanded into its parts, recursively.
2. **CDA/RIM structural expansion** (`DEC-014`) — for an **open** template the
   CDA core overlay supplies every structural child the RIM class permits but
   the template does not declare. This is the conceptually important one: it is
   invisible in the IG and it is what produced the `associatedEntity/id` slot.
3. **Revisions and contained instances** — one target per reachable revision and
   per document location; the IG page shows one revision of one template.
4. **Polymorphic `xsi:type` materialization** (phase 6) — `_as_<TYPE>` and
   `comp_as_IVL_TS` branches.

### 4.2 Narrowing: the declared-set diff

Restricting both sides to what ART-DECOR declares makes them directly
comparable. Over the 128 templates in the selected document closure:

| Measure | Count |
|---|---:|
| `<element>` / `<attribute>` ids declared in the fetched sources | 2 022 |
| distinct element ids present in compiled targets | 2 001 |
| declarations producing **no** compiled target | **24**, in 8 templates |

Inspecting all 24: every one is a fixed structural attribute —
`classCode="PSN"`, `determinerCode="INSTANCE"`, `classCode="ORG"` — on a
sub-entity. They carry a fixed `value`, so the compiler folds them into the
owning node's `fixed` map rather than materializing a separate target. That is
correct behaviour under `DEC-014`, not a loss.

**Conclusion: there are zero genuine losses between the IG's declared endpoints
and the compiled model.** The compiler is a strict superset. Anything a reviewer
sees in the IG is reachable in `cda.json`, and the surplus is the four expansion
layers above.

### 4.3 Keep the diff as a standing check

The comparison is mechanizable and cheap: parse `<element|attribute … id="…">`
per in-closure template from the fetched sources, diff against
`{target["element_id"]}` grouped by `template_id`, and report the difference.
A non-empty result that is **not** a fixed structural attribute is a compiler
defect. Worth wiring as a test alongside `tests/test_closure.py`, since it turns
"does the compiler see everything AKTIN publishes?" into an assertion rather
than a periodic manual audit.

## 5. Where the candidate list belongs

`gap.reopens_with` in `mapping-audit.json` is already this field, only
under-filtered — B0 made it descend for structural containers. Replace its body
with stages 2–4 and add a ranked, template-grouped **"Possible targets
(unproven)"** section per unmapped field in `cda-mapping-details.md`, which is
already the report for exactly this purpose.

Touchpoints: `compile/mapping.py::_gap_classification`, a new candidate filter
beside `_reportable_cda_target` in `compile/reports.py`, and the details
renderer.

## 6. The boundary that keeps this admissible

The list is a **physical admissibility inventory, not evidence**. Nothing is
auto-selected, no candidate becomes a mapping, and the ranking asserts physical
plausibility only. It therefore does not touch `DEC-003`'s prohibition on
inferred clinical semantics, and it does not weaken the two-gate model: it
reports the physical gate's contents so a human can close the semantic gate
deliberately.

It belongs under `DEC-011` as an amendment, with the stage-1–4 filter rules
stated explicitly so any generated list is reproducible and reviewable.
