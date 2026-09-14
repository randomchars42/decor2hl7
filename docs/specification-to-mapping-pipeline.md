# From ART-DECOR specifications to models and mappings

This guide follows the specification workflow from selected ART-DECOR XML to
the generated target-neutral dataset model, compiled CDA target model, mapping
evidence, mapping proposal, and reviewed mapping bundle. It explains where each
rule enters the process and which artifact records its result.

The guide stops at the mapping boundary. Synthetic mapping tests, production
input processing, CDA rendering, state handling, and transport are separate
follow-up topics.

## Pipeline at a glance

```text
release + transaction selection
              │
              ▼
       decor2hl7 fetch
              │
              ├── parse identities and references
              ├── resolve and fetch the dependency closure
              ├── freeze exact artifact forms and checksums
              └── classify build versus mapping-evidence resources
              │
              ▼
   manifest.json + closure.json + cached XML
              │
              ▼
       decor2hl7 build
              │
              ├── assemble validated compiler inputs
              │
              ├── transaction source + analysis + terminology
              │            │
              │            └──> model.json
              │
              ├── templates + CDA R2 XSD + reviewed overlays
              │            │
              │            └──> physical cda.json
              │
              ├── generated Schematron evidence
              │            │
              │            └──> annotated cda.json
              │
              └── mapping evidence + model.json + cda.json
                           │
                           ├──> mapping-audit.json
                           ├──> cda-mapping.proposed.json
                           ├──> logical datapoints in cda.json
                           └──> generated mapping guides
                                      │
                                      ▼
                         decor2hl7 init-cda-mapping
                                      │
                                      ▼
                         reviewed cda-mapping.json
                         mapping-lock.json + guides
```

The four central boundaries are deliberately separate:

| Boundary | Main input | Main output | Owner |
|---|---|---|---|
| Acquisition | Selected release and transaction | Frozen XML artifacts and closure metadata | Specification acquisition |
| Dataset compilation | Transaction source/analysis and terminology | `model.json` | Target-neutral compiler |
| CDA compilation | Effective templates, CDA R2 XSD and reviewed overlays | Physical `cda.json` | CDA target compiler |
| Mapping analysis | Mapping evidence, `model.json`, and `cda.json` | Audit, proposal and logical CDA datapoints | Mapping compiler and reviewer |

## 1. Selection establishes identity, not content

`set-version` and `set-transaction` write the selected release and transaction
to `aktin.json`. They do not fetch or compile anything.

The selected identities determine every later path and exactness check:

```text
spec/<release>/
spec/<release>/transactions/<transaction>/
model/<release>/<transaction>/
mapping/<release>/<transaction>/
```

The transaction identity includes its OID and effective date. A static
reference must resolve to that exact revision. A dynamic reference may be
resolved once, but its resolved revision is then frozen in the manifest.

Code entry points:

- release and transaction catalog parsing: `retrieval/catalog.py`;
- selected state and paths: `workspace.py`;
- CLI orchestration: `cli.py`.

## 2. Fetch parses references and closes dependencies

`decor2hl7 fetch` calls `retrieval.fetch.fetch_spec()`. Fetching is recursive:
the selected transaction is the root, and typed references discovered in each
artifact add work to either the build or evidence queue.

### 2.1 XML parsing at acquisition time

`retrieval/xml.py` parses XML with `xml.etree.ElementTree`. Its helper functions
normalise namespace access and record narrowly repaired namespace defects. The
cached forms remain XML; fetch does not create one universal in-memory AST for
all later compilers.

Reference extraction distinguishes artifact kind and XML context. In
particular, a template `include` is not confused with a ValueSet include.
Dependencies are represented as typed requests for datasets, concepts,
templates, ValueSets, or CodeSystems, including their requested identity,
effective date, project context, and reason.

### 2.2 Resolution

Resolution uses the strongest available ownership evidence before probing:

1. explicit link or project context on the reference;
2. configured source hints from `config/sources.json`;
3. the exact artifact-owner cache and project ownership evidence;
4. other known project metadata and OID-prefix inference;
5. network probing as a last resort.

The resolver records attempts and resolved identity. It never treats a nearby
revision as the requested static revision.

### 2.3 Artifact forms

