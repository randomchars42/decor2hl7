# ART-DECOR examples are not CDA defaults — 2026-09-06

## Finding

The reference `2026.1.2` / `notaufnahmeregister--60` compiled CDA model
contained 34 `compiled_default` values copied from neutral ART-DECOR examples.
They included document and clinical values such as administrative gender,
pregnancy status, transport/referral values, eye laterality, certainty, and 14
diagnostic `OPB` findings ("ohne path. Befund"). Exact terminology membership
made those values legal possibilities; it did not make them true defaults.

The MRI template `1.2.276.0.76.10.4058@2015-09-18` demonstrates the problem.
Its example contains:

```xml
<value xsi:type="CE"
       code="OPB"
       codeSystem="1.2.276.0.76.3.1.195.5.51"
       displayName="ohne path. Befund"/>
```

The executable constraint separately requires one `CE` value bound to Finding
situation ValueSet `1.2.276.0.76.11.51@2015-11-17`. It does not fix `OPB`. The
ValueSet contains both `PB` and `OPB` plus missing-information exceptions, and
the template's static association identifies the value as the historical
clinical datapoint "MRT opB". The current dataset field
`diagnostik.bildgebende_diagnostik.magnetresonanztomographie.untersuchungsregion`
instead contains body-region options and has no formal association to that
finding value.

DECOR-core 2.2.28 supplies the decisive format evidence. `DECOR.xsd` defines
`example/@type` with default `neutral` and describes it only as the alternative
to marking an instance fragment `valid` or `error`. It assigns no fixed-value or
default-value semantics to the fragment.

## Correction

The CDA compiler no longer scans examples for coded defaults or emitted display
metadata. New targets contain no `compiled_default` property and the retained
top-level compatibility count is zero. The renderer ignores that property in
older artifacts, and the presence-target completeness check no longer treats it
as supplied content.

Real construction sources remain unchanged: fixed ART-DECOR constraints,
normative CDA XSD defaults, compiler-owned system roles, mapped runtime values,
and reviewed `target_defaults`. A required but non-mandatory leaf that remains
empty uses the configured null flavor. For a polymorphic CDA `ANY` particle,
the renderer now includes the concrete compiled datatype on both generic and
reviewed null-flavor completion. The MRI sibling therefore becomes:

```xml
<value xsi:type="CE" nullFlavor="NI"/>
```

rather than an assertion that the examination had no pathological finding.

Mandatory targets that prohibit null flavor continue to fail rather than
inventing a value.

## DEC-018 boundary

DEC-018 is a distinct example-derived mechanism. It generates repeated allergy
occurrences whose `A07AA` and `V08` discriminator constants come from exact
neutral example captions and ValueSet members; it does not use
`compiled_default`. This correction leaves that accepted behavior unchanged so
the default-value fix cannot silently remove two reviewed mappings. The broader
question—whether examples may ever provide executable mapping constants—remains
an explicit follow-up in `docs/known-issues.md`.

## Verification scope

Regression coverage proves that:

- an admitted example code does not become a compiled default;
- an example cannot select one of several allowed template codes;
- an older injected `compiled_default` is ignored by rendering and presence
  completeness;
- generic and reviewed null-flavor completion retain the concrete `xsi:type`;
- explicit mapped values and real single-code template constraints still emit.
