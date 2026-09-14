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

The stage-by-stage setup-time path from fetched ART-DECOR XML through rule
composition, `model.json`, `cda.json`, mapping evidence, and the reviewed
mapping bundle is documented in
[`specification-to-mapping-pipeline.md`](specification-to-mapping-pipeline.md).

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
        schematron.py   bounded template/datatype Schematron evidence
        transaction.py source + analysis → model.json
        terminology.py logical/formal domain accessors
        mapping.py      decisions → audit + proposal
        structural.py   cardinality/terminology → structural rules
        reports.py      readable effective CDA + mapping guide
    cda/
        art_decor.py    exhaustive owner-grammar construct classification
        core.py         pinned CDA/RIM + HL7 V3 XSD definition graph
        datatypes.py    scalar XML serialization policy
        model.py        typed node/value-target/value-representation IR
        compile.py      templates + datatypes → effective cda.json
        render.py       compiled value representations → CDA XML
    build/              transitional imports for one release
    data.py             CSV joining/normalization
    bindings.py         occurrence fan-out/coalescing + CDA assignments
    cooccurrence.py     conservative datatype-shape admissibility
    validate.py         config + record/source-constraint validation
    transforms.py       small declarative mapping transforms
    assertions.py       ART-DECOR assert/report evaluator + Schematron output
    conformance.py      pinned packages + XSD/Schematron validation gates
    validation/
        XsdValidator.java  JAXP full-schema validation adapter
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
such as repository source hints and exact reviewed CDA extension attachments.

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
    dependencies. Adopting a cached file matches the requested kind and
    identifier against both the defining `id` and the referencing `ref` form, so
    a repeated offline run neither re-reports a cached artifact as missing nor
    downgrades its recorded revision.
15. Consult exact catalog entries for package-local `builtin` supplements and
    cited `waiver` decisions. Every such entry declares `source_url`,
    `source_version` and `license`, and a `completeness` from a closed
    vocabulary. Builtins verify their package checksum, artifact identity and
    exact revision and can be materialized offline; only a `complete` builtin
    satisfies a required dependency. Waivers are settled but remain
    non-successful and degraded, and never satisfy one (`DEC-012`).
16. Add a target named by `config/cda-extensions.json` as an exact structural
    dependency only after the profile-overlay record is scoped to the selected
    transaction; snapshot the normalized record in `closure.json` for
    reproducible build input. An `attach` operation still requires an open CDA
    core slot. A `select_spec_branch` operation instead requires that the exact
    selected and replacement branches are siblings of the first `SPEC` editor-prototype
    choice at the same parent element. Generic context, names and project
    evidence never create either edge or selection.
17. Resolve a reviewed malformed identity only through an exact catalog
    `alias`; retain both keys and satisfy the published key only while the
    corrected target is successful (`DEC-022`).
18. Route a configured OID owner below the fetched project directory and above
    blind probing, retaining ordered candidates and attempts as evidence.
19. Fetch and freeze expansion evidence for dynamic, intensional or otherwise
    incomplete ValueSets. Admit only a complete, non-empty response as an
    `expansion` compiler form; retain a capped response separately as
    `expansion-evidence` and crawl-degradation evidence.
20. Treat exact concepts named by `templateAssociation/concept` and
    `staticAssociations/origconcept` as analysis-only mapping evidence. Close
    their formal origins transitively through `<inherit>`, `<contains>`, and
    compiled `originalId`, but never recursively through an ART-DECOR
    `<relationship>`. A concept response may contain siblings; only a
    separately requested association endpoint causes that sibling's own formal
    origin to be traversed.

