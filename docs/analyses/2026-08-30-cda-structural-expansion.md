# CDA/RIM structural expansion analysis — 2026-08-30

PR #10 made datatype value representations model-driven, but it could only
expand children already named by ART-DECOR. It therefore did not close wildcard
or omitted-child gaps below `observation`, `procedure`, or
`substanceAdministration`.

The follow-up uses the official HL7 CDA R2 normative XSDs, pinned by immutable
repository commit and cached by `fetch`. A procedural index resolves class names,
XSD inheritance, child elements, attributes and vocabulary-valued attributes.
The compiler overlays ART-DECOR constraints on this structure and then applies
datatype expansion. Provenance survives both stages.

Focused coverage demonstrates `observation/value` through `CD`,
`procedure/code` through `CD`, and
`substanceAdministration/doseQuantity/low` through `IVL_PQ` to a writable
quantity. The existing postcode test continues to prove `AD/postalCode`.

Medication `for_each` and pupil-side `fan_out` remain because structural
definitions do not determine source occurrence identity or laterality.
