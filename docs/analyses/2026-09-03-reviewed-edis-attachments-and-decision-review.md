# Reviewed EDIS attachments and DEC-015/DEC-020 review

Date: 2026-09-03

## Question and scope

This analysis applies the reviewed CDA-extension mechanism from DEC-021 to the
three EDIS entries that were defined in project evidence but absent from the
selected document closure. It then rechecks whether DEC-015 prevents any
formal static association from becoming executable and explains why DEC-020
keeps the medication event offset unselected.

The reference identity is release `2026.1.2`, transaction
`2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`, and document template
`1.2.276.0.76.3.1.195.10.93@2026-03-25T11:04:07`. Mapping coverage and
conformance remain separate axes: the report-only DECOR source validation
still reports its known upstream findings and does not create or remove a
dataset-to-CDA correspondence.

## Outcome

The exact reviewed attachments are now part of the reference closure. The
completed rebuild reports 311 reachable templates, three reviewed extensions, 25,029
physical named targets and 97 logical mapped CDA datapoints. The reviewed
mapping headline is:

```text
Model: 120 datapoints · ✓ mapped 95 dp → 97 leaves · ! suggested 5 dp → 5 leaves · × no target 20 dp · ○ no source 368 leaves
```

This is a gain of three mapped dataset datapoints over the previous 92/120
state. No existing reviewed selection was replaced.

## Dataset-to-CDA status

| Name in dataset | `model.json` datapoint | `cda-mapping.json` target | Name in CDA template | Status and evidence |
|---|---|---|---|---|
| Zeit bis zum Export | `dokumentationsinformationen.berechnete_zeitintervalle.zeit_bis_zum_export` | `zeit_bis_zum_export.value` | Zeit bis zum Export `value` (`PQ`, fixed `h`) | Mapped; reviewed attachment, exact template/code `FLN-134`, compatible quantity payload |
| Name des EDIS | `dokumentationsinformationen.datenbereitstellung.name_des_edis` | `name_des_edis.value` | Name des EDIS `value` (`ST`) | Mapped; reviewed attachment, exact template/code `FLN-135`, unique required principal payload |
| Version des EDIS | `dokumentationsinformationen.datenbereitstellung.version_des_edis` | `version_des_edis.value` | Version des EDIS `value` (`ST`) | Mapped; reviewed attachment, exact template/code `FLN-136`, unique required principal payload |

The accepted mapping excerpt is:

```json
{
  "fields": {
    "dokumentationsinformationen.berechnete_zeitintervalle.zeit_bis_zum_export": "zeit_bis_zum_export.value",
    "dokumentationsinformationen.datenbereitstellung.name_des_edis": "name_des_edis.value",
    "dokumentationsinformationen.datenbereitstellung.version_des_edis": "version_des_edis.value"
  }
}
```

`observation/text` is not the business payload for `.10.86` or `.10.87`.
Those optional elements are explicitly described as references into the
section narrative and each contains a required `reference`. The business value
is the sibling, mandatory `observation/value` of datatype `ST`. Principal-value
selection now prefers the unique nearest required compatible payload over an
optional narrative or a required descendant inside that optional narrative.
When requiredness does not resolve a choice, the established nearest-target
behavior is retained.

The dataset describes the export interval as full hours and names its unit
`Stunden`; `.10.85` fixes the equivalent UCUM unit `h`. Unit compatibility now
normalizes the singular and plural German labels to `h`. It does not change the
numeric value or introduce a conversion factor.

The resulting placement is represented by these contextual fragments;
placeholders in braces name logical CDA datapoints:

```xml
<!-- Read-only illustration; namespace declarations are omitted. -->
<entry>
  <observation classCode="OBS" moodCode="EVN">
    <templateId root="1.2.276.0.76.3.1.195.10.85"/>
    <code code="FLN-134" codeSystem="1.2.276.0.76.3.1.195.5.98"/>
    <statusCode code="completed"/>
    <value xsi:type="PQ" value="{zeit_bis_zum_export.value}" unit="h"/>
  </observation>
</entry>
<entry>
  <observation classCode="OBS" moodCode="EVN">
    <templateId root="1.2.276.0.76.3.1.195.10.86"/>
    <code code="FLN-135" codeSystem="1.2.276.0.76.3.1.195.5.98"/>
    <statusCode code="completed"/>
    <value xsi:type="ST">{name_des_edis.value}</value>
  </observation>
</entry>
<entry>
  <observation classCode="OBS" moodCode="EVN">
    <templateId root="1.2.276.0.76.3.1.195.10.87"/>
    <code code="FLN-136" codeSystem="1.2.276.0.76.3.1.195.5.98"/>
    <statusCode code="completed"/>
    <value xsi:type="ST">{version_des_edis.value}</value>
  </observation>
</entry>
```

