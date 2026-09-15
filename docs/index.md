# Documentation

Use this page to enter the documentation by question. Current rules are
organised by topic; dates and implementation chronology are not part of the
navigation model.

## Where should I look?

| Question | Current source |
|---|---|
| What is the project trying to do, and who owns each artifact? | [`../Project-decor2hl7.md`](../Project-decor2hl7.md) |
| How is the code divided and how does data move through it? | [`architecture.md`](architecture.md) |
| Which ART-DECOR constructs are authoritative? | [`topics/art-decor-authority.md`](topics/art-decor-authority.md) |
| How are artifacts identified, fetched, cached, and admitted to a build? | [`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md) |
| How are dataset concepts, terminology, and quantities compiled? | [`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md) |
| How are CDA constraints, datatypes, assertions, and validators compiled? | [`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md) |
| How are mapping candidates, reviewed rules, defaults, and documentation produced? | [`topics/mapping-and-construction.md`](topics/mapping-and-construction.md) |
| How do site input, occurrences, runtime state, and delivery work? | [`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md) |
| What has been decided for the selected AKTIN reference transaction? | [`reference-transaction.md`](reference-transaction.md) |
| What is genuinely unresolved? | [`open-boundaries.md`](open-boundaries.md) |
| What does a `DEC-*` reference mean? | [`decisions.md`](decisions.md) |

## Workflow guides and specifications

- [`../README.md`](../README.md) is the command-oriented quick start.
- [`specification-to-mapping-pipeline.md`](specification-to-mapping-pipeline.md)
  follows the complete setup-time specification workflow.
- [`mapping-documentation-format.md`](mapping-documentation-format.md) specifies
  the generated mapping-review documents.
- [`recovery/`](recovery/) contains source-controlled, identity-pinned reviewed
  mapping overrides that cannot be regenerated from owner rules alone.

## Authority

The repository on `main` is authoritative for code, tests, and current project
documentation. The selected transaction and exact fetched artifacts establish
specification facts. Generated reference-workspace products are concrete
evidence, not general policy. Conversation text, dates, commit history, and
generated coverage counts do not define current behavior.

When sources differ, use this order:

1. exact owner artifacts and normative CDA/HL7 definitions for owner rules;
2. current topic documentation for accepted decor2hl7 policy;
3. implementation and tests for verified behavior;
4. the exact reference workspace for transaction-specific generated state.

Unresolved conflicts belong in [`open-boundaries.md`](open-boundaries.md); they
must not be filled by inference.
