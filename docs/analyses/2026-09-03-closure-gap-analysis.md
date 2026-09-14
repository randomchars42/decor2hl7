# ART-DECOR closure gap analysis (PLAN workstream A1)

> Historical snapshot. The exact selected validator described here has since
> been narrowed to its formally closed 119 effective-dated revisions and now
> generates without messages. The artifact-gap evidence below remains a record
> of the earlier closure state.

Date: 2026-09-03

Status: evidence snapshot. Documents why the reference `spec/2026.1.2` closure
is `degraded` and what in-repo work would close it. No code or mapping change is
made here.

## Method and evidence

- A fresh `decor2hl7 fetch` run against the selected release `2026.1.2` and
  transaction `notaufnahmeregister--60` (console output captured 2026-03).
- The resulting `spec/2026.1.2/` cache: `manifest.json`, `artifact-owners.json`,
  `transactions/notaufnahmeregister--60/closure.json`, and direct inspection of
  cached `templates/`, `valuesets/`, `datasets/`.
- The generated validator artifacts under
  `model/2026.1.2/notaufnahmeregister--60/conformance-validation/`
  (`validator-manifest.json`, `generation-messages.txt`).
- Reference code: `retrieval/fetch.py`, `retrieval/references.py`,
  `retrieval/resolution.py`, `retrieval/artifacts.py`
  (`REQUIRED_ROLES = {structure, formal-terminology, expansion-support}`).

## Headline

| Statement | Evidence |
|---|---|
| The crawl reports **62 missing artifacts** but only **21 are build-degrading**. | `closure.json`: `degraded_resources` = 21; `missing` = 62. |
| The other 41 (20 templates, 22 concepts minus overlap) are **evidence-only** and already `optional`. | They appear in `missing` / `optional_references`, never in `degraded_resources`; most are reached through `ADAPT`/live-evidence edges. |
| The 65 validator generation errors are a **separate problem** from the missing list. | Every ValueSet named in `generation-messages.txt` has its **definition** cached; what is missing is the **expansion**. |
| The plain `fetch` did **not** re-probe any settled failure. | Console shows `known missing` for all 62; only 4 genuinely new references were requested (`[1/1500]`…`[4/1500]`) and **all 4 resolved instantly** (~200 B stubs) via `hl7de-` / `hl7ips-`. |
| The request budget is not the constraint. | `recursive HTTP request(s): 4` against `--max-requests 1500`. |

Update 2026-09-03: `decor2hl7 fetch --retry-missing` has since been run online.
It recovered only the three DEC-021 EDIS entry templates
(`1.2.276.0.76.3.1.195.10.85` / `.86` / `.87`) and one of their dependencies
(`2.16.840.1.113883.10.12.328`) — and those came back because the reviewed
`config/cda-extensions.json` attachments now make them exact structural
dependencies, not because re-probing unstuck the closure. **None of the 21
build-degrading resources changed.** This confirms the prediction below: they
need code changes (S2 reference-identity, cluster hints), reclassification (G1),
`$expand` (G2/A6), or a reasoned waiver — not a retry.

## The 21 build-degrading resources

All 17 degrading code systems carry role `['expansion-support']` in
`closure.json::resource_roles`; the two datasets carry `['structure']` and the
one template `['structure']`, the one value set `['formal-terminology']`. A
degrading resource is any key in `roles["build"]` with a `REQUIRED_ROLE` and a
non-`ok` status (`fetch.py:1542`, `required_failures`).

### Why 17 code systems degrade

`references.py::collect_references` assigns `expansion-support` (a
`REQUIRED_ROLE`) to **every** `<include codeSystem="…">` it sees
(`references.py:190`), and `crawl_build` recursively closes every
`REQUIRED_ROLE` reference of every fetched build resource — including
**contained concepts** pulled in as `structure`. So a code system becomes
build-degrading merely by appearing in an `<include>` inside the value domain
of *any* transitively contained concept, whether or not that concept supplies a
selected datapoint or an active binding.

Verified split of the 17:

