"""Pinned ART-DECOR and CDA conformance package support.

The transformation runtime deliberately remains independent of these setup-time
tools.  ``fetch`` caches the exact archives and jars, ``build`` can compile the
selected transaction's Schematron, and explicit document validation executes
the resulting XSD/Schematron gates.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, Collection, Iterable, Mapping, Sequence

from .cda.core import CORE_REVISION
from .workspace import write_json


SVRL = "{http://purl.oclc.org/dsdl/svrl}"
SCHEMATRON = "{http://purl.oclc.org/dsdl/schematron}"


@dataclass(frozen=True)
class PackageArchive:
    key: str
    filename: str
    url: str
    sha256: str
    version: str
    license: str
    project: str


DECOR_CORE = PackageArchive(
    key="validation-package:DECOR-core@2.2.28",
    filename="DECOR-core-2.2.28.xar",
    url=(
        "https://repository.art-decor.org/exist/apps/stable3/public/"
        "DECOR-core-2.2.28.xar"
    ),
    sha256="14bda739197800f754dff57a6242aa780c01004e58af0d33fc85de72888f9110",
    version="2.2.28",
    license="GNU-LGPL",
    project="ART-DECOR/DECOR-core",
)

CDA_CORE = PackageArchive(
    key=f"validation-package:CDA-core-2.0@{CORE_REVISION}",
    filename=f"CDA-core-2.0-{CORE_REVISION}.tar.gz",
    url=f"https://github.com/HL7/CDA-core-2.0/archive/{CORE_REVISION}.tar.gz",
    sha256="cad63f59b3247b73b3ddc8caa4105080fb3a23c164a73a5dc000946d5be34ad4",
    version=CORE_REVISION,
    license="HL7 CDA R2 schema license",
    project="HL7/CDA-core-2.0",
)

SAXON_HE = PackageArchive(
    key="validation-tool:Saxon-HE@12.5",
    filename="Saxon-HE-12.5.jar",
    url=(
        "https://repo1.maven.org/maven2/net/sf/saxon/Saxon-HE/12.5/"
        "Saxon-HE-12.5.jar"
    ),
    sha256="98c3a91e6e5aaf9b3e2b37601e04b214a6e67098493cdd8232fcb705fddcb674",
    version="12.5",
    license="MPL-2.0",
    project="Saxonica/Saxon-HE",
)

XMLRESOLVER = PackageArchive(
    key="validation-tool:xmlresolver@5.2.2",
    filename="xmlresolver-5.2.2.jar",
    url=(
        "https://repo1.maven.org/maven2/org/xmlresolver/xmlresolver/5.2.2/"
        "xmlresolver-5.2.2.jar"
    ),
    sha256="efc92bd7ed32b3e57095e0b3e872051ccfbbdcc980831ef33e89e38161a85222",
    version="5.2.2",
    license="Apache-2.0",
    project="xmlresolver/xmlresolver",
)

VALIDATION_ARCHIVES = (DECOR_CORE, CDA_CORE, SAXON_HE, XMLRESOLVER)

_DECOR_ROOT_SUFFIXES = {".xsd", ".xsl", ".sch", ".xml"}
_DECOR_ROOT_FILES = {"expath-pkg.xml", "repo.xml"}
_DECOR_DIRECTORIES = {"coreschematrons", "iso-schematron"}
_CDA_DIRECTORIES = {"schema/normative", "schema/extensions/SDTC"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_archive_path(release_dir: Path, package: PackageArchive) -> Path:
    category = "tools" if package.key.startswith("validation-tool:") else "packages"
    return release_dir / "validation" / category / package.filename


def decor_core_dir(release_dir: Path) -> Path:
    return release_dir / "validation" / "decor-core" / DECOR_CORE.version


def cda_core_dir(release_dir: Path) -> Path:
    return release_dir / "validation" / "cda-core" / CDA_CORE.version


def cda_schema_path(release_dir: Path, *, sdtc: bool = True) -> Path:
    relative = (
        "schema/extensions/SDTC/infrastructure/cda/CDA_SDTC.xsd"
        if sdtc else "schema/normative/infrastructure/cda/CDA.xsd"
    )
    return cda_core_dir(release_dir) / relative


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        "\\" in name
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe validation-package member: {name}")
    return path


def _decor_member_allowed(path: PurePosixPath) -> bool:
    if len(path.parts) == 1:
        return path.name in _DECOR_ROOT_FILES or path.suffix in _DECOR_ROOT_SUFFIXES
    return path.parts[0] in _DECOR_DIRECTORIES and path.suffix in _DECOR_ROOT_SUFFIXES


def _extract_decor(archive: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            path = _safe_member(item.filename)
            if item.is_dir() or not _decor_member_allowed(path):
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    required = {
        destination / "DECOR.xsd",
        destination / "DECOR-datatypes.xsd",
        destination / "DECOR.sch",
        destination / "DECOR2schematron.xsl",
        destination / "iso-schematron" / "iso_svrl_for_xslt2.xsl",
        destination / "coreschematrons" / "DTr1_EIVL_TS.sch",
    }
    missing = sorted(str(path.relative_to(destination)) for path in required if not path.is_file())
    if missing:
        raise ValueError("DECOR-core archive is missing required files: " + ", ".join(missing))
    return extracted


def _extract_cda(archive: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    with tarfile.open(archive, "r:gz") as package:
        for item in package:
            path = _safe_member(item.name)
            if len(path.parts) < 3:
                continue
            relative = PurePosixPath(*path.parts[1:])
            if relative.suffix != ".xsd" or not any(
                str(relative).startswith(directory + "/") for directory in _CDA_DIRECTORIES
            ):
                continue
            if not item.isfile() or item.issym() or item.islnk():
                raise ValueError(f"unsafe CDA archive member type: {item.name}")
            source = package.extractfile(item)
            if source is None:
                raise ValueError(f"cannot read CDA archive member: {item.name}")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    required = {
        destination / "schema/normative/infrastructure/cda/CDA.xsd",
        destination / "schema/normative/infrastructure/cda/POCD_MT000040.xsd",
        destination / "schema/normative/processable/coreschemas/NarrativeBlock.xsd",
        destination / "schema/normative/processable/coreschemas/voc.xsd",
        destination / "schema/extensions/SDTC/infrastructure/cda/CDA_SDTC.xsd",
        destination / "schema/extensions/SDTC/infrastructure/cda/SDTC.xsd",
    }
    missing = sorted(str(path.relative_to(destination)) for path in required if not path.is_file())
    if missing:
        raise ValueError("CDA archive is missing required files: " + ", ".join(missing))
    return extracted


def extract_validation_packages(release_dir: Path) -> dict[str, Any]:
    """Verify and safely extract the locked validation archives."""
    for package in VALIDATION_ARCHIVES:
        path = package_archive_path(release_dir, package)
        if not path.is_file():
            raise ValueError(f"validation package is not cached: {path}")
        actual = sha256_file(path)
        if actual != package.sha256:
            raise ValueError(
                f"validation package checksum mismatch for {package.filename}: "
                f"expected {package.sha256}, found {actual}"
            )

    decor_files = _extract_decor(
        package_archive_path(release_dir, DECOR_CORE), decor_core_dir(release_dir)
    )
    cda_files = _extract_cda(
        package_archive_path(release_dir, CDA_CORE), cda_core_dir(release_dir)
    )
    lock = {
        "version": 1,
        "packages": [
            {
                "key": package.key,
                "version": package.version,
                "url": package.url,
                "sha256": package.sha256,
                "license": package.license,
                "project": package.project,
            }
            for package in VALIDATION_ARCHIVES
        ],
        "extracted": {
            "decor_core": {
                str(path.relative_to(decor_core_dir(release_dir))): sha256_file(path)
                for path in sorted(decor_files)
            },
            "cda_core": {
                str(path.relative_to(cda_core_dir(release_dir))): sha256_file(path)
                for path in sorted(cda_files)
            },
        },
    }
    write_json(release_dir / "validation" / "package-lock.json", lock)
    return lock


def validation_package_problems(release_dir: Path) -> list[str]:
    problems: list[str] = []
    for package in VALIDATION_ARCHIVES:
        path = package_archive_path(release_dir, package)
        if not path.is_file():
            problems.append(f"missing {path.relative_to(release_dir)}")
        elif sha256_file(path) != package.sha256:
            problems.append(f"checksum mismatch for {path.relative_to(release_dir)}")
    lock_path = release_dir / "validation" / "package-lock.json"
    if not lock_path.is_file():
        problems.append("missing validation/package-lock.json")
        return problems
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        problems.append(f"invalid validation/package-lock.json: {error}")
        return problems
    if not isinstance(lock, Mapping):
        problems.append("invalid validation/package-lock.json: root must be an object")
        return problems
    package_rows = lock.get("packages", [])
    if not isinstance(package_rows, list):
        package_rows = []
        problems.append("package lock packages must be a list")
    locked_packages = {
        str(item.get("key")): item
        for item in package_rows
        if isinstance(item, Mapping)
    }
    for package in VALIDATION_ARCHIVES:
        item = locked_packages.get(package.key, {})
        if any(
            item.get(field) != expected
            for field, expected in (
                ("version", package.version),
                ("url", package.url),
                ("sha256", package.sha256),
                ("license", package.license),
                ("project", package.project),
            )
        ):
            problems.append(f"package lock does not match pinned {package.key}")
    extracted = lock.get("extracted", {})
    if not isinstance(extracted, Mapping):
        extracted = {}
        problems.append("package lock extracted files must be an object")
    for group, base in (
        ("decor_core", decor_core_dir(release_dir)),
        ("cda_core", cda_core_dir(release_dir)),
    ):
        rows = extracted.get(group, {})
        if not isinstance(rows, Mapping) or not rows:
            problems.append(f"package lock has no {group} extracted files")
            continue
        for relative, expected in rows.items():
            try:
                locked_path = _safe_member(str(relative))
            except ValueError as error:
                problems.append(str(error))
                continue
            path = base.joinpath(*locked_path.parts)
            if not path.is_file():
                problems.append(f"missing extracted {group} file {relative}")
            elif sha256_file(path) != expected:
                problems.append(f"checksum mismatch for extracted {group} file {relative}")
    return problems


def validation_packages_available(release_dir: Path) -> bool:
    return not validation_package_problems(release_dir)


def _saxon_command(release_dir: Path) -> list[str]:
    java = shutil.which("java")
    if java is None:
        raise ValueError("Java is required for the pinned Saxon validation backend")
    classpath = os.pathsep.join(
        str(package_archive_path(release_dir, package))
        for package in (SAXON_HE, XMLRESOLVER)
    )
    return [java, "-cp", classpath, "net.sf.saxon.Transform"]


def _run_xslt(
    release_dir: Path,
    source: Path,
    stylesheet: Path,
    output: Path,
    *,
    parameters: Mapping[str, str] | None = None,
    timeout: int = 300,
) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        *_saxon_command(release_dir),
        f"-s:{source.resolve()}",
        f"-xsl:{stylesheet.resolve()}",
        f"-o:{output.resolve()}",
        *[f"{key}={value}" for key, value in (parameters or {}).items()],
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        detail = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise ValueError(f"Saxon validation transform failed: {detail}")
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())


def compile_schematron(
    release_dir: Path, schematron: Path, output: Path
) -> dict[str, Any]:
    """Compile ISO Schematron to an XSLT 2.0 validator candidate."""
    iso = decor_core_dir(release_dir) / "iso-schematron"
    with tempfile.TemporaryDirectory(prefix="decor2hl7-sch-") as temporary:
        temp = Path(temporary)
        included = temp / "included.sch"
        expanded = temp / "expanded.sch"
        logs = [
            _run_xslt(
                release_dir, schematron,
                iso / "iso_dsdl_include.xsl", included,
            ),
            _run_xslt(
                release_dir, included,
                iso / "iso_abstract_expand.xsl", expanded,
            ),
            _run_xslt(
                release_dir, expanded,
                iso / "iso_svrl_for_xslt2.xsl", output,
            ),
        ]
    return {
        "schematron": str(schematron),
        "validator": str(output),
        "sha256": sha256_file(output),
        "messages": [line for log in logs for line in log.splitlines() if line],
    }


def _svrl_diagnostics(path: Path, *, phase: str, document: Path) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    diagnostics: list[dict[str, Any]] = []
    for kind in ("failed-assert", "successful-report"):
        for node in root.findall(f".//{SVRL}{kind}"):
            role = str(node.get("role") or "error").lower()
            text = " ".join("".join(node.itertext()).split())
            diagnostics.append({
                "phase": phase,
                "severity": role if role in {"error", "warning", "info"} else "error",
                "kind": kind,
                "rule_id": str(node.get("id") or ""),
                "test": str(node.get("test") or ""),
                "location": str(node.get("location") or ""),
                "document": str(document),
                "message": text,
            })
    return diagnostics


def validate_schematron(
    release_dir: Path,
    validator: Path,
    documents: Sequence[Path],
    *,
    phase: str,
    report_dir: Path,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    report_dir.mkdir(parents=True, exist_ok=True)
    for index, document in enumerate(documents):
        svrl = report_dir / f"{phase}-{index + 1}.svrl.xml"
        _run_xslt(release_dir, document, validator, svrl)
        diagnostics.extend(_svrl_diagnostics(svrl, phase=phase, document=document))
    return diagnostics


def validate_xsd(schema: Path, documents: Sequence[Path], *, phase: str) -> list[dict[str, Any]]:
    java = shutil.which("java")
    if java is None:
        raise ValueError("Java is required for XML Schema validation")
    source = resources.files("decor2hl7").joinpath("validation/XsdValidator.java")
    with resources.as_file(source) as source_path:
        command = [java, str(source_path), str(schema), *map(str, documents)]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=300, check=False
        )
    if result.returncode:
        detail = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise ValueError(f"XML Schema validation backend failed: {detail}")
    diagnostics: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        columns = line.split("\t", 4)
        if len(columns) != 5:
            continue
        document, severity, line_number, column_number, encoded = columns
        diagnostics.append({
            "phase": phase,
            "severity": severity,
            "kind": "xsd",
            "rule_id": "",
            "test": "",
            "location": f"{line_number}:{column_number}",
            "document": document,
            "message": base64.b64decode(encoded).decode("utf-8", "replace"),
        })
    return diagnostics


def _copy_children(
    destination: ET.Element,
    paths: Iterable[Path],
    names: set[str],
    namespaces: dict[str, str] | None = None,
) -> None:
    """Copy complete artifacts while excluding API result-envelope metadata.

    ART-DECOR result forms commonly contain an outer ``template`` carrying
    only request identity and an inner, effective-dated ``template`` carrying
    the definition.  Only the latter is valid publication-transform input.
    """
    seen: dict[tuple[str, str, str], ET.Element] = {}
    for path in paths:
        try:
            declared_namespaces = dict(
                item for _, item in ET.iterparse(path, events=("start-ns",))
                if item[0]
            )
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        from .retrieval.expansion import normalized_value_sets
        from .retrieval.xml import local

        is_expansion = (
            local(root.tag) == "valueSetExpansionSet"
            or local(root.tag) == "valueSet"
            and path.name.endswith(".expansion.xml")
        )
        if is_expansion and "valueSet" in names:
            candidates = [(node, True) for node in normalized_value_sets(root)]
        else:
            candidates = [
                (node, False) for node in root.iter()
                if node.tag in names
                and bool(node.get("effectiveDate"))
                and bool(node.get("id") or node.get("name"))
            ]
        for node, extensional in candidates:
            identity = (
                node.tag,
                str(node.get("id") or node.get("ref") or node.get("name") or ""),
                str(node.get("effectiveDate") or ""),
            )
            copied = copy.deepcopy(node)
            attribute_values = " ".join(
                str(value)
                for descendant in copied.iter()
                for value in descendant.attrib.values()
            )
            # ElementTree retains namespace identity but may replace the source
            # prefix with nsN. Prefixes embedded in ART-DECOR XPath/name strings
            # are semantic QName tokens. Build one document-wide namespace
            # registry and rename only the prefix token when two source
            # artifacts reuse a prefix for different namespace URIs.
            for prefix, uri in declared_namespaces.items():
                if prefix in {"xml", "hl7", "cda", "xsi"}:
                    continue
                pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(prefix)}:"
                if not re.search(pattern, attribute_values):
                    continue
                output_prefix = prefix
                if namespaces is not None:
                    suffix = 2
                    while (
                        output_prefix in namespaces
                        and namespaces[output_prefix] != uri
                    ):
                        output_prefix = f"{prefix}{suffix}"
                        suffix += 1
                    namespaces[output_prefix] = uri
                if output_prefix != prefix:
                    for descendant in copied.iter():
                        for attribute, value in list(descendant.attrib.items()):
                            descendant.set(
                                attribute,
                                re.sub(pattern, f"{output_prefix}:", value),
                            )
            existing = seen.get(identity)
            if existing is not None:
                if node.tag in {"valueSet", "codeSystem"}:
                    _merge_terminology_resource(
                        existing, copied,
                        replace_concept_list=extensional and node.tag == "valueSet",
                    )
                continue
            seen[identity] = copied
            destination.append(copied)


def _merge_terminology_resource(
    destination: ET.Element, incoming: ET.Element, *,
    replace_concept_list: bool = False,
) -> None:
    """Merge analysis and frozen expansion forms of one exact revision."""
    for name, value in incoming.attrib.items():
        if name not in destination.attrib:
            destination.set(name, value)

    def signature(node: ET.Element) -> tuple[str, ...]:
        return (
            node.tag,
            str(node.get("id") or ""),
            str(node.get("code") or ""),
            str(node.get("codeSystem") or ""),
            str(node.get("ref") or ""),
            str(node.get("effectiveDate") or node.get("flexibility") or ""),
            str(node.get("op") or ""),
        )

    for child in incoming:
        if child.tag == "conceptList":
            if replace_concept_list:
                for item in list(destination):
                    if item.tag == "conceptList":
                        destination.remove(item)
                destination.append(copy.deepcopy(child))
                continue
            target = next(
                (item for item in destination if item.tag == "conceptList"),
                None,
            )
            if target is None:
                destination.append(copy.deepcopy(child))
                continue
            known = {signature(item) for item in target}
            for item in child:
                marker = signature(item)
                if marker not in known:
                    target.append(copy.deepcopy(item))
                    known.add(marker)
            continue
        marker = signature(child)
        if marker not in {signature(item) for item in destination}:
            destination.append(copy.deepcopy(child))


def assemble_decor_closure(
    release_dir: Path,
    inputs: Mapping[str, Any],
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
    output: Path,
) -> Path:
    """Assemble exact fetched forms for publication-transform input.

    This is explicitly an assembled closure, not a native ART-DECOR compiled
    project.  It prevents dynamic references from resolving against unrelated
    live project revisions while retaining the selected transaction context.
    """
    project_path = release_dir / "project.xml"
    if not project_path.is_file():
        raise ValueError("project.xml is required to assemble the DECOR closure")
    project = ET.parse(project_path).getroot()
    root = ET.Element("decor", {
        "versionDate": str(release.get("date") or "development"),
        "versionLabel": str(release.get("key") or ""),
        "language": str(project.get("defaultLanguage") or "en-US"),
    })
    root.append(copy.deepcopy(project))
    namespace_registry: dict[str, str] = {
        "hl7": "urn:hl7-org:v3",
        "cda": "urn:hl7-org:v3",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xs": "http://www.w3.org/2001/XMLSchema",
    }

    datasets = ET.SubElement(root, "datasets")
    _copy_children(
        datasets,
        [inputs["transaction_analysis"], *inputs.get("model_resources", [])],
        {"dataset"},
        namespace_registry,
    )

    scenarios = ET.SubElement(root, "scenarios")
    selected_id = str(transaction.get("id") or "")
    selected_source = ET.parse(inputs["transaction_source"]).getroot()
    selected_scenario = ET.Element("scenario", {
        "id": selected_id.rsplit(".4.", 1)[0] + ".3.assembled",
        "statusCode": "draft",
        "effectiveDate": str(transaction.get("effective_date") or "development"),
    })
    ET.SubElement(
        selected_scenario, "name", {"language": root.get("language", "en-US")}
    ).text = "Assembled selected transaction"
    selected_scenario.append(copy.deepcopy(selected_source))
    scenarios.append(selected_scenario)

    ids = ET.SubElement(root, "ids")
    if project.find("ids") is not None:
        for item in project.find("ids") or []:
            ids.append(copy.deepcopy(item))

    terminology = ET.SubElement(root, "terminology")
    _copy_children(
        terminology,
        inputs.get("terminology_resources", []),
        {"valueSet", "codeSystem", "conceptMap"},
        namespace_registry,
    )

    rules = ET.SubElement(root, "rules")
    _copy_children(
        rules, inputs.get("templates", []), {"template"}, namespace_registry
    )
    ET.SubElement(root, "issues")
    for prefix, uri in namespace_registry.items():
        if prefix not in {"xml", "hl7", "cda", "xsi", "xs"}:
            root.set(f"xmlns:{prefix}", uri)
            # DECOR-core intentionally discovers additional prefixes through
            # namespace nodes retained on the assembled document. Mark each
            # declaration as used so an XSLT copy does not discard it before
            # the Schematron namespace table is generated.
            root.set(f"{prefix}:dummy-decor2hl7-{prefix}", uri)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return output


def _complete_schematron_namespaces(assembled: Path, schematron: Path) -> None:
    """Restore QName-string prefixes omitted by DECOR's generated ns table."""
    available: dict[str, str] = {}
    for event, item in ET.iterparse(assembled, events=("start-ns", "start")):
        if event == "start":
            break
        prefix, uri = item
        if prefix:
            available[prefix] = uri
    tree = ET.parse(schematron)
    root = tree.getroot()
    declared = {
        str(node.get("prefix"))
        for node in root.findall(f"{SCHEMATRON}ns")
        if node.get("prefix")
    }
    attribute_values = " ".join(
        str(value)
        for source in sorted(schematron.parent.rglob("*.sch"))
        for descendant in ET.parse(source).getroot().iter()
        for value in descendant.attrib.values()
    )
    used = set(
        re.findall(
            r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]*):",
            attribute_values,
        )
    )
    missing = sorted(prefix for prefix in used if prefix in available and prefix not in declared)
    if not missing:
        return
    insertion = next(
        (index + 1 for index, node in enumerate(root) if node.tag == f"{SCHEMATRON}title"),
        0,
    )
    for prefix in missing:
        root.insert(insertion, ET.Element(f"{SCHEMATRON}ns", {
            "uri": available[prefix], "prefix": prefix,
        }))
        insertion += 1
    ET.register_namespace("", SCHEMATRON.strip("{}"))
    tree.write(schematron, encoding="utf-8", xml_declaration=True)


