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

DEC-018 still requires a separate policy review after DEC-026 removed generic
example-derived construction defaults. Its allergy rules do not use
`compiled_default`, but they do automatically obtain the `A07AA` and `V08`
discriminator constants from exact neutral examples. If examples are to remain
strictly non-executable even as mapping evidence, these two generated mappings
must be demoted to review candidates or replaced by a non-example formal
association. This follow-up is deliberately not resolved by the default-value
correction.

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
`sequenceNumber`. The event-related timing `offset` remains a strong structural
candidate, but is no longer executable by itself. The compiled datatype policy
now records that a non-null `EIVL_TS` requires `event`; proposal generation,
configuration validation and occurrence-aware rendering enforce that companion
dependency. Source concept 528 has no proven correspondence to a target
TimingEvent code, so the generated field remains `null` and no event code is
invented. This leaves five executable medication mappings, four medication
suggestions and sixteen medication datapoints without an executable target. See
[`analyses/2026-09-02-medication-compound-dependency.md`](analyses/2026-09-02-medication-compound-dependency.md).

The remaining medication boundary is narrower but still important. No formal
source association has been found for lot number, so `chargennummer` remains
unmapped even though a general manufactured-material model can expose such a
slot. The active UV Subordinate administration template
`2.16.840.1.113883.10.21.4.6` exposes alternatives for timing plus
`doseQuantity` and `rateQuantity`. Quantity normalization now preserves scalar
magnitudes, ranges and units, and compiled interval quantities expose exact
low/high assignment targets. This closes the representation/mechanics part of
the dose/rate issue, but the current source evidence still does not uniquely
bridge start/stop, dose, rate, body site, PRN and medication-reason fields to
those alternatives. The three timing meanings also lack a reviewed rule for
the materialized `IVL_TS`/`PIVL_TS` branches and their compound occurrence
constraints. They remain unmapped instead of being resolved by German/English
path vocabulary or positional guessing. See
[`analyses/2026-09-02-residual-mapping-boundaries.md`](analyses/2026-09-02-residual-mapping-boundaries.md).

The subordinate `SXPR_TS/comp` now exposes its XSD-defined `IVL_TS`, `PIVL_TS`,
`EIVL_TS`, and recursive `SXPR_TS` choices. This closes the missing-physical-leaf
part of the interval/frequency boundary but does not choose a source-to-branch
mapping or satisfy the compound occurrence semantics; that remains a reviewed
structural-rule task. The prohibited outer Medikation `effectiveTime` remains
unavailable.

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

The selected CEDIS ValueSet is a presenting-complaint taxonomy, not an ordered
scale. Its hierarchy therefore does not justify an `ordinal` transform. Dataset
option extraction accepts a bare leading rank only from the option's primary
label; unqualified numeric synonyms remain code/classification evidence. A
label or synonym may supply an ordinal when an explicit rank/score word
accompanies its number. Ordinal metadata is dropped from the whole option list
when extracted values collide. LOINC-shaped synonyms, fall-height measurements
and CEDIS classification numbers therefore cannot become ordinal evidence.

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

The generated `mapping-audit.json` is authoritative for the current boundary:
each unselected field carries a gate key and minimal reopening evidence rather
than relying on this hand-maintained prose. Audit version 2 also carries an
unproven, claim-aware list of physically admissible targets for each of the 20
context-bearing fields that still needs a semantic mapping decision. The
current field partition is
`semantic:shared_target` (four), `semantic:missing_companion` (one),
and `semantic:no_association` (twenty). One selected field additionally remains
`terminology:closure` because ValueSet `1.2.276.0.76.11.53` is genuinely
unresolved. The dated analyses below explain the clinical history; their
counts may drift without superseding the audit.

Seven non-medication datapoints remain without a suitable target after the
fresh-snapshot audit. The insurance-number concept does have a formal historical
chain: selected concept `.60.3.2.9.21582` identifies the HL7-DE concept
`.77.2.2.60210`; eVent concept `.60.12.2.358` inherits that concept; and template
`.10.2022` statically associates the eVent concept with its
`associatedEntity/id`. DEC-027 now acquires and reports this chain.

