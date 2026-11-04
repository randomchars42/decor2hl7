# Operate document generation

Process an approved source snapshot, inspect the generated documents, then
deliver them.

## Workspace for runtime

Runtime consumes the reviewed setup and external input. It writes documents
and delivery history to this workspace:

```text
/data/decor2hl7-test-input/                 complete fictional source snapshot
WORKSPACE/
├── decor2hl7.json                          selected release and transaction
├── spec/2026.1.2/                          cached validation packages
├── model/2026.1.2/notaufnahmeregister--60/   compiled models and validator
├── mapping/2026.1.2/notaufnahmeregister--60/ cda-mapping.json and mapping-lock.json
├── site/2026.1.2/
│   ├── site.json                          input relationships, identifiers, transport
│   └── notaufnahmeregister--60/            csv-mapping.json and codes-mapping.json
├── out/2026.1.2/notaufnahmeregister--60/     XML documents and JSON sidecars
├── spool/                                 local test handover
└── state/                                 SQLite history, snapshots, quarantine
```

`out/` holds prepared and delivered revisions; `state/state.sqlite` records
which revisions were handed over. A site override changes configuration paths,
while output and history still belong to the selected workspace.

## Populate the practice workspace

If you followed guide 2, use its `/data/decor2hl7-test` workspace and complete
`/data/decor2hl7-test-input` snapshot, then continue at step 1. Keep its reviewed
site configuration, including the renamed columns and local spool.