`manifest.json` answers “what is cached for this release?”; transaction
`closure.json` answers “which cached resources belong to this transaction?” It
also separates crawler settlement (`crawl_complete`) from availability of the
selected transaction pair (`build_ready`) and records unavailable recursive
dependencies as degraded resources.
Build diagnostics retain that complete `crawl_degraded` list but derive their
headline from `build_degraded`, the subset consulted by selected formal
terminology, validator ValueSets or CDA template compilation. A validator
ValueSet counts only when the rule that needs it can apply to the selected
document: a template belongs to the selected closure when at least one compiled
target holds a document location. Other fetched templates remain available to
source audit and mapping analysis but are not publication-transform rule input
and cannot affect validator completeness (`DEC-010`, `DEC-019`).

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
Analysis and complete expansion forms of the same exact terminology identity
are merged when assembling DECOR validator input. ART-DECOR expansion wrappers
are converted to extensional concept lists and replace unresolved includes;
identity deduplication must not discard the frozen members. Dataset/concept
analysis containers are also scanned for exact embedded terminology already in
the build closure. Partial expansion evidence is never passed to a compiler.

Dependency analysis forms determine cache/build availability. Dependency source
forms add provenance and mapping evidence but are not synchronously backfilled
when analysis is already cached. The selected transaction source/analysis pair
is separately mandatory.

The transaction source defines selected concepts, transaction cardinality
overrides and direct terminology associations. The analysis form supplies
resolved definitions and containment. The compiler validates the pair and
records contained additions separately.

Concept `<inherit>` and `<contains>` recursively select one terminal original.
That original supplies semantic properties; the current stored concept supplies
descendants and transaction usage supplies cardinality. If a compiled literal
`contains` alias is absent, `originalId` or the uniquely corroborated synthetic
terminal-original SPEC emitted by ART-DECOR may locate the stored subtree.
Ordinary relationships never materialize a dataset subtree.

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
The same logical datapoints are used by generated configuration, reports,
validation and runtime assignment. A reviewer may additionally select a known
physical target exposed by the possible-target inventory; it passes the same
physical/type/occurrence checks and does not become semantic evidence merely by
bypassing the generated proposal interface. ART-DECOR identifiers are
provenance, not runtime addresses.

Compilation first resolves executable `<include>` and element `@contains`, then
derives the effective CDA model inventory. `cda/core.py` indexes the fetched
pinned XSD graph and recursively follows structural classes, datatype aliases
and inheritance; `cda/datatypes.py` contains only the scalar XML serialization
policy. Explicit ART-DECOR constraints overlay the legal model structure.
Structural targets remain navigation, evidence and repeat anchors. Scalar mapping
sees only targets whose compiled
`value_representation` marks them writable. The renderer executes that
representation and does not contain a second datatype dispatch table.

When current-build Schematron generation succeeds,
`datatype_constraints.rules` stores a shared registry of a strict error-level
presence co-occurrence subset from `DTr1_*.sch`, including resolved abstract
rule inheritance and original test/source provenance. The compiler records how
many error assertions were unsupported. Mapping admissibility applies a clause
only when one target assignment plus fixed attributes and required direct
children proves the violation; it does not infer optional-field or repeat
co-occurrence. The renderer repeats the same unavoidable-shape check before XML
construction, while the full generated Schematron remains the document-level
authority.

ART-DECOR choices are transparent structural constraints. Predicate variants
retain distinct identities but overlay one underlying XSD particle. Abstract
`ANY` values expose typed scalar alternatives with compiled `xsi:type`
representations; mapping chooses a branch only when datatype and context leave
one legal endpoint.

The XSD index also retains reverse extension relationships. A reviewed set of
polymorphic complex roots, currently only `SXCM_TS`, may expose concrete subtype
parts below one physical element. Those branches are transparent compiled
nodes: activating a descendant sets the branch's `xsi:type` on its parent, and
conflicting types in one occurrence fail. Generic datatype-derived
`useablePeriod` nodes are not expanded this way.

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

`isClosed` propagates from templates and elements through the executable
include/contains tree. CDA/RIM expansion types explicit particles in both open and
closed contexts, but materializes omitted particles only in open contexts. A
reviewed CDA extension is an in-memory containment constraint with distinct
provenance. Compilation rejects it unless its exact parent is already in the
unmodified selected closure, the named element is declared in that exact parent
template and remains open, and the pinned CDA XSD admits both its wrapper
particle and contained template root. The attachment does not modify cached
ART-DECOR XML. Its selected root suppresses omitted alternative core branches
at the synthetic wrapper without closing the attached template's own content.

