"""Current specification API operations used by the retrieval layer.

The crawler works with artifact identities and representations, not endpoint
names.  All differences between raw/detail, publication extraction and
expansion operations are kept here.  Functions remain procedural and return
plain URLs or dictionaries that are easy to test.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, TypedDict
from urllib.parse import quote

from .client import DEFAULT_API_BASE, build_url


class Representation(TypedDict):
    form: str
    url: str


REQUIRED_PATHS = {
    "/project",
    "/project/{project}",
    "/project/{project}/$publication",
    "/transaction",
    "/transaction/{id}/{effectiveDate}",
    "/transaction/{id}/{effectiveDate}/$extract",
    "/dataset/{id}",
    "/dataset/{id}/{effectiveDate}",
    "/dataset/{id}/{effectiveDate}/$extract",
    "/concept/{id}",
    "/concept/{id}/{effectiveDate}",
    "/concept/{id}/{effectiveDate}/$extract",
    "/template/{id}/$extract",
    "/template/{id}/{effectiveDate}/$extract",
    "/valueset/{id}",
    "/valueset/{id}/{effectiveDate}",
    "/valueset/{idOrName}/$extract",
    "/valueset/{idOrName}/{effectiveDate}/$extract",
    "/valueset/{id}/{effectiveDate}/$expand",
    "/codesystem/{id}",
    "/codesystem/{id}/{effectiveDate}",
    "/codesystem/{idOrName}/$extract",
    "/codesystem/{idOrName}/{effectiveDate}/$extract",
}


def _part(value: str) -> str:
    return quote(value, safe="")


def openapi_url(base_url: str = DEFAULT_API_BASE) -> str:
    return build_url("modules/library/api.json", base_url=base_url)


def validate_openapi(payload: bytes) -> dict[str, Any]:
    """Validate the capabilities relied upon by the fixed procedural client."""
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("API description must contain a JSON object")
    paths = value.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("API description has no paths object")
    missing = sorted(REQUIRED_PATHS - set(paths))
    if missing:
        raise ValueError("API is missing required operations: " + ", ".join(missing))
    info = value.get("info") if isinstance(value.get("info"), dict) else {}
    return {
        "title": str(info.get("title") or ""),
        "version": str(info.get("version") or ""),
        "openapi": str(value.get("openapi") or ""),
        "required_paths": sorted(REQUIRED_PATHS),
    }


def projects_url(*, base_url: str = DEFAULT_API_BASE) -> str:
    return build_url("project", base_url=base_url)


def project_url(project: str, *, base_url: str = DEFAULT_API_BASE) -> str:
    return build_url(f"project/{_part(project)}", base_url=base_url)


def publications_url(project: str, *, base_url: str = DEFAULT_API_BASE) -> str:
    return build_url(f"project/{_part(project)}/$publication", base_url=base_url)


def project_extract_url(
    project: str,
    *,
    language: str,
    release: str = "",
    mode: str = "verbatim",
    base_url: str = DEFAULT_API_BASE,
) -> str:
    return build_url(
        f"project/{_part(project)}/$extract",
        base_url=base_url,
        release=release or None,
        language=language,
        format="xml",
        mode=mode,
    )


def transactions_url(
    project: str,
    release: str,
    *,
    language: str,
    base_url: str = DEFAULT_API_BASE,
) -> str:
    return build_url(
        "transaction",
        base_url=base_url,
        project=project,
        release=release,
        language=language,
    )


def transaction_representations(
    ident: str,
    effective_date: str,
    *,
    project: str,
    release: str,
    language: str,
    base_url: str = DEFAULT_API_BASE,
) -> list[Representation]:
    path = f"transaction/{_part(ident)}/{_part(effective_date)}"
    return [
        {
            "form": "source",
            "url": build_url(
                path,
                base_url=base_url,
                prefix=project,
                release=release,
                language=language,
            ),
        },
        {
            "form": "analysis",
            "url": build_url(
                path + "/$extract",
                base_url=base_url,
                project=project,
                release=release,
                language=language,
                format="xml",
            ),
        },
    ]


def _artifact_path(kind: str, ident: str, effective_date: str, *, extract: bool) -> str:
    noun = {
        "dataset": "dataset",
        "concept": "concept",
        "template": "template",
        "valueset": "valueset",
        "codesystem": "codesystem",
    }[kind]
    path = f"{noun}/{_part(ident)}"
    if effective_date:
        path += f"/{_part(effective_date)}"
    if extract:
        path += "/$extract"
    return path


def artifact_representations(
    artifact: Mapping[str, str],
    *,
    project: str,
    main_project: str,
    release: str,
    language: str,
    base_url: str = DEFAULT_API_BASE,
) -> list[Representation]:
    """Return source and compiler-facing requests for one artifact.

    A project release only applies to artifacts resolved in that same project.
    External exact revisions are intentionally requested without the selected
    main-project release.
    """
    kind = artifact["kind"]
    ident = artifact["id"]
    effective = artifact.get("effective_date") or ""
    context_release = release if main_project == project else ""
    common = {
        "language": language,
        "release": context_release or None,
    }

    if kind == "template":
        path = _artifact_path(kind, ident, effective, extract=True)
        source = build_url(path, base_url=base_url, project=project, **common)
        analysis = build_url(
            path, base_url=base_url, project=project, tree="expand", **common
        )
        return [
            {"form": "source", "url": source},
            {"form": "analysis", "url": analysis},
        ]

    source_path = _artifact_path(kind, ident, effective, extract=False)
    source = build_url(
        source_path,
        base_url=base_url,
        prefix=project,
        transactionId=artifact.get("dataset") if kind == "concept" else None,
        transactionEffectiveDate=(
            artifact.get("dataset_effective_date") if kind == "concept" else None
        ),
        associations="true" if kind == "concept" else None,
        **common,
    )
    result: list[Representation] = [{"form": "source", "url": source}]

    # Dataset and concept APIs do not offer a latest-version extract path. The
    # source response resolves the date and the crawler schedules the exact
    # analysis request afterwards.
    if not effective and kind in {"dataset", "concept"}:
        return result

    analysis_path = _artifact_path(kind, ident, effective, extract=True)
    analysis = build_url(
        analysis_path,
        base_url=base_url,
        project=project,
        datasetOrTransactionId=(
            artifact.get("dataset") if kind == "concept" else None
        ),
        datasetOrTransactionEd=(
            artifact.get("dataset_effective_date") if kind == "concept" else None
        ),
        format="xml" if kind != "template" else None,
        **common,
    )
    result.append({"form": "analysis", "url": analysis})
    return result


def valueset_expansion_url(
    ident: str,
    effective_date: str,
    *,
    project: str,
    language: str,
    base_url: str = DEFAULT_API_BASE,
) -> str:
    return build_url(
        f"valueset/{_part(ident)}/{_part(effective_date)}/$expand",
        base_url=base_url,
        project=project,
        language=language,
        expand="true",
    )