| Group | Code systems | Where the `<include>` lives | Selected? |
|---|---|---|---|
| **G1 — value domain of an unselected contained concept** | `1.2.276.0.76.3.1.131.1.5.1` (DKG), `2.16.840.1.113883.15.16` (TNM 8), `2.16.840.1.113883.6.43.1` / `.6.43.2` (ICD-O-3), `2.16.840.1.113883.6.174` (OMIM), `2.16.840.1.113883.6.3` (ICD-10) | `<include>` in `conceptList` under `<valueDomain type="text">` / `type="code"` of concepts `2.16.840.1.113883.2.6.60.6.2.44` / `.45` / `.47` / `.104` — AKTIN **cancer-registry** concepts contained via dataset `…3.1937.777.24.1.1` | **No.** `model.json` has **0** fields referencing `…2.6.60.6.2.*`. |
| **G2 — ValueSet bound only on an inactive C-CDA / IHE / VSAC branch** | `2.16.840.1.113883.6.88` (RxNorm), `.6.8` (UCUM), `.6.59` (CVX), `.4.9` (UNII), `.12.292`, `.6.121`, `.6.10`, `1.2.36.1.2001.1005.17` (AU) | `<include>` in VSAC / NCPDP value sets `2.16.840.1.113762.1.4.1010.*`, `2.16.840.1.113883.3.88.12.80.*`, `…1.11.11526`, `…4.642.3.1024` reached through the `2.16.840.1.113883.10.21.4.*` UV Medication lineage | Present in `cda.json` structure (3× each) but not proven a `required` intensional binding on a writable active target. |
| **G3 — genuinely-active AKTIN binding** | `1.2.276.0.76.3.1.195.5.53@2019-12-30` | `<include>` in ValueSet `1.2.276.0.76.11.53`, which **is** a build dependency of the selected transaction | **Yes.** Already recorded in `known-issues.md`. |
| **G4 — ISO country codes** | `1.0.3166.1` | `<include>` in `2.16.840.1.113883.1.11.16040` (HL7 country codes); appears 8× in `cda.json` | Needs the A4 check to decide — plausibly an active address binding. |

The earlier draft of this section claimed six of these had "0 intensional
includes"; that was a `grep` artifact (multi-line `<include>` elements, and
includes inside concept `conceptList`s rather than stand-alone value sets). The
`resource_roles` map is authoritative: all 17 are `expansion-support`.

### G1 — reclassify (PLAN A4), no fetch, no loss

`references.py` should **not** emit `expansion-support` for an `<include
codeSystem>` when either:

1. the enclosing `<valueDomain>` is `type` other than `code` (a free-text or
   quantitative domain never needs coded membership — `DEC-016`); or
2. the same `conceptList` / value domain already carries inline enumerated
   `<concept code=… codeSystem=…>` or `<exception>` members (the enumerated set
   is the executable domain; the `<include>` is supplementary — `DEC-016`,
   `compile/terminology.py` `accepted_values`).

In those cases assign `display-evidence`. Concept `…2.6.60.6.2.44` is
`<valueDomain type="text">`; `…2.6.60.6.2.104` is `type="code"` with 9 inline
concepts plus one exception. Both satisfy the rule.

Complementary compile-side check: `compile/artifacts.py::write_build_diagnostics`
should report a **crawl-degraded** set (informational: everything with a
`REQUIRED_ROLE` that failed) separately from a **build-degraded** set (the
expansions the compiler actually needed for a selected mapping or the generated
validator and did not get). Only the second should set `status: degraded`.

Expected: G1's 6 code systems leave `degraded_resources`; degrading count
21 → ~15.

### G2 — `$expand` the ValueSet, else reclassify, else waiver

1. Try `$expand` on the **including ValueSet** (not the code system): the
   ART-DECOR terminology endpoint can expand some external memberships server
   side. This is PLAN A6 (expansion is currently never requested for `dynamic`
   bindings).
2. If the A4 active-binding check shows the ValueSet is bound only on a
   non-writable / inactive-profile target: reclassify to `display-evidence`.
3. If a specific active expansion needs a specific small subset: reviewed
   `builtin` (`DEC-012`, `retrieval/external/`).
4. Otherwise: reviewed `waiver` (`DEC-012`) — never a fabricated membership.

Large proprietary terminologies (RxNorm, UNII) end at step 3 or 4.

### G3 / G4 — genuine residue

`1.2.276.0.76.3.1.195.5.53@2019-12-30` stays degrading until A2's
`--retry-missing` resolves it from `aktin-` or it gets a reasoned `waiver`
(already flagged in `known-issues.md`). `1.0.3166.1` is decided by the A4
active-binding check.

### S1 — exact static template revision absent (another revision cached)

