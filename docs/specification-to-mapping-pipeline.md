# Technical specification-to-mapping pipeline

This developer and technical-maintainer guide follows the setup-time pipeline
from selected ART-DECOR identity to compiled models, mapping evidence, and the
portable reviewed CDA mapping. It explains implementation boundaries and stops
before site input and runtime operation.

Specification maintainers and clinical mapping reviewers who need the
task-oriented workflow should instead start with
[`user/specification-and-mapping.md`](user/specification-and-mapping.md).

Detailed semantic rules are not repeated here. Follow the topic links for the
owner rule, decor2hl7 supplement, current effect, and evidence behind a stage.

## Pipeline

```text
release + transaction selection
              |
              v
            fetch
              |
              +-- identities, references, forms, checksums
              +-- bounded dependency and evidence closure
              v
 manifest.json + closure.json + cached XML
              |
              v
            build
              |
              +-- validated compiler inputs
              +-- transaction + terminology -> model.json
              +-- templates + CDA XSD      -> physical cda.json
              +-- generated Schematron     -> annotated cda.json
              +-- evidence + both models   -> audit + proposal
              v
      init-cda-mapping
              |
              v
 reviewed cda-mapping.json + mapping-lock.json + guides
```

The four principal products have different meanings:

| Product | Meaning | Owner |
|---|---|---|
| fetched closure | Exact reproducible specification inputs | acquisition |
| `model.json` | Target-neutral dataset and terminology contract | dataset compiler |
| `cda.json` | Physical CDA constraints and logical mapping interface | CDA compiler |
| `cda-mapping.json` | Reviewed source-to-target decisions | mapping maintainer |

## 1. Select identity

`set-version` and `set-transaction` write `decor2hl7.json`. They do not create
release or transaction artifacts. The selected OID and effective date determine
later paths and exactness checks:

```text
spec/<release>/
model/<release>/<transaction>/
mapping/<release>/<transaction>/
```

Static references must resolve to their requested revision. A dynamic reference
may be resolved once and is then frozen.

Primary code: `retrieval/catalog.py`, `workspace.py`, `cli.py`.

## 2. Fetch the closure

`fetch` starts from the selected transaction, parses typed dataset, concept,
template, ValueSet, and CodeSystem references, resolves their owner/project, and
iterates until the bounded build and mapping-evidence closure settles.

Resolution prefers explicit reference context and configured hints, then cached
owner evidence and project metadata, and probes the network only as a last
resort. Exact attempts and resolved identities remain in the manifest.

The cache retains source, analysis, complete expansion, and partial
expansion-evidence forms for their distinct purposes. The selected transaction
requires matching source and analysis forms. Ordinary dependencies can compile
from a valid analysis form without an optional source sidecar.

Reviewed CDA overlays are normalized for the exact selected transaction and
copied into `closure.json`. Exact catalog builtins, waivers, and aliases retain
their separate provenance and validation rules.

Main products:

- `manifest.json`: release-wide artifact identities, forms, checksums, and
  status;
- `artifact-owners.json`: reusable exact owner evidence;
- transaction `closure.json`: build/evidence membership, reviewed overlays,
  unavailable resources, crawl completion, and build readiness;
- deterministic cached XML and validation packages.

`fetch --offline` performs the same closure discovery from valid cache files
without network I/O.

Current retrieval rules:
[`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md).

## 3. Assemble compiler inputs

`compile/artifacts.py:compiler_inputs()` verifies the closure rather than
rediscovering it. It resolves manifest records, checks files, checksums, forms,
and exact identities, requires the selected transaction pair, admits only
complete terminology expansions, normalizes reviewed overlays, and carries
degradation into diagnostics.

Missing auxiliary evidence can remain visible and degraded. A mandatory missing
input, checksum failure, or exact-identity contradiction is fatal.

The result separates transaction source/analysis, model resources, terminology,
templates, mapping evidence, overlays, and degradation evidence.

## 4. Compose owner rules

Rule sources remain distinct:

| Source | Establishes | Does not establish |
|---|---|---|
| selected transaction | selection, usage, direct associations | unrelated dataset content |
| transaction analysis | resolved definitions and containment | replacement source identity |
| exact terminology | members and code systems | completeness from a partial response |
| ART-DECOR templates | stored constraints and executable containment | defaults from examples |
| CDA/RIM XSD | legal structure and datatype representation | clinical mappings |
| generated Schematron | validation and bounded supporting evidence | source-to-target meaning |
| reviewed overlay | one exact local attachment or branch selection | inferred owner containment |
| reviewed mapping | explicit source-to-target policy | changes to physical models |

Formal concept origins, ordinary relationships, executable template closure,
and first-SPEC prototypes keep their owner meanings throughout the pipeline.

Current composition rules:
[`topics/art-decor-authority.md`](topics/art-decor-authority.md).

## 5. Compile `model.json`

`compile/transaction.py:compile_model()` combines the selected transaction pair,
exact resources, terminology, formal origins, and current stored descendants.
It produces target-neutral groups and fields with:

- stable paths and owner identity;
- descriptions, datatype constraints, and cardinality;
- logical domain, formal terminology, and accepted input values;
- terminology associations and provenance;
- repeat owner and complete repeat chain.

After compiling the owner dataset, it applies the optional reviewed
`decor2hl7.json:model_extensions` supplement. Added fields must use an existing
parent group, cannot collide with owner paths, inherit repeat identity, and may
bind only to an exact complete local ValueSet revision. Their explicit source,
reason, status, and configuration hash remain in `model.json`; this does not
put CDA targets into the target-neutral model.

Source-side code proposals are generated from this model. CSV inspection is a
separate `propose-input` step and cannot affect `model.json`.

Current dataset rules:
[`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md).

