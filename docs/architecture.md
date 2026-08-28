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
               compile/transaction.py compile/cda.py
                         │                │
                         ▼                ▼
                     model.json        cda.json
                         └───────┬────────┘
                                 ▼
                       compile/mapping.py
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
    retrieval/
        client.py       IPv4-scoped HTTP client
        catalog.py      release/transaction discovery + keys
        fetch.py        recursive acquisition, manifest, closure
        references.py   typed dependencies and dependency roles
        resolution.py   link/prefix/owner inference and probe ordering
        artifacts.py    identities, forms, dependency roles
        xml.py          XML repair/helpers
    compile/
        artifacts.py    build-ready compiler inputs
        transaction.py source + analysis → model.json
        terminology.py logical/formal domain accessors
        cda.py          exact templates/SPEC → cda.json
        mapping.py      decisions → audit + proposal
        structural.py   cardinality/terminology → structural rules
        reports.py      readable effective CDA + mapping guide
    build/              compatibility imports for one release
    data.py             CSV joining/normalization
    bindings.py         occurrence fan-out/coalescing + CDA assignments
    validate.py         config + record/source-constraint validation
    transforms.py       small declarative mapping transforms
    assertions.py       ART-DECOR assert evaluator + Schematron output
    cda.py              CDA rendering from cda.json
    testing.py          synthetic fixture generation + isolated mapping test
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
- `init-cda-mapping` creates the shareable mapping bundle and identity lock.
- `propose-input` and `init-site-config` create local input/code/site scaffolds.
- `setup-test` creates an isolated synthetic fixture; `test-cda-mapping` writes
  only below that fixture (or its explicit `--out`).
- `transform` creates `out/<release>/<transaction>/...`.

The CSV input root is external to the workspace. `propose-input`, `check-input`, `transform`, and `run` accept `--input PATH`; otherwise they resolve the optional deployment default `aktin.json: input.directory`. `build` and `check` deliberately do not touch source CSVs. Relative source filenames in `site.json` are resolved below this input root.

Release-wide downloads are shared; transaction-specific products are isolated.
The workspace also expresses ownership: `mapping/` is a portable specification
product, `site/` is deployment configuration, and `test/` is disposable
verification input/output. `config/` is reserved for acquisition-wide settings
such as repository source hints.

Runtime commands accept bundle overrides rather than a separate flag for every
JSON file. `--cda-mapping` selects one reviewed mapping file;
`--site-config` selects a directory containing `site.json`,
`csv-mapping.json`, and `codes-mapping.json`. The default workspace layout may
share `site.json` across transactions within a release, while an explicit
bundle keeps all three files together for portability.

## Fetch closure

`fetch.py` uses typed references (`dataset`, `template`, `valueset`,
`codesystem`, `concept`) and iterates until closure or the request cap.

Important rules retained from the prototype:

1. Prefer containing datasets over individual concepts.
2. Distinguish template `include` from value-set `include` by XML context.
3. Follow `include`, `contains`, and template `SPEC`/`VERSION`/`COPY` links.
4. Use longest OID ownership, explicit reference links and the exact artifact
   owner cache, in that order, before probing repositories.
5. Treat empty successful XML responses as not-found; do not confuse parse
   failure with absence.
6. Cache both successes and settled failures.
7. Fetch a whole unpinned project only for the selected/main project; never for
   external building-block repositories.
8. Keep unpinned project data evidence-only, and recursively follow only external
   evidence relevant to the selected transaction closure.
9. Freeze dynamically resolved external revisions in the manifest.
10. Count the fetch safety cap in actual recursive HTTP attempts.
11. Record extensional CodeSystems as display evidence without requesting them;
    fetch a CodeSystem as required only for intensional expansion.
12. Fetch the representing template explicitly even if it appears in live
    project evidence.

`manifest.json` answers “what is cached for this release?”; transaction
`closure.json` answers “which cached resources belong to this transaction?” It
also separates crawler settlement (`crawl_complete`) from availability of the
selected transaction pair (`build_ready`) and records unavailable recursive
dependencies as degraded resources.

## Artifact and terminology contracts

Every compiler artifact retains requested and resolved identity, dependency
role, resolution provenance and all available source/analysis/expansion forms.
A static identity mismatch is an error. Optional usable forms remain accessible
even when another optional representation is unavailable.

The transaction source defines selected concepts, transaction cardinality
overrides and direct terminology associations. The analysis form supplies
resolved definitions and containment. The compiler validates the pair and
records contained additions separately.

