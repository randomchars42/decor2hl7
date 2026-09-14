# Reviewed medication-administration rules

Date: 2026-09-14

## Scope and authority

This review uses the local `2026.1.2` reference workspace and only writable
targets reachable from the exact AKTIN transaction
`2.16.840.1.113883.2.6.60.3.4.60@2026-03-25`:

- [AKTIN transaction instance](https://aktin.art-decor.pub/aktin-cda-ig-20260427T185033/tr-2.16.840.1.113883.2.6.60.3.4.60-2026-03-25T000000._instance.html)
- [Medikation template](https://aktin.art-decor.pub/aktin-cda-ig-20260427T185033/tmp-1.2.276.0.76.3.1.195.10.67-2023-12-03T000000.html)
- [UV Subordinate Substance Administration](https://aktin.art-decor.pub/aktin-cda-ig-20260427T185033/tmp-2.16.840.1.113883.10.21.4.6-2023-01-30T093600.html)
- [CEDIS Problem Concern Act](https://aktin.art-decor.pub/aktin-cda-ig-20260427T185033/tmp-1.2.276.0.76.10.4039-2015-03-03T000000.html)

No material-name, ingredient, generic RIM, or inactive sibling-template target
is introduced.

## Reviewed mappings

1. `Dosismenge und -einheit` maps to
   `UVSubordinateadministration.doseQuantity`. The target is `IVL_PQ`, whose
   scalar representation is legal: a scalar emits `@value` and optional
   `@unit`; a source range emits the compiled `low` and `high` values.

2. `Kontinuierliche Gabe (Rate)` maps to
   `UVSubordinateadministration.rateQuantity`. The source publishes five
   alternative property units: `ml/h`, `l/h`, `µg/h`, `mg/h`, and `g/h`.
   They are an admitted domain, not five constraints and not a fixed `g/h`.
   The compiler now retains all five. Local spelling-to-UCUM normalization is
   configuration (`site.json/input.unit_aliases`), not an AKTIN-specific code
   table: `g / h` → `g/h`, `ml/h` → `mL/h`, `l/h` → `L/h`, and `µg/h` →
   `ug/h` in the reference scenario.

3. `Körperstelle` maps to `Medikation.approachSiteCode`. Its binding to
   `HumanSubstanceAdministrationSite` (`2.16.840.1.113883.1.11.19724`) has
   strength `example`. An exact code supplied by site code mapping is emitted;
   otherwise the source wording is retained as `nullFlavor="OTH"` with
   `originalText`.

4. `(Start)zeitpunkt der Anwendung` maps only to the atomic
   `UVSubordinateadministration.effectiveTime_value_or_nullFlavor` (`TS`). The
   outer Medikation `effectiveTime` is prohibited and is not used. The source
   stop remains deliberately null because this atomic target has no separate
   high/stop slot.

5. `Darreichungsform` conditionally maps to
   `UVSubordinateadministration.administrationUnitCode`. The target binding
   `AdministrableDrugForm` (`2.16.840.1.113883.1.11.14570`) is required and
   contains `APPFUL`, `PUFF`, `SCOOP`, `SPRY`, `DROP`, `NDROP`, `OPDROP`,
   `ORDROP`, and `OTDROP`. Only an exact configured code/system is emitted.
   Uncoded wording is instead appended as `Darreichungsform: …` to
   `Medikation.text`; the required binding is not weakened with `OTH`.

6. Dosage free text, event-offset wording, true `Einnahme bei Bedarf`, reason
   text, coded-reason wording, and uncoded form wording are transformed to
   readable fragments, missing fragments are skipped, and the rest are joined
   in that order with `"; "` into `Medikation.text`. This is the sole active
   portable narrative rule; it does not assert coded equivalence.

7. `Art der Anwendung` and `Methode der Anwendung` coalesce into
   `Medikation.routeCode`, whose `RouteOfAdministration` binding
   (`2.16.840.1.113883.1.11.14581`) has strength `example`. If both normalized
   wordings are equal, one is emitted. If one is absent, the other is used. If
   they differ, `Art der Anwendung` wins and runtime reports a warning. Exact
   configured codes are preserved; otherwise wording uses `OTH` and
   `originalText`.

8. `Ereigniseintritt` provisionally maps to `Problemconcernactcedis.low`. This
   is an explicit reviewed decision pending AKTIN clarification, not a claim
   that the similarly named nested Problem Observation time is selected.

## Deferred timing and explicit nulls

AKTIN's current requested use is medication given, represented here by the
application start. Dosage `Zeitpunkt` and TimingEvent `Ereignis` therefore
remain explicit null selections. Event offset is narrative only; it does not
activate an incomplete EIVL value. A future event mapping can review HL7
TimingEvent `CM` (breakfast), `CD` (lunch), `CV` (dinner), and `HS` (before
extended sleep) for the source labels morgens, mittags, abends, and zur Nacht.
The renderer defect that omitted `xsi:type="EIVL_TS"` for an explicitly selected
ART-DECOR predicate branch has nevertheless been corrected and regression
tested.

The reference mapping also records deliberate null decisions for secondary
ICD-10 and documentation start. AKTIN says secondary ICD-10 is not transmitted.
For documentation start, AKTIN confirmed that the concept still exists in the
dataset/transaction but is used by no current template and is not sent
separately. Mapping version 9 stores these rationales in `field_reviews` beside
the actual null selections.

## Executable validation

The authored six-document scenario exercises application start, scalar dose,
rate input `2 g / h` normalized to `2 g/h`, equal route/method coalescing,
body-site original text, true PRN, both reason values, and form narrative
fallback. It emits:

```xml
<effectiveTime value="20260502100700+0200"/>
<doseQuantity value="4" unit="{actuation}"/>
<rateQuantity value="2" unit="g/h"/>
```

The complete scenario passes the pinned CDA/SDTC XSD and generated
Schematron. Focused unit tests separately cover a scalar and range quantity,
the five-unit source domain, site unit aliases, both route conflict outcomes,
narrative concatenation, and EIVL `xsi:type` emission.
