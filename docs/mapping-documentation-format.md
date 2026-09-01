# Generated `cda-mapping.md` documentation

This specification defines the generated, human-facing `cda-mapping.md` user
guide. It applies to dataset-to-CDA mapping. The guide is for reviewers who
understand either the dataset or the CDA template but should not need to
understand compiler internals.

## Source of truth and report purpose

`cda-mapping.json` is the editable source of truth. `cda-mapping.md` and all
XML fragments are generated explanations and may be replaced by the next build.

The guide must say explicitly:

> Edit `cda-mapping.json`. Do not edit the XML examples in this report.

It connects three representations:

1. the human-readable dataset concept and its stable `model.json` datapoint;
2. the editable assignment or rule in `cda-mapping.json`;
3. the human-readable CDA template concept and its logical CDA target.

The report should answer, in order:

1. Where would mapped data appear in the CDA?
2. Which mappings are already executable?
3. Which decisions remain, and what may the reviewer choose?
4. What will each JSON choice produce?
5. Why was a mapping or candidate proposed?

## Required organization

Generate the guide in this order:

1. document identity, coverage and editing instruction;
2. compact CDA document outline;
3. sections and CDA entities;
4. selected configuration examples and contextual CDA previews;
5. decisions and mappings requiring review;
6. structural and transformation rules;
7. required-CDA completion rules;
8. a pointer to detailed evidence.

## Document outline

Group mappings below human-readable CDA sections and entities. Beneath an entity,
show the dataset name followed by the exact logical CDA target in braces. Keep a
short target inline; move a long target to an indented continuation line.

```text
Notaufnahmeregister Transitionsversion (ClinicalDocument)
├── Document header
│   ├── PatientIdentifier
│   │   └── Patienten ID → {PatientIdentifier.id}
│   ├── CDAEncompassingEncounter
│   │   ├── Aufnahmezeitpunkt
│   │   │   → {CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.low@20160601}
│   │   └── Zeitpunkt Patient verlegt / entlassen nach
│   │       → {CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.high@20160601}
│   └── CDADocumentationOf
│       └── Zeitpunkt erster Arztkontakt
│           → {CDADocumentationOf.documentationOf.serviceEvent.performer.time.low}
└── Document body (structuredBody)
```

The outline is an overview. It omits candidate scores, rejected alternatives and
long evidence chains.

## Section and entity presentation

For every section and CDA entity, show its human-readable name, template identity
and a short description when available. Align the three representations:

| Name in dataset | `model.json` datapoint | `cda-mapping.json` target | Name in CDA template | Status |
|---|---|---|---|---|
| Ergebnis der Ersteinschätzung | `ersteinschatzung.ergebnis` | `TriageResult.value` | Ergebnis der Ersteinschätzung (`CD`) | Mapped |

Use execution-oriented status labels:

- **Mapped** — direct executable assignment;
- **Transform** — executable after a declarative transformation;
- **Structural rule** — repetition, repeat-by-discriminator or coalescing
  controls assignment;
- **Rule** — another executable multi-target or fallback rule;
- **Review required** — no executable mapping has been approved.

Retain stable source and target keys even when good human names exist. Names make
the report understandable; keys make the decision traceable and editable.

## Empty sections must have an explained status

The sentence “No selected dataset mapping” is insufficient. It says only that no
configured field currently writes into the section. It does not say whether
candidate evidence exists.

Classify an empty section using both the compiled CDA model and
`mapping-audit.json`.

### Empty section with candidates

```markdown
### Zuweisung (Typeofreferralsource)

**Status: candidate mappings exist, but none is selected.**

Two unresolved dataset datapoints have candidates in this CDA section. Review
the choices below. Selecting a candidate means editing the corresponding entry
in `cda-mapping.json`.
```

Follow this summary with the affected decision cards.

### Empty section without candidates

