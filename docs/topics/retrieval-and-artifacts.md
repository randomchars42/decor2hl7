# Retrieval, artifact identity, and build admission

Retrieval turns a selected ART-DECOR release and transaction into an exact,
reproducible compiler input closure. Runtime never performs retrieval.

Related decisions: DEC-004, DEC-010, DEC-012, DEC-021, DEC-022, DEC-027,
DEC-028, and DEC-038.

## Identity and forms

Artifact identity includes kind, OID, effective date, and repository context.
Requested and resolved identities remain distinct. Static revisions are exact;
dynamic revisions are resolved once and frozen. A defining `id` and a project
reference `ref` can both identify an artifact, but neither proves an unrecorded
revision.

One logical artifact may have several non-interchangeable forms:

| Form | Purpose |
|---|---|
| `source` | Original declaration, selection, labels, associations, provenance |
| `analysis` | Expanded or resolved compiler representation |
| `expansion` | Complete frozen terminology membership |
| `expansion-evidence` | Partial diagnostic evidence; never a complete domain |

The selected transaction requires matching source and analysis forms. A valid
analysis form is sufficient for ordinary dependencies; a missing source sidecar
reduces optional evidence and is not synchronously backfilled by an ordinary
fetch.

## Resolution and bounded closure

Repository resolution uses the strongest available context before probing:

1. explicit reference link, prefix, or project;
2. configured source hints;
3. exact cached owner and project-directory evidence;
4. other known ownership metadata and OID-prefix inference;
5. HTTP probing as a last resort.

The crawler follows the selected transaction, formal dataset origins,
executable template `include`/`contains`, terminology composition, and bounded
mapping-evidence endpoints. Ordinary relationships do not recursively expand
the crawl. Whole external projects are not downloaded merely because one
artifact is referenced.

`manifest.json` records the release cache. Transaction `closure.json` records
the resources and reviewed overlays that belong to one build. `crawl_complete`
means discovery has settled; `build_ready` means mandatory compiler inputs are
present. These states are independent.

Root acquisition, build closure, evidence closure and checkpoint publication are
separate procedural stages. Explicit crawl state owns pending/visited identities,
roles and the shared HTTP request budget. Checkpoints observe that same state
on normal completion, budget exhaustion and interruption; optional evidence
never becomes a build dependency merely through shared caching.

Artifact fetching separates checksum-checked cache admission, network attempts
and representation storage. One request-budget increment means one actual HTTP
attempt. Expansion evidence retains its own completeness state when a cached
analysis definition remains usable.

`fetch --offline` makes no HTTP requests. It validates deterministic cache
files, repairs reconstructible manifest metadata, and records uncached
references as retryable unavailable dependencies.

## Missing and contradictory artifacts

Unavailable auxiliary evidence may be omitted when compilation remains safe.
The complete missing set is `crawl_degraded`; `build_degraded` contains only
missing artifacts consulted by selected formal terminology, validator value
sets, or selected CDA template compilation. Missing selected transaction forms,
the representing document template, corrupt successful artifacts, and exact
identity contradictions remain fatal.

A successful artifact is never substituted across revisions. Partial
terminology expansion is retained as evidence but cannot constrain input,
satisfy validator assembly, or authorize target codes.

## Reviewed catalog entries

The exact source catalog supports three bounded local mechanisms:

- `builtin`: materialises a small package-local artifact. It may satisfy a
  required dependency only when completeness is `complete`, checksum and exact
  identity verify, and source URL, version, and license are recorded.
- `waiver`: records a cited settled absence. It never reports success or
  satisfies a dependency.
- `alias`: corrects one exact malformed published identity to one exact reviewed
  target while retaining both identities and the reason.

The catalog is not a generic web-scraping or arbitrary local-file framework.
New acquisition modes require a concrete artifact and a reviewed policy.

## Reviewed CDA profile overlays

An open template permits CDA-valid content but does not identify a particular
standalone template. A reviewed attachment therefore becomes a fetch dependency
only after it is scoped to the exact selected transaction. Build revalidates the
document, parent, element, target revision, openness, multiplicity, and CDA/RIM
placement. A reviewed SPEC-branch selection is similarly exact and replaces,
rather than combines, sibling branches.

The normalized overlay is stored in `closure.json`; cached ART-DECOR XML remains
unchanged. If the owner later supplies the containment explicitly, a stale
local attachment fails rather than duplicating it.

## Reproducibility and recovery

Checksums cover cached artifacts and pinned validation packages. A missing
manifest can be reconstructed from valid deterministic files; a checksum or
identity contradiction cannot. Reviewed mapping overrides that cannot be
generated from owner rules live in the identity-pinned file under
[`../recovery/`](../recovery/) and are applied only after its model and CDA
hashes match.

Current unavailable publications and closure limitations are listed in
[`../open-boundaries.md`](../open-boundaries.md).

## Compiler admission

The compiler verifies the recorded SHA-256 of every successful source, analysis
and expansion form in the selected transaction, build and evidence closure
before consuming it. A missing checksum, missing file or changed bytes is an
integrity error, even if retrieval previously succeeded. Unavailable optional
evidence still follows the documented degradation policy; successful evidence
with inconsistent bytes cannot be admitted as trustworthy input.
