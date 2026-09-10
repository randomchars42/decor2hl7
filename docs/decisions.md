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
| DEC-009 | Secondary ICD-10 diagnoses | accepted | verified |
| DEC-010 | Missing-artifact tolerance | accepted | verified |
| DEC-011 | Mapping evidence and documentation | accepted | verified |
| DEC-012 | External artifact supplements and waivers | open | partial |
| DEC-013 | Compiled HL7 V3 datatype model | accepted | verified |
| DEC-014 | Pinned CDA/RIM structural model expansion | accepted | verified |
| DEC-015 | Project ART-DECOR associations through common CDA/RIM slots | accepted | verified |
| DEC-016 | Empty owned coded domains and target-governed fallback | accepted | verified |
| DEC-017 | Specification-derived choice, occurrence and fixed-statement rules | accepted | verified |
| DEC-018 | Neutral-example boolean discriminator occurrences | accepted | verified |
| DEC-019 | DECOR-core and complete CDA validation stack | accepted | verified |
| DEC-020 | Compound-datatype companion requirements | accepted | verified |
| DEC-021 | Open templates and reviewed CDA extension attachments | accepted | verified |
| DEC-022 | Reviewed malformed artifact-identity aliases | accepted | verified |
| DEC-023 | Generated Schematron as supporting mapping evidence | accepted | verified |
| DEC-024 | Datatype Schematron co-occurrence admissibility | accepted | verified |
| DEC-025 | Conservative ordinal evidence extraction | accepted | verified |
| DEC-026 | ART-DECOR examples are non-executable instance data | accepted | verified |
| DEC-027 | Bounded association identity-lineage closure | accepted | verified |
| DEC-028 | Exact SPEC-choice overlays and namespace-aware profile extensions | accepted | verified |
| DEC-029 | Reviewed scalar CDA construction defaults | accepted | verified |
| DEC-030 | Compiled entry-to-section narrative links | accepted | verified |
| DEC-031 | Explicit child constraints in non-monotonic SPEC designs | accepted | verified |
| DEC-032 | Namespace-aware ART-DECOR assertion evaluation | accepted | verified |
| DEC-033 | Reviewed allergy time construction | accepted | verified |
| DEC-034 | Bounded receiver transport adapters | accepted | verified |
| DEC-035 | Versioned authored mapping scenarios | accepted | verified |

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

An artifact declares its identity on `id` when it defines itself and on `ref`
when a project references it rather than defining it — the published shape for
an external terminology such as SNOMED CT or LOINC, whose analysis form is a
project envelope with no revision. Both shapes identify the artifact, so cache
adoption recognises either and a cached reference declaration is a genuine cache
hit rather than a missing file. Identification is not revision proof: a
reference declaration satisfies a static request only when it carries the
requested `effectiveDate`, and the resolved revision is read from the richer
cached form, exactly as a download reads it.

Evidence: `docs/architecture.md`, `src/decor2hl7/retrieval/`.

## DEC-005 — Target-neutral model and target boundary

**Decision:** accepted  
**Implementation:** verified

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
- `repeat_by_discriminator` creates discriminated target occurrences only from
  a shared repeatable target, one required coded discriminator, its exact bound
  ValueSet revision and a unique terminology-supported source-facet/member
  correspondence. Pupil size/reaction use the AKTIN L/R eye ValueSet and retain
  Schematron uniqueness as evidence;
- `coalesce` shares equivalent singleton targets and defaults to
  `equal_or_error`;
- `mode: fallback` fills an absent leaf per occurrence without replacing a real
  value.
- `mode: fallback_if_active` fills a required value only after another mapping
  has activated that optional CDA branch. It cannot create a branch or repeat.

Legacy reviewed `fan_out` remains executable. `init-cda-mapping` migrates it only
when a generated replacement proves the same sources and physical CDA target.

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

**Decision:** accepted
**Implementation:** verified

AKTIN confirmed that the selected CDA profile contains no target template for
the transaction's `ICD-10 Sekundärdiagnose`. It therefore remains intentionally
unmapped: no delimiter parser, `CD.translation`, or inferred additional Problem
Observation is introduced.

The stale candidate was reached through weak `ADAPT` lineage from a differently
named concept. Such name-drifting weak lineage remains visible as review
evidence but is never actionable, and Schematron compatibility cannot promote
it. This is a generic semantic guard rather than a field-name exception.

Evidence: AKTIN maintainer clarification for template
`1.2.276.0.76.10.4048@2016-06-22`, `src/decor2hl7/compile/mapping.py`,
`tests/test_core.py`, `docs/known-issues.md`,
`docs/analyses/2026-09-02-residual-mapping-boundaries.md`.

## DEC-010 — Missing-artifact tolerance

**Decision:** accepted  
**Implementation:** verified

Unavailable auxiliary artifacts are reported and omitted when the selected
build can be compiled safely. Missing representing templates, selected
transaction forms, corrupt successful artifacts and exact-identity
contradictions remain fatal. Static references are never silently replaced by
another revision.

Retrieval and build degradation are distinct. `closure.json` retains every
required dependency that the crawler could not obtain as `crawl_degraded`.
`build-diagnostics.json` additionally reports `build_degraded`: only an absent
artifact consulted by a selected field's formal terminology, a generated
validator ValueSet (including its unresolved CodeSystem intension), or the CDA
template compiler affects the headline build status. A CodeSystem reference
under a non-code value domain or beside complete inline members is display
evidence unless another standalone ValueSet genuinely requires it.

A generated validator ValueSet counts only when the rule that needs it can
apply to the selected document. The publication transform emits rules for every
template the assembled specification reaches, including branches of referenced
projects the selected document never instantiates. A template belongs to the
selected closure when at least one of its compiled targets holds a document
location; a generation message whose rule context names only templates outside
that set reports an upstream gap this build does not consume. A message with no
recognisable template context stays inside the closure, so an unparsed message
can never silently narrow the reported degradation.

Evidence: `src/decor2hl7/compile/artifacts.py`, `docs/architecture.md`,
`docs/known-issues.md`.

## DEC-011 — Mapping evidence and documentation

**Decision:** accepted  
**Implementation:** verified

`mapping-audit.json` is the structured evidence/decision product.
`cda-mapping.proposed.json`, `cda-mapping.md`, `cda-mapping-details.md` and
`cda-mapping-trees.md` derive from the same analysis. The reports deliberately
separate three reviewer tasks: the main guide contains only unresolved decisions
and their candidate leaves; the details appendix contains every accepted mapping,
its abridged JSON and contextual read-only XML plus full evidence; the tree report
contains the two exhaustive coverage views. Configuration is edited in JSON,
never in generated Markdown or XML.

When an executable proposal depends on a reviewed attachment, identity alias,
source hint or OID-owner override, `cda-mapping.json` carries a short generated
`configuration_notes` entry. Reinitialization refreshes generated notes while
preserving reviewer-authored notes and mapping choices.

Its stable coverage headline separates mapped dataset datapoints and target
leaves, actionable unselected suggestions, datapoints with no suitable writable
CDA leaf, and reportable template-level CDA leaves with no dataset source.
`cda-mapping.md` prunes both hierarchies to unresolved datapoints and candidate
leaves. `cda-mapping-trees.md` presents the exhaustive evidence in opposite
directions: every dataset datapoint through its source hierarchy, and every
reportable CDA leaf through the document/template hierarchy. Tree leaves stay
on one physical line with status in a dedicated left gutter.
The inverse view excludes generic datatype-expansion plumbing and fixed,
conditional-fixed or system-supplied values rather than reporting the raw
writable-target inventory as meaningful mapping surface.