A template's first `relationship type="SPEC"` is editor-prototype evidence. It
is fetched for diagnostics and reviewed DEC-028 choice replacement, but is not
part of the executable tree and is never merged into the current template.
Only explicit current-template constraints execute. Missing prototypes are
reported independently from unresolved executable includes/contains.

Fixed text/attributes are executable constraints rather than writable data
targets. `NP` nodes prohibit their complete physical subtree; synthesized
CDA/RIM or datatype descendants retain provenance but have effective
cardinality zero and cannot be writable. A target is writable only when its
datatype defines a value representation and it resolves to exactly one
unfixed, non-prohibited physical node. Ambiguity and structural-only targets
remain as provenance/evidence but are configuration/runtime errors when
selected as scalar destinations. `validate.verify_compiled_cda()` checks these
invariants before transformation.

ART-DECOR examples remain non-executable instance data. They do not create
compiled defaults, enrich fixed values with emitted example content, or satisfy
required descendants for presence-mode mappings. Expanded coded datatypes
identify their source-wording companion through a compiled content role,
allowing normalized `raw` text to populate that child without renderer
knowledge of CD/CE layout.

Names used by ART-DECOR constraints can contain XPath predicates that select a
sibling constraint. Predicates remain part of compiled path identity and
evidence, but are removed when the renderer turns a selected node name into an
XML QName.

Only fetched build-template forms participate in compilation. Live project
evidence cannot fill a missing dependency. Static flexibility is exact; dynamic
references resolve to a frozen manifest identity.

## Mapping evidence

Editable JSON stores only selections. `mapping-audit.json` stores the structured
decision record, and all three Markdown views are produced from the same analysis:
unresolved decisions, accepted mappings/evidence, and exhaustive coverage trees.
The build copies proposal views into `model/`. `init-cda-mapping` rerenders the
views against the actual portable mapping whenever reviewer-owned executable
choices differ, while retaining the proposal audit as explicitly labelled
generated evidence in the details appendix.
Its summary persists the same coverage-headline counts printed by `build` and
`init-cda-mapping`. Each unselected field/group, plus any selected field with
unresolved formal terminology, stores one first-failing `gap` gate and the
smallest concrete evidence that would reopen it. This keeps regression checks
and human details on one compiled evidence source.
Audit version 2 separately stores `possible_targets` for an unselected field
with a unique structural context. These type-compatible descendants are a
claim-aware physical inventory for human review, not evidence or automatic
selections; the coverage headline is therefore unchanged. A source-derived
datatype replacement part enters this inventory only when a compiled
co-occurrence clause names it directly beside an already inadmissible parent
representation. Rows with an unavoidable clause violation are retained but
marked unavailable.
Short `configuration_notes` are the exception to selection-only minimality:
they record configured attachments or resolution rules actually used by an
executable selection and are not themselves semantic evidence.
Evidence includes:

- direct/formal-origin-mediated `templateAssociation` (`TA`)
- ART-DECOR `staticAssociations/origconcept` links (`STATIC_ASSOC`)
- version-tolerant TA resolution
- `inherit`, `contains`, `originalId`, their reverse evidence edges, and
  review-only `relationship:<TYPE>` edges
- direct legacy `implementation/@xpath` declarations (`XPATH`)
- guarded template-name (`NAME`) bridge
- exact terminology/value-set/datatype combinations (`TERM`, `VS`, `DT`)
- exact unique element-description (`DESC`) bridge as weak fallback evidence
- unique contextual ART-DECOR role/description and compiled content role
- unique choice branch or datatype descendant inside a mapped container
- nearest compatible value at an already-derived `for_each` occurrence boundary
- contextual (`CTX`) placement
- generated template Schematron constraints (`SCHEMATRON_CONSTRAINT`) as
  supporting-only evidence on an existing bridge

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

