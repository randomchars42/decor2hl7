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
remain unselected. In particular, `Typ Verlegung` is accepted and normalized as
source data but is not emitted because the exact target code-system include is
unresolved. The only intentional `nullFlavor="OTH"` cases are target-governed:
presenting-complaint wording and the reviewed allergy-agent fallback, each on a
target whose exact ValueSet declares OTH and whose datatype exposes
`originalText`.

The scenario site configuration supplies document confidentiality `N`
(`normal`), language `de-DE`, author name `decor2hl7user`, and
activation-scoped medication mood/status values. These are test-site values,
not portable mapping or compiler defaults. Administrative gender instead
travels through the reviewed `patient.geschlecht` model extension; the scenario
normalizes ECare-style `m`, `w`, and `d` source values to the exact HL7
AdministrativeGender members. The portable mapping declares the six required
confidentiality, language, author, and medication/subordinate-administration
targets as `site_requirements`; it records their channels and ownership without
copying these values.

Wildcard timing is deliberately narrower than the selected mapping inventory.
The source calls one field a timestamp and the other a numeric duration while
describing the latter as a period “from/(to)”; the CDA puts their selected
targets in mutually exclusive point and interval alternatives. The cases test
the unambiguous diagnostic point but omit the diagnostic duration and the two
therapy timing fields. Their exclusion is explicit in `scenario.json`; no
timestamp-to-interval-boundary meaning is inferred.