`mapping-audit.json` also records one machine-readable `gap` for every
unselected datapoint/group and for a selected datapoint whose formal terminology
is unresolved. The gap identifies the first failing gate (`physical`,
`semantic`, `terminology`, or `blocked_upstream`), a stable kind, and the
smallest compiled request, target, component, or competing source set that would
reopen the decision. Generated details render the same evidence on one line;
the audit summary rolls the keys up and persists the coverage-headline counts so
release comparisons do not parse Markdown.

Audit version 2 additionally records `possible_targets` for every unselected
field that has one uniquely located structural context. This is a physical
admissibility inventory, never semantic evidence: it cannot select a mapping or
change the coverage headline. The inventory uses its own reproducible filter,
separate from the inverse-coverage filter. It retains writable, uniquely
located, non-prohibited, non-fixed and non-system targets that are either
non-derived or originate from the CDA/RIM overlay without datatype-expansion
provenance. It excludes the fixed CDA infrastructure roles `realmCode`,
`typeId`, `templateId`, `languageCode`, `setId`, `versionNumber`,
`confidentialityCode`, `priorityCode`, `reference`, `statusCode`, `nullFlavor`,
`classCode`, `moodCode`, `typeCode`, `determinerCode`, and
`contextControlCode`. Frequency is never a genericity rule. Per field, the
compiler then keeps descendants of the selected context whose compiled
`logical_types` include the dataset type. Exact claims remain visible with
`claimed_by`, and claims elsewhere in the same contained-template occurrence
remain visible with `containing_instance_claimed_by`; neither is evidence for
the unmapped field. `gap.reopens_with` stays the compact first-gate diagnostic
and does not duplicate this potentially long list.

The main decision card groups this inventory by contained-template occurrence
and renders an annotated XML-like constraint skeleton beside each group. The
skeleton is not an instance example and is not editable: its template name,
description and identity, element description, datatype, cardinality,
conformance, fixed codes and display labels, ValueSet identity/name/revision,
claims, occurrence requirements and non-null companions all come from compiled
metadata. Missing source labels remain missing; the report never invents them.

A dataset code may map directly to an unfixed writable CDA `hl7:code` element
when both sides use coded datatypes and share an explicit ValueSet. This permits
formally associated payloads such as the referral source while preventing a
dataset value from replacing a fixed or differently bound structural section
code.

Evidence: `src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/compile/reports.py`,
`docs/mapping-documentation-format.md`.

## DEC-012 — External artifact supplements and waivers

**Decision:** accepted
**Implementation:** verified

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
framework. A `download`, `fhir`, `mediawiki` or licensed local-file mode is
added only for a concrete required artifact from a specific reviewed source.

**When an external artifact may satisfy a required dependency.** Only a
`builtin` can, and only when all of the following hold: its catalog entry
declares `completeness: "complete"`; its bytes match the recorded `sha256`; the
payload parses and contains the requested artifact kind and id; and its
`effectiveDate` equals the requested revision exactly. Any other completeness is
recorded as `partial`, which stays an unavailable compiler input. A `waiver`
never satisfies a required dependency in any circumstance: it settles an absence
with cited reasoning and keeps the artifact visibly degraded.

**Every `builtin` and `waiver` entry carries its own provenance.** The catalog
rejects an entry without `source_url`, `source_version` and `license`; a
`waiver` also requires `reason` and a `builtin` also requires `artifact`,
`sha256` and `completeness`. `completeness` is restricted to `complete`,
`partial`, `fragment`, `spec-only` or `unavailable`, so the value that decides
whether a supplement may satisfy a dependency cannot be free text.

The reviewed catalog currently holds one builtin and three waivers:

- CodeSystem `1.2.276.0.76.5.401` — a ten-code builtin derived from the public
  HL7 Germany metastasis table, marked complete.
- Template `1.3.6.1.4.1.19376.1.5.3.1.4.9` — spec-only waiver; IHE presents the
  OID as a split-dose discriminator under Medication Entry and publishes no
  independent template body.
- CodeSystem `1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` — waiver. The
  cross-project lookup answers 404 and the dated extract answers 404 in every
  candidate project, so the AKTIN ValueSet `1.2.276.0.76.11.53` that includes it
  intensionally expands to no members and its bound field keeps a
  non-executable enumeration. No exact revision is published by DIVI or HL7
  Germany, so a builtin would have to invent an identity.
- Template `2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` — waiver. The
  Continuity of Care Document project `ccd1-` is the only publisher of the OID
  and holds exactly one revision, `2007-04-01T00:00:00`, which is already cached
  from `pmp-` under its own identity and must not substitute the requested one
  (`DEC-004`). The omission is scoped to the SPEC refinement: both children
  still compile from their own constraints plus the pinned CDA/RIM expansion.

The IHE Medicine Entry
`1.3.6.1.4.1.19376.1.9.1.3.1@2019-08-27T16:13:43` is not a candidate for a
builtin: its exact analysis form is already resolved through the `ch-pharm-`
source hint and satisfies dependency availability under `DEC-004`. The missing
source form is optional evidence. Its constraints remain unlocated in the
selected AKTIN document. DEC-028 subsequently selects the sibling Universal
Medication Information detail branch by exact inherited `SPEC` evidence;
external-artifact handling still must not be used to alter that template
relationship.

Evidence: `docs/analyses/2026-08-30-external-artifact-phase-1.md`,
`docs/analyses/2026-08-30-medication-mapping-plan.md`,
`docs/analyses/2026-09-03-closure-phase-4.md`,
`src/decor2hl7/retrieval/sources.py`, `src/decor2hl7/retrieval/sources.json`,
`src/decor2hl7/retrieval/fetch.py`, `tests/test_external_sources.py`.

## DEC-013 — Compiled HL7 V3 datatype/value model

**Decision:** accepted
**Implementation:** verified

CDA compilation combines the fully resolved ART-DECOR constraint tree with the
pinned CDA R2 XSD definition graph before mapping begins. The graph supplies
datatype structure, aliases and inheritance; the package-local datatype module
retains only scalar XML serialization policy. The effective template produces
its model inventory automatically. Every declared type is classified as a
datatype, constrained alias, structural model type, or explicit unsupported
error.

The compiled target model distinguishes structural nodes from writable value
targets. Every writable target carries a compiled value representation (element
text, XML attribute, identifier, timestamp, quantity, coded value or boolean)
and logical input types. Mapping consumes that metadata instead of path-name
leaf heuristics; rendering consumes it instead of interpreting datatype names a
second time. ART-DECOR constraints override generic datatype cardinality,
conformance, fixed values and datatype refinements. Optional legal datatype
parts are instantiated only when assigned, required, fixed or needed as an
ancestor.

Normalized dataset quantities use one target-neutral representation. A scalar
is `{value, unit?}`; a range is `{low: {value, unit?}, high: {value, unit?}}`.
The input normalizer accepts a numeric magnitude with an optional unit or a
low-high range, supplies a dataset-declared fixed unit when the input omits it,
and rejects conflicting units or reversed ranges. Decimal and duration fields
retain their existing scalar representation.

Quantity-interval compilation records the exact writable `low` and `high`
target names in the parent value representation. Assignment projects a
normalized range through those compiled names while a scalar continues to use
the parent's `value`/`unit` attributes; rendering does not interpret an
`IVL_PQ` datatype or path suffix. CDA R2 permits `PQ/@unit` to be omitted (its
schema default is `1`), so there is no blanket non-null unit requirement.
Template-fixed units and field-specific clinical mapping decisions remain
authoritative where present.

