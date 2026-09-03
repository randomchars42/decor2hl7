# Project decor2hl7

## Goal

`decor2hl7` transforms flat clinical source data into an HL7 structure using specification information obtained from ART-DECOR.

CDA is the first output target. The project must not make CDA the architectural boundary of the source-data and normalized-data pipeline: a future version may target HL7 FHIR, or another HL7 representation, while reusing acquisition, dataset compilation, input normalization, validation, state handling, and as much mapping infrastructure as is target-independent.

Conceptually:

```text
source data
    │
    ▼
target-neutral dataset model
    │
    ├── CDA target model + cda-mapping.json  ──> CDA document
    │
    └── FHIR target model + fhir-mapping.json ─> FHIR resources   (future)
```

ART-DECOR complexity is a setup-time concern. Runtime must consume compiled, stable models and reviewed configuration rather than reparsing ART-DECOR XML.

The implementation should remain procedural, typed, unit-testable, and usable through one CLI. The code is installed as a Python package and does not live inside the user's working directory.

---

## Canonical project knowledge

The `randomchars42/decor2hl7` repository on `main` is authoritative for code,
tests and durable project documentation. Conversations and unmerged branches are
working contexts, not decision stores. Dated analyses under `docs/analyses/` are
evidence snapshots and are not silently rewritten as current behaviour.

Durable semantic and architectural choices are indexed in
[`docs/decisions.md`](docs/decisions.md). Open external or clinical boundaries
remain in [`docs/known-issues.md`](docs/known-issues.md). A semantic code change
must update its decision record, affected known issue, regression test and
user-facing documentation in the same pull request.

---

## User and workflow model

The project has three distinct workflows with different ownership. Their products must be separable so that a specification mapping can be reviewed and shared independently of one site's data export and independently of runtime operation.

### 1. Specification and target-mapping workflow

**Primary user:** specification / mapping maintainer.

This workflow turns an ART-DECOR release and transaction into compiled models and a reviewed mapping to one HL7 target.

Typical sequence for the current CDA target:

```text
select release and transaction
        │
        ▼
fetch specification closure
        │
        ▼
build target-neutral dataset model
        +
build CDA target model
        │
        ▼
generate mapping audit and proposal
        │
        ▼
review/edit cda-mapping.json
        │
        ▼
check-cda-mapping
        │
        ▼
synthetic mapping test
```

The workflow currently corresponds approximately to:

```bash
decor2hl7 list-versions
decor2hl7 set-version <release>
decor2hl7 list-transactions
decor2hl7 set-transaction <transaction>

decor2hl7 fetch
decor2hl7 build
decor2hl7 init-cda-mapping
decor2hl7 check-cda-mapping
decor2hl7 setup-test
decor2hl7 test-cda-mapping
```

The important product is the reviewed target mapping. For CDA this is the portable `cda-mapping.json` plus its identity lock. It must not depend on any particular site's CSV layout.

A future FHIR target should follow the same ownership model and produce a corresponding reviewed `fhir-mapping.json` rather than changing the target-neutral input configuration.

### 2. Site / input configuration workflow

**Primary user:** local deployment or site administrator.

This workflow connects one installation's actual source export to the target-neutral dataset model.

It owns:

- source-file definitions and joins;
- CSV column to dataset-field mappings;
- site-specific input representations and parsing transforms;
- input-code aliases / translations;
- local identifiers and other deployment values;
- default timezone and similar site policy.

Typical sequence:

```bash
decor2hl7 propose-input --input <source-directory>
decor2hl7 init-site-config
```

`propose-input` may inspect source filenames, headers, and observed coded values to make suggestions. It must not infer clinically or structurally important relationships such as joins, cardinalities, or occurrence identity from coincidental source content. Those relationships remain explicit configuration.

Site configuration must not modify the reviewed target mapping.

### 3. Runtime / operation workflow

**Primary user:** runtime operator or automated service.

Runtime combines:

