# Implementation plan: closing the closure and recovering more CDA targets

Status: phases 1–4 landed. Date opened: 2026-09-03.
Baseline commit: `6d3ea59`. Reference workspace: `decor2hl7-test-workspace`
`spec/2026.1.2`, transaction `notaufnahmeregister--60`.

## Progress (as of `main` @ `315087e`)

Commits since baseline: `11b33f6`/`ac7eec5` (EDIS map+merge),
`f9874a0` "Implement closure resolution and expansion phases", `15a52db` "added docs",
`c55bce5` "added immediate plan" (this document), `838bfc1` "Settle the last five
build-degrading closure artifacts" (phase 4), `315087e` "Recognize
reference-declaration identity when adopting a cached artifact".
**205 unit tests pass** (`python3 -m unittest discover -s tests`).

| Item | State | Where |
|---|---|---|
| B2 — DEC-021 EDIS attachments | **done**, `DEC-021` → accepted/verified | `config/cda-extensions.json`, coverage 92 → 95/120 |
| A1 — closure gap analysis | **done** | `docs/analyses/2026-09-03-closure-gap-analysis.md` |
| A2 step 1 (`fetch --retry-missing`) | **done** — recovered nothing from the degrading set | — |
| A2a — honour explicit dataset reference identity | **done** | `retrieval/references.py` (`sourceDatasetEffectiveDate`/`Prefix`) |
| A2b — OID-owner override **mechanism** | **done**; **no cluster entries shipped** (no ART-DECOR project owner found for `…3.2898` / `…17.3.10.1`; documented) | `retrieval/sources.py` (`SourceHints`), `retrieval/resolution.py`, arch rule 18 |
| A2c — retain ordered candidates + attempts as evidence | **done** | `retrieval/fetch.py`, arch rule 18 |
| A3 — reviewed malformed-identity `alias` mode | **done**, `DEC-022` accepted/verified | `retrieval/sources.py`, `sources.json` (2 entries), `retrieval/fetch.py`, `retrieval/artifacts.py`, `tests/test_external_sources.py` |
| A4 — display-evidence reclassification + crawl-vs-build degraded split | **done**, `DEC-010` amended | `retrieval/references.py`, `compile/artifacts.py`, `cli.py` |
| A6 — freeze `$expand` for dynamic/intensional/incomplete ValueSets | **done**, `DEC-013` amended | new `retrieval/expansion.py`, `retrieval/fetch.py`, `compile/terminology.py`, `conformance.py` |
| E1 — repair `[[hl7:supply]` generated XPath | **done**, `DEC-019` amended; validator now `executable: true`, 0 compile errors | `conformance.py` |
| `configuration_notes` in `cda-mapping.json` | **done**, `DEC-011` amended | `compile/mapping.py::_merge_mapping_configuration_notes` |
| A7 — `--fail-on-degraded` flag + `tests/test_closure.py` | **done** — `fetch --fail-on-degraded` keeps the crawl gate, new `build --fail-on-degraded` gates on `build_degraded`; `tests/test_closure.py` pins the 3-item residue, the message ceiling and `complete: true`; coverage-delta guard wired | `cli.py`, `tests/test_closure.py`, `tests/test_cli.py` |
| Phase 4 — validator scope, A5 waivers, B1, E2 | **done** — `build_degraded` 5 → 3, validator `complete: true`; `DEC-012` accepted, `DEC-010`/`DEC-019` amended | `compile/artifacts.py`, `conformance.py`, `retrieval/sources.py`, `retrieval/sources.json`, `docs/analyses/2026-09-03-closure-phase-4.md` |
| Reference-declaration identity on cache adoption | **done**, `DEC-004` amended + arch rule 14 | `retrieval/fetch.py` (`_payload_matches_request`, `_resolved_effective_date`); `fetch --offline` now reports 0 unavailable and is idempotent; build metrics unchanged |

### Current reference-workspace metrics (after phase 4)

| Measure | Value |
|---|---:|
| Mapped datapoints | 95/120 → 97 leaves (unchanged by phase 4) |
| Suggested / no-target | 5 / 20 |
| Validator | `executable: true`, **`complete: true`**, 0 compile errors, 3 generation messages (was 65), all outside the selected closure |
| Build diagnostics | `status: degraded`; `crawl_degraded: 56`, **`build_degraded: 3`** |

The 5 phase-3 `build_degraded` items and their phase-4 disposition
(evidence in
[`docs/analyses/2026-09-03-closure-phase-4.md`](docs/analyses/2026-09-03-closure-phase-4.md)):

1. `valueset:1.2.276.0.76.11.53@2015-11-17` — AKTIN; **still degraded**. Bound on
   a selected field; expansion blocked by item 4. Enumeration stays
   non-executable.
2. `valueset:2.16.840.1.113762.1.4.1021.30@2013-01-31` — **scoped out**. Genuinely
   empty upstream (VSAC codes only as an HTML table in `<desc>`), and reached
   only by rules on `template:2.16.840.1.113883.10.20.22.4.16`, which holds no
   document location in the selected AKTIN document.
3. `valueset:2.16.840.1.113762.1.4.1099.12@2018-07-02` — **scoped out**, same
   reason; the ART-DECOR record carries no members at all.
4. `codesystem:1.2.276.0.76.3.1.195.5.53@2019-12-30` — **waived**. Published
   nowhere on the server (cross-project lookup 404; 404 in all eight candidate
   projects) and in no located DIVI/HL7 Germany publication, so no builtin is
   possible. Stays degraded.
5. `template:2.16.840.1.113883.10.20.1.53@2005-09-07` — **waived**. `ccd1-` is the
   only publisher and holds only `@2007-04-01`, which must not substitute it.
   Verified that the SPEC omission is scoped: both children still compile and
   stay located.

