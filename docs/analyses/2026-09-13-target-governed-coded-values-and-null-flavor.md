# Target-governed coded values and null flavor

Date: 2026-09-13
Branch: `verify/contains-revision-boundary`
Reference: local refreshed `test-workplace`, release `2026.1.2`, transaction
`notaufnahmeregister--60`

## Question and evidence boundary

This analysis rechecks why arbitrary source wording had been serialized as
`nullFlavor="OTH"` and implements the owner-defined boundaries using only the
fetched transaction, value sets, templates, pinned CDA XSD graph, generated
model/audit, reviewed mapping, and authored reference scenarios.

The controlling evidence is:

- dataset concept-list identities and their exact `terminologyAssociation`
  endpoints in the selected transaction;
- exact target `vocabulary` identity, revision, and binding strength;
- the target ValueSet's compiled members and exception members;
- the CDA datatype's attributes and restriction hierarchy in the pinned XSD;
- a reviewed mapping transform when source and target representations differ.

Labels, relationship proximity, examples, a shared but unresolved ValueSet OID,
and a datatype-compatible physical slot do not establish code membership.

## Implemented rule order

1. Compile every non-abstract owner concept-list option and retain every exact
   concept-id-to-code association. A singular convenience alias is emitted only
   when there is one globally unambiguous formal member.
2. Normalize a complete finite or unresolved source domain strictly: unknown
   input is an error. Preserve exact logical options and explicitly open input
   as target-neutral canonical/raw wording; code normalization never creates a
   CDA null flavor.
3. Let an exact required target ValueSet disambiguate multiple exact source
   associations. The generated enum contains the formal code and code system;
   lexical resemblance is not used.
4. Generate `coded_fallback` only for an explicitly open source domain and one
   exact target ValueSet revision that admits `OTH` or `UNC` and exposes
   `originalText`. Runtime revalidates that complete contract.
5. Enforce required binding membership centrally for mappings, site values,
   defaults, and rendered values. A scalar configured code receives a code
   system only when compiled membership proves exactly one identity.
6. Serialize only attributes permitted by the concrete CDA datatype. XSD
   extension inherits base particles; XSD restriction replaces restricted
   content and removes `use="prohibited"` attributes. In particular, `CS`
   binding membership is checked with its code-system identity without writing
   forbidden `@codeSystem`.
7. Keep a shared but unresolved source/target ValueSet identity as review
   evidence only. It cannot select an executable direct mapping or manufacture
   an empty enum transform.

## `Typ Verlegung`

The source and `Referralto.act.code` both name ValueSet
`1.2.276.0.76.11.53@2015-11-17T00:00:00`, but its fetched definition contains
an unresolved whole-CodeSystem include for
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`. The requested code system is
not present in the fetched artifacts. The source also has alternatives whose
exact associations use SNOMED CT or HL7 NullFlavor rather than that required
target code system. Therefore neither a complete direct mapping nor a complete
enum transform is established.

The prior proposal's `enum` with an empty map was a compiler defect. The target
remains non-executable proposal evidence behind the terminology closure gap.
DEC-042 subsequently adds a portable `reviewed_coded_map`: it covers all six
exact source concept identities and only the exact
`Referralto.act.code`/`1.2.276.0.76.11.53@2015-11-17` contract. Codes 1, 3, and
5 follow exact source-option associations; code 7 is explicitly labelled a
reviewed cross-revision assumption; external transfer and `Sonstiges` use OTH
with their wording in `originalText`. This does not resolve the missing
CodeSystem or change the generated proposal. Reopening still needs the exact
code-system revision or a complete expansion/crosswalk published by the owner.

The ten previously reviewed relationship-era field migrations remain selected.
The triage result is the only other reviewed mapping serialization change: its
five owner concept-list members now use the exact target LOINC answer codes
selected by the required target ValueSet.

## Remaining `OTH` values

The six authored documents now contain six `OTH` values instead of 64:

- five presenting-complaint text values populate the compiled
  `coded_original_text` leaf of a required CE whose exact ValueSet admits OTH;
- one allergy-agent value (`Penicillin`) uses the reviewed target-scoped
  `coded_fallback` and retains the wording in `originalText`.

No input normalization path and no arbitrary finite-domain miss produces OTH.

## Authoritative comparison

| Measure | Captured before | Implemented branch |
|---|---:|---:|
| Dataset fields / groups | 120 / 57 | 120 / 57 |
| Reachable CDA templates | 119 | 119 |
| Physical named targets | 31,295 | 22,650 |
| Logical CDA datapoints | 88 | 87 |
| Automatic mapped datapoints | 85 | 84 |
| Reviewed mapped fields | 95 | 95 after DEC-042 |
| `OTH` values in six authored CDAs | 64 | 6 |
| Validator generation messages | 88 | 0 |
| Validator executable / complete | true / false | true / true |
| CDA/SDTC XSD diagnostics | 0 | 0 |
| Template Schematron diagnostics | 13 | 0 |

`test-cda-mapping` passes all six authored scenarios. Independent instance
validation now also passes as a whole: exact validator assembly contains only
the 119 selected effective-dated revisions, reports no generation messages, and
the CDA/SDTC XSD plus generated template Schematron produce zero diagnostics.
The separate unresolved Referral actions terminology closure remains a
proposal and build gap; generated structural requiredness cannot turn it into
an executable candidate. DEC-042 supplies a visibly reviewed finite mapping,
not inferred terminology.

Evidence: `src/decor2hl7/compile/transaction.py`,
`src/decor2hl7/compile/mapping.py`, `src/decor2hl7/data.py`,
`src/decor2hl7/cda/core.py`, `src/decor2hl7/cda/compile.py`,
`src/decor2hl7/cda/terminology.py`, `src/decor2hl7/cda/render.py`,
`src/decor2hl7/validate.py`, the selected local workspace, and regression tests.
