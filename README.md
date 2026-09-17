# decor2hl7

`decor2hl7` transforms flat clinical source data using an exact ART-DECOR
release and transaction. CDA is the first output target; the normalized dataset
and input pipeline remain target-neutral.

The project is independent of upstream artifact publishers. References to
organizations, profiles, or projects identify provenance and do not imply
endorsement.

## Documentation

Choose the documentation track that matches your role:

- [Clinical and ART-DECOR workflow guides](docs/user/index.md) explain the
  three workflows from the user's perspective.
- [Developer and technical reference](docs/index.md#developer-and-technical-reference)
  explains architecture, evidence rules, generated formats, and implementation
  behavior.

The user workflows are deliberately separate:

| User group | Work product | Guide |
|---|---|---|
| Specification maintainer and clinical mapping reviewer | Portable reviewed dataset-to-target mapping | [Review a specification and publish a mapping](docs/user/specification-and-mapping.md) |
| Site integration administrator | Site-local input and deployment configuration | [Configure a site's input](docs/user/site-configuration.md) |
| Runtime operator | Validated documents and delivery state | [Operate document generation](docs/user/runtime-operation.md) |

## Requirements

- Python 3.10.8 or newer;
- Java for setup/build and explicit CDA conformance validation;
- network access to acquire uncached ART-DECOR artifacts during `fetch`.

Runtime has no third-party Python dependencies. Setup/build validation packages
are checksum-pinned and cached by `fetch`.

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

The workspace separates generated specification/model products, portable
mapping decisions, site configuration, test output, runtime output, and state:

```text
INPUT/                              producer-owned source snapshot

WORKSPACE/                          decor2hl7-owned
├── decor2hl7.json                  selected release, transaction, and defaults
├── config/                         acquisition hints and reviewed overlays
├── spec/<release>/                 fetched cache and transaction closures
├── model/<release>/<transaction>/  generated models, audit, and proposal
├── mapping/<release>/<transaction>/ reviewed portable target mapping
├── site/<release>/                 deployment and transaction input configuration
├── test/<release>/<transaction>/   isolated mapping verification
├── out/<release>/<transaction>/    generated runtime documents
└── state/                           change and delivery history
```

Generated `spec/`, `model/`, `test/`, and `out/` content can be rebuilt.
Preserve reviewed mapping and site configuration before removing a workspace.

## Command overview

The guides explain when and why to use each command. This is a compact reminder:

```bash
# Specification and portable mapping
decor2hl7 list-versions
decor2hl7 set-version RELEASE
decor2hl7 list-transactions
decor2hl7 set-transaction TRANSACTION
decor2hl7 fetch
decor2hl7 build
decor2hl7 init-cda-mapping
decor2hl7 check-cda-mapping

# Site input
decor2hl7 propose-input --input /data/clinical-export
decor2hl7 init-site-config
decor2hl7 check-input --input /data/clinical-export

# Isolated mapping verification
decor2hl7 setup-test
decor2hl7 test-cda-mapping

# Runtime operation
decor2hl7 check
decor2hl7 transform --input /data/clinical-export
decor2hl7 send
decor2hl7 status
```

Use `decor2hl7 run --input /data/clinical-export --send` only after the separate
validation and delivery steps are understood for the deployment.

## Project maintenance

For repository development, install the development dependencies and run:

```bash
python3 -m pip install -e '.[dev]'
make check
```

Release verification also regenerates the companion reference workspace and
reviews its baseline changes with `make baseline`. Generated coverage counts
and conformance diagnostics belong in generated artifacts and fixtures rather
than durable prose.
