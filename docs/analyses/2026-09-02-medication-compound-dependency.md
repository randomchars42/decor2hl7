# Medication mapping and compound-datatype dependency

Date: 2026-09-02

Status: implemented and verified on the pinned local reference snapshot.

## Scope and authority

This analysis continues the medication boundary review recorded in
[`2026-09-02-residual-mapping-boundaries.md`](2026-09-02-residual-mapping-boundaries.md)
and applies the concrete correction identified in
[`2026-09-02-decor-core-validation-follow-up.md`](2026-09-02-decor-core-validation-follow-up.md).
It uses the local `test-workplace` release `2026.1.2`, transaction
`notaufnahmeregister--60`, transaction effective date
`2026-03-25T00:00:00`, and its pinned `spec/` closure. The active medication
templates are:

| Role | Exact template |
|---|---|
| Medication section | `1.2.276.0.76.3.1.195.10.64` |
| Medikation | `1.2.276.0.76.3.1.195.10.67@2023-12-03` |
| UV Medication Information (simple) | `2.16.840.1.113883.10.21.4.10@2021-09-29T19:15:16` |
| UV Subordinate Substance Administration | `2.16.840.1.113883.10.21.4.6@2023-01-30T09:36:00` |

ART-DECOR associations and exact template constraints establish mapping
semantics. The pinned CDA/RIM and HL7 V3 datatype material establishes physical
structure. The DECOR-core rule `@nullFlavor or hl7:event` establishes that a
non-null `EIVL_TS` cannot consist of an offset alone. Physical availability,
datatype compatibility or a similar label does not by itself establish a
source-to-target correspondence.

## Coverage after correction

The clean build from `aktin.json` plus the local specification closure reports:

```text
Model: 120 datapoints · ✓ mapped 92 dp → 94 leaves · ! suggested 5 dp → 5 leaves · × no target 23 dp · ○ no source 359 leaves
```

The change is one deliberate downgrade from the dated post-PR #20 snapshot:
medication offset moves from mapped to suggested. No target is removed from the
compiled CDA model, and no new semantic mapping is claimed.

Medication itself partitions into 25 datapoints:

| Status | Count | Meaning |
|---|---:|---|
| Mapped | 5 | Executable mapping and occurrence semantics are proven |
| Suggested | 4 | Three sources collide on one atomic time leaf; offset lacks its required event |
| No target | 16 | No unique executable active-profile correspondence is established |

## Executable medication mappings

| Name in dataset | `model.json` datapoint | `cda-mapping.json` target | Status and evidence |
|---|---|---|---|
| Arzneimittel-Name | `masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelname` | `UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.name` | Mapped; static association projected to the unique common CDA/RIM slot |
| Arzneimittel-Code | `masnahmen.medikamentose_therapie.medikation.medikament.arzneimittel.arzneimittelcode` | `UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.code@20210929` | Transform; static association plus the declared open code system |
| Sequenznummer | `masnahmen.medikamentose_therapie.medikation.dosierung.sequenznummer` | `Medikation.sequenceNumber` | Mapped; predicate-aware ART-DECOR choice overlay |
| Freitext | `masnahmen.medikamentose_therapie.medikation.dosierung.freitext` | `Medikation.text` | Mapped; static association projected to the common slot |
| Art der Anwendung | `masnahmen.medikamentose_therapie.medikation.dosierung.art_der_anwendung` | `Medikation.routeCode` | Mapped; static association projected to the common slot |

The existing `for_each` remains necessary: one repeated source medication owns
one medication `entry`, while the section is shared. None of these five
decisions is changed by the compound timing rule.

## Review required

| Dataset datapoint | Candidate target | Evidence | Why not executable |
|---|---|---|---|
| `masnahmen.medikamentose_therapie.medikation.anwendungszeiten.startzeitpunkt_der_anwendung` | `UVSubordinateadministration.substanceAdministration.effectiveTime_value_or_nullFlavor@20230130` | `CTX[496] → ARTDECOR_CHOICE(atomic)` | Shares one atomic `TS` with two other source meanings; no interval/precedence rule |
| `masnahmen.medikamentose_therapie.medikation.anwendungszeiten.stoppzeitpunkt_der_anwendung` | same | `CTX[496] → ARTDECOR_CHOICE(atomic)` | Same three-way collision |
| `masnahmen.medikamentose_therapie.medikation.dosierung.zeitangabe.zeitpunkt` | same | `CTX[525] → ARTDECOR_CHOICE(atomic)` | Same three-way collision |
| `masnahmen.medikamentose_therapie.medikation.dosierung.zeitangabe.ereignisbezogene_wiederholung.offset` | `UVSubordinateadministration.substanceAdministration.effectiveTime_xsi_type_EIVL_TS.offset` | `CTX[527] → RELATED_LABEL(Offset) → CDA_DESCENDANT` | Non-null `EIVL_TS` also requires `...effectiveTime_xsi_type_EIVL_TS.event@20230130`; no source mapping supplies it |