_SUPPLY_MATCH_DEFECT = "[[hl7:supply]"


def _repair_generated_stylesheet(stylesheet: Path) -> list[dict[str, Any]]:
    """Repair the one reviewed DECOR-core malformed supply-match emission."""
    text = stylesheet.read_text(encoding="utf-8")
    repairs: list[dict[str, Any]] = []
    attribute = re.compile(r'\bmatch="([^"]*)"')

    def replace(match: re.Match[str]) -> str:
        value = match.group(1)
        if (
            _SUPPLY_MATCH_DEFECT not in value
            or "hl7:entryRelationship[@typeCode='REFR']" not in value
            or value.count("[") != value.count("]") + 1
        ):
            return match.group(0)
        repaired = value.replace(_SUPPLY_MATCH_DEFECT, "[hl7:supply]", 1)
        repairs.append({
            "kind": "decor-core-supply-match-bracket",
            "before": value,
            "after": repaired,
        })
        return f'match="{repaired}"'

    updated = attribute.sub(replace, text)
    if repairs:
        stylesheet.write_text(updated, encoding="utf-8")
    return repairs


_GENERATION_VALUE_SET = re.compile(r"\bvalue set ([0-9][0-9.]*):")
_GENERATION_CONTEXT_TEMPLATE = re.compile(r"@root\s*=\s*'([0-9][0-9.]*)'")


