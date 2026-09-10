# Valid reference cases

This authored set contains six complete, fictional emergency-department
records for release `2026.1.2`, transaction `notaufnahmeregister--60`. It is
mapping evidence, not clinical advice, and contains no patient data.

| Case | Triage branch | Disposition |
|---|---|---|
| `SCENARIO-01` | ESI red | Transfer |
| `SCENARIO-02` | MTS red | Transfer |
| `SCENARIO-03` | MTS orange | Transfer |
| `SCENARIO-04` | MTS yellow | Discharge |
| `SCENARIO-05` | MTS green | Discharge |
| `SCENARIO-06` | MTS blue, without indicator | Discharge |

The cases intentionally keep ESI and MTS data disjoint, select at most the MTS
indicator matching the triage result, and keep transfer and discharge disjoint.
`scenario.json` makes those conditions executable and pins the exact
specification identity. All MTS records have a presentation diagram.

The source dataset requires both an isolation answer and an isolation reason,
but the CDA profile forbids a reason with a negative answer. Every case
therefore has a plausible positive indication until that upstream mismatch is
clarified. Locally coded concepts that lack a portable binding intentionally
exercise the configured `nullFlavor="OTH"` behavior.