The XSD index also records reverse extension relationships. Polymorphic complex
expansion is deliberately enabled only for reviewed roots, currently
`SXCM_TS`, rather than inferred for every type with extensions. A located
`SXCM_TS` reached through an explicit `xsi:type` branch exposes the four
concrete XSD alternatives (`IVL_TS`, `PIVL_TS`, `EIVL_TS`, `SXPR_TS`) through
transparent compiled choice metadata. Datatype-derived `useablePeriod`
plumbing is excluded. Assigning a descendant sets the compiled `xsi:type` on
the existing physical element, while conflicting choices in one occurrence are
rejected.

CDA-specific compilation, datatype modelling and rendering live in
`decor2hl7.cda`. Generated `cda.json`, mappings and documentation are rebuilt;
no compatibility adapter for the former generated representation is retained.
Structural occurrence rules from `DEC-007`, including medication `for_each` and
specification-derived pupil `repeat_by_discriminator`, remain authoritative
because datatype expansion supplies legal XML value structure, not
source/target occurrence semantics.

A frozen `$expand` response is a first-class terminology representation.
Dynamic bindings resolve to the effective revision returned by the analysis
form, and both that identity and the returned expansion evidence are cached.
Only a non-empty expansion whose ART-DECOR `current` and `count` totals prove
that the response is complete becomes compiler input. A complete wrapper is
normalized from its sibling `expansion/items` into an extensional concept list,
replacing the definition's unresolved includes. A server-capped response is
retained as `expansion-evidence`, reported as degraded, and never treated as the
whole value set. The terminology compiler and DECOR validator assembly consume
the same accepted frozen members. An unavailable or partial expansion leaves
the formal domain unresolved; it does not promote dataset labels, a returned
prefix, or another revision into normative members. Exact value-set revisions
embedded in another selected build artifact are also supplied to validator
assembly, matching the model compiler's existing closure view.

The transaction compiler applies that frozen-dynamic policy to its compiled
terminology index as well. A literal `dynamic` request resolves to the newest
available frozen revision. If analysis exposes both a dated embedded view and a
dynamic association for the same OID, the dynamic association is the governing
binding and the revisions are not unioned. A binding that contains only an
explicit effective date remains exact and never falls back, preserving
`DEC-004` identity semantics.

Evidence: `src/decor2hl7/cda/`, `src/decor2hl7/semantics.py`,
`tests/test_cda_datatypes.py`, `tests/test_core.py`.

## DEC-014 — Pinned CDA/RIM structural model expansion

**Decision:** accepted
**Implementation:** verified

`fetch` caches the official HL7 CDA R2 normative XSD definition set pinned to
commit `e922fc35586fd2629f0c8a021080bca9ab424e18`. CDA compilation indexes XSD
definitions by name, follows extension inheritance, resolves structural element
names procedurally, overlays ART-DECOR constraints, and then runs datatype/value
representation expansion. Generated nodes retain `cda-rim`, `datatype`, or
combined template provenance. Mapping and rendering contain no per-class rules.

Naming one datatype child in an open ART-DECOR constraint refines that child;
it does not prohibit omitted legal siblings. The datatype pass therefore still
materializes inherited XSD parts unless closedness or an explicit prohibition
removes them. This is observable in the active CEDIS `IVL_TS`: its declared
required `width` coexists with inherited legal `low`, `high`, and `center`
targets.

An explicit `NP` constraint governs the complete physical subtree. CDA/RIM and
datatype expansion may retain synthesized descendants as provenance, but the
compiler normalizes their effective cardinality to zero and marks every target
below the prohibited particle non-writable. Required children from the generic
XSD cannot contradict the prohibition or become destinations that the renderer
would silently suppress.

Template `include` and `contains` nodes are provenance/occurrence wrappers, not
XML elements. Structural matching descends through those wrappers before
materializing an omitted CDA/RIM particle. A wrapped explicit child is overlaid
with the structural type and combined provenance in place; it must not coexist
with a second generic child. Group placement likewise uses compiled structural
metadata (`kind`, writability, children and derivation provenance), not absence
of a datatype, because explicit CDA containers carry their RIM class datatype.
An include without its own multiplicity is an inline constraint group; it does
not make required contained particles optional. A `contains` relationship makes
the referenced concrete root present with its owner.

The CDA/RIM overlay may strengthen an explicit particle's minimum, maximum, or
required attribute from the pinned XSD, but never weakens ART-DECOR or revives
an `NP` branch. It also retains a required XSD choice independently from the
zero minimum of each alternative. When ART-DECOR exposes exactly one concrete
alternative, that branch satisfies the group requirement; generic alternatives
are not manufactured as profile targets. The compiler records normative XSD
particle order separately from stable ART-DECOR source locations, and the
renderer uses that order without changing target identity.

Medication `for_each` remains under DEC-007 because the model describes legal
XML structure, not occurrence ownership. Pupil laterality is derived separately
as `repeat_by_discriminator` from repeat cardinality, required
`targetSiteCode`, the exact bound L/R ValueSet, terminology designations and
Schematron uniqueness evidence.

ART-DECOR element ids are not assumed unique inside one template. Physical
source identity also includes the effective date and template-local path,
preventing fixed constraints from distinct revisions or sibling branches from
being overlaid or verified against each other.

ART-DECOR example fragments are excluded from executable constraint compilation
under DEC-026. Coded source wording and other companion content are carried by
compiled roles. ART-DECOR XPath predicates remain constraint identity, never
serialized QName text. These rules preserve the compiled-model boundary: the
renderer consumes representations and roles without class-, datatype- or
template-specific dispatch.

Generated target identifiers retain their flattened form as stable mapping and
runtime keys. This does not flatten the compiled CDA model: physical `path` and
`locations` metadata and the expanded readable products retain the actual
hierarchy. Renaming the identifiers solely for presentation would create broad
configuration churn without changing the executable structure.

Evidence: `src/decor2hl7/cda/core.py`, `src/decor2hl7/cda/compile.py`,
`tests/test_cda_datatypes.py`,
`docs/analyses/2026-08-31-cda-mapping-recovery.md`.

## DEC-015 — Project ART-DECOR associations through common CDA/RIM slots

**Decision:** accepted
**Implementation:** verified

ART-DECOR `staticAssociations/origconcept` is formal mapping evidence even when
it references a legacy or profile constraint that is not itself present in the
effective CDA branch. The compiler may project that association to the active
branch only when the referenced constraint resolves to one unique CDA/RIM XSD
owner-and-particle slot and the mapped target context contains one unique
nearest occurrence of the same slot. Neither the source nor target leaf name is
used to establish equivalence. Ambiguous class slots or occurrences remain
visible evidence and are not executable proposals.

XSD `complexType/@mixed` is compiled into an element-text value representation
for a complex root. Rendering consumes that representation without knowing the
datatype or template. A coded source associated with an open coded target may
use the declarative `code_system` transform when exactly one target CodeSystem
is specified; the transform preserves the normalized code and adds the
CodeSystem OID without inventing a ValueSet crosswalk.

Structural `for_each` rules are provisionally derived before field selection.
Their explicit source-group/target-repeat alignment may satisfy repeat-depth
compatibility for a scalar candidate, using the same occurrence check as
mapping validation. This retains one shared medication section and one entry per
source medication while making formally associated payload fields actionable.

