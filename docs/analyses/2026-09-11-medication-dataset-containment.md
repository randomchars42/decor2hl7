# Medication dataset containment verification

Date: 2026-09-11

## Question

Does the selected transaction actually establish the 25 medication fields, or
does that count depend on the compiler guessing through an unrelated concept
relationship? Does restricting the fallback affect other mappings?

## Authoritative local evidence

The refreshed `test-workplace` selects release `2026.1.2`, transaction
`2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`.
Its expanded transaction contains exactly one literal `<contains>` element. On
local Medikation concept `2.16.840.1.113883.2.6.60.3.2.9.30086` it names:

- literal target `2.16.840.1.113883.2.6.60.3.2.10.1` with flexibility
  `2023-12-28T16:24:42`;
- external dataset `2.16.840.1.113883.3.1937.777.75.1.2` at
  `2023-10-25T11:39:22`; and
- resolved concept effective date `2023-12-27T14:10:52`.

The same Medikation concept has an adjacent explicit `SPEC` relationship to
IOPC concept `2.16.840.1.113883.3.1937.777.75.2.1.482` at that exact resolved
effective date and in that same external dataset.

The literal target is not absent from all fetched evidence. In
`project-evidence.xml` it is a thin nameless concept shell whose sole content is
an `inherit` edge to the same IOPC concept `...75.2.1.482` at
`2023-12-27T14:10:52`. Project evidence is deliberately mapping-only and is not
a source-model build dependency, so the compiler does not use that shell to
satisfy containment. It corroborates the transaction's direct `SPEC` edge.

The exact IOPC dataset analysis form is a model build input. Its current
`...75.2.1.482` subtree has 33 named descendants: 8 groups and 25 item
concepts. All 25 materialize as medication fields in `model.json`.

Twenty-four item concepts have effective dates no later than the transaction's
literal containment timestamp. `Chargennummer`
`...75.2.1.738@2024-08-08T18:05:21` is the exception. The fetched dataset and
root concept are draft and currently return that later child under the same
identified root. Therefore 25 is exact for the current downloaded compiler
input, but the available files do not prove that a historical December 2023
snapshot already had all 25 members.

## Compiler rule found and narrowed

Before this verification, `_concept_node()` placed every relationship target in
`external_refs`, while `_graft()` tried the literal containment identity and
then every `external_refs` entry. Consequently an available `ADAPT` target
could supply a subtree when the literal target was not parsed. That contradicted
the accepted boundary that derivation is evidence rather than dataset identity.

On branch `verify/contains-revision-boundary`, `_graft()` instead falls back to
`identity_refs`. This retains `SPEC`, `INHERIT`, `ORIGINAL`, `EQUIV`, `COPY`, and
`VERSION`, but excludes `ADAPT` and other derivations. A regression test proves
that the Medikation-shaped `contains` plus `SPEC` pattern still grafts the
external child and that the equivalent `ADAPT` pattern does not.

## A/B result

The unmodified `main` compiler and the branch compiler were run separately
against the same refreshed closure, including once with the same
`PYTHONHASHSEED`. Their raw compiled source models were identical:

```text
SHA-256 16e4a19878308aadd57fef2b700d20f01be6e21a2b3ed32cb4026cc6563bd58f
120 fields
57 groups
25 medication fields
```

A complete branch build retained all 36,015 physical CDA targets. Comparison
with the frozen pre-build proposal found no removed or downgraded proposal.
Medication proposal values were identical. One unrelated proposal was added
for `hauptkostentrager.versicherungsverhaltnis.identifikation`; the source model
and physical target inventory were unchanged, so this is a regeneration delta,
not an effect of the containment restriction. The accepted mapping was not
modified. After restoring the authoritative generated snapshot,
`check-cda-mapping` again passed with 98 mapped entries.

## Conclusion

The medication subtree does not rely on `ADAPT` or a label/path guess. The
transaction supplies a direct exact `SPEC` relationship to the fetched concept
that currently defines the 25 fields, and the mapping-only alias shell
independently points to the same concept. Restricting containment fallback to
identity lineage changes no field, group, CDA target, or medication mapping in
the selected workspace, while preventing an unsupported weak-derivation graft
in other inputs.
