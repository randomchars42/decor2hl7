# Project decision register

This register is the durable index of semantic and architectural decisions for
`decor2hl7`. Conversation text, dated analyses and experimental branches provide
evidence, but they do not become project policy until recorded here and merged
to `main`.

Each entry has two independent states:

- **Decision:** `open`, `accepted`, `rejected`, or `superseded`.
- **Implementation:** `none`, `partial`, `implemented`, or `verified`.

An accepted decision is not necessarily implemented; an implemented mechanism
is not necessarily an accepted clinical policy.

| ID | Decision | Decision state | Implementation |
|---|---|---|---|
| DEC-001 | Canonical source and knowledge | accepted | verified |
| DEC-002 | Three workflows and workspace ownership | accepted | verified |
| DEC-003 | Transaction and terminology authority | accepted | verified |
| DEC-004 | Artifact identity, forms and readiness | accepted | verified |
| DEC-005 | Target-neutral model and target boundary | accepted | implemented |
| DEC-006 | Explicit occurrence identity | accepted | verified |
| DEC-007 | Structural mapping rules | accepted | verified |
| DEC-008 | Diagnosis certainty and effective time | accepted | verified |
| DEC-009 | Secondary ICD-10 diagnoses | open | none |
| DEC-010 | Missing-artifact tolerance | accepted | verified |
| DEC-011 | Mapping evidence and documentation | accepted | verified |
| DEC-012 | External artifact supplements and waivers | open | partial |
| DEC-013 | Compiled HL7 V3 datatype model | accepted | verified |
| DEC-014 | Pinned CDA/RIM structural model expansion | accepted | implemented |

## DEC-001 — Canonical source and knowledge

**Decision:** accepted
**Implementation:** verified

`randomchars42/decor2hl7` on `main` is authoritative for implementation, tests
and durable repository documentation. Chat and Library materials are working
context or dated evidence. No current source tree is maintained outside GitHub.

Evidence: `Project-decor2hl7.md`, repository history.

## DEC-002 — Three workflows and workspace ownership

**Decision:** accepted
**Implementation:** verified

Specification/target mapping, site/input configuration and runtime operation are
separate workflows. Portable CDA mappings and their guides live under
`mapping/`; local CSV/code/site configuration and its guides live under `site/`.
The same reviewed mapping may be used by several sites.

Evidence: `README.md`, `Project-decor2hl7.md`, `src/decor2hl7/workspace.py`,
`tests/test_cli.py`.

## DEC-003 — Transaction and terminology authority

**Decision:** accepted
**Implementation:** verified

The exact selected transaction controls selection, cardinality and direct formal
terminology. Source/project/history may fill only explicitly missing properties
through identity lineage. Logical choices and exact formal coded domains remain
separate; revisions are not unioned. Lossy crosswalks require an explicit
reviewed rule.

Evidence: `docs/analyses/2026-08-26-authority-and-artifact-audit.md`,
`src/decor2hl7/compile/transaction.py`, `src/decor2hl7/compile/terminology.py`.

## DEC-004 — Artifact identity, forms and readiness

**Decision:** accepted
**Implementation:** verified

Artifact identity includes type, OID, effective date and repository context.
Source, analysis and expansion forms have different purposes and are not blindly
merged. Dynamic resolutions are frozen. `crawl_complete` and `build_ready` are
independent states. Repository resolution uses explicit link/prefix, configured
hints and cached ownership before OID inference and HTTP probing.

A valid dependency analysis form is sufficient for cache/build availability;
missing dependency source sidecars are optional evidence and are not backfilled
by an ordinary rerun. The selected transaction still requires both forms. A
cache-only fetch makes no HTTP attempts, reconstructs closure from valid local
files, and records uncached references as unavailable so a later online fetch
will retry them.

Evidence: `docs/architecture.md`, `src/decor2hl7/retrieval/`.

## DEC-005 — Target-neutral model and target boundary

**Decision:** accepted  
**Implementation:** implemented

The normalized dataset model and site input configuration do not depend on CDA.
CDA is the first target; a future FHIR target should reuse acquisition,
normalization, validation, occurrence and state infrastructure. ART-DECOR is a
setup-time concern; runtime consumes compiled models only.

Evidence: `Project-decor2hl7.md`, `docs/architecture.md`.

## DEC-006 — Explicit occurrence identity

**Decision:** accepted  
**Implementation:** verified

