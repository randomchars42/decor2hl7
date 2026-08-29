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

- `for_each` preserves repetitions;
- `fan_out` creates discriminated target occurrences, including separate logical
  `Pupilsize_right.value` and `Pupilsize_left.value` datapoints backed by the
  repeatable physical `Pupilsize.value`;
- `coalesce` shares equivalent singleton targets and defaults to
  `equal_or_error`;
- `mode: fallback` fills an absent leaf per occurrence without replacing a real
  value.

Evidence: `src/decor2hl7/compile/structural.py`,
`src/decor2hl7/bindings.py`, `tests/test_core.py`.

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

Evidence: `src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/compile/reports.py`,
`docs/mapping-documentation-format.md`.

## Maintenance rule

A pull request that changes project semantics must update the affected decision
entry, known issue, regression test and user-facing documentation together. A
new decision should use the next stable `DEC-*` identifier. Superseded decisions
remain in this register with a link to their replacement.