```text
external input snapshot
        +
site configuration
        +
reviewed target mapping
        +
compiled models
        │
        ▼
ingest
        ▼
normalize
        ▼
validate
        ▼
apply target mapping
        ▼
render target HL7 representation
        ▼
state/version handling
        ▼
send / persist output
```

For CDA the current runtime commands are approximately:

```bash
decor2hl7 check-input --input <source-directory>
decor2hl7 transform --input <source-directory>
decor2hl7 run --input <source-directory>
```

Runtime must not access ART-DECOR services and must not require ART-DECOR XML.

---

## User-facing workspace

The workspace expresses ownership. Source data itself is producer-owned and remains outside the decor2hl7 workspace.

```text
# producer-owned
INPUT/
├── cases.csv
├── diagnoses.csv
├── medications.csv
└── ...

# decor2hl7-owned workspace
WORKSPACE/
├── aktin.json
│
├── config/                         acquisition-wide configuration
│   ├── sources.json                optional repository/source hints
│   └── cda-extensions.json         reviewed exact open-template attachments
│
├── spec/                           downloaded specification cache
│   └── <release>/
│       ├── manifest.json
│       ├── ... shared artifacts ...
│       └── transactions/
│           └── <transaction>/
│               └── closure.json
│
├── model/                          generated; safe to rebuild
│   └── <release>/
│       └── <transaction>/
│           ├── model.json          target-neutral dataset model
│           ├── cda.json            current target model
│           ├── mapping-audit.json
│           ├── cda-mapping.proposed.json
│           └── generated reports
│
├── mapping/                        portable/reviewable specification product
│   └── <release>/
│       └── <transaction>/
│           ├── cda-mapping.json
│           ├── cda-mapping.md
│           ├── cda-mapping-details.md
│           └── mapping-lock.json
│
├── site/                           deployment-specific configuration
│   └── <release>/
│       ├── site.json
│       └── <transaction>/
│           ├── csv-mapping.json
│           ├── csv-mapping.md
│           ├── codes-mapping.json
│           └── codes-mapping.md
│
├── test/                           disposable mapping verification
│   └── <release>/
│       └── <transaction>/
│           ├── input/
│           ├── config/
│           ├── expected.json
│           └── out/
│
├── out/                            generated runtime output
│   └── <release>/
│       └── <transaction>/
│
└── state/                          runtime send/change state
```

`mapping/` and `site/` deliberately have different owners. The same reviewed target mapping should be usable with several independent site configurations.

The current compiled target file is `cda.json`. If multiple output targets are implemented simultaneously, the generated-model layout may be refined (for example a `targets/` subdirectory), but this must not change the ownership boundaries above.

---

## Selection and scope

Release and transaction selection are state changes only. Selecting an item must not implicitly fetch or build it.

The **release** is the acquisition/cache scope. Shared datasets, templates, ValueSets, CodeSystems, and concepts are downloaded once per release.

The **transaction** is the model, mapping, site, test, and output scope within a release.

`state/` is intentionally not release-scoped; sent-state identity is based on the transaction and source record identity.

---

## Retrieval

### Network behavior

ART-DECOR access uses IPv4 by default because the observed IPv6 route is substantially slower. IPv4 selection is scoped to the ART-DECOR client; global DNS/socket monkey-patching is not acceptable.

### Closure behavior

Retrieval recursively follows the selected transaction as far as required and sensible, including datasets, templates, ValueSets, CodeSystems, concepts, `include`, `contains`, and template derivation/reference relationships.

A reviewed CDA extension attachment may add one exact template dependency to
an explicitly reachable open parent. It must be transaction-, document-,
parent-, element- and revision-specific, include a review reason, and pass CDA
core slot validation during compilation. Open-template status or generic
`context="**"` metadata alone never creates a dependency.

Already cached successful artifacts are not fetched again. Settled missing artifacts are remembered so they are not repeatedly probed unless explicitly requested.

Retrieval must avoid broad, uncontrolled crawling of unrelated external projects.

### Artifact identity and forms

Requested identity and resolved identity are distinct. Static revisions remain exact; a static reference may not silently be satisfied by a different revision. Dynamically resolved revisions are frozen once selected.

