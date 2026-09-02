# Seven active-profile mapping gaps after medication correction

Date: 2026-09-02

Status: investigated on merged `main`; no executable mapping approved.

## Scope and result

This analysis follows the medication correction merged as `70e16de` and
re-examines the seven non-medication datapoints that remain in the no-target
partition. It uses the local reference release `2026.1.2`, transaction
`notaufnahmeregister--60` (`2.16.840.1.113883.2.6.60.3.4.60` at
`2026-03-25T00:00:00`) and representing document
`1.2.276.0.76.3.1.195.10.93@2026-03-25T11:04:07`.

The clean-build coverage remains:

```text
Model: 120 datapoints · ✓ mapped 92 dp → 94 leaves · ! suggested 5 dp → 5 leaves · × no target 23 dp · ○ no source 359 leaves
```

All seven fields remain `null` in the proposed mapping. The investigation does,
however, separate them into three materially different follow-ups:

| Class | Count | Result |
|---|---:|---|
| Bounded local semantic decision | 1 | The insurance number has a unique active physical CDA/RIM slot, but no current formal source-to-leaf bridge. It is a candidate for explicit review, not an automatic mapping. |
| Exact target stranded outside the active closure | 3 | Export interval, EDIS name and EDIS version have exact draft entry definitions and exact terminology, but no selected containment. An ART-DECOR closure correction is expected to recover them. |
| Active representation or complete crosswalk absent | 3 | General event onset and MRI/X-ray regions cannot be represented completely by the currently selected statements. |

No edit to `cda-mapping.json` is recommended from this analysis. Edit
`cda-mapping.json`. Do not edit the XML examples in this report.

## Evidence authority and decision gates

The investigation used, in order:

1. the selected transaction and its concept, terminology and relationship
   evidence under the local `test-workplace/spec/2026.1.2` snapshot;
2. a clean build's `model.json`, `cda.json`, `mapping-audit.json` and
   `cda-mapping.proposed.json`;
3. exact effective templates in the selected CDA closure;
4. `project-evidence.xml` for historical or draft definitions outside the
   closure; and
5. accepted project rules in [`../decisions.md`](../decisions.md), especially
   DEC-003 and DEC-013 through DEC-018, and the physical-plus-semantic boundary
   recorded in the
   [earlier residual audit](2026-09-02-residual-mapping-boundaries.md).

A mapping must pass two independent gates:

| Gate | Required evidence |
|---|---|
| Physical | A unique, writable, non-prohibited leaf at an active document location, with executable datatype and occurrence behavior |
| Semantic | A current association, exact terminology/discriminator relationship or explicit reviewed rule connecting the source meaning to that leaf |

An open template can make a CDA/RIM slot physically legal without assigning
dataset semantics to it. Conversely, an exact draft entry outside the document
closure can prove intended semantics without supplying a physical placement.
DECOR-core, CDA XSD and Core Schematron validation would strengthen the physical
gate, but cannot create either a missing association or a missing containment.
The separate
[DECOR-core follow-up](2026-09-02-decor-core-validation-follow-up.md) records
that deferred validation work and is not reinterpreted here.

The compiled closure used here contains 308 reachable templates, 24,940 named
targets, 18,285 renderable targets, 16,878 writable targets and 94 logical CDA
datapoints. It reports the same 21 unavailable artifacts and one unresolved CDA
reference already documented for this snapshot.

## Dataset-to-CDA status

| Name in dataset | Stable `model.json` datapoint | CDA target or closest evidence | Status |
|---|---|---|---|
| Identifikation des Versicherungsverhältnisses | `hauptkostentrager.versicherungsverhaltnis.identifikation` | Physical `HeaderParticipantKostentraeger.participant_templateId_root_1.2.276.0.76.3.1.195.10.4.associatedEntity.id` | Review required; semantic bridge absent |
| Ereigniseintritt | `notfallanamnese.beschwerden_bei_vorstellung.ereigniseintritt` | Concern Act `low` and generic Problem Observation `low` | No target; wrong or inactive-profile semantics |
| MRT Untersuchungsregion | `diagnostik.bildgebende_diagnostik.magnetresonanztomographie.untersuchungsregion` | Reachable `Magneticresonanceimaging` statement | No target; statement has no region-bearing leaf |
| Röntgen Untersuchungsregion | `diagnostik.bildgebende_diagnostik.rontgen.untersuchungsregion` | Five reachable fixed-code X-ray statements | No target; only a partial, unqualified discriminator resemblance exists |
| Zeit bis zum Export | `dokumentationsinformationen.berechnete_zeitintervalle.zeit_bis_zum_export` | Draft `.10.85`, code `FLN-134`, `PQ` value in hours | No active physical location |
| Name des EDIS | `dokumentationsinformationen.datenbereitstellung.name_des_edis` | Draft `.10.86`, code `FLN-135`, `ST` value | No active physical location |
| Version des EDIS | `dokumentationsinformationen.datenbereitstellung.version_des_edis` | Draft `.10.87`, code `FLN-136`, `ST` value | No active physical location |

