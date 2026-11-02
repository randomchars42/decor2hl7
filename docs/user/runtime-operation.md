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

This ingests, normalizes, validates, maps, and renders changed documents. It
does not advance delivery or lineage state until a transport handover succeeds.
Inspect the generated output and, where required, run independent CDA
conformance validation:

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

When `site.json:source.adapter` is `odbc` or `sqlite`, the equivalent scheduled
path is:

```bash
decor2hl7 run-source --dry-run
decor2hl7 run-source --limit 20 --send
decor2hl7 run-source --send
```

Each invocation first creates a uniquely named, replayable snapshot below
`state/snapshots/` unless `--snapshot-output` selects a new explicit path.
`--since YYYY-MM-DD` widens or narrows the configured trailing window.
The dry run creates that source evidence and reports classification but emits,
delivers, and commits no document.
`--limit` is a first-look development aid: its run is recorded as partial and
does not advance the completed-snapshot watermark. Do not use it as production
batching.

`status` shows pending documents, recorded delivery state, and recent runs.
Unchanged records are not emitted again. Relevant changes to normalized data,
occurrence structure, compiled specification, mapping, site policy, or renderer
identity create a new document version. A correction keeps its CDA `setId`,
increments `versionNumber`, and identifies the prior committed document through
`relatedDocument typeCode="RPLC"`.

With `transport.adapter: spool`, successful handover means an XML document and
its JSON sidecar are atomically visible under
`<directory>/YYYY-MM/<document-stem>/`. An existing different artifact is an
error and is never overwritten. Downstream removal or acknowledgement is a
separate integration responsibility.

The generic HTTP adapter sends one document at a time. Authentication,
acknowledgement parsing, batching, receiver idempotency, and exactly-once
delivery require a receiver-specific adapter; do not assume the generic adapter
provides those guarantees.

Input-validation and rendering failures for individual records are written to
`state/quarantine/<run-id>/`, while later records continue. The configured
`operation.failure_threshold` determines whether the overall command still
succeeds. Configuration, extraction, locking, and SQLite failures abort the
run. Preserve `state/state.sqlite`; it is the authority for version and
replacement lineage. A legacy `state/index.json` is imported automatically
once but is no longer updated.

Snapshots, pending output, sidecars, and quarantine records can contain
clinical data. Apply the deployment's access, retention, backup, and secure
deletion policy to the complete workspace and configured spool; the runtime
does not substitute for those controls.

## Diagnose a failed run by ownership

| Symptom | Return to |
|---|---|
| Missing artifact, checksum, or selected identity | Specification maintainer or technical maintainer |
| Disputed clinical correspondence or unresolved target | Clinical mapping reviewer |
| Missing file/column, join, parsing, code alias, identifier, or timezone | Site integration administrator |
| Stale snapshot maximum or database/query failure | Database/replication and site integration owner |
| CDA XSD, Schematron, or assertion failure | Mapping reviewer and technical maintainer |
| Authentication, acknowledgement, or receiver protocol failure | Runtime/integration owner |

Keep failed output and reports with the exact input and configuration identity
needed for diagnosis. Do not repair a runtime incident by changing the portable
mapping or site configuration without sending that change back through its
own review workflow.

The technical runtime and state contract is documented in
[`topics/input-runtime-and-delivery.md`](../topics/input-runtime-and-delivery.md).