One logical artifact may have several forms:

| Form | Purpose |
|---|---|
| `source` | Original selection, labels, associations, and provenance |
| `analysis` | Expanded/resolved compiler input |
| `expansion` | Complete frozen terminology membership |
| `expansion-evidence` | Partial evidence retained for diagnosis, never accepted as a complete compiler expansion |

The selected transaction requires both source and analysis forms. For ordinary
dependencies, a valid analysis form is sufficient for compilation; a missing
optional source sidecar only reduces provenance or mapping evidence.

### 2.4 Build and evidence closure

Every dependency carries a role:

- **build resources** can affect `model.json`, `cda.json`, terminology, or
  formal validation;
- **evidence resources** may establish associations, formal origins, labels, or other
  mapping evidence without changing the compiled specification.

The crawler follows executable template `include`/`contains`, terminology
composition, first-SPEC editor prototypes as evidence, and the bounded formal
concept origins needed for mapping. It does not crawl complete unrelated
projects merely because they are reachable by a relationship.

Reviewed `config/cda-extensions.json` records are normalised and scoped to the
selected transaction during fetch. Their exact template dependencies join the
closure, and the normalised records are copied into `closure.json` so a later
build does not depend on mutable configuration alone.

### 2.5 Fetch products

```text
spec/<release>/manifest.json
    release-wide artifact identities, forms, paths, checksums and status

spec/<release>/artifact-owners.json
    reusable exact ownership evidence

spec/<release>/transactions/<transaction>/closure.json
    transaction build/evidence membership, reviewed overlays, unresolved
    resources, degradation, crawler completion and build readiness

spec/<release>/.../*.xml
    cached source, analysis and terminology forms
```

`crawl_complete` means discovery settled. `build_ready` separately means the
selected transaction has the mandatory inputs needed by the compiler. A closed
crawl may therefore still be degraded.

## 3. Compiler input assembly is a validation boundary

`compile/artifacts.py:compiler_inputs()` turns the fetched closure into typed
compiler inputs. It does not rediscover dependencies.

The assembler:

1. resolves closure records through the release manifest;
2. verifies files, checksums, forms, and exact identities;
3. requires the selected transaction source/analysis pair;
4. separates model, terminology, template, and mapping-evidence paths;
5. admits only complete expansion forms as terminology input;
6. normalises the snapshotted CDA extension records;
7. carries unavailable and partial resources into diagnostics.

Missing auxiliary evidence can remain degraded. Contradictory identity,
checksum, or required-form state is fatal.

```text
closure + manifest
       │
       ▼
CompilerInputs
       ├── transaction_source
       ├── transaction_analysis
       ├── model_resources
       ├── terminology_resources
       ├── templates
       ├── mapping_evidence
       ├── cda_extensions
       └── degradation evidence
```

## 4. The rule sources are composed, not blended

Rules come from several authorities. Keeping their roles separate prevents a
label, example, or mapping preference from silently becoming a specification
constraint.

| Rule source | What it may establish | Where it enters | What it may not do |
|---|---|---|---|
| Selected transaction source | Selected concepts, transaction cardinality overrides, direct associations | Dataset compilation and mapping evidence | Union unrelated or unselected dataset content |
| Transaction analysis | Resolved containment and concept definitions | Dataset compilation | Override the selected source identity |
| Exact terminology definitions/expansions | Formal members, code systems, inclusion status | Dataset model and mapping compatibility | Promote incomplete expansion evidence to a complete domain |
| ART-DECOR templates | Template relationships, cardinality, conformance, fixed values, vocabulary, assertions | CDA compilation | Supply omitted clinical values from examples |
| CDA R2/RIM XSD | Legal structural classes, particles, datatype parts and scalar representations | CDA compilation | Choose a clinical mapping |
| Generated Schematron | Effective assertions and bounded target/co-occurrence evidence | CDA annotation and mapping admissibility | Create semantic bridges on its own |
| Reviewed CDA overlay | One exact attachment or first-`SPEC` prototype branch selection | Fetch closure and CDA compilation | Apply by name, generic context, or a different revision |
| Mapping compiler policy | Candidate ranking, compatibility gates, transforms and structural-rule derivation | Mapping proposal | Turn weak similarity into reviewed clinical truth |
| Reviewed `cda-mapping.json` | Accepted mappings, explicit transforms, structures and target defaults | Portable mapping product | Redefine `model.json` or the physical CDA profile |

