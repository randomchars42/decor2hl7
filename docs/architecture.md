# Architecture

## Main boundary

ART-DECOR complexity is a setup-time concern. Runtime never parses ART-DECOR
XML.

```text
                  ART-DECOR
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      catalog.py             fetch.py
   release/transaction      recursive closure
       selection                 │
                                 ▼
                              spec/
                         ┌───────┴────────┐
                         ▼                ▼
                   build/model.py   build/target.py
                         │                │
                         ▼                ▼
                     model.json        cda.json
                         └───────┬────────┘
                                 ▼
                         build/mapping.py
                                 │
                         proposals + reports

external INPUT/ CSV → data.py → validate.py → cda.py → transport.py
            │ structured 1:n occurrences      │
            └──────────── state.py ────────────┘
```

## Package structure

```text
src/decor2hl7/
    cli.py
    workspace.py
    decor/
        client.py       IPv4-scoped HTTP client
        catalog.py      release/transaction discovery + keys
        fetch.py        recursive acquisition, manifest, closure
        xml.py          XML repair/helpers
    build/
        model.py        transaction/datasets → model.json
        target.py       templates/SPEC → compiled cda.json
        mapping.py      proposals + detailed evidence reports
    data.py             CSV joining/normalization
    validate.py         config + record/source-constraint validation
    transforms.py       small declarative mapping transforms
    assertions.py       ART-DECOR assert evaluator + Schematron output
    cda.py              CDA rendering from cda.json
    state.py            fingerprint/change/sent history
    transport.py        receiver transport
```

## Selection and paths

Selection is state, not filesystem behavior:

```text
list-versions         → discover releases
set-version KEY       → write aktin.json, clear transaction
list-transactions     → discover transactions in selected release
set-transaction KEY   → write aktin.json
```

None of these commands creates release/transaction artifact paths.

Artifact-producing commands own their directories:

- `fetch` creates `spec/<release>/...` and transaction `closure.json`.
- `build` creates `model/<release>/<transaction>/...`.
- `config` creates missing user scaffolds.
- `transform` creates `out/<release>/<transaction>/...`.

The CSV input root is external to the workspace. `check-input`, `transform`, and `run` accept `--input PATH`; otherwise they resolve the optional deployment default `aktin.json: input.directory`. `check` deliberately does not touch source CSVs. Relative source filenames in `site.json` are resolved below this input root.

Release-wide downloads are shared; transaction-specific products are isolated.

## Fetch closure

`fetch.py` uses typed references (`dataset`, `template`, `valueset`, `concept`)
and iterates until closure or the request cap.

Important rules retained from the prototype:

1. Prefer containing datasets over individual concepts.
2. Distinguish template `include` from value-set `include` by XML context.
3. Follow `include`, `contains`, and template `SPEC`/`VERSION`/`COPY` links.
4. Use ProjectIndex ownership by longest OID prefix before guessing a repository.
5. Treat empty successful XML responses as not-found; do not confuse parse
   failure with absence.
6. Cache both successes and settled failures.
7. Fetch a whole unpinned project only for the selected/main project; never for
   external building-block repositories.
8. Keep unpinned project data evidence-only, and recursively follow only external
   evidence relevant to the selected transaction closure.
9. Freeze dynamically resolved external revisions in the manifest.
10. Count the fetch safety cap in actual recursive HTTP attempts.

`manifest.json` answers “what is cached for this release?”; transaction
`closure.json` answers “which cached resources belong to this transaction?”

## CDA compilation

`cda.json` is the runtime boundary. It contains named writable targets plus the
compiled XML constraint tree. ART-DECOR identifiers are provenance, not runtime
addresses.

`SPEC` is recursive constraint refinement, not tree concatenation. Matching
child constraints inherit omitted parent properties and override explicit ones;
parent-only prototype choices are dropped at every depth. A specialized
structural node with the same ART-DECOR element ID replaces an inherited
`contains` target; this prevents legacy and replacement branches from being
emitted together.

Fixed text/attributes are executable constraints rather than writable data
targets. `NP` nodes are prohibited. Named targets are renderable only when they
resolve to exactly one physical node; ambiguity is retained as provenance but is
a configuration/runtime error when selected. `validate.verify_compiled_cda()`
checks these invariants before transformation.

