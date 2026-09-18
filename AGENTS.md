# Instructions for coding agents

This file applies to the entire repository. Use the checked-out `main` code,
tests, and current topic documentation together; do not reconstruct policy from
conversation history, deleted dated analyses, generated source trees, or an
unmerged branch.

## Required project context

Read these current documents before planning or changing the project:

1. [`Project-decor2hl7.md`](Project-decor2hl7.md) — goal, ownership, workspace,
   and project-wide invariants.
2. [`docs/index.md`](docs/index.md) — topic navigation and authority order.
3. [`docs/topics/art-decor-authority.md`](docs/topics/art-decor-authority.md) —
   owner constructs and the boundary for local supplements.
4. [`docs/open-boundaries.md`](docs/open-boundaries.md) — unresolved matters;
   do not silently invent a solution for one.
5. [`docs/architecture.md`](docs/architecture.md) — current component and data
   flow boundaries.
6. [`README.md`](README.md) — current user-facing commands and behavior.

Then read the task-specific topic page identified by `docs/index.md`, plus:

- [`docs/specification-to-mapping-pipeline.md`](docs/specification-to-mapping-pipeline.md)
  for acquisition, compilation, or mapping-pipeline work;
- [`docs/reference-transaction.md`](docs/reference-transaction.md) for the
  selected reference profile and clinical mapping questions;
- [`docs/mapping-documentation-format.md`](docs/mapping-documentation-format.md)
  for generated mapping-documentation changes;
- [`docs/decisions.md`](docs/decisions.md) only when resolving a stable `DEC-*`
  identifier used by mapping or recovery metadata;
- the affected implementation and regression tests for executable behavior.

## Authority and conflict handling

The `randomchars42/decor2hl7` repository on `main` is canonical. Exact owner
artifacts define specification facts. Topic pages state accepted current project
policy. Tests prove implemented behavior but do not independently establish
clinical policy. Generated workspace artifacts provide concrete evidence for
their exact release and transaction.

If these sources disagree, identify the conflict. Do not merge artifact
revisions, infer semantics from generic runtime capability, or substitute a
nearby ART-DECOR artifact for an exact missing identity.

Chronological analysis and completed-plan documents are intentionally absent.
Git history is available for archaeology, but historical conclusions are not
current policy unless they survive in a topic page, the reference-transaction
page, or an open boundary.

## Reference workspace

The companion `randomchars42/decor2hl7-test-workspace` records the current
generated reference state. Verify its `decor2hl7.json` identity before using it. A
complete workspace contains:

- `spec/<release>/` from `fetch`;
- `model/<release>/<transaction>/` from `build`;
- `mapping/<release>/<transaction>/` from `init-cda-mapping`;
- `site/` and input configuration;
- `test/` generated from the authored scenario;
- acquisition configuration under `config/` when required.

For a field-level question, inspect the selected source under `spec/`, compiled
field and mapping evidence under `model/`, and the reviewed selection under
`mapping/` together. The generated workspace is evidence, not policy. Implement
durable fixes in this repository.

## Working rules

- Preserve the three ownership boundaries: portable target mappings belong to
  the specification workflow, CSV/code/site configuration belongs to the local
  site workflow, and runtime consumes both with compiled models.
- Keep the normalized dataset and site-input pipeline target-neutral. CDA is the
  first target, not the common architecture.
- Prefer procedural, typed, small, unit-testable functions and one coherent CLI.
  Do not introduce a class hierarchy without a recorded reason.
- Preserve exact artifact identity, effective dates, provenance, occurrence
  identity, and crawl-degraded versus build-degraded distinctions.
- Never infer joins, independent repeated-occurrence alignment, lossy
  terminology crosswalks, clinical timestamps, or mapping choices without
  sufficient evidence and a reviewable rule.
- Keep decor2hl7-owned translatable text in the packaged locale catalogs under
  `src/decor2hl7/locales/`, addressed by stable namespaced message IDs. Do not
  add inline language dictionaries or repurpose an existing ID for a different
  meaning.
- Do not copy generated coverage counts, test totals, or temporary commit state
  into durable prose. Keep volatile measurements in generated artifacts and
  regression fixtures.

## Repository write authorization

The repository owner has authorized coding agents working on this project to
create and merge pull requests into `randomchars42/decor2hl7` without requesting
case-by-case confirmation. Continue to use a pull request, review the exact
diff, complete the repository checklist, and respect branch protections and
failed checks. This authorization ends if the owner revokes it or explicitly
asks that a pull request remain unmerged.

## Finishing a change

For a semantic or architectural change, update in the same pull request:

1. the authoritative topic page;
2. the affected entry in `docs/open-boundaries.md`, if any;
3. regression tests;
4. user-facing or generated-documentation specifications, when applicable;
5. `docs/decisions.md` only if durable mapping/recovery metadata needs a new or
   changed stable identifier.

Use [`.github/pull_request_template.md`](.github/pull_request_template.md) as
the completion checklist. Record verification commands and do not leave policy
only in chat or an unmerged branch.

`make check-unit` is the repository-contained developer suite.
`make check-reference` requires the exact sibling companion workspace and fails
closed when it is absent or identity-mismatched; it also runs the end-to-end
mapping fixture. `make check` runs both tiers. A green full gate must never rely
on skipped reference-workspace tests.
