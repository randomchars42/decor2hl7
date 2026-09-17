# Operate document generation

This workflow is for the runtime operator. It begins after the specification
mapping and site configuration have been reviewed. Its outcome is validated
target documents plus local transformation and delivery state.

## Before each run

Confirm that the following belong to the same selected release and transaction:

- compiled models;
- reviewed mapping and its identity lock;
- approved site configuration;
- the external input snapshot.

Then run the non-delivering checks:

```bash
decor2hl7 check
decor2hl7 check-input --input /data/clinical-export
```

Do not proceed to delivery when identity, configuration, input, or required
construction values fail validation.

## Transform without sending

```bash
decor2hl7 transform --input /data/clinical-export
```

This ingests, normalizes, validates, maps, renders, and records changed
documents. Inspect the generated output and, where required, run independent
CDA conformance validation:

```bash
decor2hl7 validate-cda out/RELEASE/TRANSACTION/*.xml \
  --report /tmp/cda-conformance
```

A valid mapping does not by itself prove that a complete generated document
passes every XSD and Schematron constraint; keep these gates distinct.

## Send approved output

Send already generated, pending documents with:

```bash
decor2hl7 send
decor2hl7 status
```

Or transform and send in one invocation after the process has been established:

```bash
decor2hl7 run --input /data/clinical-export --send
decor2hl7 status
```

`status` shows pending and recorded delivery state. Unchanged records are not
emitted again. Relevant changes to normalized data, occurrence structure,
compiled specification, mapping, site policy, or renderer identity create a new
document version.

The current generic HTTP adapter sends one document at a time. Authentication,
acknowledgement parsing, batching, receiver idempotency, and exactly-once
delivery require a receiver-specific adapter; do not assume the generic adapter
provides those guarantees.

## Diagnose a failed run by ownership

| Symptom | Return to |
|---|---|
| Missing artifact, checksum, or selected identity | Specification maintainer or technical maintainer |
| Disputed clinical correspondence or unresolved target | Clinical mapping reviewer |
| Missing file/column, join, parsing, code alias, identifier, or timezone | Site integration administrator |
| CDA XSD, Schematron, or assertion failure | Mapping reviewer and technical maintainer |
| Authentication, acknowledgement, or receiver protocol failure | Runtime/integration owner |

Keep failed output and reports with the exact input and configuration identity
needed for diagnosis. Do not repair a runtime incident by changing the portable
mapping or site configuration without sending that change back through its
own review workflow.

The technical runtime and state contract is documented in
[`topics/input-runtime-and-delivery.md`](../topics/input-runtime-and-delivery.md).
