# Architecture

## Main boundary

ART-DECOR complexity ends at generated models. Runtime does not parse fetched
XML or load setup-time validation packages.

```text
selection
   -> retrieval closure -> spec/
        -> dataset compiler -> model.json
        -> CDA compiler     -> cda.json
             -> mapping analysis -> audit + proposal
                  -> reviewed mapping bundle

external input + site configuration
   -> ingest -> normalize -> validate -> bind -> render -> state -> transport
```

`model.json` is target-neutral. `cda.json` is the current physical target model.
`cda-mapping.json` is the portable reviewed bridge between them. Site input
configuration and runtime state are separate products.

The rules governing each boundary are documented by topic in
[`index.md`](index.md). This page records component ownership and data flow,
not a second copy of those semantic rules.

## Package structure

```text
src/decor2hl7/
├── cli.py                  command orchestration
├── workspace.py            selection and workspace paths
├── retrieval/              ART-DECOR acquisition and closure
│   ├── client.py           scoped HTTP behavior
│   ├── catalog.py          release/transaction discovery
│   ├── references.py       typed dependencies and roles
│   ├── resolution.py       owner/project resolution order
│   ├── artifacts.py        identity and artifact-form contracts
│   ├── expansion.py        frozen terminology expansions
│   ├── sources.py          reviewed external source catalog
│   ├── fetch.py            recursive cache/manifest/closure workflow
│   └── xml.py              XML helpers and narrow repairs
├── compile/                model and mapping compilation
│   ├── artifacts.py        validated compiler inputs and degradation
│   ├── transaction.py      target-neutral dataset model
│   ├── terminology.py      terminology accessors
│   ├── structural.py       generated occurrence rules
│   ├── schematron.py       bounded supporting evidence
│   ├── mapping.py          candidates, gates, audit, proposal
│   └── reports.py          readable generated products
├── cda/                    CDA target implementation
│   ├── art_decor.py        owner-grammar classification
│   ├── core.py             CDA/RIM XSD graph
│   ├── datatypes.py        scalar representation policy
│   ├── model.py            typed physical target IR
│   ├── extensions.py       reviewed exact overlays
│   ├── compile.py          effective CDA compilation
│   ├── terminology.py      target binding enforcement
│   └── render.py           representation-driven XML output
├── data.py                 CSV ingestion and occurrence normalization
├── bindings.py             mappings, structures, and construction values
├── transforms.py           declarative scalar transforms
├── cooccurrence.py         datatype-shape admissibility
├── assertions.py           ART-DECOR assertion evaluation
├── validate.py             model/config/record validation
├── conformance.py          package and CDA validation gates
├── testing.py              synthetic and authored scenarios
├── state.py                transformation fingerprints and history
└── transport.py            bounded delivery adapters
```

The `build/` package contains transitional import compatibility; new
architecture belongs in the components above.

## Setup-time data flow

Selection writes identity to `aktin.json` and creates no generated directories.
Artifact-producing commands own their output paths:

| Command | Main products |
|---|---|
| `fetch` | release cache, manifest, artifact-owner index, transaction closure |
| `build` | `model.json`, `cda.json`, diagnostics, mapping audit and proposal |
| `init-cda-mapping` | reviewed mapping bundle and lock |
| `propose-input` | site-local CSV/code proposals |
| `init-site-config` | reviewed site bundle |
| `setup-test` | isolated generated or authored fixture |

The detailed acquisition-to-mapping sequence is in
[`specification-to-mapping-pipeline.md`](specification-to-mapping-pipeline.md).

### Retrieval boundary

Retrieval discovers and freezes typed dependencies. `manifest.json` is the
release cache inventory; `closure.json` is one transaction's selected build and
mapping-evidence set. Compiler input assembly verifies paths, checksums,
identities, forms, and mandatory artifacts and does not rediscover closure.

See [`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md).

### Dataset boundary

`compile/transaction.py` produces groups, fields, occurrence chains, datatypes,
logical/formal terminology, accepted input values, and provenance without CDA
knowledge. Future targets reuse this output.

See [`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md).

### CDA boundary

`cda/compile.py` combines exact templates, reviewed overlays, the pinned
CDA/RIM graph, datatype representations, assertions, and supporting Schematron
evidence. `cda.json:targets` is the physical registry. Logical mapping
datapoints are added only after occurrence-aware mapping analysis.

Rendering consumes compiled paths, roles, order, representations, terminology,
and occurrence metadata; it does not dispatch on clinical template names.

See
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md).

### Mapping boundary

`compile/mapping.py` combines the target-neutral model, physical CDA model, and
bounded evidence graph. It emits a rich audit and concise proposal. Reviewed
mapping remains outside generated `model/`, is protected by an identity lock,
and may differ from the proposal.

See [`topics/mapping-and-construction.md`](topics/mapping-and-construction.md).

## Runtime data flow

The input root is external and explicit. Runtime accepts a reviewed mapping
file and a site bundle rather than individual flags for each JSON file.

```text
INPUT/
  -> data.ingest
  -> target-neutral normalized records
  -> validate records and configuration
  -> bindings build occurrence-aware assignments
  -> cda.render consumes compiled representations
  -> assertions evaluate the complete tree
  -> state fingerprints relevant semantics
  -> transport optionally sends the document
```

Mapping verification uses the same ingestion, validation, binding, rendering,
and assertion code in an isolated test directory, without production state or
delivery.

See
[`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md).

## Dependency direction

The intended dependency direction is:

```text
retrieval -> compiled target-neutral model
          -> target compiler -> target model
model + target model -> mapping analysis
input + reviewed configuration + compiled models -> runtime target adapter
```

Source ingestion, occurrence normalization, and state must not depend on CDA.
Target-specific rules must not leak into site input configuration. Adding a
future output target should introduce a target compiler, mapping specialization,
renderer, and conformance gate without redesigning the normalized dataset
pipeline.

## Intentional boundaries

- Generated model and test directories are rebuildable; reviewed mapping and
  site configuration have distinct owners.
- Runtime is standard-library-only; setup/build validation may use pinned Java
  tooling.
- Mapping review, site validation, and document conformance are independent
  gates.
- Transport adapters are code-defined and bounded rather than dynamically
  importable.
- Current unresolved technical and external boundaries are listed only in
  [`open-boundaries.md`](open-boundaries.md).
