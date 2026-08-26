# Known boundaries after the 0.1.0 correctness pass

The 0.1.0 rewrite now supports declarative semantic transforms, formal
ART-DECOR assertion enforcement, transitive identity-lineage enrichment and
explicitly keyed nested repetitions. The remaining items are boundaries where
external protocol information or broader ART-DECOR expression coverage is
needed; they are not silent runtime fallbacks.

## Transform vocabulary

`cda-mapping.json` version 2 accepts direct target names and small declarative
rules. The built-in transform vocabulary is deliberately limited to `identity`,
`enum`, `ordinal`, and `not`. The generated proposal uses it for the currently
proven AKTIN semantics for Tetanusschutz, Isolation and modified Rankin.

A future concept whose ART-DECOR representation needs a different structural or
computed transformation remains evidence-linked but non-executable until an
explicit transform is added. `ADAPT` remains usable mapping evidence but is not
automatic dataset identity inheritance.

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

For some historical external repositories the available source corpus can be
incomplete. Static template flexibility may still fall back to the nearest older
revision when the exact referenced revision is unavailable. In a production
release cache known to be complete, an unavailable exact static revision should
be treated as a closure error instead of falling back.

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
