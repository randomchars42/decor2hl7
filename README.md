# decor2hl7

`decor2hl7` transforms clinical source data queried from a database to HL7
(currently CDA) using an ART-DECOR release and transaction. The normalized dataset and input pipeline remain target-neutral and will allow generation of FHIR documents in the future.

## Documentation

- [Usage](docs/user/index.md)
- [Development & technical reference](docs/index.md#developer-and-technical-reference)

ART-DECOR defines a dataset and a template.

With `decor2hl7` the data will flow like this:

```
(config) --> source database -- (mapping) --> normalized dataset -- (mapping) --> template -- (config) --> target
```

To facilitate this flow `decor2hl7` has three different levels:

1. Import the dataset and template definition from ART-DECOR & review (edit / add to) the recognized mapping between the dataset and the template. _This can be done once per dataset / template version and shared between users_. [Review a specification and publish a mapping](docs/user/specification-and-mapping.md)
2. Map the source data to the normalized dataset. Configure local access to source database and target. [Configure a site's input](docs/user/site-configuration.md)
3. Runtime. Data gets fetched from the database, processed and send off to the receiver. Validate documents and delivery state. [Operate document generation](docs/user/runtime-operation.md)

## Requirements

- Python 3.10.8 or newer;
- an ODBC driver manager and database-specific ODBC driver when ODBC source
  extraction is enabled;
- Java for setup/build and explicit CDA conformance validation;
- network access to acquire uncached ART-DECOR artifacts during `fetch`.

CSV and native SQLite operation use only the Python standard library. Direct
ODBC extraction uses the optional `pyodbc` dependency; install it with
`python3 -m pip install -e '.[odbc]'` and provide the database-specific ODBC
driver. Setup/build validation packages are
checksum-pinned and cached by `fetch`.

## Install

Currently, `decor2hl7` must be installed from source:

```bash
git clone https://github.com/randomchars42/decor2hl7.git
cd decor2hl7
python3 -m pip install -e .
```

Once the package is published, the editable source installation can be
replaced with `python3 -m pip install decor2hl7`.

## Create a workspace

Create the working directory outside the source checkout:

```bash
cd ..
mkdir decor2hl7-work
cd decor2hl7-work
decor2hl7 init
```

CLI text and generated Markdown default to English. To create a workspace with
German explanatory prose, use:

```bash
decor2hl7 --output-language de init
```

This setting is independent of ART-DECOR retrieval language and CDA document
language. See [Output language and technical terminology](docs/topics/output-language.md).

The workspace separates generated specification/model products, portable
mapping decisions, site configuration, test output, runtime output, and state:

```text
WORKSPACE/
├── decor2hl7.json                   version / transaction selection and
|                                    reviewed local model extensions
├── config/                          acquisition hints and reviewed overlays
├── spec/<release>/                  fetched cache and transaction closures
├── model/<release>/<transaction>/   generated models, audit data, and proposal
├── mapping/<release>/<transaction>/ reviewed portable target mapping
├── site/<release>/                  deployment and transaction input configuration
├── test/<release>/<transaction>/    isolated mapping verification
├── out/<release>/<transaction>/     generated runtime documents
└── state/                           SQLite lineage, snapshots, runs, quarantine
```

Generated `spec/`, `model/`, `test/`, and `out/` content can be rebuilt.
Preserve reviewed mapping and site configuration before removing a workspace.

## Command overview

```bash
#
# Stage 1: specification and mapping setup, once per version / transaction
#

# list available versions
decor2hl7 list-versions

# set the version
decor2hl7 set-version RELEASE

# list available transactions for this version
decor2hl7 list-transactions

# set the transaction
decor2hl7 set-transaction TRANSACTION

# fetch all necessary concepts, templates etc.
# (this might take a while)
decor2hl7 fetch

# build the configuration
decor2hl7 build

# generate mapping proposals
decor2hl7 init-cda-mapping

# now review those mappings

# check the defined mappings
decor2hl7 check-cda-mapping

#
# Stage 2: site configuration, once per site
#

# generate a mapping proposal / skeleton
decor2hl7 propose-input --input /data/clinical-export
decor2hl7 init-site-config
decor2hl7 check-input --input /data/clinical-export

# Isolated mapping verification
decor2hl7 setup-test
decor2hl7 test-cda-mapping

# Independent SQLite integration rehearsal from this reviewed setup
decor2hl7 setup-integration-test --output /tmp/decor2hl7-integration

#
# Stage 3: runtime operation
#

decor2hl7 check
decor2hl7 extract-source --output /data/snapshots/review-1
decor2hl7 transform --input /data/clinical-export
decor2hl7 send
decor2hl7 status
```

Use `decor2hl7 run --input /data/clinical-export --send` only after the separate
validation and delivery steps are understood for the deployment.
For a configured ODBC or SQLite source, `decor2hl7 run-source --send` performs
bounded extraction into a replayable atomic snapshot and then uses the identical
ingestion, transformation, delivery, and SQLite lineage pipeline. See the
[site configuration guide](docs/user/site-configuration.md#sqlite-input-and-a-local-integration-test)
for native SQLite input and a reproducible synthetic integration test.
The [integration test guide](docs/user/integration-testing.md) explains the
packaged scenarios, independent setup command, local spool and optional receiver
configuration.

## Project maintenance

For repository development, install the development dependencies and run:

```bash
python3 -m pip install -e '.[dev]'
make check
```

`make check-unit` runs the repository-contained suite without the companion
reference workspace. `make check-reference` requires the exact companion
workspace and fails rather than skipping when it is absent or stale. The full
`make check` gate runs both tiers, including the end-to-end reference mapping
test.

If the exact companion workspace has a different local path, use
`make check REFERENCE_WORKSPACE=/path/to/reference-workspace`. Its required
release/transaction identity and baseline checks remain unchanged.

Release verification also regenerates the companion reference workspace and
reviews its baseline changes with `make baseline`. Generated coverage counts
and conformance diagnostics belong in generated artifacts and fixtures rather
than durable prose.

Runtime accepts the current configuration, SQLite state and sidecar formats.
Malformed non-null mappings, mismatched mapping locks, invalid CSV structure and
incomplete pending metadata fail explicitly. Existing delivered revisions remain
available when a correction is generated. No automatic old-format migration is
provided; keep the reviewed mapping lock beside the mapping when moving a bundle.
