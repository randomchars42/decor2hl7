# `decor2hl7` fresh-retrieval analysis and refined restructuring plan

Date: 2026-08-27

## Outcome

The new retrieval layer preserves the selected transaction and the 177-point
transaction model, and it resolves the external IHE Medicine Entry template
successfully. The new artifacts also improve terminology labels and expose more
precise CDA attribute constraints.

The run is nevertheless not yet a trustworthy “complete build” boundary.
`closure.complete=true` currently means that the crawler has finished trying,
not that every required exact artifact exists. The compiler can also hide exact
retrieval failures by using the live project extract and, for a statically dated
template reference, by selecting a different revision.

The recommended next change remains a semantic-kernel rewrite followed by a
bounded module split. It should now begin with three retrieval/compiler contract
fixes:

1. distinguish crawl completion from build readiness;
2. pass source, analysis and expansion forms to typed compilers instead of using
   only the analysis file;
3. make static artifact revision selection exact and never let live evidence
   satisfy a required build dependency silently.

This does not call for an object-oriented rewrite. Procedural module-level
functions and plain typed data remain a good fit.

## Scope and reproducibility

| Item | Value |
|---|---|
| Archive SHA-256 | `a9c772a47b7cca43352bcedec5a1e3256ba37ae00b75f0c7e8e3e5ee4688e3b3` |
| Dataset | `2.16.840.1.113883.2.6.60.3.1.9@2023-11-20T00:00:00`, version `2025.1` |
| Transaction | `2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`, version `2026` |
| Representing template | `1.2.276.0.76.3.1.195.10.93@2026-03-25T11:04:07` |
| Release snapshot | `2026-04-27T18:50:33`, label `2026.1.2` |
| API contract recorded by fetch | ART-DECOR API `3.10.1`, OpenAPI `3.0.3` |

The fresh transaction extract has a different byte hash because two namespace
declarations are ordered differently:

| Transaction extract | Raw SHA-256 | Canonical XML SHA-256 |
|---|---|---|
| Frozen fixture | `bb63cf32e89c323086e60cc731c289b8ed0b8e474f5e15d08398a70abd17a372` | `cba9b2702a99d088ee6d9cb4377f0ffef5e721b6b244bc6c52f9ad6f902ed3a7` |
| Fresh retrieval | `39e37b8617e9a80f3bff10f5943070421ee9adf3db9ee429c1653525cd122e4b` | `cba9b2702a99d088ee6d9cb4377f0ffef5e721b6b244bc6c52f9ad6f902ed3a7` |

Golden tests should therefore hash canonical XML and a semantic summary, while
retaining the raw hash only for transport/cache diagnostics.

## Step 5: comparison with the frozen result

| Check | Frozen | Fresh | Interpretation |
|---|---:|---:|---|
| Direct transaction selections | 144: 49 groups, 95 items | 144: 49 groups, 95 items | Exact preservation |
| Compiled model | 177: 57 groups, 120 fields | 177: 57 groups, 120 fields | Exact path-set preservation |
| Parsed value-set revisions | 342 | 340 | Not a semantic regression by itself; the fetched closure is a different terminology universe |
| Exact value-set revisions referenced by selected fields | 24 | 24 | All present in both; all 24 have identical `(code, codeSystem)` member identities |
| CDA reachable revisions | 304 | 308 | Nine fresh revisions replace five old revisions, net `+4` |
| Named CDA targets | 5,532 | 5,740 | `+208` evidence targets from the changed revision inventory |
| Effective CDA elements | 986 | 986 | Document shape preserved |
| Effective CDA attributes | 647 | 647 | Document shape preserved |
| Renderable CDA targets | 1,009 | 1,009 | Preserved |
| Assertions | 13 | 13 | Preserved, with identical structured assertion data |
| Mapping coverage | 86 yes / 78 partial / 13 no | 89 yes / 75 partial / 13 no | Three diagnosis fields gain direct evidence |
| Mapping confidence | 22 strong / 57 medium / 7 weak / 91 none | 22 strong / 61 medium / 6 weak / 88 none | Net improvement |
| Executable field proposals | 53 | 54 | One net new executable proposal |
| Shared-target blocks | 6 | 8 | Two newly mapped diagnosis-code fields still require an explicit repetition/merge rule |

### Transaction and containment

The source transaction contains exactly 144 `<concept ref="…">` selections.
Every reference resolves in the analysis extract. The analysis form materializes
the selected hierarchy and the one external `contains` subtree. That subtree is
`2.16.840.1.113883.2.6.60.3.2.10.1` from dataset
`2.16.840.1.113883.3.1937.777.75.1.2@2023-10-25T11:39:22`; it accounts for the
33 additional model datapoints.