Concept identity and CDA occurrence identity remain separate. If a recovered
static association resolves directly to a node outside an already selected CDA
occurrence, it is retained as an `occurrence_mismatch` alternative but is not
executable. An independently resolved `templateAssociation` remains a separate
candidate; only the unique in-context CDA/RIM-slot projection above may make the
static association cross template revisions. Generated Schematron can strengthen
compatible evidence but cannot override this guard.
Every ART-DECOR `relationship:<TYPE>` path is non-executable. The bridge and
its exact type remain visible for review, but name agreement, structural,
datatype, and Schematron compatibility cannot establish formal concept
identity. Contextual label traversal follows only `inherit`, `contains`, and
`originalId`; relationship-only candidates are also excluded as locators for
generated transforms.

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

Source-code normalization itself remains target-neutral. Finite and unresolved
formal domains reject unknown input; explicitly open domains retain raw wording
without creating a CDA null flavor. Exact source concept-list members retain
all of their formal terminology associations, and a required target ValueSet
may disambiguate them only by exact code/system membership. A shared but
unresolved ValueSet identity stays non-actionable review evidence and cannot
produce an empty enum transform.

A separately reviewed finite conversion may cross that unresolved boundary
through `reviewed_coded_map`. The mapping records every executable source label
and owner concept identity, every exact output and rationale, plus the exact
required target ValueSet revision. Configuration validation requires complete
source-option coverage and one physical target with the named binding. Runtime
uses an in-memory authorization carried only by that transform; site/default
JSON and ordinary transforms cannot obtain it. The authorization applies only
while the exact binding is unresolved. A later complete expansion restores
ordinary formal membership checks and exposes contradictions.

Required target bindings are enforced through one compiled terminology policy
for mapped values, site values, target defaults and final rendered values. A
missing code system may be completed only when the required ValueSet proves one
unique identity. The concrete pinned CDA XSD still controls serialization:
extension adds inherited content, restriction replaces restricted content and
removes prohibited attributes. Binding validation may therefore use the formal
system identity for `CS` while serialization correctly omits its prohibited
`@codeSystem` attribute.

The generated ART-DECOR vocabulary rule admits a datatype-legal
`@nullFlavor` as the alternative to a member code. No-information flavors such
as `NI` therefore do not extend the bound ValueSet. Payload-bearing `OTH` and
`UNC` are stricter because they represent an alternate value in
`originalText`; they require an explicit binding exception or one exact
reviewed finite-map authorization.

Formal `<inherit>` and `<contains>` chains resolve one terminal original.
Following ART-DECOR `getFullConcept`, that original supplies semantic
properties while the current stored concept supplies descendants and the
transaction supplies usage cardinality. ART-DECOR relationships do not
participate, regardless of type.

Mapping values can be direct target strings or declarative rule objects. A field
may control more than one target (for example Tetanusschutz `negationInd` and
`nullFlavor`) without introducing target-specific renderer code.

`cda-mapping.json` version 8 separates scalar transforms, structural bindings,
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
- `mode: "fallback_if_active"` is a reviewed fallback for a required target
  inside an optional branch. It requires a reason, is ignored during branch and
  repeat activation, and is consumed only after another assignment selects the
  branch;
- `mode: "presence"` lets a boolean activate one optional statement only when
  exact terminology identifies the template and ART-DECOR fixes its complete
  clinical payload. False omits it. The structural target does not become a
  scalar writable endpoint;
- `defaults.required_unmapped` fills an otherwise empty required leaf in an
  active template branch with `nullFlavor="NI"` by default. A concrete compiled
  `xsi:type` is retained when the CDA particle is polymorphic;
- `target_defaults` records reviewed target-specific completion, such as
  `nullFlavor="UNK"` for the required diagnosis onset that this transaction does
  not provide. Required complex elements may receive a null flavor only when
  their compiled datatype surface exposes an optional writable `@nullFlavor`.
  A real mapped value wins in its own occurrence;
