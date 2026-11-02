# Site input, runtime, testing, and delivery

Site input configuration, portable target mapping, and runtime operation have
different owners. Runtime consumes compiled models and reviewed configuration;
it never accesses ART-DECOR XML or services.

Related decisions: DEC-002, DEC-005, DEC-006, DEC-007, DEC-034, DEC-035,
DEC-041, and DEC-044.

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

### Optional ODBC source stage

An ODBC deployment configures `site.json:source` and one reviewed SQL file per
declared `input.sources` entry. Every query receives exactly one positional
lower-bound date. The case source must return its configured join column and
`source.written_at_column`; each other query must return its global or
source-specific join column plus configured occurrence/primary columns. The
DSN or connection string is read only from the environment variable named by
`source.dsn_env`. Credentials never enter a snapshot or sidecar.

`extract-source` executes all queries through one connection and publishes one
new directory by a same-filesystem rename. The target must not already exist.
It contains the configured CSV filenames plus
`.decor2hl7-snapshot.json`, which records the window, row counts, maximum case
write timestamp, query hashes, and relevant configuration hash. Database
scalars receive only stable serialization; opaque ODBC binary values such as
`VARBINARY` hashes are written as lowercase hexadecimal text. Null, datetime,
terminology, unit, and clinical normalization remain owned by `data.ingest`.

Rows are deterministically ordered by join key, optional site-owned
`order_by`, configured occurrence keys, and remaining columns. `order_by`
records clinically meaningful row order such as diagnosis rank; remaining
columns are only deterministic tie-breakers. Duplicate `1:1` keys, missing
required columns, orphan child keys, absent query files, and query failures
abort the complete snapshot. No partially populated final directory becomes
visible.

The extraction window is a change-detection rescan, not a declaration that
older cases ceased to exist. Runtime therefore never uses absence from a
bounded ODBC snapshot—or from a `--limit` development run—to delete another
record's pending artifact.

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
optional ODBC extraction -> immutable external input snapshot
  -> ingest and join
  -> normalize and validate
  -> build occurrence-aware assignments
  -> render CDA from compiled representations
  -> evaluate assertions
  -> optionally publish/send
  -> atomically commit delivery and lineage state
```

Mapped values, target defaults, site values, and `fallback_if_active` values are
resolved through the same compiled target and terminology constraints. Naive
datetimes use the configured site timezone.

The transformation fingerprint includes normalized values and occurrence
structure, compiled specification, mapping, relevant site policy, and renderer
identity. It excludes physical input paths and CSV line numbers. State keys are
scoped by transaction OID and raw record identity, allowing corrections while
preventing unchanged duplicate output.

`state/state.sqlite` is the sole production state authority. It contains the
current stream revision, append-only version history, exact current and prior
CDA identities, delivery status, and a run ledger. An existing version-1
`state/index.json` is imported once and retained as migration evidence. A
workspace lock prevents overlapping transforming or delivering commands.

State advances only after the selected transport reports a successful
handover. A crash before that point leaves the record pending; retry therefore
reuses the same version. A changed record increments `versionNumber`, keeps the
same `setId` root and extension, creates a new document `id`, and renders a CDA
`relatedDocument typeCode="RPLC"` that names the exact previously committed
`id`, `setId`, and version. This production role is available only when the
compiled document admits the root `relatedDocument` slot.

Record validation and rendering failures are isolated under
`state/quarantine/<run-id>/` and do not stop later records. Systemic
configuration, extraction, and state errors abort the run. The site-owned
`operation.failure_threshold` controls whether the final process result accepts
a bounded number of quarantined or delivery-failed records. Every runtime run
is recorded with its status and summary.

`run-source` joins extraction and the ordinary runtime without creating a
second normalization or rendering implementation. `--dry-run` still creates a
replayable source snapshot but emits, delivers, and commits no document.
`source.require_snapshot_advance` may guard scheduled replicated sources by
requiring the case query's maximum write timestamp to exceed the last completed
source run. Sites where quiet days do not advance that timestamp must disable
this guard or provide a replication watermark with the stated property.

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

Fixture coverage treats both structured field selections and checked
narrative-only sources as mapped. This ensures reviewed wording-only fields are
exercised without pretending they produced structured target assignments.

## Transport

Site configuration selects one built-in adapter by exact name. Each adapter has
a closed option schema and is validated before document or network I/O.
Configuration cannot import arbitrary code.

The `http-post` adapter sends one CDA document by HTTP(S) POST and accepts only
URL, positive timeout, and single-line scalar headers. Its remote
acknowledgement and crash-window semantics remain protocol-specific.

The `spool` adapter is the local handover boundary for file-based integration.
It atomically renames a complete directory containing the XML and its sidecar
into `directory/YYYY-MM/<document-stem>/`. Repeating an identical publication
is successful; an existing destination with different bytes is never removed
or overwritten. SQLite records the document as `published` only after that
directory is visible. Consumption and acknowledgement beyond the spool remain
the downstream system's responsibility.

Authentication, batch envelopes, remote acknowledgement parsing, and receiver
idempotency are not generic configuration knobs; they require a concrete
protocol adapter and matching durable state contract.

Those unresolved receiver concerns are tracked in
[`../open-boundaries.md`](../open-boundaries.md).
