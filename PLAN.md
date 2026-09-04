# Implementation plan: closing the closure and recovering more CDA targets

Status: phases 1–4 landed. Date opened: 2026-09-03.
Baseline commit: `6d3ea59`. Reference workspace: `decor2hl7-test-workspace`
`spec/2026.1.2`, transaction `notaufnahmeregister--60`.

## Progress (as of `main` @ `4473eca`)

Commits since baseline: `11b33f6`/`ac7eec5` (EDIS map+merge),
`f9874a0` "Implement closure resolution and expansion phases", `15a52db` "added docs",
`c55bce5` "added immediate plan" (this document), `838bfc1` "Settle the last five
build-degrading closure artifacts" (phase 4), `315087e` "Recognize
reference-declaration identity when adopting a cached artifact", `ab85473`/`4473eca`
"completed phase 5".
**210 unit tests pass** (`python3 -m unittest discover -s tests`).

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
| F1 — machine-readable `gap` per unresolved datapoint | **done**, `DEC-011` amended; frozen-`dynamic` terminology index, `DEC-013`/`DEC-004` noted | `compile/mapping.py::_gap_classification`, `compile/transaction.py::_resolve_value_set`, `compile/reports.py`, `cda/compile.py` (`is_closed` on targets), `docs/mapping-documentation-format.md` |
| F2 — coverage guard on the documented headline | **done** — counts persisted as `summary.coverage_headline`; baseline/current reported in the documented line, no `+n/-n` shape | `compile/reports.py::coverage_headline_counts`/`format_coverage_headline`, `cli.py`, `tests/fixtures/reference-mapping-audit.json`, `scripts/update_reference_baseline.py`, `Makefile` (`check`, `baseline`) |
| F3 — closure guard + reproducible validator hashes | **done**, `DEC-019` amended; **no CI workflow — deliberately out of scope** | `conformance.py` (`@see` normalization, 14 053 rewrites logged), `tests/test_closure.py` (all three hashes pinned, crawl/unavailable ceilings) |
| Phase 6 — B0, B3, C1, C6 | **done**; C6 deliberately analysis-only | structural reopening evidence, scoped `SXCM_TS` branches, `DEC-023` Schematron support, `docs/analyses/2026-09-03-phase-6-structural-evidence.md` |

### Current reference-workspace metrics (after phase 5)

| Measure | Value |
|---|---:|
| Mapped datapoints | 95/120 → 97 leaves (unchanged by phases 4 and 5) |
| Suggested / no-target | 5 / 20 |
| Coverage headline | `Model: 120 datapoints · ✓ mapped 95 dp → 97 leaves · ! suggested 5 dp → 5 leaves · × no target 20 dp · ○ no source 368 leaves`, now persisted as `summary.coverage_headline` |
| Field gap partition | `physical:datatype_component` 19, `semantic:shared_target` 4, `physical:no_writable_leaf` 1, `semantic:missing_companion` 1, `terminology:closure` 1; **`semantic:no_association` 0** |
| Group gap partition | `physical:datatype_component` 18, `blocked_upstream:no_candidate` 8, `physical:no_writable_leaf` 4 |
| Validator | `executable: true`, **`complete: true`**, 0 compile errors, 3 generation messages (was 65), all outside the selected closure |
| Validator hashes | `assembled`/`schematron`/`validator` **all reproducible and pinned** after the `@see` normalization |
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