The near-term ordering and remaining code changes are in
[**Implementation instructions**](#implementation-instructions) at the end.

## Purpose and scope

This plan lists work that can be done **inside this repository**: code changes,
research into which external artifacts exist and where they can legitimately be
obtained, reviewed catalog/config entries, and new reviewed mapping rules.

Out of scope, and never a step here:

- editing ART-DECOR project definitions, associations, containment, cardinality
  or terminology upstream;
- waiting for AKTIN/HL7 Germany to publish a missing association or template and
  treating that as a deliverable.

Where a field can only be resolved by an upstream change, this plan either finds
a reviewed local mechanism that already exists for that situation (`DEC-012`
builtin/waiver, `DEC-021` extension attachment, a new reviewed carry-forward
rule) or records the field as **blocked upstream** with the exact evidence that
would reopen it, and stops there.

Every semantic step below must keep the target-neutral boundary: no
German/English path heuristic, no template-OID table, no inferred clinical
relationship. This is the same bar every accepted `DEC-*` mechanism has met.

## Baseline history

`6d3ea59` (pre-work): 92–93/120 mapped; closure `degraded` with 21 degrading
resources; validator `executable: false`, 65 generation errors + 2 XPath compile
errors.

A1 (`docs/analyses/2026-09-03-closure-gap-analysis.md`) established the 21 split
into **G1** (6 code systems included only under non-code value domains of
*unselected* concepts → reclassify), **G2** (~9 in inactive C-CDA/IHE/VSAC
branches → `$expand`/reclassify/waiver), **G3** (`1.2.276.0.76.3.1.195.5.53`,
genuinely active AKTIN), **G4** (`1.0.3166.1`), plus **S1**
(`template:…10.20.1.53@2005-09-07`), **S2** (datasets `…2.6.60.3.1.2` / `.3`),
**S3** (IHE ValueSet `1.3.6.1.4.1.19376.1.3.11.11`).

After phases 1–3 (see [Progress](#progress-as-of-main--315087e)): 95/120 mapped;
`build_degraded: 5`; validator `executable: true`, 3 generation messages. The
G1/G4 reclassification landed; G2 mostly moved to `crawl_degraded` only; the
remaining 5 are the concrete `build_degraded` list above.

## Two gates (recap)

An executable mapping needs both:

- **Physical gate** — a unique, writable, non-prohibited leaf at an active
  document location with executable datatype/occurrence behaviour.
- **Semantic gate** — a formal association, fixed discriminator, exact
  terminology relationship or explicit reviewed rule connecting the source
  meaning to that leaf.

Workstreams A and B widen the physical gate; C, D widen the semantic gate; E and
F are supporting infrastructure.

---

## Workstream A — close the ART-DECOR retrieval closure

Goal: drive `build_degraded` to empty and the validator to `complete: true`
without inventing content or substituting revisions. Phases 1–3 took the
original 21 degrading resources / 65 validator errors down to `build_degraded: 5`
/ 3 validator messages; phase 4 clears the rest.

### A1. Classify every missing resource — DONE

Completed in
[`docs/analyses/2026-09-03-closure-gap-analysis.md`](docs/analyses/2026-09-03-closure-gap-analysis.md);
summarized in [Baseline history](#baseline-history) above. Degrading groups:
**G1**/**G2**/**G3**/**G4** (code systems), **S1** (`template:…10.20.1.53@2005-09-07`),
**S2** (datasets `…2.6.60.3.1.2` / `.3`), **S3** (IHE ValueSet
`1.3.6.1.4.1.19376.1.3.11.11`).

### A2. Re-probe settled failures and fix reference-identity resolution

- **Step 1 — done.** `decor2hl7 fetch --retry-missing` recovered nothing from
  the 21 degrading resources (only the B2 attachment templates came back).
- **S2 fix** (code): honour an explicit `datasetEffectiveDate` + `prefix` on a
  dataset reference instead of requesting `@dynamic`; then retry `…2.6.60.3.1.2`
  / `.3`. Detailed steps in [Implementation instructions § A2a](#a2a).
- **Cluster hints** (config + small code): add an OID-prefix → project owner
  override so `2.16.840.1.113883.3.2898` and `2.16.840.1.113883.17.3.10.1`
  resolve (no owner in `artifact-owners.json`, absent from
  `project-evidence.xml`); retry recovers 14 evidence-tier templates.
  [§ A2b](#a2b).
- **Resolution trace** (code): record per-artifact `resolution_attempts`
  (ordered projects tried + HTTP status) in the manifest and `closure.json`, so
  future triage is decidable from the artifact. [§ A2c](#a2c).
- Acceptance: every remaining `known missing` item has a recorded resolution
  trace and lands in G1–G4 / S1 / S3 or a reasoned waiver.

### A3. Reviewed malformed-identity normalization catalog — DONE (`DEC-022`)

For the two confirmed malformed OIDs (`…1138836.96` → `…113883.6.96`;
`…1133883.17.3.10.1.34` → `…113883.17.3.10.1.34`). Detailed steps in
[Implementation instructions § A3](#a3-impl).

- Extend `retrieval/sources.json` (schema in `retrieval/sources.py`,
  `SOURCE_MODES`) with a third mode, `alias`, mapping a **known-malformed
  requested identity** to the corrected identity plus a mandatory `reason` and a
  human sign-off marker. For `…1138836.96` the corrected identity
  (`…113883.6.96`, SNOMED) is already fetched and cached in the same run, so the
  alias only has to reuse that record.
- `fetch.py` applies an `alias` before resolution; the stored artifact keeps
  **both** the requested (malformed) identity and the resolved identity, exactly
  as `DEC-004` already requires for requested-vs-resolved identity. The manifest
  records `identity_corrected: true` with the reason.
- This is not "fixing ART-DECOR": the upstream definition is untouched; the
  repository carries a reviewed local correction, visible and revertible.
- New decision record: `DEC-022 — Reviewed correction of malformed upstream
  artifact identities`. Implementation touches `retrieval/sources.py`,
  `retrieval/fetch.py`, `tests/test_external_sources.py`.
- Acceptance: `2.16.840.1.113883.6.96` (SNOMED) and
  `2.16.840.1.113883.17.3.10.1.34` resolve; `closure.json` shows the correction
  provenance; a bogus alias without a reason is rejected.

### A4. Role reclassification + crawl-vs-build degraded split — DONE (`DEC-010` amend)

All 17 degrading code systems carry role `expansion-support`
(`retrieval/artifacts.py:25`), assigned by `references.py:190` to **every**
`<include codeSystem>`, and `crawl_build` recursively closes those from every
contained concept whether or not it supplies a selected datapoint. Two
refinements (detailed in [Implementation instructions § A4](#a4-impl)):

- **references.py**: do not emit `expansion-support` for an `<include
  codeSystem>` when the enclosing `<valueDomain>` is not `type="code"`, or when
  the same list already carries inline enumerated `<concept>`/`<exception>`
  members (`DEC-016`: the enumeration is the executable domain). Emit
  `display-evidence` instead. Clears G1.
- **compile/artifacts.py::write_build_diagnostics**: report a **crawl-degraded**
  set (informational) separately from a **build-degraded** set (expansions the
  compiler actually needed for a selected mapping or the generated validator).
  Only the second sets `status: degraded`. Narrows G2 to genuine active
  bindings; resolves G4.
- Cross-check `compile/terminology.py` `formal_terminology.status`
  (`bound` / `unconstrained` / `logical` / `unbound` / `unresolved`, `DEC-016`).
- Acceptance: `degraded_resources` drops to the code systems that genuinely
  block an intensional expansion of a selected/active binding (expected G3 plus
  at most G4 and part of G2); the rest move to `optional_references`.
- Decision-record impact: amend `DEC-010` with the display-vs-expansion and
  crawl-vs-build refinements (add `DEC-023` if the reviewer prefers a new ID).

### A5. Extend the DEC-012 builtin/waiver catalog — DONE (`DEC-012` accepted)

For the G2/G3/S1/S3 residue that survives A2–A4 and A6, where content genuinely
cannot be crawled.

- **builtin** (small, redistributable, reviewed, checksum-pinned — like the
  existing `codesystem:1.2.276.0.76.5.401` metastasis table): only for code
  systems that are (a) small, (b) needed for an intensional expansion that a
  selected mapping or the validator actually uses, and (c) redistributable.
  Likely candidates after A1: `1.0.3166.1` country subset actually referenced,
  HL7 v2 table `2.16.840.1.113883.12.292` if small. Each needs a documented
  provenance URL, license note and `sha256`, materialized under
  `retrieval/external/`.
- **waiver** (settled absence, cited, keeps the build honestly degraded — like
  the existing IHE split-dose waiver): for large proprietary terminologies
  (SNOMED, RxNorm, UNII, LOINC-coded sets) and for
  `1.2.276.0.76.3.1.195.5.53@2019-12-30`. A waiver never becomes `ok` and never
  satisfies a `required` structural dependency.
- Do **not** build a generic scraper or a `download`/`fhir`/`mediawiki` fetch
  mode speculatively; add one only if A1 shows a concrete required artifact that
  a specific, licensed, reviewed source can supply (`architecture.md`,
  "Provisional external artifact catalog").
- Decision-record impact: `DEC-012` moves from `open`/`partial` toward
  `accepted` once the catalog rules and each concrete entry are reviewed. This
  plan supplies the concrete entries and the "when may an external artifact
  satisfy a required dependency" rule that `DEC-012` currently lacks.

### A6. Value-set expansion for dynamic and enumerated bindings — DONE (`DEC-013` amend)

The highest-yield closure item: the 65 validator errors and most blocked enum
mappings are "ValueSet contents missing" while the ValueSet **definition** is
cached. Detailed steps in [Implementation instructions § A6](#a6-impl). Root
causes, confirmed in A1:

- **Expansion only requested for `<include>` intensional sets with a resolved
  date** (`fetch.py:1231`). ValueSets bound `dynamic` never get an `$expand`.
- **`_valueset_complete` (`fetch.py:162`)** returns `True` for any set with one
  inline `concept`/`exception`, so a partly-inline set with an unresolved
  `<include>` passes as complete.
- The last crawl emitted **no** `requesting expansion` lines at all.
- **`2.16.840.1.113883.1.11.15933` (HL7 ActStatus)**, ~10 rules — small standard
  set, strong `builtin` candidate or direct `$expand`.

Code: `retrieval/fetch.py`, `retrieval/api.py::valueset_expansion_url` (exists),
`compile/terminology.py` (`accepted_values`), `conformance.py` (validator
generation input).

Acceptance:

- `validator-manifest.json` `generation_messages` count drops from 65 toward 0;
- `mapping-audit.json` gains executable `VALUE_SET_ENUM` mappings for fields
  currently blocked as "unavailable or partly expanded binding is explicitly
  incomplete" (`architecture.md`, "Artifact and terminology contracts");
- an unavailable expansion is still explicitly incomplete, never silently
  downgraded to logical labels (`DEC-003`, `DEC-016`).

### A7. Closure regression guard — DONE

- Add a test (extend `tests/test_conformance.py` / a new
  `tests/test_closure.py`) that pins the expected degraded-resource set for the
  reference snapshot and fails when it grows.
- Add a `decor2hl7 fetch` summary line and non-zero exit option
  (`--fail-on-degraded`) for CI use.

---

## Workstream B — widen the physical gate

### B1. Resolve the unresolved `SPEC` target — DONE (waived; omission verified scoped)

`template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` is an unresolved
`SPEC` parent (`build-diagnostics.md`, "Unresolved CDA template references"). Per
A1 it is the SPEC parent of `1.3.6.1.4.1.19376.1.5.3.1.4.7.2` (IHE Medications)
and `1.2.276.0.76.10.4025` (German Material) — the **medication branch** — so
its omitted constraints may be hiding the product-form / ingredient slots that
are currently "no target". The `@2007-04-01` revision from `pmp-` is cached; the
exact `2005-09-07` revision is absent.

- A1/A2 first attempt to fetch the exact revision (original HL7 CCD 1.0 "Product"
  template; it may be in an HL7 / CCD ART-DECOR project). It must not be
  satisfied by `@2007-04-01` (`DEC-004`).
- If genuinely absent: record a `waiver` (A5) **and** verify with
  `cda/compile.py` that `SPEC` refinement degrades safely — the child template
  must still compile from its own constraints plus CDA/RIM expansion, not vanish.
  `DEC-010` says a missing auxiliary revision is a degraded omission, not fatal,
  as long as the representing document template itself is present; confirm the
  omission is scoped to the refinement and add a regression test.

### B2. DEC-021 extension attachments for stranded exact entries — DONE

Three reviewed `config/cda-extensions.json` attachments for the EDIS entries
(`1.2.276.0.76.3.1.195.10.85` / `.86` / `.87`, codes `FLN-134/135/136`)
attached to the open Addendum section `1.2.276.0.76.3.1.195.10.73`. `fetch`
pulls the revisions, `build` validates placement, and the existing equal
terminology associations auto-map them — no new mapping code was needed.
Coverage 92 → 95/120, `check-cda-mapping` passing. Recorded in
[`docs/analyses/2026-09-03-reviewed-edis-attachments-and-decision-review.md`](docs/analyses/2026-09-03-reviewed-edis-attachments-and-decision-review.md).

### B3. Datatype / RIM expansion completeness audit

`DEC-013`/`DEC-014` expansion is broad but the "no target" partition includes
fields where a leaf *should* exist:

- `Ereigniseintritt` — Problem Observation `.10.4040` older revision required
  `effectiveTime/low`; the active revision requires `width` and does not select
  `low`. Confirm `cda/compile.py` `SPEC` handling is correct here (parent-only
  prototype children must be dropped — `architecture.md`) and that this is a
  genuine upstream retirement, not an expansion bug. If it is a bug, fix it; if
  not, it is blocked upstream (C4 offers a partial semantic route).
- MRI `.10.4058` has no `targetSiteCode` child at all — genuine upstream gap,
  blocked; record the exact missing particle.
- Deliverable: a short audit confirming which "structural_only" /
  "no writable leaf" verdicts are correct and which are expansion defects.
  `_unresolved_reason` (`compile/mapping.py:930`) already distinguishes
  `structural_only` / `ambiguous_value_target` / `datatype_component_available`;
  use it to drive the audit.

---

## Workstream C — widen the semantic gate

### C1. Mine the generated transaction Schematron for discriminator and cardinality evidence

`build` already emits `cda-assertions.sch` and the DEC-019 transaction
Schematron. `repeat_by_discriminator` (`compile/structural.py`) currently uses
Schematron **uniqueness** assertions only as *supporting* evidence. The
generated Schematron also encodes, per path: required value sets, fixed codes,
cardinality (`count()` tests), and co-occurrence constraints.

- Add an evidence source that parses the generated Schematron rule contexts
  (`context=/hl7:ClinicalDocument[...]/...`) and cross-references them with
  compiled target `path`/`locations`, producing:
  - confirmed **required** status for a leaf (strengthens a WEAK candidate to
    actionable when combined with an existing association);
  - confirmed **discriminator** value sets for repetition rules;
  - confirmed **mutually-exclusive** branches (helps `<choice>` selection,
    `DEC-017`).
- This is spec-derived, target-neutral, and already computed — it is not new
  clinical knowledge, it is re-using an artifact `build` produces.
- Code: new `compile/` helper consumed by `compile/mapping.py::_candidates`;
  evidence kind `SCHEMATRON_CONSTRAINT`. Decision record: extend `DEC-017` or
  add `DEC-024`.

### C2. Reverse and second-order association traversal

`_graph_and_associations` / `_ta_candidates` (`compile/mapping.py`) follow
`templateAssociation`, `staticAssociations/origconcept`, and lineage edges
(`STRONG_EDGES = SPEC/INHERIT/ORIGINAL/EQUIV/VERSION/COPY`). Gaps to close:

- **Reverse `origconcept`**: an association declared on a *newer or sibling*
  concept that points back at the selected concept's element. Audit whether
  `REVERSE_EDGES` coverage is symmetric.
- **Transitive association through an identity-equivalent concept**: if concept
  A `EQUIV`/`SPEC` concept B and B has a static association, project it to A —
  `DEC-003` allows identity lineage to fill *omitted* properties; an association
  is arguably such a property. This needs a reviewed decision because it widens
  what lineage carries.
- **Association to a legacy constraint whose CDA/RIM slot is now ambiguous**:
  `DEC-015` projection currently requires a *unique* owning particle. Record how
  many associations are lost to ambiguity and whether an occurrence-scoped
  disambiguation (nearest occurrence inside the mapped container) is safe.
- Deliverable: an analysis quantifying how many of the 53 `primary_evidence:
  NONE` fields have *some* association that is currently dropped, and why.

### C3. ConceptMap / crosswalk transform support

For lossy source→formal domain conversions that `DEC-003` says require "an
explicit crosswalk or mapping decision". Concrete target: X-ray
`Untersuchungsregion` — 13 inline logical choices, three with LOINC-looking
synonyms, five reachable fixed-code X-ray statements
(`docs/analyses/2026-09-02-seven-active-profile-gaps.md`).

- Add a declarative `concept_map` scalar transform: an explicit, reviewed,
  code-system-qualified member table `{source label → (code, codeSystem)}` plus
  an `unmapped: nullFlavor="OTH"|error` policy. Stored in `cda-mapping.json`,
  not generated automatically — the maintainer supplies and reviews the table.
- Combined with a structural rule for "one repeated source region selects among
  singleton fixed statements" and coalescing against the already-mapped
  `rontgen*_durchgefuhrt` booleans (which control the same statements'
  `negationInd`).
- Code: `transforms.py` (new primitive, keep it in the small declarative set —
  `known-issues.md` "Transform vocabulary"), `bindings.py`, `validate.py`,
  `compile/mapping.py` (surface the field as `suggested` with a template table
  stub in `cda-mapping-details.md`). Decision record: `DEC-025 — Reviewed
  ConceptMap transform`.
- Non-goal: auto-generating the crosswalk from label similarity.

### C4. Historical-specialization carry-forward rule

For the insurance-relationship identifier
(`hauptkostentrager.versicherungsverhaltnis.identifikation`). The analysis in
`docs/analyses/2026-09-02-seven-active-profile-gaps.md` shows: the active open
template `1.2.276.0.76.3.1.195.10.4` specializes historical
`1.2.276.0.76.10.2022`, which explicitly names `associatedEntity/id`
"Versichertennummern" and has static associations to older concepts; CDA/RIM
expansion supplies the same `associatedEntity/id` in the active template as a
writable repeatable `II`. The active role (`POLHOLD`), active description, unique
physical path and the specialized historical leaf all agree — but `SPEC` is
constraint refinement, not concatenation, so the historical leaf's *meaning* is
not carried forward automatically.

- Propose a reviewed general rule: when (a) an active **open** template
  `SPEC`-specializes a historical template, (b) the historical template has a
  static association from a concept in the selected concept's identity lineage
  to a specific leaf, (c) CDA/RIM expansion exposes the **same** physical path in
  the active template, (d) that path is unique and its occurrence inside the
  already-mapped container is unique, and (e) an identifier root is configured —
  then the historical association projects onto the active physical path.
- This must define identity, path, uniqueness, occurrence and identifier-root
  requirements precisely and must not be a template-OID or German-label
  exception (the analysis is explicit about this bar).
- Decision record: `DEC-026`. Code: `compile/mapping.py` (new evidence kind
  `HISTORICAL_SPEC_CARRY`), `compile/structural.py`, `bindings.py`,
  `validate.py`. Feasibility was already probed manually and the rendering
  mechanics work; the missing piece is the reviewed rule and its guards.
- Expected: +1 datapoint, and a mechanism that generalizes to any
  historical→active open specialization.

### C5. Quantity / unit bridge for dose and rate

Active UV Subordinate administration exposes `doseQuantity` and `rateQuantity`
(`docs/analyses/2026-09-02-residual-mapping-boundaries.md`), but "the current
source normalizer does not preserve unit/range semantics and no unambiguous
bridge exists" for `dosismenge_und_einheit` and `kontinuierliche_gabe_rate`.

- Step 1 (target-neutral model): extend the dataset value model so a source
  value carrying a magnitude + unit (and optionally a range) is normalized to a
  structured quantity, not a string. Touch `data.py` normalization,
  `compile/transaction.py`, `model.json` schema. This is reusable for FHIR
  `Quantity` later (`DEC-005`).
- Step 2 (CDA target): confirm `cda/datatypes.py` `PQ` representation exposes
  `value` + `unit` as a compiled compound with `non_null_requires` (`DEC-020`)
  so a bare magnitude cannot be written without a unit.
- Step 3 (bridge): the two source fields still collide with each other only if
  they target the same leaf; they do not (`doseQuantity` vs `rateQuantity`), so
  once units are preserved a `TERM`/`DESC`/`ARTDECOR_ROLE` candidate below the
  already-mapped administration context may become unique. Re-run the audit.
- Decision-record impact: extend `DEC-013` (value model) with the structured
  quantity; no new clinical decision.

### C6. Terminology-association coverage audit

`_semantic_concept_index` / `_graph_and_associations` build the concept→code
index that feeds `TERM` evidence. Audit against `terminology/` in the transaction
source and `concepts/*.xml`:

- are all `terminologyAssociation` elements (concept↔code, concept↔valueset)
  indexed, including those on inherited concepts?
- are `conceptList` hierarchical relations (`@level`, parent/child) available for
  an `ordinal` transform where a scale is implied?
- Deliverable: gap list + targeted fixes in `compile/mapping.py` /
  `compile/terminology.py`.

---

## Workstream D — structural-rule and transform vocabulary

### D1. Medication timing: interval / frequency structural rule

`docs/analyses/2026-09-02-residual-mapping-boundaries.md`: three source fields
(`startzeitpunkt_der_anwendung`, `stoppzeitpunkt_der_anwendung`,
`dosierung.zeitangabe.zeitpunkt`) all resolve to one atomic `TS` leaf and the
runtime correctly reports `SHARED(3)` instead of guessing.

- Research first: does the effective UV Subordinate administration template
  (`2.16.840.1.113883.10.21.4.6`) expose an `IVL_TS` (low/high) branch and a
  `PIVL_TS`/`EIVL_TS` frequency branch that datatype expansion is not surfacing?
  If yes, this is a B3 expansion fix and the collision dissolves.
- If the template genuinely offers only one atomic timing leaf: this is blocked
  upstream; record it precisely (which datatype branch would be needed) and do
  **not** add a precedence heuristic.
- If expansion surfaces the branches: add/extend a structural rule mapping
  start→`IVL_TS/low`, stop→`IVL_TS/high`, frequency→the repetition branch,
  reusing the existing `for_each` occurrence boundary (`DEC-007`, `DEC-017`).

### D2. Additional scalar transforms — only when a concrete field needs one

The transform set is deliberately small (`identity`, `enum`, `ordinal`, `not`,
`code_system`, `coded_fallback`). Add a primitive only when a specific field's
ART-DECOR representation demands a computation none of these express, and record
it against `known-issues.md` "Transform vocabulary". `concept_map` (C3) is the
one already justified.

---

## Workstream E — validator hardening (DEC-019 fix-forward)

The generated validator is `executable: false` for two reasons; both are
in-repo fixes.

### E1. Malformed XPath match expressions — DONE (`DEC-019` amend)

`validator-compilation-errors.txt`: two `xsl:template/@match` expressions contain
`[[hl7:supply]` (double `[`) from two revisions of one fetched template, causing
`XTSE0340`. The DEC-019 assembler already repairs omitted namespace
declarations; extend `conformance.py` assembly to detect and repair this
specific malformation (unbalanced `[` in a generated match pattern) with a
recorded, reviewed normalization — analogous to A3 but for the publication
transform output. If the malformation originates in the ART-DECOR template
source, the repair is on **our generated stylesheet**, not upstream.

### E2. Terminology completeness gate — DONE (`DEC-019` amended)

E1 landed; validator is `executable: true` with 0 compile errors. `complete` is
still `false` because of **3** generation messages, all for two VSAC medication
ValueSets whose live `$expand` returns a **complete zero-member** result:
`2.16.840.1.113762.1.4.1021.30` (×2) and `2.16.840.1.113762.1.4.1099.12` (×1).
These are `build_degraded` items 2 and 3. Resolve via the A5 disposition below
(confirm they are validator-only on an inactive branch → tighten `build_degraded`
scoping, or `waiver`). Keep `validate-cda` fail-closed on residual
`unresolved terminology`.

Acceptance: `validator-manifest.json` `complete: true`; `validate-cda` runs
against a rendered reference document and reports.

---

## Workstream F — tooling to keep finding targets

### F1. "No-target" and "semantic-gap" reports

Extend `cda-mapping-details.md` / `mapping-audit.json` so every unmapped field
is labelled with which gate fails and the smallest evidence that would reopen it
(the residual analyses do this by hand today):

- `physical_gap: closure` → points at a specific missing artifact / SPEC target;
- `physical_gap: containment` → DEC-021 attachment candidate;
- `semantic_gap: no_association` → C1/C2 candidate;
- `semantic_gap: lossy_domain` → C3 ConceptMap candidate;
- `blocked_upstream` → exact missing upstream construct.

Detailed steps, the concrete label vocabulary and the terminology-status defect
they depend on are in [Implementation instructions § F1](#f1-impl).

### F2. Coverage-delta CI

`mapping_field_delta` (`compile/mapping.py:2958`) already computes a delta, and
`tests/test_closure.py` already fails on a lost mapping. What is missing is a
reported comparison and a CI host. The comparison is reported as the **stable
coverage headline defined in `docs/mapping-documentation-format.md`**, not as a
separate `+n/-n` line: that headline is the reviewed format for build logs and
pull-request comparisons, and a second shape for the same numbers would split
the contract. Regenerating the reference workspace stays part of the release
checklist. Detailed steps in [Implementation instructions § F2](#f2-impl).

### F3. Closure-delta CI

As A7: pin degraded-resource and validator-error counts; fail on growth. Note
that the generated Schematron hashes are not reproducible across machines yet,
so they cannot be pinned until the publication transform's absolute `@see` URIs
are normalized. Detailed steps in [Implementation instructions § F3](#f3-impl).

---

## Sequencing

**Done:** A1, A2 (steps 1, a, b-mechanism, c), A3, A4, A6, E1, B2, `configuration_notes`.

| Phase | Steps | State | Coverage effect |
|---|---|---|---|
| 1 | A3, A4 | **done** (`DEC-022`, `DEC-010` amend) | 0 (closure honesty) |
| 2 | A2a, A2b-mechanism, A2c | **done**; A2b cluster entries deferred (no owner found) | 0 |
| 3 | A6 (`DEC-013` amend) | **done**; 65 → 3 validator messages | 0 this round (blocked enums need the phase-4 residue) |
| 4 | A5 for the 5 `build_degraded` items; S1/B1; E2; A7 finish | **done** — `build_degraded` 5 → 3, validator `complete: true`; B1 opened no medication slots | 0 (quality) |
| 5 (next) | F1–F3 | specified — see [Phase 5](#phase-5--gate-labelled-reporting-and-regression-guards-next); A7 already shipped part of the F2/F3 assertions | 0 (infra) |
| 6 | C1, C6, B3 | not started | opportunistic +n |
| 7 | C5, D1 | not started | up to +4 medication datapoints |
| 8 | C3 (`DEC-025`), C4 (`DEC-026`), C2 | not started | +1 (insurance), +1 (X-ray) subject to review |

## Phase 4 — LANDED

Recorded here as executed; the evidence snapshot is
[`docs/analyses/2026-09-03-closure-phase-4.md`](docs/analyses/2026-09-03-closure-phase-4.md).
The reference workspace now ignores generated `model/`, `mapping/` and `site/`
output, so only `spec/`, `config/` and `test/` are committed evidence there.

Per `build_degraded` item, as planned:

1. **#2 / #3 — VSAC `1021.30` / `1099.12` (zero-member `$expand`).**
   Check `mapping-audit.json` / the generated Schematron: are these consulted by
   a **selected AKTIN field** or only by a validator rule emitted for an
   **inactive** UV-medication template? If validator-only on an inactive branch,
   tighten `compile/artifacts.py` `build_degraded` scoping to exclude validator
   rules whose `context` template is not in the selected closure — this also
   clears E2 (`complete: true`). If genuinely selected, reviewed `waiver`
   (`DEC-012`): a complete zero-member US value set cannot be filled.
2. **#1 + #4 — AKTIN ValueSet `1.2.276.0.76.11.53` + its intension CodeSystem
   `1.2.276.0.76.3.1.195.5.53@2019-12-30` (linked).**
   Retry `$expand` on `.11.53` directly (the server may expand without the local
   CodeSystem). If still unavailable: decide between a reviewed `builtin` of
   `.5.53@2019-12-30` (only if small, redistributable, reviewed — check the
   DIVI/AKTIN publication) or a `waiver` that accepts `.11.53` stays
   `unresolved` and its enum mappings stay non-executable. Update
   `known-issues.md`.
3. **#5 — `template:2.16.840.1.113883.10.20.1.53@2005-09-07` (B1).**
   Research the exact `2005-09-07` revision (original HL7 CCD 1.0 "Product"
   template) in an HL7 / CCD ART-DECOR project; add a source hint + retry. If
   absent: reviewed `waiver` **and** verify in `cda/compile.py` that `SPEC`
   refinement degrades safely for children `1.2.276.0.76.10.4025` (German
   Material) and `1.3.6.1.4.1.19376.1.5.3.1.4.7.2` (IHE Medications) — the child
   must still compile from its own constraints + CDA/RIM expansion. Check
   whether recovering it exposes the medication product-form / ingredient slots
   currently in the "no target" partition (potential coverage gain).
4. **A5 general:** each `builtin`/`waiver` entry gets a provenance URL, license
   note, and (builtin) `sha256`; `DEC-012` moves toward `accepted` with the
   concrete entries and the "when may an external artifact satisfy a required
   dependency" rule.
5. **A7 finish:** point `--fail-on-degraded` at `build_degraded` (currently
   `degraded_resources`); make `tests/test_closure.py` pin
   `build_degraded ⊆ {known 5}` and the validator-message count; wire the
   `tests/fixtures/reference-mapping-audit.json` coverage-delta guard.

Phases 5–8 each need their own reviewed decision and analysis; they were not
started in the phase-4 PR.

Blocked-upstream after all of the above (record, do not force): MRI region
(no region-bearing leaf in the active statement); general event onset (no active
onset statement, no association); secondary ICD-10 cardinality/relationship
(`DEC-009`); any medication field needing an active-profile association that
does not exist.

## Decision-record impact

| New / changed | Subject |
|---|---|
| `DEC-010` amended | display-evidence vs expansion-support; crawl-degraded vs build-degraded; validator rules scoped to the selected document closure |
| `DEC-012` accepted | catalog rules, provenance requirement, the "may satisfy a required dependency" rule and the four concrete entries |
| `DEC-019` amended | validator completeness is a claim about the selected document closure |
| `DEC-013` amend | frozen `$expand` for dynamic bindings (A6); structured quantity (C5) |
| `DEC-022` | reviewed correction of malformed upstream artifact identities |
| `DEC-017` amend or `DEC-024` | Schematron-constraint evidence source |
| `DEC-025` | reviewed ConceptMap transform |
| `DEC-026` | historical-specialization carry-forward rule |

Every step that changes semantics updates its decision entry, the affected
`known-issues.md` item, a regression test and user-facing / generated docs in
the same pull request, per `AGENTS.md` and `.github/pull_request_template.md`.

---

## Implementation instructions

Precise, code-level steps for the near-term phases (1–3). Line numbers are
against baseline `6d3ea59`; re-anchor by symbol name if they have drifted. Every
change ships with its unit test and, where it changes generated output, a
regenerated reference workspace.

### Phase 1 — closure honesty, no ART-DECOR access — LANDED

_Kept for reference. `retrieval/sources.py`, `retrieval/fetch.py`, `retrieval/references.py`, `compile/artifacts.py`, `retrieval/sources.json`, `tests/test_external_sources.py`, `docs/decisions.md` (`DEC-022`, `DEC-010` amend)._

<a id="a3-impl"></a>
#### A3. Reviewed malformed-identity `alias` mode

Goal: a request for a known-typo OID reuses the corrected artifact, keeping both
identities on the record. Files: `retrieval/sources.py`, `retrieval/fetch.py`,
`retrieval/sources.json`, `tests/test_external_sources.py`,
`docs/decisions.md` (`DEC-022`), `docs/known-issues.md`.

1. **`retrieval/sources.py`**
   - Add `"alias"` to `SOURCE_MODES` (line 12).
   - In `load_source_hints`, after the `waiver` validation (line 60-61), add:
     an `alias` entry requires non-empty `alias_of` (the corrected
     `kind:id[@effective_date]` string) and `reason`; reject any `mode:"alias"`
     that also sets `builtin`/`waiver` fields.
   - Add a helper `resolve_alias(want, hints) -> tuple[Want, dict|None]`:
     look up `f"{kind}:{id}@{effective}"` then `f"{kind}:{id}"`; if the hint is
     `mode:"alias"`, parse `alias_of` into a `Want` (kind must match), and
     return `(corrected_want, {"identity_corrected": True,
     "requested_identity": original_key, "reason": hint["reason"]})`.
     Otherwise return `(want, None)`.
2. **`retrieval/fetch.py`**
   - In `_fetch_want` (around line 914, `resolved_want = apply_source_hint(...)`),
     call `resolve_alias` first: `resolved_want, alias_note =
     resolve_alias(want, source_hints or {})`, then `apply_source_hint` on the
     corrected want.
   - When `alias_note` is set: after a successful fetch, write the manifest
     entry under **both** keys — the corrected key with the real payload, and
     the original (malformed) key as `{"status": "alias", "alias_of":
     <corrected key>, **alias_note}`. `_satisfied` / closure role accounting
     must treat an `alias` status on a required key as satisfied (the corrected
     key carries the bytes).
   - In the closure builder (`required_failures`, line 1542), a key whose
     manifest status is `alias` and whose `alias_of` target is `ok` is **not** a
     failure.
3. **`retrieval/sources.json`** — add:
   ```json
   "codesystem:2.16.840.1.1138836.96": {
     "mode": "alias",
     "alias_of": "codesystem:2.16.840.1.113883.6.96",
     "reason": "Upstream OID typo: 1138836 for 113883.6. The corrected SNOMED CT OID 2.16.840.1.113883.6.96 is fetched normally in the same closure."
   },
   "template:2.16.840.1.1133883.17.3.10.1.34": {
     "mode": "alias",
     "alias_of": "template:2.16.840.1.113883.17.3.10.1.34",
     "reason": "Upstream OID typo: 1133883 for 113883."
   }
   ```
4. **Tests**: alias reuse resolves the corrected artifact; both manifest keys
   present; an `alias` entry missing `alias_of` or `reason` is rejected; a
   `known missing` corrected target still degrades (alias does not fabricate).
5. **`DEC-022`** in `docs/decisions.md`; note in `known-issues.md` that the two
   typo OIDs are handled by a reviewed alias, upstream untouched.

<a id="a4-impl"></a>
#### A4. Reclassify display-only includes; split crawl-degraded from build-degraded

Files: `retrieval/references.py`, `compile/artifacts.py`, `retrieval/fetch.py`
(closure keys passthrough), `tests/test_retrieval.py` / `tests/test_core.py`,
`docs/decisions.md` (`DEC-010` amend), `docs/known-issues.md`.

1. **`retrieval/references.py::collect_references`**, the
   `elif tag == "include" and node.get("codeSystem")` branch (line 190):
   - Walk `ancestors` / the current subtree to find the nearest enclosing
     `valueDomain` element and its `type` attribute. Track it on the stack the
     same way `ancestors` is tracked (push `(child, ancestors + (tag,))` already
     exists; also thread the last-seen `valueDomain@type`).
   - Determine `has_inline_members`: does the enclosing `conceptList` /
     `valueDomain` subtree contain a `<concept code=… codeSystem=…>` or
     `<exception …>` element? (Reuse the logic shape of
     `fetch.py::_valueset_complete`.)
   - If `valueDomain@type` is present and not `"code"`, **or**
     `has_inline_members` is true → `add("codesystem", …, role="display-evidence")`.
   - Else keep `role="expansion-support"`.
   - Keep the existing REQUIRED_ROLE-wins dedup (line 79-86) so a code system
     that is *also* a genuine standalone-ValueSet `<include>` elsewhere stays
     `expansion-support`.
2. **`compile/artifacts.py::write_build_diagnostics`** (line ~140):
   - Today `status = "degraded" if unavailable or unresolved else "complete"`.
     Split the inputs: `crawl_degraded` = every closure `degraded_resources`
     entry (unchanged, kept in the JSON for information); `build_degraded` =
     the subset whose OID is actually consulted by the compiler — i.e. a
     `formal_terminology` binding of a **selected** `model.json` field
     (`status in {"bound","unresolved"}`, `DEC-016`) or a value set referenced
     by the generated validator (`conformance-validation/generation-messages.txt`).
   - Set the headline `status: "degraded"` only from `build_degraded`.
   - Emit both lists in `build-diagnostics.json` / `.md` under distinct
     headings ("Unavailable artifacts (crawl)" vs "Unavailable artifacts
     affecting this build").
3. **CLI** (`cli.py:352`, the `if diagnostics["status"] == "degraded"` branch):
   message now reflects `build_degraded` only.
4. **Tests**: a codesystem included only under `<valueDomain type="text">` or
   alongside inline members gets `display-evidence` and is absent from
   `build_degraded`; a codesystem intensionally included by a ValueSet bound on
   a selected field stays in `build_degraded`; the reference snapshot's
   `build_degraded` shrinks to the expected G3 (+ possibly G4/part of G2) set.
5. **`DEC-010`**: append the display-vs-expansion rule and the
   crawl-vs-build-degraded distinction; update `known-issues.md`
   "Package validation exposes upstream conformance gaps" and
   "Provisional external artifact catalog" to cite `build_degraded`.

### Phase 2 — reference-identity resolution and traceability — LANDED (A2b cluster entries deferred)

<a id="a2a"></a>
#### A2a. Honour explicit dataset reference identity

Files: `retrieval/references.py`, `retrieval/fetch.py`, `tests/test_retrieval.py`.

1. **`retrieval/references.py`** — the `<contains datasetId=…>` branch
   (line 118-126) already passes `node.get("datasetEffectiveDate")` and
   `node.get("prefix")`. Verify the `representingTemplate` /
   `sourceDataset` branch (line 146-152) and any `<inherit datasetId=…>` path
   (line 215-223) also carry `datasetEffectiveDate` + `prefix`. Add the missing
   `dataset_effective_date` / `project` kwargs where absent.
2. **`retrieval/fetch.py::artifact_representations`** (via `_requests`,
   line 407) — confirm a `Want` with `effective_date` set produces the exact
   `/dataset/{id}/{effectiveDate}` and `/dataset/{id}/{effectiveDate}/$extract`
   URLs rather than the latest route. If `_requests` drops a non-empty
   `effective_date` for datasets, fix `api.py::artifact_representations`.
3. **Manual check** before coding: `grep -o 'datasetId="2.16.840.1.113883.2.6.60.3.1.[23]"[^>]*'`
   in `spec/2026.1.2/datasets/2.16.840.1.113883.3.1937.777.75.1.2_*.xml` to
   confirm the reference carries `datasetEffectiveDate="2015-11-01T00:00:00"`
   and `prefix="aktin-"` (A1 already saw this).
4. Run `decor2hl7 fetch --retry-missing`; expect `dataset:…2.6.60.3.1.2` / `.3`
   to resolve from `aktin-`. If the `aktin-` project genuinely lacks the
   `2015-11-01` revision, add a `waiver` (§ A5) with that finding.
5. **Test**: a `<contains>` with an explicit dataset date requests the exact
   revision; a `known missing` for the wrong date is not silently satisfied by
   another revision (`DEC-004`).

<a id="a2b"></a>
#### A2b. OID-prefix owner override for unowned clusters

Files: `retrieval/sources.py`, `retrieval/resolution.py`, `retrieval/fetch.py`,
`config/sources.json` (workspace), `tests/test_retrieval.py`.

1. **`retrieval/sources.py::load_source_hints`** — also parse a top-level
   `"oid_owners"` object `{oid_or_prefix: project}` from the bundled and the
   configured file; return it alongside the artifact hints (change the return
   type to a small dataclass or `(hints, oid_owners)` tuple; update callers in
   `cli.py`).
2. **`retrieval/fetch.py::fetch_spec`** — merge the configured `oid_owners`
   into the `owners` map (the "global project directory" dict) that is passed to
   `_candidate_projects` (line 1135-1136), configured entries taking lower
   precedence than a real directory entry but higher than blind probing.
3. **`retrieval/resolution.py::project_owner`** (line 46) already does
   longest-prefix matching over that dict, so a prefix entry
   `"2.16.840.1.113883.3.2898": "<project>"` will be picked up automatically.
4. **Research** the correct owning project for `…3.2898` (looks like a
   Belgian/eHealth or IHE project) and `…17.3.10.1` before adding the entry;
   if unknown, leave the entry out and record the cluster as evidence-only
   (they are non-degrading — S-analysis already says so).
5. **`config/sources.json`** in the reference workspace gets the reviewed
   entries; `fetch --retry-missing` should then pull the 14 templates as
   evidence.
6. **Test**: a configured `oid_owners` prefix routes `candidate_projects` to
   that project first; a real directory entry still wins over it.

<a id="a2c"></a>
#### A2c. Record resolution attempts

Files: `retrieval/fetch.py`, `tests/test_retrieval.py`.

1. In `_fetch_want`, the local `request(project, form, url)` (line 1068) already
   appends to `attempts` on failure. On a **settled miss** (line 743, the
   `"status": "missing"` manifest write) also store
   `"resolution_attempts": [{"project": p, "form": f, "http_status": s} …]`
   from `attempts`, and the ordered `candidate_projects` list as
   `"projects_considered"`.
2. Surface both fields in `closure.json` per degraded/missing key (the closure
   builder already copies manifest fields; add these to the copied set).
3. **Test**: a resource that 404s in project A then resolves in project B
   records both attempts; a `known missing` entry carries `projects_considered`.

### Phase 3 — value-set expansion (the high-value closure PR) — LANDED

_New file `retrieval/expansion.py`; `retrieval/fetch.py`, `compile/terminology.py`, `conformance.py`, `tests/test_closure.py`. `DEC-013` amend._

<a id="a6-impl"></a>
#### A6. `$expand` dynamic bindings; consume frozen expansions

Files: `retrieval/fetch.py`, `retrieval/references.py`, `compile/terminology.py`,
`conformance.py`, `tests/test_conformance.py`, `tests/test_core.py`,
`docs/decisions.md` (`DEC-013` amend), `docs/known-issues.md`.

1. **`retrieval/fetch.py`**, the value-set expansion block (line 1228-1259):
   - Drop the `resolved_date` precondition. Compute
     `resolved_date = _resolved_effective_date(analysis_payload, request_want)
     or "<newest from analysis>"`; for a `dynamic` binding this is the frozen
     newest revision (`DEC-004`).
   - Widen the `intensional` test: request `$expand` when the analysis has
     **any** `<include>` (ref or codeSystem), OR when
     `_valueset_complete(root)` is `False`.
   - Keep the `request_budget` guard and the `expansion_warning` on failure.
2. **`retrieval/fetch.py::_valueset_complete`** (line 162): return `False` when
   the set contains an `<include>` whose referenced code system / value set is
   not itself resolvable from the same document (i.e. a partly-inline set with
   an unresolved include is incomplete).
3. **`retrieval/references.py`** — when a value set is bound `dynamic`, still
   record its frozen `effective_date` on the `Want` so the expansion URL is
   exact and reproducible.
4. **`compile/terminology.py`** — `accepted_values` / `formal_terminology`
   must consume the frozen `expansion` representation when the `analysis` form
   is intensional and incomplete; an absent expansion stays
   `status:"unresolved"` (never falls back to logical labels — `DEC-003`,
   `DEC-016`).
5. **`conformance.py`** — feed the frozen expansions into the validator
   generation inputs (the `terminology_resources` list around line 600-603) so
   `generation-messages.txt` "value set contents are missing" errors drop.
6. **`2.16.840.1.113883.1.11.15933`** — if `$expand` does not resolve it from
   the HL7 project, add it as a `builtin` (§ A5) with provenance from the HL7
   core ValueSet publication.
7. **Acceptance**: `validator-manifest.json` `generation_messages` count → near
   0; `executable`/`complete` reach `true` once E1 also lands; new
   `VALUE_SET_ENUM` mappings appear in `mapping-audit.json`; regenerate the
   reference workspace and update the coverage line in `known-issues.md`.
8. **`DEC-013`** amend: frozen `$expand` for dynamic bindings is part of the
   compiled terminology contract.

### Phase 5 — gate-labelled reporting and regression guards (next)

Scope: F1, F2, F3. Coverage effect 0; this phase buys honest reporting and a
guard that keeps phases 6–8 from silently regressing. No ART-DECOR server
access is required — every question below is decidable from the local archives.

**Already landed, do not redo.** A7 shipped most of the *assertions* that F2/F3
describe: `tests/test_closure.py` pins `build_degraded ⊆ {3 reviewed items}`,
the generation-message ceiling, the `complete` claim and mapped-field
non-regression against `tests/fixtures/reference-mapping-audit.json`; `cli.py`
carries `--fail-on-degraded` on both `fetch` (line 273) and `build` (line 391).

**Three findings that change what this phase has to do**, all verified against
`main` @ `315087e` and the reference workspace:

1. **There is no CI.** `.github/` holds only `pull_request_template.md`; there is
   no `workflows/` directory. F2 and F3 both say "wire it into CI" and there is
   no host to wire into. Creating one is the first decision of the phase, and it
   is not a detail — see [§ F3](#f3-impl) step 1.
2. **`mapping-audit.json` carries no gate labels at all.** `_unresolved_reason`
   (`compile/mapping.py:950`) is computed and stored on the internal detail dict
   at line 2221, but `audit_detail` (line 2862) never copies it out. All 120
   fields persist `unresolved_reason: null`. F1 is therefore "stop dropping the
   labels that exist, then extend them", not "add labels".
3. **The documented coverage headline exists only as Markdown prose.** It is
   composed inline in `reports.py:886-898` and never persisted; the audit
   `summary` holds `field_coverage`/`executable_fields`, none of them in the
   documented shape. F2 needs an extraction before it can compare anything.

<a id="f1-impl"></a>
#### F1. Gate-labelled "no-target" and "semantic-gap" reporting

Files: `compile/transaction.py`, `compile/mapping.py`, `compile/reports.py`,
`tests/test_core.py`, `docs/decisions.md` (`DEC-011` amend, `DEC-013`/`DEC-004`
note), `docs/known-issues.md`, `docs/mapping-documentation-format.md`.

##### Step 0 — resolve `dynamic` value-set bindings (do this first)

`compile/transaction.py:738 _resolve_value_set` returns `{}` for any binding
whose `effective_date` is the literal string `dynamic`:

```python
exact = value_sets.get(_value_set_key(oid, effective)) if effective else None
if exact is not None: return exact
rows = [...]
if not rows or effective: return {}       # "dynamic" is truthy
```

`_value_set_key` (line 57) builds `f"{oid}@{effective}"` and the compiled index
is keyed `id@<frozen date>` only, so `dynamic` is never a key; only a *blank*
date reaches the newest-revision fallback.

Measured consequence: 8 fields carry `formal_terminology.status: "unresolved"`
and **7 of them are false negatives**. `vitalparameter.pupillenweite.
pupillenweite_rechts` binds `1.2.276.0.76.11.49` twice — once
`@2015-11-17T00:00:00`, once `dynamic`. Members resolve fine from the dated ref
(four codes present); the `dynamic` ref lands in `missing_value_sets` and flips
`status` to `unresolved`. The same holds for `…11.44`, `…11.45`, `…11.46`,
`…11.50` and `…11.61`. Only `1.2.276.0.76.11.53` is genuinely unresolved, and it
is the one that actually appears in `build_degraded`.

Fix in `_resolve_value_set`:

```python
frozen = "" if effective.strip().lower() == "dynamic" else effective
exact = value_sets.get(_value_set_key(oid, frozen)) if frozen else None
if exact is not None:
    return exact
rows = [v for v in value_sets.values() if str(v.get("id") or "") == oid]
if not rows or frozen:
    return {}
rows.sort(key=lambda v: str(v.get("effective_date") or ""))
return rows[-1]
```

This is the frozen-dynamic rule A6/`DEC-013` already accepted for `$expand`,
applied to the compiled terminology index. Apply the same normalization in
`_formal_values` (line 749) so members and status agree. `DEC-004` is preserved:
an **explicit** effective date still resolves exactly and never falls back.

Expect `formal_terminology.status` to move `unresolved → bound` for 7 fields
(`{unbound:74, bound:16→23, logical:11, unconstrained:11, unresolved:8→1}`) and
the reference workspace to need regeneration. Test in `tests/test_core.py`: a
field carrying both a dated and a `dynamic` ref to the same OID resolves
`bound`; a field whose only ref names an absent explicit date stays
`unresolved`.

##### Step 1 — persist the reasons that already exist

`compile/mapping.py:2862`, in `audit_detail`, alongside the existing conditional
spreads:

```python
**({"unresolved_reason": detail["unresolved_reason"]}
   if detail.get("unresolved_reason") else {}),
```

##### Step 2 — add the gap classifier

New function in `compile/mapping.py` next to `_unresolved_reason` (line 950):

```python
def _gap_classification(
    path: str,
    detail: Mapping[str, Any],
    field: Mapping[str, Any],
    unresolved_templates: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
```

Return `None` when `detail["selected"]` is set **and**
`field["formal_terminology"]["complete"]` is true. Otherwise emit
`{"gate": …, "kind": …, "reopens_with": [...]}` from inputs that already exist,
first match wins:

| Condition | `gate` / `kind` | `reopens_with` |
|---|---|---|
| `runtime_blocked` starts `SHARED(` or `WEAKER_SHARED_TARGET(` | `semantic` / `shared_target` | competing field paths + the shared target |
| `runtime_blocked` starts `REQUIRED_COMPANION(` | `semantic` / `missing_companion` | the `required_companions` target names |
| `formal_terminology.status == "unresolved"` after step 0 | `terminology` / `closure` | the `missing_value_sets` / `unresolved_includes` request keys |
| context template appears in `cda["unresolved_templates"]` | `physical` / `closure` | the `template:<oid>@<date>` key |
| `unresolved_reason == "structural_only"`, context template is open | `physical` / `containment` | the context template OID (`DEC-021` attachment candidate) |
| `unresolved_reason == "structural_only"` otherwise | `physical` / `no_writable_leaf` | the context target name |
| `unresolved_reason == "ambiguous_value_target"` | `physical` / `ambiguous_target` | the candidate target names |
| `unresolved_reason == "datatype_component_available"` | `physical` / `datatype_component` | the container target + its compiled components |
| `unresolved_reason == "incompatible_value_type"` | `semantic` / `lossy_domain` | model type + CDA logical types (C3 candidate) |
| `unresolved_reason == "no_semantic_evidence"`, context present | `semantic` / `no_association` | the context target name (C1/C2 candidate) |
| nothing above, no context | `blocked_upstream` / `no_candidate` | `[]` |

Do **not** derive `blocked_upstream` from absence in general: reserve it for the
"no context, no candidate" case and let the maintainer promote a verdict. The 13
datapoints catalogued as having no plausible leaf are the ones that should land
there.

Call it in the loop at `compile/mapping.py:2219` — where `_unresolved_reason` is
already assigned — so groups and fields both get one, and spread the result into
`audit_detail`.

Ground truth for the first run: of the 25 currently unmapped fields, expect
3 × `shared_target` (the medication timestamps, `SHARED(3)`), 1 ×
`missing_companion` (the EIVL offset), 1 × `shared_target` (secondary ICD-10,
`WEAKER_SHARED_TARGET`), and 20 × `no_writable_leaf` / `no_association` (all
context-only with no alternatives).

##### Step 3 — summary rollup

In the audit `summary` dict (`compile/mapping.py:2905`):

```python
"gaps": Counter(f"{g['gate']}:{g['kind']}" for g in gaps),
```

##### Step 4 — surface it in the details report

`compile/reports.py:547 _review_reason` already returns good prose; keep it. Add
one machine-readable line after the existing `**Reason:**` block of each field
section in `cda-mapping-details.md`:

```markdown
**Gap:** `physical:no_writable_leaf` — reopens with: `Medikation.substanceAdministration`
```

One physical line, per the format document's compactness rule. Add the
vocabulary to `docs/mapping-documentation-format.md` under "Rules and
reasoning".

##### Step 5 — decision record and tests

Amend **`DEC-011`** (`docs/decisions.md:231`): `mapping-audit.json` carries, for
every datapoint that is not both selected and terminology-complete, the failing
gate and the smallest evidence that would reopen it. No new `DEC-*` id is
needed. Add the frozen-`dynamic` resolution as a note under `DEC-013` with the
`DEC-004` exactness caveat. Update `docs/known-issues.md` "Remaining
active-profile mapping boundaries" to cite gap keys rather than restating the
prose. Tests in `tests/test_core.py`: one synthetic field per `kind`, plus an
assertion that a fully mapped, terminology-complete field emits no `gap` key.

<a id="f2-impl"></a>
#### F2. Coverage guard reported as the documented headline

The guard reports the **stable coverage headline already specified in
`docs/mapping-documentation-format.md`** ("Coverage headline and trees"), which
that document describes as suitable for build logs, pull-request comparisons and
chat summaries. It does not introduce a second `+n/-n` summary shape for the
same numbers.

Files: `compile/reports.py`, `compile/mapping.py`, `cli.py`,
`tests/fixtures/reference-mapping-audit.json`, `tests/test_closure.py`,
`Makefile`, `README.md` / `Project-decor2hl7.md`.

1. **Extract the headline.** `reports.py:868-898` computes the five numbers
   inline inside `render_cda_mapping_markdown`. Lift them out:

   ```python
   def coverage_headline_counts(model, cda, mapping, audit) -> dict[str, int]:
       """datapoints, mapped_datapoints, mapped_leaves, suggested_datapoints,
       suggested_leaves, no_target_datapoints, no_source_leaves"""

   def format_coverage_headline(
       counts: Mapping[str, int], *, markdown: bool = True,
   ) -> str:
   ```

   `render_cda_mapping_markdown` calls both with the bold markers on, so
   generated `cda-mapping.md` does not change by a byte — assert exactly that in
   a test. `markdown=False` drops the `**` for log and CI use. Note that
   `_cda_coverage_tree` currently returns `no_source_count` as a side value, so
   either thread it through `_cda_mapping_analysis` or recompute it in
   `coverage_headline_counts` from `_coverage_index` + `_reportable_cda_target`.
2. **Persist the counts.** Add `"coverage_headline": counts` to the audit
   `summary` (`compile/mapping.py:2905`). This is what makes the line comparable
   between runs without parsing Markdown.
3. **Report baseline against current.** Replace the ad-hoc block at
   `cli.py:697-706` (`init-cda-mapping`) and add the same after `cli.py:374`
   (`build`):

   ```text
   coverage  baseline: Model: 120 datapoints · ✓ mapped 95 dp → 97 leaves · ! suggested 5 dp → 5 leaves · × no target 20 dp · ○ no source 368 leaves
   coverage  current:  Model: 120 datapoints · ✓ mapped 96 dp → 98 leaves · ! suggested 4 dp → 4 leaves · × no target 20 dp · ○ no source 367 leaves
   ```

   Two lines in the documented shape and nothing else. Keep the existing
   `review  <path>` lines that name each regressed field: those are the
   actionable part, not a competing summary.
4. **Extend the baseline fixture.** `tests/fixtures/reference-mapping-audit.json`
   holds only `{"fields": {path: {"selected": true}}}` today; add a sibling
   `"coverage_headline": {...}` block. In
   `tests/test_closure.py::test_mapped_fields_do_not_regress_from_committed_baseline`
   keep `delta["lost"] == []` and add: current `mapped_datapoints >= baseline`
   and `no_target_datapoints <= baseline`. Assert on the counts, never on the
   rendered string, so a wording change in the format document does not break
   the guard.
5. **Release checklist.** Record in `Project-decor2hl7.md` / `README.md` that
   regenerating the reference workspace and refreshing both blocks of
   `tests/fixtures/reference-mapping-audit.json` is a release step. The
   `Makefile` currently has only `mypy-report`; add `make check`
   (`python3 -m unittest discover -s tests`) and `make baseline` (refresh the
   fixture from `test-workplace/`).

<a id="f3-impl"></a>
#### F3. Closure guard

Files: `.github/workflows/checks.yml` (new), `conformance.py`,
`tests/test_closure.py`, `docs/decisions.md` (`DEC-019` amend),
`docs/known-issues.md`.

1. **Decide the CI host.** Add `.github/workflows/checks.yml` running Python
   3.10 and 3.12 over `python3 -m unittest discover -s tests` plus
   `python -m mypy src tests`. Be explicit about a consequence:
   `tests/test_closure.py::setUpClass` raises `SkipTest` when `../test-workplace`
   is absent, which it will be in a fresh clone — so on CI the closure and
   coverage guards protect nothing unless the companion workspace is checked out
   as a second step. Either check it out (it is private; the runner needs a
   deploy key or PAT) or make the skip visible in the workflow summary. Do not
   leave it silently green.
2. **Normalize the Schematron `@see` URIs before pinning any hash.**
   `validator-manifest.json` carries `schematron_sha256` and `validator_sha256`,
   and **neither is reproducible across machines**: 225 of the 1032
   `conformance-validation/include/*.sch` files, and `cda-template.sch` itself,
   embed an absolute local path plus a run timestamp injected by the DECOR
   publication transform into `@see`:

   ```text
   see="http://aktin.art-decor.pub/file:///data/eike/Code/decor2hl7/project/test-workplace/model/…/generated/aktin-html-20260903T201617/tmp-….html"
   ```

   `assembled_sha256` is clean (no hits in `decor-assembled.xml`) and
   `cda-template.xsl` is clean. So pin `assembled_sha256` now and pin the other
   two only after the rewrite. The rewrite is a small addition to the existing
   repair pass (`conformance.py:737 _repair_generated_stylesheet`, assembly at
   lines 802-851): rewrite `@see` to a workspace-relative URI and log every
   rewrite to `validator-compilation-errors.txt` exactly as the namespace
   repairs already do. Treat this as F3's blocking sub-task; without it a hash
   pin churns on every machine.
3. **Widen `tests/test_closure.py`.** Add a `crawl_degraded` ceiling (`<= 56`),
   an `unavailable_artifacts` ceiling (`<= 20`), `unresolved_templates == 1`, and
   `assembled_sha256` equality against a constant. Keep `ALLOWED_BUILD_DEGRADED`
   as a subset assertion and note in the docstring that shrinking it is a
   deliberate edit.
4. **Decision record.** Amend `DEC-019` with the `@see` normalization and with
   which hashes are pinnable and why. No new `DEC-*` id. Note the
   non-reproducible generated hashes in `docs/known-issues.md`.

<a id="phase5-research"></a>
#### Phase 5 research

**Offline — all of it decidable in the local archives.**

1. **`dynamic` bindings across the model.** Cross-check every `value_set_refs`
   entry in `model/2026.1.2/notaufnahmeregister--60/model.json` against the keys
   of its `value_sets` index before changing `_resolve_value_set`. Seven fields
   are affected; confirm there is no field whose dated and `dynamic` refs
   disagree on membership. If one exists, the fallback needs a reviewed rule,
   not the one-liner above.
2. **Open-template predicate for the `containment` label.** F1's
   `physical:containment` verdict needs to know whether the context template is
   open. Reuse the predicate `cda/extensions.py` and `config/cda-extensions.json`
   already apply for the `DEC-021` attachments; do not re-derive it.
3. **Gap-label ground truth.** Run the classifier over the 25 unmapped fields and
   diff it against the hand-written partitions in
   `docs/analyses/2026-09-02-residual-mapping-boundaries.md` and the project
   to-do inventory. Any disagreement is either a classifier defect or an
   analysis that has drifted; the point of F1 is that this stops being
   hand-maintained.
4. **Headline stability.** Regenerate `cda-mapping.md` after the F2 extraction
   and diff it against the committed copy. A zero diff is the acceptance
   criterion for F2 step 1.
5. **`@see` normalization scope.** Count the affected include files and check
   whether the same URI shape appears in `decor-source.xsl`; that decides whether
   the rewrite belongs in the assembly step or in how the publication transform
   is invoked (`conformance.py:827 outputBaseUriPrefix`).

**Online — two questions only.**

1. **Schematron `@see` provenance.** Check the ART-DECOR core release notes and
   issue tracker for whether a newer core package emits a relative or
   configurable `@see`. If it does, upgrading the pinned package
   (`conformance.py:41-90`, four checksum-pinned packages) is cleaner than a
   local rewrite; if not, the local repair stands and `DEC-019` should say so.
2. **CI access to the companion workspace.** Confirm whether
   `randomchars42/decor2hl7-test-workspace` is reachable from a GitHub Actions
   runner (private repository → deploy key or PAT). This decides whether F3
   enforces the guards or merely skips them.

<a id="phase5-checklist"></a>
#### Phase 5 completion checklist

| Item | Change |
|---|---|
| `docs/decisions.md` | amend `DEC-011` (gap labels); note frozen-`dynamic` resolution under `DEC-013` with the `DEC-004` caveat; amend `DEC-019` (`@see` normalization, pinnable hashes) |
| `docs/known-issues.md` | "Remaining active-profile mapping boundaries" cites gap keys; new note on non-reproducible generated Schematron hashes |
| Tests | `test_core.py` (dynamic resolution, one case per gap `kind`, headline byte-stability); `test_closure.py` (crawl/unavailable/unresolved ceilings, `assembled_sha256`, coverage-headline non-regression) |
| Generated docs | `docs/mapping-documentation-format.md` gains the `**Gap:**` line vocabulary |
| Reference workspace | regenerate (step 0 changes `formal_terminology.status` for 7 fields) and refresh `tests/fixtures/reference-mapping-audit.json` |

Suggested split, in order: **(a)** F1 step 0 plus the regenerated workspace —
smallest diff, largest correctness effect, and F1's labels depend on it;
**(b)** the rest of F1; **(c)** F2 and F3 together, since both touch the fixture
and the new workflow.

### Cross-cutting, specifiable now

<a id="e1-impl"></a>
#### E1. Repair the malformed generated XPath match patterns

`conformance.py` assembly (the stylesheet-repair step that already restores
namespace declarations): add a pass over `xsl:template/@match` values that
balances a leading `[[` produced by the publication transform for
`…[hl7:supply]` predicates. Guard it to the exact malformation
(`[[` immediately after a step, unbalanced `]`), log every rewrite to
`validator-compilation-errors.txt`, and never execute an un-probed stylesheet
(`validate-cda` stays fail-closed). Test with the two known revisions.

<a id="a7-impl"></a>
#### A7 / F3. Closure and coverage regression guards

_Landed. The remaining guard work is specified in
[Phase 5 § F3](#f3-impl) and [§ F2](#f2-impl)._

- `tests/test_closure.py` (new): load the reference `closure.json`, assert
  `build_degraded ⊆ {expected set}` and `len(generation_messages) <= N`.
- `tests/` coverage guard: call `mapping_field_delta` (`compile/mapping.py:2938`)
  against a committed baseline `mapping-audit.json`; fail on an unexplained
  drop in mapped datapoints.
- `cli.py`: add `decor2hl7 fetch --fail-on-degraded` (exit non-zero when
  `build_degraded` is non-empty) for CI.
