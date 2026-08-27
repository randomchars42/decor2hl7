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
    ├── api.json
    ├── manifest.json
    ├── artifact-owners.json        # exact artifact revision → repository
    ├── project.xml                 # project configuration
    ├── project-evidence.xml        # live analysis evidence only
    ├── project-directory.xml
    ├── datasets/
    ├── concepts/
    ├── templates/
    ├── valuesets/
    ├── codesystems/
    └── transactions/
        └── notaufnahmeregister--60/
            ├── transaction.source.xml
            ├── transaction.xml
            └── closure.json

model/
└── 2026.1.2/
    └── notaufnahmeregister--60/
        ├── model.json
        ├── cda.json
        ├── mapping-audit.json
        ├── cda-expanded-readable.xml
        ├── cda-expanded-readable.md
        ├── *.proposed.json
        └── *.md

config/
├── sources.json                    # optional repository-hint overrides
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

The **release is the acquisition/cache scope**. Shared datasets, templates,
value sets, code systems, and concepts are downloaded once per release. The **transaction is the
model/config/output scope**. `closure.json` records which shared resources a
transaction actually uses.

`state/` is deliberately release-independent. Sent-state keys contain the
transaction OID plus the raw record key, so two transactions can process the
same source case independently while a later release of the same transaction
still detects unchanged/corrected data.

## Fetching

`fetch` consumes the already selected release and transaction; it contains no
selection logic.

It validates the server capabilities from its OpenAPI description and uses only
the current API below `/exist/apps/api`; the sunsetted Release-2 `Retrieve*`
services are not retained as fallbacks. It downloads the selected transaction,
project configuration, global project directory, and one live extract of the
**selected/main project only** (normally `aktin-`) used **only as mapping
evidence**. Whole external building-block projects are never downloaded. It
then recursively follows typed references to datasets, templates, value sets,
code systems, and (where needed) individual concepts.

The selected transaction and exact recursively resolved artifact revisions are
build truth. For templates, value sets, and code systems, both a source form and
an analysis form are retained. Template analysis uses the API's expanded tree
(`$extract?tree=expand`); intensional value sets also request `$expand` when
available. Source files remain provenance/debugging material, while analysis
files provide resolved definitions. The compiler receives both forms, uses the
transaction source as selection truth, and cross-checks their identities. The
global project directory is used to resolve the
owning project for OIDs when possible, avoiding repeated guessing and handling
stale project metadata in historical links.

Repository candidates are ordered by authoritative longest OID owner, explicit
reference prefix/link context, cached exact artifact owner, and finally the
configured building-block repositories. The owner cache key includes type, OID
and effective date. Extensional member CodeSystems are recorded as optional
display evidence without causing HTTP requests; only CodeSystems needed for an
intensional expansion are build dependencies.

HTTP 200 responses containing an empty `<return/>` are treated as not-found.
Known terminal failures are recorded in `manifest.json` and skipped on later
runs unless `--retry-missing` is given.

The live main-project file is read directly for local history and associations,
while external evidence is fetched only for concepts/templates already relevant
to the selected transaction. `project-evidence.xml` is mapping evidence only: it
never satisfies the representing template or another build dependency. A
statically dated reference must resolve to that exact revision.

Known cross-project references are data-driven. The bundled source catalog, plus
an optional `config/sources.json` override with the same shape, can supply an API
base, project, and exact effective date that an XML reference omits. Once the
source is resolved, recursive template analysis is identical for local and
external artifacts; no template-specific special case exists in the compiler.

Dynamic external references are frozen after their first resolution: the
manifest records both the requested `dynamic` binding and the resolved
`effectiveDate`, project, API base, source and expanded representation URLs, and
checksums. A missing cache file is refetched using that exact resolved date.
`--max-requests` limits actual recursive HTTP attempts rather than merely logical
resource count.

`closure.json` separates `crawl_complete` from `build_ready`. A crawl may settle
all requests while a required artifact is unavailable; `build` rejects that
state and reports the exact identities. Missing optional display or mapping
evidence does not block compilation. Closures written before this distinction
are rejected conservatively and must be refreshed with `decor2hl7 fetch`.

## Generated models

`build` is completely CSV-independent. It compiles ART-DECOR into the runtime models, generates the model-to-CDA proposal, and writes a populated `codes-mapping.proposed.json` directly from the model terminology. `propose-input` is the explicit, optional CSV-inspection step: it compares CSV headers with model field names and augments the code proposal with any additional raw values observed in proposed coded columns. It does not infer source relationships, cardinalities, or joins.


- `model.json`: groups plus value-bearing dataset fields. Logical dataset
  options, formal transaction terminology, direct terminology associations and
  executable accepted values are distinct; formal transaction membership wins
  when both domains exist.
- `cda.json`: reachable CDA template constraints, compiled document structure,
  formal ART-DECOR assertions, and readable writable target names such as
  `PatientIdentifier.id` or `ersteinschatzung.effectiveTime`.
- `cda-assertions.sch`: ISO Schematron containing the original effective
  ART-DECOR `<assert>` expressions and `<let>` variables.
- `mapping-audit.json`: structured candidates, evidence, confidence, conflicts
  and executability decisions behind the mapping reports.
- `cda-expanded-readable.xml` and `.md`: the effective CDA tree with human
  descriptions and XML comments linking nodes, source templates and dataset
  paths.

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

# generated by `build` (and code aliases augmented by `propose-input`)
codes-mapping.proposed.json   codes-mapping.md
cda-mapping.proposed.json     cda-mapping.md
cda-mapping-details.md
mapping-audit.json
cda-expanded-readable.xml     cda-expanded-readable.md
```

`propose-input` is intentionally heuristic and input-local. Source filenames, case source, 1:1/1:n cardinalities, join columns, and occurrence semantics remain explicit configuration rather than inferred relationships.

`decor2hl7 config` copies proposals to transaction-specific `config/` when the
user file does not yet exist. Existing user selections are never overwritten.
For `codes-mapping.json`, newly generated non-null canonical/code defaults are
added when missing so terminology updates become usable without discarding user
edits. `site.json` is release-specific and is never overwritten.

`cda-mapping.md` is the working report for completing the mapping: it includes
selected targets, reasons, alternatives, and suggested actions, but omits long
provenance chains. `cda-mapping-details.md` adds the build summary, evidence
chains, scores, template/element identifiers, and structural group context.

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