def _generation_message_scope(
    message: str, selected_templates: Collection[str] | None
) -> dict[str, Any]:
    """Classify one upstream generation message against the selected closure.

    The publication transform generates rules for every template the assembled
    specification carries, including referenced branches the selected document
    never instantiates.  A message whose rule context names only templates
    outside the selected closure reports an upstream gap this build does not
    consume.  A message with no recognisable template context stays inside the
    closure so an unparsed message can never silently weaken the claim.
    """
    contexts = sorted(set(_GENERATION_CONTEXT_TEMPLATE.findall(message)))
    if selected_templates is None or not contexts:
        inside = True
    else:
        inside = any(context in selected_templates for context in contexts)
    return {
        "message": message,
        "severity": "error" if message.lstrip().startswith("ERROR") else "info",
        "value_sets": sorted(set(_GENERATION_VALUE_SET.findall(message))),
        "context_templates": contexts,
        "in_selected_closure": inside,
    }


def generate_transaction_schematron(
    release_dir: Path,
    assembled: Path,
    transaction: Mapping[str, Any],
    output_dir: Path,
    selected_templates: Collection[str] | None = None,
) -> dict[str, Any]:
    generated = output_dir / "generated"
    if generated.exists():
        shutil.rmtree(generated)
    for relative in (
        "include",
        "cda-template.sch",
        "cda-template.xsl",
        "generation-messages.txt",
        "validator-compilation-errors.txt",
        "validator-manifest.json",
    ):
        stale = output_dir / relative
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    include = generated / "include"
    include.mkdir(parents=True, exist_ok=True)
    primary = generated / "publication-result.xml"
    log = _run_xslt(
        release_dir,
        assembled,
        decor_core_dir(release_dir) / "DECOR2schematron.xsl",
        primary,
        parameters={
            "outputBaseUriPrefix": generated.resolve().as_uri() + "/",
            "switchCreateDocHTML": "false",
            "switchCreateDocSVG": "false",
            "switchCreateDocDocbook": "false",
            "createDefaultInstancesForRepresentingTemplates": "false",
            "logLevel": "ERROR",
        },
    )
    candidates = sorted(generated.glob("*.sch"))
    if len(candidates) != 1:
        raise ValueError(
            "expected one generated transaction Schematron for "
            f"{transaction.get('id')}, found {len(candidates)}"
        )
    _complete_schematron_namespaces(assembled, candidates[0])
    schema = output_dir / "cda-template.sch"
    shutil.copy2(candidates[0], schema)
    # Relative includes are part of the generated schema contract.
    target_include = output_dir / "include"
    if target_include.exists():
        shutil.rmtree(target_include)
    shutil.copytree(include, target_include)
    validator = output_dir / "cda-template.xsl"
    compiled = compile_schematron(release_dir, schema, validator)
    compiled["stylesheet_repairs"] = _repair_generated_stylesheet(validator)
    compiled["generation_messages"] = [line for line in log.splitlines() if line]
    compiled["generation_message_scopes"] = [
        _generation_message_scope(line, selected_templates)
        for line in compiled["generation_messages"]
    ]
    probe_error = ""
    with tempfile.TemporaryDirectory(prefix="decor2hl7-validator-probe-") as temporary:
        probe = Path(temporary) / "probe.xml"
        probe.write_text(
            '<ClinicalDocument xmlns="urn:hl7-org:v3"/>', encoding="utf-8"
        )
        try:
            _run_xslt(
                release_dir, probe, validator, Path(temporary) / "probe.svrl.xml"
            )
        except ValueError as error:
            probe_error = str(error)
    compiled["executable"] = not probe_error
    # Completeness is a claim about the selected transaction document: every
    # rule that can apply to it was generated.  A rule skipped for a template
    # the selected document never instantiates stays visible in
    # `generation_messages` and in the scope table, but does not deny the claim
    # (`DEC-019`).
    compiled["complete"] = compiled["executable"] and not any(
        scope["severity"] == "error" and scope["in_selected_closure"]
        for scope in compiled["generation_message_scopes"]
    )
    (output_dir / "generation-messages.txt").write_text(
        log + ("\n" if log else ""), encoding="utf-8"
    )
    compilation_error_path = output_dir / "validator-compilation-errors.txt"
    repair_log = "\n".join(
        "REPAIR {kind}\nbefore: {before}\nafter:  {after}".format(**repair)
        for repair in compiled["stylesheet_repairs"]
    )
    diagnostics_log = "\n\n".join(
        item for item in (repair_log, probe_error) if item
    )
    if diagnostics_log:
        compilation_error_path.write_text(
            diagnostics_log + "\n", encoding="utf-8"
        )
    elif compilation_error_path.exists():
        compilation_error_path.unlink()
    outside = [
        scope for scope in compiled["generation_message_scopes"]
        if scope["severity"] == "error" and not scope["in_selected_closure"]
    ]
    write_json(output_dir / "validator-manifest.json", {
        "version": 2,
        "transaction": {
            "id": transaction.get("id"),
            "effective_date": transaction.get("effective_date"),
        },
        "assembled_sha256": sha256_file(assembled),
        "schematron_sha256": sha256_file(schema),
        "validator_sha256": sha256_file(validator),
        "executable": compiled["executable"],
        "complete": compiled["complete"],
        "compilation_error_lines": len(probe_error.splitlines()),
        "compilation_error_file": (
            compilation_error_path.name if probe_error else None
        ),
        "stylesheet_repair_log_file": (
            compilation_error_path.name
            if compiled["stylesheet_repairs"] else None
        ),
        "generation_messages": compiled["generation_messages"],
        "generation_message_scopes": compiled["generation_message_scopes"],
        "generation_messages_outside_selected_closure": len(outside),
        "selected_closure_templates": len(selected_templates or ()),
        "stylesheet_repairs": compiled["stylesheet_repairs"],
    })
    return compiled


