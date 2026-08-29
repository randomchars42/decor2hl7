# Instructions for coding agents

This file applies to the entire repository. Read the project information below
before planning or changing code. Do not treat conversation history, an
unmerged branch, or a copied source tree as the authoritative project state.

## Required project context

Read these files in this order:

1. [`Project-decor2hl7.md`](Project-decor2hl7.md) — goal, ownership, the three
   workflows, workspace layout, and project-wide constraints.
2. [`docs/decisions.md`](docs/decisions.md) — accepted, open, rejected, and
   superseded semantic and architectural decisions, with implementation status.
3. [`docs/known-issues.md`](docs/known-issues.md) — unresolved clinical,
   specification, validation, and delivery boundaries. Do not silently invent a
   solution for an open boundary.
4. [`docs/architecture.md`](docs/architecture.md) — current component and data
   flow boundaries.
5. [`README.md`](README.md) — current user-facing commands and behavior.

Then read the task-specific material:

- [`docs/mapping-documentation-format.md`](docs/mapping-documentation-format.md)
  for changes to generated `cda-mapping.md` documentation;
- [`docs/analyses/README.md`](docs/analyses/README.md) and the relevant dated
  analysis for specification evidence and retrieval/compiler investigations;
- [`docs/history/`](docs/history/) only for historical rationale, not current
  policy;
- the affected tests and implementation files for executable behavior.

## Authority and conflict handling

The `randomchars42/decor2hl7` repository on `main` is canonical. Use its code,
tests, and durable documentation together:

- `docs/decisions.md` records current project policy;
- `docs/known-issues.md` records deliberately unresolved boundaries;
- dated analyses are evidence snapshots and may describe earlier behavior;
- tests prove implemented behavior but do not by themselves establish clinical
  policy;
- conversations are working context and must be consolidated into the
  repository before they are considered durable decisions.

If sources disagree, identify the conflict explicitly. Do not merge different
artifact revisions, infer clinical semantics from generic runtime capability,
or replace an exact missing ART-DECOR artifact with another revision.

## Working rules

- Preserve the three ownership boundaries: portable target mappings belong to
  the specification/mapping workflow, CSV/code/site configuration belongs to
  the local site workflow, and runtime consumes compiled models and reviewed
  configuration without accessing ART-DECOR.
- Keep the normalized dataset and site-input pipeline target-neutral. CDA is the
  first target, not the architectural boundary; future FHIR support should reuse
  target-independent stages.
- Prefer procedural, typed, small, unit-testable functions and one coherent CLI.
  Do not introduce a class hierarchy without a recorded reason.
- Preserve explicit artifact identity, effective dates, provenance, occurrence
  identity, and degraded-versus-fatal build distinctions.
- Never silently infer joins, repeated-occurrence alignment, lossy terminology
  crosswalks, clinical timestamps, or mapping choices without sufficient
  evidence and a reviewable rule.

## Finishing a change

For every semantic or architectural change, update in the same pull request:

1. the affected entry in `docs/decisions.md`, or add the next stable `DEC-*`;
2. the affected item in `docs/known-issues.md`, when applicable;
3. regression tests for the behavior;
4. user-facing and generated-documentation specifications, when applicable.

Use [`.github/pull_request_template.md`](.github/pull_request_template.md) as
the completion checklist. Record verification commands and do not leave a
decision only in chat, an analysis snapshot, or an unmerged branch.
