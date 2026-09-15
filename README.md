# decor2hl7

`decor2hl7` transforms flat clinical CSV exports using an exact ART-DECOR
release and transaction. CDA is the first output target; the normalized dataset
and input pipeline remain target-neutral.

Python 3.10.8 or newer is supported. Runtime has no third-party dependencies.
Setup/build and explicit CDA conformance validation use checksum-pinned external
packages and Java tooling cached by `fetch`.

For project rules and design questions, start with
[`docs/index.md`](docs/index.md).

## Quick start

Install the package and create a workspace:

```bash
python3 -m pip install -e .
mkdir work
cd work
decor2hl7 init
```

Select an exact release and transaction, then build the specification products:

```bash
decor2hl7 list-versions
decor2hl7 set-version 2026.1.2
decor2hl7 list-transactions
decor2hl7 set-transaction notaufnahmeregister--60

decor2hl7 fetch
decor2hl7 build
decor2hl7 init-cda-mapping
decor2hl7 check-cda-mapping
```

Selection changes only `aktin.json`; it does not fetch or build. Catalog
commands print stable keys accepted by the corresponding `set-*` commands.

Review the generated mapping guides and edit the portable
`mapping/<release>/<transaction>/cda-mapping.json`, not the generated Markdown
or XML previews. `mapping-lock.json` records the exact model and target identity.

## Configure a site's input

Source CSVs remain outside the workspace. Inspect one coherent source snapshot
and initialize site-owned configuration:

```bash
decor2hl7 propose-input --input /data/aktin/export
decor2hl7 init-site-config
decor2hl7 check-input --input /data/aktin/export
```

The site bundle owns filenames, joins, columns, parsing, local code/unit aliases,
occurrence keys, timezone, identifiers, and deployment values. It does not
change the portable CDA mapping.

If `--input` is omitted, input commands use the optional deployment default:

```json
{"input": {"directory": "/data/aktin/export"}}
```

Runtime commands accept `--cda-mapping FILE` and `--site-config DIRECTORY` to
select explicit bundles.

## Verify the mapping

Create an isolated deterministic fixture:

```bash
decor2hl7 setup-test
decor2hl7 test-cda-mapping
```

Or install the repository's authored reference scenario:

```bash
decor2hl7 setup-test --force \
  --scenario tests/fixtures/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases
decor2hl7 test-cda-mapping
```

Authored scenarios pin release and transaction identity, declare all source
relationships, and provide independent present/absent expectations. Generated
CDA is not used as its own golden oracle. Mapping tests bypass production state
and transport.

Validate generated CDA independently against the pinned CDA/SDTC XSD and exact
generated Schematron:

```bash
decor2hl7 validate-cda test/2026.1.2/notaufnahmeregister--60/out/TEST-1.xml
decor2hl7 validate-cda out/*.xml --report /tmp/cda-conformance
```

Mapping validity and document conformance are separate gates.

## Run

```bash
decor2hl7 check
decor2hl7 check-input --input /data/aktin/export
decor2hl7 transform --input /data/aktin/export
decor2hl7 send

# or transform and send in one run
decor2hl7 run --input /data/aktin/export --send

decor2hl7 status
```

Runtime ingests, normalizes, validates, maps, renders, evaluates assertions,
records change state, and optionally sends. Unchanged records are not emitted
again; relevant changes to data, occurrence structure, specification, mapping,
site policy, or renderer identity produce a new version.

The only current transport adapter is bounded single-document `http-post`:

```json
{
  "transport": {
    "adapter": "http-post",
    "url": "https://receiver.example/cda",
    "timeout": 60,
    "headers": {}
  }
}
```

Authentication, batch envelopes, acknowledgements, and receiver idempotency
require a concrete future adapter rather than arbitrary configuration.

## Workspace

```text
INPUT/                              producer-owned
├── cases.csv
├── medications.csv
└── ...

WORKSPACE/                          decor2hl7-owned
├── aktin.json                      selected identity and defaults
├── config/                         acquisition hints and reviewed overlays
├── spec/<release>/                 fetched cache and transaction closures
├── model/<release>/<transaction>/  generated models, audit, and proposal
├── mapping/<release>/<transaction>/ reviewed portable target mapping
├── site/<release>/                 deployment configuration
├── test/<release>/<transaction>/   isolated verification
├── out/<release>/<transaction>/    runtime documents
└── state/                           change and delivery history
```

The release is the acquisition/cache scope. The transaction is the model,
mapping, site, test, and output scope. State is transaction-scoped so a later
release of the same transaction can still detect unchanged input.

Generated `spec/`, `model/`, `test/`, and `out/` content can be rebuilt. Preserve
reviewed mapping/site configuration and any source-controlled recovery overlay
before removing generated workspaces.

## Fetch and build behavior

`fetch` recursively resolves the selected transaction's typed dependency closure
and records exact requested/resolved identities, artifact forms, checksums,
ownership, attempts, and degraded resources. It prefers strong owner and link
context before HTTP probing and never substitutes another static revision.

Use cache-only mode when ART-DECOR is unavailable:

```bash
decor2hl7 fetch --offline
```

Use `--retry-missing` to retry settled failures. `fetch --fail-on-degraded`
gates the complete crawl; `build --fail-on-degraded` gates only missing artifacts
consulted by the selected compiler inputs.

`build` is CSV-independent. It produces:

- `model.json`: target-neutral dataset, terminology, and occurrence model;
- `cda.json`: exact physical CDA constraint and value model;
- `mapping-audit.json`: candidates, evidence, gaps, and coverage;
- `cda-mapping.proposed.json`: concise executable proposal;
- generated mapping guides and readable CDA trees;
- build and conformance diagnostics.

The complete sequence and authority boundaries are described in
[`docs/specification-to-mapping-pipeline.md`](docs/specification-to-mapping-pipeline.md).

## Mapping and site configuration

The portable mapping separates:

- `fields`: scalar selections and transforms;
- `structures`: occurrence, discriminator, coalescing, and concatenation rules;
- `field_reviews`: intentional null selections;
- `defaults` and `target_defaults`: generic and exact reviewed completion;
- `site_requirements`: required values delegated to a named site channel;
- target identities and configuration provenance.

Generated Markdown explains the JSON but is never itself configuration. The
format contract is
[`docs/mapping-documentation-format.md`](docs/mapping-documentation-format.md).

`init-cda-mapping` preserves existing reviewed choices and refreshes generated
guides. Use `init-cda-mapping --reset` only when the generated proposal should
replace all reviewed mapping state.

## Documentation

- [`Project-decor2hl7.md`](Project-decor2hl7.md): goal and ownership
- [`docs/index.md`](docs/index.md): topic/question navigation
- [`docs/architecture.md`](docs/architecture.md): component and data flow
- [`docs/reference-transaction.md`](docs/reference-transaction.md): current
  non-obvious AKTIN mapping policy
- [`docs/open-boundaries.md`](docs/open-boundaries.md): unresolved matters only
- [`docs/roadmap.md`](docs/roadmap.md): unfinished work only

## Release verification

After regenerating the companion reference workspace for its selected release
and transaction, run:

```bash
make baseline
make check
```

Review the baseline diff before accepting it. Generated coverage counts and
conformance diagnostics belong in the reference artifacts and fixtures rather
than duplicated prose.
