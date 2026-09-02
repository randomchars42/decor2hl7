# Residual dataset-to-CDA mapping boundaries after PR #20

Date: 2026-09-02

## Scope and result

This analysis consolidates the post-PR #20 audit of the selected AKTIN
2026.1.2 transaction and its active CDA closure. It covers the still-open
allergy completion rule, the complete medication group, secondary ICD-10
diagnoses and the seven remaining non-medication datapoints without a selected
target.

Fresh-build coverage is:

```text
Model: 120 datapoints · ✓ mapped 93 dp → 95 leaves · ! suggested 4 dp → 4 leaves · × no target 23 dp · ○ no source 359 leaves
```

The audit adds no executable mapping. The four suggestions need a structural
or semantic rule, and the 23 no-target datapoints need evidence that is absent
from the selected transaction or active template closure. Retaining `null` is
therefore the reviewed correctness decision, not an unfinished automatic
assignment.

Edit `cda-mapping.json`. Do not edit XML examples in generated reports or in
this evidence record.

## Evidence authority and decision rule

The audit used these sources together, in descending local relevance:

1. the selected transaction, concepts, terminology and associations under the
   fresh `spec/2026.1.2` snapshot;
2. the compiled `model.json`, `cda.json`, `mapping-audit.json` and proposed
   mapping produced from that snapshot;
3. the exact effective AKTIN, HL7, PMP and IHE templates reachable from the
   representing document;
4. project evidence outside that closure, only as non-executable historical or
   design evidence;
5. the ART-DECOR association, dataset, CDA and datatype documentation for the
   meaning of the formal constructs.