- `site_requirements` delegates a required writable target to exactly one
  deployment channel, `values` or `fallback_if_active`, and records why the
  value is site-owned without embedding it in the portable mapping. Invalid
  declarations never satisfy construction completeness.

Every referenced mapping target also records its exact and revision-independent
ART-DECOR owner identity. Human-readable target labels can change between
template revisions; ordinary initialization migrates a stale label only when
template OID, element ID and path resolve to one unique current target.
`--reset` discards reviewed mapping state and starts from the proposal.

Compiled datatype targets may also carry `non_null_requires`. Proposal
generation treats a dependent component as review-only until the required
element or a descendant is mapped; configuration validation rejects an
incomplete reviewed selection, and rendering checks companion presence for each
populated occurrence after runtime completion. This is compiled datatype
policy, not a medication/template/path special case.

Required CDA entry narrative references use the same compiled-role boundary. If
an effective entry `text` constraint requires an unfixed
`reference/@value`, the compiler links that value to the containing section
narrative target and removes the generated fragment URI from the clinical
mapping surface. Rendering creates a deterministic fragment per active entry,
adds matching structured `content/@ID` narrative, and preserves section/entry
occurrence dimensions. A mapped entry-text value becomes the linked narrative
wording instead of being duplicated as mixed content in the entry.

## Package conformance boundary

Acquisition pins and hashes DECOR-core, the complete CDA R2/SDTC schema graph,
Saxon-HE and XML Resolver. Extraction retains original relative schema/include
paths, rejects unsafe archive members and records every extracted checksum.
These are setup/build tools; the transformation runtime neither loads them nor
requires Java.

`build` applies DECOR XSD and Core Schematron to the source-project evidence as
a report-only quality check. It separately assembles the exact fetched
transaction closure and invokes DECOR-core's publication transform to generate
and compile a selected-template validator candidate. Saxon probes the generated
stylesheet before it can be used. The assembled closure is not
called a native compiled ART-DECOR project; that unavailable form remains an
explicit `not-run` stage. Upstream generation errors make the validator
degraded and are preserved rather than hidden.

The publication transform receives exactly the effective-dated template
revisions selected at physical compiled document locations. Before generation,
assembly checks that every selected definition is present and that every formal
`include` or `contains` reference in those definitions resolves within the same
selected revision set. A missing, revision-inconsistent, or ambiguous formal
reference fails assembly instead of being hidden by filtering. This prevents
unselected project branches and superseded revisions from producing rules or
generation errors for the exact transaction validator.

Non-selected fetched templates are deliberately retained in the source cache,
project-quality audit, and the separate `mapping_evidence` inputs used for
candidate analysis. Excluding them from `<rules>` therefore narrows only the
executable validator, not the evidence available to mapping suggestions.
`validator-manifest.json` still records and conservatively scopes every message
emitted for the selected rules; an unparseable context is treated as
in-closure.

Mapping analysis follows that generation step. `compile/schematron.py` extracts
required and maximum occurrences, fixed values, ValueSet references, required
attributes, and concrete `xsi:type` choices from the template pattern files. It
matches them to compiled targets by pattern owner and predicate-aware XPath
suffix. The evidence can corroborate an existing bridge or discriminator rule,
but cannot create a candidate; if generation did not complete, mapping records
it as unavailable rather than reading an earlier build's files.

`validate-cda` is the independent, fail-closed output gate. It validates CDA
against the complete SDTC schema entry point and then executes the generated
transaction/datatype Schematron. It verifies validator and package provenance
before use and treats incomplete Schematron generation as failure. Validation
results do not select mappings; only the supporting constraint evidence above
may strengthen an already existing bridge.

