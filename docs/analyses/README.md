# Dated analyses

Files in this directory are evidence snapshots: they record the source material,
counts, assumptions and conclusions available on their stated date. They are not
silently edited to describe later code.

Current project behaviour is documented in `../architecture.md`; accepted and
open decisions are indexed in `../decisions.md`; unresolved deployment or
external boundaries are maintained in `../known-issues.md`.

Current focused implementation plans:

- [`2026-09-03-reviewed-edis-attachments-and-decision-review.md`](2026-09-03-reviewed-edis-attachments-and-decision-review.md)
  records the exact reviewed DEC-021 attachments for `.10.85`–`.10.87`, the
  resulting 92→95 mapping gain, the corrected mandatory `value` targets and
  hour-unit normalization, the no-change DEC-015 re-review, and DEC-020's
  compound event/offset enforcement boundary.
- [`2026-09-03-closure-phase-4.md`](2026-09-03-closure-phase-4.md)
  records the retrieval evidence settling the last five build-degrading
  artifacts: the two VSAC medication value sets expand to genuinely empty
  results and are only reached by rules on a C-CDA template the selected
  document never instantiates; the AKTIN referral-actions value set cannot
  expand because its DIVI intension code system is published nowhere; and the
  CCD Product SPEC parent exists in no revision but `2007-04-01`. Records the
  resulting 5→3 `build_degraded` and `complete: true` metrics. Also records the
  reference-declaration identity gap that made `fetch --offline` report cached
  code systems as missing, and its fix. Closes phase 4 of the root
  [`PLAN.md`](../../PLAN.md).
- [`2026-09-03-closure-gap-analysis.md`](2026-09-03-closure-gap-analysis.md)
  records why the reference `spec/2026.1.2` closure is `degraded`: of 62 missing
  artifacts only 21 are build-degrading, a plain `fetch` never re-probes settled
  failures, the 65 validator errors are a separate value-set-expansion problem,
  and each degrading resource is sorted into a display-reclassification,
  `$expand`, exact-revision, reference-identity or waiver bucket. Supports
  workstream A of the root [`PLAN.md`](../../PLAN.md).
- [`2026-09-03-core-package-validation.md`](2026-09-03-core-package-validation.md)
  records the implemented checksum-pinned DECOR-core/full-CDA validation stack,
  the source-versus-compiled execution boundary, reference diagnostics,
  fail-closed exact-validator provenance and the unchanged mapping conclusions.
- [`2026-09-02-seven-active-profile-gaps.md`](2026-09-02-seven-active-profile-gaps.md)
  records the post-medication investigation of the seven smaller no-target
  fields: one bounded insurance-number review candidate, three exact EDIS
  metadata entries stranded outside the selected containment, and three fields
  needing a complete active representation or crosswalk. It also corrects the
  earlier MRI wording: the statement is reachable, but has no region-bearing
  target.
- [`2026-09-02-medication-compound-dependency.md`](2026-09-02-medication-compound-dependency.md)
  records the completed medication audit after the DECOR-core follow-up, the
  generic occurrence-aware compound-datatype safety mechanism, the offset
  downgrade, current 92/120 coverage, five executable medication mappings and
  the exact evidence needed before the remaining medication fields can reopen.
- [`2026-09-02-decor-core-validation-follow-up.md`](2026-09-02-decor-core-validation-follow-up.md)
  records the deferred DECOR-core/full-CDA validation integration, the
  source-versus-compiled association distinction, exact package evidence,
  additional datatype/template rules, the EIVL event dependency that requires
  revalidating the medication offset, and the complete restart checklist. It
  finds no current mapping-coverage gain.
- [`2026-09-02-residual-mapping-boundaries.md`](2026-09-02-residual-mapping-boundaries.md)
  records the post-PR #20 93/120 fresh-snapshot audit, the six medication
  mappings then considered executable, the three-way medication timing
  collision, the secondary ICD occurrence-versus-translation decision, seven
  smaller residuals and the formal physical-plus-semantic evidence boundary.
  The newer DECOR-core analysis above requires revalidating or downgrading the
  event offset and deliberately does not rewrite this dated snapshot.
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