Applied to the then-effective simple medication branch, the generic mechanism
selects manufactured-material name, product code, dosage narrative and route.
It did not select lot number because that branch supplied no proven target.
DEC-028 subsequently makes the exact detail branch and its reviewed lot mapping
available without changing this generic projection rule. The mapping and
renderer contain no medication-class, template-OID or field-name exception.

A 2026-09-03 active-profile re-review found no candidate withheld by the
one-slot or unique-nearest-occurrence gates. Sixty relevant static-association
routes resolve directly and six routes resolve through one unique slot; the
seven unresolved routes expose no CDA/RIM slot at all. They reference
pharmaceutical-model particles or an unattached precondition template, so
relaxing this decision would not recover them safely.

Evidence: `src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/cda/core.py`, `src/decor2hl7/cda/compile.py`,
`src/decor2hl7/transforms.py`, `tests/test_core.py`,
`tests/test_cda_datatypes.py`,
`docs/analyses/2026-09-01-medication-common-base-slot.md`,
`docs/analyses/2026-09-03-reviewed-edis-attachments-and-decision-review.md`.

## DEC-016 — Empty owned coded domains and target-governed fallback

**Decision:** accepted
**Implementation:** verified

An inline ART-DECOR `conceptList` is subordinate to its dataset concept. An
empty owned list with no external reference is therefore compiled as an
explicit `unconstrained` coded domain, not as an unresolved standalone
ValueSet. `model.json` retains the list identifier, status and member count;
`formal_terminology.status` distinguishes `bound`, `unconstrained`, `logical`,
`unbound` and `unresolved` domains. Missing or incomplete external ValueSets
remain unresolved and are never reclassified as open.

An unconstrained source code may become executable below a formally mapped CDA
container only when one unique compatible descendant:

1. binds one exact target ValueSet revision;
2. contains an explicit `OTH` exception; and
3. exposes the coded datatype's compiled `originalText` companion.

The generated `coded_fallback` transform admits a supplied code only when its
code/code-system pair exactly matches a non-exception target member. Otherwise
it emits `nullFlavor="OTH"` and preserves the source wording for the compiled
`coded_original_text` role. The mapper contains no allergy field, template,
class, ValueSet or path constant, and the renderer remains representation-
driven. Because there is no source-to-target ConceptMap, the proposal is STRONG
indirect evidence rather than EXACT evidence.

For the selected AKTIN snapshot this resolves `Agens` to Allergy Intolerance
Observation `playingEntity/code` through the already mapped allergy section and
ValueSet `1.2.276.0.76.11.52`. The antibiotic and contrast-derived source
disorder codes remain ineligible as allergen identities. DEC-018 later
establishes their occurrence representation from exact target-template examples
without changing that terminology boundary.

Evidence: `src/decor2hl7/compile/transaction.py`,
`src/decor2hl7/compile/mapping.py`, `src/decor2hl7/compile/structural.py`,
`src/decor2hl7/transforms.py`, `tests/test_core.py`,
`docs/analyses/2026-09-01-open-coded-allergy.md`.

## DEC-017 — Specification-derived choice, occurrence and fixed-statement rules

**Decision:** accepted
**Implementation:** verified

ART-DECOR `<choice>` is transparent XML structure. Each branch is compiled, and
predicate variants of one element overlay the same CDA/RIM or datatype particle
without losing their distinct constraint identities. An abstract `ANY` value
exposes concrete typed scalar targets whose compiled representations carry the
required `xsi:type`; the mapper and renderer do not dispatch on clinical class
or template name. Choice selection requires one unique datatype-compatible
atomic branch or one unique compatible value descendant of a complex branch.

A generated `for_each` establishes an occurrence boundary. A source field owned
directly by that repeated group may map to the unique nearest compatible
writable descendant at the boundary; deeper statement values do not compete.
This permits an occurrence-level timestamp such as the vital-sign organizer
time to be derived from structure rather than from a path-name exception.

Boolean presence and CDA negation are separate semantics. A boolean mapped to a
coded act's `@negationInd` uses the declarative `not` transform. When exact
source terminology instead locates one optional statement whose complete
clinical payload is fixed by ART-DECOR, `mode: "presence"` activates that
structural statement for true and omits it for false. The container remains
non-writable as a scalar target.

Exact contextual ART-DECOR leaf roles, descriptions, section narrative roles
and URL/datatype descendants may be selected only when the mapped container,
datatype compatibility, physical location and occurrence checks leave one
candidate. These mechanisms contain no wildcard, vital-sign, direct-contact,
medication, allergy, CDA class or template-OID table.

A compiler-assigned system role is bound to its exact physical node. Reuse of
the same included logical target elsewhere does not make that target writable
and does not copy the system value into the other occurrences. This permits the
mandatory custodian organization to be completed from site configuration while
preserving ambiguity safeguards for the reusable Organization Elements target.

Evidence: `src/decor2hl7/cda/compile.py`,
`src/decor2hl7/compile/mapping.py`, `src/decor2hl7/bindings.py`,
`src/decor2hl7/cda/render.py`, `tests/test_cda_datatypes.py`,
`tests/test_core.py`,
`docs/analyses/2026-09-01-spec-derived-target-recovery.md`.

## DEC-018 — Neutral-example boolean discriminator occurrences

**Decision:** accepted
**Implementation:** verified

A neutral ART-DECOR example may establish a repeated coded occurrence for a
boolean source only when all of the following are unique and exact:

1. the source already has a mapped CDA container context;
2. its category-specific name matches one example caption, not merely a generic
   clinical word;
3. the example belongs to the exact effective target template;
4. its coded discriminator is an exact code/code-system member of the target's
   one bound ValueSet revision; and
5. the boolean target is that occurrence's writable `@negationInd`, at exactly
   one additional repeat depth.

The generated branch uses the declarative `not` transform: source `true`
represents a positive assertion (`negationInd=false`), source `false` represents
an explicit negative assertion (`negationInd=true`), and an absent source emits
no branch. The target discriminator comes from the exact template example, not
from the source field's disorder code.

When a separately mapped coded field already supplies the discriminator, the
runtime merges an example-derived branch only if code and code system are equal.
Otherwise it creates another occurrence. Differing values for one equal
discriminator are an error; no clinical precedence rule is inferred.

For the selected AKTIN snapshot, AKTIN confirmed that the agent ValueSet
establishes `A07AA` for the antibiotic flag and `V08` for the contrast-agent
flag. `false` is represented by the corresponding occurrence with
`negationInd="true"`; absence of the source emits no occurrence. A matching
explicit `Agens` occurrence is coalesced rather than duplicated. DEC-033
separately completes the required timestamps of an activated allergy entry.

Evidence: AKTIN maintainer clarification for template
`1.2.276.0.76.10.4066@2015-09-18` and ValueSet
`1.2.276.0.76.11.52@2015-11-17`, `src/decor2hl7/compile/structural.py`,
`src/decor2hl7/compile/mapping.py`, `src/decor2hl7/bindings.py`,
`tests/test_core.py`,
`docs/analyses/2026-09-02-allergy-example-discriminators.md`.

## DEC-019 — DECOR-core and complete CDA validation stack

**Decision:** accepted
**Implementation:** verified

Specification acquisition pins DECOR-core 2.2.28, the complete CDA R2
normative and SDTC schema trees at the compiler's existing HL7 revision,
Saxon-HE 12.5 and XML Resolver 5.2.2. The manifest and package lock retain
version, source URL, checksum and license identity; archive extraction is
path-safe and every extracted file is hashed. The complete normative graph is
also preferred by the CDA compiler over the legacy four-file cache.

