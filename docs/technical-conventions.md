This file contains basic conventions and is targeted at AI.

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
