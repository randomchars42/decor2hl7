# Stable decision identifiers

This is a secondary index for durable `DEC-*` identifiers used by source-controlled
mapping and recovery metadata. Current policy is defined by the linked topic
pages, where owner rules, decor2hl7 supplements, effective behavior, evidence,
and open boundaries are kept together.

All decisions below are accepted and verified. This file does not preserve the
chronology or superseded rationale behind them; Git history provides that when
needed.

## Project and ownership

### DEC-001 — Canonical source and knowledge

The repository on `main` is authoritative for implementation, tests, and
durable documentation. See [`../Project-decor2hl7.md`](../Project-decor2hl7.md).

### DEC-002 — Three workflows and workspace ownership

Specification mapping, site input configuration, and runtime operation remain
separate ownership domains. See
[`../Project-decor2hl7.md`](../Project-decor2hl7.md#workflows-and-ownership).

### DEC-005 — Target-neutral model and target boundary

The normalized dataset and site-input pipeline remain target-neutral; CDA is
the first target, not the common architecture. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md).

## ART-DECOR authority

### DEC-003 — Transaction and terminology authority

The selected transaction governs selection and usage; formal origins may
supply semantic properties, while revisions and logical/formal domains are not
unioned. See
[`topics/art-decor-authority.md`](topics/art-decor-authority.md#owner-rules-for-dataset-concepts).

### DEC-026 — ART-DECOR examples are non-executable instance data

Examples never become fixed values or absent-source defaults. See
[`topics/art-decor-authority.md`](topics/art-decor-authority.md#executable-owner-grammar).

### DEC-027 — Bounded association formal-origin closure

Mapping-evidence concepts close recursively through formal origins, never
through ordinary relationships. See
[`topics/art-decor-authority.md`](topics/art-decor-authority.md#owner-rules-for-dataset-concepts).

### DEC-031 — Direct template constraints and SPEC prototype diagnostics

Templates compile from stored constraints; first-SPEC prototypes support only
diagnostics and exact reviewed branch selection. See
[`topics/art-decor-authority.md`](topics/art-decor-authority.md#owner-rules-for-templates).

### DEC-037 — Formal origins, relationships, and template prototypes

Concept origins, unchecked relationships, executable template closure, and
editor prototypes retain their distinct owner meanings. See
[`topics/art-decor-authority.md`](topics/art-decor-authority.md).

### DEC-039 — Owner-defined rule pipeline

The compiler applies owner constructs in an explicit order and fails on unknown
executable content instead of inventing semantics. See
[`topics/art-decor-authority.md`](topics/art-decor-authority.md#executable-owner-grammar).

## Retrieval and artifacts

### DEC-004 — Artifact identity, forms, and readiness

Requested and resolved identities, exact revisions, forms, crawl completion,
and build readiness remain distinct. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#identity-and-forms).

### DEC-010 — Missing-artifact tolerance

Unavailable auxiliary evidence may degrade safely; contradictions and mandatory
selected inputs remain fatal. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#missing-and-contradictory-artifacts).

### DEC-012 — External artifact supplements and waivers

Only verified complete builtins can satisfy dependencies; waivers record an
absence without claiming success. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#reviewed-catalog-entries).

### DEC-021 — Open templates and reviewed CDA extension attachments

An exact reviewed attachment may use one legal open slot; openness and generic
context never infer a dependency. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#reviewed-cda-profile-overlays).

### DEC-022 — Reviewed malformed artifact-identity aliases

One exact malformed published key may resolve through one reasoned alias while
both identities remain visible. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#reviewed-catalog-entries).

### DEC-028 — Exact SPEC-choice overlays and profile extensions

One exact selected branch may be replaced only by a proven sibling in the same
first-SPEC prototype choice. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#reviewed-cda-profile-overlays).

## Dataset and terminology

### DEC-006 — Explicit occurrence identity

Source occurrences and independent nested occurrence keys are preserved without
positional guessing. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md#occurrence-identity).

### DEC-016 — Empty owned coded domains and target-governed fallback

An empty owned inline domain is explicitly unconstrained; target-owned
`OTH`/`originalText` behavior remains a separate mapping contract. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md#terminology-views).

### DEC-025 — Conservative ordinal evidence extraction

Only unambiguous rank-bearing labels produce generated ordinal metadata. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md#scalar-constraints).

### DEC-040 — Target-governed coded values and XSD restrictions

Source normalization is target-neutral; exact target bindings and the pinned
XSD govern CDA value admission and serialization. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md#exact-associations-and-reviewed-bridges).

## CDA compilation and conformance

### DEC-013 — Compiled HL7 V3 datatype/value model

CDA compilation produces explicit structural and writable value
representations from the pinned datatype graph. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#datatypes-and-writable-values).

### DEC-014 — Pinned CDA/RIM structural model expansion

ART-DECOR constraints refine the pinned CDA/RIM model while preserving
closedness, prohibitions, physical identity, and XML structure. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#effective-physical-model).

### DEC-019 — DECOR-core and complete CDA validation stack

Pinned source validation, exact-closure validator generation, CDA/SDTC XSD, and
Schematron form independent fail-closed gates. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#schematron-and-assertions).

### DEC-020 — Compound-datatype companion requirements

Non-null compound components require their compiled companions in the same
occurrence. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#datatypes-and-writable-values).

### DEC-023 — Generated Schematron as supporting mapping evidence

Generated structural rules can support or disqualify an existing candidate but
cannot establish source-to-target meaning. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#schematron-and-assertions).

### DEC-024 — Datatype Schematron co-occurrence admissibility

A narrowly parsed error-level presence rule may disqualify an unavoidable
physical representation without creating a semantic bridge. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#schematron-and-assertions).

### DEC-030 — Compiled entry-to-section narrative links

Required entry references and matching section content are generated as
compiler-owned occurrence-local infrastructure. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#examples-fixed-values-and-construction-roles).

### DEC-032 — Namespace-aware ART-DECOR assertion evaluation

Assertions retain source namespace bindings in both the in-process evaluator
and generated Schematron. See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md#schematron-and-assertions).

## Mapping and construction

### DEC-007 — Structural mapping rules

Repetition, discrimination, coalescing, concatenation, fallbacks, and presence
are explicit declarative rules. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#structural-rules).

### DEC-011 — Mapping evidence and documentation

The audit is the structured evidence source; the proposal and three human views
derive from it and the reviewed mapping. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#products-and-review-boundary).

### DEC-015 — Associations through common CDA/RIM slots

A legacy static association projects into an active occurrence only through one
unique common owner-and-particle slot. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#evidence-and-gates).

### DEC-017 — Specification-derived choice, occurrence, and fixed-statement rules

Choice branches, occurrence-boundary targets, boolean polarity, presence, and
system roles require exact compiled evidence. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#structural-rules).

### DEC-029 — Reviewed scalar CDA construction defaults

One exact required writable target may receive one reviewed scalar or null
flavor without activating an optional branch. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#completion-and-ownership).

### DEC-035 — Versioned authored mapping scenarios

Authored CSV scenarios pin release and transaction identity and use independent
expectations rather than generated CDA as their oracle. See
[`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md#mapping-scenarios).

### DEC-038 — Source-controlled recovery of reviewed CDA overrides

Proposal-null human decisions are preserved in an exact model/CDA-hash-pinned
recovery overlay. See
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md#reproducibility-and-recovery).

### DEC-041 — Explicit site-owned CDA construction requirements

Portable mapping may delegate a required target to one validated site channel
without embedding the site value. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#completion-and-ownership).

### DEC-042 — Reviewed finite coded maps across an unresolved exact binding

One fully enumerated reviewed conversion may authorize outputs for one exact
unresolved target binding without repairing the terminology closure. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md#exact-associations-and-reviewed-bridges).

## Reference-transaction policy

### DEC-008 — Diagnosis certainty and effective time

V/A/Z/G maps to certainty, `A` also controls negation, and absent onset uses a
reviewed unknown value rather than an invented date. See
[`reference-transaction.md`](reference-transaction.md#diagnoses-and-referral).

### DEC-009 — Secondary ICD-10 diagnoses

The field is intentionally unmapped because the selected profile provides no
target occurrence; `CD.translation` would express the wrong semantics. See
[`reference-transaction.md`](reference-transaction.md#diagnoses-and-referral).

### DEC-018 — Neutral-example boolean discriminator occurrences

Exact confirmed agent examples may discriminate allergy boolean occurrences
under the bounded structural and terminology rule. See
[`reference-transaction.md`](reference-transaction.md#allergy).

### DEC-033 — Reviewed allergy time construction

Admission time completes an already active allergy concern; unknown clinical
onset and completed assertion status remain distinct reviewed values. See
[`reference-transaction.md`](reference-transaction.md#allergy).

### DEC-036 — Selected profile medication branch is baseline authority

The reference mapping follows the exact simple branch selected by the active
profile rather than its richer SPEC sibling. See
[`reference-transaction.md`](reference-transaction.md#medication).

### DEC-043 — Reviewed medication-administration mappings and intentional nulls

Dose, rate, start, body site, route, conditional form, coded product
composition, and narrative rules are reviewed; unsupported timing and
non-transmitted fields remain explicit nulls.
See [`reference-transaction.md`](reference-transaction.md#medication).

### DEC-044 — Reviewed narrative-only facts and labelled section presentation

Present executable mappings as labelled, occurrence-preserving section
narrative content. A separate checked `narratives` contract may preserve exact
reviewed source wording without asserting a structured CDA value mapping. The
reference MRI fact and repeated X-ray regions use that contract. See
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#narrative-presentation)
and [`reference-transaction.md`](reference-transaction.md#imaging).

### DEC-045 — Medication ingredient and instruction wording

In the selected simple medication branch, preserve ingredient name and code,
the explicit active-ingredient answer, verbatim strength, additional dosage
instructions, and patient intake instructions as separately labelled,
occurrence-local contributions to `Medikation.text`. This reviewed narrative
contract does not select the uncontained detail sibling, infer a code system or
strength ratio, or assert a structured CDA ingredient or instruction target.
See [`reference-transaction.md`](reference-transaction.md#medication).

### DEC-046 — Reviewed local model extensions and AKTIN CDA supplements

When a clinically approved CDA requirement is absent from the selected
ART-DECOR dataset, a versioned `decor2hl7.json:model_extensions` block may add
one collision-checked, target-neutral scalar field under an existing group.
Coded additions require an exact complete local ValueSet revision. The CDA
assignment or derivation remains a separate reviewed mapping decision. For the
reference transaction, the approved payer, transport-arrival, diagnosis-
laterality, receiving-department, time, and exact AMRO rules are retained by
the hash-bound recovery overlay. See
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md#reviewed-local-model-extensions),
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md#declarative-transforms),
and [`reference-transaction.md`](reference-transaction.md#other-reviewed-construction).

## Runtime and delivery

### DEC-034 — Bounded receiver transport adapters

Transport selects a built-in adapter with a closed validated option schema;
arbitrary imports and unspecified protocol behavior are excluded. The local
spool adapter publishes an immutable XML/sidecar directory atomically and
commits state afterward; downstream acknowledgement is a separate boundary. See
[`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md#transport).

## Maintenance

A semantic or architectural change must update its topic page, affected open
boundary, regression tests, and user-facing documentation in the same pull
request. Add a new `DEC-*` identifier only when durable mapping or recovery
metadata needs a stable reference; do not create an entry merely to record
implementation chronology.