## 6. Compile physical `cda.json`

`cda/compile.py:compile_cda()` selects exact reachable templates, applies
reviewed exact overlays, expands executable include/contains constraints, and
overlays them on the pinned CDA/RIM and datatype graph.

The result records the effective tree, physical target registry, exact source
identity, paths and locations, cardinality and conformance, closedness and
prohibitions, fixed content, vocabulary, assertions, datatype representations,
occurrence ancestors, runtime roles, and unresolved diagnostics.

A target becomes scalar-writable only when it has one unfixed, non-prohibited
physical location and a compiled value representation. Structural and ambiguous
targets remain evidence rather than writable destinations.

At this stage `cda.json:datapoints` is empty; mapping analysis adds the logical
source-facing interface later.

Current CDA rules:
[`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md).

## 7. Generate and attach conformance evidence

The build assembles exact selected template revisions and invokes the pinned
DECOR publication transform. It verifies the resulting validator before use.
The source-project audit remains report-only; exact output validation is a
separate fail-closed gate.

`compile/schematron.py` attaches a conservative subset of generated constraints
to uniquely identified physical targets. Supported evidence includes
cardinality, fixed values, bindings, required attributes, concrete types, and
narrow datatype co-occurrence clauses. Unsupported expressions remain visible
for the complete validator.

This evidence may support or reject an existing candidate, never create a
semantic bridge.

## 8. Generate mapping evidence and proposal

`compile/mapping.py` combines `model.json`, annotated physical `cda.json`, and
the bounded mapping-evidence XML graph.

Groups are placed before fields so structural context and provisional
`for_each` rules are available during scalar checks. Candidate generation then
applies physical, datatype, terminology, cardinality, occurrence, claim,
companion, and co-occurrence gates. Relationship paths remain review-only.

The compiler may derive a small declarative transform or structural rule only
from sufficient evidence. Shared or ambiguous candidates stay unselected. Each
gap records its first failing gate and reopening evidence; type-compatible
`possible_targets` remain explicitly non-semantic.

The portable mapping uses exact structure type names. `for_each` preserves an
existing repeated source group's occurrence identity at an explicit repeated
CDA ancestor. `repeat_by_discriminator` creates distinct logical occurrences
over one repeated physical CDA value target only when a required coded
discriminator proves how each source branch is labelled.

The resulting logical datapoints are written back to `cda.json`. Most logical
and physical target names are equal; discriminated repetitions may expose
separate logical names over one repeated physical target.

Current mapping rules:
[`topics/mapping-and-construction.md`](topics/mapping-and-construction.md).

## 9. Write generated products

`build` writes:

| Artifact | Purpose |
|---|---|
| `mapping-audit.json` | structured evidence, candidates, gaps, claims, rules, coverage |
| `cda-mapping.proposed.json` | concise executable proposal |
| `cda-mapping.proposed.md` | unresolved review work against the generated proposal |
| `cda-mapping-details.md` | accepted selections and full evidence |
| `cda-mapping-trees.md` | exhaustive dataset and CDA coverage |
| `cda-mapping-trees-extended.md` | Clinical and template-review coverage with exact source/template traceability and rule/gap annotations |
| `cda-expanded-readable.*` | readable effective target hierarchy |
| diagnostics and conformance reports | reproducibility and failure evidence |

The generated Markdown is documentation, not editable configuration. Its
format contract is
[`mapping-documentation-format.md`](mapping-documentation-format.md).

## 10. Initialize and review the portable mapping

`init-cda-mapping` moves the proposal across the ownership boundary into
`mapping/<release>/<transaction>/`. A new mapping starts from the proposal; an
existing mapping preserves reviewer-owned selections while refreshing derived
guides, compatible identities, and generated notes. Its `cda-mapping.md` is
rendered from the reviewed mapping and contains only decisions that remain open;
reviewed mappings, intentional nulls, and narrative-only decisions remain in
the headline, details, and exhaustive trees but not in that work queue.

`init-cda-mapping --reset` explicitly replaces reviewed state. Ordinary target
renaming migrates only through one unique stored owner identity. Structure type
names are not migrated or treated as aliases.

`check-cda-mapping` validates compiled targets, structural rules, completion
policy, intentional nulls, site requirement contracts, and the mapping lock
without requiring site CSV input. Concrete site values and complete CDA
conformance are later gates.

The selected reference transaction's non-obvious human decisions are summarized
in [`reference-transaction.md`](reference-transaction.md).

## Code map

| Stage | Primary implementation |
|---|---|
| selection | `workspace.py`, `retrieval/catalog.py`, `cli.py` |
| reference extraction and resolution | `retrieval/references.py`, `retrieval/resolution.py` |
| recursive fetch and cache | `retrieval/fetch.py`, `retrieval/artifacts.py` |
| compiler input validation | `compile/artifacts.py` |
| dataset and terminology | `compile/transaction.py`, `domain.py` |
| CDA structure and values | `cda/core.py`, `cda/datatypes.py`, `cda/compile.py` |
| conformance evidence | `conformance.py`, `compile/schematron.py` |
| mapping and reports | `compile/mapping.py`, `compile/structural.py`, `compile/reports.py` |
| site input proposals | `compile/site.py` |

Site input, runtime construction, state, and delivery are documented in
[`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md).
