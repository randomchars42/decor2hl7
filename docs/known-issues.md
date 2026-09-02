# Known boundaries after the 0.1.0 correctness pass

The 0.1.0 rewrite now supports declarative semantic transforms, formal
ART-DECOR assertion enforcement, transitive identity-lineage enrichment,
explicitly keyed nested repetitions and specification-derived discriminated
repetitions. The remaining items are boundaries where
external protocol information or broader ART-DECOR expression coverage is
needed; they are not silent runtime fallbacks.

## Allergy payload mapping — priority 1

The dataset allergy group maps structurally to Allergies and Intolerances
section `1.2.276.0.76.10.3051`, whose effective branch contains Allergy Concern
Act `1.2.276.0.76.10.4065` and Allergy Intolerance Observation
`1.2.276.0.76.10.4066`. The observation fixes `code=ASSERTION` and `value=OINT`;
the required allergen is represented at
`participant/participantRole/playingEntity/code`, bound to ValueSet
`1.2.276.0.76.11.52`. The section narrative is also a legal writable target.

The source `Agens` domain is now executable. Its inline `conceptList` is empty,
owned by the PMP dataset concept and has no external reference; this is recorded
as an intentionally unconstrained coded domain rather than a terminology fetch
failure. Inside the already mapped allergy section, the required
`playingEntity/code` is the unique compatible coded descendant whose exact
ValueSet contains an `OTH` exception and whose datatype exposes
`originalText`. Unknown agent values therefore serialize as
`nullFlavor="OTH"` plus their source wording. A supplied target member is kept
only when both code and code system match exactly.

The allergy description now maps to the unique compiled section narrative role;
it no longer remains a structural-only suggestion. The antibiotic-allergy and
contrast-agent-allergy flags are also executable through exact neutral examples
in the active Allergy Intolerance Observation template. The examples supply the
target ValueSet discriminators `A07AA` and `V08`; the source disorder codes
`Z88.1` and `293637006` are not written as allergen identities. A present
boolean is inverted into `negationInd`, an absent source emits no occurrence,
and an equal explicit `Agens` code/code-system occurrence is coalesced rather
than duplicated.

The complete allergy occurrence is not yet executable from this transaction by
itself. Activating any of these structured allergy values also activates Allergy
Concern Act `1.2.276.0.76.10.4065`, where ART-DECOR requires
`effectiveTime/low` as the time the allergy was first documented as a concern.
The source allergy group has no timestamp, and the mandatory target does not
permit a null flavor. The compiler therefore retains the valid field mappings,
but the synthetic full-proposal fixture reports this missing required sibling
instead of substituting document time or inventing a clinical date.

## Medication payload mapping — priority 2

The medication section `1.2.276.0.76.3.1.195.10.64` and Medikation template
`1.2.276.0.76.3.1.195.10.67` are structurally selected. The existing
`for_each` correctly binds each repeated source medication to one section
`entry` and remains required occurrence semantics.

Static ART-DECOR associations now project through unique common CDA/RIM slots
from the associated legacy/profile constraints to the effective UV Medication
Information branch. Combined with the existing `for_each`, this makes four
source fields executable without a medication-specific rule: manufactured
material name, product code with its declared open code system, dosage
narrative, and route.

Predicate-aware structural overlay recovers the associated medication
`sequenceNumber`. The post-PR #20 audit also selected the event-related timing
`offset` from datatype expansion, but later DECOR-core analysis found a required
compound-datatype dependency: a non-null `EIVL_TS` must contain `event`. The
source event has no proven correspondence to a target TimingEvent code. Offset
must therefore be revalidated as part of an event-plus-offset representation or
downgraded; structural exposure of `offset` alone is not executable mapping
evidence. See
[`analyses/2026-09-02-decor-core-validation-follow-up.md`](analyses/2026-09-02-decor-core-validation-follow-up.md).

The remaining medication boundary is narrower but still important. No formal
source association has been found for lot number, so `chargennummer` remains
unmapped even though a general manufactured-material model can expose such a
slot. The active UV Subordinate administration template
`2.16.840.1.113883.10.21.4.6` exposes alternatives for timing plus
`doseQuantity` and `rateQuantity`, but the current source evidence does not
uniquely bridge start/stop, dose, rate, body site, PRN and medication-reason
fields to those alternatives. In particular, start, stop and dosage-time fields
would otherwise claim one atomic timing target, while dose and rate are two
equally compatible quantities. They remain unmapped instead of being resolved
by German/English path vocabulary or positional guessing. See
[`analyses/2026-09-02-residual-mapping-boundaries.md`](analyses/2026-09-02-residual-mapping-boundaries.md).

## Transform vocabulary