| Requested | Cached instead | Role |
|---|---|---|
| `template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` | `@2007-04-01` from `pmp-` (`artifact-owners.json`) | `SPEC` parent of `1.3.6.1.4.1.19376.1.5.3.1.4.7.2` (IHE Medications) and `1.2.276.0.76.10.4025` (German Material) — **medication branch** |

Static references are exact (`DEC-004`/`DEC-010`): the `2007-04-01` revision must
not silently satisfy the `2005-09-07` request.

**Action:**

1. Research whether the `2005-09-07` revision (original HL7 CCD 1.0 "Product"
   template) is published in an HL7 / CCD ART-DECOR project; add a source hint
   and `--retry-missing`.
2. If genuinely gone: reviewed `waiver`, then verify in `cda/compile.py` that
   `SPEC` refinement degrades safely — the child (`…4.7.2`, `…10.4025`) must
   still compile from its own constraints plus CDA/RIM expansion, and the
   omission must be scoped to the refinement. Add a regression test (PLAN B1).
   Because this parent sits in the medication branch, confirm no currently
   executable medication mapping regresses and check whether recovering it
   exposes the product-form / ingredient slots that are today "no target".

### S2 — AKTIN datasets, wrong request identity

| Requested as | Reference actually carries |
|---|---|
| `dataset:2.16.840.1.113883.2.6.60.3.1.2 @ dynamic` | `prefix="aktin-" datasetEffectiveDate="2015-11-01T00:00:00"` (in dataset `…777.75.1.2`) |
| `dataset:2.16.840.1.113883.2.6.60.3.1.3 @ dynamic` | same |

The crawl requested `@ dynamic` and settled `known missing`, although the
containing dataset gives an explicit `aktin-` project and `2015-11-01` effective
date.

**Action:** fix `retrieval/references.py` / `retrieval/fetch.py` so an explicit
`datasetEffectiveDate` + `prefix` on a dataset reference is used instead of
`dynamic`; `--retry-missing`. These are old AKTIN "Basisdaten" datasets and are
very likely still served by the `aktin-` project. If they resolve, they may
enrich omitted dataset-context constraints (`DEC-003` identity lineage).

### S3 — IHE value set

| Missing | Note |
|---|---|
| `valueset:1.3.6.1.4.1.19376.1.3.11.11@2015-11-22T12:20:34` | Not referenced by any cached template/ValueSet directly; reached only through an unresolved `1.3.6.1.4.1.19376.*` IHE template. Low priority. |

**Action:** attempt via an IHE PCC source hint on `--retry-missing`; otherwise
`waiver`.

## The 41 evidence-only missing artifacts (non-degrading)

Recorded here so a future crawl change does not accidentally promote them to
blockers.

| Cluster | Count | How reached | Verdict |
|---|---:|---|---|
| `template:2.16.840.1.113883.3.2898.10.*` | 9 | referenced from AKTIN accident/trauma templates (`…195.10.28/29/30/32`); no owner in `artifact-owners.json`, absent from `project-evidence.xml` | evidence-only; resolution has no ownership info and settled after OID-prefix/probe failure. A source hint mapping the `…3.2898` prefix to its owning project would recover them as evidence, not as build inputs. |
| `template:2.16.840.1.113883.17.3.10.1.*` | 5 | `<relationship type="ADAPT" …>` from template `1.2.276.0.76.10.3054` | evidence-only by policy: `ADAPT` is a `WEAK_EDGE` and is explicitly **not** identity inheritance (`DEC-003`, `architecture.md`). Recovering them adds lineage evidence only. |
| `concept:2.16.840.1.113883.3.1937.777.24.2.*` | ~19 | direct evidence pass (`non-recursive`) | evidence-only; do not block build. |
| `concept:mide-dataelement-40`, `concept:psr-dataelement-108` | 2 | direct evidence | evidence-only. |
| `template:1.2.276.0.76.10.2003@2013-07-10`, `1.2.276.0.76.10.4002@dynamic` | 2 | direct evidence | German building blocks genuinely absent; evidence-only. |
| malformed OIDs (see below) | 2 | — | — |

### Malformed upstream identities (PLAN A3)

| Requested (malformed) | Intended | Status |
|---|---|---|
| `codesystem:2.16.840.1.1138836.96` | `2.16.840.1.113883.6.96` (SNOMED CT) | The **correct** OID was requested elsewhere in the same run and resolved `ok via hl7de-`; only the typo variant is `known missing`. |
| `template:2.16.840.1.1133883.17.3.10.1.34` | `2.16.840.1.113883.17.3.10.1.34` (`1133883` → `113883`) | evidence-tier `ADAPT` cluster |

