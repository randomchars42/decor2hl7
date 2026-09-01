# Medication mapping through common CDA/RIM slots

Date: 2026-09-01

## Question

The transaction associates medication source concepts with constraints from a
PMP/legacy material profile, while the effective document uses UV Medication
Information (simple). Both profiles serialize through common CDA/RIM class
particles. Can the formal association be made executable without hard-coding a
medication template, datatype, or leaf name?

## Implemented evidence chain

The mapping compiler now indexes both `templateAssociation` and ART-DECOR
`staticAssociations/origconcept`. For a static association it:

1. resolves the referenced constraint and its owning CDA/RIM XSD class;
2. identifies the exact structural particle represented by that constraint;
3. finds the same particle in the active, already mapped target context;
4. requires one unique nearest active occurrence; and
5. applies the normal datatype, cardinality and occurrence checks.

The association is therefore projected through a machine-readable common model
slot, not through matching names. Ambiguous slots or target occurrences remain
report-only evidence.

Two adjacent generic changes complete the value path. The XSD index preserves
`complexType/@mixed`, allowing a complex mixed-content root to compile an
element-text representation. An open coded target with exactly one declared
CodeSystem can use the declarative `code_system` transform, which preserves the
normalized source code and supplies the target CodeSystem OID. The renderer
continues to consume only compiled representations and assignments.

Candidate compatibility also considers a provisionally derived `for_each`
before field selection. This uses the same source-group/target-repeat alignment
as final validation; it does not introduce positional repeat matching.

## Fresh-snapshot result

The fresh `2026.1.2` `spec/` snapshot builds successfully, with its pre-existing
degraded dependency state (21 unavailable artifacts and one unresolved CDA
reference). The selected proposal increases from 69/120 before this pass to
73/120. This also exceeds the historical 64/120 after PR #9 and 59/120 after
the first model-expansion pass.

The following medication fields are now executable:

| Source field | Effective target meaning | Formal bridge |
| --- | --- | --- |
| `arzneimittelname` | manufactured-material name | static association → CDA/RIM `Material.name` → XSD mixed text |
| `arzneimittelcode` | manufactured-material product code | static association → CDA/RIM `Material.code` → declared open CodeSystem |
| `dosierung.freitext` | administration narrative | static association → CDA/RIM `SubstanceAdministration.text` |
| `dosierung.art_der_anwendung` | route code | static association → CDA/RIM `SubstanceAdministration.routeCode` |

The generated product-code rule carries CodeSystem
`1.2.276.0.76.4.6`. A runtime assignment check with one medication produced one
entry containing the product name, normalized product code and code-system OID,
dosage narrative, and route, with no assignment problems.

`chargennummer` remains unmapped. The target model exposes a lot-number slot,
but the fetched source concept has no formal association to it; selecting it by
its label would violate the evidence rules.

## Remaining medication work

- Find or establish formal source evidence for lot number.
- Model detailed dose, rate, schedule, duration and unit values without
  collapsing compound clinical meaning into scalars.
- Resolve terminology and nested occurrence ownership for repeatable UV
  Subordinate administration.
- Extend production fixtures for zero, one and repeated medications as those
  additional compound fields become executable.

The existing section-entry `for_each` remains the occurrence mechanism. No
medication class, template OID, product identifier or field name is embedded in
the mapper or renderer.

## Verification

- 141 unit tests pass.
- A fresh-snapshot `decor2hl7 build` completes and proposes 73/120 fields.
- Synthetic rendering verifies mixed-content root text plus open-code-system
  output.
- The medication assignment regression verifies one aligned source occurrence
  and no binding problems.

## Evidence

- fresh `decor2hl7-test-workspace` `spec/2026.1.2` snapshot
- `src/decor2hl7/compile/mapping.py`
- `src/decor2hl7/cda/core.py`
- `src/decor2hl7/cda/compile.py`
- `src/decor2hl7/transforms.py`
- `tests/test_core.py`
- `tests/test_cda_datatypes.py`
- `DEC-007`, `DEC-013`, `DEC-014`, and `DEC-015`
