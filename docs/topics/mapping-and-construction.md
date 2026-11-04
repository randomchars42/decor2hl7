# Mapping evidence, review, and construction

Mapping combines generated evidence with an explicit reviewed decision. Rich
evidence belongs in `mapping-audit.json`; the portable `cda-mapping.json`
contains concise executable selections and review metadata.

Related decisions: DEC-007, DEC-008, DEC-009, DEC-011, DEC-015, DEC-016,
DEC-017, DEC-018, DEC-020, DEC-023, DEC-024, DEC-025, DEC-029, DEC-030,
DEC-033, DEC-035, DEC-038, DEC-040, DEC-041, DEC-042, DEC-043, DEC-044,
DEC-046, and DEC-048.

## Evidence and gates

Candidate evidence includes formal template associations, static associations,
formal concept origins, exact implementation XPath, terminology, value-set and
datatype compatibility, unique context/description roles, CDA/RIM owner slots,
and generated Schematron support. Relationship paths remain review-only.

Candidate discovery and executable admission finish before audit serialization
or report rendering. The audit has checked field/group decision, candidate, gap
and summary shapes; the two presentations share evidence classification without
mutating the proposal. Report context is explicit rather than captured by a
large nested rendering function.

Evidence strength and executability are separate. An executable selection must
pass the applicable physical, datatype, terminology, cardinality, occurrence,
claim, companion, and co-occurrence gates. Shared targets and ambiguous
locations remain visible but unselected.

For each unselected field or group, the audit records the first failing gap and
smallest reopening evidence. `possible_targets` is a physical/type-compatible
inventory for human review; it is not semantic evidence and does not alter the
coverage headline.

A legacy/static association may project to an active branch only when its source
constraint and the active target resolve to one unique CDA/RIM owner-and-
particle slot inside the already established context and occurrence. Names do
not establish this equivalence.

## Declarative transforms

The scalar vocabulary is deliberately small: `identity`, `enum`, `ordinal`,
`not`, `code_system`, `coded_fallback`, `reviewed_coded_map`, `coded_only`,
`coded_or_original_text`, `narrative`, and `quarter_end`.

`quarter_end` accepts an ISO date or datetime and returns the final calendar
date of its containing quarter. It is intended for an explicitly reviewed
derived date rule; it does not infer whether the target branch should exist.

`coded_fallback` is available only for an explicitly open source domain below
an established container, one exact resolved target ValueSet containing the
required `OTH`/`UNC` exception, and a compiled `originalText` companion. Exact
admitted code/system pairs are retained; other values carry source wording
through the target-owned exception.

`reviewed_coded_map` is finite, exact, target-scoped, and valid only while its
named binding remains unresolved. It does not supplement or alias the missing
terminology artifact.

Clinical logic belongs in declarative configuration when these primitives can
express it; target- or template-specific Python branches require a separate
architectural decision.

## Structural rules

`cda-mapping.json:structures` accepts exactly `for_each`,
`repeat_by_discriminator`, `coalesce`, `concatenate`, and `compose_coded`.
These names are part of the checked mapping format rather than interchangeable
labels. `check-cda-mapping` rejects every other structure type.

- `for_each` binds one source repeat to one explicit target repeat. Unbound
  repeat ancestors become shared containers. It preserves the identity of each
  existing source occurrence; it does not create occurrences for separate
  scalar fields or align independent repeats by position.
- `repeat_by_discriminator` creates distinct target occurrences only from an
  exact required discriminator, bound ValueSet member, unique source/member
  correspondence, and compatible repeat structure. Every branch names a
  distinct logical target over one shared physical CDA value target and
  supplies its discriminator as a fixed coded constant. An absent branch source
  creates no occurrence; present branch sources create their own labelled
  occurrences without a positional join.
- `coalesce` lets equivalent sources share a singleton target. The default is
  `equal_or_error`; a reviewed precedence policy must report differences.
- `concatenate` maps present same-occurrence values independently and joins
  their textual results with an explicit separator.
- `compose_coded` combines one coded source and one human display-name source
  in the same occurrence into one coded CDA value. The reviewed rule fixes the
  code transform and uncoded null flavor; when only the display name is
  present, its wording is preserved in the compiled `originalText` companion.

The following are field-assignment modes under `fields`, not entries in
`structures`:

- `fallback` fills an absent target in the same occurrence.
- `fallback_if_active` fills a required leaf only after another assignment has
  activated its optional branch. It never activates a branch or creates a
  repeat.
- `if_active` writes an optional derived leaf only when its exact `active_if`
  guard target has a mapped value in the same occurrence shape. The guarded
  value may create datatype wrappers below that already-selected branch; the
  rule requires a review reason.
