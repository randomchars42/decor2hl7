# Medication detail branch and `urn:hl7-org:pharm`

Date: 2026-09-06

## Question

Can the remaining medication mappings be improved by following
`urn:hl7-org:pharm`, and can medication start/stop be represented as
`effectiveTime/low` and `effectiveTime/high`?

## Exact profile evidence

The selected AKTIN Medikation template
`1.2.276.0.76.3.1.195.10.67@2023-12-03` specializes UV Medication Statement
`2.16.840.1.113883.10.21.4.7@2023-01-30T08:32:34`. At host element
`2.16.840.1.113883.3.1937.777.15.9.19`, the specialization explicitly selects
UV Medication Information (simple)
`2.16.840.1.113883.10.21.4.10@2021-09-29T19:15:16`. The exact `SPEC` parent
declares that branch and UV Medication Information (detail)
`2.16.840.1.113883.10.21.4.11@2023-02-03T13:03:38` as sibling choices under
the same `hl7:consumable` occurrence.

The detail branch declares `pharmhl7="urn:hl7-org:pharm"` and exposes, among
other optional content:

- manufactured-material `hl7:code` and `hl7:name`;
- `pharmhl7:formCode` for pharmaceutical dose form;
- `hl7:lotNumberText` for the product lot;
- repeatable `pharmhl7:ingredient`, whose class code uses exact ValueSet
  `2.16.840.1.113883.1.11.10430@2014-03-26`;
- `pharmhl7:ingredientSubstance/pharmhl7:code` and `pharmhl7:name`;
- ingredient `pharmhl7:quantity` as `RTO_PQ_PQ`.

The ingredient-role ValueSet explicitly contains `ACTI` “active ingredient”
and `IACT` “inactive ingredient”. This gives an exact Boolean crosswalk for the
source field “Arzneilich wirksamer Bestandteil?”; it is stronger evidence than
an English/German name resemblance.

The Pharmacy URI is a namespace identity, not a template relationship. It
allows correct XML QName construction after the detail branch has been selected
by exact profile evidence; following the URI alone would not authorize adding
the detail template or choosing an ingredient occurrence. The IHE Pharmacy
material inspected earlier uses a distinct `urn:ihe:pharm` namespace and does
not establish identity with this Universal Pharmacy branch.

## Implemented structural policy

DEC-028 adds the exact `select_spec_branch` profile-overlay operation. It
replaces the already selected simple branch only when the exact inherited
sibling choice can be proved. The reference configuration records that reviewed
selection and exact identities. Fetch closes the exact detail dependency;
compile freezes the chosen branch and retains its namespace bindings.

The contained UV Ingredient template occurs at four physical positions in the
detail branch: three beneath optional recursive packaging paths and once as the
direct product ingredient. Its template-local code/name targets are therefore
correctly ambiguous. The compiler now creates occurrence-qualified
`anchor::target` aliases only where a distinct containing-template target proves
each location. The reviewed mapping can address the direct ingredient without
making the shared UV Ingredient target write to all four positions.

The CDA R2/SDTC schema graph does not declare the Pharmacy namespace. The
validation gate now rejects any foreign node outside exact compiled profile
paths, runs base CDA XSD over a projection excluding only approved Pharmacy
elements and attributes, and runs the generated exact Schematron over the
unchanged document. This is a bounded structural and policy bridge, not a claim
that a
missing Pharmacy XSD was executed.

## Mapping consequences

The selected detail branch preserves the established product-name and
product-code semantics and newly supports reviewed mappings for pharmaceutical
form, lot number, direct ingredient name/code and active/inactive ingredient
role. Unbound source codes retain the project's existing target-governed
`nullFlavor="OTH"` plus original wording behavior rather than acquiring an
invented code system.

Ingredient strength remains unresolved. The source supplies one unconstrained
text value, while the profile requires a structured `RTO_PQ_PQ` numerator and
denominator. No grammar, unit policy or denominator semantics is published, so
splitting that string would invent data.

## Timing conclusion

The outer Medikation `effectiveTime` is explicitly `NP` and cannot carry
start/stop. UV Subordinate Administration exposes several mutually exclusive
timing meanings: scalar `TS`, periodic `PIVL_TS`, event-related `EIVL_TS` with
its required event companion, and `SXPR_TS` components. Their datatype
expansions can contain low/high leaves in particular interval branches, but the
source start and stop fields have no exact association selecting one branch or
defining whether they describe administration bounds, schedule bounds, or
individual administrations. Consequently no `effectiveTime.low` or `.high`
mapping is activated. Reopening requires an explicit profile association or a
reviewed timing rule that fixes branch selection, occurrence behavior and all
mandatory companions.

## Verification boundary

Regression coverage checks exact sibling selection, namespace-aware rendering,
occurrence-qualified targets, offline reuse of an exact frozen dependency, and
the foreign-namespace validation projection. The reference workspace is then
rebuilt and exercised through mapping validation and occurrence-shaped
assignment materialization. Whole-document synthetic generation still stops at
independent mandatory `statusCode`/`moodCode` values that have neither source
evidence nor reviewed defaults after DEC-026; the implementation does not
restore example-derived defaults to bypass that policy boundary.