ART-DECOR permits zero or more dataset-to-template associations and supports
associations to a whole template or part of one. Consequently, an absent
association is allowed and means that the project supplied no formal
association; it does not mean that CDA could never represent the datum. An
inline dataset `conceptList` is a choice list unless it is explicitly bound to
a ValueSet. `CD.translation` is an alternative coding of the same concept, not
a generic slot for a related code. These distinctions follow the official
[association and mapping documentation](https://docs.art-decor.org/introduction/associations/),
[dataset documentation](https://docs.art-decor.org/documentation/dataset/),
[CDA principles](https://docs.art-decor.org/introduction/cda/) and
[`CD` datatype documentation](https://docs.art-decor.org/documentation/datatypes/DTr1_CD/).

An executable assignment therefore has two independent gates:

| Gate | Question | Insufficient by itself |
|---|---|---|
| Physical | Is the leaf writable in the effective CDA/RIM model and still permitted by every active template? | A legal `effectiveTime`, quantity, code or text leaf |
| Semantic | Does a formal association, fixed discriminator, exact terminology relationship or other explicit specification rule connect this source meaning to that leaf? | Similar labels, proximity, datatype compatibility or a historical template |

Both gates must pass. The compiler remains target-neutral: no German/English
name heuristic, template-OID exception or inferred clinical relation was added.
The local project does not currently pin a verified DECOR-core schema release;
pinning and checksumming such a normative dependency is a separate follow-up,
not evidence used to approve the mappings below.

## Coverage partition

| Dataset status | Count | Residual partition |
|---|---:|---|
| Mapped | 93 datapoints to 95 leaves | Includes six medication fields and the allergy agent/narrative/derived flags |
| Suggested | 4 datapoints to 4 leaves | Medication start, stop and dosage timepoint collide on one atomic timing leaf; secondary ICD collides with the primary value |
| No target | 23 datapoints | Sixteen medication fields plus seven smaller residuals |

The allergy Concern Act timestamp is a required-CDA completion boundary rather
than an additional unmapped source datapoint, so it does not change this
partition.

## Allergy completion boundary

The agent and narrative mappings and the antibiotic/contrast-agent
discriminated occurrences are executable. A complete Allergy Concern Act
`1.2.276.0.76.10.4065` also requires `effectiveTime/low`, representing when the
allergy was first documented as a concern. The source allergy group supplies no
suitable timestamp and the required leaf prohibits `nullFlavor`.

Document time, encounter time and an arbitrary current time have different
meanings. None was substituted. If a mapped allergy occurrence activates the
Concern Act without a real concern-onset source, required-target validation
must report the missing sibling.

## Medication

### Active context

The dataset repeat remains bound by the existing `for_each` rule to one entry
per `masnahmen.medikamentose_therapie` occurrence. The relevant active templates
are:

| Role | Template |
|---|---|
| Medication section | `1.2.276.0.76.3.1.195.10.64` |
| Medikation | `1.2.276.0.76.3.1.195.10.67@2023-12-03` |
| UV Medication Information (simple) | `2.16.840.1.113883.10.21.4.10@2021-09-29T19:15:16` |
| UV Subordinate Substance Administration | `2.16.840.1.113883.10.21.4.6@2023-01-30T09:36:00` |

### Executable medication mappings

| Name in dataset | `model.json` datapoint | `cda-mapping.json` target | Status and evidence |
|---|---|---|---|
| Arzneimittel-Name | `masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelname` | `UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.name` | Mapped; static association projected to the unique common slot |
| Arzneimittel-Code | `masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelcode` | `UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.code@20210929` | Transform; static association plus declared open code system |
| Sequenznummer | `masnahmen.medikamentose_therapie.medikation.dosierung.sequenznummer` | `Medikation.sequenceNumber` | Mapped; predicate-aware ART-DECOR choice |
| Freitext | `masnahmen.medikamentose_therapie.medikation.dosierung.freitext` | `Medikation.text` | Mapped; static association projected to common slot |
| Offset | `masnahmen.medikamentose_therapie.medikation.dosierung.zeitangabe.ereignisbezogene_wiederholung.offset` | `UVSubordinateadministration.substanceAdministration.effectiveTime_xsi_type_EIVL_TS.offset` | Mapped; contextual descendant exposed by datatype expansion |
| Art der Anwendung | `masnahmen.medikamentose_therapie.medikation.dosierung.art_der_anwendung` | `Medikation.routeCode` | Mapped; static association projected to common slot |

The product-code rule is declarative and preserves the source code under its
declared code system:

```json
{
  "fields": {
    "masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelcode": {
      "target": "UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.code@20210929",
      "transform": {
        "type": "code_system",
        "code_system": "1.2.276.0.76.4.6"
      }
    }
  }
}
```

The corresponding CDA placement is contextual; placeholders in braces name
generated CDA datapoints:

```xml
<!-- Read-only illustration; do not copy this into cda-mapping.json. -->
<manufacturedProduct classCode="MANU">
  <manufacturedMaterial classCode="MMAT" determinerCode="KIND">
    <code code="{UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.code@20210929}"
          codeSystem="1.2.276.0.76.4.6"/>
    <name value="{UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.name}"/>
  </manufacturedMaterial>
</manufacturedProduct>
```

### Review required: three sources, one atomic timing leaf

| Dataset datapoint | Candidate | Evidence | Result |
|---|---|---|---|
| `...anwendungszeiten.startzeitpunkt_der_anwendung` | `UVSubordinateadministration.substanceAdministration.effectiveTime_value_or_nullFlavor@20230130` | `CTX[496] → ARTDECOR_CHOICE(atomic)` | Rule required |
| `...anwendungszeiten.stoppzeitpunkt_der_anwendung` | same | `CTX[496] → ARTDECOR_CHOICE(atomic)` | Rule required |
| `...dosierung.zeitangabe.zeitpunkt` | same | `CTX[525] → ARTDECOR_CHOICE(atomic)` | Rule required |

The effective template describes the leaf as frequency/intake timing. All three
sources are individually datatype-compatible, but they cannot simultaneously
write one atomic `TS`, and the specification does not select an interval,
repetition or precedence interpretation. The runtime correctly reports
`SHARED(3)` instead of choosing by source order.

### Medication fields with no executable target

| Source group | Datapoints | Boundary |
|---|---|---|
| Product form | `darreichungsform` | Richer product structures exist outside the active UV simple branch; no active-profile bridge |
| Ingredient | `wirkstoffname`, `wirkstoffcode`, `arzneilich_wirksamer_bestandteilq`, `wirkstarke` | Historical/IHE structures are not active and no association projects these semantics into UV simple |
| Lot and application interval | `chargennummer`; start/stop are suggestions above | No lot association; start/stop have no distinct interval endpoints in the effective template |
| Instructions | `zusatzliche_hinweise`, `anweisungen_zur_einnahme` | Context reaches the administration, not a unique value-bearing leaf |
| Event and PRN | `ereignis`, `einnahme_bei_bedarf` | No terminology/discriminator bridge; PRN evidence belongs to a legacy, inactive profile |
| Site and method | `korperstelle`, `methode_der_anwendung` | Writable structural possibilities do not establish the active-profile correspondence |
| Dose and rate | `dosismenge_und_einheit`, `kontinuierliche_gabe_rate` | Active UV exposes `doseQuantity` and `rateQuantity`, but the current source normalizer does not preserve unit/range semantics and no unambiguous bridge exists |
| Reason | `begrundungstext`, `kodierte_begrundung` | No active relationship connects these sources to an indication/reason observation |

There are 16 medication datapoints in the no-target category. The three timing
datapoints are counted separately as suggestions. A general CDA model exposing
form, ingredient, lot, quantity, site or reason slots is physical evidence
only; it does not make those slots part of this active representation.

Optional unmapped medication leaves are omitted. No text, unit, interval,
timestamp or code is synthesized. Required nullable leaves follow the reviewed
mapping-wide completion rule; a required non-nullable leaf remains a validation
error.

## Secondary ICD-10 diagnosis

Dataset datapoint:
`abschlussdiagnosen.abschlussdiagnose.icd10_sekundardiagnose`.

The selected transaction gives this source cardinality `0..1`; historical
project material has also exposed `0..*`. The active Problem Observation has
one required `CD` value and supplies no distinct secondary-code slot or explicit
relationship.

| Possible representation | Evidence | Decision |
|---|---|---|
| Reuse `Problemobservationeddiagnosis.observation.value@20170213` | Weak lineage reaches the target already selected for primary ICD; runtime reports `WEAKER_SHARED_TARGET(abschlussdiagnosen.abschlussdiagnose.icd10)` | Reject direct assignment; it would overwrite or ambiguously merge the primary code |
| Write `value/translation` | `CD.translation` is physically legal | Reject; translation asserts another coding of the same concept, while this source is a secondary member of a multiply coded ICD-10 diagnosis |
| Create another Problem Observation | CDA can structurally repeat observations | No executable rule; occurrence ownership and the relationship to leading diagnosis, text, certainty and onset are unspecified |

The following would therefore assert semantics the project has not supplied:

```xml
<!-- Rejected illustration: a secondary diagnosis is not proven to be a translation. -->
<value xsi:type="CD" code="{primary ICD-10}">
  <translation code="{secondary ICD-10}"/>
</value>
```

`DEC-009` remains open. The field stays `null`; absence emits no secondary
diagnosis occurrence and never mutates the primary diagnosis.

## Seven smaller residuals

| Dataset datapoint | Status | Closest evidence | Decision |
|---|---|---|---|
| `hauptkostentrager.versicherungsverhaltnis.identifikation` | No target | Current insurer participant; historical `HeaderParticipantKostentraeger` | No formal edge from selected concept to the historical insured-number slot |
| `notfallanamnese.beschwerden_bei_vorstellung.ereigniseintritt` | No target | CEDIS Problem Concern Act `effectiveTime/low` | The source is general event/symptom onset; the candidate is narrower CEDIS concern onset |
| `diagnostik.bildgebende_diagnostik.magnetresonanztomographie.untersuchungsregion` | No target | Diagnostic-results section and inline choice list | No reachable MRI entry or formal region-to-statement crosswalk |
| `diagnostik.bildgebende_diagnostik.rontgen.untersuchungsregion` | No target | Several fixed-code X-ray statements | Partial label/code resemblance does not define repeat, selection or coalescing semantics |
| `dokumentationsinformationen.berechnete_zeitintervalle.zeit_bis_zum_export` | No target | Exact draft FLN-134 template outside active closure; weak lineage to encounter start | A duration in hours is not an encounter timestamp |
| `dokumentationsinformationen.datenbereitstellung.name_des_edis` | No target | Exact draft FLN-135 template outside active closure | Intended representation is known but not reachable from the selected document |
| `dokumentationsinformationen.datenbereitstellung.version_des_edis` | No target | Exact draft FLN-136 template outside active closure | Intended representation is known but not reachable from the selected document |

### Insurance identifier

The selected parent context is the newer `hauptkostentrager` participant
template `1.2.276.0.76.3.1.195.10.4`. Its `scopingOrganization/id` identifies
the insurer organization, not the insurance relationship or insured person.
A separate reachable historical template `1.2.276.0.76.10.2022` describes
`associatedEntity/id` as insured-number identifiers:

```xml
<!-- Active mapped context: organization identifier, not insured number. -->
<participant>
  <associatedEntity>
    <scopingOrganization>
      <id root="{insurer organization identifier}"/>
    </scopingOrganization>
  </associatedEntity>
</participant>

<!-- Historical evidence: physically suitable, but no formal selected-concept edge. -->
<participant>
  <associatedEntity>
    <id extension="{insured number}"/>
  </associatedEntity>
</participant>
```

The historical template has static associations to older AKTIN concepts named
“Versicherungsnummer”; the selected concept 21582 follows a separate
specification lineage. Similar wording cannot join those identities.

### Event onset and imaging regions

`ereigniseintritt` covers a general event or symptom onset, including such
different cases as stroke, myocardial infarction, accident and resuscitation.
Mapping it to the CEDIS concern `effectiveTime/low` would narrow that domain and
could activate an otherwise incomplete CEDIS occurrence. The neighbouring
free-text and CEDIS complaint sources do map into the CEDIS observation, but
proximity does not extend their association to this timepoint.

The MRI and X-ray region domains are inline logical choice lists, not explicit
ValueSet bindings. MRI has a general SNOMED MRI code in project commentary but
no reachable MRI entry target. The X-ray section contains separate fixed-code
statements for chest, spine, pelvis, limb and general studies, each with its own
required payload. Some source labels include code-like synonyms for chest,
whole spine and pelvis, but no code system or formal mapping turns those labels
into complete statement-selection rules. Existing derived booleans already
activate several of these entries, so mapping the raw region field would also
need explicit coalescing and repetition semantics.

### Export interval and EDIS metadata

The project evidence defines exact intended draft entry templates, but the
selected representing document does not reference them:

| Intended source | Project-evidence template | Fixed code and value |
|---|---|---|
| Zeit bis zum Export | `1.2.276.0.76.3.1.195.10.85@2024-05-24` | `FLN-134`; `PQ` in hours |
| Name des EDIS | `1.2.276.0.76.3.1.195.10.86@2024-05-24` | `FLN-135`; `ST` |
| Version des EDIS | `1.2.276.0.76.3.1.195.10.87@2024-05-24` | `FLN-136`; `ST` |

These definitions prove an intended representation exists; they do not make it
writable in the active CDA closure. The export interval's weak alternatives to
encounter `effectiveTime/low` are also datatype- and meaning-incompatible: a
quantity in hours is not an admission timestamp. Generic CDA device software
or model-name structures do not reproduce the two explicitly defined EDIS
fields and are not an active substitute.

## Final decision and required upstream evidence

No residual candidate passes both the physical and semantic gates, so coverage
remains 93/120. Future work can safely reopen a boundary when the effective
project supplies one of the following:

- an allergy concern-onset timestamp or a revised template rule that permits an
  unknown value;
- active medication associations/templates that distinguish interval,
  frequency, dose, rate, product detail, PRN, site and reason semantics while
  preserving source units and ranges;
- an explicit secondary-ICD occurrence/relationship rule;
- formal selected-concept associations for insured number, general event onset
  or imaging region;
- inclusion of templates `.10.85`, `.10.86` and `.10.87` in the selected CDA
  document closure.

Until then, `null` prevents plausible-looking but clinically false CDA output.
