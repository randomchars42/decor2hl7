# Section overlay correction and mapping priorities — 2026-09-01

## Scope

This record captures the fresh-snapshot investigation prompted by repeated
`Emergency medicine Note CDA document ... — no selected dataset mapping`
entries in the document-body mapping report. It also records the decision to
retain flattened target identifiers and preserves the allergy and medication
findings as the next two implementation priorities.

Evidence comes from the fresh `spec/` snapshot for release `2026.1.2`,
transaction `notaufnahmeregister--60`.

## Repeated document-section diagnosis

The report entries were not comments. The compiled document contained 30
physical `section` nodes: the 15 explicit specialized sections supplied through
document `contains` wrappers plus 15 generic `POCD_MT000040.Component3/section`
siblings. The generic target inherited the document template label and resolved
to 15 locations, so the concise report printed the same unselected document
heading 15 times. Rendering could consequently emit an empty generic
`<section nullFlavor="NI"/>` beside the real contained section.

The cause was in structural overlay. Direct children alone were checked when a
CDA/RIM definition particle was materialized. `include` and `contains` wrappers
remain in the compiled tree for provenance and occurrence semantics but create
no XML node, so their element descendants must participate in that match.

The correction traverses only transparent `include`/`template` wrappers while
matching existing element children. Every wrapped match receives the structural
datatype and combined `template + cda-rim` provenance. A generic child is added
only when no explicit descendant supplies that particle. This is procedural and
does not know any CDA class or section name.

The same expansion exposed a stale mapping assumption: group placement treated
the absence of `datatype` as the definition of a structural container. Explicit
sections and clinical statements now correctly carry RIM structural datatypes,
so the selector briefly stopped locating the medication section and statement.
It now selects explicit, renderable, non-writable element containers with
children and excludes generated datatype descendants. That restores the
medication `for_each` without a medication-specific exception.

Fresh-build results after both generic corrections:

- 15 physical sections, all specialized; zero document-owned generic sections;
- 24,743 physical named targets, down from 26,170 by removing only duplicate
  generic section subtrees;
- 69/120 proposed executable source fields and 71 logical targets, unchanged;
- all three `for_each` rules retained, including
  `for-each-masnahmen-medikamentose-therapie` targeting
  `medikamentose-therapie.entry`;
- the repeated Emergency-document report heading occurs zero times.

## Target-name decision

Generated target identifiers keep their current flattened form. Names such as
`code.code_9267-6.observation.value` can be visually awkward, but changing them
would churn mapping configuration, tests and downstream references without
changing CDA semantics. The target name is a stable key, not the authoritative
tree representation.

The non-flattened structure remains available through each target's `path` and
physical `locations`, and through `cda-expanded-readable.xml` / `.md`. Future
readability work should improve those views or add display paths rather than
rename executable keys unless a broader versioned mapping migration is already
required.

## Priority 1 — allergy payload mapping

The available target structure is stronger than the current mapping:

- Allergies and Intolerances section: `1.2.276.0.76.10.3051`;
- contained Allergy Concern Act: `1.2.276.0.76.10.4065`;
- contained Allergy Intolerance Observation: `1.2.276.0.76.10.4066`;
- fixed observation `code=ASSERTION` and `value=OINT`;
- required allergen path:
  `participant/participantRole/playingEntity/code`, datatype `CE`, bound to
  ValueSet `1.2.276.0.76.11.52`;
- writable section narrative.

Four source fields currently stop at section context: allergy description,
agent, antibiotic-allergy flag and contrast-agent-allergy flag. No safe leaf
proposal is available yet because the source agent concept list has no resolved
members in the compiled snapshot. The antibiotic and contrast flags are marked
with diagnosis/disorder concepts `Z88.1` and `293637006`; these are not
allergenic substances and cannot be serialized as the required agent code.
Their source comments describe derived information, so they need an explicit
derivation/representation decision.

Next safe work:

1. retrieve or otherwise resolve the source agent terminology/list;
2. establish source agent to bound `playingEntity/code` evidence;
3. decide reviewed placement for description/narrative/originalText;
4. represent the two derived flags explicitly and verify occurrence semantics.

## Priority 2 — medication payload mapping

The structural mapping is valid and must be retained:

- section `1.2.276.0.76.3.1.195.10.64` contains Medikation
  `1.2.276.0.76.3.1.195.10.67`;
- repeated source `masnahmen.medikamentose_therapie` is aligned to repeated
  section `entry` by `for_each`;
- one shared section contains one entry per source medication.

The scalar gap is not caused by missing CDA/RIM expansion. Source association
evidence points to PMP Material `1.2.276.0.76.10.90022`, but the active product
branch is UV Medication Information (simple)
`2.16.840.1.113883.10.21.4.10`. The outer Medikation template marks
`effectiveTime`, `doseQuantity`, `rateQuantity` and `administrationUnitCode` as
`NP`. Dose and rate are available under repeatable UV Subordinate administration
`2.16.840.1.113883.10.21.4.6`, creating an additional occurrence boundary.

The remaining steps therefore stay those in
`2026-08-30-medication-mapping-plan.md`: model compound values, establish
cross-template field evidence, resolve exact terminology, align nested
occurrences and add zero/one/many output tests. Neither importing the IHE
Medicine Entry constraints nor selecting datatype-expanded leaves by name would
prove the missing semantics.