## Reviewed attachment contract

`config/cda-extensions.json` contains three separate attachment records. Every
record fixes the same selected transaction and document, the reachable
Addendum parent
`1.2.276.0.76.3.1.195.10.73@2024-08-15T11:08:15`, parent element
`2.16.840.1.113883.2.6.60.3.9.196`, child particle `hl7:entry`, cardinality
`0..1`, conformance `R`, and a non-empty review reason. The target identities
are exact:

| Template | Effective date | Fixed observation code | Payload |
|---|---|---|---|
| `1.2.276.0.76.3.1.195.10.85` | `2024-05-24T00:00:00` | `FLN-134` | required `PQ`, unit `h` |
| `1.2.276.0.76.3.1.195.10.86` | `2024-05-24T00:00:00` | `FLN-135` | required `ST` |
| `1.2.276.0.76.3.1.195.10.87` | `2024-05-24T00:00:00` | `FLN-136` | required `ST` |

`fetch` obtained both source and analysis representations for all three exact
revisions from project `pmp-`, recorded their checksums, and classified them as
structural build resources. The attachment does not infer containment from
`context="**"`, OID proximity or project membership; it is the explicit
reviewed placement required by DEC-021.

## DEC-015 review

### Result

Retain DEC-015 as accepted and verified without broadening it. The current
active-profile audit found no mapping withheld by its one-slot or
one-nearest-occurrence safeguards.

The audit followed each model field's compiled lineage to every relevant
`staticAssociations/origconcept` record. Counts below are association routes,
not coverage counts; duplicate evidence can describe the same field/target
pair.

| Static-association outcome | Routes | Interpretation |
|---|---:|---|
| Exact active target resolves directly | 60 | DEC-015 projection is not needed |
| One CDA/RIM slot and one nearest active occurrence | 6 | Five distinct field/target pairs are recoverable; one sequence-number route is duplicated in the evidence |
| No CDA/RIM slot | 7 | Five source fields remain unresolved |
| More than one CDA/RIM slot | 0 | No candidate is blocked by slot ambiguity |
| More than one nearest active occurrence | 0 | No candidate is blocked by occurrence ambiguity |

The successful distinct projected pairs are medication product name, product
code, sequence number, dosage narrative and route. Sequence number is selected
through stronger predicate-aware active-template evidence; the projected route
remains corroborating evidence.

The unresolved routes do not expose a common CDA/RIM slot:

| Source field | Referenced legacy representation | Why DEC-015 correctly stops |
|---|---|---|
| Darreichungsform | `pharm:formCode` in `.10.90022` | Pharmaceutical model particle, not a CDA R2/RIM particle; the active UV Medication Information (simple) material has no form leaf |
| Wirkstoffname | `pharm:ingredient/pharm:name` in `.10.90022` | Pharmaceutical ingredient structure has no corresponding active simple-profile occurrence |
| Wirkstoffcode | `pharm:ingredient/pharm:code` in `.10.90022` | Same missing active ingredient structure; two legacy code systems also preclude an implicit code-system choice |
| Wirkstärke | pharmaceutical `capacityQuantity` or ingredient `IVL_PQ` in `.10.90022` | Different compound meanings and no active ingredient-strength occurrence |
| Einnahme bei Bedarf | `precondition/criterion/code` in unattached `.10.90028` | The active template exposes only the open RIM `precondition` container, not a reachable criterion/code leaf; the boolean source supplies no condition code |

Lot number is a different boundary: the active simple medication profile has a
writable `lotNumberText`, but the source concept has no formal association to
it. DEC-015 cannot project an association that does not exist.

