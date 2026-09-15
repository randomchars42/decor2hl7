# Mapping evidence, review, and construction

Mapping combines generated evidence with an explicit reviewed decision. Rich
evidence belongs in `mapping-audit.json`; the portable `cda-mapping.json`
contains concise executable selections and review metadata.

Related decisions: DEC-007, DEC-008, DEC-009, DEC-011, DEC-015, DEC-016,
DEC-017, DEC-018, DEC-020, DEC-023, DEC-024, DEC-025, DEC-029, DEC-030,
DEC-033, DEC-035, DEC-038, DEC-040, DEC-041, DEC-042, and DEC-043.

## Evidence and gates

Candidate evidence includes formal template associations, static associations,
formal concept origins, exact implementation XPath, terminology, value-set and
datatype compatibility, unique context/description roles, CDA/RIM owner slots,
and generated Schematron support. Relationship paths remain review-only.

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
`coded_or_original_text`, and `narrative`.

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

- `for_each` binds one source repeat to one explicit target repeat. Unbound
  repeat ancestors become shared containers.
- `repeat_by_discriminator` creates distinct target occurrences only from an
  exact required discriminator, bound ValueSet member, unique source/member
  correspondence, and compatible repeat structure.
- `coalesce` lets equivalent sources share a singleton target. The default is
  `equal_or_error`; a reviewed precedence policy must report differences.
- `concatenate` maps present same-occurrence values independently and joins
  their textual results with an explicit separator.
- `compose_coded` combines one coded source and one human display-name source
  in the same occurrence into one coded CDA value. The reviewed rule fixes the
  code transform and uncoded null flavor; when only the display name is
  present, its wording is preserved in the compiled `originalText` companion.
- `fallback` fills an absent target in the same occurrence.
- `fallback_if_active` fills a required leaf only after another assignment has
  activated its optional branch. It never activates a branch or creates a
  repeat.
- `presence` lets a boolean activate one optional statement only when exact
  owner evidence fixes its complete payload.

Legacy reviewed `fan_out` remains executable and migrates only when a generated
replacement proves identical source and physical target identity.

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
- `cda-mapping.md`: unresolved review work;
- `cda-mapping-details.md`: accepted selections and evidence;
- `cda-mapping-trees.md`: exhaustive dataset and CDA coverage.

`init-cda-mapping` creates or refreshes the portable mapping bundle without
overwriting reviewer choices. `--reset` explicitly replaces reviewed state with
the current proposal. Target names may migrate only through one unique stored
owner identity. `mapping-lock.json` pins transaction, model, CDA, and mapping
identity.

The reference transaction's non-obvious reviewed mappings are summarized in
[`../reference-transaction.md`](../reference-transaction.md). The generated
document contract is specified in
[`../mapping-documentation-format.md`](../mapping-documentation-format.md).
