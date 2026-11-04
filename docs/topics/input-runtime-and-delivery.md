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
This also applies when an input transform returns a code/system object: it must
identify one exact admitted source member. Canonical labels and display names
come from that member, not from the transform.

Both concise `SOURCE:COLUMN` locators and locator objects are current syntax.
Only explicit `null` means unmapped; malformed entries, empty mapping lists,
unknown executable keys and invalid transforms fail configuration admission.
CSV headers must be non-empty and unique, and every row must have exactly the
header width. Integer parsing preserves exact values and rejects fractions;
all numeric input must be finite. An invalid scalar quarantines its record.

A scalar field read from multiple rows requires exactly one explicitly marked
primary row. Source order alone never selects a scalar clinical fact. Repeated
group minima and maxima are checked independently within every parent occurrence;
required children of inactive optional groups remain inactive.

### Optional database source stage

An ODBC or SQLite deployment configures `site.json:source` and one reviewed SQL
file per declared `input.sources` entry. Every query receives exactly one positional
lower-bound date. The case source must return its configured join column and
`source.written_at_column`; each other query must return its global or
source-specific join column plus configured occurrence/primary columns. An ODBC
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

Native SQLite uses `source.adapter: sqlite` and a non-empty `source.database`
filename. Absolute filenames are accepted; relative filenames resolve beside
the actual `site.json`, including the default release-wide site file and
`--site-config` overrides. SQL paths still resolve against the transaction
bundle. SQLite never imports `pyodbc` and needs no ODBC driver. ODBC installation
uses the optional `odbc` package extra.

The SQLite file must already exist and contain a valid database. The adapter
opens it with URI `mode=ro`, enables query-only mode, and establishes one read
transaction for the complete extraction. Site SQL is restricted to reads and
computations, including CTEs; it cannot attach databases, change pragmas, or end
that transaction. Closing the connection releases the snapshot. A concurrent
writer cannot cause case and child queries to observe different revisions.
The adapter does not open SQLite's `immutable` mode because the source may be
updated between runs.

SQLite receives the lower-bound parameter as explicit `YYYY-MM-DD` text,
without Python's implicit date adapters. SQLite queries must return timestamps
as ISO text in a consistent timezone/format so date-window and maximum-write
comparisons remain meaningful. Numeric or engine-specific dates need explicit
site-owned SQL conversion. Scalar serialization and all subsequent clinical
normalization remain shared with ODBC and external CSV input. The snapshot
manifest records the selected adapter.

Rows are deterministically ordered by join key, optional site-owned
`order_by`, configured occurrence keys, and remaining columns. `order_by`
records clinically meaningful row order such as diagnosis rank; remaining
columns are only deterministic tie-breakers. Native integers, finite decimals,
and floats compare numerically; text remains text even when it looks numeric.
For mixed columns, finite numbers precede non-finite numbers, then text and
other serialized scalars; nulls sort last. Serialization remains unchanged.
Duplicate `1:1` keys, missing
required columns, orphan child keys, absent query files, and query failures
abort the complete snapshot. No partially populated final directory becomes
visible.

The extraction window is a change-detection rescan, not a declaration that
older cases ceased to exist. Runtime therefore never uses absence from a
bounded database snapshot—or from a `--limit` development run—to delete another
record's pending artifact.

## Occurrences and validation

One source occurrence remains one normalized occurrence. A missing value never
shifts a sibling occurrence. A one-file, one-level repeated source may retain
its declared source order; independent nested repetitions require explicit
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

Loading the runtime bundle checks the stable shapes of its models, mappings
and site configuration. The returned bundle has named products; malformed
nested executable data fails before ingestion. These structural checks do not
replace terminology, occurrence or construction validation.

Before input processing or delivery, the selected mapping lock must match the
release key/date, transaction key/OID/date, and exact compiled model and CDA
digests. The same admission function serves runtime and mapping checks. The
mapping hash recorded at creation is provenance; reviewed mapping edits remain
possible without silently authorizing a different compilation. Sending commands
also validate their complete transport contract before extraction or rendering.


The runtime sequence is:

```text
optional database extraction -> immutable external input snapshot
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
CDA identities, delivery status, and a run ledger. Only the current SQLite
schema is supported; legacy JSON state and older schemas require an explicit
external conversion rather than an automatic migration. A workspace lock prevents overlapping transforming or delivering commands.

State advances only after the selected transport reports a successful
handover. A crash before that point leaves the record pending; retry therefore
reuses the same version and the exact pending XML and sidecar bytes. Pending
artifacts record their preparation time and XML checksum; reuse and delivery
reject incomplete identities, state keys, replacement lineage, timestamps or
checksums. Missing checksums and file modification times are never substitutes
for current sidecar metadata. Delivered XML and sidecars remain available for
every history entry, including superseded versions; cleanup removes only
uncommitted pending artifacts.

Before pruning or replacing output, a transforming command recovers any exact
local spool publication whose delivery-state commit was interrupted. It records
only a handover that is already visible, so changed source data can then produce
the next version with the correct predecessor. The summary's `recovered` count
reports those commits separately from newly emitted or sent documents. A dry
run never performs recovery or commits document state. Unpublished stale output
still follows ordinary invalidation rules.

A changed record increments `versionNumber`, keeps the
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
run for that source stream. The stream covers the transaction OID and effective
date, adapter, resolved SQLite filename or configured ODBC connection identity,
input relationships, write-timestamp column, and SQL content hashes. Connection
identity is stored only as part of an opaque digest, never as a connection
string. Changing database, queries, or transaction starts an independent
baseline; changing only the rescan window does not. Only run entries carrying
that exact stream identity can establish its baseline.

Sites where quiet days do not advance that timestamp must disable
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

The month comes from the persisted preparation time, so a retry after a month
boundary still addresses the same publication. A missing or invalid timestamp
is an error. Preserve pending artifacts and their
metadata until handover and state recovery have completed.

Authentication, batch envelopes, remote acknowledgement parsing, and receiver
idempotency are not generic configuration knobs; they require a concrete
protocol adapter and matching durable state contract.

Those unresolved receiver concerns are tracked in
[`../open-boundaries.md`](../open-boundaries.md).
