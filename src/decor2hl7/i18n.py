"""Load and validate deterministic locale catalogs for UI and report prose."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache, wraps
import inspect
from importlib.resources import files
import json
import re
from string import Formatter
from types import MappingProxyType
from typing import Any, Callable, Mapping, ParamSpec, TypeVar


OUTPUT_LANGUAGE: ContextVar[str] = ContextVar("decor2hl7_output_language", default="en")

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


def message(message_id: str, **values: Any) -> str:
    """Construct presentation text by ID; owner strings never pass through here."""
    return Translator(OUTPUT_LANGUAGE.get()).text(message_id, **values)


P = ParamSpec("P")
T = TypeVar("T")


def localized(function: Callable[P, T]) -> Callable[P, T]:
    """Scope a report's explicit output_language without changing semantic data."""
    signature = inspect.signature(function)
    @wraps(function)
    def render(*args: P.args, **kwargs: P.kwargs) -> T:
        bound = signature.bind(*args, **kwargs)
        language = normalize_output_language(bound.arguments.get("output_language", OUTPUT_LANGUAGE.get()))
        token = OUTPUT_LANGUAGE.set(language)
        try:
            return function(*args, **kwargs)
        finally:
            OUTPUT_LANGUAGE.reset(token)
    return render