## Review required: insurance-relationship identifier

### Source and active context

The selected source is an optional identifier whose definition is
“Identifikation des Versicherungsverhältnisses, Versichertennummer.” Its
selected concept `...3.2.9.21582` inherits `...3.2.6.21582`; the transaction
also records historical origin `...77.2.2.60210`. None of these identities is
connected by a current static association or terminology association to an
insured-number leaf.

`CTX[21581]` uniquely locates the parent in active template
`1.2.276.0.76.3.1.195.10.4@2024-08-09T10:35:24` at document location
`0.15.0`. The active template is open, fixes the role to `POLHOLD` and says in
its own description that the insurance number and insurer identification are
of interest. Its explicit children distinguish the insurer from the insured
relationship:

- `associatedEntity/scopingOrganization/id` at `0.15.0.1.1.0` is described as
  identification of the insurance company; and
- it does not explicitly constrain `associatedEntity/id`.

CDA/RIM expansion supplies the omitted `associatedEntity/id` at
`0.15.0.1.5`. It is a writable, repeatable `II`, represented as an identifier
whose scalar source value is written to `extension`. This passes the physical
gate. It is not currently a logical CDA datapoint and has only `cda-rim`
provenance, so it does not pass the semantic gate.

### Historical evidence and its limit

The active `.10.4` template specializes historical
`1.2.276.0.76.10.2022@2014-08-25`. That historical template explicitly calls
`associatedEntity/id` “Versichertennummern” and has static associations from
older AKTIN concepts `...3.2.2.808` and `...3.2.3.808`. The selected concept
21582 is not related to either 808 concept in the compiled relationship graph.

This is stronger evidence than a label collision: the active role, active
template description, unique physical path and specialized historical leaf all
agree. It still does not make the old leaf constraint part of the active
specialization. The compiler deliberately treats `SPEC` as constraint
refinement and does not concatenate parent-only prototype children into the
specialized template. Carrying the historical leaf meaning forward would
therefore be a new semantic policy, not a bug fix implied by current policy.

The distinct placements are:

```xml
<!-- Read-only illustration; this is not cda-mapping.json configuration. -->
<participant typeCode="HLD">
  <templateId root="1.2.276.0.76.3.1.195.10.4"/>
  <associatedEntity classCode="POLHOLD">
    <id extension="{insured number}" root="{identifier root}"/>
    <scopingOrganization>
      <id extension="{insurer organization identifier}"
          root="1.2.276.0.76.4.5"/>
      <name>{insurer name}</name>
    </scopingOrganization>
  </associatedEntity>
</participant>
```

An isolated feasibility probe confirmed that, if a logical datapoint is
temporarily attached to the physical `associatedEntity/id` and an identifier
root is supplied, existing configuration validation and rendering mechanics can
write the identifier. That probe establishes mechanical feasibility only; it
does not establish the missing source-to-target correspondence.

### Decision

Keep the source mapping `null`. Reopen it by either:

1. adding a current ART-DECOR association or explicit `associatedEntity/id`
   child for concept 21582; or
2. accepting and testing a general rule that carries a uniquely matching
   historical prototype meaning onto an active, open specialization's same
   physical CDA/RIM path.

The second option requires a new reviewed decision. It must define identity,
path, uniqueness, occurrence and identifier-root requirements and must not be a
template-OID or German-label exception.

## No active representation: general event onset

The source is a datetime with the direct SNOMED CT terminology association
`298059007` “Date of onset.” Its definition is intentionally broad: event or
symptom onset for stroke, myocardial infarction, accident, resuscitation and
other presentations. `CTX[10034]` locates only the Chief Complaint section
`1.2.276.0.76.10.3048@2015-01-10`.

