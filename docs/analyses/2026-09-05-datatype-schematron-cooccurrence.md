# Datatype Schematron co-occurrence compilation — 2026-09-05

## Question

Can generated datatype Schematron formally narrow writable CDA mapping
candidates, in particular the representation of
`notfallanamnese.beschwerden_bei_vorstellung.ereigniseintritt`, without adding
reviewed datatype rules or weakening other mapping evidence?

## Concrete evidence

The selected 2026.1.2 reference model compiles
`Problemobservationcedis.effectiveTime` as `IVL_TS`. Writing the target uses the
element's `@value` timestamp representation. Template
`1.2.276.0.76.10.4040` requires its direct `width` child. The generated
`DTr1_IVL_TS.sch` contains error assertions:

- `not(@value and hl7:*)`; and
- `not(@value and (hl7:low|hl7:center|hl7:high|hl7:width))`.

Consequently every ordinary parent timestamp assignment produces `@value`
while the active template necessarily emits `width`, and violates both rules.
The inherited datatype target
`Problemobservationcedis.observation.effectiveTime.low` writes `low/@value`
instead. Required `width` plus `low` violates neither assertion. When no width
value is mapped, the existing required-value completion emits
`<width nullFlavor="NI"/>`, which is legal for this co-occurrence shape.

This establishes structural admissibility, not the clinical correspondence of
Ereigniseintritt to the lower boundary.

## Implemented boundary

The compiler uses only generated `DTr1_*.sch` files from the successful current
build. A standard-library parser accepts only error-level `not(...)`
expressions formed from conjunctions of direct `@attribute`, `hl7:child`, or
`hl7:*` presence selectors. Parenthesized unions are expanded to at most 32
clauses. N-ary conjunctions remain n-ary. Abstract `<extends>` inheritance is
resolved with missing-parent and cycle diagnostics.

All other expressions—including descendant axes, predicates, comparisons,
functions, variables, and `except`—remain unsupported and are counted in the
compiled evidence summary. They are neither executed nor approximated.

The hard admissibility proof combines one candidate assignment with only facts
that the compiled document must add at the same datatype owner: fixed
attributes and required direct children. It does not assume that optional
siblings, different dataset fields, or repeated occurrences co-occur. The same
proof is applied in possible-target reporting, configuration validation, and
the renderer. Complete generated Schematron validation remains responsible for
arbitrary document-level combinations.

When a parent representation already conflicts with required/fixed structure,
direct scalar datatype descendants named explicitly beside that representation
by a compiled co-occurrence clause are included in the unproven possible-target
inventory. Wildcard-only participation does not expose the whole generic
expansion. A reviewer may select such a physical target even
when it was not emitted as a generated logical mapping datapoint; all ordinary
physical target, type, occurrence, claim, and conformance checks still apply.

## Dependency and efficacy impact

No third-party dependency was added. Parsing and proof use Python's standard
library and the already compiled CDA document/target model. The registry is
stored once in `cda.json` rather than copied to every target.

The restriction cannot remove a target merely because a complex rule resembles
a co-occurrence rule: unsupported syntax is ignored and counted. It also cannot
remove a target based on speculative optional-field combinations. In the
reference accepted mapping, no selected mapping writes a scalar parent
`IVL_TS/@value`, so the CEDIS correction is expected to change candidate
quality without reducing accepted coverage.

## Verification

The complete 230-test suite passes. A clean build from the local reference
`spec/` attaches 49 inherited datatype rule sets compiled from 123 files: 42 of
408 error assertions match the narrow grammar and expand to 211 inherited
clauses; the remaining 366 are explicitly reported as unsupported. There are
no unresolved `<extends>` references or inheritance cycles.

The accepted reference mapping remains 95/120 dataset fields and none of its 93
distinct selected physical targets has an unavoidable co-occurrence conflict.
The bounded document candidate pool changes from 848 to 873. For
Ereigniseintritt, the rebuilt report lists eight type-compatible descendants:
the parent `Problemobservationcedis.effectiveTime` is unavailable with both
source assertions, while
`Problemobservationcedis.observation.effectiveTime.low` is available and has no
datatype conflict. The existing independent report-only conformance findings
remain unchanged by this mapping mechanism.
