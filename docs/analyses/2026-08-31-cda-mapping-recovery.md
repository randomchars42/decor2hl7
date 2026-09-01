# CDA mapping recovery and discriminator analysis — 2026-08-31

## Evidence snapshot

The integration run used `spec/` produced by the latest `fetch` and committed to
`randomchars42/decor2hl7-test-workspace` at
`d9c603bc634ca9fec756c4ecbfed1c432518b12a`. The selected release is
`2026.1.2`; the transaction is `notaufnahmeregister--60`.

The build remains visibly degraded by 21 unavailable auxiliary artifacts and
one unresolved CDA reference. No alternate revision was substituted. These
known omissions did not prevent compilation or the mapping gates below.

## Coverage comparison

The PR #9 accepted `cda-mapping.json` contains 62 non-null source-field
mappings. Its displayed `64/120` result counted logical CDA targets: two
multi-target transformations add one logical target each. The current proposal
contains 69 non-null fields and 71 logical targets. Field-by-field comparison
retained all 62 accepted mappings and lost none.

Seven source fields were added:

- medical transport accompaniment;
- referral to the emergency department;
- discharge type;
- transfer type;
- triage system used;
- accident vehicle;
- patient postal code.

The accepted mapping remained authoritative. A temporary review bundle carrying
that exact mapping plus a lock for the new compiled model passed
`check-cda-mapping`.

## Model-expansion gates

- Seven real fixed-unit `PQ` targets remain writable: core temperature, GCS eye,
  verbal, motor and total, Modified Rankin, and numeric pain. Their scalar is
  written to `@value` while the fixed `Cel` or `{score}` unit is preserved.
- `patient.anschrift.postleitzahl` maps to
  `recordTarget/patientRole/addr/postalCode`. The audit chain is formal parent
  context plus the linked “Postal code three digits” label and a datatype-derived
  CDA descendant; no postal-code XPath is hard-coded.
- The real medication branch reaches
  `substanceAdministration/doseQuantity : IVL_PQ` and the datatype-derived
  writable `low : IVXB_PQ` representation.
- `WildcardDiagnostik.observation` exposes 116 compiled descendant targets;
  `WildcardTherapie.procedure` exposes 115. Their still-unmapped fields remain
  review items because structural availability alone does not identify one
  semantically correct writable descendant.
- The full compiled model contains 26,170 physical named targets. XSD-derived
  descendants are present below `substanceAdministration`, `observation`, and
  `procedure` without per-class mapping or renderer rules.

The source verifier also exposed a valid publisher pattern: one expanded
document template reused the same ART-DECOR element ids in two participant
branches with different fixed template roots. Physical source identity now
includes the effective date and template-local path, so the two constraints remain distinct;
element-id-only lookup is retained only as tolerant mapping evidence.

## CDA pupil laterality

AKTIN Pupilsize (`1.2.276.0.76.10.4046`) and Pupilreaction
(`1.2.276.0.76.10.4047`) may each occur `0..2`. Each occurrence requires one
`value` and one `targetSiteCode`. `targetSiteCode` is bound to ValueSet
`1.2.276.0.76.11.48@2015-11-17T00:00:00`, whose relevant members are:

| Code | Display | Code system |
|---|---|---|
| `R` | Auge rechts | `1.2.276.0.76.3.1.195.5.48` |
| `L` | Auge links | `1.2.276.0.76.3.1.195.5.48` |

Schematron permits at most one occurrence with `R` and at most one with `L`.
The generated rule therefore creates one repeat per present source-side value,
keyed by the corresponding required discriminator. It no longer writes SNOMED
eye concepts.

No explicit ConceptMap between the source concepts and `R`/`L` was found. The
German source facets `rechts`/`links` uniquely match the German target
designations `Auge rechts`/`Auge links`, the target structure is compatible,
and the exact ValueSet binding is present. This is recorded as STRONG evidence.
An explicit ConceptMap or terminology association would be EXACT; lexical
similarity without a unique same-language terminology match remains WEAK and is
not sufficient for automatic generation.

`repeat_by_discriminator` is generic: it requires one additional repeat level,
a required coded discriminator, an exact selected ValueSet revision, unique
source/member matches and compatible occurrence structure. Runtime validation
rejects any discriminator constant outside that selected ValueSet. Legacy
`fan_out` remains readable, but automatic migration occurs only when the newly
generated evidence proves the same sources and physical CDA target.
document template reused the same ART-DECOR element ids in two participant