### 4.1 Dataset rule composition

```text
transaction analysis: resolved dataset tree
                  +
transaction source: selected concepts and explicit overrides
                  +
exact resource definitions and terminology
                  +
formal `<inherit>`/`<contains>` terminal-original properties
                  │
                  ▼
             model.json
```

Formal `<inherit>` and `<contains>` chains resolve one terminal original, which
supplies semantic properties. The current stored concept supplies descendants;
the transaction supplies usage cardinality. Every `<relationship>` type is
review evidence only and never participates in that composition.

### 4.2 CDA constraint composition

```text
pinned CDA R2/RIM XSD legal structure
                  │
                  ▼
stored ART-DECOR document/template constraints
  (`include`, `contains`, cardinality, conformance, fixed values)
                  │
                  ├── first-`SPEC` editor-prototype diagnostics
                  │
                  ├── exact reviewed attachment/branch overlay
                  │
                  ▼
expanded effective physical CDA tree and target registry
                  │
                  ├── generated Schematron evidence
                  │
                  ▼
                cda.json
```

Only the current template's stored constraints execute. If its first SPEC
editor prototype is available, matching explicit nodes are compared and any
cardinality/conformance broadening becomes a visible `SPEC`-weakening
diagnostic; `--strict-specializations` makes it fatal.

ART-DECOR examples are instance illustrations. They do not become fixed values
or defaults. A narrowly derived structural discriminator may use an exact
neutral example only when the compiler also proves the target structure,
terminology member, and source-category correspondence.

## 5. Building the target-neutral dataset model

`compile/transaction.py:compile_model()` compiles the source side. Its result
is independent of CDA and can be reused by a future target.

### 5.1 Parse the selected transaction pair

The compiler parses the transaction analysis into a flat path-indexed concept
tree. It then parses the transaction source and verifies that source and
analysis identify the same transaction and revision.

Source selections are applied to the analysis tree. A selected concept that
the analysis form cannot resolve is a contradiction, not an invitation to
guess from another dataset revision.

### 5.2 Parse and expand terminology

ValueSets and CodeSystems embedded in the transaction are parsed first.
Additional exact resources then enrich matching stubs. Definitions are keyed
by identity and effective date; revisions are not merged.

The compiler resolves extensional members and supported intensional includes.
For every field it preserves three distinct views:

- `logical_domain`: dataset labels and options;
- `formal_terminology`: the exact transaction binding, members, completeness,
  missing ValueSets, and unresolved includes;
- `accepted_values`: the executable input domain, using formal members when a
  formal binding exists and logical values only when no formal binding exists.

### 5.3 Resolve formal originals and stored descendants

Formal `<inherit>` and `<contains>` are followed to one terminal original. Its
semantic properties replace the alias/use concept's semantic properties, while
the alias identity, short name, transaction cardinality, and currently stored
descendants remain current. A literal `contains` identity is preferred for
stored descendants. If that compiled alias is unavailable, its explicit
`originalId` or ART-DECOR's uniquely corroborated synthetic terminal-original
SPEC may locate the subtree. Ordinary relationships cannot do so. This is
owner-defined origin resolution, not a union of historical datasets.

### 5.4 Materialise groups and fields

Each parsed concept becomes either a group or field keyed by its stable model
path. Common properties include:

- names, descriptions, comments, implementation text and concept identity;
- parent, cardinality, required state;
- repeat owner and complete `repeat_chain`;
- logical datatype and datatype constraints;
- terminology associations and domain metadata;
- provenance and transaction metadata.

Repeated occurrence structure is established here. Mapping and runtime do not
reconstruct it later by positional guessing.

### 5.5 Write source-side products

The build writes:

- `model.json`: target-neutral groups, fields, domains, occurrence structure,
  terminology, transaction identity, and artifact-closure status;
- `codes-mapping.proposed.json` and `codes-mapping.md`: model-derived input-code
  defaults and guidance. These are site/input products, not CDA mappings.

## 6. Building the physical CDA target model

