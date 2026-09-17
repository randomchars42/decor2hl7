# Configure a site's input

This workflow is for the site integration administrator. Its outcome is a
site-local configuration that converts one deployment's source export into the
target-neutral dataset model. It does not change the reviewed dataset-to-CDA
mapping.

## Before you start

You need:

- compiled models and the reviewed mapping for the exact selected release and
  transaction;
- one coherent source-data snapshot outside the decor2hl7 workspace;
- knowledge of source files, relationships, identifiers, code conventions,
  units, timestamps, and timezone;
- approved values for deployment-owned document fields.

Use non-production data while developing the configuration. Source data remains
producer-owned and should not be copied into the specification or mapping
directories.

## 1. Inspect the source snapshot

```bash
decor2hl7 propose-input --input /data/clinical-export
decor2hl7 init-site-config
```

`propose-input` can suggest filenames, columns, and observed codes. Suggestions
are a starting point: the tool does not infer joins, record identity,
cardinality, or occurrence keys.

`init-site-config` creates the site-owned bundle under `site/`. Review its files
rather than editing generated models or the portable mapping.

## 2. Record site-owned decisions

The site bundle describes:

- source filenames and the relationships between them;
- columns and parsing rules;
- record identity and occurrence keys;
- local code and unit aliases;
- identifiers, timezone, and deployment values;
- transport configuration when delivery is enabled.

Keep values from one repeated source occurrence together. If two tables repeat
independently, configure explicit keys for each level; do not align them by row
position.

Local aliases may normalize input into a formal dataset domain, but they do not
extend the specification's terminology. If a source value has no approved
meaning in the selected dataset, return it to review instead of inventing a
code mapping.

## 3. Validate the configuration and input

```bash
decor2hl7 check
decor2hl7 check-input --input /data/clinical-export
```

`check` verifies the selected workspace products and configuration.
`check-input` reads and validates the source snapshot without generating CDA.
Resolve errors at the layer that owns them:

- file, column, join, parsing, local code, or timezone errors belong to the
  site configuration;
- missing or disputed dataset-to-CDA meaning belongs to the mapping review;
- missing specification artifacts belong to the specification workflow.

If a deployment always uses one input directory, it may be recorded as the
optional site default. An explicit `--input` path remains useful for testing a
specific snapshot.

## 4. Hand off to operations

Provide the approved site bundle, the matching reviewed mapping, and the
location of the external input snapshot to the runtime operator. Record how
credentials or other protected transport values are supplied; do not place
secrets in shared mapping documentation.

Before production use, run the first transformation without delivery and
inspect its validation result and output. Continue with
[Operate document generation](runtime-operation.md).

Technical details about joins, occurrences, validation layers, state, and
transport are in
[`topics/input-runtime-and-delivery.md`](../topics/input-runtime-and-delivery.md).
