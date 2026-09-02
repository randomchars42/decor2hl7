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
               compile/transaction.py cda/compile.py
                         │                │
                         ▼                ▼
                     model.json        cda.json
                         └───────┬────────┘
                                 ▼
                       compile/mapping.py
                                 │
                         proposals + reports

external INPUT/ CSV → data.py → validate.py → cda/render.py → transport.py
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
        mapping.py      decisions → audit + proposal
        structural.py   cardinality/terminology → structural rules
        reports.py      readable effective CDA + mapping guide
    cda/
        core.py         pinned CDA/RIM + HL7 V3 XSD definition graph
        datatypes.py    scalar XML serialization policy
        model.py        typed node/value-target/value-representation IR
        compile.py      templates + datatypes → effective cda.json
        render.py       compiled value representations → CDA XML
    build/              transitional imports for one release
    data.py             CSV joining/normalization
    bindings.py         occurrence fan-out/coalescing + CDA assignments
    validate.py         config + record/source-constraint validation
    transforms.py       small declarative mapping transforms
    assertions.py       ART-DECOR assert evaluator + Schematron output
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
13. Treat valid dependency analysis XML as a complete cache hit even when its
    optional source sidecar is absent; both selected transaction forms remain
    mandatory.
14. In `--offline` mode, perform closure discovery from cached files without any
    HTTP attempt and record uncached references as retryable unavailable
    dependencies.
15. Provisionally, consult exact catalog entries for package-local `builtin`
    supplements and cited `waiver` decisions. Builtins verify their package
    checksum and can be materialized offline; waivers are settled but remain
    non-successful and degraded. This phase is open for review under `DEC-012`.

`manifest.json` answers “what is cached for this release?”; transaction
`closure.json` answers “which cached resources belong to this transaction?” It
also separates crawler settlement (`crawl_complete`) from availability of the
selected transaction pair (`build_ready`) and records unavailable recursive
dependencies as degraded resources.

`manifest.json` is reconstructible metadata rather than the sole index of
deterministically named cache files. If it is deleted, `fetch` validates and
reuses existing expected files, recalculates their checksums and rewrites the
manifest. Missing, invalid, modified-against-a-known-checksum or wrong-revision
files are fetched again when online. Bundled supplements restore their external
origin and completeness metadata from the durable package catalog.

## Artifact and terminology contracts

Every compiler artifact retains requested and resolved identity, dependency
role, resolution provenance and all available source/analysis/expansion forms.
A static identity mismatch is an error. Optional usable forms remain accessible
even when another optional representation is unavailable.

Dependency analysis forms determine cache/build availability. Dependency source
forms add provenance and mapping evidence but are not synchronously backfilled
when analysis is already cached. The selected transaction source/analysis pair
is separately mandatory.

The transaction source defines selected concepts, transaction cardinality
overrides and direct terminology associations. The analysis form supplies
resolved definitions and containment. The compiler validates the pair and
records contained additions separately.

`logical_domain` records dataset choices, `formal_terminology` records the exact
transaction ValueSet binding and members, and `terminology_associations` retains
direct links with their source concept IDs. An owned inline `conceptList` is
also retained as `coded_domain`, including its identifier, member count and
whether it is enumerated, referenced or explicitly unconstrained. This prevents
an intentional empty/open domain from being confused with an unavailable
external ValueSet. `accepted_values` is the executable source domain. When a
formal binding exists, only known formal members are executable; an unavailable
or partly expanded binding is explicitly incomplete and does not fall back to
logical-only labels.

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

Compilation first resolves template relationships and specialization, then
derives the effective CDA model inventory. `cda/core.py` indexes the fetched
pinned XSD graph and recursively follows structural classes, datatype aliases
and inheritance; `cda/datatypes.py` contains only the scalar XML serialization
policy. Explicit ART-DECOR constraints overlay the legal model structure.
Structural targets remain navigation, evidence and repeat anchors. Scalar mapping
sees only targets whose compiled
`value_representation` marks them writable. The renderer executes that
representation and does not contain a second datatype dispatch table.

ART-DECOR choices are transparent structural constraints. Predicate variants
retain distinct identities but overlay one underlying XSD particle. Abstract
`ANY` values expose typed scalar alternatives with compiled `xsi:type`
representations; mapping chooses a branch only when datatype and context leave
one legal endpoint.

Compiler-assigned runtime roles belong to concrete compiled nodes, not to
clinical path logic in the renderer. When a reusable include gives one logical
target several physical locations, that target remains non-writable. A role
such as the configured custodian organization identifier/name is delivered to
its exact compiled physical occurrence, so it neither activates nor populates
the same include under author, recipient or participant branches.

