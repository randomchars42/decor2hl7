"""Validate the compact, topic-first documentation contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "decisions.md"
RECOVERY = ROOT / "docs" / "recovery"
MAX_DOCUMENTATION_WORDS = 40_000
MAX_REQUIRED_CONTEXT_WORDS = 10_000
REQUIRED_CONTEXT = (
    ROOT / "Project-decor2hl7.md",
    ROOT / "docs" / "index.md",
    ROOT / "docs" / "topics" / "art-decor-authority.md",
    ROOT / "docs" / "open-boundaries.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "README.md",
)
OBSOLETE_REFERENCES = (
    "docs/analyses",
    "docs/history",
    "docs/known-issues.md",
    "docs/upstream-questions.md",
    "PLAN.md",
)
VOLATILE_PATTERNS = (
    (re.compile(r"\b\d+/\d+\b"), "copied coverage fraction"),
    (re.compile(r"\bunit tests pass\b", re.IGNORECASE), "copied test total"),
    (re.compile(r"\bas of `?main`?\b", re.IGNORECASE), "commit snapshot wording"),
)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
EXPLICIT_ANCHOR_RE = re.compile(
    r"<a\s+(?:name|id)=[\"']([^\"']+)", re.IGNORECASE
)
DECISION_HEADING_RE = re.compile(r"^### (DEC-\d{3})\b", re.MULTILINE)
DECISION_REF_RE = re.compile(r"DEC-\d{3}")


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if ".git" not in path.parts
    )


def github_slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r" +", "-", value)


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    result = {github_slug(heading) for heading in HEADING_RE.findall(text)}
    result.update(EXPLICIT_ANCHOR_RE.findall(text))
    return result


def local_link_errors(files: list[Path]) -> list[str]:
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in files:
        for raw_target in LINK_RE.findall(source.read_text(encoding="utf-8")):
            target = raw_target.strip()
            if "://" in target or target.startswith("mailto:"):
                continue
            file_part, separator, fragment = target.partition("#")
            destination = (
                (source.parent / unquote(file_part)).resolve()
                if file_part
                else source.resolve()
            )
            if not destination.exists():
                errors.append(
                    f"{source.relative_to(ROOT)}: missing link target {target!r}"
                )
                continue
            if not separator or not fragment or destination.suffix != ".md":
                continue
            known = anchor_cache.setdefault(destination, anchors(destination))
            if unquote(fragment) not in known:
                errors.append(
                    f"{source.relative_to(ROOT)}: missing anchor {target!r}"
                )
    return errors


def decision_errors() -> tuple[list[str], int]:
    errors: list[str] = []
    text = DECISIONS.read_text(encoding="utf-8")
    identifiers = DECISION_HEADING_RE.findall(text)
    unique = set(identifiers)
    duplicates = sorted(identifier for identifier in unique if identifiers.count(identifier) > 1)
    if duplicates:
        errors.append(f"duplicate decision headings: {', '.join(duplicates)}")
    if identifiers:
        highest = max(int(identifier.removeprefix("DEC-")) for identifier in identifiers)
        expected = {f"DEC-{number:03d}" for number in range(1, highest + 1)}
        missing = sorted(expected - unique)
        if missing:
            errors.append(f"missing stable decision identifiers: {', '.join(missing)}")
    for recovery in sorted(RECOVERY.glob("*.json")):
        references = set(DECISION_REF_RE.findall(recovery.read_text(encoding="utf-8")))
        missing = sorted(references - unique)
        if missing:
            errors.append(
                f"{recovery.relative_to(ROOT)}: unknown decisions {', '.join(missing)}"
            )
    return errors, len(unique)


def content_errors(files: list[Path]) -> tuple[list[str], int]:
    errors: list[str] = []
    total_words = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        total_words += len(text.split())
        relative = path.relative_to(ROOT)
        for obsolete in OBSOLETE_REFERENCES:
            if obsolete in text:
                errors.append(f"{relative}: obsolete documentation reference {obsolete!r}")
        for pattern, label in VOLATILE_PATTERNS:
            if pattern.search(text):
                errors.append(f"{relative}: {label} belongs in generated evidence")
    if total_words > MAX_DOCUMENTATION_WORDS:
        errors.append(
            f"documentation has {total_words} words; compactness limit is "
            f"{MAX_DOCUMENTATION_WORDS}"
        )
    required_words = sum(
        len(path.read_text(encoding="utf-8").split()) for path in REQUIRED_CONTEXT
    )
    if required_words > MAX_REQUIRED_CONTEXT_WORDS:
        errors.append(
            f"required project context has {required_words} words; limit is "
            f"{MAX_REQUIRED_CONTEXT_WORDS}"
        )
    return errors, total_words


def main() -> int:
    files = markdown_files()
    errors = local_link_errors(files)
    decision_failures, decision_count = decision_errors()
    content_failures, total_words = content_errors(files)
    errors.extend(decision_failures)
    errors.extend(content_failures)
    if errors:
        for error in errors:
            print(f"documentation error: {error}", file=sys.stderr)
        return 1
    print(
        "documentation check passed: "
        f"{len(files)} Markdown files, {total_words} words, "
        f"{decision_count} stable decisions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