`logical_domain` records dataset choices, `formal_terminology` records the exact
transaction ValueSet binding and members, and `terminology_associations` retains
direct links with their source concept IDs. `accepted_values` is the executable
domain. When a formal binding exists, only known formal members are executable;
an unavailable or partly expanded binding is explicitly incomplete and does not
fall back to logical-only labels.

The compiler boundary separates unavailability from contradiction. Missing
auxiliary datasets, terminology and nested templates are omitted and listed in
`build-diagnostics.*`. A successful artifact with a mismatched exact identity or
missing cached file is a contradiction and remains fatal. The selected
transaction source/analysis pair and the representing CDA document template are
also mandatory. This permits review of partial source material without silently
claiming constraints or terminology that were not retrieved.

## CDA compilation

`cda.json` is the runtime boundary. `targets` contains physical named template
constraints; `datapoints` contains the logical writable interface established
after mapping. Most logical datapoints point to a same-named physical target.
Discriminated repetitions instead expose separate names such as
`Pupilsize_right.value` and `Pupilsize_left.value`, both linked to the physical
repeatable `Pupilsize.value` constraint and carrying their side discriminator.
The same logical datapoints are used by configuration, reports, validation and
runtime assignment. ART-DECOR identifiers are provenance, not runtime addresses.

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

Only fetched build-template forms participate in compilation. Live project
evidence cannot fill a missing dependency. Static flexibility is exact; dynamic
references resolve to a frozen manifest identity.

## Mapping evidence

Editable JSON stores only selections. `mapping-audit.json` stores the structured
decision record, and both Markdown views are produced from the same analysis.
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

`cda-mapping.json` version 5 separates scalar transforms, structural bindings,
and CDA completion policy. The compiler emits only rules supported by explicit
cardinality, terminology, and template evidence:

- `for_each` preserves one source-group occurrence as one CDA occurrence;
- `fan_out` turns sibling fields such as right/left measurements into separate
  logical CDA datapoints and occurrences, retaining their shared physical
  target and writing the discriminator required by the target ValueSet;
- `coalesce` lets equivalent singleton fields share a target, using
  `equal_or_error` unless a different policy is explicitly configured;
- `mode: "fallback"` remains available for an explicitly configured
  source-dependent fallback and fills each occurrence independently;
- `defaults.required_unmapped` fills an otherwise empty required leaf in an
  active template branch with `nullFlavor="NI"` by default;
- `target_defaults` records reviewed target-specific completion, such as
  `nullFlavor="UNK"` for the required diagnosis onset that this transaction does
  not provide. A real mapped onset wins in its own occurrence.

Completion rules do not activate optional branches. They cannot nullify
attributes, optional targets, complex elements, or mandatory constraints that
prohibit null flavors. Thus deliberately leaving a dataset-to-CDA field mapping
empty does not invalidate the whole mapping when the corresponding required CDA
leaf can legally carry a null flavor; optional leaves remain absent.

The compiler does not embed AKTIN paths, OIDs, or side codes in the runtime. A
generated rule carries the resolved source paths, targets, and terminology
members, so the same binding engine can execute another transaction/template.

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

CSV mapping entries may be either the compact `SOURCE:COLUMN` form or an object
with `source`, `column`, optional `parse_as`, and optional scalar `transform`.
This supports representation changes at the input boundary without changing the
transaction model—for example a Boolean leading-diagnosis column can become
sequence number `1` for true and be omitted for false.

`build` has no input argument and never inspects CSVs. CSV/code proposal generation is a separate explicit `propose-input` step. The proposal step may inspect column names and observed coded values, but it does not infer relationships between CSV sources; joins/cardinalities remain explicit configuration.

## User-facing mapping verification

`check-cda-mapping` validates the compiled CDA, structural bindings, target
compatibility, and `mapping-lock.json` without requiring site CSV mappings.
This is the review gate for the shareable specification product.

`setup-test` derives deterministic CSV columns from `model.json`. Scalar fields
go to `cases.csv`; each distinct repeat chain gets a generated `1:n` source with
explicit occurrence-key columns. The fixture configuration uses valid synthetic
identifier roots and model-derived terminology aliases. `expected.json` freezes
the selected release/transaction and model/CDA/mapping hashes and records mapped
and unmapped fields.

`test-cda-mapping` reads that fixture through the ordinary production modules:
`data.ingest` → record validation → structural bindings → CDA rendering and
ART-DECOR assertions. It writes generated XML, `results.json`, and `results.md`
to the test result directory. It intentionally bypasses production change
state and transport. Coverage means a mapped datapoint survived normalization
and participated in the tested record; it does not claim that a single
synthetic document can exercise mutually exclusive or conditional branches.

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
