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


class DomainMember(TypedDict, total=False):
    code: str
    code_system: str
    concept_id: str
    synonyms: list[str]
    ordinal: int
    exception: bool
    terminology_association: dict[str, str]
    terminology_associations: list[dict[str, str]]


class LogicalDomain(TypedDict, total=False):
    options: dict[str, DomainMember]
    source: str
    terminology_association_diagnostics: list[JsonObject]


class FormalTerminology(TypedDict, total=False):
    value_sets: list[JsonObject]
    members: dict[str, DomainMember]
    source: str
    status: str
    bound: bool
    complete: bool
    missing_value_sets: list[JsonObject]
    unresolved_includes: list[JsonObject]


class ModelExtensionMetadata(TypedDict, total=False):
    field_count: int
    sha256: str


class ArtifactClosure(TypedDict, total=False):
    crawl_degraded: bool
    crawl_degraded_artifacts: list[str]
    unavailable_artifacts: list[str]
    degraded: bool
    build_degraded: list[str]


class DatasetMetadata(TypedDict, total=False):
    dataset_id: str | None
    transaction_id: str | None
    transaction_effective_date: str | None
    template_id: str | None
    template_effective_date: str | None
    name: str | None
    selected_concepts: int | None
    dataset_rule_pipeline: list[JsonObject]
    model_extensions: ModelExtensionMetadata
    artifact_closure: ArtifactClosure
    configured_source_rules: list[dict[str, str]]


class FieldDefinition(TypedDict, total=False):
    name: str
    description: str | None
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
    logical_domain: LogicalDomain
    formal_terminology: FormalTerminology
    coded_domain: JsonObject
    value_sets: list[str]
    codes: list[JsonObject]
    formal_origin: JsonObject
    relationships: list[JsonObject]
    comment: str | None
    implementation: str | None
    model_extension: JsonObject
    terminology_associations: list[JsonObject]


class GroupDefinition(TypedDict, total=False):
    name: str
    description: str | None
    concept: str
    parent: str | None
    min: int
    max: int | None
    required: bool
    repeat: str | None
    repeat_chain: list[str]
    repeating: bool
    contains_resolution: str


class DatasetModel(TypedDict, total=False):
    version: int
    meta: DatasetMetadata
    fields: dict[str, FieldDefinition]
    groups: dict[str, GroupDefinition]
    order: list[str]
    value_sets: JsonObject


class CdaAttribute(TypedDict, total=False):
    name: str
    datatype: str | None
    value: JsonValue
    optional: bool | None
    namespace_uri: str | None
    conditional_fixed: bool
    targets: list[str]
    provenance: list[JsonObject]


class ConstraintDiagnostic(TypedDict, total=False):
    path: str
    code: str
    message: str
    changes: list[JsonObject]


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
    attributes: list[CdaAttribute]
    fixed: JsonObject
    codes: list[JsonObject]
    properties: list[JsonObject] | None
    validation_rules: list[JsonObject]
    lets: dict[str, str]
    content_role: str | None
    contains: str | None
    contains_flexibility: str | None
    compiled_default: JsonValue
    representation_datatype: str | None
    cda_required_choice: JsonObject
    is_closed: bool


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
    description: str | None
    template_description: str | None
    has_children: bool
    permits_null_flavor: bool
    occurrence_anchor: str
    cda_target: str
    required_binding_constraints: list[str]
    schematron_constraints: list[JsonObject]
    non_null_requires: list[str]


class TemplatePrototype(TypedDict, total=False):
    relation: str
    template: str
    flexibility: str | None
    used_by: JsonObject
    required: bool
    purpose: str


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
    constraint_diagnostics: list[ConstraintDiagnostic]
    unresolved_template_prototypes: list[TemplatePrototype]
    terminology_constraints: dict[str, JsonObject]
    datatype_inventory: dict[str, list[str]]
    reviewed_extensions: list[JsonObject]
    datatype_constraints: JsonObject
    schematron_evidence: JsonObject


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


class AuditCandidate(TypedDict, total=False):
    target: str
    confidence: str
    kind: str
    chain: list[str]
    score: int
    actionable: bool
    mode: str
    via: str | None
    via_name: str | None
    warnings: list[str]
    mapping: MappingSelection
    suggested: bool
    occurrence_mismatch: bool


class AuditGap(TypedDict, total=False):
    gate: str
    kind: str
    reopens_with: list[str]


class AuditDetail(TypedDict, total=False):
    selected: MappingSelection
    primary: AuditCandidate | None
    alternatives: list[AuditCandidate]
    context: AuditCandidate | None
    runtime_blocked: str
    required_companions: list[str]
    unresolved_reason: str
    gap: AuditGap
    possible_targets: JsonObject
    structural_rule: str
    shared_target_winner: bool