For a non-CDA namespace selected by the compiled exact profile, the gate first
checks every foreign element and attribute against the compiled physical paths.
The CDA/SDTC XSD phase receives a structural projection with only those
reviewed foreign elements and attributes removed; the generated exact
Schematron still receives the unchanged original. This keeps the base-XSD claim
accurate when the pinned
package has no Pharmacy schema and does not present projection as validation
against that missing schema.

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
`cda-assertions.sch`. Every assertion retains the in-scope namespace bindings
from its source template. Both the in-process evaluator and generated
Schematron therefore resolve non-CDA prefixes such as `pharmhl7` to expanded
XML names instead of treating the lexical prefix as part of a local name. The
independent source verifier checks that assertions on effective ART-DECOR
source elements survive compilation.

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

Quantity fields normalize to a target-neutral object rather than a bare number:
`{"value": 2.5, "unit": "mg"}` for a scalar, or
`{"low": {"value": 1, "unit": "mg"}, "high": {"value": 2,
"unit": "mg"}}` for a range. A fixed unit declared by the dataset is supplied
when absent and conflicts are rejected. Numeric bounds are validated on both
ends of a range. CDA compilation attaches exact low/high child target names to
an interval quantity's value representation, so assignment can split a range
without datatype- or path-specific renderer behavior.

`build` has no input argument and never inspects CSVs. CSV/code proposal generation is a separate explicit `propose-input` step. The proposal step may inspect column names and observed coded values, but it does not infer relationships between CSV sources; joins/cardinalities remain explicit configuration.

## User-facing mapping verification

`check-cda-mapping` validates the compiled CDA, structural bindings, target
compatibility, and `mapping-lock.json` without requiring site CSV mappings.
This is the review gate for the shareable specification product. Explicit
`site_requirements` are validated as construction contracts and printed as
configuration notes; a concrete value is required and binding-checked only
when an actual site is validated or rendered.

`setup-test` supports two fixture sources. Its synthetic mode derives
deterministic CSV columns from `model.json`: scalar fields go to `cases.csv` and
each distinct repeat chain gets a generated `1:n` source with explicit
occurrence-key columns. Its authored mode reads a caller-selected directory
containing `scenario.json` and `input/*.csv`. The manifest pins the release and
exact transaction identity, declares every input relationship, and may require
case-specific model fields and CDA template IDs to be present or absent. Setup
rejects identity drift, unsafe or duplicate source paths, unknown model columns,
duplicate field ownership, and a case-source order that differs from the
declared cases before generating fixture configuration.

Both modes produce an isolated fixture configuration with valid identifier
roots and model-derived terminology aliases. `expected.json` freezes the
selected release/transaction and model/CDA/mapping hashes and records mapped and
unmapped fields. Authored mode additionally records the scenario name, source,
content digest, case list, and case-level assertions. The authored oracle is
therefore the reviewed input and explicit structural expectations; renderer
output is not copied back as golden expected XML.

An authored manifest may add local CDA values and activation-scoped CDA
fallbacks to the generated site configuration. It may also add input-code
translations. For an unbound dataset code, a translation can carry an explicit
code, code-system identity, and display name; bound dataset terminology still
accepts only one of its compiled canonical values. These declarations are
copied into the isolated fixture and never mutate `model.json`, `cda.json`, or
the reviewed portable CDA mapping.

`test-cda-mapping` reads that fixture through the ordinary production modules:
`data.ingest` → record validation → structural bindings → CDA rendering and
ART-DECOR assertions. It writes generated XML, `results.json`, and `results.md`
to the test result directory. It intentionally bypasses production change
state and transport. Coverage means a mapped datapoint survived normalization
and participated in the fixture suite. One synthetic document cannot exercise
mutually exclusive or conditional branches; a versioned authored suite can
distribute them across complete records and prove the declared absences as well
as presences.

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

- Generic CDA narrative remains minimal. Required entry references resolve to
  generated section `content` nodes; richer section-specific tables can be
  added without changing mappings.
- Nested repetition requires stable occurrence keys when more than one independent
  level/source is involved; positional guessing remains intentionally unsupported.
- `transport.py` selects a built-in adapter through a closed, validated
  configuration contract. Its only current adapter is one-document generic
  HTTP POST; batch and acknowledgement semantics remain unspecified.
