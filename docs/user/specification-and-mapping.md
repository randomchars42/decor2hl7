# Review a specification and publish a mapping

This workflow is for the specification maintainer and clinical mapping reviewer.
Its outcome is a portable, reviewed mapping between one exact ART-DECOR dataset
transaction and the selected target profile. It contains no site's CSV layout
or delivery settings.

## Before you start

You need:

- a decor2hl7 workspace;
- the exact release and transaction to review;
- access to the required ART-DECOR artifacts, or a complete local cache;
- authority to decide clinical correspondences and intentional omissions.

The work often involves two people: a specification maintainer who can verify
source concepts and template constraints, and a clinical reviewer who can judge
whether a proposed correspondence preserves meaning. A developer is needed only
when the tool cannot express an approved rule or when compilation evidence must
be investigated.

## 1. Select the exact specification

List the available release and transaction keys, then select one of each:

```bash
decor2hl7 list-versions
decor2hl7 set-version RELEASE
decor2hl7 list-transactions
decor2hl7 set-transaction TRANSACTION
```

The selection is an identity boundary. If the release or transaction changes,
fetch and build again and review the resulting differences as a new mapping
revision.

## 2. Fetch and build the review material

```bash
decor2hl7 fetch
decor2hl7 build
decor2hl7 init-cda-mapping
```

`fetch` collects the exact dependency closure. `build` compiles the dataset and
target models and creates mapping evidence. `init-cda-mapping` creates the
review-owned mapping bundle under
`mapping/<release>/<transaction>/`.

If the required artifacts are already cached and the service is unavailable,
use `decor2hl7 fetch --offline`. A degraded or incomplete build remains visible
in the diagnostics; do not treat missing evidence as approval for a guess.

## 3. Review the mapping bundle

Open the generated documents in this order:

1. `cda-mapping.md` — the remaining decisions and available actions;
2. `cda-mapping-details.md` — accepted mappings, reasons, and contextual CDA
   previews;
3. `cda-mapping-trees.md` — complete dataset-to-CDA and CDA-to-dataset coverage;
4. `cda-mapping-trees-extended.md` — exact source concept and template
   traceability for clinical and template review.

Edit only `cda-mapping.json`. The Markdown reports, XML previews, compiled
models, and proposal are generated evidence and may be replaced.

If the approved source concept is absent from the published dataset, add it to
the workspace root's reviewed `model_extensions` block before rebuilding. Use
an existing dataset group, an explicit reason, and an exact complete ValueSet
revision for coded fields. Do not add a CDA target there: after `build`, select
that separately in `cda-mapping.json`. The extended tree marks the field as a
reviewed model extension so downstream reviewers can distinguish it from
ART-DECOR-owned concepts.

For every unresolved datapoint, decide whether to:

- select a supported target;
- approve the shown transform or occurrence rule;
- request additional owner evidence;
- keep the field intentionally unmapped with a review reason; or
- leave the decision open.

Check repeated groups occurrence by occurrence. Independent repetitions must
not be aligned by row number or display order. For coded values, verify the
exact code system and ValueSet revision rather than relying on similar labels.

## 4. Validate the reviewed choices

```bash
decor2hl7 check-cda-mapping
decor2hl7 setup-test
decor2hl7 test-cda-mapping
```

`check-cda-mapping` validates the portable mapping without reading a site's
CSV files. The isolated mapping test exercises construction behavior. If an
authored scenario is available, prefer it for clinically meaningful branches:

```bash
decor2hl7 setup-test --force --scenario PATH_TO_SCENARIO
decor2hl7 test-cda-mapping
```

Mapping validity and complete CDA conformance are separate checks. Validate
generated examples when the review includes document-level constraints:

```bash
decor2hl7 validate-cda test/RELEASE/TRANSACTION/out/EXAMPLE.xml
```

## 5. Publish the handoff

Share the complete mapping directory, including `cda-mapping.json`,
`mapping-lock.json`, and its generated review guides. The lock ties the reviewed
decisions to the compiled dataset and target identities.

The receiving site should not rewrite this bundle to match local columns or
codes. Those choices belong in the
[site and input configuration workflow](site-configuration.md).

## When to involve a developer

Use the [technical specification-to-mapping pipeline](../specification-to-mapping-pipeline.md)
when a fetch or build must be diagnosed, evidence provenance is unclear, or an
approved clinical rule is not representable by the existing mapping schema.
Unresolved project-level questions are tracked in
[`open-boundaries.md`](../open-boundaries.md).
