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

external CSV snapshot + site configuration
   -> ingest -> normalize -> validate -> bind -> render -> transport -> state

optional ODBC or SQLite source
   -> bounded extraction -> atomic CSV snapshot -> the same runtime pipeline
```

`model.json` is target-neutral. `cda.json` is the current physical target model.
An optional reviewed `model_extensions` block in root `decor2hl7.json` is
compiled into the former only after collision, parent, cardinality, provenance,
and exact-terminology checks. Target assignments remain in the portable mapping.
`cda-mapping.json` is the portable reviewed bridge between them. Site input
configuration and runtime state are separate products.

The rules governing each boundary are documented by topic in
[`index.md`](index.md). This page records component ownership and data flow,
not a second copy of those semantic rules.

## Package structure

```text
src/decor2hl7/
├── cli.py                  command parsing and specification/setup commands
├── runtime.py              execution, pending delivery and run orchestration
├── contracts.py            checked stable data shapes and named runtime bundle
├── runtime_config.py       selected runtime files and configuration paths
├── bundle.py               shared exact mapping-lock admission
├── pending.py              typed, validated pending document metadata
├── ui.py                   terminal output
├── hashing.py              stable JSON and file digests
├── occurrences.py          shared sparse occurrence lookup and packing
├── workspace.py            selection and workspace paths
├── i18n.py                 locale loading, validation, and protected terminology
├── locales/                packaged stable-ID English and German catalogs
├── text.py                 target-neutral matching normalization
├── value_format.py         normalized quantity/range presentation structure
├── xmlnames.py             namespace constants without source-parser coupling
├── retrieval/              ART-DECOR acquisition and closure
│   ├── api.py              supported operations and URL construction
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
│   ├── structural.py       generated occurrence rules
│   ├── schematron.py       bounded supporting evidence
│   ├── mapping.py          separate candidate, admission and report/audit stages
│   ├── site.py             site CSV and input-code proposals
│   └── reports.py          readable generated products
├── cda/                    CDA target implementation
│   ├── art_decor.py        owner-grammar classification
│   ├── core.py             CDA/RIM XSD graph
│   ├── datatypes.py        scalar representation policy
│   ├── model.py            typed physical target IR
│   ├── extensions.py       reviewed exact overlays
│   ├── compile.py          effective CDA compilation
│   ├── terminology.py      target binding enforcement
│   ├── semantics.py        CDA value compatibility
│   ├── parity.py           published/compiled endpoint comparison
│   ├── tree.py             shared compiled-tree indexing and locations
│   ├── narrative.py        checked section-narrative rules and presentation IR
│   └── render.py           representation-driven XML output
├── domain.py               target-neutral dataset value domains
├── data.py                 CSV ingestion and occurrence normalization
├── source.py               bounded ODBC/SQLite extraction and snapshot publication
├── bindings.py             mappings, structures, and construction values
├── transforms.py           declarative scalar transforms
├── cooccurrence.py         datatype-shape admissibility
├── assertions.py           ART-DECOR assertion evaluation
├── validate.py             model/config/record validation
├── conformance.py          package and CDA validation gates
├── testing.py              synthetic and authored scenarios
├── state.py                SQLite lineage, delivery history, runs, and locking
└── transport.py            bounded delivery adapters
```

## Setup-time data flow

Selection writes identity to `decor2hl7.json` and creates no generated
directories.
Artifact-producing commands own their output paths:

| Command | Main products |
|---|---|
| `fetch` | release cache, manifest, artifact-owner index, transaction closure |
| `build` | `model.json`, `cda.json`, diagnostics, mapping audit, proposal, and `cda-mapping.proposed.md` |
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

`compile/site.py` separately owns suggestions based on site-local CSV headers
and observed input values. This keeps the portable dataset-to-CDA mapping
workflow independent of site data.

See [`topics/mapping-and-construction.md`](topics/mapping-and-construction.md).

## Runtime data flow

The input root is external and explicit. It may be producer-supplied or an
immutable snapshot created by the built-in ODBC or SQLite source adapter.
Runtime accepts a reviewed mapping file and a site bundle rather than individual flags for
each JSON file.

```text
ODBC or SQLite source (optional)
  -> source.extract -> atomically published INPUT/

INPUT/
  -> data.ingest
  -> target-neutral normalized records
  -> validate records and configuration
  -> bindings build occurrence-aware assignments
  -> cda.render consumes compiled representations
  -> assertions evaluate the complete tree
  -> state fingerprints relevant semantics and selects the next version
  -> transport optionally publishes or sends the document
  -> SQLite commits delivery state and CDA lineage
```

Mapping verification uses the same ingestion, validation, binding, rendering,
and assertion code in an isolated test directory, without production state or
delivery.

See
[`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md).

## Checked data contracts

`contracts.py` defines the shared serialized shapes for dataset fields/groups,
CDA nodes/targets, input and target mappings, site configuration and normalized
occurrences. Runtime loading validates these shapes before bundle admission.
`RuntimeBundle` names its six products explicitly instead of relying on tuple
positions. Normalization checks its resulting records at the owning boundary.

These types describe the internal format, not the names or membership of a
particular specification. New datapoints, template identities and terminology
members remain data. Additional non-executable owner metadata is retained as
JSON; executable semantics remain checked by their owning validators. The
contract readers preserve serialized values and do not add defaults, rename
keys or migrate formats.

## Dependency direction

The intended dependency direction is:

```text
retrieval -> compiled target-neutral model
          -> target compiler -> target model
model + target model -> mapping analysis
input + reviewed configuration + compiled models -> runtime target adapter
```

Source extraction, ingestion, occurrence normalization, and stream revision
state must not depend on CDA. CDA document and replacement identities are
target artifact metadata attached to each committed version.
Target-specific rules must not leak into site input configuration. Adding a
future output target should introduce a target compiler, mapping specialization,
renderer, and conformance gate without redesigning the normalized dataset
pipeline.

Output localization is a presentation boundary. The selected output language
is threaded into Markdown renderers and CLI presentation; semantic JSON,
mapping locks, runtime fingerprints, and CDA narrative language do not depend
on it. Setup-time source verification and endpoint parity live under `cda/`
rather than runtime-oriented `validate.py`.

## Intentional boundaries

- Generated model and test directories are rebuildable; reviewed mapping and
  site configuration have distinct owners.
- CSV and SQLite runtime use the standard library. ODBC extraction optionally
  uses `pyodbc`; setup/build validation may also use pinned Java tooling.
- Mapping review, site validation, and document conformance are independent
  gates.
- Transport adapters are code-defined and bounded rather than dynamically
  importable.
- Current unresolved technical and external boundaries are listed only in
  [`open-boundaries.md`](open-boundaries.md).
