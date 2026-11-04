# Review a specification and publish a mapping

Create a reviewed dataset-to-CDA mapping that several sites can reuse.

## Workspace for specification review

This workflow prepares the specification and portable mapping. The relevant
parts of the workspace are:

```text
WORKSPACE/
├── decor2hl7.json                          selection and reviewed model additions
├── config/                                acquisition hints and reviewed overlays
├── spec/2026.1.2/                          fetched specification and closure
├── model/2026.1.2/notaufnahmeregister--60/   generated models, proposal, diagnostics
├── mapping/2026.1.2/notaufnahmeregister--60/ editable mapping, lock, and review guides
└── test/
    ├── scenarios/                         authored fictional records
    └── 2026.1.2/notaufnahmeregister--60/    generated mapping-test fixture and output
```

Edit reviewed decisions in `mapping/`. The generated models and reports explain
those decisions. `site/`, runtime `out/`, and `state/` are used in the later
guides.

## Set up the practice workspace

Install decor2hl7 as described in the [README](../../README.md#install). To
follow this guide with working examples, use a prepared reference workspace for
`2026.1.2 / notaufnahmeregister--60`, including its reviewed model additions and
mapping. In the commands below, replace `/data/decor2hl7-reference` with its
location, and `/path/to/decor2hl7` with the source checkout.

Create a new practice directory and copy the matching setup and authored cases:

```bash
mkdir /data/decor2hl7-test
cd /data/decor2hl7-test
decor2hl7 init
cp /data/decor2hl7-reference/decor2hl7.json .
cp -a /data/decor2hl7-reference/config /data/decor2hl7-reference/spec .
cp -a /data/decor2hl7-reference/model /data/decor2hl7-reference/mapping .
mkdir -p test/scenarios
cp -a /path/to/decor2hl7/src/decor2hl7/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases \
  test/scenarios/
decor2hl7 check-cda-mapping
```

Expect the mapping check to succeed. The copied selection, models, reviewed
mapping, and lock must agree. Keep this practice workspace for guides 2 and 3;
the next guide populates its site configuration and source snapshot. Run the
remaining commands here.

## 1. Inspect the prepared specification

Open `decor2hl7.json` and confirm the release and transaction. Then check
`model/2026.1.2/notaufnahmeregister--60/build-diagnostics.md` for missing
artifacts and their effect. The adjacent
`conformance-validation/build-conformance.md` reports source and
validator-generation findings; clinical-document validation comes in step 3.

The practice copy already contains these products. When preparing a **new
specification**, create a separate workspace, then select, fetch, build, and
initialize its mapping in order:

```bash
decor2hl7 list-versions
decor2hl7 set-version 2026.1.2
decor2hl7 list-transactions
decor2hl7 set-transaction notaufnahmeregister--60
decor2hl7 fetch
decor2hl7 build
decor2hl7 init-cda-mapping
```

`fetch --offline` uses the local cache. When changing the selected specification,
fetch and build again and review the differences as a new mapping revision.

## 2. Review one datapoint at a time

Open the files below in `mapping/2026.1.2/notaufnahmeregister--60/`:

| File | Where to look and what to expect |
|---|---|
| `cda-mapping.md` | Start with the coverage headline, then the unresolved dataset tree and decision cards. Each card explains the current gap, possible actions, and any candidate configuration. |
| `cda-mapping-details.md` | Find the dataset path or target name to inspect accepted choices, transforms, repetition rules, reasons, and contextual CDA previews. |
| `cda-mapping-trees.md` | Check the complete dataset tree, then the inverse CDA tree to see where fields go and which CDA leaves have no source. |
| `cda-mapping-trees-extended.md` | Follow `S:` for source identity, `T:` for template and XPath, `A:` for owner annotations, `R:` for rule behavior, and `G:` for gaps or intentional omissions. |

A resolved field disappears from the main work queue and remains in the
details and full trees. `✓` means mapped, `=` intentionally unmapped, `!` a
suggestion, and `×` no approved target. On the CDA side, `▲` flags required
construction still to resolve and `◆` identifies an explicit site responsibility.
A row labelled **Possible target (unproven)** needs semantic review before use.
Narrative-only mappings also count as mapped; their details explain which
wording appears in the selected section.

For example, search the details report for `patient.anschrift.postleitzahl`.
The reference mapping
selects `CDArecordTargetnnar.recordTarget.patientRole.addr.postalCode`. To record
that choice, update the entry under `fields` in **`cda-mapping.json`**:

```json
{
  "fields": {
    "patient.anschrift.postleitzahl": "CDArecordTargetnnar.recordTarget.patientRole.addr.postalCode"
  }
}
```

This is an excerpt to merge into the existing file. Keep the other entries.
For a transform or repeated group, use the complete configuration shown by its
decision card and check that values from each source occurrence stay together.
For codes, compare the code system and ValueSet revision as well as the label.

Keep a field at `null` when no mapping is approved. A deliberate omission also
needs a `field_reviews` entry with `status: intentionally_unmapped` and a reason;
otherwise it remains review work. If a mapping is suspended, retain its former
assignment and reopening conditions, as in the
[EDIS restoration example](../reference-transaction.md#suspended-edis-mappings).

Save the JSON, refresh the guides, and check that the trees and work queue now
reflect the decision. Generated Markdown and XML previews are read-only.

```bash
decor2hl7 init-cda-mapping
decor2hl7 check-cda-mapping
```

Ordinary initialization preserves reviewed selections. `--reset` replaces them
with the generated proposal. The check also lists site requirements and their
`cda.values` or `cda.fallback_if_active` channels for the next workflow.

## 3. Check the result with example records

For workspace isolation and instructions for authoring your own cases, follow
the [specification and mapping test setup](testing.md#1-test-the-specification-and-mapping).
It explains `scenario.json`, source CSVs, coverage, and expected fields/templates.

Use the [valid reference cases](../../src/decor2hl7/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases/README.md)
copied into `test/scenarios/` during setup. The command prepares an isolated
fixture containing `input/` CSVs, a
`config/` site bundle, and `expected.json` below
`test/2026.1.2/notaufnahmeregister--60/`. Running it writes `out/results.md`,
`out/results.json`, and the example XML documents.

Open `results.md` first: expect `PASS`. Resolve errors for unexercised mapped
fields and review warnings about unassigned target branches. Use `results.json`
for configuration errors, render warnings, and per-document details. Open the
XML and compare values and repeated occurrences with the fixture CSVs.
Mapping-test success and complete CDA conformance are separate results.

```bash
decor2hl7 setup-test \
  --scenario test/scenarios/valid-reference-cases
decor2hl7 test-cda-mapping
decor2hl7 validate-cda test/2026.1.2/notaufnahmeregister--60/out/*.xml \
  --report test/2026.1.2/notaufnahmeregister--60/out/conformance
```

For another specification, use a scenario matching its exact identity.
Without `--scenario`, generated smoke-test input may need adjustment for
mutually exclusive clinical branches. Use `--force` when deliberately replacing
an existing fixture after mapping changes. Inspect `out/conformance.md` for
validation stages and `out/conformance.json` for the complete diagnostics.

## 4. Hand over the reviewed setup

Share the complete `mapping/2026.1.2/notaufnahmeregister--60/` directory,
including `cda-mapping.json`, `mapping-lock.json`, and all four review guides.
Record remaining decisions and the site requirements listed by the check.

For a ready-to-configure workspace, also supply `decor2hl7.json`, required
`config/` files, and the matching `spec/` and `model/` products. The mapping lock
checks the exact selected identities and compiled models. Site-specific CSV
columns and local codes are configured in the
[site workflow](site-configuration.md).

Approved source fields missing from the owner dataset can be added through the
reviewed root `model_extensions` block before rebuilding; see the
[compilation guide](../specification-to-mapping-pipeline.md#5-compile-modeljson).
For fetch/build problems or evidence questions, use the
[technical pipeline](../specification-to-mapping-pipeline.md) and
[open boundaries](../open-boundaries.md).