`build` validates the live source-project evidence with the DECOR XSD and Core
Schematron under a report-only policy. It then assembles only exact fetched
transaction artifacts, generates the selected template Schematron through the
pinned DECOR publication transform, resolves datatype Core Schematron includes,
compiles an XSLT 2.0 validator candidate and probes the stylesheet with Saxon
before use. The assembler is explicitly not a native compiled ART-DECOR
project. Since no complete native compiled project
is published by the fetched API forms, that distinct validation stage is
recorded as `not-run` rather than inferred from source or analysis views.

The assembler restores QName-string namespace declarations omitted by the
publication transform. One reviewed DECOR-core emission defect is repaired
narrowly: a generated `match` containing the unbalanced
`hl7:entryRelationship[@typeCode='REFR'][[hl7:supply]` token loses the extra
opening bracket. Every rewrite is recorded in `validator-manifest.json`; other
malformed XPath remains untouched and the executable probe still fails closed.
The same before/after record is written to
`validator-compilation-errors.txt` for the publication-transform diagnostic
trail; a logged reviewed repair is not itself a compilation failure.

The same narrow post-generation pass normalizes DECOR-core `@see` values that
embed the generator machine's absolute `file:///` path and timestamped HTML
directory. Only that recognized generated URI shape is rewritten to a stable
workspace-relative documentation URI, and every occurrence is included in the
same repair manifest/log. External documentation links are preserved. With
this normalization, `assembled_sha256`, `schematron_sha256`, and
`validator_sha256` are reproducible and may be pinned by the reference closure
tests.

`validator-manifest.json` reports `complete` as a claim about the *selected
transaction document*: every rule that can apply to it was generated. The
publication transform runs over the whole assembled closure, so it also reports
skipped rules for referenced templates the selected document never instantiates.
Each generation message is therefore classified in `generation_message_scopes`
by the value sets it names, the template OIDs in its rule context, and whether
any of those templates holds a document location in the compiled CDA model. Only
an in-closure error denies `complete`. The raw `generation_messages` list stays
intact and `generation_messages_outside_selected_closure` counts the remainder,
so the omission is visible rather than dropped; a message whose context cannot
be parsed is treated as in-closure.

For a template OID instantiated by the compiled document, validator assembly
retains only the exact effective-dated revision or revisions selected at a
physical document location. This prevents superseded rules with the same
template OID from being activated against one instance. Templates used only as
publication-transform dependencies remain available at all fetched revisions,
so dynamic and generic CDA/RIM resolution is not broken by document filtering.

`validate-cda` is a separate enforced gate: it validates documents against the
complete SDTC schema entry point and the generated transaction/datatype
Schematron. It fails closed if package or validator checksums differ, generation
reported unresolved terminology inside the selected closure, or either validator
emits errors. Setup and validation may use Java; transformation remains
standard-library-only.

The foreign-extension projection used only for the base CDA/SDTC XSD gate
serializes the normal CDA default namespace plus `xsi` and `sdtc` bindings.
This preserves the namespace meaning of unprefixed QName values such as
`xsi:type="CE"`; projection cannot turn a valid datatype QName into an
unnamespaced name.

Conformance and mapping coverage remain independent. Core rules can disqualify
a representation, as DEC-020 did for the medication event offset, but neither
a valid structural slot nor a package rule supplies a semantic dataset-to-CDA
bridge. The current source extract's Core Schematron errors, unavailable native
compiled form and incomplete terminology used during generation remain visible
quality boundaries in `docs/known-issues.md`; the implementation does not turn
them into false success claims.

Evidence: `src/decor2hl7/conformance.py`,
`src/decor2hl7/validation/XsdValidator.java`, `src/decor2hl7/retrieval/fetch.py`,
`tests/test_conformance.py`,
`docs/analyses/2026-09-02-decor-core-validation-follow-up.md`,
`docs/analyses/2026-09-03-core-package-validation.md`.

## DEC-020 — Compound-datatype companion requirements

**Decision:** accepted
**Implementation:** verified

A writable datatype component is not independently executable when a normative
compound-datatype rule requires another component for every non-null
occurrence. These dependencies are declared in the generic HL7 datatype policy,
compiled to concrete CDA targets as `non_null_requires`, and enforced at three
boundaries:

1. proposal generation retains the supported target as review evidence but
   leaves its `cda-mapping.json` field `null` until a mapping supplies the
   required element or one of its descendants;
2. configuration validation rejects reviewed mappings that omit the required
   companion; and
3. rendering checks the populated values occurrence by occurrence after
   mapping and runtime completion, so a companion in one repeated occurrence
   cannot satisfy another.

A null-flavored compound value is exempt because the requirement applies only
to non-null values. A required target-template child is also sufficient because
it is rendered for every active parent occurrence. The mechanism is independent
of clinical field names, target-template identities and XML path constants.

The first applied rule is the normative `EIVL_TS` constraint
`@nullFlavor or hl7:event`. It downgrades the medication event offset from an
executable selection to a review-required candidate because source concept 528
has no proven correspondence to the target TimingEvent domain. No event code or
date is invented. The five mappings present when this decision was accepted
remain executable; DEC-028 later adds five independent detail-product mappings.

This decision encodes one verified datatype invariant. DEC-019 now provides
the independent package gate; its upstream source and terminology findings do
not change the semantic basis of this mapping decision.

Evidence: `src/decor2hl7/cda/datatypes.py`,
`src/decor2hl7/cda/compile.py`, `src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/validate.py`, `src/decor2hl7/bindings.py`,
`src/decor2hl7/cda/render.py`, `tests/test_cda_datatypes.py`,
`docs/analyses/2026-09-02-medication-compound-dependency.md`,
`docs/analyses/2026-09-03-reviewed-edis-attachments-and-decision-review.md`.

## DEC-021 — Open templates and reviewed CDA extension attachments

**Decision:** accepted
**Implementation:** verified

ART-DECOR `isClosed` is part of the executable template constraint model.
Closedness propagates through nested elements and `SPEC` refinement. The CDA
core overlay may supply omitted structural children and attributes only in an
open context; it may still type and complete explicitly selected particles in
a closed context. This prevents CDA XSD permissiveness from turning content
prohibited by a closed template into writable targets.

An open template permits additional CDA-valid content but does not identify a
particular standalone template or establish dataset semantics. `context="**"`,
project membership and neighboring OIDs therefore remain insufficient for
automatic containment. A maintainer may instead record an exact reviewed
attachment in `config/cda-extensions.json`. Each attachment fixes the
transaction, document template, explicitly reachable parent template, parent
element, CDA child particle, target template revision, occurrence constraint
and a non-empty review reason.

`fetch` treats an attached target as an exact structural dependency, closes its
own explicit dependencies recursively and snapshots the normalized attachment
in transaction `closure.json`. `build` accepts it only when that exact target
was fetched, the selected document identity matches, the parent is already
explicitly reachable, the named element is declared by that parent template,
the parent context is open, and the pinned CDA core proves both the child
particle and contained template root legal. A now-explicit upstream containment
makes a stale attachment fail instead of producing a duplicate.

This is a reviewed local profile overlay, not inferred ART-DECOR truth. The
compiled containment wrapper retains `reviewed-extension` provenance, while
the attached template retains its own exact template provenance and openness.
Because the attachment selects one concrete wrapper root, omitted alternative
CDA core choice branches are not materialized at that occurrence.

Evidence: `src/decor2hl7/cda/extensions.py`,
`src/decor2hl7/retrieval/fetch.py`, `src/decor2hl7/cda/compile.py`,
`tests/test_core.py`, `tests/test_cda_datatypes.py`.