### Offset configuration consequence

The offset candidate remains visible with STRONG evidence, but the generated
proposal now contains:

```json
{
  "fields": {
    "masnahmen.medikamentose_therapie.medikation.dosierung.zeitangabe.ereignisbezogene_wiederholung.offset": null
  }
}
```

`mapping-audit.json` records
`REQUIRED_COMPANION(UVSubordinateadministration.substanceAdministration.effectiveTime_xsi_type_EIVL_TS.event@20230130)`.
The source event concept 528 describes values such as morning, noon, evening
and night, but supplies no proven crosswalk to the target TimingEvent domain.
An event code is therefore not inferred from labels.

The candidate may reopen only when the same source occurrence can supply both a
proven TimingEvent representation and the offset with valid quantity/unit
semantics. A companion from another repeated medication occurrence is not
sufficient.

## Medication datapoints with no executable target

| Source area | Datapoints | Current boundary |
|---|---|---|
| Product form | `darreichungsform` | Richer product structures are outside the active UV simple branch; no active-profile bridge |
| Ingredient and strength | `wirkstoffname`, `wirkstoffcode`, `arzneilich_wirksamer_bestandteilq`, `wirkstarke` | Historical/IHE structure does not establish the active UV correspondence |
| Lot | `chargennummer` | No source association to the available lot slot |
| Instructions | `zusatzliche_hinweise`, `anweisungen_zur_einnahme` | Context reaches the administration, not a unique value-bearing leaf |
| Event and PRN | `ereignis`, `einnahme_bei_bedarf` | No TimingEvent/discriminator bridge; PRN evidence belongs to an inactive legacy profile |
| Site and method | `korperstelle`, `methode_der_anwendung` | Structurally possible slots do not prove the active-profile semantics |
| Dose and rate | `dosismenge_und_einheit`, `kontinuierliche_gabe_rate` | Active UV exposes `doseQuantity` and `rateQuantity`, but no formal source bridge selects them; source quantity normalization also does not yet preserve every unit/range form |
| Reason | `begrundungstext`, `kodierte_begrundung` | No active relationship connects these sources to a reason/indication statement |

This result supersedes the earlier working estimate that richer datatype
expansion alone might recover dose, rate, PRN, body site, reason, ingredient or
form. Expansion proves that slots exist; it does not prove what the source means
in the active profile.

## Implemented generic rule

The implementation contains no medication concept, field name, template OID or
XPath exception:

1. the HL7 datatype policy declares required parts of a non-null compound value;
2. CDA compilation resolves those parts through transparent template/include
   wrappers and stores concrete `non_null_requires` target identities;
3. mapping proposal generation retains the primary evidence but blocks an
   executable selection until a required target or descendant is also selected;
4. `check-cda-mapping` rejects an incomplete manually reviewed mapping; and
5. rendering validates populated companions occurrence by occurrence after
   runtime completion.

A compound value carrying `nullFlavor` is not a non-null value and is exempt.
A required template child is intrinsically present for every active parent
occurrence. The implementation is a bounded encoding of the verified EIVL rule,
not an implementation of the complete deferred DECOR-core or CDA validation
stack in DEC-019.

## Verification

The regression test compiles an EIVL timing structure through a transparent
contained template, verifies the generated dependency metadata, proves that an
offset-only proposal remains `null`, checks static rejection of a manual
offset-only mapping, checks render-time rejection, proves event-plus-offset
success, and verifies that a missing event in the second repeated occurrence is
reported.

The clean reference build completed with 308 reachable templates, 24,940
physical named targets, 94 logical mapped CDA datapoints, 21 unavailable
artifacts and one unresolved CDA reference. The degraded artifacts are the same
documented snapshot boundary; they were not replaced by other revisions.

## Reopening criteria

Additional medication mappings require one of the following specification
changes or reviewed rules:

- an exact active-profile association or equivalent formal bridge for product,
  ingredient, lot, dose, rate, PRN, site, method or reason;
- an explicit start/stop/administration-time representation that resolves the
  current atomic-target collision;
- a source-to-TimingEvent terminology correspondence plus an offset
  representation that preserves quantity, unit and range semantics; or
- a reviewed semantic transform whose clinical meaning and occurrence behavior
  are explicit and testable.

Until then these fields remain suggested or unmapped; no timestamps, units,
codes, precedence rules or clinical relationships are invented.