`cda/compile.py:compile_cda()` compiles the target side from fetched templates
and the pinned CDA R2 XSD graph.

### 6.1 Select the document and reachable templates

The representing template ID and effective date come from `model.json`.
Template XML is indexed by exact identity. The compiler walks executable
`include` and `contains` references and records unresolved references instead
of substituting another revision. Missing first-SPEC editor prototypes are
reported separately and do not degrade executable closure.

### 6.2 Apply reviewed overlays

Before effective-template construction, reviewed overlays are revalidated
against the compiled transaction and exact document scope:

- `attach` adds an exact template below an explicitly open parent slot;
- `select_spec_branch` replaces one stored sibling choice with another exact
  sibling declared by the first `SPEC` editor prototype's same host element.

The compiler checks transaction, document, parent, element, selected template,
replacement template, revision, multiplicity, and CDA XSD compatibility.

### 6.3 Resolve effective ART-DECOR constraints

The current template's stored constraints are effective. Transparent `include`
and `contains` wrappers recurse and retain template identity/provenance without
adding an XML level. A template SPEC is editor-prototype evidence and is not
merged into the executable tree.

Before composition, `cda/art_decor.py` accounts for every template-design
child. `element`, `attribute`, bounded `choice`, `include`, and `context` are
structure; `property`, `vocabulary`, `text`, `let`, `defineVariable`, `assert`,
and `report` carry executable validation semantics. An unknown grammar child is
fatal. `constraint` is preserved free-form prose because the owner schema types
it as markup and the owner Schematron transform does not execute it. Examples,
descriptions, comments, classification, purpose/copyright, FHIR annotations,
and relationship metadata are retained or accounted for but do not execute.

The executable pass order is: select the exact current revision and lifecycle;
expand formal `include`/`contains`; preserve choice alternatives and aggregate
bounds; overlay current cardinality, conformance, closedness, fixed values,
properties and vocabulary; expand legal CDA/RIM structure; expand datatype
flavours and scalar representations; then attach assertions/reports and
generated Schematron evidence. Template `SPEC` remains prototype comparison
evidence throughout and is not inserted into this sequence.

This establishes binding strength, `minInclude`/`maxInclude`, fraction and
length bounds, namespace/context attributes, variable definitions, assertions,
reports, textual constraints, and prototype-comparison diagnostics as explicit
compiled properties. A conditional (`C`) rule without a machine-readable
condition is diagnosed; prose is never promoted into executable XPath.

### 6.4 Expand CDA/RIM structure

`cda/core.py` indexes the pinned CDA R2 XSD graph, including structural classes,
type inheritance, particles, attributes, and reverse extension relationships.
The compiler overlays ART-DECOR constraints onto that legal model and fills
omitted CDA/RIM particles only where the effective context is open.

An explicit child already supplied through `include` or `contains` satisfies
its XSD particle; it is not accompanied by a second generic sibling.

### 6.5 Expand datatypes and representations

HL7 V3 datatypes are expanded recursively into structural parts and writable
scalar representations. `cda/datatypes.py` defines scalar XML serialization
policy; mapping and rendering consume the compiled `value_representation`
instead of maintaining their own datatype switch tables.

The compiler also handles:

- supported polymorphic branches and their required `xsi:type`;
- prohibited subtrees inherited from `NP` constraints;
- interval/quantity low and high targets;
- non-null companion requirements for compound datatypes;
- coded original-text companions;
- linked entry narrative targets;
- exact compiler-owned system-content roles.

### 6.6 Name and annotate physical targets

Every structural or writable constraint receives a stable flattened target
identifier. The identifier is a configuration key, not an alternate XML path.
The target still records its full CDA path, template and element identity,
datatype, fixed constraints, physical locations, repeat ancestors,
representation, provenance, and writability.

A target is directly writable only when it resolves to one unfixed,
non-prohibited physical location and has a compiled scalar representation.
Ambiguous or structural targets remain visible for navigation and evidence but
cannot be selected as scalar destinations.

The initial physical `cda.json` contains:

- the effective document tree;
- physical target registry;
- source-to-target index;
- assertions and namespace maps;
- reviewed overlay evidence and SPEC prototype-comparison diagnostics;
- unresolved templates, datatype inventory, and summary statistics.