class AuditSummary(TypedDict, total=False):
    datapoints: int
    coverage: dict[str, int]
    field_coverage: dict[str, int]
    group_coverage: dict[str, int]
    confidence: dict[str, int]
    primary_evidence: dict[str, int]
    executable_fields: int
    shared_target_blocks: int
    required_companion_blocks: int
    gaps: dict[str, int]
    structural_rules: dict[str, int]
    coverage_headline: JsonObject


class MappingAudit(TypedDict):
    version: int
    model: JsonObject
    target: JsonObject
    fields: dict[str, AuditDetail]
    groups: dict[str, AuditDetail]
    structures: dict[str, JsonObject]
    unresolved_templates: list[JsonObject]
    summary: AuditSummary


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
    'name': _string, 'description': _nullable(_string), 'concept': _string,
    'parent': _nullable(_string), 'min': _integer, 'max': _nullable(_integer),
    'required': _boolean, 'repeat': _nullable(_string), 'repeat_chain': _array(_string),
}


def _domain_member(value: object) -> TypeGuard[DomainMember]:
    return _shape(value, {
        'code': _string, 'code_system': _string, 'concept_id': _string,
        'synonyms': _array(_string), 'ordinal': _integer, 'exception': _boolean,
        'terminology_association': _dictionary(_string),
        'terminology_associations': _array(_dictionary(_string)),
    })


def _logical_domain(value: object) -> TypeGuard[LogicalDomain]:
    return _shape(value, {
        'options': _dictionary(_domain_member), 'source': _string,
        'terminology_association_diagnostics': _array(_json_object),
    })


def _formal_terminology(value: object) -> TypeGuard[FormalTerminology]:
    return _shape(value, {
        'value_sets': _array(_json_object), 'members': _dictionary(_domain_member),
        'source': _string, 'status': _string, 'bound': _boolean, 'complete': _boolean,
        'missing_value_sets': _array(_json_object), 'unresolved_includes': _array(_json_object),
    })


def _dataset_metadata(value: object) -> TypeGuard[DatasetMetadata]:
    return _shape(value, {
        **{key: _nullable(_string) for key in (
            'dataset_id', 'transaction_id', 'transaction_effective_date',
            'template_id', 'template_effective_date', 'name',
        )},
        'selected_concepts': _nullable(_integer), 'dataset_rule_pipeline': _array(_json_object),
        'model_extensions': lambda item: _shape(item, {'field_count': _integer, 'sha256': _string}),
        'configured_source_rules': _array(_dictionary(_string)),
        'artifact_closure': lambda item: _shape(item, {
            'crawl_degraded': _boolean, 'degraded': _boolean,
            **{key: _array(_string) for key in (
                'crawl_degraded_artifacts', 'unavailable_artifacts', 'build_degraded',
            )},
        }),
    })


def _field(value: object) -> TypeGuard[FieldDefinition]:
    return _shape(value, {
        **_COMMON, 'type': _string, 'precision': _string, 'unit': _string,
        'units': _array(_string), 'min_value': _number, 'max_value': _number,
        'min_length': _integer, 'max_length': _integer,
        'accepted_values': _dictionary(_json_object), 'logical_domain': _logical_domain,
        'formal_terminology': _formal_terminology, 'coded_domain': _json_object,
        'formal_origin': _json_object, 'relationships': _array(_json_object),
        'value_sets': _array(_string), 'codes': _array(_json_object),
        'comment': _nullable(_string), 'implementation': _nullable(_string),
        'model_extension': _json_object, 'terminology_associations': _array(_json_object),
    })


def _group(value: object) -> TypeGuard[GroupDefinition]:
    return _shape(value, {**_COMMON, 'repeating': _boolean, 'contains_resolution': _string})


def _dataset(value: object) -> TypeGuard[DatasetModel]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'meta': _dataset_metadata, 'fields': _dictionary(_field),
        'groups': _dictionary(_group), 'order': _array(_string), 'value_sets': _json_object,
    })


def _attribute(value: object) -> TypeGuard[CdaAttribute]:
    return _shape(value, {
        'name': _string, 'datatype': _nullable(_string), 'value': is_json,
        'optional': _nullable(_boolean), 'namespace_uri': _nullable(_string),
        'conditional_fixed': _boolean, 'targets': _array(_string),
        'provenance': _array(_json_object),
    })