**Action:** a reviewed `alias` mode in `retrieval/sources.json` mapping a
known-malformed requested identity to the corrected one, keeping both identities
on the stored record (`DEC-004` requested-vs-resolved). New `DEC-022`. The
upstream definition is untouched.

## The separate problem: value-set expansion (PLAN A6)

`validator-manifest.json`: `executable: false`, `complete: false`, 65
`generation_messages`, all of the form:

```
value set skipped for use in schematron because the value set contents are
missing - value set <oid>: dynamic in rule <name> …
```

Distinct value sets involved include `1.2.276.0.76.11.51` (~20 diagnostic-result
rules), `1.2.276.0.76.11.49` / `.50` (pupils), `1.2.276.0.76.3.1.195.11.*`
(AKTIN triage/accident), and `2.16.840.1.113883.1.11.15933` (HL7 ActStatus,
~10 rules).

Every one of these has a cached **definition** under `spec/2026.1.2/valuesets/`.
What is missing is a materialized **expansion**. Root causes in `fetch.py`:

- expansion is requested only when the ValueSet has an `<include>` **and** a
  truthy `resolved_date` (`fetch.py:1231`); `dynamic` bindings — the majority
  here — get no `$expand` call;
- `_valueset_complete` (`fetch.py:162`) returns `True` for any set with one
  inline `concept`/`exception`, so a set that is partly inline plus an
  unresolved `<include>` passes as complete;
- the console for this run shows **no** `requesting expansion` lines at all.

**Action (A6):**

1. When the selected transaction binds a ValueSet `dynamic`, freeze the newest
   revision (already done for identity, `DEC-004`) and also request its
   `$expand`, storing the result as frozen `expansion` evidence.
2. Tighten `_valueset_complete`: a set with an `<include>` of an unresolved code
   system is incomplete.
3. `2.16.840.1.113883.1.11.15933` (HL7 ActStatus) is small and standard — a
   strong `builtin` candidate or a direct `$expand` from the HL7 project.
4. Feed frozen expansions into `conformance.py` validator generation and into
   `compile/terminology.py::accepted_values`, so both the 65 errors drop and
   blocked `VALUE_SET_ENUM` mappings become executable — without ever falling
   back to logical-only labels (`DEC-003`, `DEC-016`).

## Recommended sequence for workstream A

| Step | Command / change | Expected result |
|---|---|---|
| 1 | `decor2hl7 fetch --retry-missing` (online) | re-probe the 62 settled failures; the 4 new refs this run resolved instantly, so expect several more to clear |
| 2 | Fix explicit-effective-date/prefix use for dataset refs (`references.py`) + retry | B4 datasets `2.6.60.3.1.2/.3` resolve or become a reasoned waiver |
| 3 | OID-prefix → project source hints for `…3.2898` and `…17.3.10.1` clusters | 14 templates recovered as **evidence** |
| 4 | `alias` catalog (`DEC-022`) | 2 malformed identities resolved |
| 5 | `display-evidence` vs `expansion-support` reclassification + crawl-vs-build degraded split (`DEC-010` amend) | −6 degrading code systems (G1); G2 narrowed to genuine active bindings |
| 6 | ValueSet `$expand` for `dynamic` bindings + tighten `_valueset_complete` (`DEC-013`/A6) | 65 → ~0 validator generation errors; enum mappings unblocked; G2 `$expand` attempts |
| 7 | Research + `builtin`/`waiver` for the residual G2/G3/S1/S3 items (`DEC-012`) | closure honestly `degraded: false` or each remaining gap cited |
| 8 | Regression guard: pin degraded-resource and validator-error counts (`tests/`) | closure cannot silently regress |

After steps 1–6 the degrading set should be a small, named residue of genuinely
unavailable external content, each carrying a reviewed `builtin` or `waiver`
record rather than an unexplained warning.

## Decision-record impact

| Record | Change |
|---|---|
| `DEC-010` | amend: display-evidence vs expansion-support classification |
| `DEC-012` | concrete `builtin`/`waiver` entries for residual B2/B3/B5; move toward `accepted` |
| `DEC-013` | amend: frozen `$expand` for dynamic bindings |
| `DEC-022` (new) | reviewed `alias` correction of malformed upstream identities |
