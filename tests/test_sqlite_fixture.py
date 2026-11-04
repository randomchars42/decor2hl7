from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import datetime as dt
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from decor2hl7.cli import main
from decor2hl7 import source, state
from decor2hl7.testing import synthetic_site
from decor2hl7.workspace import init_workspace, set_release, set_transaction, write_json
from decor2hl7.sqlite_fixture import create_source


class SQLiteFixtureTests(unittest.TestCase):
    @staticmethod
    def prepare(root: Path) -> Path:
        fixture = root / "fixture"
        (fixture / "input").mkdir(parents=True)
        (fixture / "input/cases.csv").write_text("case_id,note\nA,First\nB,Second\n", encoding="utf-8")
        (fixture / "input/diagnoses.csv").write_text("case_id,rank,code\nA,2,B\nA,1,A\nB,1,C\n", encoding="utf-8")
        manifest = {
            "name": "authored-source-test", "release": "release-v1",
            "transaction": {"id": "1.2.3.4.1", "key": "example--1", "effective_date": "2024-01-01T00:00:00"},
        }
        site = synthetic_site({"key": manifest["release"]}, {}, {})
        site["input"]["sources"] = {
            "cases": {"file": "cases.csv", "cardinality": "1:1"},
            "diagnoses": {"file": "diagnoses.csv", "cardinality": "1:n", "occurrence_keys": {"diagnosis": "rank"}},
        }
        write_json(fixture / "config/site.json", site)
        write_json(fixture / "config/csv-mapping.json", {"fields": {}})
        write_json(fixture / "config/codes-mapping.json", {"fields": {}})
        write_json(fixture / "expected.json", {"scenario": manifest, "cases": ["A", "B"]})
        return fixture

    def test_authored_fixture_becomes_a_replayable_source_through_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.prepare(root)
            bundle = root / "source-bundle"
            result = create_source(fixture, bundle, written_at="2026-05-03T12:00:00+02:00")
            self.assertEqual(result["written_at"], "2026-05-03T10:00:00+00:00")
            site = json.loads((bundle / "site.json").read_text(encoding="utf-8"))
            self.assertEqual(site["source"]["database"], "source.sqlite")
            self.assertFalse(site["source"]["require_snapshot_advance"])
            workspace = root / "workspace"
            init_workspace(workspace)
            set_release(workspace, {"key": "release-v1", "date": "2024-01-02T03:04:05"})
            set_transaction(workspace, result["scenario"]["transaction"])
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                status = main([
                    "--root", str(workspace), "extract-source", "--site-config", str(bundle),
                    "--output", str(root / "snapshot"), "--since", "2026-01-01",
                ])
            self.assertEqual(status, 0, output.getvalue())
            self.assertEqual(source.load_manifest(root / "snapshot")["row_counts"], result["row_counts"])
            self.assertEqual(state.load_state(workspace / "state")["documents"], {})
            source.extract(site, bundle, root / "empty", since=dt.date(2027, 1, 1))
            self.assertTrue(all(count == 0 for count in source.load_manifest(root / "empty")["row_counts"].values()))
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_source(fixture, bundle, written_at="2026-05-03T12:00:00+02:00")
            with sqlite3.connect(bundle / "source.sqlite") as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM "cases"').fetchone(), (len(result["cases"]),))

    def test_builder_rejects_unpinned_fixtures_and_naive_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.prepare(root)
            with self.assertRaisesRegex(ValueError, "timezone"):
                create_source(fixture, root / "output", written_at="2026-01-01T12:00:00")
            write_json(fixture / "expected.json", {})
            with self.assertRaisesRegex(ValueError, "authored scenario"):
                create_source(fixture, root / "output", written_at="2026-01-01T12:00:00Z")
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