`cda-mapping.json` version 6 accepts direct target names, small declarative
rules, and explicit structural bindings. The built-in scalar transform vocabulary is deliberately limited to `identity`,
`enum`, `ordinal`, `not`, `code_system`, and `coded_fallback`. The generated proposal uses it for the currently
proven AKTIN semantics for Tetanusschutz, Isolation, modified Rankin, and
diagnosis certainty, to carry a normalized source code into one explicitly
declared open target CodeSystem, and to constrain an explicitly open source
domain through an exact target ValueSet's `OTH`/`originalText` fallback.
`mode: "presence"` is a structural assignment, not a scalar transform: it is
allowed only for a boolean source and a unique renderable fixed statement.
Structural `for_each`, `repeat_by_discriminator`, and
`coalesce` behavior is implemented in the generic binding layer and is generated
only from formal repeat/discriminator evidence. Legacy reviewed `fan_out`
configuration remains executable for compatibility.

A future concept whose ART-DECOR representation needs a different structural or
computed transformation remains evidence-linked but non-executable until an
explicit transform is added. `ADAPT` remains usable mapping evidence but is not
automatic dataset identity inheritance.

## Diagnosis time and certainty

Decision record: `DEC-008` in [`decisions.md`](decisions.md).

The compiler no longer derives a diagnosis end from certainty `Z`. The
transaction web view contains no diagnosis timepoint, and `Zustand nach` is a
certainty/clinical-status qualifier rather than a timestamp. V/A/Z/G therefore
maps only to the formal certainty qualifier; `A` additionally controls exclusion
negation. `effectiveTime/high` remains absent unless a real source mapping or an
explicitly reviewed mapping rule supplies it.

The CDA template does require `effectiveTime/low` for each active diagnosis
occurrence. Because this transaction contains no diagnosis-onset datapoint, the
generated CDA mapping declares a target-specific `nullFlavor="UNK"` default for
that required leaf. This states that the onset value is unknown; it does not
invent a date. If a future transaction supplies a real onset and maps it to the
same target, that value wins for its occurrence.

More generally, an otherwise empty required nullable CDA leaf receives the
mapping-wide `nullFlavor="NI"` completion default. Optional unmapped leaves are
omitted, and mandatory/non-nullable targets remain validation errors.

## Secondary ICD-10 diagnoses (concept 29508)

Decision record: `DEC-009` in [`decisions.md`](decisions.md).

The current transaction represents `ICD-10 Sekundärdiagnose` as concept 29508
with cardinality `0..1`, while historical/project material has also exposed it
as `0..*`. It is therefore not yet safe to define a delimiter syntax or to
expand it into additional diagnosis occurrences.

The current CDA evidence provides no proven direct target distinct from the
primary ICD value. The compiler deliberately leaves concept 29508 unmapped; it
must not be written as `CD.translation`, because that would assert a translation
of the primary diagnosis rather than another diagnosis.

AKTIN clarification is needed on cardinality and intended CDA representation:
whether each secondary code becomes another Problem Observation, how it relates
to the leading diagnosis, and whether text/certainty are repeated with it. Until
that is resolved, no semicolon parser or inferred clinical relationship is
implemented.

The post-PR #20 audit also rejects `CD.translation`: the ART-DECOR CDA datatype
documentation defines a translation as an alternative code for the same
concept, while the source defines a secondary member of a multiply coded ICD-10
diagnosis. See
[`analyses/2026-09-02-residual-mapping-boundaries.md`](analyses/2026-09-02-residual-mapping-boundaries.md).

## Remaining active-profile mapping boundaries

Seven non-medication datapoints remain without a suitable target after the
fresh-snapshot audit. The insurance-relationship identifier has a physically
suitable historical insured-number slot but no formal edge from the selected
concept. General event onset and the MRI/X-ray region choice lists have no
unique active statement mapping. Exact draft templates for export interval,
EDIS name and EDIS version exist in project evidence as `.10.85`, `.10.86` and
`.10.87`, but are not reachable from the selected document. They are retained
as evidence rather than forced into the active CDA closure. See
[`analyses/2026-09-02-residual-mapping-boundaries.md`](analyses/2026-09-02-residual-mapping-boundaries.md).

## ART-DECOR assertion expression coverage

The built-in standard-library evaluator covers all error-level assertion shapes
used by the selected AKTIN 2026.1.2 CDA closure: boolean expressions, nested
selectors/predicates, attribute comparisons, `count()` comparisons and the one
MDRO sequence-uniqueness expression using `<let>`.

An unknown future **error-level** expression is intentionally a validation error,
not a warning. `build` also writes `cda-assertions.sch` containing the original
ART-DECOR tests and variables so a standards Schematron processor can apply the
authoritative expressions independently. Full CDA XSD and repository-provided
Schematron validation are still useful additional deployment gates.

## DECOR-core and complete CDA validation — deferred

Decision record: open `DEC-019` in [`decisions.md`](decisions.md).