```markdown
### Zuweisung (Typeofreferralsource)

**Status: no dataset mapping candidate found.**

No selected mapping writes into this section, and the current transaction,
associations and mapping evidence produced no candidate for it. The section may
be intentionally unused, or a manual mapping may still be required.
```

### Candidate exists but cannot be assigned to one section

If a candidate is contextual, ambiguous, or has no unique physical CDA location,
say so rather than assigning it to an arbitrary section:

```markdown
**Status: unresolved candidates exist outside a unique CDA location.**

See “Review required”; these candidates cannot yet be presented as mappings for
this section.
```

A section with no selected mapping must never silently imply “no candidates.”

## Configuration help

For the first simple mapping and every non-trivial pattern:

1. tell the reviewer what to edit in `cda-mapping.json`;
2. show an abridged JSON excerpt;
3. when useful, show the resulting CDA placement as contextual read-only XML.

### Direct mapping example

```markdown
In `cda-mapping.json`, map **Patienten ID** by setting
`fields["patient.identifikatoren.patienten_id"]` to
`"PatientIdentifier.id"`.
```

```json
{
  "fields": {
    "patient.identifikatoren.patienten_id": "PatientIdentifier.id"
  }
}
```

## Contextual CDA XML previews

A list of isolated leaves is not a useful CDA example. XML previews must show
enough surrounding structure to explain where the values appear.

For every preview:

- start at the nearest meaningful CDA entity or header component;
- retain the ancestor path from that entity to every illustrated target;
- retain relevant fixed attributes, such as `classCode`, `moodCode`,
  `typeCode`, `xsi:type`, template identifiers and fixed codes;
- merge targets belonging to the same entity into one fragment;
- emit each physical target once, even when several source fields feed it;
- explain structural rules or source precedence in an XML comment;
- omit unrelated branches with a single `<!-- … -->` when useful;
- keep placeholders in `{braces}` and explain that they name generated CDA
  datapoints;
- omit the XML preview entirely when a meaningful enclosing fragment cannot be
  produced.

### Header-component mockup

Instead of:

```xml
<low value="{CDAEncompassingEncounter....low}"/>
<id extension="{CDAEncompassingEncounter.id_2}"/>
<id extension="{CDAEncompassingEncounter.id_1}"/>
<high value="{CDAEncompassingEncounter....high}"/>
<low value="{CDAEncompassingEncounter....low}"/>
```

generate one merged contextual fragment:

```xml
<!-- Read-only consequence of cda-mapping.json. -->
<componentOf typeCode="COMP">
  <encompassingEncounter classCode="ENC" moodCode="EVN">
    <id extension="{CDAEncompassingEncounter.id_1}"/>
    <id extension="{CDAEncompassingEncounter.id_2}"/>
    <effectiveTime>
      <!-- encounter-time: either source may populate low;
           if both are present, equal_or_error requires equal values. -->
      <low value="{CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.low@20160601}"/>
      <high value="{CDAEncompassingEncounter.componentOf.encompassingEncounter.effectiveTime.high@20160601}"/>
    </effectiveTime>
  </encompassingEncounter>
</componentOf>
```

This mockup demonstrates three required improvements: ancestor context, merged
siblings and deduplication of the repeated `low` target.

### Entry mockup

```xml
<!-- Read-only consequence of cda-mapping.json. -->
<observation classCode="OBS" moodCode="EVN">
  <templateId root="{Diagnosis.templateId}"/>
  <value xsi:type="CD"
         code="{Diagnosis.value}"
         displayName="{Diagnosis.displayName}"/>
</observation>
```

The preview is explanatory rather than a complete production document. Text in
`{braces}` names generated CDA datapoints; it is not XML the reviewer should
edit.

## Decisions with multiple candidates or rules

When the audit contains several actionable candidates or supported executable
rules, tell the reviewer explicitly:

- that a choice is required;
- whether exactly one or more than one option may be selected;
- the human name and short purpose of every option;
- whether the option is directly selectable, requires a transform, requires a
  structural rule, or is evidence/context only;
