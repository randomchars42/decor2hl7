# Site input, runtime, testing, and delivery

Site input configuration, portable target mapping, and runtime operation have
different owners. Runtime consumes compiled models and reviewed configuration;
it never accesses ART-DECOR XML or services.

Related decisions: DEC-002, DEC-005, DEC-006, DEC-007, DEC-034, DEC-035, and
DEC-041.

## Site-owned input

The producer owns the external input directory. One command invocation treats
it as one coherent snapshot. `site.json` defines logical sources, relative
filenames, joins, cardinality, occurrence keys, timezone, local identifiers,
and deployment policy. `csv-mapping.json` maps columns into the target-neutral
model; `codes-mapping.json` normalizes local representations.

`propose-input` may inspect filenames, headers, and observed codes, but it does
not infer joins, cardinality, or occurrence identity. `build` and
`check-cda-mapping` never read site CSV input.

CSV mappings may specify parsing and small input transforms. Local code or unit
aliases are input policy and cannot extend a bound formal dataset terminology.

## Occurrences and validation

One source occurrence remains one normalized occurrence. A missing value never
shifts a sibling occurrence. A one-file, one-level repeated source may retain
source order for compatibility; independent nested repetitions require explicit
occurrence keys at every independent level. Positional zipping is unsupported.

Validation is layered:

1. acquisition and cache integrity;
2. compiled dataset and target integrity;
3. portable mapping validity;
4. site/input configuration validity;
5. normalized record validity;
6. target construction, assertions, XSD, and Schematron.

Mapping review can therefore run without site input, while actual
transformation requires the selected site bundle and its declared construction
values.

## Runtime

The runtime sequence is:

```text
external input snapshot
  -> ingest and join
  -> normalize and validate
  -> build occurrence-aware assignments
  -> render CDA from compiled representations
  -> evaluate assertions
  -> update state
  -> optionally deliver
```

Mapped values, target defaults, site values, and `fallback_if_active` values are
resolved through the same compiled target and terminology constraints. Naive
datetimes use the configured site timezone.

The transformation fingerprint includes normalized values and occurrence
structure, compiled specification, mapping, relevant site policy, and renderer
identity. It excludes physical input paths and CSV line numbers. State keys are
scoped by transaction OID and raw record identity, allowing corrections while
preventing unchanged duplicate output.

## Mapping scenarios

Authored scenarios are versioned CSV source sets with a manifest pinned to the
release and exact transaction. The manifest declares every source relationship,
case identity, expected present/absent fields or templates, and optional local
site/code values. Generated CDA is never accepted as its own oracle.

`setup-test --scenario` creates an isolated fixture; `test-cda-mapping` runs the
ordinary ingestion, validation, binding, rendering, and assertion modules
without production state or transport. The deterministic synthetic generator
remains available for broad smoke coverage, but it cannot prove mutually
exclusive clinical branches.

## Transport

Site configuration selects one built-in adapter by exact name. Each adapter has
a closed option schema and is validated before document or network I/O.
Configuration cannot import arbitrary code.

The current `http-post` adapter sends one CDA document by HTTP(S) POST and
accepts only URL, positive timeout, and single-line scalar headers. Receiver
authentication, envelopes, acknowledgements, and exactly-once semantics are not
generic configuration knobs; they require a concrete protocol adapter and the
matching durable state contract.

Those unresolved receiver concerns are tracked in
[`../open-boundaries.md`](../open-boundaries.md).