Relaxing DEC-015 to match names, relative paths, XML namespaces or merely
compatible datatypes would conflate different information models and could
select absent active-profile structures. A future mapping requires one of:

1. an exact active template that contains the relevant pharmaceutical or
   precondition structure, whether through upstream containment or a separately
   reviewed DEC-021 attachment;
2. a formal source-to-active association or reviewed crosswalk that identifies
   the payload and any code system;
3. explicit occurrence and compound-value rules for ingredients and strength;
   or
4. for PRN, a source condition code/text or a complete fixed target statement
   that a boolean may safely activate through `mode: "presence"`.

## DEC-020 explained

The medication offset leaf is physically real, writable and locally
datatype-compatible. Its audit primary is therefore still shown as a strong
contextual descendant:

```text
CTX[527] → RELATED_LABEL(Offset) → CDA_DESCENDANT
```

It is nevertheless not an executable standalone mapping. The containing HL7
V3 datatype is `EIVL_TS`, whose invariant is `@nullFlavor or hl7:event`.
Consequently every non-null offset occurrence needs a `TimingEvent` event in
the same compound occurrence. The compiled offset target records this as:

```text
non_null_requires:
  UVSubordinateadministration.substanceAdministration.effectiveTime_xsi_type_EIVL_TS.event@20230130
```

The source event field is an unconstrained code concept with no terminology
association, while the target event is a coded `EIVL.event`. Neither the event
code nor a crosswalk can be inferred from the offset. DEC-020 therefore leaves
the field selection `null` and records both `runtime_blocked` and
`required_companions` in `mapping-audit.json`.

The three enforcement boundaries serve different purposes:

1. proposal generation retains the offset as review evidence but does not put
   it into the executable mapping;
2. `check-cda-mapping` rejects a manually selected offset when no configured
   mapping supplies its event companion; and
3. rendering checks each repeated occurrence after assignment, preventing an
   event in one medication/timing occurrence from satisfying another.

A null-flavored whole `EIVL_TS` is exempt because it has no non-null offset. A
mandatory or fixed event child would also satisfy the rule for every active
occurrence. Neither condition applies here. DEC-020 does not hide a leaf or
prevent discovery of a new association; it prevents an incomplete compound
value from being promoted to executable output. Reopening the mapping requires
an exact source-to-`TimingEvent` mapping or a reviewed transform with complete
event-code semantics.

## Verification

- `decor2hl7 fetch` completed with 629 cached/available resources, 62 settled
  missing resources, one waiver, no partial resources and no errors. The 21
  known build-degrading unavailable artifacts remain unchanged.
- `decor2hl7 build` reports 311 reachable templates, three reviewed
  extensions, 97 logical CDA datapoints and a 95/120 proposal.
- `decor2hl7 init-cda-mapping` retained 95/95 accepted mappings, gained none
  implicitly and reported no proposal regression.
- `decor2hl7 check-cda-mapping` passes with 95 mapped fields and one target
  default.
- `python -m unittest discover -s tests` passes all 173 tests.
- A production ingestion and binding probe assigns `0`, the generated EDIS
  name and the generated EDIS version to the three expected `.value` targets
  with no binding problems.
- The isolated full-document fixture remains blocked at the already documented
  Allergy Concern Act `effectiveTime/low`; it generated no CDA and no timestamp
  was invented. The report-only DECOR source result remains 381 errors and
  1,780 warnings from the known upstream/source boundary.

## Evidence

- reference workspace `config/cda-extensions.json`
- reference workspace exact `.10.85`, `.10.86` and `.10.87` source/analysis
  artifacts, closure and manifest
- reference workspace `model/2026.1.2/notaufnahmeregister--60/cda.json`
- reference workspace `model/2026.1.2/notaufnahmeregister--60/mapping-audit.json`
- reference workspace reviewed `cda-mapping.json` and generated mapping guide
- `src/decor2hl7/compile/mapping.py`
- `src/decor2hl7/semantics.py`
- `src/decor2hl7/cda/datatypes.py`
- `src/decor2hl7/validate.py`
- `src/decor2hl7/bindings.py`
- `src/decor2hl7/cda/render.py`
- `tests/test_core.py`
- DEC-015, DEC-020 and DEC-021