- `presence` lets a boolean activate one optional statement only when exact
  owner evidence fixes its complete payload.

## Narrative presentation

Every present executable field mapping is also presented in the narrative of
its owning CDA section. Direct mappings to the section text remain paragraphs;
other singleton facts use labelled `Merkmal`/`Wert` rows. Repeated facts add a
one-based `Vorkommen` column and retain source occurrence boundaries. Missing
values are omitted, booleans use document-language wording, and codes and
quantities use their normalized human-readable forms. Mapping transforms still
control whether a source contributes: for example, a false value transformed
to omission is not reintroduced by presentation, and a coalesce rule presents
only the winning source in each occurrence.

`cda-mapping.json:narratives` is a separate reviewed bridge for source wording
that has no defensible structured target. It is keyed by one exact writable,
unambiguous `section_narrative` target and contains `blocks`:

- `fact` accepts one non-repeated source field;
- `for_each` accepts one source field whose `repeat_chain` is exactly the named
  `source_repeat`, and renders every occurrence independently.

Each block requires `source`, `label`, and `reason`; `decision` and
`reviewed_at` retain review provenance. Its source remains `null` in `fields`
and cannot also appear in `field_reviews`. A narrative block may activate its
own non-repeated section, but it does not assert a structured CDA value, create
or coalesce structured entry occurrences, or provide a terminology crosswalk.
Unknown block types, keys, sources, repeated shapes, and targets fail portable
mapping validation.

A reviewed structured selection may be suspended by an explicit `null` in
`fields`, with a narrative-only rule retaining the fact where that presentation
is appropriate. Record its former assignment, exact source/target identity,
reason, and reopening evidence in a source-controlled suspension list. Recovery
overrides must retain that explicit null so a generated proposal cannot silently
restore the rejected selection. Reintroduction requires a new review of the
owner placement and intended receiver, followed by refreshed mapping reports
and conformance checks. The reference EDIS suspension is described in
[`../reference-transaction.md`](../reference-transaction.md#suspended-edis-mappings).

## Completion and ownership

`defaults.required_unmapped` supplies the general legal missing-information
policy for otherwise empty required leaves in active branches. Optional leaves
are omitted; mandatory non-nullable leaves remain errors.

`target_defaults` records one reviewed scalar or null flavor for one exact
required writable target, with a reason. Defaults do not activate optional
branches, and real mapped values win in their occurrence. Coded values must pass
the compiled binding; compound and identifier values cannot be reduced to an
unsafe scalar default.

`site_requirements` delegates one required target to either site `values` or
`fallback_if_active`, with a reason but no concrete value. Portable mapping
validation checks the contract; an actual site must provide a binding-valid
value through the declared channel. Coverage therefore writes `○◆`: there is
no dataset-field source (`○`), while construction ownership is explicit (`◆`).

`field_reviews` records an intentional null selection. It requires an existing
field, status `intentionally_unmapped`, a non-empty reason, and an actual null
mapping. It documents review and does not construct output.

## Products and review boundary

The canonical generated products are:

- `mapping-audit.json`: structured evidence, decisions, gaps, and coverage;
- `cda-mapping.proposed.json`: executable proposal;
- `cda-mapping.proposed.md`: unresolved review work for the generated proposal;
- `cda-mapping-details.md`: accepted selections and evidence;
- `cda-mapping-trees.md`: exhaustive dataset and CDA coverage.
- `cda-mapping-trees-extended.md`: exhaustive clinical and template-review
  coverage with source concept OIDs, template revisions, template-relative
  XPaths, exact ART-DECOR descriptions and rule/gap annotations.

`init-cda-mapping` creates or refreshes the portable mapping bundle without
overwriting reviewer choices. `--reset` explicitly replaces reviewed state with
the current proposal. Reviewed target names are never migrated automatically;
a renamed or removed target requires an explicit reviewed mapping change.
Structure type names are neither aliased nor translated. `mapping-lock.json`
pins the exact release, transaction, model and CDA identity and records the
mapping digest at creation as informational provenance. Runtime enforces the
same lock admission as mapping checks.
The bundle's `cda-mapping.md` is a strictly unresolved work queue; resolved
structured mappings, narrative-only decisions, and intentional nulls are
retained in the other reports instead of appearing as open decision cards.

The reference transaction's non-obvious reviewed mappings are summarized in
[`../reference-transaction.md`](../reference-transaction.md). The generated
document contract is specified in
[`../mapping-documentation-format.md`](../mapping-documentation-format.md).
