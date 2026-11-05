# Set up tests for each workflow

Use the same reviewed specification across three kinds of tests:

| Level | What you prepare | What to inspect |
|---|---|---|
| [Specification and mapping](#1-test-the-specification-and-mapping) | Authored cases and expected fields or templates | Mapping-test results and CDA conformance |
| [Site input](#2-test-the-site-input) | Your site configuration and representative source rows | Joins, parsing, aliases, repeated rows, and extraction |
| [Runtime and delivery](#3-test-runtime-and-delivery) | An isolated workspace and local spool | Pending output, delivery, replay, corrections, and failures |

Examples use `2026.1.2 / notaufnahmeregister--60`. Replace the keys for your
selected specification. Python and decor2hl7 must be installed; independent CDA
validation also needs Java and the fetched validation packages.

For a complete fictional SQLite rehearsal, start with the
[integration setup command](#build-a-runnable-sqlite-baseline). It creates an
independent workspace and input database in one step. Use levels 1 and 2 to
adapt authored cases or test your own site configuration.

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

To use the complete [reference scenario](../../src/decor2hl7/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases/README.md)
without changing its cases, prepare it by its packaged name:

```bash
decor2hl7 setup-test --scenario valid-reference-cases --test-dir test/mapping
```

The installed application selects the exact release and transaction. Packaged
reference cases exist for `2026.1.2` and `2026.1.3`, both with transaction
`notaufnahmeregister--60`. An unavailable identity fails rather than using
another version's cases.

To change cases, copy the scenario directory from the source checkout or the
`scenario/` snapshot in a [generated rehearsal](#build-a-runnable-sqlite-baseline)
to `/data/decor2hl7-test-cases`. It contains `scenario.json` and `input/` CSVs.
Keep these parts aligned when adding or changing cases:

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

For custom cases, edit the authored `scenario.json` and CSVs, then refresh the
fixture before testing:

```bash
decor2hl7 setup-test --scenario /data/decor2hl7-test-cases --test-dir test/mapping --force
```

`--force` deliberately replaces an existing fixture after source or mapping
changes. For either packaged or custom cases, run:

```bash
decor2hl7 check-cda-mapping
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

To try extraction and runtime with fictional data, start from a reviewed
specification workspace. Replace `/data/decor2hl7-reference` with its location;
guide 1's `/data/decor2hl7-test` also works. The source needs its selected fetched
specification, compiled models, reviewed CDA mapping, and matching lock.

```bash
decor2hl7 --root /data/decor2hl7-reference setup-integration-test \
  --output /tmp/decor2hl7-integration
cd /tmp/decor2hl7-integration/workspace
decor2hl7 check
decor2hl7 extract-source --output ../input/baseline-1 --since 2026-06-01
decor2hl7 check-input --input ../input/baseline-1
```

Use a new output directory outside both the source workspace and any custom
scenario directory. If you used this path in guide 3, choose another here for
fresh delivery history. Setup copies the exact specification evidence, selected
models and validator, reviewed mapping and lock, and required `config/` files.
The copies are independent, including files reached through source symlinks,
and can be large. Mapping-review reports remain in the source workspace.

The result separates source data from runtime:

```text
/tmp/decor2hl7-integration/
├── README.md                  commands for this setup
├── integration-test.json      identities, expected cases and initial checksums
├── scenario/                  preserved authored scenario.json and input CSVs
├── fixture/                   mapping-test input, config, and expected.json
├── input/
│   ├── source.sqlite          synthetic source database
│   └── baseline-1/            snapshot created by extract-source above
└── workspace/
    ├── decor2hl7.json
    ├── spec/                  exact release evidence and validation tools
    ├── model/                 selected compiled models and validator
    ├── mapping/               reviewed CDA mapping and lock
    └── site/                  scenario-specific values, mappings and SQL
```

Setup uses `valid-reference-cases` for the exact selected identity. To use custom
cases, add `--scenario /data/decor2hl7-test-cases`; the release key, transaction
key, OID, and effective date must match. `--written-at 2026-06-01T12:00:00Z`
sets the synthetic case-write timestamp; this is the default and needs a
timezone. Use its date as `--since` when running the rehearsal.

The site bundle comes from the authored scenario, with local `spool/` transport.
Source site settings, output, and runtime history are left in the source
workspace. Setup performs no fetch, rebuild, extraction, transformation, or
delivery. The commands above then verify extraction: compare the snapshot
manifest's row counts and maximum write timestamp with `../integration-test.json`.
The long extraction window and disabled freshness guard permit fixed-input
replay. Your actual export, queries, ODBC driver, and local mappings need the
site-specific checks above.

## 3. Test runtime and delivery

Use the [SQLite baseline](#build-a-runnable-sqlite-baseline) in the separate
`/tmp/decor2hl7-integration/workspace`, with its own output and history. Run the
commands below from that directory. To test your own site, use the
[copied test workspace](#prepare-a-test-workspace) instead and add
`--site-config test/site` to each command that consumes site configuration.
For CSV input, prepare with
`transform --site-config test/site --input /data/site-test-input` and replay with
`run` using those options plus `--send`.

### Prepare, validate, deliver, and replay

Start with a fresh test workspace history and run the following sequence:

```bash
decor2hl7 run-source --since 2026-06-01 --dry-run
decor2hl7 run-source --since 2026-06-01
decor2hl7 validate-cda out/2026.1.2/notaufnahmeregister--60/*.xml \
  --report test/runtime/conformance
decor2hl7 send
decor2hl7 status
decor2hl7 run-source --since 2026-06-01 --send
```

| Step | Expected result and where to look |
|---|---|
| Dry run | A snapshot and run-ledger entry appear under `state/`; no XML or document version is committed. |
| Prepare | XML/JSON pairs appear under `out/2026.1.2/notaufnahmeregister--60/` and remain pending. Inspect sidecar warnings and `source_snapshot`; compare XML with `../fixture/input/` and expected cases in `../fixture/expected.json`. |
| Validate | `test/runtime/conformance.md` and `.json` describe the independent CDA checks. Resolve failures before delivery. |
| Send | Pairs appear under `spool/YYYY-MM/<document-stem>/`; `status` shows no pending documents for the batch. |
| Replay | Unchanged records produce no additional committed versions or spool entries. |

For a site with the freshness guard enabled, an unchanged database snapshot may
be rejected. Disable that guard only in the replay-test configuration, or test
against an advancing replication watermark.

### Exercise a correction and a failure

In the baseline's `../input/source.sqlite`, change one mapped value
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
decor2hl7 run-source --since 2026-06-01
decor2hl7 validate-cda out/2026.1.2/notaufnahmeregister--60/*-v2.xml \
  --report test/runtime/correction
decor2hl7 send
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

### Rehearse delivery to a test receiver

Prepare a separate environment with the agreed HTTP endpoint:

```bash
decor2hl7 --root /data/decor2hl7-reference setup-integration-test \
  --output /tmp/decor2hl7-receiver-test \
  --receiver-url http://127.0.0.1:9090/aktin/cda/fhir/Binary
```

Replace the URL with your test receiver's endpoint. Setup sends nothing. Change
to `/tmp/decor2hl7-receiver-test/workspace`, then follow the prepare and validate
steps above before sending. In this environment `send` uses HTTP instead of
spool. Verify receiver validation, import, stored values, and correction
acceptance separately. The [open receiver boundaries](../open-boundaries.md#validation-and-delivery)
describe the remaining profile and protocol constraints.

Recreate disposable environments from their reviewed source and scenario. Keep
exact validated documents, checksums, reports, and receiver responses separately
when preserving acceptance evidence; newly generated documents do not replace
that evidence.

For changes to decor2hl7 itself, use the separate
[developer checks](../../README.md#project-maintenance), including unit and exact
reference-workspace verification.
