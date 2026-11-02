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
- optional ODBC or SQLite extraction queries, window, and replication guard;
- transport configuration when delivery is enabled.

Keep values from one repeated source occurrence together. If two tables repeat
independently, configure explicit keys for each level; do not align them by row
position.

Local aliases may normalize input into a formal dataset domain, but they do not
extend the specification's terminology. If a source value has no approved
meaning in the selected dataset, return it to review instead of inventing a
code mapping.

For direct extraction from a read-only replica, set `source.adapter` to
`odbc`, put one query below the transaction site bundle for every configured
input source, and name each query in `source.queries`. For example:

```json
{
  "source": {
    "adapter": "odbc",
    "dsn_env": "DECOR2HL7_ODBC_DSN",
    "written_at_column": "replica_written_at",
    "window_days": 90,
    "queries": {
      "cases": "sql/cases.sql",
      "diagnoses": "sql/diagnoses.sql"
    },
    "require_snapshot_advance": true
  },
  "operation": {"failure_threshold": 0},
  "transport": {"adapter": "spool", "directory": "var/spool"}
}
```

For a repeated input source whose row order carries meaning, add an ordered
`order_by` column list to that source under `input.sources` (for example,
`"order_by": ["diagnosis_rank"]`). Occurrence keys still define identity;
`order_by` defines presentation/order, and all remaining columns are used only
as deterministic tie-breakers.

Each SQL file must accept one positional `?` lower-bound date. The case query
returns exactly one row per case plus its configured join column and the
configured write timestamp. A child query returns its global or
source-specific join column, configured occurrence/primary columns, and zero or
more rows for cases in the same window. Keep clinical selection and joins
explicit in SQL; decor2hl7 does not generate site queries. Set the environment
variable to the DSN or connection string outside JSON.

Enable `require_snapshot_advance` only if the selected write timestamp or
replication watermark advances for every successful scheduled replication.
Otherwise a legitimate quiet day is indistinguishable from a stale replica;
disable the guard and monitor replication separately.

### SQLite input and a local integration test

Set `source.adapter` to `sqlite` and `source.database` to an existing SQLite
filename. Keep the same input sources, SQL query contract, joins, occurrence
keys, and site mappings. For example:

```json
{
  "source": {
    "adapter": "sqlite",
    "database": "/data/synthetic/source.sqlite",
    "written_at_column": "written_at",
    "window_days": 90,
    "queries": {
      "cases": "sql/cases.sql",
      "diagnoses": "sql/diagnoses.sql"
    },
    "require_snapshot_advance": false
  }
}
```

A relative database filename resolves beside `site.json`; SQL filenames resolve
against the transaction bundle. The adapter opens an existing database
read-only and holds one consistent read transaction across all queries. No
SQLite ODBC driver or `pyodbc` installation is needed. Use ISO text timestamps
in one consistent timezone/format; the lower-bound `?` is `YYYY-MM-DD` text.
Write queries for SQLite's SQL dialect.

For a repeatable integration test, use the authored reference scenarios already
maintained in this repository. From the source checkout, after preparing the
matching compiled models and reviewed mapping in the companion workspace:

```bash
decor2hl7 --root ../test-workplace setup-test \
  --scenario tests/fixtures/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases \
  --test-dir /tmp/decor2hl7-authored
python3 scripts/create_sqlite_test_source.py \
  --fixture /tmp/decor2hl7-authored --output /tmp/decor2hl7-sqlite \
  --written-at 2026-06-01T12:00:00Z
decor2hl7 --root ../test-workplace check --site-config /tmp/decor2hl7-sqlite
decor2hl7 --root ../test-workplace run-source \
  --site-config /tmp/decor2hl7-sqlite --since 2026-01-01 --dry-run
decor2hl7 --root ../test-workplace run-source \
  --site-config /tmp/decor2hl7-sqlite --since 2026-01-01 --send
```

Choose new fixture and output paths for each setup. The builder preserves raw
CSV values, adds an explicit synthetic case-write timestamp, and creates a
SQLite database, SQL queries, copied site mappings, provenance, and a site
configuration that publishes to the bundle's `spool/` directory. It refuses
existing output. Its source data is the authored fixture; generated CDA is not
used as the expected result.

The test configuration disables `require_snapshot_advance` so the same fixture
can be replayed. The initial send publishes documents; an unchanged repeat
publishes no new versions. A change to a mapped source value exercises the
normal correction and replacement-lineage path. Source and runtime-state
SQLite files have separate ownership. Runtime output and delivery history still
belong to the selected workspace, even with a test site override; use a
separate test workspace to keep an independent history.

The spool is a local handover. Testing an AKTIN container additionally requires
its supported import interface and confirmation that it accepted the documents.

## 3. Validate the configuration and input

```bash
decor2hl7 check
decor2hl7 check-input --input /data/clinical-export
decor2hl7 extract-source --output /data/snapshots/acceptance-1
decor2hl7 check-input --input /data/snapshots/acceptance-1
```

`check` verifies the selected workspace products and configuration. For either
database adapter it also checks query files and connectivity; ODBC additionally
requires its credential environment variable.
`check-input` reads and validates the source snapshot without generating CDA.
`extract-source` is optional and never changes document lineage; its output is
an immutable CSV snapshot that can be replayed through `check-input`,
`transform`, or `run`.
Resolve errors at the layer that owns them:

- file, column, join, parsing, local code, or timezone errors belong to the
  site configuration;
- missing or disputed dataset-to-CDA meaning belongs to the mapping review;
- missing specification artifacts belong to the specification workflow.

If a deployment always uses one input directory, it may be recorded as the
optional site default. An explicit `--input` path remains useful for testing a
specific snapshot.

## 4. Hand off to operations

Provide the approved site bundle, the matching reviewed mapping, and either the
location of the external input snapshot or the reviewed SQL query bundle to the
runtime operator. Record how source and transport credentials are supplied; do
not place secrets in shared mapping documentation.

Before production use, run the first transformation without delivery and
inspect its validation result and output. Continue with
[Operate document generation](runtime-operation.md).

Technical details about joins, occurrences, validation layers, state, and
transport are in
[`topics/input-runtime-and-delivery.md`](../topics/input-runtime-and-delivery.md).