To start directly, first create the practice workspace from
[guide 1](specification-and-mapping.md#set-up-the-practice-workspace). Then
populate a fresh site and input directory from the authored cases:

```bash
cd /data/decor2hl7-test
decor2hl7 setup-test --scenario test/scenarios/valid-reference-cases \
  --test-dir test/runtime-fixture
cp -a test/runtime-fixture/input /data/decor2hl7-test-input
mkdir -p site/2026.1.2/notaufnahmeregister--60
cp test/runtime-fixture/config/site.json site/2026.1.2/
cp test/runtime-fixture/config/csv-mapping.json site/2026.1.2/notaufnahmeregister--60/
cp test/runtime-fixture/config/codes-mapping.json site/2026.1.2/notaufnahmeregister--60/
```

The copied bundle supplies fictional identifiers, local aliases, and required
CDA values. In `site/2026.1.2/site.json`, replace `transport` with the local
practice destination:

```json
{
  "transport": { "adapter": "spool", "directory": "/data/decor2hl7-test/spool" }
}
```

Use unused input and site paths for this direct-start route. Examples below use
`2026.1.2 / notaufnahmeregister--60`; run commands from the practice workspace
root. For correction, retry, and rejection exercises, follow the
[runtime testing guide](testing.md#3-test-runtime-and-delivery).

## 1. Check the files for this run

Check configuration first, then the actual input. Resolve identity,
configuration, or input errors before preparing delivery.

```bash
decor2hl7 check
decor2hl7 check-input --input /data/decor2hl7-test-input
```

For a configured database source, first create a snapshot with
`extract-source --output /data/snapshots/review-1` and use that path as
`--input` throughout the review. The destination must be new; inspect its
`.decor2hl7-snapshot.json` for the selected window and row counts.

## 2. Prepare and inspect the documents

Transform the snapshot without sending. Changed valid records produce paired
files under `out/2026.1.2/notaufnahmeregister--60/`:

```text
SCENARIO-01--<hash>-v1.xml     CDA document for the case
SCENARIO-01--<hash>-v1.json    identity, validation messages, warnings, source provenance
```

The filename contains a sanitized case key and a hash; the sidecar's `key`
identifies the original case. Inspect these in order:

1. Read the command summary. `emitted` reports prepared documents;
   `unchanged` reports records already committed with the same relevant content;
   `invalid` and `quarantined` need investigation.
2. Open the matching JSON sidecar. Check `validation`, `render_warnings`, and
   the document version. For `run-source`, `source_snapshot` records extraction
   provenance.
3. Open the XML and compare it with the input. For the site guide's example,
   find the postal code under `recordTarget/patientRole/addr/postalCode` and
   compare diagnosis texts with their source occurrences.
4. Validate the XML independently. Open `validation/first-run.md` for the
   overall status and validation stages; the adjacent JSON contains complete
   diagnostics, including affected files and locations.

Prepare, validate, and check pending status:

```bash
decor2hl7 transform --input /data/decor2hl7-test-input
decor2hl7 validate-cda out/2026.1.2/notaufnahmeregister--60/*.xml \
  --report out/2026.1.2/notaufnahmeregister--60/validation/first-run
decor2hl7 status
```

Expect pending documents after a successful first transformation. Delivery and
lineage advance after successful handover. Keep pending XML and JSON sidecars
together and unchanged; delivery checks their identity and XML checksum.
Independent CDA conformance is a separate gate from mapping and input validity.

## 3. Deliver the reviewed output

Send the pending documents after inspection and validation. To deliver only
specific reviewed documents, pass their XML filenames to `send`.

With the site guide's spool configuration, a successful handover creates:

```text
/data/decor2hl7-test/spool/
└── YYYY-MM/
    └── <document-stem>/
        ├── <document-stem>.xml
        └── <document-stem>.json
```

The pair becomes visible atomically. Check `status`: `pending_documents`
should clear for the delivered batch, and `delivered_documents` includes local
spool handovers. Confirm downstream import through the receiver's own interface.

```bash
decor2hl7 send
decor2hl7 status
```

An identical spool retry is safe; conflicting content at the same destination
is rejected. Retry reuses the pending document and preparation month. If spool
publication succeeded before a process stopped, a subsequent transforming run
can recover its local state commit; the summary reports this as `recovered`.

## 4. Repeat or schedule the established workflow

An unchanged record produces no new committed version. Relevant changes to
source data, mapping, compiled specification, site policy, or the renderer
produce a correction. Inspect its new document `id`, stable `setId`, incremented
`versionNumber`, and `relatedDocument typeCode="RPLC"` reference to the prior
committed document. Older delivered XML and sidecars remain available.

For an approved CSV pipeline, transformation and delivery can be combined:

```bash
decor2hl7 run --input /data/decor2hl7-test-input --send
decor2hl7 status
```

For a configured ODBC or SQLite source, first preview extraction and
classification, then enable delivery:

```bash
decor2hl7 run-source --dry-run
decor2hl7 run-source --send
decor2hl7 status
```

Each invocation creates a replayable snapshot under `state/snapshots/`.
The dry run creates source evidence but no XML or document-state commit.
`--snapshot-output PATH` selects a new snapshot directory, and
`--since YYYY-MM-DD` changes the rescan window. `--limit 20` is a development
preview recorded as partial, so it does not advance the completed-snapshot
watermark.

When the freshness guard rejects a snapshot, check replication and the maximum
case write timestamp before retrying. Changing the database, query, or input
relationships starts a separate source baseline.

## 5. Investigate failures and preserve state

For an individual rejected record, open
`state/quarantine/<run-id>/<case-stem>.json`. Its `stage`, `problems`, and
`record` identify the failing step and normalized values. Later records can
continue; `operation.failure_threshold` controls the overall exit result.
Configuration, extraction, locking, and SQLite failures abort the run.

| Finding | Inspect or return to |
|---|---|
| Missing artifact, checksum, or selected identity | Specification setup and build diagnostics |
| File, column, join, parsing, alias, identifier, or timezone error | Site JSON and the original snapshot |
| Unresolved clinical correspondence | Mapping decision card and clinical review |
| XSD or Schematron failure | Validation Markdown/JSON, affected XML, and mapping reviewer |
| Database error or stale snapshot | SQL files, snapshot manifest, and replication owner |
| Delivery or receiver rejection | Transport settings and the receiver's response |

Preserve the input snapshot, failed output, and reports for diagnosis. Back up
`state/state.sqlite`: it owns version and replacement lineage. Only current
state and complete current sidecar formats are accepted; legacy import requires
an explicit conversion. Apply site access and retention rules to snapshots,
output, quarantine, state, and the spool.

The generic HTTP adapter requires a separately agreed receiver protocol for
authentication, acknowledgements, and idempotency. Local CDA conformance and
spool success do not establish receiver acceptance; known receiver constraints
are recorded in [open boundaries](../open-boundaries.md#validation-and-delivery).
Further state and delivery details are in the
[technical runtime contract](../topics/input-runtime-and-delivery.md#runtime).
