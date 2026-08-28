# Generated target-mapping documentation

This specification defines the short human-facing guide generated beside a
machine-readable target mapping. It applies to `cda-mapping.json` and is intended
to be reused for a future `fhir-mapping.json`.

## Purpose and representations

The guide connects three representations without becoming a second configuration
format:

1. the source data model, for example a datapoint in `model.json`;
2. the editable assignment in the target mapping JSON;
3. the destination model, for example a CDA template datapoint or FHIR element.

The mapping JSON is always the source of truth. Generated Markdown and target
fragments are read-only explanations and may be replaced whenever reports are
regenerated.

## Compact guide

The primary `<target>-mapping.md` should contain:

1. a short instruction saying which JSON file to edit;
2. a compact outline of the resulting target document or resource tree;
3. coverage counts by section or resource;
4. connected entity cards;
5. a compact list of datapoints requiring review;
6. structural rules and required-value defaults;
7. a pointer to the detailed evidence appendix.

The outline groups mappings below human-readable target entities. Each mapped
dataset name is followed by its exact logical target placeholder. Keep a short
target on the same line; place a long target on an indented continuation line so
the hierarchy and the complete identifier remain readable:

```text
Example document (ClinicalDocument)
├── Document header
│   ├── PatientIdentifier
│   │   └── Patienten ID → {PatientIdentifier.id}
│   └── CDAEncompassingEncounter
│       └── Aufnahmezeitpunkt
│           → {CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.low}
└── Document body (structuredBody)
```

Each entity card directly aligns the three representations:

| Human source name | Source-model datapoint | Mapping-JSON target | Human target name | Status |
|---|---|---|---|---|
| Example result | `triage.result` | `TriageResult.value` | Triage result | Mapped |

When configuration help is useful, show the JSON instruction and excerpt first:

> In `cda-mapping.json`, set `fields["triage.result"]` to
> `"TriageResult.value"`.

Only then show a target-format preview labelled as read-only. CDA uses an XML
fragment; FHIR should use a JSON or FHIRPath-oriented fragment. Placeholders such
as `{TriageResult.value}` identify generated target datapoints and are never
instructions to edit the target document directly.

To limit report size, generate configuration excerpts and target previews for the
first simple example and for mappings involving review, transforms, repetition,
fan-out, coalescing, defaults, ambiguity, or other non-trivial behavior. Keep
straightforward mappings in compact tables.

## Detailed appendix

The generated `<target>-mapping-details.md` contains candidate scores, rejected
alternatives, evidence chains, source identifiers, target paths, and unresolved
structural context. It explains why a proposal was made; it is not edited as
configuration. Machine-readable audit evidence remains in `mapping-audit.json`.

## Generation requirements

- Prefer human-readable names, but always retain stable source and target keys.
- Present the direction as source model → mapping JSON → target model.
- Never phrase a target fragment as a place where the reviewer enters values.
- Distinguish direct mappings, transforms, structural rules, deliberate `null`,
  and unresolved proposals.
- State the runtime consequence of `null` and required-value defaults explicitly.
- Generate deterministically from the compiled models, mapping, and audit; do not
  maintain duplicate hand-written mapping facts in the Markdown generator.
