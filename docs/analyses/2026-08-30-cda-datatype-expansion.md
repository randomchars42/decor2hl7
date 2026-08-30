# CDA datatype-expansion implementation analysis — 2026-08-30

## Scope and evidence

This analysis records the implementation of the attached general HL7 V3
datatype-expansion plan against `randomchars42/decor2hl7` main at
`9e99f967c1820c7a1bdec6b1c57634c830df3d99`.

The current generated target was checked in
`randomchars42/decor2hl7-test-workspace` at
`fe305cfb4cbca30e10f645c2eea6359d3162c5fc`, using
`model/2026.1.2/notaufnahmeregister--60/cda.json` blob
`04ee1c35715ee5cff204397a4359059f1eebc145`. Traversing its effective document
tree produced this declared-type inventory:

`AD`, `ANY`, `BL`, `CD`, `CE`, `CR`, `CS`, `CS.LANG`, `CV`, `ED`, `II`, `INT`,
`INT.POS`, `IVL_PQ`, `IVL_TS`, `ON`, `PN`, `PQ`, `RTO_PQ_PQ`, `SD.TEXT`, `ST`,
`SXCM_TS`, `TEL`, `TS`, `TS.DATE.MIN`, `TS.DATETIME.MIN`, `UID`, and `URL`.

This is an evidence snapshot, not a manually maintained compiler allow-list.
The implementation derives and validates the inventory from each newly compiled
effective template.

## Existing-rule classification

The medication and pupil-side rules were reviewed before the rewrite:

- medication `for_each` aligns a repeated dataset medication group with the CDA
  section-entry occurrence boundary while keeping one shared section;
- pupil-side `fan_out` creates left/right CDA occurrences and their terminology-
  backed discriminators.

Both solve occurrence semantics. Datatype expansion supplies legal XML
components and value representations; it does not establish occurrence
identity. The rules therefore remain under `DEC-007` and their regressions stay
executable.

The mechanisms superseded by the new layer were the path-name payload heuristic,
renderer datatype dispatch, the old top-level renderer module, the old CDA
compiler module, and the renderer fallback for older generated repeat metadata.

## Resulting boundary

The authoritative CDA semantic chain is now:

```text
decor2hl7.cda.datatypes
        ↓
decor2hl7.cda.compile
        ↓
decor2hl7.cda.model
        ↓
mapping
        ↓
decor2hl7.cda.render
```

`cda.json` version 4 records the automatic inventory, datatype/template
provenance, structural targets, explicit writable targets, logical input types,
and compiled value representations. Unknown declared datatypes fail compilation
with their identity and path.

Focused tests cover generic AD and PN expansion, the postcode and given-name
mapping/rendering paths, ART-DECOR overlay precedence, aliases/inheritance, and
unknown datatype failure. The pre-existing medication and pupil-side tests are
part of the full regression suite.