At this point `datapoints` is still empty. Logical datapoints are added only
after mapping establishes source-facing occurrence semantics.

## 7. Generated Schematron adds evidence after CDA compilation

`build` assembles the exact fetched specification with the pinned DECOR-core
transform and generates the transaction Schematron. This validation build is
recorded below `model/.../conformance-validation/`.

`compile/schematron.py:attach_constraints()` parses a conservative subset of
the generated rules and attaches it to uniquely identified physical targets:

- required attribute/element evidence;
- fixed-value and ValueSet constraints supported by the parser;
- error-level datatype presence/co-occurrence clauses, including resolved
  abstract-rule inheritance.

Unsupported XPath remains counted and is left to complete Schematron
validation. Schematron evidence can make a candidate inadmissible or strengthen
an existing bridge; it does not invent a source-to-target semantic bridge.

The annotated in-memory CDA model is passed directly to mapping generation and
then rewritten as the final generated `cda.json`.

## 8. Generating mapping evidence and the proposal

`compile/mapping.py:_cda_mapping_analysis()` combines:

```text
model.json
    +
annotated physical cda.json
    +
transaction/dependency source and analysis XML marked as mapping evidence
    │
    ▼
candidate graph → compatibility gates → occurrence rules → proposal + audit
```

This stage does not inspect site CSV files.

### 8.1 Build evidence indexes

The mapper parses the evidence XML into:

- formal-origin and relationship graph;
- direct and formal-origin-mediated `templateAssociation` edges;
- `staticAssociations/origconcept` edges;
- legacy `implementation/@xpath` declarations;
- concept names, labels, descriptions, and formal-origin label neighbours;
- exact ValueSet members and target indexes.

Evidence kinds remain visible in candidate chains such as `TA`,
`STATIC_ASSOC`, `XPATH`, `TERM`, `VS`, `DT`, `NAME`, `DESC`, `CTX`, and
`SCHEMATRON_CONSTRAINT`.

### 8.2 Resolve group context before fields

Groups are processed from parent to child. A uniquely placed structural target
can establish context even though a group is not a scalar writable value.
Resolving groups first prevents a historical association from moving a child
into a different CDA occurrence.

Preliminary `for_each` rules are derived from the group placements and repeat
chains. Field candidate checks can then account for source and target
occurrence dimensions.

### 8.3 Generate and filter field candidates

For each field, the mapper combines formal association candidates with bounded
contextual candidates such as an exact descendant, choice branch, repeat-scope
value, section narrative target, or target-governed open-code fallback.

Candidate evidence and executability are separate. Before a candidate can enter
the executable proposal, it must pass applicable gates for:

- one physical writable location;
- source/target datatype and scalar-representation compatibility;
- unit and finite terminology compatibility;
- source and target cardinality;
- structural context and occurrence alignment;
- existing claims on the same physical target;
- required compound-datatype companions;
- generated datatype co-occurrence constraints.

For coded fields, a shared ValueSet identity is executable only when its exact
revision has a complete usable member set. An unresolved include is retained as
review evidence and a terminology gap; it cannot create a direct mapping or an
empty enum transform. Each non-abstract source option keeps every exact formal
code association. If several exist, only exact membership in the required
target ValueSet may choose among them.

An unselected field may still receive a `possible_targets` inventory. Those
rows are type-compatible physical leaves for review, not proof of meaning.

### 8.4 Derive declarative scalar transforms

Where specification evidence proves the conversion, the proposal may contain
a small declarative transform rather than a direct target string. Current
transform forms include `identity`, `enum`, `ordinal`, `not`, `code_system`,
`coded_fallback`, and `reviewed_coded_map`.

These transformations remain data in the mapping. They are not implemented as
template-specific renderer branches.

Dataset code normalization never emits CDA `OTH`, `UNC`, or another null flavor.
`coded_fallback` is generated only for an explicitly open source domain and a
resolved exact target ValueSet that declares the exception and exposes a
compiled `originalText` companion. Required target binding membership is then
checked centrally for mapped values, site values, target defaults, and final
rendered values. The pinned XSD restriction/extension graph controls which
attributes may actually be serialized.

