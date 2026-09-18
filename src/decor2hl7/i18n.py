"""Load and validate deterministic locale catalogs for UI and report prose."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
import re
from string import Formatter
from types import MappingProxyType
from typing import Any, Iterable, Mapping


DEFAULT_OUTPUT_LANGUAGE = "en"
SUPPORTED_OUTPUT_LANGUAGES = frozenset({"en", "de"})

_MESSAGE_ID = re.compile(r"^(?:cli|ui|markdown)\.[a-z0-9]+(?:[._][a-z0-9]+)*$")

# These words name project/domain concepts. German prose deliberately keeps
# their English spelling because literal translations such as ``leaf`` ->
# ``Blatt`` are misleading in a dataset/CDA tree.
PROTECTED_TECHNICAL_TERMS = frozenset({
    "ART-DECOR",
    "CDA",
    "ValueSet",
    "dataset",
    "datapoint",
    "leaf",
    "leaves",
    "mapping",
    "model",
    "target",
    "template",
    "workspace",
})


def normalize_output_language(value: Any) -> str:
    """Normalize a supported BCP-47-like output locale to its base language."""
    text = str(value or DEFAULT_OUTPUT_LANGUAGE).strip().replace("_", "-")
    language = text.split("-", 1)[0].casefold()
    if language not in SUPPORTED_OUTPUT_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_OUTPUT_LANGUAGES))
        raise ValueError(
            f"unsupported output language {value!r}; choose one of: {supported}"
        )
    return language


def configured_output_language(
    settings: Mapping[str, Any] | None,
    override: Any = None,
) -> str:
    """Resolve CLI override, workspace setting, then the stable default."""
    if override not in (None, ""):
        return normalize_output_language(override)
    output = settings.get("output", {}) if isinstance(settings, Mapping) else {}
    configured = output.get("language") if isinstance(output, Mapping) else None
    return normalize_output_language(configured or DEFAULT_OUTPUT_LANGUAGE)


@lru_cache(maxsize=None)
def load_catalog(language: str) -> Mapping[str, str]:
    """Load one packaged locale catalog keyed by stable message ID."""
    normalized = normalize_output_language(language)
    resource = files("decor2hl7").joinpath("locales").joinpath(
        f"{normalized}.json"
    )
    try:
        with resource.open("r", encoding="utf-8") as handle:
            payload: Any = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"could not load {normalized!r} output-language catalog"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"output-language catalog {normalized!r} must contain a JSON object"
        )
    catalog: dict[str, str] = {}
    for message_id, message in payload.items():
        if not isinstance(message_id, str) or not isinstance(message, str):
            raise RuntimeError(
                f"output-language catalog {normalized!r} must map strings to strings"
            )
        catalog[message_id] = message
    return MappingProxyType(catalog)


CATALOGS: Mapping[str, Mapping[str, str]] = MappingProxyType({
    language: load_catalog(language)
    for language in sorted(SUPPORTED_OUTPUT_LANGUAGES)
})


def message_ids(namespace: str | None = None) -> frozenset[str]:
    """Return stable English-catalog IDs, optionally within one namespace."""
    identifiers = frozenset(CATALOGS[DEFAULT_OUTPUT_LANGUAGE])
    if namespace is None:
        return identifiers
    prefix = f"{namespace.rstrip('.')}."
    return frozenset(
        message_id for message_id in identifiers if message_id.startswith(prefix)
    )


def _placeholders(value: str) -> set[str]:
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(value)
        if field_name
    }


def catalog_problems() -> list[str]:
    """Return ID, key-set, placeholder, and protected-term catalog problems."""
    errors: list[str] = []
    english = CATALOGS[DEFAULT_OUTPUT_LANGUAGE]
    base_keys = set(english)

    for message_id in sorted(base_keys):
        if _MESSAGE_ID.fullmatch(message_id) is None:
            errors.append(f"en: invalid message ID: {message_id!r}")

    for namespace in ("ui", "markdown"):
        sources: dict[str, str] = {}
        for message_id in sorted(message_ids(namespace)):
            source = english[message_id]
            previous = sources.get(source)
            if previous is not None:
                errors.append(
                    f"en:{namespace}: duplicate source text for message IDs "
                    f"{previous!r} and {message_id!r}"
                )
            else:
                sources[source] = message_id

    for language, catalog in CATALOGS.items():
        missing = base_keys - set(catalog)
        extra = set(catalog) - base_keys
        if missing:
            errors.append(f"{language}: missing message IDs: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{language}: unknown message IDs: {', '.join(sorted(extra))}")
        for message_id in base_keys & set(catalog):
            if _placeholders(english[message_id]) != _placeholders(catalog[message_id]):
                errors.append(
                    f"{language}:{message_id}: placeholders differ from English"
                )
            if language == "de":
                for term in PROTECTED_TECHNICAL_TERMS:
                    if term in english[message_id] and term not in catalog[message_id]:
                        errors.append(
                            f"de:{message_id}: protected technical term {term!r} "
                            "was changed"
                        )
    return errors


@dataclass(frozen=True)
class Translator:
    """Format one complete catalog message in the selected output language."""

    language: str = DEFAULT_OUTPUT_LANGUAGE

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", normalize_output_language(self.language))

    def text(self, message_id: str, **values: Any) -> str:
        try:
            template = CATALOGS[self.language][message_id]
        except KeyError as error:
            raise ValueError(
                f"missing {self.language!r} translation for message ID "
                f"{message_id!r}"
            ) from error
        return template.format(**values)


@lru_cache(maxsize=None)
def _replacement_pairs(
    namespace: str,
    language: str,
) -> tuple[tuple[str, str, str], ...]:
    """Resolve deterministic replacement tuples through stable message IDs."""
    normalized = normalize_output_language(language)
    english = CATALOGS[DEFAULT_OUTPUT_LANGUAGE]
    localized = CATALOGS[normalized]
    identifiers = sorted(
        message_ids(namespace),
        key=lambda message_id: (-len(english[message_id]), message_id),
    )
    return tuple(
        (message_id, english[message_id], localized[message_id])
        for message_id in identifiers
    )


def _replace_catalog_messages(value: str, namespace: str, language: str) -> str:
    for _message_id, source, translated in _replacement_pairs(namespace, language):
        value = value.replace(source, translated)
    return value


def localize_ui(value: str, output_language: str = "en") -> str:
    """Localize one decor2hl7-authored terminal message."""
    language = normalize_output_language(output_language)
    if language == DEFAULT_OUTPUT_LANGUAGE:
        return value
    return _replace_catalog_messages(value, "ui", language)


def _protected_markdown_strings(
    values: Iterable[Any],
    language: str,
) -> set[str]:
    sources = tuple(
        source for _message_id, source, _translated
        in _replacement_pairs("markdown", language)
    )
    protected: set[str] = set()
    visited: set[int] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if any(source in item for source in sources):
                protected.add(item)
            return
        if isinstance(item, Mapping):
            identity = id(item)
            if identity in visited:
                return
            visited.add(identity)
            for key, nested in item.items():
                visit(key)
                visit(nested)
            return
        if isinstance(item, (list, tuple, set, frozenset)):
            identity = id(item)
            if identity in visited:
                return
            visited.add(identity)
            for nested in item:
                visit(nested)

    for value in values:
        visit(value)
    return protected


def localize_markdown(
    value: str,
    output_language: str = "en",
    *,
    protected_values: Iterable[Any] = (),
) -> str:
    """Localize generated Markdown without translating supplied owner content."""
    language = normalize_output_language(output_language)
    if language == DEFAULT_OUTPUT_LANGUAGE:
        return value
    tokens: dict[str, str] = {}
    for index, source in enumerate(
        sorted(
            _protected_markdown_strings(protected_values, language),
            key=len,
            reverse=True,
        )
    ):
        token = f"\x00decor2hl7-protected-{index}\x00"
        while token in value:
            token += "x"
        if source in value:
            value = value.replace(source, token)
            tokens[token] = source
    value = _replace_catalog_messages(value, "markdown", language)
    for token, source in tokens.items():
        value = value.replace(token, source)
    return value