This is a strong reason for the transaction compiler to accept both forms:

- source form: authoritative selection manifest and transaction-local overrides;
- analysis form: resolved concept definitions, hierarchy and containment;
- compiler output: 144 direct selections plus 33 explicitly provenance-marked
  contained imports, not an undifferentiated 177-node tree.

### Terminology and transport

All 24 exact value-set revisions used by selected fields retain the same formal
member identities. Sixteen of those value-set records differ only in labels or
metadata. The current API extracts often preserve a German logical label in
`<name>` while retaining the formal terminology display in `@displayName`.
That is useful evidence and improves 15 fields' generated aliases.

It also reinforces the need to represent the two labels separately. They must
not be flattened into a single dictionary key.

Transport is unchanged and still demonstrates the central defect:

- logical source domain: `Bodentransportmittel`, `Lufttransportmittel`, `Ohne`;
- exact formal binding: `1.2.276.0.76.11.41@2015-11-17T00:00:00`;
- executable formal codes: `1`, `2`, `3`, `4`, `NA`, `OTH`;
- current model output still unions the two coarse logical labels into the
  formal `values` map without codes.

Only the six formal values are safe by default. Mapping a coarse logical choice
to a formal code is a lossy, explicit crosswalk decision.

### Lost field-level terminology associations

The fresh model loses 20 field-code associations across 11 fields, including
respiratory rate, systolic blood pressure, pupil size/reaction, tetanus status,
modified Rankin scale and pain score.

The data is present in the fresh transaction analysis. The loss is caused by
`build/model.py::_concept_node()`, which only accepts a direct
`terminologyAssociation` when its `conceptId` equals the current concept's ID.
Inherited associations are direct children of the selected concept but retain
the predecessor concept ID. The old build later recovered them through its much
broader lineage inputs; the fresh build-resource set does not.

The parser should preserve every direct association with its original
`conceptId` and provenance. Applicability should be decided by the transaction
compiler, not by discarding the association during XML parsing.

### CDA closure and effective constraints

The revision-set change is:

- nine fresh-only revisions, including the externally resolved IHE Medicine
  Entry `1.3.6.1.4.1.19376.1.9.1.3.1@2019-08-27T16:13:43` and newer dynamic
  revisions of several base templates;
- five frozen-only 2014 revisions replaced by later dynamic selections.

The effective document still contains 986 elements and 647 attributes. Comparing
the effective constraint trees by structural position finds only 15 property
changes:

- ten attributes gain or tighten explicit optionality;
- five attributes gain an explicit datatype.

One optionality change (`true` to `false`) is substantive; the others fill
previously unspecified values. The updated API-expanded sources are therefore
providing useful precision without changing the CDA shape.

The named-target count is not a sufficient golden by itself. It includes every
addressable constraint in every reachable revision, including constraints that
do not occur in the effective document. Golden verification should separately
record:

1. exact reachable revision set;
2. effective document constraint fingerprint;
3. evidence target registry;
4. renderable physical target registry.

### Mapping delta

Only nine of the 177 mapping rows change. The meaningful changes are in
isolation and final-diagnosis branches:

- isolation evidence becomes terminology-association based rather than only a
  weak value-set/name inference;
- the free-text final diagnosis gains an executable `originalText` target;
- primary and secondary ICD-10 diagnosis fields gain direct targets but both
  claim the same physical CDA value and remain blocked pending an explicit
  repetition/merge rule.

The fresh result is therefore slightly better, but `54/120 executable fields`
must still be treated as a proposal count, not proof that all relevant data can
already be rendered safely.

## Retrieval closure and external references

The manifest records 739 resource keys: 544 `ok`, 195 `missing`, and no request
errors. The transaction closure reports 552 build resources and 733 evidence
resources.

The build-role set itself contains missing artifacts:

| Type | OK | Missing |
|---|---:|---:|
| Dataset | 3 | 0 |
| Template | 171 | 1 |
| ValueSet | 167 | 1 |
| CodeSystem | 58 | 151 |

The two non-CodeSystem build misses are:

- template `2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00`;
- ValueSet `1.3.6.1.4.1.19376.1.3.11.11@2015-11-22T12:20:34`.

