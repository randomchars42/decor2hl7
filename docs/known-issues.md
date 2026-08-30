# Known boundaries after the 0.1.0 correctness pass

The 0.1.0 rewrite now supports declarative semantic transforms, formal
ART-DECOR assertion enforcement, transitive identity-lineage enrichment and
explicitly keyed nested repetitions. The remaining items are boundaries where
external protocol information or broader ART-DECOR expression coverage is
needed; they are not silent runtime fallbacks.

## Transform vocabulary

`cda-mapping.json` version 5 accepts direct target names, small declarative
rules, and explicit structural bindings. The built-in scalar transform vocabulary is deliberately limited to `identity`,
`enum`, `ordinal`, and `not`. The generated proposal uses it for the currently
proven AKTIN semantics for Tetanusschutz, Isolation, modified Rankin, and
diagnosis certainty. Structural `for_each`, `fan_out`, and `coalesce` behavior is
implemented in the generic binding layer and is generated only from formal
repeat/discriminator evidence.

A future concept whose ART-DECOR representation needs a different structural or
computed transformation remains evidence-linked but non-executable until an
explicit transform is added. `ADAPT` remains usable mapping evidence but is not
automatic dataset identity inheritance.

## Diagnosis time and certainty

Decision record: `DEC-008` in [`decisions.md`](decisions.md).

The compiler no longer derives a diagnosis end from certainty `Z`. The
transaction web view contains no diagnosis timepoint, and `Zustand nach` is a
certainty/clinical-status qualifier rather than a timestamp. V/A/Z/G therefore
maps only to the formal certainty qualifier; `A` additionally controls exclusion
negation. `effectiveTime/high` remains absent unless a real source mapping or an
explicitly reviewed mapping rule supplies it.

The CDA template does require `effectiveTime/low` for each active diagnosis
occurrence. Because this transaction contains no diagnosis-onset datapoint, the
generated CDA mapping declares a target-specific `nullFlavor="UNK"` default for
that required leaf. This states that the onset value is unknown; it does not
invent a date. If a future transaction supplies a real onset and maps it to the
same target, that value wins for its occurrence.

More generally, an otherwise empty required nullable CDA leaf receives the
mapping-wide `nullFlavor="NI"` completion default. Optional unmapped leaves are
omitted, and mandatory/non-nullable targets remain validation errors.

## Secondary ICD-10 diagnoses (concept 29508)

Decision record: `DEC-009` in [`decisions.md`](decisions.md).

The current transaction represents `ICD-10 Sekundärdiagnose` as concept 29508
with cardinality `0..1`, while historical/project material has also exposed it
as `0..*`. It is therefore not yet safe to define a delimiter syntax or to
expand it into additional diagnosis occurrences.

The current CDA evidence provides no proven direct target distinct from the
primary ICD value. The compiler deliberately leaves concept 29508 unmapped; it
must not be written as `CD.translation`, because that would assert a translation
of the primary diagnosis rather than another diagnosis.

AKTIN clarification is needed on cardinality and intended CDA representation:
whether each secondary code becomes another Problem Observation, how it relates
to the leading diagnosis, and whether text/certainty are repeated with it. Until
that is resolved, no semicolon parser or inferred clinical relationship is
implemented.

## ART-DECOR assertion expression coverage

The built-in standard-library evaluator covers all error-level assertion shapes
used by the selected AKTIN 2026.1.2 CDA closure: boolean expressions, nested
selectors/predicates, attribute comparisons, `count()` comparisons and the one
MDRO sequence-uniqueness expression using `<let>`.

An unknown future **error-level** expression is intentionally a validation error,
not a warning. `build` also writes `cda-assertions.sch` containing the original
ART-DECOR tests and variables so a standards Schematron processor can apply the
authoritative expressions independently. Full CDA XSD and repository-provided
Schematron validation are still useful additional deployment gates.

## Exact/static historical template resolution

Static template and terminology references are exact identities. An unavailable
auxiliary revision is reported as a degraded-build omission and is never replaced
with an older or newer revision. The representing document template itself is
still mandatory. Dynamic references remain explicitly dynamic and resolve to a
frozen identity recorded in the manifest.

## Provisional external artifact catalog

Decision record: open `DEC-012` in [`decisions.md`](decisions.md).

Phase 1 supports package-local `builtin` supplements and evidence-backed
`waiver` entries. This mechanism and its first two concrete uses require review:

- CodeSystem `1.2.276.0.76.5.401` is packaged as a ten-code builtin derived
  from the public HL7 Germany metastasis table and provisionally marked
  complete. Its completeness and redistribution basis must be confirmed.
- IHE split-dose template `1.3.6.1.4.1.19376.1.5.3.1.4.9` has a provisional
  spec-only waiver because the IHE text presents it as a discriminator under
  Medication Entry and no independent template body was located. The waiver is
  intentionally not an `ok` artifact and the build remains degraded.

The exact IHE Medicine Entry analysis artifact
`1.3.6.1.4.1.19376.1.9.1.3.1@2019-08-27T16:13:43` is resolved by the existing
`ch-pharm-` source hint and is sufficient for cache/build availability under
`DEC-004`; its optional source sidecar remains unavailable. It is not an
external-artifact blocker and must not be duplicated as a builtin. In the
selected AKTIN document its 49 named constraints are registry evidence only:
none has a CDA location or is renderable. The effective medication branch uses
`UV Medication Information (simple)` instead, so forcing the IHE constraints
onto that branch would invent a template relationship.

The exact AKTIN/DIVI CodeSystem
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` remains unresolved. A fragment
must not be promoted to a complete formal terminology dependency. Future
`download`, `fhir`, `mediawiki`, or licensed local-file modes must be added only
for a concrete required artifact and reviewed separately.

## Repetition identifiers

Nested repetitions are supported when every independent occurrence level has an
explicit `occurrence_keys` column. This permits outer and inner occurrences to
be joined across CSV sources without positional guessing. A single one-file
one-level `1:n` source may still use source order as its occurrence identity for
backward convenience.

An explicit `for_each` may bind a source repeat to a deeper CDA repeat node
while leaving an enclosing repeat-capable CDA node as one shared container. The
selected medication structure uses this to produce one medication section with
one entry per `medikamentose_therapie` occurrence. This alignment does not
license a join between independent source repetitions; those still require
occurrence keys.

If a future source format has no stable occurrence identifier for independent
nested streams, the ambiguity must be resolved in source configuration; the
runtime will not invent an association by zipping rows.

## CDA narrative

The structural CDA renderer is generic. Section-specific human-readable
narrative remains minimal and should be generated from the same normalized
occurrence model without changing data-to-CDA mapping semantics.

## Receiver protocol and exactly-once delivery

`transport.py` intentionally uses generic HTTP POST until the actual receiver
protocol, authentication and batch envelope are specified. Local sent-state
cannot prove exactly-once delivery across the failure window where a POST
succeeds but the process crashes before state is recorded. Receiver-supported
document IDs or idempotency semantics should be used when available.