`reviewed_coded_map` is never generated from unresolved terminology. A
maintainer may add it only to the portable mapping with complete exact source
concept coverage, one exact target ValueSet revision, and per-case reasons.
Its enumerated outputs are authorized only for that unresolved target binding;
the unresolved closure stays visible. If the target binding later resolves,
the formal expansion wins and incompatible reviewed outputs fail.

### 8.5 Resolve shared targets and occurrence semantics

After initial candidates are selected, claims on shared physical targets are
resolved explicitly:

- `repeat_by_discriminator` creates separate logical occurrences only when an
  exact discriminator and source/member correspondence are proven;
- `coalesce` allows equivalent singleton fields to share one target and uses
  `equal_or_error` unless another policy is reviewed;
- reviewed `prefer_first_warn_if_different` keeps deterministic precedence but
  reports a difference, while `concatenate` applies per-source transforms,
  skips absent values, and joins same-occurrence text with an explicit
  separator;
- `for_each` binds each source repeat dimension to one explicit CDA repeat
  node;
- unresolved shared targets are blocked rather than populated positionally.

A bounded second field pass may use the completed occurrence rules to resolve
one exact nearest value inside an already established repeat boundary.

### 8.6 Classify unresolved decisions

After shared-target and compound-datatype checks, every field/group has one of
three useful outcomes:

- an executable selected mapping;
- structural context or reviewable alternatives without an executable mapping;
- no CDA bridge, with a first-failing `gap` and evidence needed to reopen it.

The audit retains alternatives, confidence, warnings, blocked reasons,
possible targets, structural rules, and coverage counts. The concise proposal
contains only selections and executable rules.

## 9. Generated mapping products

The final part of `build` writes:

| Artifact | Purpose |
|---|---|
| `mapping-audit.json` | Canonical structured evidence, alternatives, gaps, claims, rule provenance, and coverage |
| `cda-mapping.proposed.json` | Concise executable proposal for review |
| `cda-mapping.md` | Working review guide for selected and unresolved fields |
| `cda-mapping-details.md` | Accepted mappings, complete evidence chains, candidates, and diagnostics |
| `cda-mapping-trees.md` | Exhaustive dataset and CDA coverage trees |
| `cda-expanded-readable.xml` / `.md` | Human-readable effective CDA hierarchy |
| final `cda.json` | Physical target registry plus mapping-derived logical datapoints |

The proposal uses mapping version 9 and separates:

- `fields`: source field to logical target selections and scalar transforms;
- `structures`: named occurrence, repetition, discriminator, coalescing, and
  reviewed text-concatenation rules;
- `field_reviews`: reviewer-owned reasons for intentional null selections;
- `defaults.required_unmapped`: generic completion policy for active required
  target leaves;
- `target_defaults`: reviewed exact target-specific completion values and
  reasons;
- `site_requirements`: reviewed required targets that deployment configuration
  must supply, each with an exact `values` or `fallback_if_active` channel and
  a rationale but no concrete value;
- `target_identities`: exact and revision-independent ART-DECOR owner identity
  for every referenced readable target name;
- `configuration_notes`: short provenance for relevant acquisition/profile
  configuration.

### Physical targets and logical datapoints

`cda.json:targets` remains the physical template-constraint registry.
`cda.json:datapoints` is generated from the proposal and forms the logical
model-facing interface.

Most mappings are one-to-one. For a structural rule, the logical name may
differ from the physical target. This is why a mapping rule can contain both:

```json
{
  "target": "Pupilsize_right.value",
  "cda_target": "Pupilsize.value",
  "structure": "repeat-by-discriminator-pupilsize-value",
  "branch": "right"
}
```

`target` is the logical assignment name; `cda_target` is the physical CDA
constraint. They are intentionally equal for some structurally uniform rules,
including a generated `coalesce`. The explicit fields keep the mapping schema
and runtime resolution uniform rather than requiring rule-type-specific
interpretation.

## 10. Initialising and reviewing the portable mapping

`decor2hl7 init-cda-mapping` moves the generated proposal across the ownership
boundary:

```text
model/.../cda-mapping.proposed.json       generated analysis
                    │
                    ▼
mapping/.../cda-mapping.json              reviewer-owned decision
```