After phases 1–3 (see [Progress](#progress-as-of-main--4473eca)): 95/120 mapped;
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

Three of the four questions below are now answered from the pinned CDA core XSD
and the compiled reference workspace, including one confirmed expansion defect
(`SXCM_TS` compiled as an alias, so no interval branch exists) that also unblocks
D1. Detailed steps and evidence in [Implementation instructions § B3](#b3-impl).

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

The generated artifact has since been measured — 226 template-derived pattern
files, 5 530 rule contexts, ~14 000 assertions with a classified shape
distribution. Detailed steps in [Implementation instructions § C1](#c1-impl).

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
(`docs/analyses/2026-09-02-residual-mapping-boundaries.md`). That analysis found
two separate blockers for `dosismenge_und_einheit` and
`kontinuierliche_gabe_rate`: the source normalizer did not preserve unit/range
semantics, and no unambiguous source-to-target bridge existed.

- Step 1 (target-neutral model): **done 2026-09-04**. Quantity input preserves
  scalar `{value, unit?}` and range `{low, high}` forms, supplies a declared
  field unit when absent, and validates unit/range shape. This is reusable for
  FHIR `Quantity` later (`DEC-005`).
- Step 2 (CDA target): **done 2026-09-04, with the draft premise corrected**.
  Compilation records the exact writable low/high targets for an interval
  quantity and bindings project ranges through that metadata. The pinned CDA
  R2 schema declares `PQ/@unit` optional with default `1`; no blanket
  `non_null_requires` rule is added.
- Step 3 (bridge): **evidence gate not met**. Re-running the local evidence
  review found no formal association, exact implementation path, or reviewed
  crosswalk selecting `doseQuantity` and `rateQuantity`. Both accepted mapping
  entries remain `null`; datatype compatibility and distinct leaf names do not
  establish clinical correspondence.
- Decision-record impact: extend `DEC-013` (value model) with the structured
  quantity; no new clinical decision.

### C6. Terminology-association coverage audit

The coverage gap has since been measured: 1 312 of 4 188 `terminologyAssociation`
elements in the fetched specification sit under a parent the compiler never
inspects. Detailed steps in [Implementation instructions § C6](#c6-impl).

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

**2026-09-04 outcome:** expansion has surfaced the physical branches, but the
semantic gate is not met. The source provides three datetimes and no formal
association that selects the interval/repetition alternatives; in particular,
the dosage `zeitpunkt` cannot be converted into the quantity carried by
`PIVL_TS/period`. The selected choice and its `comp` cardinality also require a
reviewed within-occurrence construction rule. No timing mapping is added.

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
| 5 | F1–F3 | **done** (`4473eca`) — `gap` labels, `coverage_headline`, reproducible pinned hashes; CI workflow deliberately omitted | 0 (infra) |
| 6 | B0, B3, C1, C6 (in that order) | **done** — B3 scoped to a reviewed union list, C1 supporting-only, C6 analysis-only with zero coverage effect | +0 direct; B3 unblocks phase 7 |
| 7 | C5, then D1 | **mechanics done 2026-09-04** — structured quantities and compiled range targets landed; dose/rate and timing mappings remain closed at the semantic gate | 0; no clinical selection invented |
| 8 | C3 (`DEC-025`) only; **C4 closed as blocked**, C2 re-aimed | ordinal defect fixed 2026-09-04; X-ray dispatcher/`DEC-025` deferred because the complete reviewed 13-row crosswalk and conflict policy do not exist | 0; **the insurance +1 is withdrawn** |

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
does not exist; **and the insurance-relationship identifier** — the identified
`associatedEntity/id` leaf is active and writable, but only on the sibling
`1.2.276.0.76.10.2022` participant, and its association is held by a concept
family (`…3.2.1.808` "Versicherungsnummer") with no identity edge to the
selected concept (`…3.2.9.21582` "Identifikation") ([§ C4](#c4-research)).

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

### Phase 5 — gate-labelled reporting and regression guards — LANDED

Scope: F1, F2, F3. Coverage effect 0; this phase buys honest reporting and a
guard that keeps phases 6–8 from silently regressing. No ART-DECOR server
access is required — every question below is decidable from the local archives.

**As executed (`4473eca`, 210 tests).** The specification below landed as
written, with three recorded deviations:

- **No CI workflow.** F3 step 1 proposed `.github/workflows/checks.yml`. Adding
  one was **deliberately left out of scope** by the repository owner. The guards
  therefore run as ordinary unit tests through `make check`; they are not
  enforced by a hosted runner, and this document does not treat that as an open
  task. Do not re-propose it.
- **A stronger frozen-`dynamic` rule than specified.** Beyond resolving a literal
  `dynamic` request to the newest frozen revision, the compiler now also settles
  the case where analysis exposes *both* a dated embedded view and a dynamic
  association for the same OID: the dynamic association governs and the
  revisions are not unioned (`DEC-013`, preserving `DEC-004` exactness).
- **All three validator hashes turned out to be pinnable.** The `@see`
  normalization made `assembled_sha256`, `schematron_sha256` and
  `validator_sha256` reproducible (14 053 rewrites logged in the repair
  manifest), so `tests/test_closure.py` pins all three rather than only the
  assembled input.

Phase 5 also produced the measurement that re-aims phase 6: see
[Phase 6 § Status after phase 5](#phase-6--semantic-evidence-and-expansion-completeness-complete).

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

1. **CI host — decided: none.** This step originally proposed
   `.github/workflows/checks.yml`. Adding a CI workflow was **deliberately left
   out of scope**; the item is closed, not deferred, and must not be
   re-proposed. The guards run locally through `make check`
   (`python3 -m unittest discover -s tests`). One consequence is recorded here
   so it is not rediscovered as a defect: `tests/test_closure.py::setUpClass`
   raises `SkipTest` when the companion `../test-workplace` is absent, so in a
   clone without the reference workspace the closure and coverage guards skip
   rather than fail. That is intended behaviour for an optional local companion.
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

### Phase 6 — semantic evidence and expansion completeness (complete)

Implemented on 2026-09-03. The durable result and the one corrected premise
(CEDIS `IVL_TS` already retains inherited children) are recorded in
[`docs/analyses/2026-09-03-phase-6-structural-evidence.md`](docs/analyses/2026-09-03-phase-6-structural-evidence.md)
and `DEC-013`, `DEC-014`, and `DEC-023`. C6 remained analysis-only because its
optional compiler change had zero field-coverage effect. No CI workflow was
added.

Implemented scope: B0, B3, C1, and C6, in that order. Coverage effect: zero
direct gains; B3 supplies the physical leaves required by phase 7. The offline
research recorded below drove the reviewed rules and required no ART-DECOR
server access.

#### Status after phase 5

Every precondition named in the original phase-6 draft is now met: `is_closed`
is carried on compiled targets, the frozen-`dynamic` terminology index has
landed, and `mapping-audit.json` persists a `gap` per unresolved datapoint. Two
of phase 5's measurements change what phase 6 should do.

**1. `semantic:no_association` is empty — C1 must be re-aimed.** The draft
justified C1 partly as "the candidate list for fields with no association". The
measured field partition after phase 5 is:

| Gap key | Fields | Groups |
|---|---:|---:|
| `physical:datatype_component` | 19 | 18 |
| `semantic:shared_target` | 4 | — |
| `physical:no_writable_leaf` | 1 | 4 |
| `semantic:missing_companion` | 1 | — |
| `terminology:closure` | 1 | — |
| `blocked_upstream:no_candidate` | 0 | 8 |
| **`semantic:no_association`** | **0** | **0** |

No selected-model field fails on a missing association. C1 therefore keeps only
its *structural* justifications — confirmed `required` status, discriminator
domains for repetition rules, occurrence upper bounds, and permitted `xsi:type`
branches — and drops the "find the missing association" motivation entirely. It
also moves **last** in the phase, because it can no longer unblock a field on
its own. See [§ C1](#c1-impl), which is rewritten accordingly.

**2. The medication cluster is a depth problem, not an evidence problem.**
Thirteen of the nineteen `physical:datatype_component` fields are the medication
cluster, and every one of them reopens against
`Medikation.substanceAdministration`. Their `reopens_with` lists the *immediate*
components of that container — `Medikation.moodCode`, `…routeCode`,
`…approachSiteCode`, `CDASubstanceAdministration.substanceAdministration.repeatNumber`
and so on — because `_gap_classification` (`compile/mapping.py:1125-1154`)
selects writable targets exactly one location level below the context node.
The leaves that actually fit those fields (`…doseQuantity@20230130`,
`…rateQuantity@20230130`, the `effectiveTime` branches) sit on the contained UV
Subordinate administration, several levels deeper. The label is correct; the
evidence stops too shallow to be actionable. [§ B0](#b0-impl) fixes that, and it
is a precondition for phase 7 reading its own targets out of the audit.

**3. All phase-6 research is complete** — five offline questions and the one
online question, recorded in [§ Phase 6 research](#phase6-research). It changed
three of the four items materially: B3's trigger must be a reviewed union list
rather than an XSD-derived predicate (the generic rule hits 414 elements), C6
collapses to an analysis with **zero** coverage effect, and C1's `xsi:type`
census was corrected from 3 825 to 29.

Ordering for the phase: [B0](#b0-impl) → [B3](#b3-impl) → [C1](#c1-impl) →
[C6](#c6-impl). B0 is hours and unblocks reading phase 7's targets out of the
audit; B3 is the only item that opens new physical leaves and is the one that
unblocks D1; C1 is viable (78.2 % in-closure context match) but evidence-only;
C6 is last because the audit already answered it — what remains is writing it
down.

<a id="b0-impl"></a>
#### B0. Deepen `datatype_component` reopening evidence (new, from phase 5)

Files: `compile/mapping.py` (`_gap_classification`, lines 1125-1154),
`tests/test_core.py`, `docs/mapping-documentation-format.md` (one sentence),
`tests/fixtures/reference-mapping-audit.json` if the headline moves (it should
not — this changes evidence, not selection).

The depth-1 component rule is right for a plain complex datatype (`AD`, `EN`,
an `IVL_PQ`) whose parts are its immediate children. It is wrong for a
*structural* container such as `hl7:substanceAdministration`, whose payload
leaves live under contained templates.

**Measured ([R5](#phase6-research)): every current case is structural.**
Classifying each gap's context-node datatype with
`cda/datatypes.py::classify_datatype` gives `structural` for **19 of 19** fields
and **18 of 18** groups, and `datatype`/`alias` for none. The
`datatype_component_available` branch in `_unresolved_reason`
(`compile/mapping.py:968`) fires whenever the context node has any datatype
string and children, and a `POCD_MT000040.*` container satisfies that. So the
depth-1 branch is currently dead code and the gap *kind* is misnamed for every
case that occurs.

1. **Rename the kind for the structural case.** Emit
   `physical:structural_container` when the context datatype classifies as
   `structural`, and keep `physical:datatype_component` for a genuine complex
   datatype. Both keys go in the vocabulary in
   `docs/mapping-documentation-format.md`; today the second will simply have a
   count of zero, which is the honest reading.
2. **Keep depth-1** for the `datatype` / `alias` case. It is unexercised now but
   correct, and a future template that binds a field directly to an `AD` or
   `IVL_PQ` will need it. Cover it with a synthetic test rather than deleting it.
3. **Descend for the structural case** to the **nearest writable leaves** below
   the context location, at any depth, capped (twenty is enough; the audit is
   evidence, not a proposal). Prefer leaves whose compiled logical type is
   compatible with the field's model type, so the medication timestamps surface
   the `effectiveTime` branches and `dosismenge_und_einheit` surfaces
   `doseQuantity`.
4. Do not turn any of this into a candidate: `reopens_with` is reopening
   evidence for a reviewer, never a mapping. The selection path (`_candidates`)
   is untouched, so the coverage headline must come out identical — assert that.
5. **Update the pinned counts.** `summary.gaps` keys change for 37 datapoints,
   and `docs/known-issues.md` quotes the partition verbatim
   ("`physical:datatype_component` (nineteen)"). Update both, and re-run
   `make check`; `tests/test_closure.py::test_mapping_gaps_are_persisted_and_rendered`
   will need the new key.
6. Test: a synthetic datatype container keeps the depth-1 list; a structural
   container gets leaves from below the contained template; the reference
   coverage headline is byte-identical.

Acceptance: the thirteen medication fields reopen against the UV Subordinate
administration leaves that `docs/analyses/2026-09-02-residual-mapping-boundaries.md`
names by hand today, so phase 7 can read its targets out of the audit instead of
the analysis prose.

<a id="b3-impl"></a>
#### B3. Datatype / RIM expansion completeness audit

Files: `cda/datatypes.py`, `cda/compile.py`, `cda/model.py`,
`tests/test_cda_datatypes.py`, `docs/decisions.md` (`DEC-013`/`DEC-014` amend),
`docs/known-issues.md`, a dated analysis under `docs/analyses/`.

##### Finding 1 — `SXCM_TS` is compiled as an alias, so no interval branch exists (defect)

`cda/datatypes.py:56` declares `"SXCM_TS": _definition("SXCM_TS", base="TS",
kind=DatatypeKind.ALIAS)`. An element declared `SXCM_TS` therefore compiles to a
bare timestamp with no children. Verified in the reference workspace:
`UVSubordinateadministration.substanceAdministration.effectiveTime_xsi_type_SXPR_TS.comp`
is `SXCM_TS`, `writable: true`, `has_children: false`, `min: 2`.

But `SXCM_TS` is not a leaf in the pinned CDA core XSD — it is the abstract root
of the interval family. Verified against
`spec/2026.1.2/cda-core/datatypes-base.xsd` and `datatypes.xsd`:

| Type | XSD base | XSD element children |
|---|---|---|
| `SXCM_TS` | `TS` | — |
| `IVL_TS` | `SXCM_TS` | `low`, `width`, `high`, `center` |
| `PIVL_TS` | `SXCM_TS` | `phase`, `period` |
| `EIVL_TS` | `SXCM_TS` | `event`, `offset` |
| `SXPR_TS` | `SXCM_TS` | `comp` |

A concrete branch is reachable only through `xsi:type`, and the compiler already
has exactly one mechanism for that: `_materialize_polymorphic_targets`
(`cda/compile.py:1986`), which emits `<name>_as_<TYPE>` targets carrying
`value_representation.xsi_type`. Today it fires only for
`datatype == "ANY"` against a hard-coded `scalar_types` tuple
(`cda/compile.py:1998`).

Change — **scoped, not XSD-derived**. The obvious generalization ("fire for any
element whose declared datatype has XSD extensions and no children of its own")
was measured and rejected: it hits **414 compiled elements**, including 178 `TS`,
97 `INT` and 56 `URL` that carry their own scalar representation and are
perfectly writable as declared ([R4](#phase6-research)). Materializing
`_as_IVXB_TS` / `_as_PPD_TS` / `_as_UVP_TS` on every timestamp would be noise and
would move the `○ no source` term of the pinned coverage headline for nothing.

Instead:

- In `cda/core.py`, still build the reverse `xs:extension/@base → [subtype]`
  index while `index_definitions` walks the schema, and expose it on the
  `DefinitionIndex` — it is needed to know *which* branches to emit.
- Gate the *trigger* on a small reviewed union list in `cda/datatypes.py`, with
  exactly one entry today: `SXCM_TS`. It is the one type the policy models as an
  `ALIAS` while the XSD models it as the abstract root of the interval family.
  Adding a second entry is a reviewed change, not an inference.
- In `_materialize_polymorphic_targets`, emit one typed target per concrete
  subtype from the XSD index and recurse into that subtype's declared parts.
  Keep the existing `ANY` behaviour as the scalar case; keep the duplicate-name
  guard at `cda/compile.py:2011`.

**Protect the plumbing.** Of the 66 located `SXCM_TS` elements, **64 are
`useablePeriod`** on `addr` / `telecom` / `text/reference` — `datatype_derived`
CDA/RIM plumbing that is never a mapping target — and one is
`Medikation.effectiveTime`, which is `conformance="NP"` / `prohibited: true`.
The change has exactly **one** intended beneficiary,
`UVSubordinateadministration.…effectiveTime_xsi_type_SXPR_TS.comp`. Gate
materialization on the element being non-`datatype_derived` **or** reached
through an explicit `xsi:type` step, and assert in a test that no
`useablePeriod` target gains typed branches.

**Independent corroboration.** The generated Schematron asserts exactly the four
XSD subtypes as concrete choice branches — `EIVL_TS` (13), `PIVL_TS` (12),
`SXPR_TS` (8), `IVL_TS` (7) — with none missing and no fifth interval type
([R3](#phase6-research)).

Expected effect: `…SXPR_TS.comp_as_IVL_TS.low` / `.high` and
`…comp_as_PIVL_TS.period` become writable leaves. That is the physical
precondition for [D1](#d1-medication-timing-interval--frequency-structural-rule) — the three medication timestamps currently collide
on one atomic `TS` because the template's `effectiveTime` `<choice>` offers
`TS` / `PIVL_TS` / `EIVL_TS` / `SXPR_TS` and **no `IVL_TS` branch at all**
(verified in
`spec/2026.1.2/templates/2.16.840.1.113883.10.21.4.6_2023-01-30T09_36_00.source.xml`,
lines 36-83). B3 supplies the leaves; D1 supplies the rule that selects the
`SXPR_TS` branch when more than one timing source is present. Do not attempt
D1's rule here.

Guards this must not break: `EIVL_TS` keeps its
`non_null_required_parts=("hl7:event",)` (`DEC-020`), the `<choice>` remains
`max 1` so only one branch may be written, and `comp` keeps `min: 2`.

**The simpler alternative is closed.** Writing repeated `effectiveTime` elements
on the *outer* `Medikation` substance administration — the ordinary CDA pharmacy
pattern of one `IVL_TS` for the period plus one `PIVL_TS` for frequency — is not
available: `1.2.276.0.76.3.1.195.10.67` declares
`<element name="hl7:effectiveTime" conformance="NP"/>`, and the compiled target
is `prohibited: true`, `writable: false`. `SXPR_TS/comp` on the subordinate
administration is the only route.

##### Finding 2 — writable `@value` on an `IVL_TS` element is correct, not a defect (closed)

`Problemobservationcedis.effectiveTime` is `IVL_TS` and compiles
`value_representation: {kind: "timestamp", attribute: "value"}`, which looks
wrong because `cda/datatypes.py:57` gives `IVL_TS` no representation. It is
correct: `representation_type` (`cda/compile.py:1264`) walks the **XSD** base
chain when the policy has none, so `IVL_TS → SXCM_TS → TS` yields the `TS`
timestamp policy, and `<effectiveTime value="…"/>` is the legal V3 point-in-time
shorthand for an interval. Record this in the analysis so it is not
re-investigated. The one question left for review — should a template that
declares a required `hl7:width` still offer the `@value` shorthand on the same
element? — was taken to the published specification and is **closed**: `IVL_TS`
inherits `@value` from `SXCM_TS`/`TS`, and the CDA StructureDefinition carries no
constraint forbidding it (its only interval co-occurrence rule is
`ivl-ts-center`). No HL7 erratum addresses `@value` alongside a declared required
`width` ([Online](#phase6-research)). It is therefore neither an upstream defect
nor a compiler defect. Recommendation: keep the shorthand — the compiled
representation follows the pinned XSD, which is this project's stated authority —
and record the oddity in `known-issues.md` rather than special-casing the
compiler. No `DEC-013` change is required unless a reviewer disagrees.

##### Finding 3 — `Ereigniseintritt`: confirm the declared-children drop rule, then close

Active `1.2.276.0.76.10.4040` declares
`<element name="hl7:effectiveTime" datatype="IVL_TS" conformance="R">` with a
single declared child `<element name="hl7:width" datatype="PQ"
minimumMultiplicity="1" conformance="R">` and **no** `low`/`high`. The compiled
targets match: `Problemobservationcedis.observation.effectiveTime.width.*`
exists and `…effectiveTime.low` / `.high` do not — while the *unconstrained*
sibling `CDAObservation.observation.effectiveTime` on the same revision does get
`.low`, `.high`, `.center` from datatype expansion.

So the compiler stops CDA/RIM datatype expansion for an element whose ART-DECOR
constraint set names explicit children, and expands fully when it names none.
Decide and record whether that is the intended `DEC-014` rule. Arguments both
ways: naming `width` refines the interval, but ART-DECOR does not thereby
*prohibit* `low`/`high` unless the element is closed or they carry
`isProhibited`. If the rule is intended, `Ereigniseintritt` is **blocked
upstream** — record the exact missing particle (`hl7:effectiveTime/hl7:low` on
`1.2.276.0.76.10.4040@2015-09-18`) and close it; C4 in phase 8 offers no route
here either. If it is not intended, this is the expansion defect B3 was written
to find, and fixing it may open the onset leaf.

##### Finding 4 — MRI region: confirmed blocked upstream (close with evidence)

`1.2.276.0.76.10.4058` compiles to 14 targets with exactly **one** writable
leaf, `Magneticresonanceimaging.value` (`CE`), already carrying the
"performed" indicator. There is no `targetSiteCode`, no `approachSiteCode` and
no region-bearing particle of any kind. `PLAN.md`'s B3 claim is confirmed;
record the missing particle and close the item as blocked upstream. The X-ray
region stays a C3 ConceptMap candidate in phase 8 and is unaffected.

##### Deliverable

A dated analysis under `docs/analyses/` recording findings 1-4, plus the code
for finding 1 and a decision note on finding 3. `_unresolved_reason`
(`compile/mapping.py:950`) already distinguishes `structural_only` /
`ambiguous_value_target` / `datatype_component_available`; once [F1](#f1-impl)
persists those, use them to drive the remaining sweep rather than re-reading the
audit by hand.

<a id="c1-impl"></a>
#### C1. Schematron-derived constraint evidence

Files: new `compile/schematron.py`, `compile/mapping.py` (`_candidates`,
line 1241), `compile/structural.py` (`repeat_by_discriminator_rule`, line 539),
`tests/test_conformance.py` / `tests/test_core.py`, `docs/decisions.md`
(`DEC-017` amend or new `DEC-024`).

##### What the generated artifact actually contains (measured)

`build` already emits, under
`model/<release>/<transaction>/conformance-validation/include/`, **226
template-derived pattern files** (excluding the `DTr1_*` datatype patterns and
the `voc-*` value-set snapshots) carrying **5 530 rule contexts**. Classifying
every `<assert>/@test` in them:

Corrected census over all 14 043 assertions (categories are **not** mutually
exclusive — one assertion may be both a cardinality and a fixed-value test):

| Assertion shape | Count | Evidence it yields |
|---|---:|---|
| `count(…) <= n` | 3 881 | repetition upper bound |
| datatype conformance, `QName('urn:hl7-org:v3','X')` | 3 809 | per-context datatype oracle across 32 types |
| `string(@a) = ('V')` fixed value | 2 583 | discriminator fixed codes |
| `count(…) >= n` | 1 828 | confirmed **required** status |
| `doc('include/voc-<OID>-…xml')` | 1 134 | discriminator value sets |
| unclassified | 1 119 | co-occurrence, string form |
| bare `@attr` required | 188 | mandatory attribute |
| concrete choice branch, `@xsi:type='X'` | **29** | permitted `xsi:type` (`DEC-017`; corroborates [B3 finding 1](#b3-impl)) |

An earlier draft of this table reported "3 825 `xsi:type` constraints". That was
over-broad — it counted every assertion mentioning `xsi:type`, almost all of
which are the datatype-conformance form. Only 29 enumerate a concrete branch
([R3](#phase6-research)).

This is spec-derived and already computed — C1 re-uses an artifact `build`
produces, it does not add clinical knowledge.

##### Re-aimed after phase 5

Phase 5 measured **zero** fields and zero groups in `semantic:no_association`,
so C1 can no longer be justified as the route to a field that lacks an
association. What survives is structural, and each use must name the gap it
serves:

| Surviving use | Serves |
|---|---|
| confirmed `required` status (1 180 `count(…) >= n`) | strengthens an existing WEAK/MEDIUM candidate |
| discriminator domains (1 134 value-set + 2 463 fixed-value) | `repeat_by_discriminator` rule construction |
| occurrence upper bounds (2 988 `count(…) <= n`) | stops a rule proposing more occurrences than allowed |
| permitted `xsi:type` branches (**29**, not 3 825 — see [R3](#phase6-research)) | `DEC-017` choice selection; independent cross-check on [B3 finding 1](#b3-impl) |

Consequences for scope: C1 runs **last** in phase 6, its acceptance criterion is
evidence quality rather than coverage, and step 3 below is explicitly *not*
allowed to create a candidate. If the match rate measured in step 2 is poor, the
honest outcome is an analysis recording that the generated Schematron cannot be
cross-referenced reliably — not a looser matcher.

##### Steps

1. **`compile/schematron.py` (new).** Parse each `include/*.sch` pattern file
   into `{context_xpath: [constraint]}` where a constraint is
   `{"kind": "required"|"max_occurs"|"fixed_value"|"value_set"|"xsi_type"|"attribute_required",
   "path": …, "value": …, "value_set": …}`. Read only `@context` and `@test`;
   **ignore `@see`**, so [F3](#f3-impl)'s URI rewrite cannot affect this parser.
   Skip `DTr1_*` (datatype patterns) and `voc-*` (value-set snapshots).
2. **Cross-reference with compiled targets.** Rule contexts are predicated
   XPaths such as
   `*[hl7:substanceAdministration[hl7:templateId[@root='…']]]/hl7:substanceAdministration[…]`;
   compiled targets carry `path` plus `template_id`/`template_effective_date`.
   Match on the template-id predicate plus the trailing step, not on string
   equality — the contexts carry ancestor predicates the compiled `path` does
   not. **Already measured ([R1](#phase6-research)): 78.2 % of the 2 427
   contexts owned by an in-closure template match**, and only 13 contexts in the
   whole set name a step that exists nowhere in the compiled model. Two
   requirements follow from that measurement: split the XPath on `/` at bracket
   depth zero and skip quoted literals (a naive split corrupts every context
   whose predicate contains a `doc('include/voc-….xml')` path), and take the
   owning template from the pattern file's `id="template-<oid>-<date>"` as well
   as from `@root` predicates. The 19.3 % residual is generic header/entity
   plumbing (`hl7:addr`, `hl7:telecom`, `hl7:name`, organization parts) and is
   accepted, not chased — record the unmatched tail in the analysis.
3. **New evidence kind `SCHEMATRON_CONSTRAINT`** in `compile/mapping.py`,
   produced by a new contributor called from `_candidates` (line 1241) next to
   `_vocabulary_candidates`. It never creates a candidate on its own: it
   **strengthens** an existing WEAK/MEDIUM candidate to actionable when a
   `required` or `value_set` constraint confirms the leaf, exactly as
   `boolean_example_discriminator_rules` treats neutral examples as supporting
   evidence. Guard this in a test: a field with no candidate before the
   contributor runs must still have no candidate after it, on the reference
   workspace as well as on a synthetic case.
4. **Feed `repeat_by_discriminator`.** `compile/structural.py:518
   _schematron_unique_codes` already consumes uniqueness assertions; extend it
   with the 1 134 value-set and 2 463 fixed-value constraints so a repetition
   rule can name its discriminator domain, and with the `count(…) <= n` bounds
   so a rule cannot propose more occurrences than the template allows.
5. **Decision record.** Amend `DEC-017` with the Schematron constraint source
   and its supporting-evidence-only status, or open `DEC-024` if the reviewer
   prefers a separate id. State explicitly that a Schematron constraint may
   never be the *sole* bridge for a mapping.

<a id="c6-impl"></a>
#### C6. Terminology-association coverage audit — AUDIT COMPLETE, no coverage item

Files (only if the optional fix in step 2 is taken):
`compile/transaction.py` (lines 438 and 507), `tests/test_core.py`, a dated
analysis. The precondition ([F1 step 0](#f1-impl)) is satisfied.

##### Measured gap, and why it does not matter

Both `terminologyAssociation` parse loops in `compile/transaction.py` require
the element to be a direct child of a `<concept>`. Counting every
`terminologyAssociation` in the fetched `spec/2026.1.2/` tree by its parent:

| Parent path | Count | Read today |
|---|---:|---|
| `concept/concept` | 2 729 | yes |
| `concept/valueSet` | 669 | **no** |
| `decor/terminology` | 643 | **no** |
| `representingTemplate/concept` | 95 | yes |
| `dataset/concept` | 52 | yes |

1 312 of 4 188 associations (31 %) sit under a parent the compiler never
inspects. That number looks alarming and is not: resolving the 643
project-level associations against the 177 selected concepts leaves **70** whose
subject is selected at all, and **8** that are not already compiled
([R2](#phase6-research)). All 8 are plain `code` associations, and all 8 belong
to **groups** — `ersteinschatzung`, `…manchester_triage_system`,
`vitalparameter.blutdruck`, `vitalparameter.korperkerntemperatur`,
`abschlussdiagnosen`, `abschlussdiagnose`. Five are already selected; the sixth,
`vitalparameter.blutdruck`, fails on `physical:datatype_component`, a physical
gap no code association can open.

**C6 therefore opens zero mappings and is not a coverage item.** Record that
result rather than pursuing the 31 % headline.

##### What remains

1. **Write the analysis.** A dated `docs/analyses/` note recording the parent
   census, the 643 → 70 → 8 funnel, and the conclusion that the uninspected
   associations are duplicates or group-level metadata. This is the deliverable;
   it closes C6.
2. **Optional completeness fix (correctness, not coverage).** If the 8 are worth
   carrying for provenance, extend both loops to accept an association addressed
   by `@conceptId` from a `<terminology>` container, reusing the existing
   association dict shape and `_association_scope`. Keep nesting-derived
   associations preferred on conflict and record the container in `form`
   (new value `"project-terminology"`). Guard with a test that the coverage
   headline is unchanged — it must be, since no field gains an association.
3. **Inherited concepts — still open, and deliberately deferred.** Whether an
   association on a concept reached only through `<inherit>` should be indexed
   is the same question C2 raises in phase 8. `_semantic_concept_index`
   (`compile/mapping.py:167`) follows `inherit`/`relationship`/`contains` for
   *labels* only. Do not decide it here by accident; hand it to C2.
4. **`conceptList` hierarchy for `ordinal` — closed, no transform.** Of the 24
   value-set OIDs bound by a selected field, exactly one is hierarchical
   (`1.2.276.0.76.11.61`, CEDIS, 189 members), and its field is already mapped
   and `bound`. CEDIS is a presenting-complaint taxonomy, not a scale
   ([R2b](#phase6-research)). Add no `ordinal` transform; note it against
   `known-issues.md` "Transform vocabulary".

No new decision record. C6 changes no policy.

<a id="phase6-research"></a>
#### Phase 6 research — COMPLETE

All five offline questions and the one online question are answered. Results are
folded into the items above; this section records the measurements and the
method so they can be re-run after any compiler change. Everything below was
measured against the post-phase-5 workspace (`main` @ `4473eca`).

##### R1 — Schematron context match rate: **78.2 % in the selected closure** (viable)

Matching rule contexts to compiled targets by *template-id predicate plus
trailing step*:

| Matcher | Contexts | Matched |
|---|---:|---:|
| naive (split on `/`, trailing step, roots in the context string) | 5 530 | 68.0 % |
| predicate-aware split + pattern-owner template as fallback | 5 530 | 73.6 % |
| the same, restricted to the 119 pattern files owned by an in-closure template | 2 427 | **78.2 %** |

Two lessons for [§ C1](#c1-impl). First, split an XPath on `/` **at bracket
depth zero** and skip quoted literals — a naive split corrupts every context
whose predicate contains a `doc('include/voc-….xml')` path, which alone
accounted for ~390 false misses. Second, take the owning template from the
pattern file's `id="template-<oid>-<date>"` rather than only from `@root`
predicates inside the context.

The residual 19.3 % is not a defect: it is almost entirely generic CDA
header/entity plumbing whose step exists under a different template —
`hl7:addr` (160), `hl7:telecom` (160), `hl7:name` (157),
`hl7:standardIndustryClassCode` (96), `hl7:asOrganizationPartOf` /
`hl7:wholeOrganization` (48 each). Only **13 contexts in the whole set** name a
step that exists nowhere in the compiled model. A full ancestor-chain matcher
would recover most of the residual and is not worth it: those contexts do not
constrain mapping surface. Accept 78 % and record the unmatched tail.

##### R2 — C6 new associations: **8, all on groups, zero coverage effect** (scope collapses)

Resolving the 643 project-level `<decor>/<terminology>` associations against the
177 selected concepts:

| Step | Count |
|---|---:|
| project-level `<terminology>` associations in the fetched spec | 643 |
| …whose `@conceptId` is a **selected** concept | 70 |
| …not already present in the compiled association set | **8** |
| …that are value-set associations | 0 (all 8 are plain `code`) |

Those 8 belong to six **groups** and no field:
`ersteinschatzung`, `…manchester_triage_system`, `vitalparameter.blutdruck`,
`vitalparameter.korperkerntemperatur`, `abschlussdiagnosen`,
`abschlussdiagnose`. Five of the six are already selected. The sixth,
`vitalparameter.blutdruck`, carries `physical:datatype_component` — a physical
gap that an additional code association cannot open.

**Conclusion: the C6 compiler change would open zero mappings.** C6 is therefore
an analysis plus an optional cheap completeness fix, not a coverage item — see
the rewritten [§ C6](#c6-impl).

##### R2b — `conceptList` hierarchy: **no ordinal transform is justified**

Of the 24 value-set OIDs bound by a selected field, exactly **one** is
hierarchical (`@level > 0`): `1.2.276.0.76.11.61`, CEDIS, 189 members, bound by
`notfallanamnese.beschwerden_bei_vorstellung.beschwerden_bei_vorstellung_cedis`
— which is already **mapped and `bound`**. CEDIS is a presenting-complaint
taxonomy, not a scale, so reading its nesting as an ordinal would be wrong on
the merits as well as unnecessary. Add no transform; record the finding against
`known-issues.md` "Transform vocabulary".

##### R3 — `xsi:type` cross-check: **exact agreement**, and a census correction

The four XSD-derived `SXCM_TS` subtypes are exactly the four asserted as
concrete choice branches in the generated Schematron — `EIVL_TS` (13),
`PIVL_TS` (12), `SXPR_TS` (8), `IVL_TS` (7). None is missing and no fifth
interval type appears. Two independent sources agree, which is strong
corroboration for [B3 finding 1](#b3-impl).

**Correction to the earlier census.** The "3 825 `xsi:type` constraints" row in
the first draft of § C1 was over-broad: it counted every assertion that merely
*mentions* `xsi:type`. Split honestly, 3 842 assertions mention it, of which
**3 809 are datatype-conformance assertions** of the form
`empty(@xsi:type) or resolve-QName(@xsi:type, .) = QName('urn:hl7-org:v3','II')`
across 32 distinct types, and only **29 assert a concrete `@xsi:type='X'`
equality**. The first form is a per-context datatype oracle; only the second is
choice-branch enumeration. § C1's census table is corrected accordingly.

##### R4 — B3 blast radius: **the generic rule is unusable; scope to `SXCM_TS`**

A rule of the form "materialize typed branches for any element whose declared
datatype has XSD extensions and no element children of its own" would fire on
**414 compiled elements**:

| Declared datatype | Elements |
|---|---:|
| `TS` | 178 |
| `INT` | 97 |
| `SXCM_TS` | 75 |
| `URL` | 56 |
| `ANY` | 8 |

`TS`, `INT` and `URL` all carry their own scalar representation and are
perfectly writable as declared; materializing `_as_IVXB_TS`, `_as_PPD_TS`,
`_as_UVP_TS` on every timestamp would be pure noise and would move the
`○ no source` term of the pinned coverage headline for nothing. **Do not derive
the trigger from the XSD graph.** Scope the change to a reviewed union list
whose only current entry is `SXCM_TS` — the one type the policy models as an
alias while the XSD models it as the abstract root of the interval family.

Of the 75 `SXCM_TS` elements, 66 hold a document location, and their
distribution decides the design:

- **64 are `useablePeriod`** on `addr` / `telecom` / `text/reference`, all
  `datatype_derived` CDA/RIM plumbing that is never a mapping target;
- **1 is `Medikation.effectiveTime`** — and it is `conformance="NP"`,
  `prohibited: true`, so the tempting alternative of writing repeated
  `effectiveTime` elements on the *outer* substance administration is **closed
  by the template**, confirmed in
  `spec/2026.1.2/templates/1.2.276.0.76.3.1.195.10.67_resource.source.xml`;
- **1 is `UVSubordinateadministration.…effectiveTime_xsi_type_SXPR_TS.comp`** —
  the [D1](#d1-medication-timing-interval--frequency-structural-rule) target.

So the change has exactly **one** intended beneficiary and 64 plumbing elements
it must not disturb. Gate the materialization on the element being
non-`datatype_derived` **or** explicitly reached through an `xsi:type` step, and
assert in a test that no `useablePeriod` target gains typed branches.

##### R5 — B0 depth check: **all 37 `datatype_component` gaps are structural**

Classifying each gap's context-node datatype with
`cda/datatypes.py::classify_datatype`:

| Context datatype class | Fields | Groups |
|---|---:|---:|
| `structural` (`POCD_MT000040.Section`, `…SubstanceAdministration`) | **19** | **18** |
| `datatype` / `alias` (a genuine complex datatype) | **0** | **0** |

Not one current gap is actually about a datatype component. The
`datatype_component_available` branch in `_unresolved_reason`
(`compile/mapping.py:968`) fires whenever the context node has *any* datatype
string and children, and a `POCD_MT000040.*` container satisfies that. This
simplifies and sharpens [§ B0](#b0-impl): the depth-1 branch it preserves is
currently dead code, and the gap **kind** is misnamed for every case that
occurs.

##### Online — no HL7 erratum; the `@value` question is ours to decide

`IVL_TS` inherits `@value` from `SXCM_TS`/`TS`, and the CDA StructureDefinition
carries no constraint forbidding it: the only interval co-occurrence rule
published there is `ivl-ts-center` ("center cannot co-exist with low or high").
Writing `<effectiveTime value="…"/>` on an element declared `IVL_TS` is
therefore legal and merely semantically odd — it states a point where the type
promises an interval. No erratum or clarification addresses the specific case of
`@value` alongside a template-declared required `width`.

[B3 finding 2](#b3-impl) is consequently closed as *not an upstream defect and
not a compiler defect*. Whether decor2hl7 should keep offering the `@value`
shorthand on a `width`-declaring element is a local `DEC-013` policy question;
the recommendation is to keep it (the compiled representation follows the
pinned XSD, which is the project's stated authority) and to record the oddity
in `known-issues.md` rather than special-case the compiler.

Sources: [IVL_TS: Interval (V3 Data Type), CDA core 2.0](https://build.fhir.org/ig/HL7/CDA-core-2.0/StructureDefinition-IVL-TS.html),
[IVL_TS definitions](https://build.fhir.org/ig/HL7/CDA-core-2.0/StructureDefinition-IVL-TS-definitions.html),
[HL7 V3 Data Types abstract specification](https://vico.org/HL7_RIM/infrastructure/datatypes_r2/datatypes_r2.html).

##### What the research changes

| Item | Before research | After |
|---|---|---|
| B0 | keep depth-1 for datatype containers, descend for structural | depth-1 branch is dead; every case is structural; also rename the gap kind |
| B3 | generalize the polymorphic pass from the XSD graph | XSD-derived trigger hits 414 elements — scope to a reviewed union list (`SXCM_TS`), one real beneficiary, 64 plumbing elements to protect |
| C1 | parser viability unknown | 78.2 % in-closure match; census corrected (29 choice branches, not 3 825) |
| C6 | compiler change, size unknown | 8 new associations, all on groups, **zero** coverage effect — analysis only |
| Ordering | B0 → B3 → C6 → C1 | **B0 → B3 → C1 → C6**, C6 last because it is now the cheapest and least consequential |

### Phases 7–8 — advance research (COMPLETE)

Measured against `main` @ `4473eca` while phase 6 was in flight, and re-verified
against `6396d62` after phase 6 landed. None of it required ART-DECOR access.
It settles one item outright (**C4 cannot fire as specified**), re-aims a second
(**C2**), sizes the two phase-7 items, and turns up one latent compiler defect.

Implementation status after the 2026-09-04 sequenced pass: structured
quantities and compiled interval-bound assignment are implemented; the ordinal
extractor is guarded; and **D1's physical B3 precondition is satisfied**. The
dose/rate, timing, and X-ray selections remain closed because their semantic
evidence gates are not satisfied. See the durable outcome in
[`docs/analyses/2026-09-04-phase-7-8-sequenced-implementation.md`](docs/analyses/2026-09-04-phase-7-8-sequenced-implementation.md).

<a id="c5-research"></a>
#### C5 (phase 7) — representation mechanics complete; semantic bridge absent

**Original finding (now fixed): the normalizer discarded units.** `data.py:169`
routed `quantity` / `decimal` / `duration` to `_parse_number(text, site)`, which
returned a bare number. Any unit written by the source was lost before the value
reached a target.

**The model already has a slot for the unit, and it is partly populated.**
`compile/transaction.py:288` copies `unit` off the ART-DECOR `<quantity>` value
domain into the compiled field. Of the two phase-7 fields:

| Field | `type` | model `unit` | implementation note |
|---|---|---|---|
| `…dosierung.kontinuierliche_gabe_rate` | `quantity` | **`g/h`** | "Menge mit Einheit pro Zeiteinheit bei kontinuierlicher Gabe (Rate)" |
| `…dosierung.dosismenge_und_einheit` | `quantity` | *(none)* | "Menge mit Einheit pro Dosis, kann auch einen Mengenbereich umfassen" |

So the rate has a declared unit the compiler already knows, and the dose does
not — its unit is genuinely per-value, and its note explicitly allows a
**range**. That asymmetry should drive the design: a structured quantity needs
`{value, unit}` at minimum and `{low, high, unit}` for the dose.

**The CDA side exposes both scalar and interval structure.** `doseQuantity@20230130` compiles
`value_representation {kind: "quantity", attributes: ["value","unit"],
scalar_attribute: "value"}`, so the compound already exists — C5 step 2's
premise holds. The draft's proposed global `PQ/@unit` requirement does not: the
pinned CDA R2 XSD marks that attribute optional with default `1`, and active
examples permit unitless counts. The implemented rule preserves a provided or
field-declared unit on the compound representation and records exact low/high
child target names for ranges; it does not create a universal companion rule.

**2026-09-04 outcome.** The source representation and CDA assignment mechanics
are complete under amended `DEC-013`. The clinical bridge is not: neither field
has a formal association or reviewed crosswalk to the active subordinate
administration leaves. `dosismenge_und_einheit` and
`kontinuierliche_gabe_rate` therefore remain `null` in the accepted mapping.

<a id="d1-research"></a>
#### D1 (phase 7) — the occurrence boundary already exists; only branch selection is missing

All three colliding timestamps are `type: datetime`, `min 0 / max 1`, and carry
the **same** `repeat_chain: ["masnahmen.medikamentose_therapie"]`:

| Field | `runtime_blocked` |
|---|---|
| `…anwendungszeiten.startzeitpunkt_der_anwendung` | `SHARED(3)` |
| `…anwendungszeiten.stoppzeitpunkt_der_anwendung` | `SHARED(3)` |
| `…dosierung.zeitangabe.zeitpunkt` | `SHARED(3)` |

So within one medication occurrence there is at most one of each. The enclosing
occurrence rule is **already in place**: the reviewed mapping carries
`for_each` on `masnahmen.medikamentose_therapie` →
`medikamentose-therapie.entry`. D1 needs no new outer occurrence rule, but it
still needs approved **within-occurrence branch selection and construction**;
physical materialization alone is not semantic evidence.

**Precondition met — B3 landed in `6396d62`.** `cda/datatypes.py` now carries
`POLYMORPHIC_COMPLEX_ROOTS = frozenset({"SXCM_TS"})` — the reviewed one-entry
union list this research recommended over an XSD-derived trigger — and the
branches D1 needs are materialized and writable in the regenerated workspace:

| Target | datatype | writable | locations |
|---|---|---|---:|
| `…SXPR_TS.comp_as_IVL_TS.low` | `IVXB_TS` | yes | 1 |
| `…SXPR_TS.comp_as_IVL_TS.high` | `IVXB_TS` | yes | 1 |
| `…SXPR_TS.comp_as_PIVL_TS.period` | `PQ` | yes | 1 |

Sequencing consequence: D1 remains a rule on top of B3 rather than an
independent outer-occurrence workstream. The tempting start→low and stop→high
correspondence still lacks a formal source bridge, while the source dosage
`zeitpunkt` is a datetime and cannot supply the quantity represented by
`PIVL_TS.period`. A future rule must provide the missing semantics and preserve
the `<choice> max 1` and `comp min 2` guards. No rule was added in the
2026-09-04 pass.

<a id="c4-research"></a>
#### C4 (phase 8) — **the premise fails; the rule cannot fire**

C4 proposed a reviewed carry-forward rule with five conditions. Four hold. The
fifth — the one that carries the *meaning* — does not.

| Condition | Verdict | Evidence |
|---|---|---|
| (a) active **open** template `SPEC`-specializes a historical template | **holds** | `1.2.276.0.76.3.1.195.10.4` declares `<relationship type="SPEC" template="1.2.276.0.76.10.2022" flexibility="2014-08-25T00:00:00"/>` and `isClosed="false"` |
| (b) the historical template has a static association **from a concept in the selected concept's identity lineage** to a specific leaf | **FAILS** | see below |
| (c) CDA/RIM expansion exposes the same physical path in the active template | **holds** | `…195.10.4.associatedEntity.id`, `II`, writable, not prohibited |
| (d) that path is unique and its occurrence inside the mapped container is unique | **holds** | exactly one `…/associatedEntity/hl7:id` target, one document location |
| (e) an identifier root is configured | site configuration, unchanged | — |

**Why (b) fails.** The historical template does declare the leaf and its
meaning: `1.2.276.0.76.10.2022` carries
`<element name="hl7:id" datatype="II" id="2.16.840.1.113883.2.6.77.9.26">` with
`<desc language="de-DE">Versichertennummern</desc>`, under an
`associatedEntity` fixed to `classCode="POLHOLD"`. Static associations to that
element exist too, in the active document template's `<representingTemplate>`
block: `concept ref="…3.2.2.808" elementId="…9.26"` and
`concept ref="…3.2.3.808" elementId="…9.26"`.

But those concepts are not in the selected concept's lineage. Tracing the two
chains:

- **selected:** `…3.2.9.21582` "Identifikation" → `inherit` `…3.2.6.21582` →
  `inherit` `2.16.840.1.113883.2.6.77.2.2.60210` "Identifikation", declared in
  an **external** dataset (`…2.6.77.2.2.60200@2015-10-15`);
- **associated:** `…3.2.2.808` and `…3.2.3.808` → both `inherit`
  `…3.2.1.808` **"Versicherungsnummer"** (2014-07-10, `valueDomain type="string"`).

There is no `inherit` or `relationship` edge joining the two. They are
independently rooted concept families that happen to denote the same clinical
thing under different names. Note also that the active compiled target has
`element_id: None` and provenance `source: "cda-rim"` — it carries no ART-DECOR
element identity at all, so even a widened rule would have to match on physical
path rather than element id.

##### A `DEC-021` attachment cannot recover the dropped declarations

Asked directly, the answer is no, for three independent reasons.

1. **An attachment's payload is a contained template, not an element
   declaration.** `DEC-021` fixes "transaction, document template, parent
   template, parent element, CDA child particle, target template revision,
   occurrence constraint and a review reason". `associatedEntity/id` is not a
   standalone template; there is nothing to attach. The decision also *requires*
   that "the named element is declared by that parent template" — an attachment
   extends containment beneath an already-declared element, it does not create a
   declaration.
2. **Nothing is physically missing.** `DEC-021` exists for a leaf that openness
   alone cannot identify. Here openness already did the work: the active
   template is `isClosed="false"`, so the CDA core overlay supplies the omitted
   `AssociatedEntity` children. Of the dropped parent declarations, `hl7:id`,
   `hl7:addr`, `hl7:telecom` and `code/hl7:translation` are present and
   **writable** under the active participant, and `hl7:associatedPerson` is
   present (not writable). The physical gate is already open.
3. **`DEC-021` explicitly does not supply meaning.** In its own words, "an open
   template permits additional CDA-valid content but does not identify a
   particular standalone template or establish dataset semantics." The blocker
   is condition (b), and no containment mechanism touches it.

##### The identified leaf is already active — in a sibling participant

Investigating the attachment question produced a better characterization, and it
corrects the framing this plan inherited from C4. The selected document
instantiates **two** Kostenträger participants, both `typeCode="HLD"` with
`associatedEntity/@classCode="POLHOLD"`:

| Participant | Location | `associatedEntity/id` | Mapped? |
|---|---|---|---|
| `1.2.276.0.76.10.2022` (hl7de-) | `0.14.0` | `0.14.0.2.0`, **`element_id …2.6.77.9.26`**, `source: "template"`, writable, `<desc>Versichertennummern</desc>` | **nothing maps into it** |
| `1.2.276.0.76.3.1.195.10.4` (AKTIN) | `0.15.0` | `0.15.0.1.5`, `element_id: None`, `source: "cda-rim"`, writable | the `hauptkostentrager` group selects this participant; `kostentrager.name` writes `scopingOrganization/name` at `0.15.0.1.1.1` |

So this was never a "carry a historical declaration forward onto an expanded
path" problem. The fully identified Versichertennummern leaf **exists, is active
and is writable** — it sits in a sibling participant element that the dataset
group is not mapped to. Using it would place one logical Kostenträger across two
participant elements at two document locations: a `DEC-006` occurrence-identity
question, not a `DEC-021` containment one, and one a reviewer must answer
(both participants carry the same role codes and the document template declares
both).

**Conclusion.** The only bridge available is name similarity — the dataset's
`implementation` text says "Versichertennummer" and the historical `<desc>` says
"Versichertennummern" — which is precisely the German-label exception the plan
forbids. **C4 is closed as blocked**, `DEC-026` is not written, and the
sequencing table's "+1 (insurance)" is withdrawn. Reopening evidence is exact
and narrow: an upstream `inherit`/`relationship` edge between the `…21582` and
`…808` families, or a new static association from `…21582` to element
`…9.26`. Record it in `known-issues.md` next to the existing insurance entry — or, alternatively, a
reviewed `DEC-006` decision that the `0.14.0` participant is the same
Kostenträger occurrence as `0.15.0`, which would still need its own concept
association before anything could be written.

<a id="c2-research"></a>
#### C2 (phase 8) — re-aimed: there are almost no dropped associations to recover

C2 was framed as "quantify how many of the `primary_evidence: NONE` fields have
*some* association that is currently dropped, and why". Measured on the 25
unmapped fields:

| | Fields |
|---|---:|
| carry **no** terminology association at all in the compiled model | **24** |
| carry at least one | 1 |

There is essentially nothing to recover: the associations do not exist for these
concepts, so neither reverse-`origconcept` traversal nor ambiguity-tolerant
projection can produce them. (The lineage machinery is also not the obstacle —
every unmapped field's concept has an `inherit` edge that resolves inside
`project-evidence.xml` at the first hop.)

What survives is the **second** bullet of C2, and [C4](#c4-research) is now its
motivating case: projecting an association that exists on a *different but
co-denoting* concept family. That is a much larger decision than "make
`REVERSE_EDGES` symmetric" — it is the question of what counts as identity when
two concept families were authored independently. Do not attempt it as a
traversal fix; if it is attempted at all it needs its own decision record and a
bar at least as strict as `DEC-015`.

<a id="c3-research"></a>
#### C3 (phase 8) — the crosswalk target is confirmed, and one latent defect sits next to it

The X-ray `untersuchungsregion` domain is as described: `type: code`,
`formal_terminology.status: "logical"`, **13 inline options**, three carrying
LOINC-shaped synonyms (`30745-4` Thorax, `38008-9` Gesamte Wirbelsäule,
`28561-9` Becken). The MRI counterpart has 15. C3's `concept_map` transform
remains the right shape, and the maintainer-supplied table stays mandatory.

**Latent defect found next door: numeric labels are misread as ordinals.**
`compile/transaction.py:355-361` derives `option_details[...]["ordinal"]` with

```python
re.search(r"(?:^|\b)(?:rankin\s*)?([0-9]+)(?:\s*(?:punkt|score))?(?:\b|$)", text, re.I)
```

which takes the first integer in any synonym or label. Consequences in the
reference model:

- **X-ray region** — LOINC codes become ordinals: Thorax `30745`,
  Gesamte Wirbelsäule `38008`, Becken `28561`.
- **CEDIS** (189 members) — the CEDIS classification numbers become ordinals,
  and range headers collide with members: `'101-150'` and `'101'` both yield
  `101`, `'251-300'` and `'251'` both yield `251`, and so on. The result is
  neither a rank nor injective.
- **`notfallanamnese.unfallanamnese.unfallkinetik`** — "Sturz mit Fallhöhe
  >= 3 m" and "Sturz mit Fallhöhe < 3 m" both yield ordinal `3`, extracted from
  the physical measurement in the label. Wrong *and* non-injective, and it looks
  plausible enough to pass review.
- **GCS** (`gcs_augenoffnen`, `gcs_verbale_antwort`, …) — correct: "1 keine",
  "2 auf Schmerzreiz" are genuine leading ranks. The heuristic works where the
  number *is* the rank.

**Impact today: latent, not live.** The reference mapping uses exactly one
`ordinal` transform, on `scores.modified_rankin_skala_score`, and it supplies an
explicit reviewed `map` rather than consuming the extracted metadata. So nothing
is currently mis-rendered — but the wrong ordinals sit in `model.json` as
evidence a reviewer may act on, and any future generated ordinal proposal would
inherit them.

**Fixed 2026-09-04:** a number must now be a non-hyphenated leading rank or be
accompanied by an explicit rank/score word. If extracted values are not
injective across the option list, the compiler emits no ordinal metadata for
that list. Regression tests retain genuine GCS ranks and reject the X-ray,
CEDIS, and fall-height false positives. C3 itself remains deferred: no complete
reviewed 13-row crosswalk or repeat/coalescing/conflict policy exists, so no
singleton dispatcher or `DEC-025` was added.

<a id="phase78-summary"></a>
#### What this research changes

| Item | Before | After |
|---|---|---|
| C5 | "extend the value model" | structured scalar/range quantities and compiled interval targets implemented; no global PQ-unit rule; dose/rate remain unmapped without a semantic bridge |
| D1 | independent structural rule, "up to +4" | physical branches exist and the outer occurrence boundary is reusable; branch meaning and compound construction remain unproved |
| C4 | `DEC-026`, "+1 (insurance)" | **closed as blocked** — condition (b) fails on evidence; no decision record; claim withdrawn |
| C2 | recover dropped associations | 24 of 25 unmapped fields have no association to drop; survives only as the C4 co-denoting-concept question, which needs its own bar |
| C3 | ConceptMap transform | ordinal defect fixed; ConceptMap/dispatcher deferred until the complete reviewed crosswalk and conflict policy exist |

### Phase 9 — reviewable target candidates for human mapping (next)

Goal: emit a complete CDA. Human review of the remaining 20 unmapped datapoints
is accepted; what is missing is the input to that review. Evidence and the
measured funnel are in
[`docs/analyses/2026-09-04-target-candidate-generation.md`](docs/analyses/2026-09-04-target-candidate-generation.md).

<a id="g1-impl"></a>
#### G1. Per-datapoint candidate list

Files: `compile/reports.py` (new candidate filter beside
`_reportable_cda_target`; details renderer), `compile/mapping.py`
(`_gap_classification`), `tests/test_core.py`, `tests/test_closure.py`,
`docs/decisions.md` (`DEC-011` amend), `docs/mapping-documentation-format.md`.

1. **New candidate filter** — do not reuse `_reportable_cda_target`; it is a
   coverage-headline filter and excludes `datatype_derived` targets, which drops
   CDA/RIM structural children such as `associatedEntity/id`. Keep non-derived
   leaves **and** targets whose provenance `source` is `cda-rim` without
   `datatype`; drop `source: datatype`; drop the fixed CDA-infrastructure
   deny-list; drop already-selected targets. Pool: 594 document-wide.
2. **Scope and type** — restrict to descendants of the datapoint's selected
   container location, then to `logical_types` compatible with the model `type`.
   Result: median 9 candidates, max 34, non-empty for all 20 context-bearing
   unmapped datapoints.
3. **Genericity by role, never by frequency.** A frequency rule deletes
   `hl7:value`. Use the deny-list.
4. **Render** grouped by contained template with IG-style columns (template,
   path, datatype, cardinality, conformance, description, bound value sets) plus
   `non_null_requires`, repeatable-ancestor and already-claimed flags, as a
   "Possible targets (unproven)" section per unmapped field in
   `cda-mapping-details.md`; persist the same list in `gap.reopens_with`.
5. **Acceptance:** the X-ray Untersuchungsregion list surfaces the five reachable
   fixed-code X-ray statements that
   `docs/analyses/2026-09-02-seven-active-profile-gaps.md` found by hand.
6. **Boundary:** an admissibility inventory, never evidence. Nothing
   auto-selects; the coverage headline must not move. Amend `DEC-011` with the
   filter rules so any list is reproducible.

<a id="g2-impl"></a>
#### G2. Declared-endpoint parity check (standing test)

Parse `<element|attribute … id="…">` per in-closure template from the fetched
sources and diff against `{target["element_id"]}` grouped by `template_id`.
Measured today: 2 022 declared, 2 001 compiled, 24 differences in 8 templates —
all fixed structural attributes (`classCode="PSN"`, `determinerCode="INSTANCE"`,
`classCode="ORG"`) folded into the owning node's `fixed` map, which is correct.
**Zero genuine losses**; the compiler is a strict superset of the IG's declared
surface.

Wire it as a test beside `tests/test_closure.py` so "does the compiler see
everything AKTIN publishes?" becomes an assertion. A difference that is not a
fixed structural attribute is a compiler defect.

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