An artifact may have several representations with different purposes:

- **source** — original definition, labels, composition, provenance;
- **analysis** — compiler-facing expanded/resolved representation;
- **expansion** — materialized terminology membership where needed.

These forms are not blindly merged.

For recursive dependencies, a valid analysis representation is sufficient for
a cache hit and compiler availability. A missing source sidecar does not trigger
synchronous backfilling during an ordinary fetch; it only reduces optional
provenance or mapping evidence. The selected transaction remains a deliberate
exception because its source form controls selection and its analysis form
controls resolved definitions, so both are required.

A cache-only fetch mode must make no network requests. It may reconstruct a
completed closure from valid files already under `spec/`; uncached references
remain explicitly unavailable and retryable by a later online fetch.

Dynamic and exact request aliases that resolve to one artifact should point to one canonical stored artifact record.

External publisher content is currently an open, provisional boundary
(`DEC-012`). A small exact-identity catalog may materialize a reviewed bundled
supplement or record an evidence-backed waiver during `fetch`, including in
cache-only mode. Such provenance must remain distinguishable from ART-DECOR;
waivers and partial content may not masquerade as successful complete artifacts.
The package must not grow a generic web-scraping subsystem without a reviewed
decision.

### Resolution order

Repository/project resolution should prefer strong context before probing:

1. explicit reference project/prefix/link context;
2. configured source hints;
3. cached artifact-owner index / BBR ownership information;
4. other known ownership metadata;
5. OID-prefix inference;
6. HTTP probing as a last resort.

Ownership information determines where to look, not whether the artifact is semantically required.

### Crawl completion versus build readiness

A complete crawl can contain unavailable artifacts. Therefore `crawl_complete` and `build_ready` are separate states.

References carry a role/reason. Missing structural or formally required terminology may block the affected build; mapping/display evidence may only reduce confidence and produce warnings.

The implementation must tolerate unavailable artifacts that are not needed to compile or execute the selected target mapping.

---

## Target-neutral dataset model

The selected transaction is the primary authority for the current data model.

Older/project material may contribute lineage or fill explicitly missing properties, but must not silently union older children or value domains into the selected transaction.

The compiled model preserves distinctions such as:

- groups and fields;
- repeat chains / occurrence identity;
- logical value domains;
- owned inline coded-domain identity and open/enumerated/reference status;
- exact formal terminology bindings;
- option associations;
- concept associations;
- provenance.

Logical source choices are not automatically formal codes. Any lossy or ambiguous source-to-formal-domain conversion requires an explicit crosswalk or mapping decision.

The target-neutral model is the stable boundary shared by CDA today and possible FHIR output later.

---

## Target models

A target implementation compiles the selected HL7 output specification into a form usable for mapping, validation, and rendering.

### CDA target

The current CDA target compiles exact reachable templates, recursive `SPEC` refinement, `INCLUDE` / `CONTAINS`, fixed constraints, vocabulary, and assertions.

It also expands CDA/RIM structural classes and the HL7 V3 datatypes declared by
that effective template from the pinned CDA R2 XSD graph cached under `spec/`.
ART-DECOR constraints refine the generic structure. Transparent `include` and
`contains` wrappers retain provenance but do not create an XML level: an
explicit child supplied through either wrapper satisfies the corresponding
CDA/RIM particle and is not accompanied by a second generic child. Structural
CDA nodes and explicit writable value targets remain distinct; mapping and
rendering consume each target's compiled value representation instead of
guessing from XML path names, class names, or datatype names.

It distinguishes:

- **physical CDA targets** — actual writable constraints in the compiled template;
- **logical CDA datapoints** — the reviewable/mappable target interface after structural semantics are taken into account.

Usually these are 1:1. They may differ for discriminated repetitions. For example:

```text
Pupilsize_right.value ─┐
                      ├──> physical repeatable Pupilsize.value
Pupilsize_left.value  ─┘
```

The logical target names used in configuration must be the same names used by reports, validation, tests, and runtime assignment.

### Future targets