## DEC-022 — Reviewed malformed artifact-identity aliases

**Decision:** accepted
**Implementation:** verified

A source catalog entry may declare an exact `alias` from one malformed
published artifact key to one reviewed corrected key. The alias requires a
non-empty reason and cannot carry builtin/waiver payload fields. Retrieval
requests and caches only the corrected identity, while `manifest.json` retains
both keys: the published key has `status: "alias"`, its target and correction
reason; the corrected key owns the bytes and resolved identity.

An alias satisfies a closure dependency only while its target is `ok`. A
missing, partial, waived or erroneous target remains degraded, so an alias can
never fabricate an artifact. Compiler records retain requested and resolved
identities and mark the correction explicitly. The initial reviewed aliases
correct the malformed SNOMED CT CodeSystem OID
`2.16.840.1.1138836.96` and template OID
`2.16.840.1.1133883.17.3.10.1.34`.

Evidence: `src/decor2hl7/retrieval/sources.py`,
`src/decor2hl7/retrieval/fetch.py`,
`src/decor2hl7/retrieval/artifacts.py`,
`tests/test_external_sources.py`.

## DEC-023 — Generated Schematron as supporting mapping evidence

**Decision:** accepted
**Implementation:** verified

`build` may parse the exact template-pattern Schematron it has just generated
for the selected closure and attach a bounded structural subset to compiled CDA
targets: required and maximum occurrences, fixed values, ValueSet references,
required attributes, and concrete `xsi:type` choices. Matching uses the pattern
owner template plus predicate-aware XPath steps; `@see` is ignored and datatype
and vocabulary support files are excluded.

This evidence is supporting-only. It never creates a mapping candidate or a
clinical association. It may strengthen an existing weak or medium candidate
only after the ordinary datatype, payload, location, and occurrence checks pass.
Discriminator construction may also use corroborating ValueSet, fixed-code, and
unpredicated upper-bound evidence. Predicate-specific cardinalities are not
misread as aggregate repeat bounds.

The conformance generator therefore runs before mapping analysis in one build.
If its template-pattern stage does not complete, mapping proceeds without this
optional evidence and records that state in `cda.json`; no artifact from an
earlier build is consumed. Validator success/failure remains an independent
conformance result and does not by itself select or reject a mapping.

Evidence: `src/decor2hl7/compile/schematron.py`,
`src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/compile/structural.py`, `src/decor2hl7/cli.py`,
`tests/test_conformance.py`, `tests/test_core.py`,
`docs/analyses/2026-09-03-phase-6-structural-evidence.md`.

## DEC-024 — Datatype Schematron co-occurrence admissibility

**Decision:** accepted
**Implementation:** implemented

Generated datatype Schematron may disqualify a physical representation without
supplying any dataset-to-CDA semantics. The compiler therefore reads a narrow,
source-derived subset of error-level abstract datatype rules: a negated
conjunction of direct attribute or `hl7:` child-presence selectors, optionally
containing parenthesized unions. It expands unions to bounded forbidden
clauses, preserves conjunctions of more than two selectors, resolves abstract
rule inheritance, records source/test provenance, and reports every unsupported
error assertion. It never evaluates arbitrary XPath and warning-level rules
never become mapping restrictions.

A clause is a hard mapping restriction only when one ordinary non-null target
assignment plus fixed attributes and direct children required by the compiled
template necessarily violates it. This proof marks the target unavailable in
the unproven possible-target inventory, rejects a reviewed mapping at
configuration validation, and is repeated before rendering. Optional sibling
assignments are not combined statically because their co-occurrence—especially
inside repeats—is not guaranteed; the complete generated Schematron remains
the authoritative document-level gate for those cases. If generation is
unavailable, the datatype registry is explicitly unavailable and no constraint
is invented.

When a parent representation is already inadmissible because of required or
fixed structure, direct scalar datatype descendants explicitly named beside
that representation by a compiled co-occurrence clause are reviewable physical
candidates even when generated semantic proposals do not name them as logical
CDA datapoints. Wildcard-only participation does not reopen a whole generic
datatype expansion.
An explicit reviewed physical selection is accepted by configuration only
after the same target existence, uniqueness, writability, datatype,
occurrence, and co-occurrence checks. This widens reviewability, not semantic
automation.

For CEDIS problem-observation `effectiveTime`, template 4040 requires direct
child `width`. `DTr1_IVL_TS.sch` forbids `@value` with any `hl7:` child and also
forbids it with `width` explicitly. The parent timestamp representation is
therefore unavoidably inadmissible, whereas datatype-derived `low/@value` plus
required `width` is structurally admissible. An unmapped required `width` is
rendered with the configured required-value null flavor; this completion does
not establish that `low` is the clinical mapping.

Evidence: `src/decor2hl7/compile/schematron.py`,
`src/decor2hl7/cooccurrence.py`, `src/decor2hl7/compile/mapping.py`,
`src/decor2hl7/validate.py`, `src/decor2hl7/cda/render.py`,
`tests/test_conformance.py`, `tests/test_cda_datatypes.py`,
`tests/test_core.py`,
`docs/analyses/2026-09-05-datatype-schematron-cooccurrence.md`.

## DEC-025 — Conservative ordinal evidence extraction

**Decision:** accepted
**Implementation:** verified

A bare leading integer is ordinal evidence only in an option's primary label,
and only when it is not the prefix of a hyphenated identifier. An unqualified
numeric synonym is code or classification evidence, not rank evidence. A label
or synonym may still supply an ordinal when the number is explicitly associated
with `rank`, `Rankin`, `Rang`, `score`, or `Punkt(e)` wording.

Extracted ordinal values must also be injective across the option list. A
collision removes ordinal metadata from every option in that list. These rules
retain genuine GCS leading ranks and modified-Rankin synonyms while excluding
LOINC identifiers, CEDIS classification numbers, and measurements such as fall
height. Explicit reviewed ordinal maps remain authoritative and do not depend
on generated evidence surviving a later rebuild.

Evidence: `src/decor2hl7/compile/transaction.py`,
`src/decor2hl7/compile/mapping.py`, `tests/test_core.py`,
`docs/analyses/2026-09-05-ordinal-evidence-correction.md`.

## DEC-026 — ART-DECOR examples are non-executable instance data

**Decision:** accepted
**Implementation:** verified

An ART-DECOR `<example>` is an instance fragment, not a constraint or a source
of default clinical facts. Neither `type="neutral"` nor exact membership of an
example code in a constrained ValueSet establishes that the code is true when
source data is absent. CDA compilation therefore does not copy example codes,
display names, timestamps, identifiers, or other instance content into
executable defaults or fixed-value provenance. Runtime also ignores the former
`compiled_default` property in an older compiled model.

Executable construction values must instead come from an actual fixed template
constraint, a normative CDA XSD default, a compiler-owned system role, a mapped
source value, or an explicit reviewed mapping default. An active required leaf
without one of those sources uses the configured null flavor when the template
permits it; a mandatory non-nullable leaf remains an error. When the CDA model
declares the particle as abstract `ANY` but ART-DECOR constrains a concrete
datatype, null-flavor completion retains that compiled `xsi:type` so the result
remains schema-valid.

This decision removes generic example-derived construction defaults. DEC-018's
allergy occurrence rules use exact example captions and discriminator codes as
mapping evidence rather than absent-source construction defaults; AKTIN later
confirmed those agent codes and negation semantics explicitly.

