# Core-package validation implementation

> Historical snapshot. The refreshed 2026-09-13 workspace now isolates the
> exact 119-revision validator rule set, generates it with zero messages, and
> passes six authored documents with zero XSD/Schematron diagnostics. The
> counts below describe the earlier package-integration state.

## Scope and source snapshot

This evidence snapshot implements the restart checklist in
[`2026-09-02-decor-core-validation-follow-up.md`](2026-09-02-decor-core-validation-follow-up.md)
for release `2026.1.2`, transaction
`2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`.
It uses the local reference workspace after a completed fetch: 626 exact
resources were cached or available, 62 were known missing, one was waived, and
21 unavailable resources affected the build closure. No missing artifact was
replaced by another revision.

The package work is a conformance axis, not another mapping-proposal pass.
`cda-mapping.json` remains the editable source of mapping truth. Package rules
may reject an invalid representation, but they do not establish a semantic
dataset-to-CDA correspondence.

## Locked inputs

| Input | Version | SHA-256 | Purpose |
|---|---|---|---|
| ART-DECOR DECOR-core | `2.2.28` | `14bda739197800f754dff57a6242aa780c01004e58af0d33fc85de72888f9110` | DECOR XSD, Core Schematron, publication transform and datatype rules |
| HL7 CDA-core-2.0 | `e922fc35586fd2629f0c8a021080bca9ab424e18` | `cad63f59b3247b73b3ddc8caa4105080fb3a23c164a73a5dc000946d5be34ad4` | complete normative and SDTC XSD graph |
| Saxon-HE | `12.5` | `98c3a91e6e5aaf9b3e2b37601e04b214a6e67098493cdd8232fcb705fddcb674` | XSLT 2.0 Schematron compilation and execution |
| XML Resolver | `5.2.2` | `efc92bd7ed32b3e57095e0b3e872051ccfbbdcc980831ef33e89e38161a85222` | Saxon resolver dependency |

The lock contains 195 extracted DECOR-core files and 15 CDA normative/SDTC XSD
files with individual hashes. Original relative include/import paths are
preserved. Archive entries with absolute paths, parent traversal or unsafe CDA
member types are rejected.

## Additional executable rules obtained

The packages materially strengthen structural validation:

- DECOR XSD checks the ART-DECOR representation itself;
- `DECOR.sch` adds cross-artifact identity, status, cardinality, vocabulary,
  relationship, association and template-consistency rules;
- `DECOR2schematron.xsl` applies template inclusion, containment, conformance,
  fixed-value and assertion semantics defined by ART-DECOR and grounded in the
  HL7 Templates Standard;
- the generated validator incorporates the selected datatype Core
  Schematrons, including compound constraints such as the `EIVL_TS` event
  dependency already represented by DEC-020; and
- the complete CDA/SDTC schema import graph checks document grammar, RIM
  structures, narrative datatypes and the SDTC extensions actually present in
  the compiled active template.

These rules enhance the analysis by independently testing physical legality and
by exposing missing package/source material. They do not alter the authority
order for ART-DECOR associations: transaction/template-specific associations
remain semantic evidence; generic CDA/RIM/datatype legality remains physical
evidence only.

## Reference execution

| Stage | Policy | Result |
|---|---|---|
| DECOR source XSD on `project-evidence.xml` | report-only | passed with no diagnostics |
| DECOR source Core Schematron | report-only | 381 errors, 1,780 warnings, 536 information events |
| Exact-closure template generation | report-only during build | generated with 65 missing/undefined-ValueSet errors; QName-string namespaces are restored, then the Saxon probe rejects two malformed `[[hl7:supply]` match expressions from two revisions of one fetched template |
| Native compiled DECOR project Schematron | report-only | not run; that artifact is not published in the fetched API forms |
| Complete CDA R2/SDTC XSD | enforced by `validate-cda` | executable once a CDA document exists |
| Generated transaction + datatype Schematron | enforced by `validate-cda` | not executable for this closure; the gate records failure and does not run the invalid stylesheet |

The exact-closure assembler excludes ART-DECOR result-envelope metadata and
copies only effective-dated artifact definitions. It does not import live
project terminology to hide exact-closure gaps and is not described as a native
compiled project. Prefixes used in generated XPath strings are retained in one
collision-safe namespace registry (`pharm` and `pharm2` represent distinct
pharmaceutical namespaces in this snapshot). The 65 generator messages are retained in
`generation-messages.txt`; `validator-manifest.json` records the incomplete
state and checksums the assembled input, generated Schematron and validator
candidate. Full compilation output is retained in
`validator-compilation-errors.txt`, and the invalid stylesheet is not executed.

## Effect on mapping coverage

No mapping category changes. The current headline remains 92 of 120 dataset
datapoints mapped, and the package result does not reopen any of the previously
documented semantic boundaries:

| Boundary | Package finding | Mapping conclusion |
|---|---|---|
| Allergy Concern Act `effectiveTime/low` | Schematron can enforce the mandatory, non-null-flavored timestamp | no suitable transaction timestamp exists; no date is invented |
| Medication form, ingredient, strength, lot, start/stop, dose/rate, PRN, body site and reason | XSD/Core rules confirm or constrain possible physical slots | no sufficiently unambiguous active-profile source bridge was added |
| Medication event offset | datatype Core rule confirms non-null `EIVL_TS` requires `event` | remains review-only under DEC-020; no TimingEvent code is invented |
| Secondary ICD | template rules retain one atomic diagnosis value occurrence | occurrence-versus-translation semantics remain unresolved under DEC-009 |
| Seven smaller active-profile gaps | package graph strengthens physical validation | the one review candidate, three stranded exact entries and three missing bridge/crosswalk cases remain as documented |

The isolated mapping fixture still stops before emitting CDA at the known
Allergy Concern Act timestamp: the mandatory `effectiveTime/low` has no fixed,
mapped or default value and prohibits `nullFlavor`. This is the intended honest
failure and means no reference output was manufactured merely to demonstrate
the new validator.

## Implemented boundary

`fetch` acquires and verifies the packages. `build` emits report-only source
findings and the exact transaction validator. `validate-cda` is the independent
enforced output gate and returns non-zero for schema/rule errors, incomplete
generation, missing packages or checksum drift. Complete JSON diagnostics are
retained; Markdown displays at most 200 rows and points to the machine-readable
record.

The transformation runtime remains standard-library-only and does not load
DECOR-core, Saxon or Java. The unresolved source and terminology findings are
tracked in `docs/known-issues.md`, not hidden in this dated snapshot.