Two nearby leaves were examined:

| Candidate | Physical evidence | Semantic failure |
|---|---|---|
| Problem Concern Act `.10.4039@2015-03-03` `effectiveTime/low` | Required `IVXB_TS` at `0.18.0.4.0.0.4.0.0.4.0` | It dates the concern-tracking container for the most prominent CEDIS complaint, not a general clinical event. |
| Problem Observation `.10.4040@2015-09-18` generic `effectiveTime/low` | CDA/RIM expansion exposes an optional `low` | The active template explicitly requires `width` in hours and does not select `low`; the older 2015-03-03 revision described/required `low`. Parent/RIM structure does not restore the retired semantic choice. |

No template in the selected project evidence uses source code `298059007`, and
no association connects concept 20101 to either occurrence. Mapping the field
would both narrow its domain and attach it to a complaint occurrence that the
source does not uniquely identify. A valid recovery needs an active onset
statement or an explicit association and occurrence rule for the intended
problem/complaint.

## No region-bearing target: MRI

This finding corrects the wording of the earlier residual snapshot: an MRI
entry is reachable. Active template
`1.2.276.0.76.10.4058@2015-09-18` occurs at
`0.18.0.7.0.0.17.0.0` and fixes the observation code to LOINC `25056-3`,
“Unspecified body region MRI.”

The source is one of 16 inline logical choices. It has no ValueSet binding,
code system or formal member mapping. The active statement offers:

| Active leaf | Meaning | Suitability for region |
|---|---|---|
| fixed `code` `25056-3` | Unspecified-body-region MRI procedure | Not writable and deliberately does not carry the selected region |
| required `effectiveTime` | Time of examination | Wrong datatype and meaning |
| required `value` | Finding | Wrong meaning |

There is no `targetSiteCode` or other region-bearing child. Activating the MRI
statement from region presence would lose the actual source value and require
unprovided examination time and finding data. The reachable wildcard diagnostic
statement also does not solve this: it requires an explicit code/value and
definition-link contract and has no association or placement rule for this
source group.

Recovery requires an active MRI representation that carries the region, or an
explicit complete rule for another selected statement. Datatype expansion alone
cannot produce the missing semantic slot.

## Incomplete discriminator crosswalk: X-ray region

The Röntgen source group repeats, and its sole field has 13 inline logical
choices. Three choices have code-looking synonyms that exactly match fixed
LOINC codes in reachable statements:

| Source member | Unqualified synonym | Reachable fixed statement |
|---|---|---|
| Thorax | `30745-4` | `.10.4050` Plain chest X-ray |
| Gesamte Wirbelsäule | `38008-9` | `.10.4051` Spine X-ray |
| Becken | `28561-9` | `.10.4052` Pelvis X-ray |

The remaining reachable fixed statements are `.10.4053` extremity X-ray
(`37637-6`) and `.10.4054` unspecified-region X-ray (`43468-8`). The source
upper/lower-extremity and “Sonstige” members do not carry those codes, and the
other source regions have no corresponding selected fixed statement.

The three matching strings are source synonyms, not terminology associations:
they have no code system and do not make the 13-member logical choice list a
LOINC domain. Even a reviewed three-member match would leave ten legitimate
values unrepresented. A complete rule would also have to define:

- how repeated source occurrences select singleton fixed statements;
- what happens when the same region occurs more than once;
- whether specific spine or extremity regions may collapse to broader
  statements; and
- how source-region presence coalesces or conflicts with the already mapped
  `rontgenthorax_durchgefuhrt`, `rontgenwirbelsaule_durchgefuhrt` and
  `rontgenbecken_durchgefuhrt` booleans that control the same statements'
  `negationInd`.

Partial mapping would silently discard supported source values, so the field
remains `null`. Recovery needs a code-system-qualified, complete member
crosswalk plus explicit repeat/coalescing/conflict behavior, or a general
region-bearing X-ray statement.

## Exact semantics without active containment: EDIS metadata

These three fields pass the semantic gate unusually well. The selected concepts
have direct, equal terminology associations, and `project-evidence.xml` defines
matching draft CDA entry templates:

| Source field | Exact association | Intended template | Required value |
|---|---|---|---|
| Zeit bis zum Export | `FLN-134` in `1.2.276.0.76.3.1.195.5.98` | `.10.85@2024-05-24` | `PQ`, fixed unit `h` |
| Name des EDIS | `FLN-135` in the same code system | `.10.86@2024-05-24` | `ST` |
| Version des EDIS | `FLN-136` in the same code system | `.10.87@2024-05-24` | `ST` |

They fail the physical gate. The selected document contains Addendum
Dokumentationsinformationen section
`1.2.276.0.76.3.1.195.10.73@2024-08-15T11:08:15` at
`0.18.0.14.0.0`, but that section explicitly contains only `.10.75`, `.10.76`
and `.10.77`. Entries `.10.85`, `.10.86` and `.10.87` have generic
`context id="**"`, are not contained or referenced by a selected template, and
are absent from the compiled `cda.json` closure.

The section is open, so a generic CDA `entry` is structurally possible. That
does not identify which draft template belongs there or establish occurrence
and cardinality. The compiler must not infer containment from OID sequence,
similar names or nearby source hierarchy.

The three weak `mapping-audit.json` alternatives for export interval point to
encounter `effectiveTime/low`. They are rejected independently: a quantity in
hours is neither datatype-compatible with nor semantically equivalent to an
encounter timestamp. EDIS name and version have no candidates at all.

The direct upstream repair is to add explicit, dated containment for `.10.85`,
`.10.86` and `.10.87` to `.10.73` or another selected section, with intended
cardinalities. A fresh build should then expose the exact value leaves and is
expected to recover three mappings from the existing equal terminology
associations, subject to ordinary validation. No compiler semantic rule is
needed to guess their meaning.

## Configuration consequence

The generated proposal correctly retains:

```json
{
  "fields": {
    "hauptkostentrager.versicherungsverhaltnis.identifikation": null,
    "notfallanamnese.beschwerden_bei_vorstellung.ereigniseintritt": null,
    "diagnostik.bildgebende_diagnostik.magnetresonanztomographie.untersuchungsregion": null,
    "diagnostik.bildgebende_diagnostik.rontgen.untersuchungsregion": null,
    "dokumentationsinformationen.berechnete_zeitintervalle.zeit_bis_zum_export": null,
    "dokumentationsinformationen.datenbereitstellung.name_des_edis": null,
    "dokumentationsinformationen.datenbereitstellung.version_des_edis": null
  }
}
```

An absent optional source emits no invented participant identifier, onset time,
diagnostic occurrence or metadata entry. A populated source remains explicitly
unmapped and visible in coverage; it is not silently redirected to a merely
datatype-compatible leaf.

## Reopening evidence and priority

| Priority | Fields | Smallest sufficient new evidence |
|---|---|---|
| 1 | Export interval, EDIS name, EDIS version | Explicit selected containment of `.10.85`–`.10.87`; rebuild and validate. This is the clearest potential +3 coverage change. |
| 2 | Insurance identifier | Current association/explicit child, or acceptance of a generic historical-specialization carry-forward rule with identifier-root and occurrence semantics. Potential +1 after review and implementation. |
| 3 | X-ray region | Complete qualified crosswalk for all 13 values plus repeat, coalescing and conflict rules, or a region-bearing active statement. |
| 4 | MRI region | Active statement with a region-bearing target and completion semantics. |
| 5 | Event onset | Active event/problem-onset representation plus an association and occurrence-owner rule. |

The ordering reflects closeness to an executable mapping, not clinical
importance. The first three metadata fields already have exact semantics; their
missing link is structural. The remaining fields require semantic decisions or
new active-profile content.

## Verification

The investigation was performed on clean merged `main` commit `70e16de`. The
reference `aktin.json` and isolated build agree on release, transaction and
effective date. The following evidence was checked directly:

- all seven source definitions and current `mapping-audit.json` records;
- all seven `null` assignments in `cda-mapping.proposed.json`;
- active document locations and writable target metadata in `cda.json`;
- exact `.10.4`, `.10.73`, `.10.85`–`.10.87`, `.10.4039`, `.10.4040`,
  `.10.4050`–`.10.4054` and `.10.4058` definitions in local project evidence;
- absence of `.10.85`–`.10.87` from selected containment and compiled targets;
  and
- existing X-ray boolean selections that would share the fixed statements.

This is a documentation-only investigation. It changes neither mapping policy
nor runtime behavior.