Evidence: `src/decor2hl7/cda/compile.py`, `src/decor2hl7/cda/render.py`,
`src/decor2hl7/bindings.py`, `tests/test_cda_datatypes.py`, `tests/test_core.py`,
`docs/analyses/2026-09-06-template-examples-are-not-defaults.md`.

## DEC-027 — Bounded association identity-lineage closure

**Decision:** accepted
**Implementation:** verified

The exact concepts named by selected-template `templateAssociation/concept` and
legacy/profile `staticAssociations/origconcept` declarations are mapping-evidence
dependencies. `fetch` retrieves their analysis forms as concept-scoped artifacts
and recursively closes only identity-style concept relationships: `SPEC`,
`INHERIT`, `ORIGINAL`, `EQUIV`, `VERSION`, and `COPY`. It does not turn `ADAPT`,
other derivation, template, terminology, or sibling-dataset evidence into a new
recursive crawl. Exact concept scoping bounds both acquisition and the semantic
graph consumed by `build`.

A recovered static association proves a concept-to-legacy-template bridge, not
that the legacy node is the selected active CDA occurrence. When its direct
target lies outside an already selected occurrence, the candidate remains
review-only. A separate explicit template association remains independently
actionable, while the existing DEC-015 rule may project the static association
into the selected occurrence only when one CDA/RIM owner-particle slot and one
in-context target are unique. Schematron support and transform generation cannot
revive an occurrence-mismatch candidate. Weak derivation lineage (`ADAPT` and
similar edges) whose source and related concept names disagree is likewise
review-only; structural compatibility and Schematron constraints cannot repair
that semantic drift. Missing lineage remains missing evidence; it never causes
a guessed association.

Evidence: `src/decor2hl7/retrieval/references.py`,
`src/decor2hl7/retrieval/fetch.py`, `src/decor2hl7/retrieval/artifacts.py`,
`src/decor2hl7/compile/mapping.py`, `tests/test_core.py`,
`docs/analyses/2026-09-06-association-identity-lineage.md`.

## DEC-028 — Exact SPEC-choice overlays and namespace-aware profile extensions

**Decision:** accepted
**Implementation:** verified

A reviewed `select_spec_branch` rule may replace one exact branch explicitly
selected by a specialized template with one exact sibling declared at the same
host element by an inherited `SPEC` choice. The rule fixes transaction,
document, parent, host element, old branch and new branch identities and carries
a review reason. Compilation fails unless the old branch is the one currently
selected, the new branch was fetched exactly, the parent is explicitly
reachable and open, and one exact inherited choice proves the sibling
relationship. The operation does not infer clinical mappings from names or
combine both choice branches.

ART-DECOR design names retain their in-scope prefix-to-URI declarations in the
compiled node and target model. The renderer uses those URIs for expanded XML
names. A template-local target reused at several physical locations remains
non-writable; when each occurrence has a distinct target from a containing
template, the compiler exposes an `anchor::target` alias for that one physical
location. This preserves the no-write-to-ambiguous-target invariant while
allowing reviewed mappings to address a direct occurrence.

The pinned CDA R2 XSD package has no Pharmacy schema. `validate-cda` therefore
checks foreign elements and attributes against the exact compiled physical
paths, validates a projection with only those reviewed foreign nodes
removed against the CDA/SDTC XSD, and applies the exact generated transaction
Schematron to the unchanged original document. This is not presented as
Pharmacy-XSD validation. Supplying and pinning such a schema would permit a
stronger future gate without changing the mapping decision.

An exact dependency request may reuse an already frozen successful dynamic
artifact only when kind, id and resolved effective date match and its checksum
still validates. This avoids a network-only duplicate cache entry without
weakening exact revision identity.

Evidence: `src/decor2hl7/cda/extensions.py`,
`src/decor2hl7/cda/compile.py`, `src/decor2hl7/cda/render.py`,
`src/decor2hl7/conformance.py`, `src/decor2hl7/retrieval/xml.py`,
`src/decor2hl7/retrieval/fetch.py`, `tests/test_cda_datatypes.py`,
`tests/test_conformance.py`, `tests/test_core.py`,
`docs/analyses/2026-09-06-medication-pharmacy-profile.md`.

## DEC-029 — Reviewed scalar CDA construction defaults

**Decision:** accepted
**Implementation:** verified

`target_defaults` may supply either a CDA `nullFlavor` or one reviewed JSON
scalar `value`, but never both. A scalar default requires a non-empty review
reason and is limited to one exact, writable, required scalar target. Its type
must match the compiled value representation, and a compiled finite code
constraint must admit a coded value. When that code selects one unique compiled
coding, the runtime carries its compiled `codeSystem` and display metadata into
the CDA; the same lexical code with different coding companions is rejected as
ambiguous. Identifier values and targets with compound non-null companions
remain excluded because one scalar cannot satisfy their construction semantics.

A scalar default is completion policy, not source data: it never activates an
otherwise unused optional branch. It is applied independently in every active
occurrence, including repeated medication entries. A real mapped value wins in
the same occurrence, allowing a later source discriminator to replace the
default without changing renderer policy.

Site configuration may provide the same activation-scoped completion behavior
under `cda.fallback_if_active`. Attribute and leaf values are consumed only
after another assignment has selected their owning branch; an attribute
fallback cannot activate its optional element. This is suitable for local
author identity and administration details that the dataset does not own, but
it does not create clinical occurrences.

For the selected emergency-department transaction, the CEDIS Problem Concern
Act uses `statusCode="active"` while the presenting complaint is tracked;
`completed` would require explicit closure evidence and would pair with the
concern's `effectiveTime/high`. The aggregate Abschlussdiagnosen Concern Act
uses the same lifecycle policy: diagnoses communicated for handoff remain an
active concern unless the source explicitly says tracking has ended. Its
required concern-start time uses `nullFlavor="UNK"`, because such a time is
applicable but absent from the transaction. These exact defaults activate only
when real final-diagnosis data activates the optional branch.

The final-diagnosis Problem Observation uses the template's explicitly
preferred LOINC statement-kind code `29308-4`, rather than the permitted but
deprecated `75324-4`. This identifies the observation as a diagnosis statement;
the patient diagnosis itself remains in `observation/value`.

Medication currently covers only medication given during treatment in the
emergency department, so its reviewed `moodCode` is `EVN`. Future medication
history and future recommendations must add a per-medication three-way dataset
field. Given-in-ED and medication-history entries map to `EVN`; future
recommendations map to `INT`. Start/stop timestamps do not substitute for that
source distinction.

Evidence: `src/decor2hl7/bindings.py`, `src/decor2hl7/cda/render.py`,
`tests/test_core.py`,
`docs/analyses/2026-09-07-reviewed-scalar-target-defaults.md`,
`docs/analyses/2026-09-08-final-diagnosis-concern-defaults.md`.

## DEC-030 — Compiled entry-to-section narrative links

**Decision:** accepted
**Implementation:** verified

A required CDA entry `text/reference/@value` branch below a section is
document-production infrastructure when all of the following are explicit in
the effective compiled constraint: the entry `text` has an element-text
representation, its direct `reference` child is required, and the child's
unfixed `value` attribute is required. Compilation marks the entry text as a
linked-narrative source, marks the reference value as compiler-supplied, and
records the exact physical relationship to the containing section narrative.
It does not depend on a template id, medication field name, or prose example.

For every active entry occurrence, rendering creates one deterministic,
document-local fragment identifier, writes it as `reference/@value`, and adds a
matching CDA narrative `content/@ID` node to that occurrence's containing
section. A mapped entry-text scalar supplies the human-readable content. If it
is absent, the renderer derives minimal wording from the same entry occurrence's
other explicitly mapped values and finally falls back to the compiled template
display name. Repeated entries and repeated sections retain their normalized
occurrence boundaries; references never share or zip independent rows.