One source occurrence remains one target occurrence. Missing values do not shift
sibling occurrences. Independent nested repetitions require occurrence keys;
ambiguous positional zipping is unsupported. Diagnosis rows therefore retain
their own code, text, certainty, leading flag and mapped CDA values.

Evidence: `src/decor2hl7/data.py`, `src/decor2hl7/bindings.py`,
`tests/test_core.py`.

## DEC-007 — Structural mapping rules

**Decision:** accepted  
**Implementation:** verified

Structural semantics are explicit and declarative:

- `for_each` preserves repetitions and explicitly binds each source repeat
  group to a named CDA repeat node. Target repeat ancestors not bound by a
  source group become one shared container; this permits one medication section
  containing one entry per repeated dataset medication without positional
  guessing;
- `fan_out` creates discriminated target occurrences, including separate logical
  `Pupilsize_right.value` and `Pupilsize_left.value` datapoints backed by the
  repeatable physical `Pupilsize.value`;
- `coalesce` shares equivalent singleton targets and defaults to
  `equal_or_error`;
- `mode: fallback` fills an absent leaf per occurrence without replacing a real
  value.

Evidence: `src/decor2hl7/compile/structural.py`,
`src/decor2hl7/bindings.py`, `src/decor2hl7/validate.py`,
`tests/test_core.py`,
`docs/analyses/2026-08-30-medication-mapping-plan.md`.

## DEC-008 — Diagnosis certainty and effective time

**Decision:** accepted  
**Implementation:** verified

V/A/Z/G maps to the formal certainty qualifier within each diagnosis
occurrence. `A` additionally controls exclusion negation. The compiler does not
derive `effectiveTime/high` from `Z`: “Zustand nach” contains no timestamp.

The CDA template requires `effectiveTime/low`. Because the selected transaction
does not provide diagnosis onset, the generated mapping supplies the reviewed
target default `nullFlavor="UNK"`. A real onset wins in its occurrence.

The generic runtime can execute an explicitly configured occurrence-local
fallback, including an unknown boundary, but that capability is not generated
as a Z clinical rule.

Evidence: `src/decor2hl7/compile/mapping.py`, `src/decor2hl7/bindings.py`,
`tests/test_core.py`, `docs/known-issues.md`.

## DEC-009 — Secondary ICD-10 diagnoses

**Decision:** open  
**Implementation:** none

Concept 29508 is `0..1` in the selected transaction while historical material
has exposed `0..*`. The intended CDA occurrence/relationship and association
with text, certainty and the leading diagnosis require AKTIN clarification.
Until then it remains unmapped: no delimiter parser, `CD.translation`, or
inferred additional Problem Observation is introduced.

Evidence: `docs/known-issues.md`.

## DEC-010 — Missing-artifact tolerance

**Decision:** accepted  
**Implementation:** verified

Unavailable auxiliary artifacts are reported and omitted when the selected
build can be compiled safely. Missing representing templates, selected
transaction forms, corrupt successful artifacts and exact-identity
contradictions remain fatal. Static references are never silently replaced by
another revision.

Evidence: `src/decor2hl7/compile/artifacts.py`, `docs/architecture.md`,
`docs/known-issues.md`.

## DEC-011 — Mapping evidence and documentation

**Decision:** accepted  
**Implementation:** verified

`mapping-audit.json` is the structured evidence/decision product.
`cda-mapping.proposed.json`, `cda-mapping.md` and
`cda-mapping-details.md` derive from the same analysis. The concise guide shows
human names, exact keys, contextual read-only XML and explicit candidate/result
classes. Configuration is edited in JSON, never in generated Markdown or XML.

A dataset code may map directly to an unfixed writable CDA `hl7:code` element
when both sides use coded datatypes and share an explicit ValueSet. This permits
formally associated payloads such as the referral source while preventing a
dataset value from replacing a fixed or differently bound structural section
code.

Evidence: `src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/compile/reports.py`,
`docs/mapping-documentation-format.md`.

## DEC-012 — External artifact supplements and waivers

**Decision:** open — review required
**Implementation:** partial — provisional phase 1

ART-DECOR references may identify specifications or terminologies whose content
is maintained only by an external publisher. A provisional phase-1 mechanism
extends the exact-identity source catalog with two deliberately small modes:

- `builtin` materializes a reviewed package-local XML supplement, verifies its
  catalog checksum and requested identity, and records external provenance and
  completeness in `manifest.json`;
