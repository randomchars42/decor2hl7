"""Exercise tied terminology candidates in complete mapping products."""
import json
from typing import Any

from decor2hl7.compile.mapping import cda_mapping_audit

model = {
    "meta": {},
    "fields": {"measurement": {
        "name": "Measurement",
        "type": "quantity",
        "codes": [
            {"code": "A", "code_system": "cs"},
            {"code": "B", "code_system": "cs"},
        ],
        "value_sets": ["vs-a", "vs-b"],
        "repeat_chain": [],
    }},
    "groups": {},
}
targets: dict[str, Any] = {}
for index, code in enumerate(("A", "B")):
    targets[code] = {
        "datatype": "CD",
        "codes": [{"code": code, "code_system": "cs"}],
        "value_sets": ["vs-" + code.lower()],
        "path": "hl7:ClinicalDocument/hl7:observation/hl7:code",
        "locations": ["0." + str(index)],
        "writable": True,
        "renderable": True,
        "logical_types": ["code"],
        "value_representation": {"kind": "coded", "logical_types": ["code"]},
        "template_id": code,
        "template_name": code,
        "repeat_ancestors": [],
    }
proposal, audit, report, appendix = cda_mapping_audit(
    model,
    {"document": [], "targets": targets, "document_template": {"name": "Document"}, "datapoints": {}},
    [],
)
print(json.dumps([proposal, audit, report, appendix], sort_keys=True))