The mapped scalar is not duplicated as raw mixed content in the entry `text`,
and generated reference targets are not offered as clinical mapping endpoints.
The section narrative remains intentionally minimal, but every generated
fragment reference resolves within the document.

Evidence: `src/decor2hl7/cda/compile.py`, `src/decor2hl7/cda/render.py`,
`src/decor2hl7/bindings.py`, `tests/test_cda_datatypes.py`.

## DEC-031 — Explicit child constraints in non-monotonic SPEC designs

**Decision:** accepted
**Implementation:** verified

ART-DECOR `SPEC` formally denotes specialization, so a child is expected to
narrow rather than broaden its parent. Published designs can nevertheless
contain an explicit child constraint that is broader than its declared parent.
The compiler follows the executable child design in that case: explicit child
cardinality and mandatory flags are authoritative, while omitted properties
are inherited. In particular, an explicit child minimum of zero clears an
inherited mandatory flag unless the child explicitly says it is mandatory.

Every such minimum, maximum, or mandatory weakening is retained as a
`spec-constraint-weakening` warning in `cda.json` and the build diagnostics.
`build --strict-specializations` converts any warning into a build error for
users who require monotonic specialization. This policy also applies to
included template groups.

The AKTIN Medikation template explicitly changes its UV Medication Statement
parent's `statusCode` from `1..1 M` to `0..1 R`; its generated Schematron likewise
allows omission. The effective target is therefore optional. It is omitted
when the dataset has no medication lifecycle datum, and no ActStatus default is
invented. Medication mood, order mood, administration occurrence and lifecycle
status remain distinct clinical facts.

Evidence: `src/decor2hl7/cda/compile.py`, `src/decor2hl7/compile/artifacts.py`,
`src/decor2hl7/cli.py`, `tests/test_core.py`,
`docs/analyses/2026-09-08-spec-relaxation-and-medication-state.md`.

## DEC-032 — Namespace-aware ART-DECOR assertion evaluation

**Decision:** accepted
**Implementation:** verified

Each compiled ART-DECOR assertion retains the namespace bindings in scope on
its source template. The in-process assertion evaluator resolves every QName
through that map, with the project's known-prefix table as compatibility for
older compiled models. Generated `cda-assertions.sch` declares every prefix
used by an assertion path, test, or let expression and fails compilation for
an unknown or conflicting binding.

This is required for assertions over selected profile extensions. In
particular, the UV Ingredient rule tests `pharmhl7:code or pharmhl7:name` in
the `urn:hl7-org:pharm` namespace. Lexically treating `pharmhl7` as part of an
unnamespaced element name produces a false failure even when both children are
present in the XML.

Evidence: `src/decor2hl7/assertions.py`, `src/decor2hl7/cda/compile.py`,
`tests/test_core.py`,
`docs/analyses/2026-09-08-final-diagnosis-concern-defaults.md`.

## DEC-033 — Reviewed allergy time construction

**Decision:** accepted
**Implementation:** verified

AKTIN confirmed that Allergy Concern Act `effectiveTime/low` denotes the start
of documenting the concern, not the clinical onset of the allergy. The reviewed
mapping therefore uses `administrative_aufnahmeinformationen.aufnahmezeitpunkt`
as an activation-scoped fallback for `Allergyconcernact.low`.

This rule may fill the mandatory `low` only when another mapped allergy value
has already activated that optional branch. It cannot create an Allergy Concern
Act or another repetition by itself. If an activated allergy occurrence has no
admission time, rendering fails instead of inventing a time.

The allergy onset belongs to Allergy Intolerance Observation `effectiveTime`.
Because the selected transaction provides no onset, the reviewed mapping emits
`nullFlavor="UNK"` on that required element. A complex required element may use
such a target default only when the compiled template exposes a writable,
optional `@nullFlavor`; other complex defaults remain invalid.

The observation's mandatory `statusCode` describes completion of the assertion,
not resolution of the allergy or closure of the concern. The reviewed mapping
uses ActStatus `completed`, consistently with every active-template example;
the Allergy Concern Act retains its independent lifecycle status.

Evidence: AKTIN maintainer clarification for templates
`1.2.276.0.76.10.2036@2016-06-01` and
`1.2.276.0.76.10.4066@2015-09-18`, `src/decor2hl7/bindings.py`,
`src/decor2hl7/cda/compile.py`, `src/decor2hl7/cda/render.py`,
`src/decor2hl7/validate.py`, `tests/test_core.py`.

## DEC-034 — Bounded receiver transport adapters

**Decision:** accepted
**Implementation:** verified

Site configuration selects one built-in transport adapter by exact name. Each
adapter has a closed set of accepted options and validates them before reading
or transmitting a document; configuration cannot name importable code or add
undeclared protocol settings. The adapter boundary is a small typed send
function rather than a class hierarchy.

The only current adapter is `http-post`. It sends one CDA XML document as one
HTTP or HTTPS POST and accepts only `url`, positive integer `timeout`, and
single-line scalar `headers`. Existing site configurations without `adapter`
continue to select `http-post`; newly generated site configuration records the
selection explicitly. Unknown adapters and options fail before document or
network I/O.

Batch envelopes, receiver acknowledgements, authentication protocols and
idempotency semantics are deliberately not generalized as configuration. A
future receiver adapter must implement and validate one specified protocol in
code. It may extend the transport result contract only together with the
durable state changes required to interpret per-document acknowledgement.

Evidence: `src/decor2hl7/transport.py`, `src/decor2hl7/cli.py`,
`src/decor2hl7/testing.py`, `tests/test_transport.py`, `tests/test_cli.py`.

## DEC-035 — Versioned authored mapping scenarios

**Decision:** accepted
**Implementation:** verified

Reusable mapping scenarios are authored as CSV source sets with a manifest,
stored beneath their release key and exact transaction key. The manifest also
pins transaction OID and effective date; setup rejects a mismatch instead of
adapting old data to a new compiled specification. Source cardinality, joins,
and occurrence identity are explicit configuration and are never inferred from
filenames or row position.

`setup-test --scenario` copies the declared sources into an isolated generated
fixture and derives its CSV/code/site configuration and `expected.json` from
the selected model and mapping. The authored contract may declare suite-wide
mapping coverage plus per-case present/absent model fields and CDA template IDs.
This permits mutually exclusive choices to be tested across complete records.
Generated CDA output is not accepted as its own golden oracle.

The scenario manifest may also declare local `site.cda.values`,
`site.cda.fallback_if_active`, and input-code translations. A translation for
an unbound dataset code may be an explicit `{code, codeSystem, displayName}`
object; both code and code-system identity are required and remain site/input
configuration. It cannot replace or extend a bound formal dataset terminology.

The deterministic synthetic generator remains available when no scenario is
specified, but the repository reference `testrun` uses the pinned authored set.
Scenario names describe the complete record set; individual records use neutral
`SCENARIO-*` identifiers rather than naming one partial clinical feature as the
whole document.

Evidence: `src/decor2hl7/testing.py`, `src/decor2hl7/cli.py`, `Makefile`,
`tests/test_cli.py`, `tests/test_scenarios.py`,
`tests/fixtures/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases/`.

## Maintenance rule

A pull request that changes project semantics must update the affected decision
entry, known issue, regression test and user-facing documentation together. A
new decision should use the next stable `DEC-*` identifier. Superseded decisions
remain in this register with a link to their replacement.
