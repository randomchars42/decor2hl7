# Closure phase 4 — settling the last five build-degrading artifacts

Date: 2026-09-03. Reference workspace: `decor2hl7-test-workspace`,
`spec/2026.1.2`, transaction `notaufnahmeregister--60`. Baseline for this
snapshot: `main` @ `c55bce5`, `build_degraded: 5`, validator `executable: true`
/ `complete: false` with 3 generation messages.

This snapshot records the retrieval evidence gathered for each of the five
remaining `build_degraded` artifacts, the disposition chosen for each, and the
resulting reference metrics. It is evidence for phase 4 of the root
[`PLAN.md`](../../PLAN.md).

## Retrieval conditions on the day

Every dated route of the specification API answered HTTP 500 during this
investigation, including routes that had answered 200 during the snapshot's own
fetch. A known-good control confirms the outage is not artifact-specific:

| Request | Result |
|---|---|
| `template/2.16.840.1.113883.10.20.22.4.16/2014-06-09T00:00:00/$extract?project=ccda-` | HTTP 500 |
| `template/2.16.840.1.113883.10.20.22.4.16/$extract?project=ccda-` | 200, `effectiveDate="2014-06-09T00:00:00"` |
| `valueset/1.2.276.0.76.11.53/2015-11-17T00:00:00/$extract?project=aktin-` | HTTP 500 |
| `valueset/1.2.276.0.76.11.53/$extract?project=aktin-` | 200, `effectiveDate="2015-11-17T00:00:00"` |
| `template/2.16.840.1.113883.10.20.1.53/2007-04-01T00:00:00/history?project=ccd1-` | HTTP 500 |

Conclusions below therefore rest on the dateless and cross-project routes, which
answered normally, and on the `resolution_attempts` recorded in the snapshot's
own manifest, which were collected while the dated routes worked. The outage is
a transient external condition and is not treated as a project finding.

## 1–2. VSAC medication value sets `1021.30` and `1099.12`

`2.16.840.1.113762.1.4.1021.30@2013-01-31` and
`2.16.840.1.113762.1.4.1099.12@2018-07-02T16:22:48` produce all three validator
generation messages. Both expand to a complete zero-member result.

The dateless `$expand` against `ccda-` returns the exact requested revisions and
shows why:

- `1021.30` ("Administration Unit Dose Form") carries the VSAC codes only as an
  escaped HTML table inside `<desc>`, with no `conceptList`, `items` or
  `concept` elements. The prose table is visibly damaged (OIDs are broken across
  lines as `2.16.840.1.11388 3.3.26.1.1`), so it is not a machine-readable
  domain even as evidence.
- `1099.12` ("Medication Route") carries a description and a publishing
  authority and nothing else; `valueSetExpansionAssociation count="0"`.

The content is maintained at VSAC under licensing this project does not carry.
Neither can be filled, and neither is a candidate for a builtin.

**Are they consulted by a selected field?** No. Neither OID appears in any
`model.json` field; both appear only in the `value_sets` catalog and in the CDA
target registry. All three generation messages name the same rule context
template `2.16.840.1.113883.10.20.22.4.16` (`MedicationActivity` and
`MedicationActivityV2`).

**Is that template in the selected closure?** No. It contributes 100 compiled
targets, and **none** of them holds a document location. Of the 274 templates
that contribute targets, 128 have at least one located target; this one does
not. The selected AKTIN document's effective medication branch is
`UV Medication Information (simple)`.

**Disposition:** scope the validator ValueSet accounting to the selected
document closure rather than waive genuine content. `build_degraded` no longer
counts a validator ValueSet whose rule context names only templates outside the
selected closure, and the validator's `complete` claim is scoped the same way.
Both remain fully visible: the raw `generation_messages` list is unchanged, and
`generation_message_scopes` records the value sets, context templates and
in/out classification per message. A message whose context cannot be parsed
stays in-closure, so the scoping can only be applied on positive evidence.

## 3–4. AKTIN ValueSet `1.2.276.0.76.11.53` and CodeSystem `…195.5.53`

`valueset:1.2.276.0.76.11.53@2015-11-17` ("Referral actions") is bound on a
selected field. Its definition is cached; its expansion is not:

- the dated `$expand` answered HTTP 500 at fetch time and again now;
- the dateless `$expand` returns 200 with the exact revision but with the
  intension unresolved: a single
  `<items is="include" codeSystem="1.2.276.0.76.3.1.195.5.53" flexibility="2019-12-30T00:00:00"/>`
  and `valueSetExpansionAssociation count="0"`.

The blocker is the intension code system
`1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` (`divi-codesystem-53`,
"andere-entlassungsarten"). It is published nowhere on the specification server:
the cross-project lookup `/codesystem/1.2.276.0.76.3.1.195.5.53` answers 404,
and the dated extract answered 404 in all eight candidate projects recorded in
`resolution_attempts` (`aktin-`, `pmp-`, `ad1bbr-`, `kbvde-`, `hl7de-`,
`ad2bbr-`, `hl7ips-`, `dguvbbr-`). Dateless extracts against `hl7de-`, `aktin-`
and `ihede-` also answer 404.

