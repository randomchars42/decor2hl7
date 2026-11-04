# Open boundaries

This register contains only unresolved matters. Each entry names the current
effect and the evidence needed to close it. Resolved behavior belongs in the
relevant topic or reference-transaction page.

## Specification and terminology

### Historical reference Referral Actions terminology is unavailable

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

For the separate `2026.1.3` snapshot, this ValueSet is extensional and complete;
it no longer needs the missing CodeSystem to establish its members. That does
not publish the historical CodeSystem. Its selected source still exposes logical
referral options outside the complete formal binding. Those options require
owner alignment and remain rejected under the
[new profile contract](reference-2026.1.3.md).

### New source and CDA transport domains differ

In release `2026.1.3`, source Transportmethod binds to
`1.2.276.0.76.11.41@2024-02-14T09:42:48` while the CDA observation binds to
the same OID at `2015-11-17T00:00:00`. The newer SNOMED CT ground/air categories
do not establish the older local vehicle-category distinctions. Preserve the
source fact in Transport narrative and keep structured selection suspended.
Closing this requires aligned owner bindings or a complete reviewed lossless
crosswalk, followed by exact output and intended-receiver validation.

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

### Structured EDIS placement awaits AKTIN clarification

Entries `.10.85`, `.10.86`, and `.10.87` are not contained by the selected
document. The current Addendum definition declares only the discharge-timestamp
entries, while the structural overview still lists the EDIS entries. The
unchanged provided receiver rejects the reviewed local attachments.

Their structured mappings are suspended, with values retained as Addendum
narrative facts. Exact former assignments and attachment records remain in the
[restoration list](recovery/2026.1.2-notaufnahmeregister--60-suspended-cda-mappings.json).
The compiled attachments remain inactive candidate evidence. Closing this
requires AKTIN confirmation of each datum's intended use, exact placement and
revision for the selected transition profile, followed by reviewed mapping and
successful validation against the unchanged intended receiver.

### Isolation cardinality conflicts with the negative branch

The selected dataset requires both the isolation answer and reason, while the
CDA profile prohibits a reason when the answer is negative. Authored reference
scenarios therefore cannot exercise a legal negative-isolation record. Closing
this requires an upstream cardinality or conditional-rule clarification.

## Validation and delivery

### New allergy discriminator is rejected by the provided receiver

The `2026.1.3` owner example and complete allergy ValueSet admit J01 for the
antibiotic category. The unchanged provided receiver rejects that discriminator;
validation-only copies using the former A07AA isolate the incompatibility.
The active mapping and original documents retain J01. Closing this requires
receiver/publication alignment or a separately approved compatibility contract
with complete clinical semantics. A passing diagnostic copy is not permission
to narrow or rewrite an antibiotic statement, and validates no import or storage.

### Published AKTIN validation applies stricter content rules

The AKTIN runtime publication `aktin-runtime-20260427T185033` maps the selected
document `.10.93@2026-03-25T11:04:07` to `aktin-nartrv2026-2`. In its document
context, that validator applies closed-content rules to payer code, payer
associated entity, and the Addendum section. These reject CDA/RIM content allowed
by the cached open source templates and the reviewed local EDIS attachments.

Automatic optional text for coded values and the duplicate insurance identifier
in the Hauptkostenträger participant are omitted under the reviewed construction
policy. Local aliases retain their canonical coded meaning; the original input
remains in the source snapshot. The code/display name and the insurance number
in the explicitly declared generic payer slot remain. Structured EDIS assignments are suspended
under DEC-048; the source facts remain in narrative while their intended
placement is clarified. Rejection of the runtime replacement link
(`relatedDocument typeCode="RPLC"`) remains unresolved.

Local exact-closure conformance therefore does not establish acceptance by that
receiver publication. The unchanged provided receiver is the acceptance target.
Closing this boundary requires AKTIN clarification of structured EDIS placement
and the receiver's correction protocol. Initial-document validation does not
establish successful import, database storage, or correction acceptance. Do not
silently delete mapped content, change selected template revisions, or replace
receiver validation to obtain a pass.

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