That chain ends in historical participant template `.10.2022`, however, while
the selected Kostenträger occurrence is active template `.3.1.195.10.4`.
Concept ancestry therefore establishes semantic relatedness but not occurrence
identity. The historical identifier has no unique CDA/RIM owner-particle
provenance that would permit a DEC-015 projection into `.10.4`, so the candidate
remains review-only and the active `associatedEntity/id` remains unselected.
Reopening requires an explicit occurrence association or sufficient structural
provenance for one unique in-context projection.

General event onset has no uniquely owned active event/problem statement. The
MRI statement is reachable, correcting the earlier residual wording, but it
has no region-bearing target. The X-ray choice list has only three unqualified
synonym strings matching fixed statements and lacks a complete 13-member
crosswalk plus repeat/coalescing/conflict rules. No singleton dispatcher is
enabled until that reviewed table exists.

Exact draft templates for export interval, EDIS name and EDIS version exist in
project evidence as `.10.85`, `.10.86` and `.10.87`. The selected Addendum
Dokumentationsinformationen section `.10.73` contains only `.10.75`–`.10.77`,
so the three exact entries have no upstream-selected physical placement.
DEC-021 supports an exact, reasoned `config/cda-extensions.json` attachment to
the open `.10.73` section: `fetch` then retrieves the selected entry revision
and `build` validates its placement against CDA core. The reference workspace
now contains the three reviewed `.10.85`–`.10.87` attachment records and the
accepted mapping selects their `value` leaves, raising reviewed coverage from
92/120 to 95/120 dataset fields without replacing an existing selection.
Explicit upstream containment remains preferable and makes any duplicate
local attachment fail. See the current
field-by-field investigation in
[`analyses/2026-09-02-seven-active-profile-gaps.md`](analyses/2026-09-02-seven-active-profile-gaps.md)
and the earlier snapshot in
[`analyses/2026-09-02-residual-mapping-boundaries.md`](analyses/2026-09-02-residual-mapping-boundaries.md).

The active CEDIS problem-observation interval is open. Its explicitly required
`width` coexists with inherited XSD `low`, `high`, and `center` targets;
declaring one child does not close the others. The earlier conclusion that the
pinned model contained no constraint against scalar `IVL_TS/@value` alongside
`width` was incomplete: the generated `DTr1_IVL_TS.sch` forbids `@value` with
any `hl7:` child and names `width` explicitly. DEC-024 now compiles that narrow
co-occurrence rule, making the parent timestamp target inadmissible while
retaining `effectiveTime/low` as a structurally admissible, datatype-derived
review candidate. The required `width` can be emitted with the configured
required-value null flavor when it has no real value. None of this establishes
the missing clinical association from Ereigniseintritt to `low`; that semantic
selection remains a review decision.

The active MRI statement has no region-bearing `targetSiteCode`,
`approachSiteCode`, or equivalent particle. Its region datapoint remains blocked
upstream until the selected template supplies such a target; generic CDA model
permissiveness does not invent one.

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

## Package validation exposes upstream conformance gaps

Decision record: accepted `DEC-019` in [`decisions.md`](decisions.md).

The pinned validation stack is implemented. On the 2026.1.2 reference
snapshot, DECOR XSD validation of `project-evidence.xml` passes, while the
DECOR Core Schematron reports 381 error, 1,780 warning and 536 information
events. These are source-project quality findings and remain report-only; they
do not make a local compiler build fail or change mapping coverage.

The prior reference snapshot's exact-closure template generator reported 65
errors for missing or undefined ValueSet contents, including dynamic bindings.
`fetch` now requests and freezes `$expand` evidence for dynamic, intensional
and otherwise incomplete ValueSets. Complete non-empty responses are normalized
from `expansion/items` into extensional validator/compiler input. Several live
ART-DECOR responses are capped (`current < count`), including large HL7 value
sets; these prefixes are retained as `expansion-evidence` and reported as
degraded instead of being presented as complete. Any expansion still partial
or unavailable after a refetch remains unresolved; terminology is never filled
from the live project evidence or a different revision merely to make
validation pass. The exact ten-member ActStatus revision is already embedded
in a selected frozen dataset artifact and is now supplied to validator assembly
as well as the model compiler, so no duplicate builtin is introduced.

