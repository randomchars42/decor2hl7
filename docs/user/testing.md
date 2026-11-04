# Set up tests for each workflow

Use the same reviewed specification across three kinds of tests:

| Level | What you prepare | What to inspect |
|---|---|---|
| [Specification and mapping](#1-test-the-specification-and-mapping) | Authored cases and expected fields or templates | Mapping-test results and CDA conformance |
| [Site input](#2-test-the-site-input) | Your site configuration and representative source rows | Joins, parsing, aliases, repeated rows, and extraction |
| [Runtime and delivery](#3-test-runtime-and-delivery) | An isolated workspace and local spool | Pending output, delivery, replay, corrections, and failures |

Examples use `2026.1.2 / notaufnahmeregister--60`. Replace the keys and source
checkout path for your selected specification. Python and decor2hl7 must be
installed; independent CDA validation also needs Java and the fetched validation
packages.

## Prepare a test workspace

The workflow guides begin with [workspace creation](specification-and-mapping.md#set-up-the-practice-workspace)
and [sample-data population](site-configuration.md#populate-the-practice-workspace).
If you already have that practice workspace, use it for mapping and site tests.
For a runtime rehearsal after previous deliveries, choose a new workspace path
to start with fresh history.

From the prepared workspace, copy the exact selected setup into a **new**
directory when starting independently:

```bash
mkdir /data/decor2hl7-test
cp -a decor2hl7.json spec model mapping /data/decor2hl7-test/
```

If the setup uses `config/`, copy it with
`cp -a config /data/decor2hl7-test/` as well. Then change to the test workspace
with `cd /data/decor2hl7-test`. Run the remaining commands there.

The test workspace creates its own `out/` and `state/`; leave production output
and state in their original workspace. `--test-dir` relocates a mapping fixture
only. Runtime output and SQLite history always belong to the selected workspace.

## 1. Test the specification and mapping

Begin in the [test workspace](#prepare-a-test-workspace) prepared above.

### Prepare authored cases

Start from the complete [reference scenario](../../tests/fixtures/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases/README.md)
for this release. Copy it to a new directory before adapting cases:

```bash
cp -a /path/to/decor2hl7/tests/fixtures/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases \
  /data/decor2hl7-test-cases
```

The copied directory contains `scenario.json` and `input/` CSVs. Keep these
parts aligned when adding or changing cases:

| In `scenario.json` | What to set |
|---|---|
| `release`, `transaction` | Match the workspace's release key, transaction key, OID, and effective date. |
| `input` | Name every CSV, its join column, cardinality, and occurrence keys. CSV data columns use exact `model.json` field paths. |
| `codes`, `site.cda` | Supply test aliases and required test-site construction values. |
| `expected.cases`, `expected.documents` | List case identifiers in case-CSV order and the corresponding document count. |
| `expected.case_fields` | Declare fields that must be present or absent after normalization, and `present_templates` or `absent_templates` for each case. |
| `expected.coverage` | Require all mapped fields, or state the intended coverage and any reviewed exclusions explicitly. |

For example, add these expectations to `SCENARIO-01` in `scenario.json`, keeping
the existing case and branch expectations:

```json
{
  "expected": {
    "case_fields": {
      "SCENARIO-01": {
        "present": ["patient.anschrift.postleitzahl"],
        "present_templates": ["1.2.276.0.76.3.1.195.10.93"]
      }
    }
  }
}
```

Retain the required data in all related CSVs. Include separate cases for mutually
exclusive branches and multiple rows for repeated groups. Establish expected
meaning from the authored source and reviewed mapping, then compare the output
with that expectation.

### Create and run the fixture

The setup creates this disposable fixture from your authored source:

```text
test/mapping/
├── input/                   copied scenario CSVs
├── config/
│   ├── site.json            generated test-site configuration
│   ├── csv-mapping.json
│   └── codes-mapping.json
├── expected.json            generated expectations and provenance
└── out/                     results.md, results.json, and example XML
```

Edit the authored `scenario.json` and CSVs, then rerun setup to refresh the
fixture. Use `--force` when intentionally replacing an existing fixture.

```bash
decor2hl7 check-cda-mapping
decor2hl7 setup-test --scenario /data/decor2hl7-test-cases --test-dir test/mapping
decor2hl7 test-cda-mapping --test-dir test/mapping
decor2hl7 validate-cda test/mapping/out/*.xml --report test/mapping/out/conformance
```

Expect `PASS` in `test/mapping/out/results.md`. In `results.json`, examine
`configuration_errors`, `coverage.mapped_fields_not_exercised`, and
`test_warnings`. Open `conformance.md` for validation stages and its JSON for
complete diagnostics. Compare actual values and occurrence placement in the XML
with the source CSVs; presence expectations alone do not check every value.

The fixture uses its own CSV mappings and site values. To verify your site's
configuration, continue with level 2. Generated input from `setup-test` without
`--scenario` is useful for smoke testing but may conflict with mutually exclusive
clinical branches.

## 2. Test the site input

Use the separate [test workspace](#prepare-a-test-workspace) for these checks.

### Exercise your actual site configuration

Copy your reviewed site files into one test bundle. From the test workspace,
using `/data/decor2hl7-work` as the prepared site's workspace:

```bash
mkdir -p test/site
cp /data/decor2hl7-work/site/2026.1.2/site.json test/site/
cp /data/decor2hl7-work/site/2026.1.2/notaufnahmeregister--60/csv-mapping.json test/site/
cp /data/decor2hl7-work/site/2026.1.2/notaufnahmeregister--60/codes-mapping.json test/site/
```

Copy any transaction SQL files beside these files, preserving their relative
paths. With `--site-config test/site`, all three JSON files live together.
Relative database paths now resolve beside this copied `site.json`.

In `test/site/site.json`, use approved test identifiers, a test database or
non-production export, and this local transport:

```json
{
  "transport": {
    "adapter": "spool",
    "directory": "/data/decor2hl7-test/test/spool"
  },
  "operation": { "failure_threshold": 0 }
}
```

Merge these settings into the copied file. For a CSV-only test, set
`source.adapter` to `null`. For database extraction, point the copied source
settings and credential variable at the test database.

Put complete representative CSVs in `/data/site-test-input/`, using the site's
actual filenames and columns. Include local codes, empty optional values,
timestamps, and multiple child rows for one case. Check the copied mappings:

```bash
decor2hl7 check --site-config test/site
decor2hl7 check-input --site-config test/site --input /data/site-test-input
```

For a database, extract into a fresh directory and validate its CSVs instead:

```bash
decor2hl7 extract-source --site-config test/site \
  --output test/snapshots/site-1 --since 2026-01-01
decor2hl7 check-input --site-config test/site --input test/snapshots/site-1
```

Compare the snapshot manifest's row counts and write timestamp with the test
database. Check that each child's case and occurrence keys survive extraction.
Repeat with a separate invalid input copy: remove a required column, duplicate
a `1:1` case, or supply an invalid code. Expect a nonzero result with a useful
diagnostic. Keep the valid input for the runtime rehearsal.

### Build a runnable SQLite baseline

To try the complete pipeline before adapting your site, turn the authored
fixture from level 1 into a SQLite bundle. From the test workspace:

```bash
python3 /path/to/decor2hl7/scripts/create_sqlite_test_source.py \
  --fixture test/mapping --output test/sqlite-source \
  --written-at 2026-06-01T12:00:00Z
decor2hl7 check --site-config test/sqlite-source
decor2hl7 extract-source --site-config test/sqlite-source \
  --output test/snapshots/baseline-1 --since 2026-01-01
decor2hl7 check-input --site-config test/sqlite-source --input test/snapshots/baseline-1
```

Use an unused output path. `test/sqlite-source/` contains `source.sqlite`,
`site.json`, both mapping JSONs, `sql/`, and `fixture.json`. Its transport writes
to its own `spool/`; the freshness guard is disabled to permit identical replay.
This baseline exercises the generated fixture's layout. Your own export,
queries, ODBC driver, and local mappings need the site-specific checks above.

## 3. Test runtime and delivery

Use the [SQLite baseline](#build-a-runnable-sqlite-baseline) in the separate
[test workspace](#prepare-a-test-workspace), or substitute `test/site` for your
database rehearsal. For CSV input, prepare with
`transform --site-config test/site --input /data/site-test-input` and replay with
`run` using those options plus `--send`.

### Prepare, validate, deliver, and replay

Start with a fresh test workspace history and run the following sequence:

```bash
decor2hl7 run-source --site-config test/sqlite-source --since 2026-01-01 --dry-run
decor2hl7 run-source --site-config test/sqlite-source --since 2026-01-01
decor2hl7 validate-cda out/2026.1.2/notaufnahmeregister--60/*.xml \
  --report test/runtime/conformance
decor2hl7 send --site-config test/sqlite-source
decor2hl7 status
decor2hl7 run-source --site-config test/sqlite-source --since 2026-01-01 --send
```

| Step | Expected result and where to look |
|---|---|
| Dry run | A snapshot and run-ledger entry appear under `state/`; no XML or document version is committed. |
| Prepare | XML/JSON pairs appear under `out/2026.1.2/notaufnahmeregister--60/` and remain pending. Inspect sidecar warnings and compare XML with the source. |
| Validate | `test/runtime/conformance.md` and `.json` describe the independent CDA checks. Resolve failures before delivery. |
| Send | Pairs appear under `test/sqlite-source/spool/YYYY-MM/<document-stem>/`; `status` shows no pending documents for the batch. |
| Replay | Unchanged records produce no additional committed versions or spool entries. |

For a site with the freshness guard enabled, an unchanged database snapshot may
be rejected. Disable that guard only in the replay-test configuration, or test
against an advancing replication watermark.

### Exercise a correction and a failure

In the baseline's `test/sqlite-source/source.sqlite`, change one mapped value
with a SQLite client. For example:

```sql
UPDATE cases
SET "patient.anschrift.postleitzahl" = '10117',
    "_decor2hl7_written_at" = '2026-06-02T12:00:00Z'
WHERE case_id = 'SCENARIO-01';
```

Prepare again without delivery. Expect a new version for that case. Check its
stable CDA `setId`, new document `id`, incremented `versionNumber`, and `RPLC`
reference to the committed predecessor. Repeating preparation before sending
should reuse the same pending version and payload checksum. Then validate and
send the correction:

```bash
decor2hl7 run-source --site-config test/sqlite-source --since 2026-01-01
decor2hl7 validate-cda out/2026.1.2/notaufnahmeregister--60/*-v2.xml \
  --report test/runtime/correction
decor2hl7 send --site-config test/sqlite-source
decor2hl7 status
```

For a rejection test, temporarily replace a valid integer in the test database:

```sql
UPDATE cases
SET "scores.glasgow_coma_scale_gcs.gcs_summe" = 'not-a-number'
WHERE case_id = 'SCENARIO-01';
```

Run the preparation command again without `--send`. Expect a nonzero result
with the zero failure threshold. Inspect `state/quarantine/<run-id>/*.json` for
the case and parsing error. A separate CSV test can remove a required column to
exercise a structural failure, reported by the command. Restore valid input
from the authored case before continuing.

Local spool tests establish handover. Receiver acceptance needs a configured
test receiver: verify import and stored values for both the initial document
and its correction. The [open receiver boundaries](../open-boundaries.md#validation-and-delivery)
describe the remaining profile and protocol constraints.

For changes to decor2hl7 itself, use the separate
[developer checks](../../README.md#project-maintenance), including unit and exact
reference-workspace verification.
