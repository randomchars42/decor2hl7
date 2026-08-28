# Known boundaries after the 0.1.0 correctness pass

The 0.1.0 rewrite now supports declarative semantic transforms, formal
ART-DECOR assertion enforcement, transitive identity-lineage enrichment and
explicitly keyed nested repetitions. The remaining items are boundaries where
external protocol information or broader ART-DECOR expression coverage is
needed; they are not silent runtime fallbacks.

## Transform vocabulary

`cda-mapping.json` version 3 accepts direct target names, small declarative
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

## Secondary ICD-10 diagnoses (concept 29508)

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
revision is a fetch/readiness error and is never replaced with an older or newer
revision. Dynamic references remain explicitly dynamic and resolve to a frozen
identity recorded in the manifest.

## Repetition identifiers

Nested repetitions are supported when every independent occurrence level has an
explicit `occurrence_keys` column. This permits outer and inner occurrences to
be joined across CSV sources without positional guessing. A single one-file
one-level `1:n` source may still use source order as its occurrence identity for
backward convenience.

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