def _constraint_diagnostic(value: object) -> TypeGuard[ConstraintDiagnostic]:
    return _shape(value, {
        'code': _string, 'message': _string, 'path': _string, 'changes': _array(_json_object),
    })


def _node(value: object) -> TypeGuard[CdaNode]:
    return _shape(value, {
        'kind': _string, 'name': _string, 'datatype': _nullable(_string),
        'min': _integer, 'max': _nullable(_integer), 'mandatory': _boolean,
        'prohibited': _boolean, 'children': _array(_node), 'targets': _array(_string),
        'attributes': _array(_attribute), 'fixed': _json_object,
        'codes': _array(_json_object), 'properties': _nullable(_array(_json_object)),
        'validation_rules': _array(_json_object), 'lets': _dictionary(_string),
        'content_role': _nullable(_string), 'contains': _nullable(_string),
        'contains_flexibility': _nullable(_string), 'compiled_default': is_json,
        'representation_datatype': _nullable(_string), 'cda_required_choice': _json_object,
        'is_closed': _boolean,
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
        'non_null_requires': _array(_string), 'description': _nullable(_string),
        'template_description': _nullable(_string), 'has_children': _boolean,
        'permits_null_flavor': _boolean, 'occurrence_anchor': _string,
        'cda_target': _string, 'required_binding_constraints': _array(_string),
        'schematron_constraints': _array(_json_object),
    })


def _template_prototype(value: object) -> TypeGuard[TemplatePrototype]:
    return _shape(value, {
        'relation': _string, 'template': _string, 'flexibility': _nullable(_string),
        'used_by': _json_object, 'required': _boolean, 'purpose': _string,
    })


def _cda(value: object) -> TypeGuard[CdaModel]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'format': _string, 'document_template': _json_object,
        'document': _array(_node), 'targets': _dictionary(_target),
        'datapoints': _dictionary(_target), 'validation_rules': _array(_json_object),
        'unresolved_templates': _array(_json_object), 'stats': _dictionary(_integer),
        'constraint_diagnostics': _array(_constraint_diagnostic),
        'unresolved_template_prototypes': _array(_template_prototype),
        'terminology_constraints': _dictionary(_json_object),
        'datatype_inventory': _dictionary(_array(_string)),
        'reviewed_extensions': _array(_json_object),
        'datatype_constraints': _json_object, 'schematron_evidence': _json_object,
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


def json_object(value: object, path: object = 'object') -> JsonObject:
    if _json_object(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='JSON object', path=path))


def _audit_candidate(value: object) -> TypeGuard[AuditCandidate]:
    return _shape(value, {
        **{key: _string for key in ('target', 'confidence', 'kind', 'mode')},
        'chain': _array(_string), 'score': _integer, 'actionable': _boolean,
        'via': _nullable(_string), 'via_name': _nullable(_string),
        'warnings': _array(_string), 'mapping': _selection, 'suggested': _boolean,
        'occurrence_mismatch': _boolean,
    })


def _audit_detail(value: object) -> TypeGuard[AuditDetail]:
    return _shape(value, {
        'selected': _selection, 'primary': _nullable(_audit_candidate),
        'alternatives': _array(_audit_candidate), 'context': _nullable(_audit_candidate),
        'runtime_blocked': _string, 'required_companions': _array(_string),
        'unresolved_reason': _string, 'possible_targets': _json_object,
        'structural_rule': _string, 'shared_target_winner': _boolean,
        'gap': lambda item: _shape(item, {
            'gate': _string, 'kind': _string, 'reopens_with': _array(_string),
        }),
    })


def _audit_summary(value: object) -> TypeGuard[AuditSummary]:
    return _shape(value, {
        **{key: _integer for key in (
            'datapoints', 'executable_fields', 'shared_target_blocks', 'required_companion_blocks',
        )},
        **{key: _dictionary(_integer) for key in (
            'coverage', 'field_coverage', 'group_coverage', 'confidence',
            'primary_evidence', 'gaps', 'structural_rules',
        )},
        'coverage_headline': _json_object,
    })


def _mapping_audit(value: object) -> TypeGuard[MappingAudit]:
    return _json_object(value) and _shape(value, {
        'version': _integer, 'model': _json_object, 'target': _json_object,
        'fields': _dictionary(_audit_detail), 'groups': _dictionary(_audit_detail),
        'structures': _dictionary(_json_object), 'unresolved_templates': _array(_json_object),
        'summary': _audit_summary,
    }, tuple(MappingAudit.__annotations__))


def mapping_audit(value: object) -> MappingAudit:
    if _mapping_audit(value):
        return value
    raise ValueError(message('ui.contract_invalid', kind='mapping audit', path='audit'))