- `waiver` settles a known absence with cited reasoning but never claims an
  artifact is successful. It remains visible as unavailable compiler input and
  therefore keeps the affected build degraded.

Both modes work during `fetch --offline`. `spec/` remains a generated cache:
the durable recipe and small redistributable supplement live in the repository,
while `fetch` materializes them under the selected release. A missing manifest
is rebuilt from valid deterministic cache files or package supplements; cached
bytes are not trusted when an existing manifest checksum, a builtin catalog
checksum, requested identity or static revision contradicts them.

The implementation does not establish a generic scraper or publisher API
framework. It also does not decide that every current catalog entry is
authoritative. The initial completeness claim for CodeSystem
`1.2.276.0.76.5.401`, the provisional split-dose waiver, redistribution terms,
and the rules by which an external artifact may satisfy a required dependency
must be reviewed before this decision can be accepted.

The IHE Medicine Entry
`1.3.6.1.4.1.19376.1.9.1.3.1@2019-08-27T16:13:43` is not a candidate for a
builtin: its exact analysis form is already resolved through the `ch-pharm-`
source hint and satisfies dependency availability under `DEC-004`. The missing
source form is optional evidence. Its constraints remain unlocated in the
selected AKTIN document, whose effective medication branch uses
`UV Medication Information (simple)`; external-artifact handling must not be
used to alter that template relationship.

Evidence: `docs/analyses/2026-08-30-external-artifact-phase-1.md`,
`docs/analyses/2026-08-30-medication-mapping-plan.md`,
`src/decor2hl7/retrieval/sources.py`,
`src/decor2hl7/retrieval/fetch.py`, `tests/test_external_sources.py`.

## DEC-013 — Compiled HL7 V3 datatype model

**Decision:** accepted
**Implementation:** verified

CDA compilation combines the fully resolved ART-DECOR constraint tree with a
deterministic HL7 V3 datatype catalogue before mapping begins. The catalogue is
compiler knowledge derived from HL7 Version 3 Data Types Release 2 and CDA R2;
it is package-local and requires no build-time network access. The effective
template produces its datatype inventory automatically. Every declared type is
classified as a datatype, constrained alias, structural model type, or explicit
unsupported error.

The compiled target model distinguishes structural nodes from writable value
targets. Every writable target carries a compiled value representation (element
text, XML attribute, identifier, timestamp, quantity, coded value or boolean)
and logical input types. Mapping consumes that metadata instead of path-name
leaf heuristics; rendering consumes it instead of interpreting datatype names a
second time. ART-DECOR constraints override generic datatype cardinality,
conformance, fixed values and datatype refinements. Optional legal datatype
parts are instantiated only when assigned, required, fixed or needed as an
ancestor.

CDA-specific compilation, datatype modelling and rendering live in
`decor2hl7.cda`. Generated `cda.json`, mappings and documentation are rebuilt;
no compatibility adapter for the former generated representation is retained.
Structural occurrence rules from `DEC-007`, including medication `for_each` and
pupil-side `fan_out`, remain authoritative because datatype expansion supplies
legal XML value structure, not source/target occurrence semantics.

Evidence: `src/decor2hl7/cda/`, `src/decor2hl7/semantics.py`,
`tests/test_cda_datatypes.py`, `tests/test_core.py`.

## DEC-014 — Pinned CDA/RIM structural model expansion

**Decision:** accepted
**Implementation:** implemented

`fetch` caches the official HL7 CDA R2 normative XSD definition set pinned to
commit `e922fc35586fd2629f0c8a021080bca9ab424e18`. CDA compilation indexes XSD
definitions by name, follows extension inheritance, resolves structural element
names procedurally, overlays ART-DECOR constraints, and then runs datatype/value
representation expansion. Generated nodes retain `cda-rim`, `datatype`, or
combined template provenance. Mapping and rendering contain no per-class rules.

Medication `for_each` and pupil-side `fan_out` remain under DEC-007 because the
model describes legal XML structure, not occurrence ownership or laterality.

Evidence: `src/decor2hl7/cda/core.py`, `src/decor2hl7/cda/compile.py`,
`tests/test_cda_datatypes.py`.

## Maintenance rule

A pull request that changes project semantics must update the affected decision
entry, known issue, regression test and user-facing documentation together. A
new decision should use the next stable `DEC-*` identifier. Superseded decisions
remain in this register with a link to their replacement.
