# Configure a site's input

Connect your source export to the reviewed dataset model.

## Workspace for site configuration

Start with the matching specification and reviewed mapping from guide 1. This
workflow adds the source snapshot and site configuration:

```text
/data/decor2hl7-test-input/                    CSV copy for the column/join exercise
/data/decor2hl7-site-test/
├── README.md                                commands for the generated setup
├── integration-test.json                     identities and initial checksums
├── scenario/                                preserved authored cases
├── fixture/                                 fictional CSVs and expected.json
├── input/source.sqlite                      synthetic source, outside workspace/
└── workspace/
    ├── decor2hl7.json                        selected specification
    ├── spec/                                exact evidence and validation tools
    ├── model/2026.1.2/notaufnahmeregister--60/ compiled models and validator
    ├── mapping/2026.1.2/notaufnahmeregister--60/ reviewed mapping and lock
    └── site/2026.1.2/
        ├── site.json                        input relationships and test-site values
        └── notaufnahmeregister--60/          CSV/code mappings and extraction SQL
```

Read field names from `model/` and mapping decisions from `mapping/`. Record
local filenames, columns, codes, and joins in `site/`.

## Populate the practice workspace

Use the reviewed `/data/decor2hl7-test` setup from
[guide 1's setup](specification-and-mapping.md#set-up-the-practice-workspace).
If starting here, substitute your prepared specification workspace. Its selected
models, reviewed mapping, lock, and fetched specification must agree.

Create a separate environment with a matching packaged scenario, then check its
generated SQLite source:

```bash
decor2hl7 --root /data/decor2hl7-test setup-integration-test \
  --output /data/decor2hl7-site-test
cd /data/decor2hl7-site-test/workspace
decor2hl7 check
decor2hl7 extract-source --output ../input/baseline-1 --since 2026-06-01
decor2hl7 check-input --input ../input/baseline-1
cp -a ../fixture/input /data/decor2hl7-test-input
```

Use new environment, snapshot, and CSV-copy directories; the environment must be
outside the source workspace. Expect a complete CSV set in `../input/baseline-1/`,
including cases, diagnoses, medications, and vital signs. Compare row counts and
the fixed write timestamp in `.decor2hl7-snapshot.json` with
`../integration-test.json`.

The generated site files contain fictional identifiers, local aliases, required
CDA values, SQL, and local spool transport. They describe the scenario; test
your actual site configuration separately using the [site test setup](testing.md#2-test-the-site-input).
The setup copies selected runtime models and the reviewed mapping; keep the
source workspace for the full mapping-review reports.

For the CSV exercise below, the last command makes an editable copy of the
authored input. In `site/2026.1.2/site.json`, set `source.adapter` to `null` to
use that copy. Then adapt two column mappings and a diagnosis key, keeping all
other supplied data and configuration.

Examples use release `2026.1.2`, transaction `notaufnahmeregister--60`, and
commands run from the workspace root. JSON examples are excerpts to merge into
the named generated files; retain the rest of their configuration.

## 1. Prepare a small source snapshot

In `/data/decor2hl7-test-input/`, rename only these CSV headers to simulate a
local export:

| File | Existing header | New header |
|---|---|---|
| `cases.csv` | `patient.anschrift.postleitzahl` | `postcode` |
| `diagnoses.csv` | `occurrence_1` | `diagnosis_id` |
| `diagnoses.csv` | `abschlussdiagnosen.abschlussdiagnose.freitext_abschlussdiagnose` | `diagnosis_text` |

Keep every other column and row. The relevant part of the input layout is:

```text
/data/decor2hl7-test-input/
├── cases.csv
└── diagnoses.csv
```

These excerpts show only the renamed columns. `cases.csv` has one row per case:

```csv
case_id,postcode
SCENARIO-01,10111
SCENARIO-02,10112
```

`diagnoses.csv` has one row per diagnosis, with the same case key and a stable
diagnosis identifier:

```csv
case_id,diagnosis_id,diagnosis_text
SCENARIO-01,diagnosis-1,"Kreislaufstillstand, erfolgreich reanimiert"
SCENARIO-02,diagnosis-1,Akute schwere Asthmaexazerbation
```

All files in a snapshot describe the same cases and related rows. For your own
site, replace this fictional export with representative source files and retain
the selected dataset's required values.

Generate proposals using the actual join column, then initialize the site files:

```bash
decor2hl7 propose-input --input /data/decor2hl7-test-input --join-column case_id
decor2hl7 init-site-config
```

## 2. Review the generated files in order

The default layout separates release-wide settings from transaction mappings:

```text
site/2026.1.2/
├── site.json
└── notaufnahmeregister--60/
    ├── csv-mapping.json
    ├── csv-mapping.md
    ├── codes-mapping.json
    ├── codes-mapping.md
    └── *.proposed.json
```

1. Open `csv-mapping.md`. Find the intended dataset path and compare the
   proposed source and column with the CSV headers. Expect gaps where names do
   not match. Record the corrected choices in `csv-mapping.json`.
2. Open `codes-mapping.md`. Look for raw local values without a canonical
   dataset value. Record approved aliases in `codes-mapping.json`.
3. Edit `site.json` to describe the files, joins, repeated rows, timezone,
   identifiers, and deployment values.

The Markdown guides explain generated proposals; your edited JSON controls the
run. Initialization preserves the seeded JSON choices. Align them with the
renamed sample columns by merging these entries into
`site/2026.1.2/notaufnahmeregister--60/csv-mapping.json`:

```json
{
  "join": { "column": "case_id" },
  "fields": {
    "patient.anschrift.postleitzahl": "cases:postcode",
    "abschlussdiagnosen.abschlussdiagnose.freitext_abschlussdiagnose": "diagnoses:diagnosis_text"
  }
}
```

In `site/2026.1.2/site.json`, configure the corresponding input relationships:

```json
{
  "input": {
    "join_column": "case_id",
    "case_source": "cases",
    "delimiter": ",",
    "sources": {
      "cases": { "file": "cases.csv", "cardinality": "1:1" },
      "diagnoses": {
        "file": "diagnoses.csv",
        "cardinality": "1:n",
        "occurrence_keys": {
          "abschlussdiagnosen.abschlussdiagnose": "diagnosis_id"
        }
      }
    }
  }
}
```

The case identifier connects the files. `diagnosis_id` identifies each diagnosis
within its case; different cases may both use `diagnosis-1`. Keep the other
fixture sources and their occurrence keys when merging this excerpt. For a new
site, review every generated `1:1` assumption. If order matters, add `order_by`
columns to the source; keys still define identity.

The practice configuration supplies `timezone`, `organization`, and fictional
identifiers. For a real site, replace them with approved deployment values.
For coded input, map local aliases to accepted values shown in the code guide;
a value outside the dataset domain needs review. Run `decor2hl7 check-cda-mapping`
to list site requirements, then fill `cda.values` and `cda.fallback_if_active` in
`site.json`. For explanations, consult the source workspace's
`cda-mapping-trees-extended.md` (`◆` and `R:` lines).

The practice setup already uses a local file handover:

```json
{
  "transport": { "adapter": "spool", "directory": "spool" }
}
```

A relative spool directory resolves from the workspace root. Preserve the
portable mapping when adapting local files and codes.

## 3. Add database extraction when needed

The initial extraction exercised the generated SQLite queries. To repeat that
baseline after the CSV exercise, create a fresh
[SQLite rehearsal](testing.md#build-a-runnable-sqlite-baseline). Its original
column names differ from the renamed CSVs. The SQL excerpts below illustrate
adapting queries to your own source schema.

For ODBC or SQLite, keep the same CSV mappings and input relationships. Create
one query per input source under the transaction directory:

```text
site/2026.1.2/notaufnahmeregister--60/sql/
├── cases.sql
└── diagnoses.sql
```

For example, adapt these queries to your schema. Each accepts one lower-bound
date parameter, and its column names match the snapshot above.

`sql/cases.sql`:

```sql
SELECT case_id, postcode, written_at
FROM source_cases
WHERE written_at >= ?;
```

`sql/diagnoses.sql`:

```sql
SELECT d.case_id, d.diagnosis_id, d.diagnosis_text
FROM source_diagnoses d
JOIN source_cases c ON c.case_id = d.case_id
WHERE c.written_at >= ?;
```

In `site/2026.1.2/site.json`, a native SQLite source could use:

```json
{
  "source": {
    "adapter": "sqlite",
    "database": "/data/source/clinical.sqlite",
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

The database must exist. Relative database paths resolve beside `site.json`;
SQL paths resolve from the transaction directory. SQLite reads all queries in
one read transaction and expects ISO text timestamps in a consistent timezone.

For ODBC, set `source.adapter` to `odbc` and `source.dsn_env` to the name of
the environment variable supplying the DSN or connection string. Install the
optional [ODBC dependency and driver](../../README.md#requirements), and adapt
SQL to that database's dialect. Keep credentials outside JSON.

Enable `require_snapshot_advance` only when the case write timestamp or
replication watermark advances after every successful replication. Otherwise
leave it disabled and monitor replication separately.

## 4. Validate a snapshot and hand over

First follow the [site test setup](testing.md#2-test-the-site-input) to copy your
site bundle, prepare representative input, and check both valid and invalid
cases in an isolated workspace.

For CSV input, run the checks below. Review errors for the source filename,
column, dataset path, and offending value before changing the owning JSON file.

```bash
decor2hl7 check
decor2hl7 check-input --input /data/decor2hl7-test-input
```

For a database source, `check` also verifies queries and connectivity. Extract
into a **new** directory, then validate that exact snapshot:

```bash
decor2hl7 check
decor2hl7 extract-source --output /data/snapshots/acceptance-1
decor2hl7 check-input --input /data/snapshots/acceptance-1
```

Expect the configured CSV files and `.decor2hl7-snapshot.json` in the extracted
directory. The manifest records the window, row counts, and maximum case write
timestamp; compare these with the intended export. Extraction does not advance
document lineage.

Hand over the reviewed `site/2026.1.2/` directory, matching compiled setup and
mapping, input location or database queries, and credential instructions.
Continue with a transformation and output inspection in
[Operate document generation](runtime-operation.md). For unresolved join,
occurrence, or source behavior, consult the
[technical input contract](../topics/input-runtime-and-delivery.md).

For local delivery, unchanged replay, corrections, and rejected records, continue
with the [runtime rehearsal](testing.md#3-test-runtime-and-delivery).
