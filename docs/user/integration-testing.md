# Prepare an independent integration test

Use this workflow to exercise database extraction, document generation, local
delivery, unchanged replay and corrections with fictional data. It creates a
new test environment from an existing reviewed specification workspace. Your
source site's input configuration and delivery history are not copied.

## Prepare the environment

The source workspace must contain its selected fetched specification, compiled
models, reviewed CDA mapping and matching lock. From any directory, run:

```bash
decor2hl7 --root /data/reviewed-workspace setup-integration-test \
  --output /tmp/decor2hl7-integration
```

The destination must be new and separate from the source workspace. Setup uses
the packaged `valid-reference-cases` scenario for the exact selected release and
transaction. Packaged cases are available for `2026.1.2` and `2026.1.3`,
transaction `notaufnahmeregister--60`. They are version-specific synthetic test
definitions, not production extraction layouts or clinical advice.

Use `--scenario /path/to/authored-scenario` for a different authored scenario.
Its release, transaction OID, key and effective date must match. Setup rejects a
mismatch rather than translating values or substituting another revision.
`--written-at` overrides the fixed synthetic source-write timestamp and requires
an ISO timestamp with timezone.

The result contains:

```text
decor2hl7-integration/
├── README.md                  commands for this exact setup
├── integration-test.json      identities, expected cases and initial checksums
├── scenario/                  preserved authored scenario definition
├── fixture/                   CSV/config mapping fixture and expected.json
├── input/source.sqlite        synthetic input outside the runtime workspace
└── workspace/
    ├── decor2hl7.json
    ├── spec/                  copied exact release evidence and validation tools
    ├── model/                 selected models and generated validator
    ├── mapping/               reviewed CDA mapping and lock
    └── site/                  generated test site values, mappings and SQL
```

Files are copied independently, including through source symlinks; the new test
does not need the old auxiliary SQLite workspaces. The specification and model
copies can be large. The maintained scenario definitions are small and packaged
with the installed application. Setup does not fetch, rebuild, change mappings,
run transformations or send documents.

## Generate, validate and publish locally

Follow the commands in the generated `README.md`. For the default timestamp:

```bash
decor2hl7 --root /tmp/decor2hl7-integration/workspace check
decor2hl7 --root /tmp/decor2hl7-integration/workspace run-source --since 2026-06-01
decor2hl7 --root /tmp/decor2hl7-integration/workspace validate-cda \
  /tmp/decor2hl7-integration/workspace/out/2026.1.2/notaufnahmeregister--60/*.xml \
  --report /tmp/decor2hl7-integration/conformance
decor2hl7 --root /tmp/decor2hl7-integration/workspace run-source --since 2026-06-01 --send
```

Use the actual selected release/transaction in the validation path. Compare the
documents with the expected cases and content in `fixture/expected.json`.
Extraction snapshots appear under `workspace/state/snapshots/`, generated XML and
metadata under `workspace/out/`, and local publications under `workspace/spool/`.
Spool publication establishes a local handover.

Repeat `run-source --since 2026-06-01 --send` without changing the input. No
additional versions should appear. To exercise a correction, change one authored
value in `input/source.sqlite`, retain its case/occurrence identity and source
timestamp, and run the command again. Only the changed case should receive a new
version. Check its replacement reference and inspect `decor2hl7 status`.

The fixed write timestamp, long extraction window and disabled freshness guard
are fixture settings. They permit repeating these checks without making the
test data look like a new production snapshot.

## Prepare a receiver rehearsal separately

Use a different output directory and an explicit endpoint to prepare HTTP
delivery instead of local spool:

```bash
decor2hl7 --root /data/reviewed-workspace setup-integration-test \
  --output /tmp/decor2hl7-receiver-test \
  --receiver-url http://127.0.0.1:9090/aktin/cda/fhir/Binary
```

Setup sends nothing. Generate and validate the documents first. Running `--send`
in this variant uses the configured HTTP endpoint. Receiver validation, import,
storage and correction acceptance are separate checks; configuring an endpoint
does not establish any of them. Profile-specific incompatibilities remain in
the [open boundaries](../open-boundaries.md).

## Keep definitions and historical evidence

The generated environment is disposable once the test results you need have
been retained. Recreate it from its reviewed source setup and matching scenario.
Keep exact previously validated documents, receiver responses and checksums
separately when historical acceptance evidence matters. A newly generated
document cannot replace that evidence.

The repository's reference tests still require the exact companion reference
workspace. For another local path, run:

```bash
make check REFERENCE_WORKSPACE=/data/reference-workspace
```

This changes its location, not the required reference identity. The integration
setup command does not remove that reference dependency.
