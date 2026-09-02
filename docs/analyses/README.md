# Dated analyses

Files in this directory are evidence snapshots: they record the source material,
counts, assumptions and conclusions available on their stated date. They are not
silently edited to describe later code.

Current project behaviour is documented in `../architecture.md`; accepted and
open decisions are indexed in `../decisions.md`; unresolved deployment or
external boundaries are maintained in `../known-issues.md`.

Current focused implementation plans:

- [`2026-09-02-residual-mapping-boundaries.md`](2026-09-02-residual-mapping-boundaries.md)
  records the post-PR #20 93/120 fresh-snapshot audit, all six executable
  medication mappings, the three-way medication timing collision, the
  secondary ICD occurrence-versus-translation decision, seven smaller
  residuals and the formal physical-plus-semantic evidence boundary.
- [`2026-09-02-allergy-example-discriminators.md`](2026-09-02-allergy-example-discriminators.md)
  records the exact active-template examples that close the antibiotic/contrast
  flag boundary, the generic inverse-negation/discriminator rule, exact-agent
  coalescing, the 91→93 fresh-snapshot gain and the still-open Concern Act time.
- [`2026-09-01-spec-derived-target-recovery.md`](2026-09-01-spec-derived-target-recovery.md)
  records the fresh-snapshot 74→91 recovery, choice/ANY/occurrence/presence
  mechanisms, corrected boolean negation semantics and deliberately unresolved
  allergy, medication and secondary-diagnosis boundaries.
- [`2026-09-01-open-coded-allergy.md`](2026-09-01-open-coded-allergy.md)
  records the implemented empty-owned-domain classification, the generic
  target-ValueSet `OTH`/`originalText` derivation for `Agens`, fresh-snapshot
  coverage, and the then-open description/derived-flag boundary. The newer
  recovery analysis records the resolved narrative and still-open mandatory
  concern timestamp plus derived-flag boundary.
- [`2026-09-01-medication-common-base-slot.md`](2026-09-01-medication-common-base-slot.md)
  records the implemented static-association projection, XSD mixed-content and
  open-code handling, the resulting medication mappings, and the remaining lot
  and detailed-dosage boundaries.
- [`2026-09-01-section-overlay-and-mapping-priorities.md`](2026-09-01-section-overlay-and-mapping-priorities.md)
  records the transparent-wrapper section correction, the stable flattened-name
  decision, and the allergy/medication evidence that now heads the priority list.
- [`2026-08-30-medication-mapping-plan.md`](2026-08-30-medication-mapping-plan.md)
  records the medication gap plan and the completed IHE Medicine Entry artifact
  check.
- [`2026-08-30-cda-datatype-expansion.md`](2026-08-30-cda-datatype-expansion.md)
  records the current-template datatype inventory, the rewrite boundary and why
  medication/pupil occurrence rules remain.
- [`2026-08-30-cda-structural-expansion.md`](2026-08-30-cda-structural-expansion.md)
  records the normative XSD source and structural-to-datatype acceptance cases.
- [`2026-08-31-cda-mapping-recovery.md`](2026-08-31-cda-mapping-recovery.md)
  records the fresh-spec integration gates, PR #9 field-by-field comparison and
  terminology-derived pupil discriminator evidence.
- [`2026-09-01-cda-structural-expansion-checkpoint.md`](2026-09-01-cda-structural-expansion-checkpoint.md)
  records the completed fresh-snapshot production gates, generic fixes found by
  them, final coverage and publication criterion.
