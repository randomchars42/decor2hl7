"""Stable, checked data shapes shared by the pipeline.

Names, owner identities and terminology members are data. These contracts
express the compiled format rather than a particular clinical specification.
Unknown non-executable metadata is retained as JSON, without changing bytes on
serialization. Semantic admission remains with the owning validator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, TypeAlias, TypeGuard, TypedDict

from .i18n import message

JsonValue: TypeAlias = 'None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]'
JsonObject: TypeAlias = dict[str, JsonValue]


class FieldDefinition(TypedDict, total=False):
    name: str
    description: str
    concept: str
    type: str
    parent: str | None
    min: int
    max: int | None
    required: bool
    repeat: str | None
    repeat_chain: list[str]
    precision: str
    unit: str
    units: list[str]
    min_value: int | float
    max_value: int | float
    min_length: int
    max_length: int
    accepted_values: dict[str, JsonObject]
    logical_domain: JsonObject
    formal_terminology: JsonObject
    coded_domain: JsonObject
    value_sets: list[str]
    codes: list[JsonObject]
    formal_origin: JsonObject
    relationships: list[JsonObject]


class GroupDefinition(TypedDict, total=False):
    name: str
    description: str
    concept: str
    parent: str | None
    min: int
    max: int | None
    required: bool
    repeat: str | None
    repeat_chain: list[str]
    repeating: bool


class DatasetModel(TypedDict, total=False):
    version: int
    meta: JsonObject
    fields: dict[str, FieldDefinition]
    groups: dict[str, GroupDefinition]
    order: list[str]
    value_sets: JsonObject


class CdaNode(TypedDict, total=False):
    kind: str
    name: str
    datatype: str | None
    min: int
    max: int | None
    mandatory: bool
    prohibited: bool
    children: list[CdaNode]
    targets: list[str]
    attributes: list[JsonObject]
    fixed: JsonObject
    codes: list[JsonObject]
    properties: list[JsonObject] | None
    validation_rules: list[JsonObject]
    lets: dict[str, str]
    content_role: str | None


class CdaTarget(TypedDict, total=False):
    path: str
    datatype: str | None
    min: int
    max: int | None
    locations: list[str]
    logical_types: list[str]
    renderable: bool
    writable: bool
    prohibited: bool
    repeatable: bool
    repeat_ancestors: list[str]
    value_representation: JsonObject | None
    value_sets: list[str]
    value_set_bindings: list[JsonObject]
    codes: list[JsonObject]
    fixed: JsonObject
    template_id: str
    template_effective_date: str
    source_key: str
    non_null_requires: list[str]


class CdaModel(TypedDict, total=False):
    version: int
    format: str
    document_template: JsonObject
    document: list[CdaNode]
    targets: dict[str, CdaTarget]
    datapoints: dict[str, CdaTarget]
    validation_rules: list[JsonObject]
    unresolved_templates: list[JsonObject]
    stats: dict[str, int]


class InputLocator(TypedDict, total=False):
    source: str
    column: str
    parse_as: str
    transform: JsonObject


class MappingRule(TypedDict, total=False):
    target: str
    cda_target: str
    transform: JsonObject | None
    mode: str
    structure: str
    reason: str
    active_if: str
    branch: str


MappingSelection: TypeAlias = str | MappingRule | list[str | MappingRule] | None


class TargetMapping(TypedDict, total=False):
    version: int
    model: JsonObject
    target: JsonObject
    fields: dict[str, MappingSelection]
    field_reviews: dict[str, JsonObject]
    structures: dict[str, JsonObject] | list[JsonObject]
    narratives: dict[str, JsonObject]
    defaults: JsonObject
    target_defaults: dict[str, JsonValue]
    site_requirements: dict[str, JsonObject]


class InputMapping(TypedDict, total=False):
    version: int
    model: JsonObject
    join: dict[str, str]
    fields: dict[str, str | InputLocator | None]


class CodeMapping(TypedDict, total=False):
    version: int
    fields: dict[str, dict[str, JsonValue]]


class OperationConfig(TypedDict, total=False):
    failure_threshold: int


class SiteConfig(TypedDict, total=False):
    version: int
    timezone: str
    identifiers: JsonObject
    organization: JsonObject
    input: JsonObject
    source: JsonObject | None
    transport: JsonObject
    cda: JsonObject
    null_flavor: JsonObject
    operation: OperationConfig | None


class Occurrence(TypedDict):
    key: str
    source: str
    row: int
    values: JsonObject
    instances: dict[str, list[Occurrence]]


class NormalizedRecord(TypedDict):
    key: str
    values: JsonObject
    instances: dict[str, list[Occurrence]]
    problems: list[dict[str, str]]


@dataclass(frozen=True)
class RuntimeBundle:
    model: DatasetModel
    cda: CdaModel
    csv_mapping: InputMapping
    codes_mapping: CodeMapping
    cda_mapping: TargetMapping
    site: SiteConfig


Check: TypeAlias = Callable[[object], bool]


def _object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def is_json(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(is_json(item) for item in value)
    return _object(value) and all(is_json(item) for item in value.values())


def _json_object(value: object) -> TypeGuard[JsonObject]:
    return _object(value) and all(is_json(item) for item in value.values())


def _integer(value: object) -> bool:
    return type(value) is int


def _number(value: object) -> bool:
    return type(value) in (int, float)


def _nullable(check: Check) -> Check:
    return lambda value: value is None or check(value)


def _array(check: Check) -> Check:
    return lambda value: isinstance(value, list) and all(check(item) for item in value)


def _dictionary(check: Check) -> Check:
    return lambda value: _object(value) and all(check(item) for item in value.values())


def _string(value: object) -> bool:
    return isinstance(value, str)


def _boolean(value: object) -> bool:
    return isinstance(value, bool)


def _shape(value: object, checks: Mapping[str, Check], required: tuple[str, ...] = ()) -> bool:
    return _object(value) and all(key in value for key in required) and all(
        check(value[key]) for key, check in checks.items() if key in value
    )


_COMMON: dict[str, Check] = {
    'name': _string, 'description': _string, 'concept': _string,
    'parent': _nullable(_string), 'min': _integer, 'max': _nullable(_integer),
    'required': _boolean, 'repeat': _nullable(_string), 'repeat_chain': _array(_string),
}


def _field(value: object) -> TypeGuard[FieldDefinition]:
    return _shape(value, {
        **_COMMON, 'type': _string, 'precision': _string, 'unit': _string,
        'units': _array(_string), 'min_value': _number, 'max_value': _number,
        'min_length': _integer, 'max_length': _integer,
        'accepted_values': _dictionary(_json_object), 'logical_domain': _json_object,
        'formal_terminology': _json_object, 'coded_domain': _json_object,
        'formal_origin': _json_object, 'relationships': _array(_json_object),
        'value_sets': _array(_string), 'codes': _array(_json_object),
    })


def _group(value: object) -> TypeGuard[GroupDefinition]:
    return _shape(value, {**_COMMON, 'repeating': _boolean})


def _dataset(value: object) -> TypeGuard[DatasetModel]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'meta': _json_object, 'fields': _dictionary(_field),
        'groups': _dictionary(_group), 'order': _array(_string), 'value_sets': _json_object,
    })


def _node(value: object) -> TypeGuard[CdaNode]:
    return _shape(value, {
        'kind': _string, 'name': _string, 'datatype': _nullable(_string),
        'min': _integer, 'max': _nullable(_integer), 'mandatory': _boolean,
        'prohibited': _boolean, 'children': _array(_node), 'targets': _array(_string),
        'attributes': _array(_json_object), 'fixed': _json_object,
        'codes': _array(_json_object), 'properties': _nullable(_array(_json_object)),
        'validation_rules': _array(_json_object), 'lets': _dictionary(_string),
        'content_role': _nullable(_string),
    })


def _target(value: object) -> TypeGuard[CdaTarget]:
    return _shape(value, {
        'path': _string, 'datatype': _nullable(_string), 'min': _integer,
        'max': _nullable(_integer), 'locations': _array(_string),
        'logical_types': _array(_string), 'renderable': _boolean,
        'writable': _boolean, 'prohibited': _boolean, 'repeatable': _boolean,
        'repeat_ancestors': _array(_string), 'value_representation': _nullable(_json_object),
        'value_sets': _array(_string), 'value_set_bindings': _array(_json_object),
        'codes': _array(_json_object), 'fixed': _json_object,
        'template_id': _string, 'template_effective_date': _string, 'source_key': _string,
        'non_null_requires': _array(_string),
    })


def _cda(value: object) -> TypeGuard[CdaModel]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'format': _string, 'document_template': _json_object,
        'document': _array(_node), 'targets': _dictionary(_target),
        'datapoints': _dictionary(_target), 'validation_rules': _array(_json_object),
        'unresolved_templates': _array(_json_object), 'stats': _dictionary(_integer),
    })


def _rule(value: object) -> TypeGuard[MappingRule]:
    return _object(value) and set(value) <= set(MappingRule.__annotations__) and _shape(value, {
        key: _nullable(_json_object) if key == 'transform' else _string
        for key in MappingRule.__annotations__
    }, ('target',)) and bool(value['target'])


def _selection(value: object) -> bool:
    return value is None or (isinstance(value, str) and bool(value.strip())) or _rule(value) or (
        isinstance(value, list) and bool(value) and all(
            (isinstance(item, str) and bool(item.strip())) or _rule(item) for item in value
        )
    )


def _mapping(value: object) -> TypeGuard[TargetMapping]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'model': _json_object, 'target': _json_object,
        'fields': _dictionary(_selection), 'field_reviews': _dictionary(_json_object),
        'structures': lambda item: _dictionary(_json_object)(item) or _array(_json_object)(item),
        'narratives': _dictionary(_json_object), 'defaults': _json_object,
        'target_defaults': _json_object, 'site_requirements': _dictionary(_json_object),
    })


def _locator(value: object) -> TypeGuard[InputLocator]:
    return _object(value) and set(value) <= set(InputLocator.__annotations__) and _shape(value, {
        'source': _string, 'column': _string, 'parse_as': _string, 'transform': _json_object,
    }, ('source', 'column')) and bool(value['source']) and bool(value['column'])


def _input_mapping(value: object) -> TypeGuard[InputMapping]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'model': _json_object, 'join': _dictionary(_string),
        'fields': _dictionary(lambda item: item is None or isinstance(item, str) or _locator(item)),
    })


def _codes(value: object) -> TypeGuard[CodeMapping]:
    return _json_object(value) and _shape(value, {'version': _integer, 'fields': _dictionary(_json_object)})


def _site(value: object) -> TypeGuard[SiteConfig]:
    return _json_object(value) and _shape(value, {
        **{key: _json_object for key in ('identifiers', 'organization', 'input', 'transport', 'cda', 'null_flavor')},
        'version': _integer, 'timezone': _string,
        'source': _nullable(_json_object),
        'operation': _nullable(lambda item: _shape(item, {'failure_threshold': _integer})),
    })


def _occurrence(value: object) -> TypeGuard[Occurrence]:
    return _shape(value, {
        'key': _string, 'source': _string, 'row': _integer, 'values': _json_object,
        'instances': _dictionary(_array(_occurrence)),
    }, ('key', 'source', 'row', 'values', 'instances'))


def _record(value: object) -> TypeGuard[NormalizedRecord]:
    return _json_object(value) and _shape(value, {
        'key': _string, 'values': _json_object, 'instances': _dictionary(_array(_occurrence)),
        'problems': _array(_dictionary(_string)),
    }, ('key', 'values', 'instances', 'problems'))


def dataset_model(value: object, path: object = 'model') -> DatasetModel:
    if _dataset(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='dataset model', path=path))


def cda_model(value: object, path: object = 'cda') -> CdaModel:
    if _cda(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='CDA model', path=path))


def target_mapping(value: object, path: object = 'cda-mapping') -> TargetMapping:
    if _mapping(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='target mapping', path=path))


def input_mapping(value: object, path: object = 'csv-mapping') -> InputMapping:
    if _input_mapping(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='input mapping', path=path))


def code_mapping(value: object, path: object = 'codes-mapping') -> CodeMapping:
    if _codes(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='code mapping', path=path))


def site_config(value: object, path: object = 'site') -> SiteConfig:
    if _site(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='site config', path=path))


def normalized_record(value: object) -> NormalizedRecord:
    if _record(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='normalized record', path='record'))


def mapping_rule(value: object) -> MappingRule:
    if _rule(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='mapping rule', path='rule'))


def locator(value: object) -> InputLocator:
    if _locator(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='input locator', path='locator'))