**Builtin or waiver?** Waiver. The DIVI Notfalldokumentation publication does
not publish the code list for this OID, and the HL7 Germany
`IG:Notaufnahmeregister` guide references sibling DIVI code systems
(`…5.51`, `…5.69`, `…5.72`, `…5.73`) but not `…5.53`, and publishes no code list
or effective date for any of them. A builtin would have to invent content for an
exact revision that no located publication describes, which `DEC-004` and
`DEC-012` both forbid.

The value set therefore stays `build_degraded` with `partial-expansion`, and its
bound field keeps a non-executable enumeration rather than falling back to
logical labels (`DEC-003`, `DEC-016`). Reopening evidence: a DIVI or HL7 Germany
publication of the code system at exactly `2019-12-30T00:00:00`, or the code
system appearing in an ART-DECOR project.

## 5. SPEC parent `template:2.16.840.1.113883.10.20.1.53@2005-09-07`

This is the HL7 CCD 1.0 "Product" template, the SPEC parent of
`1.3.6.1.4.1.19376.1.5.3.1.4.7.2` (IHE Medications) and `1.2.276.0.76.10.4025`
(German Material).

**Where the OID lives.** The Continuity of Care Document project `ccd1-`
(`2.16.840.1.113883.3.1937.777.4`) publishes it. Its template list and the
cross-project lookup `/template/2.16.840.1.113883.10.20.1.53` both return
exactly one revision, `2007-04-01T00:00:00`. The requested `2005-09-07T00:00:00`
revision exists in no project on the server.

**Does the omission degrade safely?** Yes, and this was verified rather than
assumed. `select_template` returns nothing when a static flexibility has no
exact match, so the `2007-04-01` revision — already cached from `pmp-` and
contributing its own 13 targets under its own identity — is never substituted.
`_effective_template` skips an unresolvable SPEC parent and the child still
compiles from `_direct_template` plus the pinned CDA/RIM expansion. In the
reference snapshot the children yield 44 (`…10.4025`) and 10
(`…1.4.7.2`) targets respectively, and the unresolved relation stays in
`cda.json` `unresolved_templates`. The strict compiler still refuses the
incomplete closure; only the tolerant build path omits and reports it.

**Does recovering it open medication slots?** No. Both children already compile
their own constraint trees, and neither holds a document location in the
selected document — the product-form and ingredient slots stay in the no-target
partition for the branch-selection reasons recorded in
[`2026-09-02-medication-compound-dependency.md`](2026-09-02-medication-compound-dependency.md),
not because of this parent.

**Disposition:** spec-only waiver. Reopening evidence: an ART-DECOR project
publishing the OID at exactly `2005-09-07T00:00:00`.

## Resulting reference metrics

| Measure | Before | After |
|---|---:|---:|
| Mapped datapoints | 95/120 | 95/120 |
| Crawl-degraded artifacts | 56 | 56 |
| Build-degraded artifacts | 5 | **3** |
| Validator `executable` | true | true |
| Validator `complete` | false | **true** |
| Generation messages | 3 | 3 (all outside the selected closure) |
| Manifest `waived` | 1 | 3 |

The three remaining `build_degraded` artifacts are
`valueset:1.2.276.0.76.11.53` (partial expansion),
`codesystem:1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00` (waived) and
`template:2.16.840.1.113883.10.20.1.53@2005-09-07T00:00:00` (waived). All three
are settled with cited evidence and named reopening conditions; none can be
closed from inside this repository.

## Incidental finding, fixed

Running `fetch --offline` against the reference snapshot flipped four code
systems (`0.4.0.127.0.16.1.1.2.1`, `2.16.840.1.113883.15.6`,
`2.16.840.1.113883.6.1`, `2.16.840.1.113883.6.96`) and the alias key
`2.16.840.1.1138836.96` from `ok` to `unavailable` with "not cached; network
disabled by `--offline`". This was first reproduced with the phase-4 changes
stashed, so it was pre-existing behaviour rather than a phase-4 regression.

The cause is an identity-modelling gap, not a cache problem. ART-DECOR publishes
a code system that a project references rather than defines as a reference
declaration carrying its identity on `ref`:

```xml
<codeSystems><project ident="hl7de-">
  <codeSystem ref="2.16.840.1.113883.6.96" name="Snomedct" language="de-DE"/>
</project></codeSystems>
```

`_payload_matches_request` recognised only the defining `id` form, so cache
adoption rejected a file that was in fact present and correct, and reported it
as not cached. The download path never ran that check, which is why the same
bytes were `ok` online.

Both `_payload_matches_request` and `_resolved_effective_date` now accept either
identity attribute. The revision guard is unchanged in strength: a reference
declaration identifies the artifact but proves no revision, so it satisfies a
static request only when it carries the requested `effectiveDate` — the analysis
envelope carries none and correctly cannot. Because that envelope has no
revision while the source form does, adoption now also reads the revision from
the cached source form, the way a download does, instead of downgrading the
recorded identity to `dynamic`.

After the fix, `fetch --offline` against the committed snapshot reports
`0 unavailable` and changes no artifact status. It additionally fills
`resolved_effective_date` for the three dated reference declarations, which had
been empty while `identity.effective_date` already carried the same value. The
manifest-reconstruct path (`manifest.json` deleted, then `fetch --offline`) also
adopts all four instead of reporting them missing.
