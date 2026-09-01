# Specification-derived writable-target recovery

Date: 2026-09-01

## Scope

This analysis compares canonical `main` after PR #18 with the same fresh
`decor2hl7-test-workspace` `spec/2026.1.2` snapshot after the generic recovery
rules in this change. It asks which structural-only fields can become executable
from ART-DECOR, CDA/RIM, datatype, cardinality and terminology evidence without
adding clinical path tables to mapping or rendering.

## Reproducible comparison

Both compilers used the same selected transaction and cached specification:

| Measure | Canonical baseline | Recovered |
|---|---:|---:|
| Dataset fields | 120 | 120 |
| Dataset groups | 57 | 57 |
| Reachable templates | 308 | 308 |
| Physical named CDA targets | 24,743 | 24,940 |
| Proposed mapped fields | 74 | 91 |
| Proposal losses | — | 0 |
| Unavailable artifacts | 21 | 21 |
| Unresolved CDA references | 1 | 1 |

The 197 additional physical names are typed alternatives for abstract values and
newly visible choice/datatype descendants, not hand-written template fields.

## Generic mechanisms and recovered fields

| Mechanism | Representative recoveries |
|---|---|
| Predicate-insensitive CDA/XSD particle overlay | medication `sequenceNumber`; datatype/provenance on all selected choice variants |
| Transparent ART-DECOR choice plus datatype selection | wildcard diagnostic/therapy instant and interval width; medication event offset |
| Typed `ANY` alternatives | wildcard diagnostic value as `ST` with `xsi:type="ST"` |
| Unique explicit role/description below mapped context | payer organization name; wildcard codes; external-document URL references |
| Compiled section narrative role | allergy description; disposition/procedure text |
| `for_each` occurrence boundary | vital-sign organizer timestamp |
| Exact terminology plus fixed-statement presence | direct physician contact observation |
| Boolean act semantics | spine-radiography performed plus correction of ten existing requested/performed mappings to inverse `negationInd` |

The proposal gains 17 fields and loses none. The chief-complaint free-text target
also becomes more precise: formal template context selects the CEDIS problem
observation `originalText` instead of the section text.

## Corrected semantics, not just coverage

Canonical output directly assigned boolean “performed/requested” values to
`@negationInd`. CDA negation has the opposite polarity. The generated rules now
use `transform: {"type": "not"}` for the eleven supported boolean act fields.

Direct physician contact is different. Its optional observation has fixed
`code=FLN-13` and fixed SNOMED value `305660003`, and the source carries an exact
FLN-13 terminology association. The template exposes no `negationInd` because
the statement's occurrence itself represents true. `mode: "presence"` therefore
emits the fixed observation for true and omits it for false.

Wildcard time is likewise representation-sensitive. A point selects the atomic
TS choice. A duration selects the `IVL_TS/width` datatype descendant. The
predicate remains constraint identity and never enters the serialized QName.

## Deliberately unresolved

- Antibiotic- and contrast-agent-allergy flags are disorder assertions, not
  allergen codes. The current specification does not uniquely prove their
  required allergy occurrence/negation form.
- Medication form, ingredient, strength and lot data lack an active-profile
  bridge. Detailed start/stop, dose/rate, PRN, body-site and reason fields reach
  plausible UV subordinate-administration structure, but the specification does
  not uniquely select among its timing and quantity alternatives.
- Secondary ICD-10 remains open under DEC-009; `CD.translation` would express a
  translation, not a second diagnosis occurrence.
- Insurance relationship identifier is not mapped to the insurer organization's
  identifier merely because both descriptions contain “Identifikation”.
- Symptom onset, MRI/X-ray region, export interval and EDIS name/version have no
  unique executable target in the selected closure.

These omissions are the correctness boundary. They should be revisited when a
ConceptMap, static association, active template constraint or explicit reviewed
occurrence rule supplies the missing semantics.

## Verification

- Generated proposal validation against the fresh compiled model: zero errors.
- Unit suite covers choice overlay, URL representation, typed `ANY`, occurrence
  scope, inverse negation, fixed-statement presence/omission and a system value
  attached to one physical occurrence of a reused include.
- Canonical `main` stops the standard fresh-snapshot fixture at the mandatory
  custodian because the shared Organization Elements target has four physical
  locations. The recovered renderer now uses the compiler-assigned role at the
  exact physical custodian occurrence and passes that gate without making the
  shared target writable.
- The fixture then reaches the pre-existing allergy occurrence-completion gap:
  `Agens` activates Allergy Concern Act `1.2.276.0.76.10.4065`, whose mandatory
  `effectiveTime/low` has no source datapoint and does not permit null flavor.
  No date is fabricated. Field-level proposal validation remains clean; this
  missing clinical timestamp stays an explicit priority boundary.
