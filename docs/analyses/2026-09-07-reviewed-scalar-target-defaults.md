# Reviewed scalar CDA construction defaults — 2026-09-07

## Blocking constraints

The accepted `2026.1.2` / `notaufnahmeregister--60` field mapping activated two
required non-null CDA values for which the dataset has no direct field. The
CEDIS Problem Concern Act requires `statusCode`; Medikation requires the root
`moodCode` attribute. Neither permits the general `nullFlavor` completion rule.
After DEC-026 removed example-derived defaults, whole-document construction
correctly stopped rather than inventing either value.

The inherited C-CDA Problem Concern Act defines its lifecycle semantics:
`active` means that the provider still tracks the concern, while `completed`
means it is no longer of concern; `effectiveTime/high` records that closure.
The AKTIN wrapper is the concern container for the complaint at presentation.
The reviewed transaction policy therefore uses `active` whenever that wrapper
is emitted. A future source closure state must override the default and supply
the corresponding high time rather than deriving completion from symptom
onset.

The Pharmacy medication statement defines `EVN` for medication currently or
previously taken and `INT` for medication planned in the future. The current
transaction scope is medication given during treatment in the emergency
department, so `EVN` is the reviewed default. This is not inferred from the
neutral example or from the namespace URI.

## Future medication scope

Medication history and recommendations may be added later. Their addition
requires one explicit field on every medication occurrence with three source
categories:

- medication given during ED treatment → `EVN`;
- medication taken at home / medication history → `EVN`;
- recommendation for future medication → `INT`.

The three source categories intentionally collapse to the two moods defined by
the selected medication-statement profile. Start and stop timestamps cannot
replace this field: the present descriptions include both retrospective and
prospective wording, and time comparison would not establish whether a
statement records an event or an intent.

## Executable completion rule

`target_defaults` now accepts exactly one of `nullFlavor` or `value`. A scalar
value requires a non-empty reason and one exact writable required target. It is
validated against the compiled scalar representation and any finite compiled
code constraint. Identifier and compound-dependent targets remain unsupported.

Defaults never activate optional CDA branches. Inside a branch activated by
real mapped data, a scalar default is broadcast to every active occurrence; a
mapped value overrides it for its own occurrence. This behavior lets the
future three-way medication field replace the current `EVN` policy without a
medication-specific renderer condition.

## Verification

Regression coverage exercises a coded mandatory element, a mandatory
attribute, repeated occurrences, per-occurrence source override, an unused
optional branch, invalid scalar types, finite code constraints, required review
reasons, and compound dependency rejection. The reference mapping records the
two reviewed defaults. The whole-document synthetic run proceeds past both and
then fails closed at the unrelated mandatory Allergy Concern
`effectiveTime/low`, for which the transaction has no first-documented source
timestamp.