The exact CodeSystem requested for ValueSet `1.2.276.0.76.11.53`,
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`, remains unresolved. Direct
CodeSystem retrieval is still the right first operation, but this run proves
that the modern endpoint cannot guarantee that every referenced external code
system is hosted or discoverable.

The known external hint works as intended for IHE Medicine Entry:

- source server and project are used during resolution;
- source and expanded analysis forms are stored locally;
- the compiler later treats it exactly like any other template.

The owner index is valuable: it contains 1,889 type-qualified owner hints. It
should remain an ownership resolver only; it must not decide whether a reference
is build-critical.

### Why `complete=true` is currently misleading

Three behaviors mask incompleteness:

1. `crawl_build()` accepts a matching template from the unpinned live
   `project-evidence.xml` before trying to fetch and record the exact artifact.
   The selected root template `...10.93@2026-03-25T11:04:07` is consequently
   absent as a manifest resource.
2. `select_template()` may choose the newest available row even when a static
   flexibility date was requested and no exact or older row exists. The missing
   `...10.20.1.53@2005-09-07` is silently represented by
   `...10.20.1.53@2007-04-01` from live evidence.
3. 151 missing CodeSystems are placed in the hard build closure even when they
   are merely identifiers attached to already-extensional concepts and no code
   system definition is needed to compile the document.

The closure should expose two independent outcomes:

```json
{
  "crawl_complete": true,
  "build_ready": false,
  "required_missing": ["..."],
  "optional_missing": ["..."],
  "fallback_substitutions": ["..."]
}
```

## Step 6: source, analysis and expansion pairs

| Artifact type | Source + analysis | Analysis only | Source only but artifact marked missing | Missing all forms |
|---|---:|---:|---:|---:|
| Dataset | 3 | 0 | 0 | 0 |
| Template | 176 | 22 | 0 | 21 |
| ValueSet | 167 | 0 | 0 | 1 |
| CodeSystem | 58 | 0 | 32 | 119 |
| Concept | 1 | 111 | 0 | 22 |

There are 15 unique ValueSet expansion files. The manifest reports 23 successful
expansion representations because eight dynamic and exact request keys point to
the same resolved expansion file. More generally, 15 ValueSet manifest pairs
resolve to the same full artifact identity. Requested aliases and resolved
artifacts should be stored separately.

### What each representation contributes

| Form | Role |
|---|---|
| Source | Original selection/composition, human labels, provenance and server metadata |
| Analysis | Compiler-facing resolved extract; hierarchy and embedded definitions |
| Expansion | Materialized membership for intensional terminology only |

The differences are material:

- three dataset analysis forms expand 5,734 source concepts to 26,423 concept
  occurrences and add 2,718 terminology associations;
- 176 template analysis forms wrap the exact template and add linked-template
  metadata/expanded structure; every analysis form is larger in node count;
- 167 ValueSet analysis forms materialize 25,169 concept members that are not
  present as explicit members in the source forms;
- 58 CodeSystem analysis forms materialize 1,535 coded concepts versus 460 in
  source forms.

The current build uses only `entry["file"]`, which is the analysis
representation. Source and expansion paths are retained in the manifest but are
not passed to the compiler and are not cross-checked. Fetching all forms is
therefore useful, but the implementation does not yet realize that value.

The compiler should receive an artifact record with all available forms and a
form-specific policy. It should never blindly merge their members:

```json
{
  "requested": {"type": "template", "id": "...", "effective_date": "..."},
  "resolved": {"type": "template", "id": "...", "effective_date": "..."},
  "forms": {
    "source": {"path": "...", "sha256": "..."},
    "analysis": {"path": "...", "sha256": "..."}
  },
  "roles": ["cda-structure"],
  "required": true,
  "resolution": {"project": "...", "server": "...", "method": "owner-index"}
}
```

## Step 7: refined code structure

Keep the neutral `retrieval` name. The layer now visits OpenAPI, project,
publication, transaction, dataset, concept, template, ValueSet and CodeSystem
endpoints, and it may later support non-ART-DECOR sources. A vendor name would
make the boundary less accurate.

Recommended package shape:

```text
src/decor2hl7/
├── cli.py                         # argument parsing and dispatch
├── commands.py                    # workflow orchestration
├── schema.py                      # compiled schemas and version constants
├── workspace.py
├── retrieval/
│   ├── client.py                  # scoped HTTP/IPv4 request primitive
│   ├── operations.py              # current API operation URLs/capabilities
│   ├── catalog.py                 # releases and transactions
│   ├── references.py              # typed dependency extraction + reasons
│   ├── resolution.py              # owner index, hints, repositories
│   ├── store.py                   # forms, cache, manifest, hashes
│   ├── closure.py                 # crawl orchestration/readiness report
│   └── xml.py
├── compile/
│   ├── artifacts.py               # load/cross-check source-analysis-expansion records
│   ├── transaction.py             # 144 selections + explicit contains imports
│   ├── terminology.py             # logical domains, exact formal bindings, associations
│   ├── cda.py                     # exact revision selection and effective constraints
│   ├── mapping.py                 # candidates and decisions, no Markdown
│   └── reports.py                 # mapping reports and readable expanded CDA
└── runtime/
    ├── input.py
    ├── validate.py
    ├── render.py
    ├── transforms.py
    ├── state.py
    └── transport.py
