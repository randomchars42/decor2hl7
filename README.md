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
decor2hl7 init-cda-mapping
decor2hl7 check-cda-mapping
decor2hl7 setup-test
decor2hl7 test-cda-mapping
decor2hl7 validate-cda test/2026.1.2/notaufnahmeregister--60/out/TEST-1.xml
```

The complete setup-time path from ART-DECOR parsing through rule composition,
model compilation, mapping evidence, and the reviewed mapping bundle is
described in
[`docs/specification-to-mapping-pipeline.md`](docs/specification-to-mapping-pipeline.md).
Testing and runtime processing are intentionally documented as separate
workflow stages.

Both catalogs print a `KEY`; pass that key to the corresponding `set-*` command.
`list-versions FILTER` and `list-transactions FILTER` optionally narrow the
printed catalog.

Changing the selected release clears the transaction selection. Selection
commands modify only `aktin.json`; they never create version/transaction
artifact directories.

This first workflow produces the shareable `mapping/<release>/<transaction>/`
bundle. A local administrator can then configure a concrete CSV export without
changing that bundle:

```bash
decor2hl7 propose-input --input /data/aktin/export
decor2hl7 init-site-config
```

Input/runtime commands are separate from both setup workflows:

```bash
decor2hl7 check
decor2hl7 check-input --input /data/aktin/export
decor2hl7 transform --input /data/aktin/export
decor2hl7 run --input /data/aktin/export
```

`build`, `check-cda-mapping`, and `setup-test` never read site CSV input.
`propose-input`, `check-input`, `transform`, and `run` use the explicit
`--input` directory first and otherwise fall back to `aktin.json`
`input.directory`. Runtime commands accept `--cda-mapping FILE` and
`--site-config DIRECTORY`; this permits a reviewed mapping to be shared while
each site retains its own input/code configuration.

When a published ART-DECOR `SPEC` child explicitly weakens a parent constraint,
`build` follows the executable child constraint and records a warning in the
build diagnostics. Use `build --strict-specializations` to reject such designs
instead.

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
    ├── validation/
    │   ├── package-lock.json       # pinned versions, URLs and checksums
    │   ├── packages/               # DECOR-core and complete CDA archive
    │   ├── tools/                  # pinned Saxon-HE and XML resolver
    │   ├── decor-core/             # safely extracted DECOR rules
    │   └── cda-core/               # complete normative + SDTC XSD graph
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
        ├── cda-mapping.proposed.json
        ├── codes-mapping.proposed.json
        ├── conformance-validation/
        │   ├── build-conformance.json
        │   ├── build-conformance.md
        │   ├── cda-template.sch
        │   ├── cda-template.xsl
        │   └── validator-manifest.json
        └── *.md

config/
├── sources.json                    # optional repository-hint overrides
└── cda-extensions.json             # optional reviewed exact CDA profile overlays

mapping/                            # shareable/reviewable specification product
└── 2026.1.2/
    └── notaufnahmeregister--60/
        ├── cda-mapping.json
        └── mapping-lock.json

site/                               # deployment-specific configuration
└── 2026.1.2/
    ├── site.json
    └── notaufnahmeregister--60/
        ├── csv-mapping.json
        └── codes-mapping.json

test/
└── 2026.1.2/
    └── notaufnahmeregister--60/
        ├── input/                  # generated cases.csv + repeat-group CSVs
        ├── config/                 # generated CSV/code/site test bundle
        ├── out/                    # CDA documents + results.json/results.md
        └── expected.json           # identities, hashes and expected coverage

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
model/mapping/site/test/output scope**. `closure.json` records which shared resources a
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
build truth. When a new template, value set, or code system is retrieved, its
available source and analysis forms are retained. Template analysis uses the
API's expanded tree
(`$extract?tree=expand`); intensional value sets also request `$expand` when
available. Analysis files provide the compiler-facing definitions and are
sufficient for a dependency cache hit and build availability. Source sidecars
remain optional provenance and mapping evidence; an ordinary rerun does not
backfill a missing source sidecar when valid analysis XML is already cached.
The selected transaction is stricter: its source and analysis forms are both
required and their identities are cross-checked. The global project directory
is used to resolve the
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

`decor2hl7 fetch --offline` performs a cache-only closure pass and makes no HTTP
requests. It is intended for resuming after an interrupted fetch while
ART-DECOR is unavailable: valid files already under `spec/` repair their
manifest entries and participate in closure discovery. Referenced artifacts
that are not cached are recorded as temporarily `unavailable`, so `build` can
report a degraded omission where allowed and a later ordinary `fetch` will try
them again. The selected transaction source/analysis pair must already be
cached; otherwise the offline fetch is not build-ready.

The live main-project file is read directly for local history and associations,
while external evidence is fetched only for concepts/templates already relevant
to the selected transaction. Exact concepts named by selected-template
`templateAssociation` or `staticAssociations/origconcept` declarations are
retrieved as analysis-only mapping evidence. Their transitive closure follows
only identity-style concept relationships (`SPEC`, `INHERIT`, `ORIGINAL`,
`EQUIV`, `VERSION`, `COPY`); `ADAPT`, other derivations, templates, terminology,
and unrelated dataset siblings do not expand this evidence crawl.
`project-evidence.xml` is mapping evidence only: it never satisfies the
representing template or another build dependency. A statically dated reference
must resolve to that exact revision.

Known cross-project references are data-driven. The bundled source catalog, plus
an optional `config/sources.json` override with the same shape, can supply an API
base, project, and exact effective date that an XML reference omits. A top-level
`oid_owners` object can route a reviewed OID prefix before blind repository
probing; the fetched global project directory always has higher precedence.
Every failed request and ordered project candidate remains in the manifest and
transaction closure. Once the source is resolved, recursive template analysis
is identical for local and external artifacts; no template-specific special
case exists in the compiler.

```json
{
  "oid_owners": {"1.2.3": "reviewed-project-"},
  "artifacts": {
    "template:malformed-id": {
      "mode": "alias",
      "alias_of": "template:corrected-id",
      "reason": "Reviewed correction of the published identity"
    }
  }
}
```

Aliases request only the corrected identity but preserve both identities and
the reason in `manifest.json`. They satisfy a closure dependency only when the
corrected target is successful.

An open ART-DECOR template permits additional CDA-valid content, but neither
`context="**"` nor project membership identifies which standalone template
belongs in that slot. A reviewed acquisition-wide profile overlay may be recorded
in `config/cda-extensions.json`. An attachment rule adds its exact target template to the
structural closure and stores the normalized record in `closure.json`; `build`
then requires an exact selected document, an explicitly reachable open parent,
a parent element declared by that template, and a wrapper/root placement
admitted by the pinned CDA core XSD.

```json
{
  "format": 1,
  "attachments": [
    {
      "transaction_id": "2.16.840.1.113883.2.6.60.3.4.60",
      "transaction_effective_date": "2026-03-25T00:00:00",
      "document_template_id": "1.2.276.0.76.3.1.195.10.93",
      "document_template_effective_date": "2026-03-25T11:04:07",
      "parent_template_id": "1.2.276.0.76.3.1.195.10.73",
      "parent_template_effective_date": "2024-08-15T11:08:15",
      "parent_element_id": "2.16.840.1.113883.2.6.60.3.9.196",
      "element_name": "hl7:entry",
      "template_id": "1.2.276.0.76.3.1.195.10.85",
      "template_effective_date": "2024-05-24T00:00:00",
      "minimum_multiplicity": 0,
      "maximum_multiplicity": 1,
      "conformance": "R",
      "reason": "Reviewed placement in the open Addendum section"
    }
  ]
}
```

Repeat the attachment with a different exact target template when several
reviewed entries occupy the same repeat-capable CDA particle. Attachments are
rejected below closed elements, for parents outside the explicit selected
closure, when the exact target is unavailable, for CDA-illegal particles, and
when upstream containment already selects the same target.

The same file can select an exact sibling already declared by a `SPEC` parent
choice. This is a replacement, not an attachment: the selected specialization
must already contain the exact replaced branch, and both branches must occur at
the same named parent element in one exact inherited choice.

```json
{
  "operation": "select_spec_branch",
  "transaction_id": "2.16.840.1.113883.2.6.60.3.4.60",
  "transaction_effective_date": "2026-03-25T00:00:00",
  "document_template_id": "1.2.276.0.76.3.1.195.10.93",
  "document_template_effective_date": "2026-03-25T11:04:07",
  "parent_template_id": "1.2.276.0.76.3.1.195.10.67",
  "parent_template_effective_date": "2023-12-03T00:00:00",
  "parent_element_id": "2.16.840.1.113883.3.1937.777.15.9.19",
  "element_name": "hl7:consumable",
  "template_id": "2.16.840.1.113883.10.21.4.11",
  "template_effective_date": "2023-02-03T13:03:38",
  "replaces_template_id": "2.16.840.1.113883.10.21.4.10",
  "replaces_template_effective_date": "2021-09-29T19:15:16",
  "reason": "Reviewed selection of the detail medication branch"
}
```

Design prefixes such as `pharmhl7` are retained with their declared namespace
URI in `cda.json` and emitted as expanded XML names. If one reusable contained
template appears at several physical positions, its template-local target stays
non-writable; the compiler exposes stable `anchor::target` aliases for each
uniquely anchored occurrence so a reviewed mapping can select one position
without writing to all of them.

The source catalog also has a provisional external-artifact phase (`DEC-012`).
An exact entry may use `mode: "builtin"` to materialize a small reviewed XML
supplement shipped with the package, or `mode: "waiver"` to retain a cited
decision that no complete external artifact is currently available. Builtins
work with `fetch --offline`; waivers are never reported as successful artifacts.
This supplement/waiver mechanism and its initial entries remain open for
review; it is not a generic web scraper. Exact aliases are governed separately
by accepted `DEC-022`.

`fetch` also caches checksum-pinned validation inputs: DECOR-core 2.2.28, the
complete official CDA R2 normative and SDTC XSD trees at the compiler's pinned
HL7 repository commit, Saxon-HE 12.5, and XML Resolver 5.2.2. Their versions,
source URLs, checksums and license identifiers are recorded in
`validation/package-lock.json`; extracted files are individually hashed. The
complete normative CDA tree is compiler input for generic CDA/RIM structural
expansion and all packages are reused by later `--offline` runs. Java is needed
for setup/build conformance work and explicit CDA validation, but the transform
runtime retains its standard-library-only boundary.

Deleting `manifest.json` does not by itself discard the cache. On the next
fetch, valid files at their deterministic `spec/` paths are revalidated,
re-hashed and registered in a new manifest instead of being downloaded again.
Files that are absent, invalid, checksum-incompatible or inconsistent with an
exact requested revision are retrieved again when network access is allowed.

Dynamic external references are frozen after their first resolution: the
manifest records both the requested `dynamic` binding and the resolved
`effectiveDate`, project, API base, source and expanded representation URLs, and
checksums. A missing cache file is refetched using that exact resolved date.
Intensional, dynamic or otherwise incomplete ValueSets also receive frozen
`$expand` evidence when the service supplies it. Compilation and validator
generation consume the response only when its `current`/`count` totals prove a
complete, non-empty expansion. Server-capped prefixes remain cached as
`expansion-evidence`, are reported as degraded, and are not mistaken for the
whole formal domain. Exact terminology embedded in another selected build
artifact is available to both model and validator compilation.
`--max-requests` limits actual recursive HTTP attempts rather than merely logical
resource count. `fetch --fail-on-degraded` is a conservative acquisition gate
that returns nonzero when any required retrieval dependency remains degraded.
The crawl cannot yet tell which gaps a build actually consumes, so CI that
should only fail on consulted gaps uses `build --fail-on-degraded`, which
returns nonzero when `build-diagnostics.json` reports a non-empty
`build_degraded`.

`closure.json` separates crawler settlement from compiler readiness. A settled
crawl can contain unavailable recursive dependencies. `build` uses the exact
artifacts that are present and writes `build-diagnostics.json` plus a concise
`build-diagnostics.md` describing the full `crawl_degraded` set separately from
`build_degraded`, the subset actually consulted by selected formal terminology,
validator ValueSets or CDA template compilation. A validator ValueSet counts
only when the rule needing it can apply to the selected document, so a rule
skipped for a template this document never instantiates is reported but does not
degrade the build. It never substitutes another revision. The selected transaction source/analysis pair, the representing CDA
document template, identity mismatches, and corrupt successful downloads remain
fatal. Other unavailable evidence remains visible without falsely changing the
headline build status.

## Generated models

`build` is completely CSV-independent. It compiles ART-DECOR into the runtime models, generates the model-to-CDA proposal, and writes a populated `codes-mapping.proposed.json` directly from the model terminology. `propose-input` is the explicit, optional CSV-inspection step: it compares CSV headers with model field names and augments the code proposal with any additional raw values observed in proposed coded columns. It does not infer source relationships, cardinalities, or joins.


- `model.json`: groups plus value-bearing dataset fields. Logical dataset
  options, formal transaction terminology, direct terminology associations and
  executable accepted values are distinct; formal transaction membership wins
  when both domains exist. An unavailable formal binding is marked incomplete;
  logical labels are not promoted into formal codes. Owned inline coded domains
  retain their list identity and distinguish enumerated, unconstrained and
  referenced lists, so an intentional empty list is not reported as a missing
  standalone ValueSet.
- `build-diagnostics.json` / `build-diagnostics.md`: unavailable dependency
  identities split into crawl and actual-build impact, plus unresolved CDA
  template links.
- `conformance-validation/build-conformance.json` and `.md`: report-only
  DECOR source XSD/Schematron findings, exact-closure validator generation and
  the explicit status of native compiled-project validation. Source findings
  do not make `build` fail and do not change mapping coverage.
- `cda.json`: reachable CDA template constraints plus XSD-derived CDA/RIM and
  datatype structure, reviewed polymorphic datatype branches, the automatic
  model inventory, explicit writable value representations, formal ART-DECOR
  assertions, generated-Schematron supporting constraints, the bounded
  datatype co-occurrence registry, and readable target names such as
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
branch. `include` and `contains` nodes preserve template provenance but add no
XML level. An explicit element reached through them satisfies the enclosing
CDA/RIM content particle, so the compiler does not add a second generic sibling.

Fixed element text and fixed attributes are compiled as template constraints,
not writable targets. `conformance="NP"` nodes are prohibited and never emitted.
A writable target must have a datatype-defined value representation and resolve
to exactly one unfixed physical document location. Complex datatypes such as
`AD` and `PN` expose their legal child value targets even when the ART-DECOR
template declares only the parent datatype. ART-DECOR constraints refine those
generic parts. Ambiguous or structural-only targets stay in `cda.json` for
evidence/provenance but cannot be selected for scalar rendering. `decor2hl7
check` verifies these compiled-model invariants before transformation.

After successful Schematron generation, a bounded error-level datatype subset
also refines admissibility. Negated direct presence conjunctions can prove that
one parent value representation necessarily conflicts with fixed or required
children. Such a target remains visible with its source assertion but is not
selectable; explicitly named direct datatype alternatives can reopen for human
review without exposing the whole generic datatype expansion.

ART-DECOR `<choice>` branches are compiled as transparent alternatives of their
underlying CDA/RIM particle. Abstract `ANY` values expose concrete typed scalar
targets carrying their compiled `xsi:type`; the renderer remains unaware of the
clinical class or datatype choice.

The reviewed polymorphic complex root `SXCM_TS` similarly exposes concrete XSD
subtype parts beneath an explicitly typed branch while retaining one physical
element. Mapping a descendant selects its compiled `xsi:type`; generic
datatype-derived `useablePeriod` plumbing is excluded.

The compiler can also retain exact, terminology-validated construction
fallbacks from neutral template examples and compiled companion-content roles.
Explicit mapped values take precedence. ART-DECOR XPath predicates continue to
identify constraint branches but are never serialized as part of an XML tag.
Compiler-assigned system roles are likewise consumed from the compiled node.
If a shared include has several logical-target locations, only the exact
physical occurrence carrying the role receives the runtime value; the shared
target does not become writable.
Generated target names keep their compact flattened form for stable mappings;
use target `path`/`locations` or the expanded readable model when inspecting the
actual nested CDA structure.

## Mapping configuration

Generated specification proposals/reports are transaction-specific under
`model/`; input-side proposals are written under the selected `site/`
transaction after `propose-input`:

```text
# generated by `propose-input` under site/<release>/<transaction>/
csv-mapping.proposed.json     csv-mapping.md
codes-mapping.proposed.json   codes-mapping.md