A future FHIR target should expose the analogous concepts required for mapping and rendering while reusing the target-neutral dataset model and generic mapping infrastructure.

Target-specific concerns such as CDA `nullFlavor`, CDA template identity, FHIR profiles, slices, extensions, and FHIR missing-data conventions belong inside the target implementation rather than the common input/model layer.

---

## Mapping model

Mapping is the combination of **evidence** and a **reviewed decision**.

Rich candidate evidence should be retained separately from the concise editable mapping configuration.

The canonical analysis product is `mapping-audit.json`; generated mapping proposals and human-readable mapping documentation should be derived from the same decision/evidence source so they cannot silently disagree.

### Scalar mappings

The built-in transform language stays deliberately small and declarative. Current primitives include:

- `identity`;
- `enum`;
- `ordinal`;
- `not`;
- `code_system`;
- `coded_fallback` — preserve only exact target-member code/system pairs and
  otherwise carry source wording through a target-defined `OTH` fallback.

Clinical semantics should not accumulate as target-specific Python conditionals when a small declarative rule can express them.

### Structural mappings

Structural behavior is explicit. Current CDA work uses generic concepts such as:

- `for_each` — preserve one source occurrence as one target occurrence;
- `repeat_by_discriminator` — turn semantically distinct sibling fields into
  separate target occurrences only when a required coded discriminator, its
  exact ValueSet revision and a unique source-facet/member correspondence are
  available;
- `coalesce` — let equivalent source values share one target, conservatively using `equal_or_error` unless configured otherwise;
- `fallback` — fill an absent target leaf without replacing a real value.

These concepts should remain as target-independent as practical, while target adapters provide the target-specific placement and discriminator details.

### Explicit constants and deliberate non-mappings

A target requirement may be supplied by an explicit constant/fallback where specification semantics support it; a fake source datapoint should not be invented merely to populate a target leaf.

A deliberately empty mapping is a valid reviewed decision. It must not make the whole mapping unusable. Target-specific rendering policy decides how a required instantiated element represents absence. For CDA the default missing-information representation is normally `nullFlavor="NI"`; `UNK`, `MSK`, `OTH`, etc. carry distinct meanings and must not be conflated with a deliberately absent source mapping.

---

## Input and occurrence semantics

Source data is linked across files by configured identifiers and joins.

Data with 1:n relationships may live in separate source files. Repeated data retains explicit occurrence identity; a missing value in one occurrence must never shift another occurrence into its place.

Nested independent repetitions use configured occurrence keys. Positional guessing/zipping is intentionally unsupported where it can create ambiguous associations.

A primary-row marker may control ordering, but invalid input is reported rather than silently rewritten. Multiple primary rows are an error.

Datetime values without a timezone are interpreted using the configured site default timezone.

---

## Validation

Validation is layered:

1. acquisition/cache integrity;
2. compiled model/target integrity;
3. reviewed target mapping validity;
4. site/input configuration validity;
5. normalized record validity;
6. target-specific constraints and assertions.

The specification/mapping workflow must be verifiable without site CSV input. This is the purpose of `check-cda-mapping` and the isolated synthetic mapping fixture for the current CDA target.

Unmapped or unresolved candidate mappings remain visible; they are never silently treated as proven mappings.

---

## Generated mapping documentation

The mapping maintainer needs a concise, human-readable document that explains the reviewed target mapping and makes the corresponding JSON configuration easy to inspect and edit.

The generated documentation is not itself configuration and must never imply that illustrative target output should be edited.

The generic requirements and the current CDA specialization are defined separately in:

**[`docs/mapping-documentation-format.md`](docs/mapping-documentation-format.md)**

For CDA the generated products are expected to include at least:

- `cda-mapping.md` — concise review/implementation guide;
- `cda-mapping-details.md` — detailed candidate/evidence information;
- `mapping-audit.json` — machine-readable evidence and decisions.

A future FHIR target should be able to generate the analogous `fhir-mapping.md` / detail documentation from the same generic documentation contract.

---

## State and outgoing documents

The same unchanged source record should not be emitted twice.