After these changes, the 2026.1.2 reference generator reports 3 messages (down
from 65 in the published baseline and 140 during the unsafe intermediate merge).
All three are honest undefined-content findings for two external medication
ValueSets: `2.16.840.1.113762.1.4.1021.30` occurs twice and
`2.16.840.1.113762.1.4.1099.12` once. Their live `$expand` responses are
complete and carry no coded members at all: the ART-DECOR record for `1021.30`
holds the VSAC codes only as an HTML table inside `<desc>`, and `1099.12` holds
nothing. The content lives at VSAC under licensing this project does not carry,
so neither can be filled.

All three messages belong to rules on the C-CDA Medication Activity templates
`2.16.840.1.113883.10.20.22.4.16` (`MedicationActivity` and
`MedicationActivityV2`). Those templates are reachable in the assembled closure
but hold no document location in the selected AKTIN document, whose effective
medication branch is `UV Medication Information (simple)`. They are therefore
classified as outside the selected closure: they stay listed in
`generation_messages` and counted in
`generation_messages_outside_selected_closure`, and they neither degrade the
build nor deny `complete` (`DEC-010`, `DEC-019`). The generated stylesheet is
executable, has no compilation errors and now reports `complete: true`.

The reference mapping stays at 95/120 with no lost or gained mapped fields. The
build diagnostics report 56 crawl-degraded artifacts, of which 3 affect the
selected build: the AKTIN ValueSet `1.2.276.0.76.11.53`, its waived intension
CodeSystem `1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`, and the waived SPEC
parent `template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00`.

The assembler restores the QName-string namespace declarations omitted by the
publication transform, including the two distinct pharmaceutical namespaces.
It now also repairs only the reviewed unbalanced `[[hl7:supply]` emission under
the exact `entryRelationship[@typeCode='REFR']` match pattern and records every
rewrite in `validator-manifest.json` and `validator-compilation-errors.txt`.
Other malformed XPath still reaches the Saxon probe unchanged; a validator
that remains invalid or has unresolved generation errors is never executed by
`validate-cda`.

DECOR-core also emits generated Schematron `@see` links containing the local
machine path and a timestamped publication directory. The build now rewrites
only that recognized generated URI shape to a workspace-relative link before
copying includes or compiling the validator, while preserving external links
and recording every rewrite. The assembled input, normalized Schematron, and
compiled validator hashes are therefore reproducible and pinned by the local
reference closure tests. Raw output from invoking DECOR-core outside this build
pipeline remains non-reproducible for this reason.

The fetched API forms also do not publish one native complete compiled DECOR
project. Source-project validation and exact-closure generation are therefore
implemented, while native compiled-project Schematron validation is explicitly
reported as `not-run`. Resolving this boundary requires the producer's compiled
publication artifact or complete exact terminology closure—not reconstruction
from unmatched views.

The source counts and package identities are recorded in
[`analyses/2026-09-03-core-package-validation.md`](analyses/2026-09-03-core-package-validation.md).
The pre-implementation rationale remains in
[`analyses/2026-09-02-decor-core-validation-follow-up.md`](analyses/2026-09-02-decor-core-validation-follow-up.md).

## Exact/static historical template resolution

Static template and terminology references are exact identities. An unavailable
auxiliary revision is reported as a crawl omission and is never replaced with
an older or newer revision. `build-diagnostics.json` distinguishes the full
`crawl_degraded` list from `build_degraded`, the subset actually consulted by
selected formal terminology, validator ValueSets or CDA template compilation.
The representing document template itself is still mandatory. Dynamic
references remain explicitly dynamic and resolve to a frozen identity recorded
in the manifest.

`template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` is the concrete
case. It is the SPEC parent of the medication branch children
`1.3.6.1.4.1.19376.1.5.3.1.4.7.2` (IHE Medications) and
`1.2.276.0.76.10.4025` (German Material). The Continuity of Care Document
project `ccd1-` is the only publisher of the OID and holds exactly one revision,
`2007-04-01T00:00:00` — confirmed by its template list and by the cross-project
lookup `/template/2.16.840.1.113883.10.20.1.53`. That revision is already cached
from `pmp-` and contributes its own targets under its own identity; it is never
used to satisfy the `2005-09-07` request. The refinement is simply omitted:
`select_template` returns nothing for an unpublished static revision, the
relation stays in `unresolved_templates`, and both children still compile from
their own constraints plus the pinned CDA/RIM expansion. Recovering the parent
would not open the medication product-form or ingredient slots, which remain in
the no-target partition for the separate reasons recorded above.

