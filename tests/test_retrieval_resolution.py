from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

from decor2hl7.cda.compile import collect_templates, select_template
from decor2hl7.retrieval.artifacts import closure_records
from decor2hl7.retrieval.fetch import _fetch_want, fetch_spec
from decor2hl7.retrieval.references import (
    hard_references,
    original_references,
    soft_references,
)
from decor2hl7.retrieval.resolution import (
    candidate_projects as _candidate_projects,
    load_artifact_owners as _load_artifact_owners,
)
from decor2hl7.retrieval.api import REQUIRED_PATHS


RELEASE = {"key": "release-v1", "label": "release-v1", "date": "2024-01-02T03:04:05", "status": "final"}


TRANSACTION = {
    "key": "example--1",
    "id": "1.2.3.4.1",
    "effective_date": "2024-01-01T00:00:00",
    "version_label": "v1",
    "status": "active",
    "name": "Example transaction",
}


API_CONTRACT = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "3.10.2"},
    "paths": {path: {} for path in REQUIRED_PATHS},
}).encode()


def api_path(url: str) -> str:
    return urlsplit(url).path


class RetrievalResolutionTests(unittest.TestCase):
    def test_hard_and_soft_reference_scopes_are_distinct(self) -> None:
        root = ET.fromstring('''<dataset id="current" templateId="doc">
          <relationship type="VERSION" ref="old-dataset" flexibility="2020-01-01" prefix="main-"/>
          <concept id="current-concept">
            <relationship type="SPEC" ref="old-concept" flexibility="2020-01-01" prefix="main-" datasetId="old-dataset" datasetEffectiveDate="2020-01-01"/>
            <contains ref="external-root" datasetId="external-dataset" datasetEffectiveDate="2023-01-01" prefix="ext-"/>
          </concept>
          <template id="doc">
            <relationship type="SPEC" template="prototype" flexibility="2019"/>
            <relationship type="VERSION" template="old-template" flexibility="2018"/>
          </template>
        </dataset>''')
        hard = hard_references(root)
        soft = soft_references(root)
        self.assertEqual({row["id"] for row in hard if row["kind"] == "dataset"}, {"external-dataset"})
        self.assertNotIn("old-dataset", {row["id"] for row in hard})
        self.assertEqual(
            {row["id"] for row in soft if row["kind"] == "concept"},
            {"old-concept", "external-root"},
        )
        self.assertEqual(
            {
                (row["id"], row["role"])
                for row in soft if row["kind"] == "template"
            },
            {
                ("prototype", "template-prototype"),
                ("old-template", "mapping-evidence"),
            },
        )
        self.assertNotIn(
            "prototype", {row["id"] for row in hard if row["kind"] == "template"}
        )

    def test_association_endpoints_and_formal_origins_are_typed(self) -> None:
        root = ET.fromstring('''<project>
          <concept id="child">
            <inherit ref="parent" effectiveDate="2020" prefix="base-"
              originalId="original" originalEffectiveDate="2019"
              originalPrefix="original-"/>
            <relationship type="SPEC" ref="spec" flexibility="2018"
              prefix="base-"/>
            <relationship type="ADAPT" ref="adapted" flexibility="2017"
              prefix="weak-"/>
          </concept>
          <concept id="contained-child">
            <contains ref="contained-parent" flexibility="2021"
              prefix="base-" originalId="contained-original"
              originalEffectiveDate="2019"
              originalPrefix="original-"/>
          </concept>
          <templateAssociation templateId="active" effectiveDate="2026">
            <concept ref="dynamic-endpoint" effectiveDate="2025"
              elementId="active-element" prefix="source-"/>
          </templateAssociation>
          <template id="legacy" effectiveDate="2020" name="Legacy">
            <staticAssociations>
              <origconcept ref="static-endpoint" effectiveDate="2016"
                ident="external-" datasetId="dataset"
                datasetEffectiveDate="2015" elementId="legacy-element"/>
              <origconcept ref="second-static-endpoint" effectiveDate="2016"
                ident="external-" datasetId="dataset"
                datasetEffectiveDate="2015" elementId="second-legacy-element"/>
              <origconcept ref="bare-static-endpoint" effectiveDate="2014"
                ident="bare-" elementId="other-legacy-element"/>
            </staticAssociations>
          </template>
        </project>''')
        soft = soft_references(root)
        self.assertEqual(
            {
                (row["id"], row["effective_date"], row["project"], row["role"])
                for row in soft if row["kind"] == "concept"
            },
            {
                ("parent", "2020", "base-", "mapping-evidence"),
                ("original", "2019", "original-", "mapping-evidence"),
                ("spec", "2018", "base-", "mapping-evidence"),
                ("adapted", "2017", "weak-", "mapping-evidence"),
                ("contained-parent", "2021", "base-", "mapping-evidence"),
                ("contained-original", "2019", "original-", "mapping-evidence"),
                ("dynamic-endpoint", "2025", "source-", "association-endpoint"),
                ("static-endpoint", "2016", "external-", "association-endpoint"),
                ("second-static-endpoint", "2016", "external-", "association-endpoint"),
                ("bare-static-endpoint", "2014", "bare-", "association-endpoint"),
            },
        )
        self.assertEqual(
            {
                (
                    row["id"], row.get("dataset"),
                    row.get("dataset_effective_date"),
                )
                for row in soft if row.get("dataset") == "dataset"
            },
            {
                ("static-endpoint", "dataset", "2015"),
                ("second-static-endpoint", "dataset", "2015"),
            },
        )
        self.assertEqual(
            {
                (row["id"], row["effective_date"], row["role"])
                for row in original_references(root)
            },
            {
                ("parent", "2020", "formal-origin"),
                ("original", "2019", "formal-origin"),
                ("contained-parent", "2021", "formal-origin"),
                ("contained-original", "2019", "formal-origin"),
            },
        )
        self.assertTrue(all(
            row.get("analysis_only")
            for row in soft
            if row.get("role") == "association-endpoint"
        ))
        self.assertTrue(all(
            row.get("analysis_only") for row in original_references(root)
        ))

    def test_known_owner_stops_broad_repository_probe(self) -> None:
        want = {"kind": "dataset", "id": "1.2.3.4", "effective_date": "2020-01-01", "project": "main-"}
        self.assertEqual(
            _candidate_projects(want, {"1.2.3": "main-"}, ["main-", "pmp-", "hl7de-"]),
            ["main-"],
        )
        stale = {**want, "project": "old-"}
        self.assertEqual(
            _candidate_projects(stale, {"1.2.3": "main-"}, ["main-", "pmp-"]),
            ["main-", "old-"],
        )

    def test_configured_owner_precedes_probe_but_not_project_directory(self) -> None:
        want = {
            "kind": "template", "id": "1.2.3.4",
            "effective_date": "", "project": "",
        }
        self.assertEqual(
            _candidate_projects(
                want, {}, ["main-", "configured-"], None,
                {"1.2.3": "configured-"},
            ),
            ["configured-", "main-"],
        )
        self.assertEqual(
            _candidate_projects(
                want, {"1.2": "directory-"}, ["main-"], None,
                {"1.2.3": "configured-"},
            ),
            ["directory-"],
        )

    def test_static_template_selection_never_substitutes_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "templates.xml"
            source.write_text('''<project>
              <template id="t" effectiveDate="2007-01-01" name="Newer"/>
            </project>''', encoding="utf-8")
            templates = collect_templates([source])
            self.assertIsNone(select_template(templates, "t", "2005-01-01"))
            selected = select_template(templates, "t", "dynamic")
            self.assertIsNotNone(selected)
            assert selected is not None
            self.assertEqual(selected.get("effectiveDate"), "2007-01-01")

    def test_dynamic_and_exact_requests_share_one_canonical_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            transaction = release / "transactions" / "tx"
            transaction.mkdir(parents=True)
            artifact = release / "valuesets" / "vs.xml"
            artifact.parent.mkdir()
            artifact.write_text(
                '<valueSet id="vs" effectiveDate="2025"/>', encoding="utf-8"
            )
            base = {
                "status": "ok", "file": "valuesets/vs.xml",
                "resolved_effective_date": "2025",
                "identity": {
                    "type": "valueset", "id": "vs",
                    "effective_date": "2025", "project": "term-",
                },
            }
            dynamic = {**base, "requested_effective_date": "dynamic"}
            exact = {**base, "requested_effective_date": "2025"}
            (release / "manifest.json").write_text(json.dumps({
                "resources": {"valueset:vs": dynamic, "valueset:vs@2025": exact}
            }), encoding="utf-8")
            (transaction / "closure.json").write_text(json.dumps({
                "crawl_complete": True, "build_ready": True,
                "build_resources": ["valueset:vs", "valueset:vs@2025"],
                "resource_roles": {
                    "valueset:vs": ["formal-terminology"],
                    "valueset:vs@2025": ["formal-terminology"],
                },
            }), encoding="utf-8")
            records = closure_records(release, transaction)
            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0]["aliases"], ["valueset:vs", "valueset:vs@2025"]
            )

    def test_cached_artifact_owner_precedes_repository_probe(self) -> None:
        want = {
            "kind": "codesystem",
            "id": "2.16.840.1.113883.5.25",
            "effective_date": "",
            "project": "",
        }
        self.assertEqual(
            _candidate_projects(
                want, {}, ["main-", "pmp-", "ad1bbr-"],
                {"codesystem:2.16.840.1.113883.5.25@dynamic": "ad1bbr-"},
            ),
            ["ad1bbr-", "main-", "pmp-"],
        )

    def test_cached_owner_never_overrides_oid_owner(self) -> None:
        want = {
            "kind": "codesystem",
            "id": "1.2.3.4",
            "effective_date": "2020-01-01",
            "project": "",
        }
        self.assertEqual(
            _candidate_projects(
                want, {"1.2.3": "main-"}, ["main-", "ad1bbr-"],
                {"codesystem:1.2.3.4@2020-01-01": "ad1bbr-"},
            ),
            ["main-"],
        )

    def test_cached_owner_is_effective_date_specific(self) -> None:
        owners = {
            "codesystem:2.16.840.1.113883.5.25@2019-12-30": "ad1bbr-",
        }
        historical = {
            "kind": "codesystem",
            "id": "2.16.840.1.113883.5.25",
            "effective_date": "2019-12-30",
            "project": "",
        }
        current = {**historical, "effective_date": "2024-01-01"}
        repositories = ["main-", "pmp-", "ad1bbr-"]
        self.assertEqual(
            _candidate_projects(historical, {}, repositories, owners),
            ["ad1bbr-", "main-", "pmp-"],
        )
        self.assertEqual(
            _candidate_projects(current, {}, repositories, owners),
            repositories,
        )

    def test_format_one_owner_cache_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact-owners.json"
            path.write_text(
                '{"format":1,"owners":{"codesystem:1.2.3":"wrong-"}}',
                encoding="utf-8",
            )
            self.assertEqual(_load_artifact_owners(path), {})

    def test_source_reference_redirects_before_wrong_project_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, Any] = {"resources": {}}
            owners: dict[str, str] = {}
            calls: list[str] = []
            want = {
                "kind": "codesystem",
                "id": "2.16.840.1.113883.5.25",
                "effective_date": "",
                "project": "main-",
            }

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if "$extract" not in path and "prefix=main-" in url:
                    return (
                        b'<return><codeSystem id="2.16.840.1.113883.5.25" '
                        b'href="https://art-decor.org/exist/apps/api/project/ad1bbr-/codesystem/'
                        b'2.16.840.1.113883.5.25"/></return>'
                    )
                if "$extract" in path and "project=main-" in url:
                    raise AssertionError("wrong-project analysis must be skipped")
                return (
                    b'<return><codeSystem id="2.16.840.1.113883.5.25" '
                    b'effectiveDate="2020-01-01T00:00:00"><concept code="N"/></codeSystem></return>'
                )

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(
                    release_dir, manifest, want,
                    owners={}, repositories=["main-", "pmp-", "ad1bbr-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                    artifact_owners=owners,
                )

            self.assertIsNotNone(path)
            self.assertEqual(
                owners["codesystem:2.16.840.1.113883.5.25@dynamic"], "ad1bbr-"
            )
            self.assertFalse(any(
                "$extract" in api_path(url) and "project=main-" in url
                for url in calls
            ))

    def test_source_link_does_not_redirect_known_oid_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest: dict[str, Any] = {"resources": {}}
            owner_index: dict[str, str] = {}
            calls: list[str] = []
            want = {
                "kind": "codesystem",
                "id": "1.2.3.4",
                "effective_date": "",
                "project": "",
            }

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if "$extract" not in path:
                    return (
                        b'<return><codeSystem id="1.2.3.4" '
                        b'href="https://art-decor.org/exist/apps/api/project/ad1bbr-/codesystem/1.2.3.4" '
                        b'effectiveDate="2020-01-01T00:00:00"/></return>'
                    )
                if "project=main-" in url:
                    return (
                        b'<return><codeSystem id="1.2.3.4" '
                        b'effectiveDate="2020-01-01T00:00:00"><concept code="A"/></codeSystem></return>'
                    )
                raise AssertionError("known OID owner must not redirect to BBR")

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                path = _fetch_want(
                    release_dir, manifest, want,
                    owners={"1.2.3": "main-"},
                    repositories=["main-", "ad1bbr-"],
                    language="de-DE", ipv4=True, retry_missing=False,
                    artifact_owners=owner_index,
                )

            self.assertIsNotNone(path)
            self.assertTrue(any(
                "$extract" in api_path(url) and "project=main-" in url
                for url in calls
            ))
            self.assertFalse(any(
                "$extract" in api_path(url) and "project=ad1bbr-" in url
                for url in calls
            ))

    def test_soft_evidence_closes_formal_origin_but_not_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b'<return><project id="9" prefix="ext-"/></return>'
                if "/transaction/t/" in path:
                    return b'<dataset id="d" transactionId="t"><concept id="current"><inherit ref="9.1" effectiveDate="2020-01-01" prefix="ext-"/></concept></dataset>'
                if path.endswith("/project/main-/$extract") or path.endswith("/project/main-"):
                    return b'<project><transaction id="t"/></project>'
                if "/concept/9.1/" in path:
                    return b'<return><concept id="9.1" effectiveDate="2020-01-01"><inherit ref="9.2" effectiveDate="2019-01-01" prefix="ext-"/><relationship type="ADAPT" ref="9.3" flexibility="2018-01-01" prefix="ext-"/></concept></return>'
                if "/concept/9.2/" in path:
                    return b'<return><concept id="9.2" effectiveDate="2019-01-01"/></return>'
                if "/concept/9.3/" in path:
                    raise AssertionError("weak evidence must not recurse")
                raise AssertionError(url)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE, transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=20,
                )
            self.assertTrue(any("/concept/9.1/" in api_path(url) for url in calls))
            self.assertTrue(any("/concept/9.2/" in api_path(url) for url in calls))
            self.assertFalse(any("/concept/9.3/" in api_path(url) for url in calls))
            self.assertTrue(all(
                "$extract" in api_path(url)
                for url in calls if "/concept/9.2/" in api_path(url)
            ))
            self.assertIn("concept:9.1@2020-01-01", result["closure"]["evidence_resources"])
            self.assertIn("concept:9.2@2019-01-01", result["closure"]["evidence_resources"])

    def test_static_association_endpoint_closes_to_shared_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "spec" / "release-v1"
            tx_dir = release_dir / "transactions" / "tx"
            calls: list[str] = []

            def fake_get(url: str, **_: object) -> bytes:
                calls.append(url)
                path = api_path(url)
                if path.endswith("/modules/library/api.json"):
                    return API_CONTRACT
                if path.endswith("/project"):
                    return b'<return><project id="9" prefix="ext-"/></return>'
                if "/transaction/t/" in path:
                    return b'<dataset id="d" transactionId="t" templateId="doc" templateEffectiveDate="2026"><concept id="selected"><inherit ref="common" effectiveDate="2015" prefix="base-"/></concept></dataset>'
                if path.endswith("/project/main-/$extract"):
                    return b'<project><transaction id="t"/></project>'
                if path.endswith("/project/main-"):
                    return b'<project><buildingBlockRepository ident="assoc-"/><buildingBlockRepository ident="base-"/></project>'
                if "/template/doc/" in path:
                    return b'<return><template id="doc" effectiveDate="2026" name="Doc"><element name="hl7:ClinicalDocument" id="root"/><staticAssociations><origconcept ref="association" effectiveDate="2016" ident="assoc-" datasetId="association-dataset" datasetEffectiveDate="2016" elementId="legacy-id" templateId="legacy" templateEffectiveDate="2014"/><origconcept ref="association-sibling" effectiveDate="2016" ident="assoc-" datasetId="association-dataset" datasetEffectiveDate="2016" elementId="legacy-sibling" templateId="legacy" templateEffectiveDate="2014"/></staticAssociations></template></return>'
                if "/concept/association/" in path:
                    return b'<return><concept id="association" effectiveDate="2016"><inherit ref="common" effectiveDate="2015" prefix="base-"/></concept><concept id="association-sibling" effectiveDate="2016"><inherit ref="sibling-common" effectiveDate="2015" prefix="base-"/></concept></return>'
                if "/concept/common/" in path:
                    return b'<return><concept id="common" effectiveDate="2015"/></return>'
                if "/concept/sibling-common/" in path:
                    return b'<return><concept id="sibling-common" effectiveDate="2015"/></return>'
                raise AssertionError(url)

            with patch("decor2hl7.retrieval.fetch.get", side_effect=fake_get):
                result = fetch_spec(
                    release_dir, tx_dir, prefix="main-",
                    release=RELEASE,
                    transaction={**TRANSACTION, "id": "t", "key": "tx"},
                    max_requests=30,
                )

            self.assertTrue(any(
                "/concept/association/" in api_path(url) for url in calls
            ))
            self.assertTrue(all(
                "$extract" in api_path(url)
                for url in calls
                if "/concept/association/" in api_path(url)
            ))
            self.assertIn(
                "concept:association@2016|context=association-dataset@2016",
                result["closure"]["evidence_resources"],
            )
            self.assertIn(
                "association-endpoint",
                result["closure"]["resource_roles"][
                    "concept:association@2016|context=association-dataset@2016"
                ],
            )
            self.assertIn(
                "concept:common@2015",
                result["closure"]["evidence_resources"],
            )
            self.assertIn(
                "concept:sibling-common@2015",
                result["closure"]["evidence_resources"],
            )
            self.assertFalse(any(
                "/concept/association-sibling/" in api_path(url)
                for url in calls
            ))


if __name__ == "__main__":
    unittest.main()