If the destination does not exist, it is created from the proposal. If it
already exists, reviewer selections are preserved. The command may apply a
narrow compatible structural-rule migration and refresh generated
configuration notes, but it does not overwrite field choices merely because a
new proposal differs.

`init-cda-mapping --reset` is the explicit destructive counterpart: it replaces
all reviewed field, structure and default choices with the current generated
proposal and refreshes the mapping lock. On an ordinary initialization, stale
target labels migrate only through one unique stored owner identity; an
ambiguous identity never falls back to a name or path guess.

A generated proposal is not necessarily a complete document configuration.
`check-cda-mapping` traverses the same active cardinality and choice structure
as rendering and reports mandatory slots for which neither the template,
mapping, structural rules, site configuration nor document-production roles
can supply a value. A valid `site_requirements` declaration records that a
specific required slot is intentionally site-owned, so the portable check emits
a configuration note instead of a missing-value error. It does not invent or
verify a concrete deployment value. Actual site validation requires that value
in the declared channel and checks required terminology binding.

The three generated mapping guides are refreshed beside the reviewed mapping.
`mapping-lock.json` records release, transaction, model, CDA, and mapping
identity for the bundle. `check-cda-mapping` is the next boundary, but its
validation behavior belongs to the later testing documentation.

## 11. Worked trace: Aufnahmezeitpunkt and reviewed allergy time

The source compiler records
`administrative_aufnahmeinformationen.aufnahmezeitpunkt` as a target-neutral
datetime field with minute precision, `0..1` source cardinality, and no repeat
chain.

The CDA compiler independently creates the physical target
`CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.low@20160601`.
Its provenance combines template `1.2.276.0.76.10.2036@2016-06-01` with the
`IVL_TS/low` datatype part. Its value representation accepts a date or datetime
and serializes the timestamp through `@value`.

The available association reaches that target only across a `SPEC` relationship
and reverse formal-origin edge. It is therefore a visible review candidate, not
an executable generated mapping for Aufnahmezeitpunkt. An older association for
`dokumentationsinformationen.beginn_patientenbezogene_dokumentation.zeitpunkt_beginn_patientenbezogene_dokumentation`
is reached only through an `ADAPT` relationship whose concept name has changed.
AKTIN confirmed that the target profile does not use this documentation-start
concept. The compiler therefore keeps the bridge as review evidence with
`semantic_blocked="relationship_requires_review"`; datatype and Schematron compatibility
cannot promote either relationship-only bridge. A reviewed mapping may still
make an explicit domain decision, but the generated proposal remains `null`.

AKTIN separately confirmed that Allergy Concern Act `effectiveTime/low` is the
start of documenting an allergy concern, and that the emergency-department
collection time may be used. The reviewed mapping adds an activation-scoped
fallback to the already direct encounter mapping:

```json
[
  "CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.low@20160601",
  {
    "target": "Allergyconcernact.low",
    "mode": "fallback_if_active",
    "reason": "Reviewed emergency-department collection time for an activated allergy concern."
  }
]
```

The marker is ignored while the renderer decides which optional branches and
repeats are active. It fills the mandatory concern start only after an agent,
allergy flag, or other actual assignment has selected that allergy branch.
The distinct clinical onset belongs to Allergy Intolerance Observation
`effectiveTime`; because the transaction provides no onset, the reviewed target
default emits `nullFlavor="UNK"` there. The reviewed ActStatus `completed`
fills the observation's mandatory `statusCode`; it describes completion of the
assertion, not resolution of the allergy.

## 12. Worked trace: Tetanusschutz fan-out

The dataset compiler records Tetanusschutz as a coded source field with three
accepted states. The strongest formal association identifies the complete
Clostridium tetani immunization statement, but that structural CDA node cannot
accept the source code directly.

The CDA compiler exposes two relevant writable attributes on the statement:

- mandatory boolean `Clostridiumtetaniimmunization.negationInd`;
- optional conditionally fixed
  `Clostridiumtetaniimmunization.nullFlavor="NI"`.

The semantic transform pass recognises the dataset state labels and CDA
negation/null semantics and emits two `enum` assignments:

| Source state | `negationInd` | `nullFlavor` |
|---|---:|---:|
| `Patient hat Tetanusschutz` | `false` | omitted |
| `Patient hat keinen Tetanusschutz` | `true` | omitted |
| `Information nicht erhebbar` | `false` | `NI` |

One source field can therefore select several target assignments without
putting Tetanus-specific logic in the renderer. A mapping test that supplies
only the positive state exercises `negationInd` but not the conditional
`nullFlavor` branch; that is a test-coverage observation, not a failed CDA
constraint.

## 13. Worked trace: repeated medication structure

The dataset model records the medication source occurrence in its
`repeat_chain`. Group mapping first places the medication hierarchy in the
compiled medication section. The structural mapper then derives a `for_each`
rule whose source group is `masnahmen.medikamentose_therapie` and whose target
repeat is the section's repeatable `entry` particle.

This distinction matters:

```text
one medication section
        │
        ├── entry for source medication occurrence 1
        ├── entry for source medication occurrence 2
        └── entry for source medication occurrence n
```

The section is shared; `entry` owns the source-aligned repetition. Individual
medication value mappings are checked against this occurrence rule. The mapper
does not zip unrelated source rows or create repeated sections merely because
both source and CDA contain repeatable ancestors.

## 14. Diagnostics and reproducibility

The pipeline records failures at the boundary that can explain them:

| Diagnostic | Meaning |
|---|---|
| Fetch closure status | What was resolved, missing, unavailable, waived, partial, or truncated |
| `build-diagnostics.json` / `.md` | Which degraded artifacts actually affect the selected build and why |
| `constraint_diagnostics` in `cda.json` | Explicit broadening relative to a SPEC prototype or other effective-template concerns |
| `schematron_evidence` in `cda.json` | Parsed/attached rule counts and unsupported bounded subsets |
| `mapping-audit.json` | Why a field was selected, blocked, left unmapped, or offered review-only targets |
| Generated mapping guides | Human-readable review surfaces derived from the audit and proposal |

Generated files under `model/` are rebuildable. The fetched closure and exact
artifact checksums make the build reproducible. The reviewed mapping under
`mapping/` is not regenerated over existing choices and remains the portable
decision product.

## 15. Code map

| Concern | Primary implementation |
|---|---|
| Catalog selection | `src/decor2hl7/retrieval/catalog.py` |
| XML helpers and namespace repairs | `src/decor2hl7/retrieval/xml.py` |
| Dependency extraction and roles | `src/decor2hl7/retrieval/references.py` |
| Artifact identity/forms | `src/decor2hl7/retrieval/artifacts.py` |
| Resolution and ownership | `src/decor2hl7/retrieval/resolution.py` |
| Recursive closure | `src/decor2hl7/retrieval/fetch.py` |
| Build input contract | `src/decor2hl7/compile/artifacts.py` |
| Dataset and terminology compilation | `src/decor2hl7/compile/transaction.py` |
| CDA R2 XSD graph | `src/decor2hl7/cda/core.py` |
| CDA scalar representations | `src/decor2hl7/cda/datatypes.py` |
| Reviewed CDA overlays | `src/decor2hl7/cda/extensions.py` |
| Effective CDA compilation | `src/decor2hl7/cda/compile.py` |
| Generated Schematron evidence | `src/decor2hl7/compile/schematron.py` |
| Datatype co-occurrence proof | `src/decor2hl7/cooccurrence.py` |
| Structural mapping rules | `src/decor2hl7/compile/structural.py` |
| Mapping analysis and proposals | `src/decor2hl7/compile/mapping.py` |
| Generated mapping reports | `src/decor2hl7/compile/reports.py` |
| Workflow orchestration | `src/decor2hl7/cli.py` |

## Deferred documentation

The following begin after the reviewed mapping boundary and are intentionally
not described here:

- `check-cda-mapping` and static mapping validation;
- `setup-test`, synthetic scenario design, `test-cda-mapping`, and independent
  CDA conformance validation;
- site CSV/code configuration and input proposal generation;
- input ingestion, joins, occurrence normalisation, and record validation;
- assignment building, target defaults, and CDA rendering;
- runtime state, correction/version behavior, transport, and operational
  failure handling.

Those topics should reference the model and mapping contracts defined here
rather than restating how the specification products are built.
