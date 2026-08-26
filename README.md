# decor2hl7

`decor2hl7` transforms flat clinical CSV exports using an ART-DECOR project
release and transaction. CDA is the first target. The normalized dataset model
is target-neutral so future FHIR/HL7 targets can reuse ingestion,
normalization and validation.

The project is a clean rewrite of the earlier prototype. Runtime has no
third-party dependencies; implementation is procedural, typed, and unit-testable.
Python **3.10.8 or newer** is supported.

## Workflow

Selection is explicit and separate from fetching:

```bash
decor2hl7 init

decor2hl7 list-versions
decor2hl7 set-version 2026.1.2

decor2hl7 list-transactions
decor2hl7 set-transaction notaufnahmeregister--60

decor2hl7 fetch
decor2hl7 build
decor2hl7 propose-input --input /data/aktin/export
decor2hl7 config
```

Both catalogs print a `KEY`; pass that key to the corresponding `set-*` command.
`list-versions FILTER` and `list-transactions FILTER` optionally narrow the
printed catalog.

Changing the selected release clears the transaction selection. Selection
commands modify only `aktin.json`; they never create version/transaction
artifact directories.

Input/runtime commands are separate from workspace validation:

```bash
decor2hl7 check
decor2hl7 check-input --input /data/aktin/export
decor2hl7 transform --input /data/aktin/export
decor2hl7 run --input /data/aktin/export
```

`build` and `check` never read CSV input. `propose-input`, `check-input`, `transform`, and `run` use the explicit `--input` directory first and otherwise fall back to `aktin.json` `input.directory`.

ART-DECOR network access uses **IPv4 by default** because the IPv6 route used
during development was dramatically slower. `--ipv6` is a diagnostic override
scoped to ART-DECOR requests; global socket resolution is never monkey-patched.

## Workspace and input

Source CSVs are external to the decor2hl7 workspace. The producer owns the input directory; decor2hl7 only reads one coherent snapshot from it.

```text
# producer-owned
INPUT/
    cases.csv
    medications.csv
    ...

# decor2hl7-owned workspace
aktin.json
state/

spec/
└── 2026.1.2/
    ├── manifest.json
    ├── project.xml
    ├── project-evidence.xml
    ├── project-index.xml
    ├── datasets/
    ├── concepts/
    ├── templates/
    ├── valuesets/
    └── transactions/
        └── notaufnahmeregister--60/
            ├── transaction.xml
            └── closure.json

model/
└── 2026.1.2/
    └── notaufnahmeregister--60/
        ├── model.json
        ├── cda.json
        ├── *.proposed.json
        └── *.md

config/
└── 2026.1.2/
    ├── site.json
    └── notaufnahmeregister--60/
        ├── csv-mapping.json
        ├── codes-mapping.json
        └── cda-mapping.json

out/
└── 2026.1.2/
    └── notaufnahmeregister--60/
        └── *.xml
```

The input root is passed to data-consuming commands with `--input PATH`, or set as a deployment default in `aktin.json`:

```json
{"input": {"directory": "/data/aktin/export"}}
```

Relative source filenames in `site.json` are resolved below that root. The input path is diagnostic provenance only and is never part of sent-state fingerprints. `init` does not create or own a `raw/` directory.

The **release is the acquisition/cache scope**. Shared datasets/templates/value
sets/concepts are downloaded once per release. The **transaction is the
model/config/output scope**. `closure.json` records which shared resources a
transaction actually uses.

`state/` is deliberately release-independent. Sent-state keys contain the
transaction OID plus the raw record key, so two transactions can process the
same source case independently while a later release of the same transaction
still detects unchanged/corrected data.

## Fetching

`fetch` consumes the already selected release and transaction; it contains no
selection logic.

It downloads the pinned project, selected transaction, a global project index,
and one unpinned snapshot of the **selected/main project only** (normally
`aktin-`) used **only as mapping evidence**. Whole unpinned external building-
block projects are never downloaded. It then recursively follows typed
references to:

- datasets (`RetrieveDataSet`)
- templates (`RetrieveTemplate`, `expandedxml`)
- value sets (`RetrieveValueSet`)
- individual concepts (`RetrieveConcept`) only when no containing dataset is
  available

Whole datasets are preferred over individual concept requests. A global
`ProjectIndex` is used to resolve the owning prefix for OIDs when possible,
which avoids repeated guessing and handles stale prefixes in historical links.
HTTP 200 responses containing an empty `<return/>` are treated as not-found.
Known terminal failures are recorded in `manifest.json` and skipped on later
runs unless `--retry-missing` is given.

The pinned project/transaction define build truth. The live main-project file is
read directly for local history and associations, while external evidence is
recursively fetched only for concepts/templates already relevant to the selected
transaction. `project-evidence.xml` may supply a missing historical template
definition only as a fallback: primary pinned/downloaded definitions always win,
and fallback definitions newer than the selected release are ignored.

Dynamic external references are frozen after their first resolution: the
manifest records both the requested `dynamic` binding and the resolved
`effectiveDate`, and a missing cache file is refetched using that resolved date.
`--max-requests` limits actual recursive HTTP attempts rather than merely logical
resource count.

## Generated models

`build` is completely CSV-independent. It compiles ART-DECOR into the runtime models and generates the model-to-CDA proposal only. `propose-input` is the explicit, optional CSV-inspection step: it compares CSV headers with model field names and reads observed values from proposed coded columns to generate `csv-mapping.proposed.json` and `codes-mapping.proposed.json`. It does not infer source relationships, cardinalities, or joins.


- `model.json`: groups plus value-bearing dataset fields and canonical coded
  values.
- `cda.json`: reachable CDA template constraints, compiled document structure,
  formal ART-DECOR assertions, and readable writable target names such as
  `PatientIdentifier.id` or `ersteinschatzung.effectiveTime`.
- `cda-assertions.sch`: ISO Schematron containing the original effective
  ART-DECOR `<assert>` expressions and `<let>` variables.

CDA `SPEC` relationships are compiled as constraint refinement at every tree
depth. A specialized constraint inherits omitted constraints from a matching
parent node, while parent-only prototype choices are dropped. Reused ART-DECOR
element IDs provide structural identity when a specialization replaces a
`contains` target; the old containment therefore cannot survive as a duplicate
branch.

Fixed element text and fixed attributes are compiled as template constraints,
not writable targets. `conformance="NP"` nodes are prohibited and never emitted.
A writable target must resolve to exactly one physical document location;
ambiguous targets stay in `cda.json` for evidence/provenance but cannot be
selected for rendering. `decor2hl7 check` verifies these compiled-model
invariants before transformation.

## Mapping configuration

Generated proposals/reports are transaction-specific under `model/`:

```text
# generated by `propose-input`
csv-mapping.proposed.json     csv-mapping.md
codes-mapping.proposed.json   codes-mapping.md

# generated by `build`
cda-mapping.proposed.json     cda-mapping.md
```

`propose-input` is intentionally heuristic and input-local. Source filenames, case source, 1:1/1:n cardinalities, join columns, and occurrence semantics remain explicit configuration rather than inferred relationships.

`decor2hl7 config` copies proposals to transaction-specific `config/` only when
the user file does not already exist. `site.json` is release-specific and is
also never overwritten.

### CSV → model

Logical sources map to relative filenames under the external input root via release `site.json`; for example `cases` may resolve to `cases.csv`. Upstream programs do not need to know or modify the decor2hl7 workspace layout.


```json
{
  "version": 1,
  "join": {"column": "patient_id"},
  "fields": {
    "administrative_aufnahmeinformationen.aufnahmezeitpunkt": "cases:aufnahmezeitpunkt",
    "notfallanamnese.beschwerden_bei_vorstellung.beschwerden_bei_vorstellung_freitext": null
  }
}
```