Reopening evidence: an ART-DECOR project publishing
`2.16.840.1.113883.10.20.1.53` at exactly `2005-09-07T00:00:00`.

## External artifact catalog

Decision record: accepted `DEC-012` in [`decisions.md`](decisions.md).

The catalog supports package-local `builtin` supplements, evidence-backed
`waiver` entries and exact reviewed malformed-identity `alias` entries. Only a
`builtin` that declares `completeness: "complete"` and verifies its checksum,
artifact identity and exact revision may satisfy a required dependency; a
`waiver` never can. Every builtin and waiver entry must record `source_url`,
`source_version` and `license`, and `completeness` is a closed vocabulary.

- CodeSystem `1.2.276.0.76.5.401` is packaged as a ten-code builtin derived
  from the public HL7 Germany metastasis table and marked complete. Its
  redistribution basis rests on the public HL7 Germany wiki table.
- IHE split-dose template `1.3.6.1.4.1.19376.1.5.3.1.4.9` has a spec-only
  waiver because the IHE text presents it as a discriminator under Medication
  Entry and no independent template body was located.
- CodeSystem `1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` has a waiver; see
  the paragraph below.
- Template `2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` has a spec-only
  waiver; see "Exact/static historical template resolution".

A waiver is intentionally not an `ok` artifact, so the crawl remains degraded;
it affects the build headline only when the selected compiler inputs consult it.

The accepted alias policy is recorded separately in `DEC-022`. Its initial
entries correct the malformed SNOMED CT CodeSystem OID
`2.16.840.1.1138836.96` and template OID
`2.16.840.1.1133883.17.3.10.1.34`. Both published keys remain visible in the
manifest and count as satisfied only when their corrected target is `ok`.

No `oid_owners` override is currently shipped for the
`2.16.840.1.113883.3.2898` or `2.16.840.1.113883.17.3.10.1` clusters. The local
ART-DECOR project directory identifies no owner for either prefix. The
[AKTIN trauma publication](https://wiki.hl7.de/index.php?title=IG%3ANotaufnahmeregister_trauma)
and the
[HL7 EMS Patient Care Report](https://wiki.hl7.org/w/images/wiki.hl7.org/f/f5/CDAR2L3_IG_EMSRUNRPT_R1_N1_2013SEP.pdf)
establish the referenced template specifications, but not a current
ART-DECOR API project prefix. Guessing one would merely reorder blind probes,
so those evidence-only clusters remain without an owner override.

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
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` remains unresolved and now
carries a reviewed waiver. It is published nowhere on the specification server:
the cross-project lookup `/codesystem/1.2.276.0.76.3.1.195.5.53` answers 404 and
the dated extract answers 404 in all eight candidate projects recorded in
`resolution_attempts`. AKTIN ValueSet `1.2.276.0.76.11.53@2015-11-17`
("Referral actions") includes it intensionally and therefore expands to no
members: the dateless `$expand` returns the include unresolved with
`valueSetExpansionAssociation count="0"`, and the dated `$expand` answers 500.
The field bound to that value set keeps a non-executable enumeration; it is not
filled from logical labels (`DEC-003`, `DEC-016`). Neither the DIVI
Notfalldokumentation publication nor the HL7 Germany Notaufnahmeregister
implementation guide publishes the code list for this OID, so a builtin would
have to invent the identity. A fragment must not be promoted to a complete
formal terminology dependency. Future `download`, `fhir`, `mediawiki`, or
licensed local-file modes must be added only for a concrete required artifact
and reviewed separately.

Reopening evidence: a DIVI or HL7 Germany publication of
`1.2.276.0.76.3.1.195.5.53` at exactly `2019-12-30T00:00:00`, or the code system
appearing in an ART-DECOR project.

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