```

This remains procedural. `ArtifactIdentity`, `ArtifactReference`,
`ArtifactForms`, `PropertyProvenance`, `TerminologyBinding`, `CdaVocabulary`
and `MappingDecision` should be `TypedDict`/dataclass-like immutable records,
not a service-class hierarchy.

### Dependency roles replace hard/soft

The present binary `hard_references()` / `soft_references()` distinction is too
coarse. Every reference should record why it is needed:

| Role | Examples | Missing behavior |
|---|---|---|
| `structure` | root template, `SPEC`, `INCLUDE`, `CONTAINS`, contained dataset | Build blocker |
| `formal-terminology` | exact selected field ValueSet, exact CDA ValueSet needed for compatibility | Build blocker when executable mapping depends on it |
| `expansion-support` | CodeSystem required by an intensional ValueSet include/filter | Build blocker for that expansion only |
| `mapping-evidence` | concept lineage, non-structural associations | Warning / reduced confidence |
| `display-evidence` | CodeSystem referenced by an already-extensional member | Optional |

This change would prevent 151 unavailable CodeSystems from making the closure
look catastrophically incomplete while still requiring the small number of code
systems actually needed to expand selected intensional ValueSets. In the current
model, five of the 24 selected ValueSets are intensional: four resolve through
CodeSystem `...5.102`; one remains unresolved through `...5.53`.

### Compiler contracts

1. **Artifact compiler** validates requested versus resolved identity and
   cross-checks all available forms. A static revision mismatch is an error.
2. **Transaction compiler** uses source form for selection and overrides,
   analysis form for resolved definitions, and records contained imports.
3. **Terminology compiler** produces separate `logical_domain`,
   `formal_binding`, `option_associations` and `concept_associations` properties.
4. **CDA compiler** preserves exact vocabulary flexibility and rejects a
   different revision for a static template reference.
5. **Mapping compiler** writes `mapping-audit.json`; proposal JSON and all human
   reports render from that one decision source.
6. **Runtime** continues to consume compiled JSON only.

### Implementation order

1. Add semantic/canonical golden tests for the fresh archive.
2. Introduce the artifact/form schema and manifest reader without changing
   runtime output.
3. Fix root-template retrieval, exact static revision selection, readiness
   reporting and dependency roles.
4. Rewrite transaction and terminology compilation; remove the mixed `values`
   property and preserve all direct associations.
5. Strengthen CDA compilation and generate the readable expanded CDA as a
   normal report.
6. Move mapping decisions to `mapping-audit.json`, then enforce exact
   terminology compatibility.
7. Perform mechanical module moves and retain compatibility imports for one
   release.
8. Only then implement the remaining model/CDA/mapping/runtime behavior.

### Tests to add before step 8

1. canonical transaction hash and `144 + 33 = 177` provenance;
2. selected root template is a recorded exact artifact even when present in
   project evidence;
3. live project evidence cannot satisfy a required build artifact silently;
4. a static `@effectiveDate` never selects an older or newer template;
5. `crawl_complete` and `build_ready` are independent;
6. extensional member CodeSystems are optional, intensional expansion
   CodeSystems are required;
7. source-only usable forms remain accessible even when another form is missing;
8. source/analysis identity mismatch is reported;
9. inherited direct terminology associations retain their source concept ID;
10. transport logical options never enter formal code defaults without an
    explicit crosswalk;
11. dynamic and exact request aliases resolve to one canonical artifact record;
12. mapping reports and readable CDA comments are rendered from
    `mapping-audit.json`.

## Verification performed

- The current compiler was executed over the fresh closure for model, CDA and
  mapping analysis.
- Frozen and fresh transaction XML were canonicalized and compared.
- Exact reachable template revision sets and effective constraint trees were
  compared.
- The current source package's 72 `unittest` tests pass.
- No network retrieval was run during this analysis.