The project does not yet pin or execute the official DECOR-core XSD,
cross-artifact Schematron, template Schematron-generation transforms and
datatype Core Schematrons. It also uses a selected subset of the pinned official
CDA R2 XSD graph for compilation rather than running an independent output
validation against the complete schema closure.

This is primarily validation debt, not an identified mapping-coverage
opportunity. It may expose additional structural candidates, but no new
semantic source-to-target bridge was found. Core rules can also remove apparent
mappings; the medication EIVL offset is the first concrete example because the
corresponding event is required but lacks a proven terminology mapping.

Before implementation, establish the DECOR-core version compatible with the
selected ART-DECOR release, pin its checksum, use an XPath 2.0-capable
Schematron processor, validate source and compiled DECOR forms under their
different completeness rules, and select the exact CDA/SDTC schema baseline.
The full deferred design and restart checklist are recorded in
[`analyses/2026-09-02-decor-core-validation-follow-up.md`](analyses/2026-09-02-decor-core-validation-follow-up.md).

## Exact/static historical template resolution

Static template and terminology references are exact identities. An unavailable
auxiliary revision is reported as a degraded-build omission and is never replaced
with an older or newer revision. The representing document template itself is
still mandatory. Dynamic references remain explicitly dynamic and resolve to a
frozen identity recorded in the manifest.

## Provisional external artifact catalog

Decision record: open `DEC-012` in [`decisions.md`](decisions.md).

Phase 1 supports package-local `builtin` supplements and evidence-backed
`waiver` entries. This mechanism and its first two concrete uses require review:

- CodeSystem `1.2.276.0.76.5.401` is packaged as a ten-code builtin derived
  from the public HL7 Germany metastasis table and provisionally marked
  complete. Its completeness and redistribution basis must be confirmed.
- IHE split-dose template `1.3.6.1.4.1.19376.1.5.3.1.4.9` has a provisional
  spec-only waiver because the IHE text presents it as a discriminator under
  Medication Entry and no independent template body was located. The waiver is
  intentionally not an `ok` artifact and the build remains degraded.

The exact IHE Medicine Entry analysis artifact
`1.3.6.1.4.1.19376.1.9.1.3.1@2019-08-27T16:13:43` is resolved by the existing
`ch-pharm-` source hint and is sufficient for cache/build availability under
`DEC-004`; its optional source sidecar remains unavailable. It is not an
external-artifact blocker and must not be duplicated as a builtin. In the
selected AKTIN document its 49 named constraints are registry evidence only:
none has a CDA location or is renderable. The effective medication branch uses
`UV Medication Information (simple)` instead, so forcing the IHE constraints
onto that branch would invent a template relationship.

The exact AKTIN/DIVI CodeSystem
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` remains unresolved. A fragment
must not be promoted to a complete formal terminology dependency. Future
`download`, `fhir`, `mediawiki`, or licensed local-file modes must be added only
for a concrete required artifact and reviewed separately.

## Repetition identifiers

Nested repetitions are supported when every independent occurrence level has an
explicit `occurrence_keys` column. This permits outer and inner occurrences to
be joined across CSV sources without positional guessing. A single one-file
one-level `1:n` source may still use source order as its occurrence identity for
backward convenience.

An explicit `for_each` may bind a source repeat to a deeper CDA repeat node
while leaving an enclosing repeat-capable CDA node as one shared container. The
selected medication structure uses this to produce one medication section with
one entry per `medikamentose_therapie` occurrence. This alignment does not
license a join between independent source repetitions; those still require
occurrence keys.

If a future source format has no stable occurrence identifier for independent
nested streams, the ambiguity must be resolved in source configuration; the
runtime will not invent an association by zipping rows.

HL7/CDA model expansion (`DEC-013`/`DEC-014`) does not replace these occurrence rules. It
can expose legal value components below the active medication template, but it
does not establish which repeated dataset medication owns which CDA entry. The
reviewed medication `for_each` therefore remains. Pupil laterality is now a
`repeat_by_discriminator` instance derived from the repeatable pupil templates,
required `targetSiteCode`, exact AKTIN L/R ValueSet revision, unique German
designation matches and Schematron uniqueness assertions. The remaining
right/left source-facet correspondence is STRONG terminology evidence rather
than an explicit ConceptMap; if that match ceases to be unique, generation must
stop and require review.

## CDA narrative

The structural CDA renderer is generic. Section-specific human-readable
narrative remains minimal and should be generated from the same normalized
occurrence model without changing data-to-CDA mapping semantics.

## Receiver protocol and exactly-once delivery

`transport.py` intentionally uses generic HTTP POST until the actual receiver
protocol, authentication and batch envelope are specified. Local sent-state
cannot prove exactly-once delivery across the failure window where a POST
succeeds but the process crashes before state is recorded. Receiver-supported
document IDs or idempotency semantics should be used when available.