def _summary(diagnostics: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        severity: sum(item.get("severity") == severity for item in diagnostics)
        for severity in ("error", "warning", "info")
    }


def write_conformance_report(
    destination: Path,
    *,
    scope: str,
    diagnostics: Sequence[Mapping[str, Any]],
    stages: Sequence[Mapping[str, Any]],
    policy: str,
) -> dict[str, Any]:
    summary = _summary(diagnostics)
    if summary["error"] or any(stage.get("status") == "failed" for stage in stages):
        status = "failed"
    elif any(stage.get("status") == "degraded" for stage in stages):
        status = "degraded"
    elif stages and all(stage.get("status") == "not-run" for stage in stages):
        status = "not-run"
    elif any(stage.get("status") == "not-run" for stage in stages):
        status = "degraded"
    else:
        status = "passed"
    result = {
        "version": 1,
        "scope": scope,
        "status": status,
        "policy": policy,
        "packages": {
            package.key: {
                "version": package.version,
                "sha256": package.sha256,
                "license": package.license,
                "url": package.url,
            }
            for package in VALIDATION_ARCHIVES
        },
        "summary": summary,
        "stages": list(stages),
        "diagnostics": list(diagnostics),
    }
    write_json(destination.with_suffix(".json"), result)
    lines = [
        "# Conformance validation",
        "",
        f"**Scope:** {scope}",
        "",
        f"**Status:** {str(result['status']).upper()} ({policy})",
        "",
        f"Errors: {summary['error']} · Warnings: {summary['warning']} · "
        f"Information: {summary['info']}",
        "",
        "Package validation is independent of dataset-to-CDA mapping coverage. "
        "A legal structural slot is not semantic mapping evidence.",
        "",
        "## Stages",
        "",
        "| Stage | Status | Detail |",
        "|---|---|---|",
    ]
    for stage in stages:
        detail = str(stage.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {stage.get('phase')} | {stage.get('status')} | {detail} |")
    lines.append("")
    if diagnostics:
        lines += [
            "## Diagnostics",
            "",
            "| Severity | Phase | Location | Message |",
            "|---|---|---|---|",
        ]
        displayed = diagnostics[:200]
        for item in displayed:
            message = str(item.get("message") or "").replace("|", "\\|").replace("\n", " ")
            location = str(item.get("location") or "").replace("|", "\\|")
            lines.append(
                f"| {item.get('severity')} | {item.get('phase')} | `{location}` | {message} |"
            )
        if len(diagnostics) > len(displayed):
            lines += [
                "",
                f"Showing the first {len(displayed)} of {len(diagnostics)} diagnostics. "
                f"The complete list is in `{destination.with_suffix('.json').name}`.",
            ]
    else:
        lines += ["No conformance diagnostics were emitted.", ""]
    destination.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return result


def build_conformance_artifacts(
    release_dir: Path,
    model_dir: Path,
    inputs: Mapping[str, Any],
    release: Mapping[str, Any],
    transaction: Mapping[str, Any],
    selected_templates: Collection[str] | None = None,
) -> dict[str, Any]:
    """Run report-only source checks and compile the exact transaction validator."""
    destination = model_dir / "conformance-validation"
    destination.mkdir(parents=True, exist_ok=True)
    diagnostics: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    if not validation_packages_available(release_dir):
        stages.append({
            "phase": "packages", "status": "not-run",
            "detail": "run `decor2hl7 fetch` to cache the validation packages",
        })
        return write_conformance_report(
            destination / "build-conformance", scope="build", diagnostics=[],
            stages=stages, policy="report-only",
        )

    evidence = release_dir / "project-evidence.xml"
    if evidence.is_file():
        xsd = validate_xsd(
            decor_core_dir(release_dir) / "DECOR.xsd", [evidence], phase="decor-source-xsd"
        )
        diagnostics.extend(xsd)
        stages.append({
            "phase": "decor-source-xsd",
            "status": "failed" if any(item["severity"] == "error" for item in xsd) else "passed",
            "detail": f"{len(xsd)} diagnostic(s) from project-evidence.xml",
        })
        source_validator = destination / "decor-source.xsl"
        compile_schematron(
            release_dir, decor_core_dir(release_dir) / "DECOR.sch", source_validator
        )
        source_diagnostics = validate_schematron(
            release_dir, source_validator, [evidence], phase="decor-source-schematron",
            report_dir=destination / "svrl",
        )
        diagnostics.extend(source_diagnostics)
        stages.append({
            "phase": "decor-source-schematron",
            "status": (
                "failed"
                if any(item["severity"] == "error" for item in source_diagnostics)
                else "passed"
            ),
            "detail": f"{len(source_diagnostics)} diagnostic(s); source-project policy",
        })
    else:
        stages.append({
            "phase": "decor-source", "status": "not-run",
            "detail": "project-evidence.xml is unavailable",
        })

    assembled = assemble_decor_closure(
        release_dir, inputs, release, transaction, destination / "decor-assembled.xml"
    )
    generation = generate_transaction_schematron(
        release_dir, assembled, transaction, destination, selected_templates
    )
    outside = sum(
        1 for scope in generation.get("generation_message_scopes", [])
        if scope.get("severity") == "error" and not scope.get("in_selected_closure")
    )
    stages.append({
        "phase": "template-schematron-generation",
        "status": "passed" if generation["complete"] else "degraded",
        "detail": (
            f"validator {Path(str(generation['validator'])).name}; "
            f"{len(generation.get('generation_messages', []))} upstream generation message(s), "
            f"{outside} outside the selected document closure; "
            f"executable probe {'passed' if generation['executable'] else 'failed'}; "
            "see generation-messages.txt and validator-manifest.json"
        ),
    })
    stages.append({
        "phase": "decor-compiled-schematron", "status": "not-run",
        "detail": (
            "no native complete compiled DECOR project is published in the "
            "fetched API forms"
        ),
    })
    return write_conformance_report(
        destination / "build-conformance", scope="build", diagnostics=diagnostics,
        stages=stages, policy="report-only",
    )


def validate_cda_documents(
    release_dir: Path,
    model_dir: Path,
    documents: Sequence[Path],
    report_base: Path,
) -> dict[str, Any]:
    if not validation_packages_available(release_dir):
        raise ValueError("validation packages are unavailable; run `decor2hl7 fetch`")
    validator = model_dir / "conformance-validation" / "cda-template.xsl"
    if not validator.is_file():
        raise ValueError("generated CDA Schematron is unavailable; run `decor2hl7 build`")
    validator_manifest_path = (
        model_dir / "conformance-validation" / "validator-manifest.json"
    )
    if not validator_manifest_path.is_file():
        raise ValueError("generated CDA validator manifest is unavailable; run `decor2hl7 build`")
    validator_manifest = json.loads(validator_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(validator_manifest, Mapping):
        raise ValueError("generated CDA validator manifest must contain an object")
    if validator_manifest.get("validator_sha256") != sha256_file(validator):
        raise ValueError(
            "generated CDA validator checksum does not match its manifest; "
            "rerun `decor2hl7 build`"
        )
    diagnostics = validate_xsd(
        cda_schema_path(release_dir, sdtc=True), documents, phase="cda-sdtc-xsd"
    )
    validator_executable = bool(validator_manifest.get("executable"))
    generation_complete = bool(validator_manifest.get("complete"))
    if not validator_executable:
        provenance_detail = (
            "validator compilation probe failed; see validator-compilation-errors.txt"
        )
    elif not generation_complete:
        provenance_detail = (
            "upstream generation reported missing terminology; see generation-messages.txt"
        )
    else:
        provenance_detail = "exact transaction validator is complete"
    stages: list[dict[str, Any]] = [{
        "phase": "template-validator-provenance",
        "status": "passed" if generation_complete else "failed",
        "detail": provenance_detail,
    }, {
        "phase": "cda-sdtc-xsd",
        "status": (
            "failed"
            if any(item["severity"] == "error" for item in diagnostics)
            else "passed"
        ),
        "detail": f"{len(documents)} document(s)",
    }]
    if validator_executable:
        template_diagnostics = validate_schematron(
            release_dir, validator, documents, phase="cda-template-schematron",
            report_dir=report_base.parent / "svrl",
        )
        diagnostics.extend(template_diagnostics)
        stages.append({
            "phase": "cda-template-schematron",
            "status": (
                "failed"
                if any(item["severity"] == "error" for item in template_diagnostics)
                else "passed"
            ),
            "detail": f"{len(template_diagnostics)} diagnostic(s)",
        })
    else:
        stages.append({
            "phase": "cda-template-schematron",
            "status": "not-run",
            "detail": "validator compilation probe failed; see validator-compilation-errors.txt",
        })
    return write_conformance_report(
        report_base, scope="generated CDA", diagnostics=diagnostics,
        stages=stages, policy="enforced",
    )
