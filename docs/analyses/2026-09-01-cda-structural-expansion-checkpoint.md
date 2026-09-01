# CDA structural expansion completion record — 2026-09-01

## Purpose and publication state

This record describes the implementation and its final pre-publication
verification state. No remote branch or `main` commit had been modified when
the production gates below were completed.

The integration source is the fresh `spec/` snapshot from
`randomchars42/decor2hl7-test-workspace` at commit
`d9c603bc634ca9fec756c4ecbfed1c432518b12a`, release `2026.1.2`, transaction
`notaufnahmeregister--60`.

## Current verified measurements

- clean `build`: 120 datapoints, 57 groups, 308 reachable templates;
- compiled CDA: 26,170 physical named targets and 71 logical mapped targets;
- proposed mapping: 69/120 non-null source fields and 71 logical targets;
- PR #9 baseline: 62/120 non-null fields and 64 logical targets;
- comparison: all 62 accepted fields retained, seven fields gained, no loss;
- unit suite: 137 tests pass;
- bytecode compilation and `git diff --check` pass;
- accepted 62-field production fixture: one assertion-valid document;
- 69-field proposal: assertion-valid discharge and transfer documents in two
  mutually exclusive scenarios.

The build remains explicitly degraded by 21 unavailable auxiliary artifacts
and one unresolved CDA reference. No alternate artifact revision is silently
substituted.

## Relation to the original six implementation points

| Initial point | Status | Current result |
|---|---|---|
| 1. General CDA/RIM expansion | Verified | One recursive model expands structural CDA/RIM classes and HL7 V3 datatypes. |
| 2. One machine-readable definition source | Implemented | `fetch` caches the pinned official CDA R2 XSD set under `spec/<release>/cda-core/`; datatype structure is no longer a separate handwritten catalogue. |
| 3. Procedural resolution | Implemented | The compiler indexes definitions, resolves aliases/inheritance, enumerates children/attributes, and classifies structural versus value definitions. |
| 4. Recursive ART-DECOR overlay | Implemented | `include`, `contains`, and `SPEC` are resolved; generic structural/datatype descendants are materialized and explicit constraints overlay them. |
| 5. Writable targets after expansion | Implemented | Mapping uses compiled value representations; structural nodes stay navigation/repeat anchors; the renderer consumes compiled representations and roles. |
| 6. Provenance | Implemented | Effective nodes retain template, CDA/RIM, datatype, combined, and strong inferred-evidence provenance. |

The original representative structural gates are present:

- postcode reaches `recordTarget/patientRole/addr/postalCode` and is selected;
- medication reaches `substanceAdministration/doseQuantity/low` through
  `IVL_PQ`;
- wildcard diagnostics exposes 116 descendants below `observation`;
- wildcard therapy exposes 115 descendants below `procedure`.

## Coverage recovery

The proposal gains these seven fields over the accepted PR #9 mapping:

1. medical transport accompaniment;
2. referral to the emergency department;
3. discharge type;
4. transfer type;
5. triage system used;
6. accident vehicle;
7. patient postal code.

The accepted medication `for_each` rule remains because it expresses source
occurrence ownership, not CDA datatype structure.

## Laterality and repeat-by-discriminator

Pupil `fan_out` has been generalized to `repeat_by_discriminator`. The rule is
derived from repeat depth, the required `targetSiteCode`, its exact bound
ValueSet, and Schematron uniqueness assertions. The generated constants are:

| Source facet | Code | ValueSet | Code system | Evidence |
|---|---|---|---|---|
| rechts | `R` | `1.2.276.0.76.11.48@2015-11-17T00:00:00` | `1.2.276.0.76.3.1.195.5.48` | STRONG |
| links | `L` | `1.2.276.0.76.11.48@2015-11-17T00:00:00` | `1.2.276.0.76.3.1.195.5.48` | STRONG |

No SNOMED eye constants are emitted. Legacy `fan_out` remains readable, but
automatic migration occurs only when the current specification proves the same
source branches and physical target.

## Production hardening completed

The fresh production fixture exposed required CDA content that unit-sized
templates did not. These generic, compiled behaviours are now present and have
focused regression tests:

- optional fixed attributes are conditional constraints, including tetanus
  `@nullFlavor="NI"`;
- document/author generation time and custodian organization are compiled
  system-value roles;
- required complex values use `nullFlavor` only when their compiled structure
  permits it;
- active section titles and narratives are completed from compiled content
  roles and explicit descendant assignments;
- a single ART-DECOR vocabulary code without a redundant code-system OID is
  retained and serialized;
- CDA XSD defaults complete explicit ART-DECOR attributes that omit a value,
  such as `entry/@typeCode="COMP"`;
- required unfixed `II` values receive stable per-occurrence generated
  identifiers without activating unused optional branches;
- renderer errors include the exact template identity and local CDA path.

## Production closure

The fresh fixture exposed four generic representation gaps after structural
expansion. They are now compiled or handled without concept-specific renderer
branches:

1. A required coded node may use a neutral template example only when the
   candidate is scoped to the exact template revision and CDA path and resolves
   uniquely in the exact bound ValueSet revision or explicit allowed-code set.
   The fallback is recorded as STRONG `template-example` provenance and an
   explicit mapping still wins.
2. A coded datatype's expanded text companion receives the source wording via
   a compiled `coded_original_text` role. This satisfies templates that require
   traceable `originalText` while the renderer remains datatype-independent.
3. Required representation-owned attributes, such as PQ `@value`, are checked
   after the compiled value representation writes them.
4. Synthetic repeated integer values vary by occurrence within their declared
   bounds, so sequence/order test data does not invent duplicate leading
   occurrences. ART-DECOR path predicates remain selectors and are stripped
   from serialized XML QNames.

After these changes the accepted 62-field mapping passes `check-cda-mapping`
and produces one assertion-valid document. The 69-field proposal produces one
valid discharge document with no transfer branch and one valid transfer
document with no discharge disposition. Together those scenarios exercise all
69 proposed fields.

Generated artifacts and XML were inspected for:

- postcode element text below `recordTarget/patientRole/addr/postalCode`;
- pupil observations discriminated by AKTIN `R`/`L` codes from code system
  `1.2.276.0.76.3.1.195.5.48`, with no SNOMED laterality constants;
- preservation of medication `for_each` in the generated mapping and focused
  occurrence regression; diagnosis and vital-sign repetitions were additionally
  exercised in the production XML fixture;
- mutually exclusive discharge/transfer structures;
- absence of XPath predicates in emitted XML element names.

## Final gates

- clean fresh-snapshot build: 120 fields, 57 groups, 308 templates, 26,170
  physical targets, 69/120 proposed mappings and 71 logical datapoints;
- accepted mapping: all 62 prior selections retained, seven proposal gains,
  zero regressions;
- 137 unit tests pass, including the import/circular-import regression;
- accepted and both proposal scenario fixtures render and satisfy assertions;
- generated XML parses successfully;
- bytecode compilation and whitespace/diff checks pass;
- static typing is run when `mypy` is available.

## Merge criterion

The functional publication criteria are met: the accepted mapping passes, both
proposal disposition scenarios validate, all 62 accepted fields remain, and
the seven gains are evidence-backed. The remaining publication operation is to
confirm the final remote diff/status and merge the reviewed pull request.
