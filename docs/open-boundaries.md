# Open boundaries

This register contains only unresolved matters. Each entry names the current
effect and the evidence needed to close it. Resolved behavior belongs in the
relevant topic or reference-transaction page.

## Specification and terminology

### Referral Actions terminology is unavailable

The selected profile's ValueSet `1.2.276.0.76.11.53@2015-11-17` includes
CodeSystem
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`, but that exact CodeSystem is
not published by any located ART-DECOR project or identified DIVI/HL7 Germany
publication. The expansion therefore remains incomplete and the build remains
visibly degraded.

The reviewed finite `Typ Verlegung` conversion is target-scoped and does not
repair this closure. The boundary closes only with the exact publication, an
upstream-confirmed successor identity, or another authoritative complete source
that can be reviewed as an exact artifact.

### Exact historical CCD Product prototype is not published

Template `2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` is referenced as a
SPEC prototype, while the only located published revision is
`2007-04-01T00:00:00`. The newer revision cannot substitute for the request.
The missing prototype is evidence-only for the selected build; children compile
from their own constraints. Reopen only if the exact revision is published.

### Native compiled DECOR project validation is unavailable

The fetched API forms do not provide one native complete compiled DECOR project.
Source-project validation and exact-closure validator generation are available;
the native compiled-project stage remains explicitly `not-run`. It closes with
the producer's complete compiled publication artifact.

### Broad source-project conformance findings remain upstream

The report-only DECOR Core Schematron audit of the broad live project evidence
contains owner-quality errors and warnings. These findings do not redefine the
exact selected closure or mapping, but they remain visible in generated
conformance reports. Resolution requires upstream source corrections; durable
documentation does not copy the volatile event counts.

## Reference-profile semantics

### Presenting-complaint onset needs profile-owner confirmation

The reviewed mapping provisionally places the presenting-complaint onset on
CEDIS Problem Concern Act `effectiveTime/low`. The active template declares
`width` but not `low`; the pinned datatype model makes `low` structurally legal
while generated co-occurrence rules disallow the scalar parent representation.
The mapping remains provisional until the profile owner confirms that `low` is
the intended clinical meaning or publishes a direct association.

### Medication timing remains incomplete

The selected subordinate-administration choice provides atomic `TS`, `PIVL_TS`,
`EIVL_TS`, and `SXPR_TS` alternatives. Application start uses the atomic `TS`;
application stop, structured dosage point, and event-relative repetition remain
intentional nulls. Event offset is narrative only.

Closing this boundary requires an upstream association or a reviewed compound
occurrence rule that defines which source facts select which branch, including
event code and start/stop semantics.

### Some medication payloads have no reviewed structured target

The selected simple medication branch does not establish ingredient name, code,
active-ingredient indicator, or strength/denominator placement. The detail
sibling is not selected by the active profile. The reviewed reference mapping
now preserves ingredient name, code, active-ingredient wording, and verbatim
strength in the occurrence-local medication narrative. This does not assert
structured ingredient semantics. Reopen the structured mapping with an
owner-selected ingredient profile or a separately approved downstream profile
whose code system, strength, and occurrence semantics are complete.

Product name is resolved through the selected simple branch's coded product
representation and the existing medication narrative; it is deliberately not
mapped to the writable name exposed only by open-template CDA/RIM expansion.
Additional dosage instructions and intake instructions are likewise preserved
as separately labelled medication-narrative contributions. A structured
instruction representation remains open and needs direct owner evidence or a
separately reviewed instruction profile; the reviewed narrative contract does
not make a code-system or structured-target claim.

### Structured imaging region remains under-specified

The active MRI statement contains no region-bearing particle. X-ray region has
only a partial set of LOINC-shaped option associations and lacks a complete
code-system-qualified crosswalk plus repeat, coalescing, and conflict policy.
The reviewed reference mapping now preserves MRI and each X-ray region as
labelled Diagnostics-section narrative wording, without claiming structured
semantics. Reopen the structured mapping only with an active region target and
formal binding, or a complete reviewed structured mapping contract.

### EDIS containment remains a local profile overlay

Entries `.10.85`, `.10.86`, and `.10.87` are not contained by the selected
document. Exact reviewed attachments make them available locally. Explicit
upstream containment would allow those overlays to be removed and remains
preferable.

### Isolation cardinality conflicts with the negative branch

The selected dataset requires both the isolation answer and reason, while the
CDA profile prohibits a reason when the answer is negative. Authored reference
scenarios therefore cannot exercise a legal negative-isolation record. Closing
this requires an upstream cardinality or conditional-rule clarification.

## Validation and delivery

### Published AKTIN validation applies stricter content rules

The AKTIN runtime publication `aktin-runtime-20260427T185033` maps the selected
document `.10.93@2026-03-25T11:04:07` to `aktin-nartrv2026-2`. In its document
context, that validator applies closed-content rules to payer code, payer
associated entity, and the Addendum section. These reject CDA/RIM content allowed
by the cached open source templates and the reviewed local EDIS attachments.

Local exact-closure conformance therefore does not establish acceptance by
that receiver publication. Closing this boundary requires an agreed receiver
profile/validator or an explicitly reviewed compatibility mapping that preserves
the intended clinical facts. Do not silently delete mapped content, change the
selected template revisions, or replace receiver validation to obtain a pass.

### Pharmacy extension XSD is not pinned

The CDA package has no Pharmacy schema. Reviewed foreign nodes are checked
against compiled exact paths, removed only for the base CDA/SDTC XSD projection,
and retained for exact Schematron. Stronger validation requires a licensed,
versioned Pharmacy schema and a reviewed package integration.

### Narrative presentation is intentionally minimal

Required entry references resolve to generated section content, but richer
section tables and presentation are not specified. This can be extended without
changing portable field mappings once presentation requirements are agreed.

### Receiver protocol and exactly-once delivery are unspecified

The local spool adapter now defines an atomic, immutable handover: a document
and sidecar become visible together, identical replay is idempotent, and local
SQLite state advances only after publication. Downstream consumption and
acknowledgement of that directory are outside the contract.

The generic HTTP adapter still has no receiver-specific authentication, batch
envelope, acknowledgement parsing, or idempotency contract. In particular, the
crash window between a successful remote POST and local SQLite commit remains
unresolved. Closing the remote boundary requires the concrete receiver protocol
and its durable acknowledgement/state semantics.

### Recovery overlay application is manual

The reference recovery overlay is deterministic and hash-pinned, but applying
it is currently a documented shallow-merge procedure rather than a general CLI
command. A future command must preserve exact identity checks and must not turn
arbitrary overlays into owner-derived evidence.