### Raw code → dataset value

```json
{
  "version": 1,
  "fields": {
    "ersteinschatzung.parameter_der_ersteinschatzung.ergebnis_der_ersteinschatzung": {
      "1": "rot",
      "2": "orange",
      "3": "gelb"
    }
  }
}
```

Unmapped raw codes become `nullFlavor="OTH"` by default.

### Model → CDA

```json
{
  "version": 2,
  "fields": {
    "patient.identifikatoren.patienten_id": "PatientIdentifier.id",
    "ersteinschatzung.parameter_der_ersteinschatzung.zeitpunkt_der_ersteinschatzung": "ersteinschatzung.effectiveTime",
    "scores.modified_rankin_skala_score": {
      "target": "Modifiedrankinscale.observation.value",
      "transform": {"type": "ordinal", "map": {"keine Symptome": 0, "Tod": 6}}
    },
    "masnahmen.wildcard_therapie.code": null
  }
}
```

The editable mapping contains only a selected readable target that is safe for
direct execution. The Markdown report is broader: it contains ART-DECOR OIDs,
evidence chains, confidence, alternatives, ambiguities, and links that require a
semantic transform before they can be executed. A strong formal association is
therefore never discarded merely because it is not a direct datatype-compatible
assignment.

`ADAPT` relationships are followed and retained as mapping evidence, but they do
not automatically copy omitted dataset constraints into `model.json`: adaptation
means the related concept/design may have been changed. Identity-style lineage
(`SPEC`, `INHERIT`, `ORIGINAL`, `EQUIV`, `COPY`, `VERSION`) may enrich omitted
model constraints; `ADAPT`/derivation remains evidence unless an explicit target
mapping or transform proves the runtime semantics.

Direct `implementation/@xpath` declarations are treated as explicit technical
mapping evidence when they uniquely resolve to a current writable CDA target.

`cda-mapping.json` version 2 may also contain declarative rules. The generated
proposal currently derives only semantics supported by the specification itself:
Tetanusschutz drives `negationInd` plus `nullFlavor=NI` for unknown status,
Isolation drives `negationInd`, and modified Rankin labels map to their numeric
`{score}` value. The transform vocabulary is intentionally small (`identity`,
`enum`, `ordinal`, `not`) and remains data rather than clinical Python code.

## Runtime

```bash
decor2hl7 check
decor2hl7 transform
decor2hl7 send
# or
decor2hl7 run --send
```

Runtime is intentionally boring:

```text
CSV → model paths → code normalization → validation → CDA targets → CDA
```

Missing required values use configurable `nullFlavor="NI"` by default. Naive
datetimes use the configured timezone. `1:n` CSV sources preserve source order
**and occurrence identity**: repeated groups are normalized as structured rows,
so an absent value in occurrence 1 cannot shift occurrence 2 into its place. An
optional primary flag can move one row first, and duplicate primary flags are
reported/demoted deterministically. Nested independent repetitions use explicit
`occurrence_keys` for every repeat level; those keys allow several CSV sources to
join the same outer/inner occurrences without positional zipping.

After rendering, effective ART-DECOR assertions are evaluated against the complete
CDA. Error-level failures abort document generation; warning-level failures are
reported. Unsupported future error expressions are also fatal rather than silently
ignored.

Sent-state fingerprints include normalized occurrence values plus a
transformation-context fingerprint (selected specification/model, mappings, site
configuration and renderer identity) but deliberately exclude CSV row-number/source
provenance. Thus unchanged clinical input can still produce a correction when the
transformation semantics materially change. Pending documents from an older source
state are removed before a newer/invalid state is processed, and unsent pending
documents for records no longer present in the input are pruned. History rotation
is based on the first entry timestamp, not file modification time.

See `docs/architecture.md` for package boundaries and `docs/known-issues.md` for intentionally remaining work.
