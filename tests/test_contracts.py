from __future__ import annotations

import unittest
from decor2hl7.contracts import (
    cda_model, code_mapping, dataset_model, input_mapping,
    normalized_record, site_config, target_mapping,
)
from decor2hl7.hashing import json_digest


class ContractTests(unittest.TestCase):
    def test_owner_names_and_metadata_are_data_and_roundtrip_without_changes(self) -> None:
        raw = {'version': 1, 'fields': {'new.release.field': {'type': 'code', 'accepted_values': {'New option': {'code': 'NEW', 'code_system': '9.8.7'}}, 'owner_metadata': {'future': [1, 'text', None]}}}, 'groups': {}, 'meta': {'transaction_id': '9.9.1'}}
        before = json_digest(raw)
        model = dataset_model(raw)
        self.assertIs(model, raw)
        self.assertEqual(model['fields']['new.release.field']['accepted_values']['New option']['code'], 'NEW')
        self.assertEqual(json_digest(model), before)

    def test_opaque_metadata_still_has_to_be_json(self) -> None:
        with self.assertRaises(ValueError):
            dataset_model({'fields': {'field': {'type': 'text', 'owner_metadata': object()}}})

    def test_field_shapes_reject_invalid_nested_contracts(self) -> None:
        invalid_fields: list[object] = [{'type': 1}, {'min': True}, {'repeat_chain': 'group'}, {'accepted_values': {'a': []}}]
        for field in invalid_fields:
            with self.subTest(field=field), self.assertRaises(ValueError):
                dataset_model({'fields': {'field': field}})

    def test_cda_shape_checks_nested_nodes_and_targets(self) -> None:
        with self.assertRaises(ValueError):
            cda_model({'document': [{'kind': 'element', 'children': [{'min': 'one'}]}]})
        with self.assertRaises(ValueError):
            cda_model({'targets': {'Target': {'writable': 'yes'}}})
        self.assertEqual(cda_model({'targets': {'new-template.value': {'writable': True}}})['targets']['new-template.value']['writable'], True)

    def test_mapping_and_site_boundaries_reject_malformed_executable_shapes(self) -> None:
        for decode, raw in ((target_mapping, {'fields': {'x': {'targte': 'value'}}}), (input_mapping, {'fields': {'x': {'source': 3, 'column': 'x'}}}), (code_mapping, {'fields': {'x': []}}), (site_config, {'operation': {'failure_threshold': True}})):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode(raw)

    def test_optional_configuration_nulls_keep_the_current_meaning(self) -> None:
        raw = {'fields': {'a': {'target': 'Value', 'transform': None}}}
        self.assertEqual(target_mapping(raw), raw)
        self.assertIsNone(site_config({'source': None, 'operation': None})['source'])

    def test_normalized_occurrences_preserve_identity_and_reject_bad_shapes(self) -> None:
        raw = {'key': 'case', 'values': {}, 'problems': [], 'instances': {'group': [{'key': 'g1', 'source': 'children', 'row': 2, 'values': {'group.code': {'code': 'A', 'codeSystem': '1.2.3'}}, 'instances': {}}]}}
        record = normalized_record(raw)
        self.assertIs(record, raw)
        self.assertEqual(record['instances']['group'][0]['key'], 'g1')
        with self.assertRaises(ValueError):
            normalized_record({'key': 'case', 'values': {}, 'problems': [], 'instances': {'group': [None]}})