Generated target identifiers remain flattened and stable for configuration and
runtime compatibility. They are identifiers, not an alternate XML hierarchy.
The effective unflattened hierarchy remains available in each target's `path`
and physical `locations` and in `cda-expanded-readable.xml` / `.md`.

Before datatype expansion, `cda/core.py` loads the pinned normative CDA R2 XSD
set cached by `fetch`. It indexes structural definitions, follows XSD extension
inheritance, and materializes omitted CDA/RIM children and attributes. Explicit
ART-DECOR constraints overlay these generic nodes. `include` and `contains`
wrappers are transparent to the XML content model: their element descendants
satisfy a parent's CDA/RIM particles while the wrappers remain in the compiled
tree for template identity, occurrence metadata and provenance. The compiler
therefore never materializes a generic sibling for a structural child already
provided through one of those wrappers. One compiled path can
therefore cross an ART-DECOR constraint, a CDA structural class, an HL7
datatype, and its writable XML representation without class knowledge in
mapping or rendering.

`SPEC` is recursive constraint refinement, not tree concatenation. Matching
child constraints inherit omitted parent properties and override explicit ones;
parent-only prototype choices are dropped at every depth. A specialized
structural node with the same ART-DECOR element ID replaces an inherited
`contains` target; this prevents legacy and replacement branches from being
emitted together.

Fixed text/attributes are executable constraints rather than writable data
targets. `NP` nodes are prohibited. A target is writable only when its datatype
defines a value representation and it resolves to exactly one unfixed,
non-prohibited physical node. Ambiguity and structural-only targets remain as
provenance/evidence but are configuration/runtime errors when selected as scalar
destinations. `validate.verify_compiled_cda()` checks these invariants before
transformation.

Required coded construction values may be compiled from neutral ART-DECOR
examples only after exact template/path scoping and unique validation against
the exact bound ValueSet revision or explicit allowed-code set. The value and
STRONG `template-example` provenance stay in the compiled model; an explicit
assignment always has precedence. Expanded coded datatypes also identify their
source-wording companion through a compiled content role, allowing normalized
`raw` text to populate that child without renderer knowledge of CD/CE layout.

Names used by ART-DECOR constraints can contain XPath predicates that select a
sibling constraint. Predicates remain part of compiled path identity and
evidence, but are removed when the renderer turns a selected node name into an
XML QName.

Only fetched build-template forms participate in compilation. Live project
evidence cannot fill a missing dependency. Static flexibility is exact; dynamic
references resolve to a frozen manifest identity.

## Mapping evidence

Editable JSON stores only selections. `mapping-audit.json` stores the structured
decision record, and both Markdown views are produced from the same analysis.
Evidence includes:

- direct/lineage-mediated `templateAssociation` (`TA`)
- ART-DECOR `staticAssociations/origconcept` links (`STATIC_ASSOC`)
- version-tolerant TA resolution
- `SPEC`, `INHERIT`, reverse lineage, `ORIGINAL`, `ADAPT`, etc.
- direct legacy `implementation/@xpath` declarations (`XPATH`)
- guarded template-name (`NAME`) bridge
- exact terminology/value-set/datatype combinations (`TERM`, `VS`, `DT`)
- exact unique element-description (`DESC`) bridge as weak fallback evidence
- unique contextual ART-DECOR role/description and compiled content role
- unique choice branch or datatype descendant inside a mapped container
- nearest compatible value at an already-derived `for_each` occurrence boundary
- contextual (`CTX`) placement

Evidence strength and executability are separate. A formal link may remain in the
report even when datatype/unit/cardinality/payload rules show that it needs a
semantic transform. Shared physical targets are also retained as evidence but are
not written into the executable proposal without explicit merge/repetition
semantics. Strong mappings win; weaker alternatives remain visible and never
downgrade the selected mapping.

A static association can name a constraint from a legacy or profile template
instead of the active template node. The mapper resolves that constraint to its
unique owning CDA/RIM XSD class and particle, then projects the association to
the same compiled structural slot in the active branch. Projection is
executable only when the slot and the nearest occurrence inside the already
mapped context are both unique. This is structural identity supplied by the
pinned model, not a leaf-name match; ambiguous slots remain report-only
evidence.

The XSD graph also carries `complexType/@mixed`. A mixed-content root receives
an element-text value representation during compilation, so mappings such as a
profile-associated manufactured-material name remain renderer-independent.
When a coded source has an explicit open target code system but no enumerated
ValueSet, the proposal carries a declarative `code_system` transform that
normalizes the source code and supplies that code-system OID.

An explicitly unconstrained source coded domain has a different contract. It
may map inside an already established container only when exactly one compatible
CDA descendant binds an exact ValueSet revision with an `OTH` exception and has
a datatype-derived `coded_original_text` companion. The declarative
`coded_fallback` transform preserves an exact admitted code/code-system pair;
all other values become `nullFlavor="OTH"` while retaining source wording for
the companion text. ValueSet membership, structure and datatype roles are
compiled evidence; the renderer has no domain- or template-specific branch.

