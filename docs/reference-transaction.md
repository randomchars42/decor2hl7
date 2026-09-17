# AKTIN 2026.1.2 reference transaction

This page records only non-obvious reviewed policy for release `2026.1.2`,
transaction `notaufnahmeregister--60`. Exact field selections belong to the
reviewed `cda-mapping.json`; generated coverage and diagnostics belong to the
reference workspace. Counts are not copied here because they change whenever
the workspace is rebuilt or reviewed.

Related decisions: DEC-008, DEC-009, DEC-018, DEC-029, DEC-033, DEC-036,
DEC-038, DEC-041, DEC-042, DEC-043, DEC-044, and DEC-045.

## Evidence boundary

The selected transaction and exact reachable templates are authoritative. The
reviewed recovery overlay in
[`recovery/2026.1.2-notaufnahmeregister--60-reviewed-cda-overrides.json`](recovery/2026.1.2-notaufnahmeregister--60-reviewed-cda-overrides.json)
preserves human decisions that the owner-rule proposal correctly declines to
infer. It is accepted policy only for the model and CDA hashes it records.

## Allergy

The allergy group maps to the selected Allergies and Intolerances section,
Allergy Concern Act, and Allergy Intolerance Observation.

- `Agens` is an explicitly unconstrained source code. An exact admitted
  target-member code/system is retained; other agent wording uses the target
  ValueSet's `OTH` plus `originalText` contract.
- Antibiotic and contrast-agent booleans create exact `A07AA` and `V08`
  discriminator occurrences. `true` means a positive assertion
  (`negationInd=false`), `false` means an explicit negative assertion, and an
  absent source emits no occurrence. Equal explicit agent occurrences coalesce.
- Allergy description maps to section narrative.
- Allergy Concern Act `effectiveTime/low` is the start of documenting the
  concern. Admission time supplies it only after another allergy value activates
  the branch.
- The transaction supplies no clinical allergy onset, so the required
  observation time uses `nullFlavor="UNK"`.
- Allergy Intolerance Observation `statusCode="completed"` describes completion
  of the assertion, not resolution of the allergy or concern.

## Diagnoses and referral

- V/A/Z/G maps occurrence-locally to diagnosis certainty. `A` also controls
  exclusion negation. `Z` does not create `effectiveTime/high` because it
  supplies no timestamp.
- Required diagnosis onset uses `nullFlavor="UNK"`; no date is invented.
- Final-diagnosis Concern Act status is `active` while diagnoses remain relevant
  for handoff. Its unknown start uses `nullFlavor="UNK"`.
- Final-diagnosis Problem Observation uses the template-preferred LOINC
  statement code `29308-4`; the diagnosis itself remains in the observation
  value.
- AKTIN confirmed that secondary ICD-10 has no target in this profile. It is
  intentionally unmapped and is not represented as `CD.translation` or an
  inferred additional observation.
- `Typ Verlegung` uses one exact finite `reviewed_coded_map` across the still
  unresolved Referral Actions binding. This authorizes only its enumerated
  target outputs and does not close the terminology gap.

## Imaging

MRI and X-ray examination regions are reviewed wording-only mappings to the
Diagnostics section narrative:

- MRI region is one labelled fact, `MRT – Untersuchungsregion`;
- X-ray region is a `for_each` fact, `Röntgen – Untersuchungsregion`, which
  preserves every source occurrence and its order.

Both source fields remain `null` under structured `fields`. These rules do not
claim a region-bearing MRI particle, a complete X-ray code crosswalk, or any
selection, coalescing, or conflict relationship with structured diagnostic
entries. Those structured mapping questions remain open.

## Medication

The baseline follows the exact simple UV Medication Information branch selected
by the AKTIN Medikation template. The richer sibling detail branch is evidence,
not authority to replace that selection.

Current reviewed behavior is:

- one shared medication section contains one entry per repeated source
  medication;
- product code and product name are composed into the selected simple-branch
  `manufacturedMaterial/code`: the configured product code uses the German PZN
  code-system OID and the product name supplies `displayName`; with a name but
  no code, the template-required `nullFlavor="NA"` is emitted and the name is
  retained in `originalText`;
- product name is also the first contribution to the existing medication
  narrative concatenation; it is not mapped to the open-template CDA/RIM name
  leaf;
- ingredient name and code, the explicit active-ingredient answer, and verbatim
  strength are separately labelled contributions to the same occurrence-local
  medication narrative; the boolean is rendered as `ja` or `nein`, while an
  absent answer contributes nothing;
- application start maps to the atomic subordinate-administration `TS` choice;
- dose and continuous rate map to `doseQuantity` and `rateQuantity`, with scalar
  and range quantities using compiled representations;
- body site maps to `approachSiteCode`, retaining exact codes and otherwise
  using the target's reviewed `OTH`/`originalText` behavior;
- administration form populates required-bound `administrationUnitCode` only
  when input supplies an exact code/system; uncoded wording goes to narrative;
- route coalesces `Art der Anwendung` and `Methode der Anwendung`, preferring
  the first with a visible warning when both differ;
- product name, ingredient wording, dosage text, additional dosage instructions,
  patient intake instructions, event-offset wording, true PRN, medication
  reasons, and uncoded form wording are concatenated in reviewed order into
  medication narrative;
- medication root and subordinate administration mood/status are site-owned
  activation-scoped requirements, not compiler defaults.

The medication mapping records these deliberate null selections:

| Source field | Current reason |
|---|---|
| Application stop | The selected atomic branch exposes no distinct stop slot |
| Structured dosage time | Outside the current medication-given scope |
| Event-relative repetition event | Timing construction is deferred; offset is narrative only |

Ingredient name/code/indicator/strength, additional dosage instructions, and
intake instructions therefore no longer remain untransmitted. Their structured
ingredient and instruction targets remain open: the selected simple branch has
no ingredient container, source ingredient strength is free text rather than a
ratio, and the two unconstrained code domains establish no code-system bridge.

Medication history, recommendations, orders, and non-administration require an
explicit per-medication source discriminator. Start/stop times do not establish
mood or lifecycle state.

## Other reviewed construction

- The three EDIS metadata entries are attached to the open Addendum section by
  exact reviewed profile overlays until upstream containment exists.
- Document confidentiality and language are unconditional site values.
- Author name is an activation-scoped site fallback.
- Document identifiers, versioning, creation time, custodian content, and
  narrative links are compiler/runtime construction roles rather than dataset
  mappings.
- The retained documentation-start concept is intentionally unmapped because
  AKTIN reports that no current target template uses it.

Remaining profile and publication questions are in
[`open-boundaries.md`](open-boundaries.md).