# generated by `build` under model/<release>/<transaction>/
codes-mapping.proposed.json   codes-mapping.md
cda-mapping.proposed.json     cda-mapping.md
cda-mapping-details.md        cda-mapping-trees.md
mapping-audit.json
cda-expanded-readable.xml     cda-expanded-readable.md
```

`propose-input` is intentionally heuristic and input-local. Source filenames, case source, 1:1/1:n cardinalities, join columns, and occurrence semantics remain explicit configuration rather than inferred relationships.

`decor2hl7 init-cda-mapping` copies the CDA proposal and all three generated CDA
mapping guides to the shareable transaction-specific `mapping/` bundle.
`mapping-lock.json` records the release,
transaction identity, and compiled model hashes; test results record the exact
hash of the mapping that was exercised.

`decor2hl7 init-site-config` copies CSV/code proposals and their generated
guides to the local `site/` bundle. This keeps code-mapping review with the
local administrator rather than in the shareable CDA-mapping bundle. Existing
user selections are never overwritten; generated Markdown guidance is refreshed.
For `codes-mapping.json`, newly generated non-null canonical/code defaults are
added when missing so terminology updates become usable without discarding user
edits. `site.json` is release-specific by default and is never overwritten.

## CDA mapping test fixture

`setup-test` creates deterministic, pre-populated CSVs for every compiled model
datapoint, including separate `1:n` files and explicit occurrence keys for
repeat chains. It also creates a matching CSV/code/site configuration and an
`expected.json` provenance/coverage contract. It refuses to replace the
generated input/config unless `--force` is supplied.

`test-cda-mapping` runs the normal ingestion, normalization, validation,
binding, and CDA rendering code against that fixture. It never sends, writes
sent state, or uses production `out/`. The default result directory is the
fixture's own `out/`; `--out PATH` redirects only the test results:

```bash
decor2hl7 test-cda-mapping --out /tmp/aktin-mapping-review
```

The generated test is a broad executable smoke/coverage test, not a proof that
one document covers mutually exclusive template branches. Such limitations and
unmapped fields are recorded in `expected.json` and `results.md` rather than
being silently treated as covered.

## Independent CDA conformance gate

`validate-cda` validates one or more generated documents against the complete
CDA R2 SDTC schema graph and the selected transaction Schematron generated by
the pinned DECOR-core transform. When the exact compiled profile selects a
foreign-namespace subtree such as `urn:hl7-org:pharm`, a preliminary structural
check permits only those compiled paths. The base CDA XSD then validates a copy
with only those reviewed foreign elements and attributes projected out, while
the full original document is passed unchanged to the exact generated
Schematron. This does not
claim validation against a Pharmacy XSD that is absent from the pinned package:

```bash
decor2hl7 validate-cda out/TEST-1.xml
decor2hl7 validate-cda out/*.xml --report /tmp/cda-conformance
```

The command writes JSON, Markdown and SVRL evidence and exits non-zero for an
XSD or Schematron error. It also fails closed when the exact validator was
generated with unresolved terminology, its Saxon compilation probe fails, its
checksum no longer matches its manifest, or packages are missing. Generation
and compilation logs remain beside the validator. This gate is deliberately
independent of `cda-mapping.md`: passing mapping review does not prove document
conformance, and a structurally legal target does not prove a clinical mapping.

`cda-mapping.md` is the working report for completing unresolved decisions. It
contains a pruned dataset tree, a pruned CDA candidate tree and one decision card
per unmapped datapoint. Each card distinguishes semantic evidence from the
unproven type-compatible target inventory and shows annotated, generated
template constraint skeletons where context exists.
Rows that necessarily violate a compiled datatype co-occurrence assertion are
marked unavailable. A reviewed physical datatype descendant may be selected
directly even when no generated logical proposal datapoint names it; the normal
physical, datatype, occurrence, claim and conformance checks still apply.
`cda-mapping-details.md` records every accepted datapoint-to-leaf mapping with
the established entity tables, abridged JSON and contextual CDA previews, then
adds the build summary, evidence chains, scores, template/element identifiers,
and structural group context. `cda-mapping-trees.md` owns the two exhaustive
status-gutter trees. Generic datatype plumbing and fixed/system values are
excluded from the inverse coverage surface; stable identifiers remain on one
physical line. The reusable, target-neutral format is specified in
[`docs/mapping-documentation-format.md`](docs/mapping-documentation-format.md).
When selected mappings use reviewed attachment or source-resolution
configuration, the editable JSON also contains short generated
`configuration_notes`; `init-cda-mapping` refreshes those notes without
overwriting reviewer-authored notes or field choices.

### CSV → model

Logical sources map to relative filenames under the external input root via release `site.json`; for example `cases` may resolve to `cases.csv`. Upstream programs do not need to know or modify the decor2hl7 workspace layout.


```json
{
  "version": 2,
  "join": {"column": "patient_id"},
  "fields": {
    "administrative_aufnahmeinformationen.aufnahmezeitpunkt": "cases:aufnahmezeitpunkt",
    "abschlussdiagnosen.abschlussdiagnose.fuhrende_abschlussdiagnoseq_sequenznummer": {
      "source": "diagnoses",
      "column": "leading",
      "parse_as": "boolean",
      "transform": {"type": "enum", "select": "value", "map": {"true": 1, "false": null}}
    },
    "notfallanamnese.beschwerden_bei_vorstellung.beschwerden_bei_vorstellung_freitext": null
  }
}
```

Quantity columns accept a scalar number with an optional unit (`2.5 mg`) or a
low-high range (`1-2 {tablet}`). The normalized record preserves the unit:

```json
{"value": 2.5, "unit": "mg"}
```

or, for a range:

```json
{
  "low": {"value": 1, "unit": "{tablet}"},
  "high": {"value": 2, "unit": "{tablet}"}
}
```

When the transaction declares a fixed unit, a unitless input inherits it and a
different explicit unit is rejected. Range bounds must use one unit and the low
value must not exceed the high value. CDA interval quantities use their
compiler-recorded `low`/`high` targets; this input support does not by itself
select a clinical dose, rate, or timing mapping.

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
  "version": 7,
  "fields": {
    "patient.identifikatoren.patienten_id": "PatientIdentifier.id",
    "administrative_aufnahmeinformationen.aufnahmezeitpunkt": [
      "CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.low@20160601",
      {
        "target": "Allergyconcernact.low",
        "mode": "fallback_if_active",
        "reason": "Reviewed start of documenting an activated allergy concern."
      }
    ],
    "dokumentationsinformationen.beginn_patientenbezogene_dokumentation.zeitpunkt_beginn_patientenbezogene_dokumentation": null,
    "ersteinschatzung.parameter_der_ersteinschatzung.zeitpunkt_der_ersteinschatzung": "ersteinschatzung.effectiveTime",
    "scores.modified_rankin_skala_score": {
      "target": "Modifiedrankinscale.observation.value",
      "transform": {"type": "ordinal", "map": {"keine Symptome": 0, "Tod": 6}}
    },
    "masnahmen.wildcard_therapie.code": null
  },
  "defaults": {
    "required_unmapped": {"nullFlavor": "NI"}
  },
  "target_defaults": {
    "Allergyintoleranceobservation.effectiveTime": {
      "nullFlavor": "UNK",
      "reason": "The transaction does not provide the allergy onset."
    },
    "Allergyintoleranceobservation.statusCode": {
      "value": "completed",
      "reason": "The allergy assertion has been completed."
    },
    "Diagnosis.effectiveTime.low": {
      "nullFlavor": "UNK",
      "reason": "The transaction contains no diagnosis-onset datapoint."
    },
    "ProblemConcern.statusCode": {
      "value": "active",
      "reason": "This profile treats the emitted concern as actively tracked."
    }
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
When weak derivation lineage also changes the concept name, its mapping bridge is
review-only. Datatype, structural, or Schematron compatibility cannot make that
semantic identity actionable.

Direct `implementation/@xpath` declarations are treated as explicit technical
mapping evidence when they uniquely resolve to a current writable CDA target.
A legacy/profile `staticAssociations/origconcept` link can likewise be
projected to an active target when both constraints resolve to one unique common
CDA/RIM XSD slot inside the mapped context. XSD mixed-content metadata supplies
element-text writability for complex roots; neither mapping nor rendering uses
datatype- or medication-specific leaf rules.
When such an entry-text target has a required unfixed
`reference/@value`, the compiler records a linked-narrative role. Runtime writes
the mapped text into a matching section `content/@ID` fragment and generates a
distinct local reference for each entry occurrence; the fragment URI is not a
second clinical mapping value.
A static association recovered through identity ancestry does not by itself
identify the active CDA occurrence. A direct target outside an already selected
occurrence is shown as a review-only alternative; a separate explicit
`templateAssociation` remains independent evidence, and only the same unique
in-context CDA/RIM-slot projection described above can make the static
association executable.
A structurally writable datatype component can still be review-only when a
normative compound datatype requires a companion value. The compiled target
records that dependency, `check-cda-mapping` rejects incomplete reviewed
selections, and rendering verifies it for every repeated occurrence. For
example, an `EIVL_TS` offset is not executable without its event; the compiler
does not infer a TimingEvent code from labels.
Generated datatype Schematron can independently make a representation
inadmissible. The supported presence-only subset is parsed and inherited from
the current generated files, not maintained as a second reviewed datatype-rule
table. Unsupported XPath is counted and left to complete Schematron validation.
A formally coded dataset field can also map directly to an unfixed writable
CDA `hl7:code` element when both sides share an explicit ValueSet. Fixed or
differently bound structural codes, such as a section's identifying LOINC code,
remain unavailable as dataset payload targets.

An explicitly unconstrained source code can use a target-governed fallback only
below an already mapped container and only when one unique compatible CDA code
target binds an exact ValueSet with an `OTH` exception plus a compiled
`originalText` companion. Exact admitted code/code-system pairs are preserved;
other values render as `nullFlavor="OTH"` with their wording in `originalText`.

`cda-mapping.json` version 7 may also contain declarative scalar, structural,
and completion rules. The generated proposal currently derives only semantics
supported by the specification itself:
Tetanusschutz drives `negationInd` plus `nullFlavor=NI` for unknown status,
Isolation drives `negationInd`, and modified Rankin labels map to their numeric
`{score}` value. Diagnosis occurrences use `for_each`; medication occurrences
use it to create repeated entries below one shared medication section; V/A/Z/G
certainty controls the formal qualifier and exclusion negation; left/right pupil
fields use a specification-derived `repeat_by_discriminator` rule with the
bound AKTIN L/R eye ValueSet. `Aufnahmezeitpunkt` maps to encounter start, while
the differently named documentation-start concept remains unmapped. The reviewed
allergy mapping also uses `Aufnahmezeitpunkt` only to complete the concern start
after another allergy value has activated the branch. The active allergy
observation derives antibiotic and contrast-agent branches: each source
boolean is inverted into `negationInd`, while the target example supplies the
bound `A07AA` or `V08` discriminator. An explicit `Agens` with the same code and
code system is merged into that occurrence rather than duplicated; the source
disorder codes are never written as allergen codes. A `for_each` names the exact
CDA repeat node driven by its source group, so additional repeat-capable target
ancestors are not populated positionally. The transform vocabulary is
intentionally small (`identity`, `enum`, `ordinal`, `not`, `code_system`,
`coded_fallback`) and remains data
rather than clinical Python code.

Generated ordinal evidence is conservative. A bare leading integer counts only
when it appears in the option's primary label and is not part of a hyphenated
identifier. A number elsewhere in a label or synonym requires explicit
rank/score wording, and duplicate extracted ranks suppress ordinal evidence for
the complete option list. Unqualified numeric synonyms remain coded-domain
evidence; they do not create score transforms.

A boolean coded act uses inverse `negationInd` when that attribute is the target
representation. Separately, `mode: "presence"` may activate an optional
ART-DECOR statement whose complete payload is fixed and whose template is
uniquely identified by exact source terminology; false omits the statement.
`mode: "fallback_if_active"` may fill a required target only after another value
has activated the optional branch. It requires a review reason and cannot create
a branch or repeat by itself.
Occurrence-level values may be selected as the unique nearest compatible
descendant of an already-derived `for_each` boundary. Structural containers do
not become scalar writable targets through either rule.

Existing reviewed version-5 `fan_out` rules remain executable. During
`init-cda-mapping`, an old rule is migrated only when the newly generated
`repeat_by_discriminator` rule proves the same source set and physical CDA
target; otherwise the accepted mapping is left untouched for review.

Completion belongs to the shareable CDA mapping rather than site configuration.
`defaults.required_unmapped` supplies `nullFlavor="NI"` to an otherwise empty
required leaf in an active CDA occurrence; optional unmapped elements are omitted.
`target_defaults` records reviewed, more specific decisions. A rule contains
exactly one of `nullFlavor` or a JSON scalar `value`. Scalar values require a
non-empty reason and can complete required non-null elements or attributes;
they are checked against the compiled scalar datatype and finite code
constraints. Defaults never activate an otherwise unused optional branch and
are applied to every active repeated occurrence. Actual mapped values always
win in the same occurrence. Null defaults cannot be applied to attributes,
optional targets, or mandatory constraints that prohibit null flavors. A
required complex element is eligible only when its compiled
template exposes a writable optional `@nullFlavor`; other complex elements are
rejected. Scalar defaults cannot supply identifiers or compound values
whose non-null companion semantics require a structural mapping.

ART-DECOR `<example>` fragments never supply automatic values or display
metadata. They are instance illustrations, not fixed template constraints. For
a required polymorphic CDA leaf without source content, null-flavor completion
retains the concrete datatype—for example `<value xsi:type="CE"
nullFlavor="NI"/>`—instead of copying a clinical assertion from an example.

## Runtime

```bash
decor2hl7 check
decor2hl7 transform
decor2hl7 send
# or
decor2hl7 run --send
```

Transport is selected in the release `site.json`. The only current adapter is
the bounded, single-document `http-post` adapter:

```json
{
  "transport": {
    "adapter": "http-post",
    "url": "https://receiver.example/cda",
    "timeout": 60,
    "headers": {}
  }
}
```

For compatibility, a configuration without `adapter` still selects
`http-post`. Unknown adapters or options are rejected before document or
network I/O. Batch envelopes, acknowledgement parsing and idempotency are
receiver-protocol behavior and are not configurable until such a protocol is
specified and implemented as another built-in adapter.

Runtime is intentionally boring:

```text
CSV → model paths → code normalization → validation → CDA targets → CDA
```

Missing required dataset values use the site validation policy. Empty required
CDA leaves in active template branches use the completion policy in
`cda-mapping.json`, which defaults to `nullFlavor="NI"`. Naive datetimes use the
configured timezone. `1:n` CSV sources preserve source order
**and occurrence identity**: repeated groups are normalized as structured rows,
so an absent value in occurrence 1 cannot shift occurrence 2 into its place. An
optional primary flag can move one row first, and duplicate primary flags are
reported as errors without changing the input. Nested independent repetitions use explicit
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

See [`Project-decor2hl7.md`](Project-decor2hl7.md) for the project charter,
[`docs/decisions.md`](docs/decisions.md) for durable semantic and architectural
choices, [`docs/architecture.md`](docs/architecture.md) for current package
boundaries, and [`docs/known-issues.md`](docs/known-issues.md) for intentionally
remaining work. Dated source analyses are retained separately under
[`docs/analyses/`](docs/analyses/README.md).

## Release verification

After regenerating the companion `test-workplace` for the selected release and
transaction, run `make baseline` to refresh both the accepted-field set and the
persisted coverage-headline counts in
`tests/fixtures/reference-mapping-audit.json`. Review that fixture change, then
run `make check`. These are local release checks; this repository does not
install a CI workflow.
