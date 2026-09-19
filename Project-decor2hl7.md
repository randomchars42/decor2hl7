# Project decor2hl7

## Goal

`decor2hl7` transforms flat clinical source data into an HL7 representation
using specification information obtained from ART-DECOR. CDA is the first
target. Acquisition, dataset compilation, input normalization, validation,
occurrence handling, and state management remain target-neutral so another
target such as FHIR can reuse them.

```text
source data
    -> target-neutral dataset model
        -> CDA model + reviewed CDA mapping -> CDA document
        -> future target model + mapping    -> future output
```

ART-DECOR is a setup-time concern. Runtime consumes compiled stable models and
reviewed configuration; it does not access ART-DECOR XML or services.

The implementation is procedural, typed, unit-testable, and exposed through one
CLI. Clinical and structural semantics are explicit rules, never silent
inference from names, positions, or coincidental source content.

## Canonical knowledge

The `randomchars42/decor2hl7` repository on `main` is authoritative for code,
tests, and durable project documentation. Current rules are organised by topic
under [`docs/`](docs/index.md). Exact owner artifacts establish specification
facts; the reference workspace records one generated transaction state.

Conversations, generated outputs, commit chronology, and unmerged branches are
not decision stores. Stable `DEC-*` identifiers are indexed in
[`docs/decisions.md`](docs/decisions.md), while genuinely unresolved matters are
kept in [`docs/open-boundaries.md`](docs/open-boundaries.md).

## Workflows and ownership

The project has three distinct workflows. Their products remain separable so a
reviewed target mapping can be shared independently of a site's CSV export and
runtime operation.

### Specification and target mapping

The specification maintainer selects an exact release and transaction, fetches
the dependency closure, compiles the target-neutral dataset and target model,
reviews the generated mapping evidence, and publishes a portable mapping
bundle.

For CDA:

```text
select -> fetch -> build -> init-cda-mapping -> check-cda-mapping -> test
```

The product is `mapping/<release>/<transaction>/cda-mapping.json` plus its
identity lock and generated review guides. It contains no site CSV layout.

### Site and input configuration

The local administrator connects a deployment's source export to the
target-neutral dataset model. This workflow owns filenames, joins, CSV columns,
parsing, local code and unit aliases, occurrence keys, identifiers, timezone,
and other deployment policy.

Its products live under `site/`. They may not modify the reviewed portable
target mapping.

### Runtime and operation

Runtime combines one external input snapshot, compiled models, the reviewed
mapping, and site configuration. It ingests, normalizes, validates, maps,
renders, records change state, and optionally delivers output. Runtime does not
perform specification discovery or compilation.

## Workspace boundary

The producer owns source data outside the workspace. The workspace expresses
artifact ownership:

```text
INPUT/                             producer-owned source snapshot

WORKSPACE/
├── decor2hl7.json                 selection and reviewed model extensions
├── config/                        acquisition hints and reviewed overlays
├── spec/                          fetched release cache and closures
├── model/                         generated compiled models and evidence
├── mapping/                       portable reviewed target mapping
├── site/                          deployment-specific input configuration
├── test/                          disposable mapping verification
├── out/                           generated runtime output
└── state/                         delivery/change history
```

The release is the acquisition/cache scope. The transaction is the model,
mapping, site, test, and output scope. Sent state is transaction-scoped rather
than release-scoped.

## Project-wide invariants

- The selected transaction controls selection and usage. Exact revisions are
  never substituted or silently combined.
- Formal ART-DECOR origins, ordinary relationships, template containment, and
  editor prototypes retain distinct owner-defined meanings.
- Source, analysis, and terminology-expansion forms remain distinguishable.
- The target-neutral model preserves groups, fields, value domains, provenance,
  and complete repeat/occurrence identity.
- Logical source choices are not automatically formal codes. Lossy terminology
  bridges require an explicit reviewed rule.
- One source occurrence remains one target occurrence. Independent repetitions
  are never joined positionally.
- Mapping evidence and reviewed decisions remain separate. Unresolved and
  deliberately unmapped fields stay visible.
- Target-specific behavior such as CDA templates, `nullFlavor`, XSD structure,
  and FHIR profiles stays inside the target boundary.
- Required values come only from owner constraints, mapped data, reviewed
  defaults, explicit site requirements, or compiler-owned production roles.
- Missing auxiliary evidence may degrade safely; exact identity contradictions
  and mandatory selected inputs fail.

The detailed current contracts are linked from
[`docs/index.md`](docs/index.md).

## Change and release discipline

A semantic or architectural change updates its topic documentation, affected
open boundary, tests, and user-facing behavior together. Stable decision IDs are
added only when durable mapping or recovery metadata needs a reference.

Before a release, regenerate the companion reference workspace for its selected
identity, review the accepted mapping-field and coverage-baseline changes with
`make baseline`, then run `make check`. Generated counts and diagnostics belong
to those artifacts and fixtures rather than copied prose.