Identity-style lineage may enrich omitted dataset constraints. `ADAPT` and other
derivation relationships are deliberately not treated as automatic identity
inheritance, because the adaptation may have changed the value domain or meaning.
Identity enrichment is transitive for `SPEC`/`INHERIT`/`ORIGINAL`/`EQUIV`/`COPY`/
`VERSION` and fills omitted value-domain metadata only; dataset-context
cardinality is never inherited through lineage.

Mapping values can be direct target strings or declarative rule objects. A field
may control more than one target (for example Tetanusschutz `negationInd` and
`nullFlavor`) without introducing target-specific renderer code.

`cda-mapping.json` version 6 separates scalar transforms, structural bindings,
and CDA completion policy. The compiler emits only rules supported by explicit
cardinality, terminology, and template evidence:

- `for_each` binds one source-group repeat dimension to an explicit CDA repeat
  node. Unbound target repeat ancestors are rendered as one shared container;
  for example, repeated medication records bind to section `entry` while the
  enclosing medication section is emitted once;
- `repeat_by_discriminator` turns sibling fields such as right/left measurements
  into separate logical CDA datapoints and occurrences only when the target has
  one additional repeat level, a required coded discriminator, an exact bound
  ValueSet revision and a unique terminology-supported source/member match.
  Schematron uniqueness constraints are retained as additional evidence. The
  same runtime rule may be derived for category booleans when an exact neutral
  example in the effective template uniquely matches the source category,
  supplies an admitted discriminator member and exposes `@negationInd` as the
  boolean representation. Such a branch uses inverse negation and never copies
  the source disorder code into the discriminator. If one direct coded source
  already supplies an equal discriminator, the occurrences are coalesced by
  exact code and code system;
- `coalesce` lets equivalent singleton fields share a target, using
  `equal_or_error` unless a different policy is explicitly configured;
- `mode: "fallback"` remains available for an explicitly configured
  source-dependent fallback and fills each occurrence independently;
- `mode: "presence"` lets a boolean activate one optional statement only when
  exact terminology identifies the template and ART-DECOR fixes its complete
  clinical payload. False omits it. The structural target does not become a
  scalar writable endpoint;
- `defaults.required_unmapped` fills an otherwise empty required leaf in an
  active template branch with `nullFlavor="NI"` by default;
- `target_defaults` records reviewed target-specific completion, such as
  `nullFlavor="UNK"` for the required diagnosis onset that this transaction does
  not provide. A real mapped onset wins in its own occurrence.

Compiled datatype targets may also carry `non_null_requires`. Proposal
generation treats a dependent component as review-only until the required
element or a descendant is mapped; configuration validation rejects an
incomplete reviewed selection, and rendering checks companion presence for each
populated occurrence after runtime completion. This is compiled datatype
policy, not a medication/template/path special case.

Completion rules do not activate optional branches. They cannot nullify
attributes, optional targets, complex elements, or mandatory constraints that
prohibit null flavors. Thus deliberately leaving a dataset-to-CDA field mapping
empty does not invalidate the whole mapping when the corresponding required CDA
leaf can legally carry a null flavor; optional leaves remain absent.

The generated pupil rule therefore uses `targetSiteCode` values `R` and `L`
from AKTIN ValueSet `1.2.276.0.76.11.48` and code system
`1.2.276.0.76.3.1.195.5.48`; it does not substitute SNOMED eye concepts.
Legacy reviewed `fan_out` remains runtime-compatible and is migrated only when
the generated rule proves identical source and physical-target identity.

The compiler does not embed AKTIN paths, OIDs, or side codes in the runtime. A
generated rule carries the resolved source paths, targets, and terminology
members, so the same binding engine can execute another transaction/template.
Occurrence rules are derived provisionally before scalar candidate selection,
allowing a candidate to become executable when the established `for_each`
alignment accounts for its otherwise incompatible repeated ancestors.
After sibling scalar mappings establish an additional `for_each`, one bounded
second pass may select the unique nearest compatible value for a field directly
owned by that repeated source group. This cannot project nested group fields or
choose between equally near targets.

Physical ART-DECOR source identity uses template id, effective date, element id
and template-local path. Revisionless/path and element-id-only indexes remain
useful tolerant semantic evidence, but cannot identify a physical constraint
alone because one template may reuse an id in distinct sibling branches.

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

Synthetic mapping fixtures vary repeated integer/count/ordinal values by
occurrence within model bounds. This exercises order/sequence semantics without
manufacturing duplicate discriminator values such as several sequence-1
diagnoses.

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