A corrected or otherwise materially changed source record must be eligible for a new output document/version.

The transformation fingerprint includes clinically or semantically relevant changes in:

- normalized data;
- occurrence structure/order;
- compiled specification;
- reviewed mapping;
- relevant site configuration.

It excludes irrelevant physical properties such as absolute input-directory location or CSV line number.

State identity is scoped by transaction, conceptually:

```text
<transaction OID>::<source record key>
```

Transport remains isolated from compilation and mapping so the receiver protocol can evolve independently.

---

## Current clinical semantics and open questions

Unresolved clinical semantics must remain explicit rather than being filled by inference.

The diagnosis-certainty behaviour is decided and verified:

- V/A/Z/G maps to the formal certainty qualifier in each diagnosis occurrence;
- `A` additionally controls exclusion negation;
- the generator does not derive `effectiveTime/high` from `Z`, because
  “Zustand nach” supplies no timepoint;
- the required diagnosis onset `effectiveTime/low`, which the selected
  transaction does not supply, receives the reviewed target default
  `nullFlavor="UNK"` without inventing a date;
- the generic runtime still supports an explicitly configured, occurrence-local
  fallback, but that capability is not generated as a clinical Z rule.

The remaining diagnosis question is:

- secondary ICD-10 diagnoses: current cardinality and intended CDA repetition/relationship remain insufficiently established, therefore no delimiter parser, `CD.translation` substitution, or inferred additional diagnosis relationship is introduced.

---

## Implementation direction

The code should preserve clear target-neutral and target-specific boundaries. A reasonable long-term package shape is:

```text
src/decor2hl7/
├── cli.py
├── commands.py
├── workspace.py
├── schema.py
│
├── retrieval/               external artifact acquisition and closure
│   ├── client.py
│   ├── operations.py
│   ├── catalog.py
│   ├── references.py
│   ├── resolution.py
│   ├── store.py
│   ├── closure.py
│   └── xml.py
│
├── model/                   target-neutral dataset/terminology compilation
│   ├── artifacts.py
│   ├── transaction.py
│   └── terminology.py
│
├── mapping/                 reusable mapping analysis / transforms / docs model
│   ├── analysis.py
│   ├── structural.py
│   ├── transforms.py
│   └── documentation.py
│
├── target/
│   ├── cda/                 current target
│   │   ├── compile.py
│   │   ├── mapping.py
│   │   ├── render.py
│   │   ├── assertions.py
│   │   └── documentation.py
│   └── fhir/                future target
│       └── ...
│
└── runtime/                 target-neutral orchestration/input/state
    ├── input.py
    ├── normalize.py
    ├── validate.py
    ├── bindings.py
    ├── state.py
    └── transport.py
```

The exact module split may evolve. The important invariant is the direction of dependency: source ingestion and the normalized dataset model must not depend on CDA, and adding another HL7 target must not require redesigning site input configuration.

---

## Development priorities

1. Continue the remaining allergy payload work after the generic open-domain
   mapping made `Agens` executable at the bound allergen `playingEntity/code`:
   decide description/narrative placement and represent the derived diagnosis
   flags without treating them as substance codes.
2. Continue the remaining medication work after the common-slot projection:
   retain the now executable product name/code, dosage narrative and route;
   establish formal lot-number evidence; represent detailed dose/rate/schedule
   compound values; and align the repeatable subordinate-administration branch
   while preserving the current section-entry `for_each` rule.
3. Keep retrieval closure bounded while improving strong owner/project resolution.
4. Stabilize artifact/form and transaction/terminology compiler contracts.
5. Keep target-neutral dataset semantics separate from CDA semantics.
6. Make `mapping-audit.json` the single evidence/decision source for generated mapping products.
7. Keep the concise CDA mapping guide aligned with
   `docs/mapping-documentation-format.md` and `mapping-audit.json`.
8. Resolve remaining diagnosis semantics without undocumented inference.
9. Harden synthetic mapping coverage and runtime validation.
10. Keep the target boundary suitable for a future FHIR implementation.
