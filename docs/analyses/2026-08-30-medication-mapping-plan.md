# Medication mapping plan and Medicine Entry check

Date: 2026-08-30

## Status

This is the open implementation plan for closing the selected-dataset mapping
gap for `Medikamentöse Therapie` (`medikamentose-therapie`). Steps 1 and 2 are
complete; steps 3 through 6 remain open. Any clinical mapping still requires formal
evidence and review under `DEC-003` and `DEC-011`.

## Step 1 — verify the exact IHE Medicine Entry artifact

The `decor2hl7-test-workspace` demo workspace contains the exact analysis
artifact for IHE Medicine Entry
`1.3.6.1.4.1.19376.1.9.1.3.1@2019-08-27T16:13:43`. Its manifest entry is `ok`,
the analysis representation validates, and only the optional source
representation is unavailable. Under `DEC-004`, this is already sufficient for
dependency cache/build availability; no builtin or reconstructed XML is needed.

The artifact contributes 49 named target constraints to the registry, including
manufactured material, medication code and name, form code, lot number,
packaging, generic material and ingredient strength. In the selected AKTIN
document, however, all 49 have no CDA location and are non-renderable. The
reference is specification evidence rather than part of the effective document
branch.

The effective medication branch instead uses
`UV Medication Information (simple)`
`2.16.840.1.113883.10.21.4.10@2021-09-29T12:35:45`. It already exposes seven
renderable targets in the current model: template identity, manufactured
product, manufactured material, medication code, code translation, lot number
and manufacturer organization. This corrects the earlier assumption that the
manufactured-product children were absent; they are present under the UV
template's target names rather than the `Medikation.*` prefix.

### Result

Artifact acquisition does not close the mapping gap and does not add executable
mapping candidates. It does help by ruling out a missing-template cause and by
locating the actual boundary: mappings must target the active UV medication
profile, while IHE-only fields such as medication name, form and ingredients
cannot be made writable by importing or copying the IHE artifact. Injecting
those constraints would invent a relationship not present in the selected CDA
closure.

## Step 2 — align medication occurrences

The selected dataset has one repetition level:
`masnahmen.medikamentose_therapie` is `0..*`, while its `medikation` child and
all product, dose, time and reason groups are at most one within each occurrence.
The active CDA path has two repetition-capable ancestors: the medication
`section` and its `entry`; each entry contains at most one
`Medikation.substanceAdministration`.

The compiler now recognizes the unique section → repeated entry → singular
statement shape from the mapped parent and child groups and proposes:

```json
{
  "type": "for_each",
  "source_group": "masnahmen.medikamentose_therapie",
  "target_repeat": "medikamentose-therapie.entry"
}
```

The runtime uses the named target repeat rather than positional list depth. Two
source medication occurrences therefore render as one shared medication section
with two entries, not as two sections. Validation rejects missing, duplicate,
non-repeating or non-renderable repeat anchors. The inference is deliberately
limited to a unique mapped section, one singular mapped child group and exactly
one intervening repeated CDA entry; ambiguous structures produce no rule.

This step establishes occurrence ownership only. It selects no clinical field
mapping and does not resolve product identifiers, dose components, route,
schedule, form or ingredient terminology.

## Remaining plan

3. **Represent compound values.** Define target-neutral source structures for
   medication product/code, dose, route, schedule and duration, then bind only
   the parts exposed by the active CDA profile. Do not flatten compound clinical
   meaning into an ambiguous scalar.
4. **Add reviewed field mappings.** Map dataset concepts to the active UV and
   subordinate-administration targets where datatype, terminology and
   cardinality evidence agree. Keep unsupported IHE-only leaves explicitly
   unmapped.
5. **Resolve terminology.** Add exact ValueSet/CodeSystem evidence and explicit
   crosswalks for medication product identifiers, route, units and schedule;
   never infer equivalence from labels alone.
6. **Verify occurrences and output.** Add regression fixtures covering zero,
   one and repeated medications; incomplete optional fields; required unknown
   values; and rejection of ambiguous occurrence associations. Rebuild the demo
   workspace and compare selected, executable and intentionally unmapped
   targets.

## Immediate next question

Step 3 should determine which dataset medication values are genuinely scalar
and which require compound target-neutral representations before field-level CDA
bindings are reviewed. Occurrence ownership is now explicit, so that work can
proceed without mixing sibling medications.

## Evidence

- `decor2hl7-test-workspace` current `spec/` manifest and exact Medicine Entry
  analysis artifact
- `decor2hl7-test-workspace` current compiled `model/cda.json`
- `docs/analyses/2026-08-27-fresh-retrieval-analysis.md`
- `docs/analyses/2026-08-30-external-artifact-phase-1.md` (earlier snapshot;
  its unresolved-artifact statement is superseded by this check)
- `DEC-004`, `DEC-011` and open `DEC-012` in `docs/decisions.md`