Pinned/downloaded template definitions are primary. Historical definitions from
`project-evidence.xml` are fallback-only and are ignored when newer than the
selected release date.

## Mapping evidence

Editable JSON stores only selections; rich evidence stays in Markdown.
Evidence includes:

- direct/lineage-mediated `templateAssociation` (`TA`)
- version-tolerant TA resolution
- `SPEC`, `INHERIT`, reverse lineage, `ORIGINAL`, `ADAPT`, etc.
- direct legacy `implementation/@xpath` declarations (`XPATH`)
- guarded template-name (`NAME`) bridge
- exact terminology/value-set/datatype combinations (`TERM`, `VS`, `DT`)
- exact unique element-description (`DESC`) bridge as weak fallback evidence
- contextual (`CTX`) placement

Evidence strength and executability are separate. A formal link may remain in the
report even when datatype/unit/cardinality/payload rules show that it needs a
semantic transform. Shared physical targets are also retained as evidence but are
not written into the executable proposal without explicit merge/repetition
semantics. Strong mappings win; weaker alternatives remain visible and never
downgrade the selected mapping.

Identity-style lineage may enrich omitted dataset constraints. `ADAPT` and other
derivation relationships are deliberately not treated as automatic identity
inheritance, because the adaptation may have changed the value domain or meaning.
Identity enrichment is transitive for `SPEC`/`INHERIT`/`ORIGINAL`/`EQUIV`/`COPY`/
`VERSION` and fills omitted value-domain metadata only; dataset-context
cardinality is never inherited through lineage.

Mapping values can be direct target strings or declarative rule objects. A field
may control more than one target (for example Tetanusschutz `negationInd` and
`nullFlavor`) without introducing target-specific renderer code.

## Assertions and nested occurrences

Effective `<assert>` and `<let>` constraints are carried through recursive SPEC
refinement. The renderer records each instantiated assertion context and evaluates
it only after the complete CDA tree exists, so document-global `//` tests work.
Error failures or unsupported error expressions abort emission; warning failures
are returned as diagnostics. The same original expressions are emitted as
`cda-assertions.sch`. The independent source verifier checks that assertions on
effective ART-DECOR source elements survive compilation.

Dataset fields record `repeat_chain` from outer to inner repeating groups. CSV
configuration can bind each level to an `occurrence_keys` column. Normalized
records therefore form nested keyed occurrence trees, and CDA targets record
repeating XML ancestors. A mapping is executable only when dataset and CDA repeat
depths agree; rendering carries the occurrence tuple through every repeated CDA
ancestor instead of flattening lists.

## Input boundary

The producer owns the CSV directory; decor2hl7 never requires another program to copy data into a workspace-owned `raw/` directory. One command invocation treats the supplied input directory as one coherent snapshot.

`data.py` receives the resolved external root explicitly. Source definitions remain logical (`cases`, `medications`, ...) and `site.json` supplies relative filenames/cardinality/occurrence keys. The physical input path is excluded from transformation fingerprints, so moving an otherwise identical snapshot does not create a correction.

`build` does not gain an input command-line option. It uses the optional configured default only to improve CSV/code proposals; model/CDA compilation does not depend on source CSV availability.

## State

Sent-state is independent of release but scoped by transaction OID:

```text
state key = <transaction OID>::<raw record key>
```

Therefore:

- the same case may be emitted independently by different transactions;
- corrected input increments the document version;
- occurrence order/value changes are detected, while CSV line-number changes are
  ignored;
- a material change in transformation/spec/configuration semantics also changes
  the fingerprint even when the clinical values are unchanged;
- stale unsent artifacts are removed when a newer, invalid, reverted, or absent
  source state supersedes them.

## Current intentional boundaries

- Generic CDA narrative remains minimal; section-specific narrative can be
  added behind `cda.py` without changing mappings.
- Nested repetition requires stable occurrence keys when more than one independent
  level/source is involved; positional guessing remains intentionally unsupported.
- `transport.py` is generic HTTP POST until the receiver protocol is specified.
