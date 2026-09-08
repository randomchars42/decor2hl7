# Final-diagnosis defaults and assertion namespaces — 2026-09-08

## Constraint and meaning

AKTIN template `1.2.276.0.76.10.4048@2016-06-22T00:00:00` is the aggregate
Problem Concern Act for Abschlussdiagnosen. One act contains the repeated final
diagnosis observations. It requires a non-null `statusCode` from ActStatus and
an `effectiveTime/low`; the selected transaction has no source field for
either concern-lifecycle fact.

The template adapts the C-CDA Problem Concern Act. In that model `active` means
the provider continues to regard the condition as a concern, including when
the underlying condition is resolved. `completed` means it no longer requires
tracking and is paired with the end of the Concern Act's effective time. The
fact that a diagnosis is an Abschlussdiagnose establishes its encounter-final
classification, not that clinical concern has ended.

## Reviewed completion policy

The accepted reference mapping adds three exact target defaults:

- `Problemconcernacteddiagnoses.act.statusCode@20160622` receives `active`.
  Diagnoses included in the handoff remain clinically relevant; a future
  concern-closure datum may override this and must also supply a matching high
  time when it selects `completed`.
- `Problemconcernacteddiagnoses.act.effectiveTime.low@20160622` receives
  `nullFlavor="UNK"`. A concern-start time is applicable, but its value is not
  known from the transaction. `UNK` states that distinction more precisely than
  the generic `NI` fallback.
- `Problemobservationeddiagnosis.observation.code@20170213` receives LOINC
  `29308-4`. The Problem Observation template permits both `29308-4` and
  `75324-4`, but explicitly directs producers to replace `75324-4` with
  `29308-4`. This is the observation-kind code; the actual diagnosis remains
  mapped to `observation/value`.

Defaults do not activate optional target branches. These values are emitted
only when mapped final-diagnosis data activates the aggregate act, and a real
source assignment overrides the default. Because the profile has one aggregate
Concern Act, a future status supplied separately for each diagnosis would
require structural review rather than occurrence-wise assignment to this act.

A reviewed scalar coded default remains a JSON string in the portable mapping.
When it selects one unique member of the compiled finite code constraint, the
runtime supplies that member's `codeSystem` and display metadata. A duplicated
lexical code with different compiled companions is rejected rather than
choosing a code system by position.

## Assertion namespace correction

After the diagnosis defaults, the fixture reached the UV Ingredient assertion
`pharmhl7:code or pharmhl7:name`. The rendered XML already contained both
children. The failure came from the in-process XPath subset treating only
`hl7:*` as expanded XML names; `pharmhl7:*` remained a literal unnamespaced
name. Generated `cda-assertions.sch` likewise declared only `hl7`.

Compilation now retains each source template's in-scope prefix map with its
assertions. Runtime evaluation resolves element and attribute QNames through
that map, while the known-prefix table supports already compiled local models.
Schematron generation declares every prefix used by a context, test, or let and
rejects unknown or conflicting bindings.

## Verification and fixture split

`check-cda-mapping` accepts the reference mapping with six reviewed target
defaults. An isolated build of the exact local reference workspace compiles 311
reachable templates and retains the three documented SPEC-weakening warnings.
Both a discharge-only and a transfer-only synthetic scenario render one CDA
document and pass all in-process ART-DECOR assertions. All 250 unit tests pass;
static checking adds no errors beyond the three existing findings in
`cooccurrence.py` and `cda/extensions.py`.

The reference fixture now stores the mutually exclusive outcomes separately:
`TEST-1` supplies discharge type and leaves transfer empty; `TEST-2` supplies
transfer type and leaves discharge empty. `test-cda-mapping` therefore emits
and validates two documents while retaining coverage of both mappings. A real
record that supplies both still fails the AKTIN assertion; production rendering
does not discard either source value to manufacture validity.

## Sources

- [HL7 C-CDA Problem Concern Act](https://build.fhir.org/ig/HL7/CDA-ccda-2.1-sd/StructureDefinition-ProblemConcernAct.html)
- [HL7 V3 NullFlavor](https://terminology.hl7.org/en/CodeSystem-v3-NullFlavor.html)
