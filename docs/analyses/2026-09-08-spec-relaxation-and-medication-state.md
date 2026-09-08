# Non-monotonic SPEC constraints and medication state — 2026-09-08

## Constraint finding

ART-DECOR documents `SPEC` as a specialization whose constraints should be
narrower than those of its parent. Its conformance rules also make mandatory a
stronger form of required: mandatory implies a lower bound of at least one and
does not permit null values.

The published AKTIN Medikation template
`1.2.276.0.76.3.1.195.10.67@2023-12-03T00:00:00` is non-monotonic. It declares
the UV Medication Statement
`2.16.840.1.113883.10.21.4.7@2023-01-30T08:32:34` as a `SPEC` parent, but changes
`substanceAdministration/statusCode` from the parent's `1..1 R M` to `0..1 R`.
The generated child Schematron enforces at most one status and validates its
code when present; it does not require the element. The generated AKTIN mapping
guide also publishes `0..1 R`. The CDA R2 base model independently permits the
element to be absent.

This is not isolated to medication. Compiling the complete selected local
template set finds three explicit weakenings: represented custodian
organization, procedure identifier and medication status. Treating inherited
mandatory flags as authoritative therefore contradicts the executable child
design in several places.

## Implemented compilation policy

DEC-031 makes explicit child constraints authoritative while preserving
inheritance for properties the child omits. An explicit child minimum of zero
clears inherited mandatory unless the child explicitly declares mandatory.
Minimum, maximum and mandatory broadening are reported as
`spec-constraint-weakening` diagnostics in the compiled model and build report.
They do not degrade an otherwise complete build.
`build --strict-specializations` is available when non-monotonic `SPEC` input
must be rejected instead.

Consequently Medikation `statusCode` is optional and omitted when the dataset
does not supply a medication lifecycle state. No clinical value is guessed and
no reviewed scalar default is added.

## Medication mood and lifecycle

The selected AKTIN Medikation root permits `EVN` and `INT`. Its source text
defines `EVN` for current or past taking/administration and `INT` for future
plans. The present transaction describes measures performed on the patient in
the emergency department, which supports the existing reviewed `EVN` default
for the current scope.

ActStatus is a separate lifecycle axis. `active` means the act can be or is
being performed. `completed` means normal completion. `cancelled` is
abandonment before activation, while `aborted` is termination after activation
but before intended completion. None can be selected merely from `EVN`, `INT`
or the presence of a medication row.

## Future source markers

A future “discharge recommendation” marker may select `moodCode="INT"` when it
means a future medication plan. It may also select `statusCode="active"` only
if the source contract explicitly means that recommendation remains operative;
otherwise status should remain absent or come from a separate lifecycle field.

A future “ordered in the ED but not administered” marker must not set the
current Medikation root to `RQO`/`aborted`. That root excludes `RQO`. The
available UV Medication Order Reference fixes its own `moodCode` to `RQO`, so a
reviewed construction could represent the order separately. Non-administration
is a different assertion: CDA's `negationInd=true` records that the
administration did not occur without changing its mood. Whether the order is
active, cancelled, aborted or completed requires independent order-lifecycle
evidence. The exact combination, relationship and reason representation must
be reviewed against the future dataset contract before implementation.

## Sources and verification

- [ART-DECOR template relationships](https://docs.art-decor.org/documentation/template/)
- [ART-DECOR mandatory and conformance rules](https://wiki.art-decor.org/index.php?title=DECOR-rules#Mandatory_/_Conformance)
- [HL7 CDA SubstanceAdministration](https://build.fhir.org/ig/HL7/CDA-core-sd/StructureDefinition-SubstanceAdministration.html)
- [HL7 ActMood value set](https://terminology.hl7.org/4.0.0/ValueSet-v3-ActMood.html)
- [HL7 ActStatus code system](https://terminology.hl7.org/7.1.0/en/CodeSystem-v3-ActStatus.html)

Regression coverage verifies effective `0..1` cardinality, omission during
rendering, warning retention, strict rejection and build-report output. The
same policy was checked against the exact local AKTIN/UV template pair. All 246
unit tests pass. An isolated build of the complete reference workspace reports
three weakenings and compiles Medikation `statusCode` as optional. Its synthetic
mapping fixture no longer reports medication status; it advances to the
independent mandatory `hl7:act/hl7:statusCode` in template
`1.2.276.0.76.10.4048`, for which no value is currently mapped or defaulted.