- the exact JSON change for every supported executable option;
- that retaining `null` is allowed and what its runtime consequence is.

Do not advertise a rule that the runtime does not support. Do not call
context-only evidence selectable.

### Target-choice mockup

```markdown
### Decision required: Art der Zuweisung

Dataset datapoint: **Art der Zuweisung**
(`administrative_aufnahmeinformationen.zuweisung.art`)

Current configuration: `null`

Choose **one** executable target below, or retain `null`.

| Option | CDA name and target | Datatype | Confidence | Evidence | Result and meaning |
|---:|---|---|---|---|---|
| 1 | **Art der Zuweisung** — `Typeofreferralsource.code` | `CD` | STRONG | formal template association | **Selectable** — writes the coded referral source |
| 2 | **Zuweisender Dienst** — `Referringprovider.code` | `CD` | MEDIUM | related terminology | **Selectable after review** — represents the referring service rather than the referral type |
| — | **Zuweisung section** — `Typeofreferralsource` | — | CONTEXT | structural association | **Context only** — identifies placement, not a writable value |

To choose option 1, set:

```json
{
  "fields": {
    "administrative_aufnahmeinformationen.zuweisung.art":
      "Typeofreferralsource.code"
  }
}
```

To choose option 2, replace the value with
`"Referringprovider.code"`. Retaining `null` leaves the dataset datapoint
unmapped; optional CDA content is omitted and active required nullable content
uses the configured completion rule.
```

Candidate names and explanations come from the compiled CDA target’s template
display name, description and path. They must not be invented by the Markdown
renderer.

### Rule-choice mockup

```markdown
### Decision required: encounter start

Two dataset datapoints refer to one CDA encounter-start target.

Choose one supported behavior:

1. **`equal_or_error` coalescing** — either value may populate the target; if
   both are present they must be equal. This preserves both sources without
   silently choosing between conflicting values.
2. **Map only Aufnahmezeitpunkt** — use only the first datapoint and keep the
   other field `null`.
3. **Keep both fields unmapped** — no dataset value populates the target; the
   configured required-CDA completion policy applies if the element is active.

The runtime supports no “prefer first” rule, so that choice is not offered.
```

Every offered rule must be accompanied by its exact abridged JSON configuration.

## Review required

Use the same candidate structure as the concise candidate table derived for
`cda-mapping-details.md`, enriched with a human target name and a short
explanation.

For each unmapped dataset datapoint, generate a decision card rather than only a
comma-separated list:

```markdown
### Transportmittel

`administrative_aufnahmeinformationen.transport.transportmittel`

**Current selection:** none — `null` in `cda-mapping.json`

**Reason:** candidate evidence exists, but none is safe enough to become an
executable mapping automatically.

| Target | CDA name / short explanation | Datatype | Confidence | Evidence | Result |
|---|---|---|---|---|---|
| `TransportMode.code` | **Transportmittel** — coded means of transport | `CD` | STRONG | template association | selectable |
| `ArrivalMode.code` | **Art der Ankunft** — describes arrival rather than the vehicle | `CD` | MEDIUM | related terminology | alternative |
| `TransportSection` | **Transport section** — structural context only | — | CONTEXT | group association | evidence only |

**Available actions:**

1. select a row marked **selectable** or **alternative** using the generated JSON
   excerpt;
2. define the indicated transform or structural rule when required;
3. retain `null` deliberately.

Full scores and evidence chains remain in `cda-mapping-details.md` and
`mapping-audit.json`.
```

If no candidate exists, the card must say:

```markdown
**Reason:** no usable CDA target evidence was found.

No candidate can be offered from the currently available transaction, templates
and terminology. Keep `null`, or manually inspect `cda.json` and add a target
only after confirming its semantics and datatype.
```

The report must distinguish:

- **selectable** — executable by assigning the target;
- **transform required** — executable only with the shown transform;
- **rule required** — shared/repeating semantics must be configured;
- **alternative** — actionable but not selected automatically;
- **evidence only** — useful context, not a writable choice;
- **no candidate** — no usable target evidence was found.

Where available, unresolved rows should also state the compiled cause:

- `datatype_component_available` — evidence reaches a complex datatype and a
  value-bearing component must be chosen;
- `structural_only` — evidence reaches a container with no identified writable
  descendant;
- `ambiguous_value_target` — more than one physical value target remains;
- `incompatible_value_type` — a writable target exists but its compiled logical
  type is incompatible;
- `no_semantic_evidence` — no usable target evidence was found.

The expanded CDA documentation must identify whether a node comes from an
ART-DECOR template, an HL7 datatype part, or both. Datatype-derived optional
parts are legal targets, not instructions to emit empty XML elements.

## Rules and reasoning

Describe rules through observable behavior:

- which source datapoint or repeat group drives the rule;
- which CDA target or occurrence it creates;
- what happens when values are absent;
- what happens when values conflict;
- why the rule is necessary.

Examples:

```markdown
`diagnosis-occurrences`: create one CDA Diagnosis occurrence for every input
diagnosis row. Values from one row stay in the same CDA occurrence.
```

```markdown
`medication-occurrences`: create one medication-section `entry` for every input
medication occurrence. All entries share one enclosing medication section, and
values from one source occurrence stay in its own entry.
```

```markdown
`pupils`: create a right-pupil occurrence when Pupillengröße rechts is present
and a left-pupil occurrence when Pupillengröße links is present. Both use the
physical CDA `Pupilsize.value`; fixed target-site codes distinguish the
logical datapoints `Pupilsize_right.value` and `Pupilsize_left.value`.
```

```markdown
Diagnosis certainty is mapped within each diagnosis occurrence. Code `A` also
sets `negationInd=true`. No diagnosis end is derived from code `Z`, because
“Zustand nach” supplies no timepoint. The required diagnosis onset that the
selected transaction does not provide uses the reviewed target default
`nullFlavor="UNK"`; it does not manufacture a date.
```

## Mapping reasoning

For a selected mapping, name the strongest evidence and any semantic step needed
for execution.

Good example:

```markdown
Selected because a formal ART-DECOR template association connects the dataset
concept to this CDA element. The datatypes are compatible, so no transform is
required.
```

Good unresolved example:

```markdown
Two actionable targets have comparable evidence. Neither is selected because
they represent different clinical meanings; the reviewer must choose one.
```

Insufficient example:

```markdown
Score: 117; confidence: HIGH.
```

A score alone does not explain the evidence, clinical distinction or runtime
behavior.

## Compactness rules

- Show all mappings in entity tables.
- Do not generate full JSON and XML for every direct mapping.
- Generate one simple example and one example for every non-trivial pattern that
  occurs: transform, repetition, repeat-by-discriminator, coalescing, fallback,
  ambiguity or target-specific default.
- Group candidate details into decision cards only for unresolved or ambiguous
  fields.
- Limit the working guide to the strongest five candidates; keep complete
  evidence in the detailed report.
- Merge one entity’s XML targets into one contextual fragment.
- Omit XML that would contain only isolated leaves.
- Truncate prose descriptions, not identifiers.

## Generation requirements

- Generate deterministically from `model.json`, the compiled CDA model,
  `cda-mapping.json` and `mapping-audit.json`.
- Present the direction consistently as dataset model → editable mapping → CDA.
- Never phrase XML as a place where the user enters values.
- Reuse candidate classification and reasoning from the mapping audit; do not
  implement a second scoring system in the report generator.
- Distinguish selected mappings, alternatives, transforms, rule requirements,
  context-only evidence and absence of candidates.
- Preserve occurrence semantics whenever source or target repetition is involved.
- State conflict, fallback and missing-value behavior explicitly.
- Do not maintain duplicate hand-written mapping facts in the Markdown
  generator.
