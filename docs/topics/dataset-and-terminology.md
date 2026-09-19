# Dataset and terminology compilation

`model.json` is the target-neutral boundary between ART-DECOR acquisition and
all output targets. CDA is a consumer of this model, not part of its definition.

Related decisions: DEC-003, DEC-005, DEC-006, DEC-016, DEC-025, DEC-037,
DEC-039, DEC-040, DEC-042, and DEC-046.

## Dataset composition

The compiler combines, without blending their authority:

1. the transaction analysis tree for resolved containment and definitions;
2. the transaction source for selection, usage, and direct associations;
3. exact terminology resources and complete frozen expansions;
4. semantic properties from one formal `inherit`/`contains` terminal original;
5. the current stored concept's descendants.

Relationship neighbours remain evidence and never contribute properties or
children. Selected concepts missing from the matching analysis form are a
contradiction, not a reason to borrow from another dataset revision.

Every compiled field retains identity, name and description, datatype and
constraints, cardinality, parent, repeat chain, terminology associations,
domain metadata, and provenance. Groups and fields remain distinct.

## Reviewed local model extensions

When an approved CDA data requirement has no field in the published dataset,
the workspace may declare `decor2hl7.json:model_extensions`. This is a narrow
target-neutral supplement, not an editable replacement dataset. Version 1
requires `status: "reviewed"`, `collision_policy: "error"`, an existing
immediate parent group, a scalar 0..1 or 1..1 field, and a review reason.
Paths may not collide with owner-published groups or fields.

A coded extension may name one exact `id` and `effective_date`. The revision
must be locally available and completely expanded; unresolved terminology
fails the build. Repeat identity is inherited from the parent group. Compiled
fields carry `concept: model-extension:<path>`, a `model_extension` provenance
block, and the canonical extension hash in `meta.model_extensions`. The
generated mapping trees label this provenance explicitly.

Extensions add input/model concepts only. CDA target choices and derivations
remain reviewed decisions in `cda-mapping.json`, while CSV columns and local
aliases remain site configuration.

## Terminology views

The model keeps three separate views:

| View | Meaning |
|---|---|
| `logical_domain` | Dataset labels and choices |
| `formal_terminology` | Exact binding, members, completeness, and missing dependencies |
| `accepted_values` | Values executable at the input boundary |

A complete formal binding governs accepted values. Logical labels do not fill
an unresolved formal domain, and revisions are not unioned. A dynamic binding
uses its frozen resolved revision. Abstract owner options remain evidence but
cannot be selected.

An inline concept list owned by a dataset concept is not a standalone external
ValueSet. An empty owned list with no external reference is explicitly
`unconstrained`; it is not an unresolved terminology failure. Conversely, a
missing or partial external ValueSet remains unresolved and never becomes an
open domain.

Input code normalization is target-neutral. Finite or unresolved domains reject
unadmitted values; an explicitly open domain retains its raw wording. CDA
`nullFlavor`, `OTH`, `UNC`, and target `originalText` handling belong to target
mapping and conformance, not dataset normalization.

## Exact associations and reviewed bridges

One source option may carry several exact code/code-system associations. A
required target ValueSet may choose among them only by exact membership.

Where an exact target binding is unavailable, `reviewed_coded_map` may authorize
one finite target-scoped conversion. It must enumerate every executable source
option with owner concept identity, every exact output and rationale, and the
exact target ValueSet revision. This does not repair the missing artifact. If
the binding later resolves, formal membership takes precedence and exposes any
contradiction.

## Scalar constraints

Ordinal evidence is conservative. A bare leading integer is a rank only in the
primary label and not when it begins a hyphenated identifier. Elsewhere, a
number requires explicit rank, score, Rankin, Rang, or Punkte wording. A
collision removes generated ordinal metadata from the whole option list.

Quantity values use one target-neutral representation:

```json
{"value": 2.5, "unit": "mg"}
```

or:

```json
{"low": {"value": 1, "unit": "mg"}, "high": {"value": 2, "unit": "mg"}}
```

The normalizer accepts a magnitude with an optional unit or a low-high range,
applies a dataset-fixed unit only when input omits it, validates the admitted
unit domain and numeric bounds, and rejects conflicting or reversed ranges.
Multiple published unit properties form an admitted domain; the last property
is not treated as a fixed unit. Local spelling-to-UCUM aliases belong to site
configuration.

## Occurrence identity

Repeated groups produce explicit `repeat_chain` metadata. One source occurrence
remains one normalized occurrence, so an absent value cannot shift later rows.
Independent nested repetitions require configured occurrence keys and are never
joined by positional guessing.

Target-specific mapping and rendering consume this structure but do not redefine
it. Current transaction-specific terminology exceptions are described in
[`../reference-transaction.md`](../reference-transaction.md).
