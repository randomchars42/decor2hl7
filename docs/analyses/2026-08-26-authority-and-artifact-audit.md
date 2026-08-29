# decor2hl7: transaction, CDA, and terminology authority audit

Date: 2026-08-26

## Outcome

The fetched XML is sufficient to parse the selected transaction and almost all of the reachable CDA closure. The transport dictionary is incorrect because the model flattens two different semantic layers into one `values` collection:

- the source concept's logical choices (`Bodentransportmittel`, `Lufttransportmittel`, `Ohne`); and
- the 2026 transaction's formal coding override (`KTW`, `RTW`, `NAW/NEF/ITW`, `RTH/ITH`, `NA`, `OTH`).

Those collections must not be unioned. For the selected transaction, the formal transaction binding and the selected CDA target both use value set `1.2.276.0.76.11.41@2015-11-17T00:00:00`. The current source value set `...11.41@2024-02-14T09:42:48` is useful lineage evidence, but it is not the authoritative output domain for this transaction.

This also corrects the apparent provenance: `Bodentransportmittel` and `Lufttransportmittel` are present in the Notfalldokumentation 2025.1 source concept. The Notaufnahmeregister Transitionsversion 2026 transaction supplies the local override to the legacy 2015 value-set revision.

## Pinned scope

| Role | Selected artifact |
|---|---|
| Source dataset | `2.16.840.1.113883.2.6.60.3.1.9@2023-11-20T00:00:00`, version label `2025.1` |
| Transaction | `2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`, version label `2026` |
| Representing CDA template | `1.2.276.0.76.3.1.195.10.93@2026-03-25T11:04:07` |
| Pinned project snapshot | `2026-04-27T18:50:33` |
| Live project XML | Fallback evidence only; it must not override the pinned selection |

The resolved transaction XML explicitly says that it is a transaction-filtered dataset view, that inheritances have been resolved, and that value sets are embedded for reference. Its calculated XPath values are only starting points, not executable truth.

## XML and closure results

- All 431 XML files in `data.zip` are well-formed XML; there are no parse failures.
- Twenty-nine fetch responses are empty `<result/>` documents. Only two of them are reachable from the selected CDA template closure.
- The resolved transaction XML contains 144 selected concepts directly: 49 groups and 95 items.
- One selected `contains` relationship imports the medication subtree `2.16.840.1.113883.2.6.60.3.2.10.1` from the already-fetched IOPCDE reference. It adds 33 concepts.
- The complete compiled transaction therefore contains 177 datapoints: 57 groups and 120 fields.
- Terminology parsing found 342 exact value-set revisions. Revisions are keyed by `(OID, effectiveDate)` in the current build.
- The selected CDA closure contains 304 reachable templates, 5,532 named targets, 1,009 renderable targets, and 13 assertions.
- The current source package's 69 unit tests pass. The mixed-domain defect is semantic and is not covered by those tests.

## Correct authority model

Authority must be decided per property. A single global “primary dataset” flag is too coarse.

| Property | Authority | Fallback rule |
|---|---|---|
| Selected concepts, cardinality, conformance, representing template | Exact selected transaction | None |
| Field structure and description | Resolved transaction concept | Follow identity lineage only when the property is absent |
| Formal field terminology binding | Transaction-local `terminologyAssociation` | Source dataset binding only when the transaction has no binding |
| Allowed output codes | Exact bound value-set revision and code-system revision | Never merge a different revision |
| Logical choices and labels | `valueDomain/conceptList`, including option IDs and exceptions | Presentation/semantic evidence only; never add them to the formal code domain |
| CDA structure, cardinality, datatype, fixed values | Exact reachable template closure | Pinned downloaded templates first; older/live material only for a missing exact property |
| CDA vocabulary | `vocabulary/@valueSet` plus exact `@flexibility` | OID-only equality is insufficient |
| Older datasets, inherited concepts, live project | Lineage and review evidence | Missing-property-only; never add children or values already defined by the selected transaction |

A configurable selection should therefore pin the transaction and template and expose independent policies such as `terminology: transaction`, `fallback: missing-property-only`, and `conflict: error`. Selecting an alternative transaction can change those authorities; enabling a fallback must not mean set union.

## Transport trace

### Dataset side

`administrative_aufnahmeinformationen.transport.transportmittel` is concept `2.16.840.1.113883.2.6.60.3.2.9.20139`.

Its logical `valueDomain/conceptList` contains:

- `Bodentransportmittel`
- `Lufttransportmittel`
- `Ohne`

The source dataset associates that concept list with the 2024 SNOMED-based value-set revision. The selected 2026 transaction overrides the list binding to:

`1.2.276.0.76.11.41@2015-11-17T00:00:00`

That formal value set contains:

| Display | Code | Code system |
|---|---|---|
| KTW | `1` | `1.2.276.0.76.3.1.195.5.41` |
| RTW | `2` | `1.2.276.0.76.3.1.195.5.41` |
| NAW/NEF/ITW | `3` | `1.2.276.0.76.3.1.195.5.41` |
| RTH/ITH | `4` | `1.2.276.0.76.3.1.195.5.41` |
| Ohne | `NA` | `2.16.840.1.113883.5.1008` (NullFlavor) |
| Andere | `OTH` | `2.16.840.1.113883.5.1008` (NullFlavor) |

### CDA side

The exact template path is:

`10.93@2026-03-25` → section `10.3045@2025-12-01` → entry `10.4037@2015-03-03` → `hl7:value` (`CV`)

The `hl7:value` vocabulary is also pinned to `1.2.276.0.76.11.41@2015-11-17T00:00:00`. The transaction and CDA output constraints therefore agree exactly.

### Implementable rule

For this transaction, only the six formal legacy values/codes are automatically executable. `Bodentransportmittel` and `Lufttransportmittel` must not be emitted as peer canonical values and must disappear from generated code defaults.

If an input source actually supplies the coarser 2024 domain, that is a separate source-to-transaction crosswalk:

- ground transport cannot select KTW versus RTW versus NAW/NEF/ITW and is lossy/one-to-many;
- air transport to RTH/ITH is a plausible candidate, but the selected transaction does not provide an explicit option-level code association after its override;
- such rules must be explicit and review-required, not inferred by label similarity.

If input supplies the formal codes `1`, `2`, `3`, `4`, `NA`, or `OTH`, the transformation is identity coding and is executable.

## Parser defects causing the current result

| Area | Current behavior | Required behavior |
|---|---|---|
| Logical domain | Keeps labels but drops option concept IDs and exception semantics | Preserve each option as `{concept_id, label, exception, synonyms}` |
| Terminology associations | Reads only associations on the field concept itself | Preserve list-level and option-level associations, transaction scope, code, code system, value set, and effective dates |
| Field values | Unions formal value-set members with logical labels using `setdefault` | Store `logical_domain` and `terminology_binding` separately |
| Code defaults | Accepts every member of the union | Generate defaults only from the selected formal binding; add aliases only when a unique explicit association proves them |
| CDA vocabulary | Stores the value-set OID but discards `vocabulary/@flexibility` | Store and compare the exact value-set revision |
| Mapping executability | OID equality can make a value-set mapping actionable | Require compatible exact revisions/code systems and a lossless transform |
| Draft 0.14.1 | Keyed value sets by OID and used first-seen `setdefault` | The current `(OID,effectiveDate)` keying is correct and must be retained |

Recommended model shape:

```json
{
  "logical_domain": {
    "options": [
      {"concept_id": "...", "label": "...", "exception": false}
    ]
  },
  "terminology_binding": {
    "value_set": {"id": "...", "effective_date": "...", "source": "transaction"},
    "values": [
      {"code": "...", "code_system": "...", "display_name": "..."}
    ],
    "option_mappings": []
  },
  "conflicts": []
}
```

CDA targets need `vocabularies: [{value_set, flexibility, codes}]` rather than an OID-only list.

## Semantic audit triggers

Eight fields have different logical labels/member sets and formal value-set labels/member sets. This is an audit trigger, not automatically an error: some differences are translations or display-name changes, while others are real coverage gaps.

| Field | Interpretation |
|---|---|
| `administrative_aufnahmeinformationen.transport.transportmittel` | Hard version/domain conflict; no option-level codes remain in the selected transaction override |
| `ersteinschatzung...mtsprasentationsdiagramm` | Seven renamed labels and two additional formal neonatal/infant values; code input can be authoritative, label-only input needs an explicit alias table |
| `notfallanamnese...beschwerden_bei_vorstellung_cedis` | Eight renamed/changed logical labels and ten differing formal members; do not infer by labels |
| `notfallanamnese.unfallanamnese.unfallursache` | German/English display differences; all four options have explicit code associations and can be resolved by option ID |
| `notfallanamnese.unfallanamnese.unfallart_trauma_register` | One German/English display difference; all 18 options have explicit code associations |
| `notfallanamnese.verdacht_auf_alkohol_drogen_medikamenteneinflussq` | German/English display differences without direct option-level associations; prefer actual input codes |
| `masnahmen.isolation.isolation_begrundung` | Ten options have explicit codes; `Keine Isolation` has no code association while formal vocabulary adds RSV |
| `administrative_verlegungsentlassungsinformationen.typ_entlassung` | Transaction overrides to legacy `...11.56@2015-11-17`; three newer destinations are absent from that formal domain and therefore not automatically writable to the selected CDA vocabulary |

Three fields have explicit transaction-local value-set overrides relative to the 2025.1 source dataset:

1. `administrative_aufnahmeinformationen.zuweisung_zur_notaufnahme.zuweisung`: `...11.42@2015-09-18` instead of `...11.42@2024-02-14`.
2. `administrative_aufnahmeinformationen.transport.transportmittel`: `...11.41@2015-11-17` instead of `...11.41@2024-02-14`.
3. `administrative_verlegungsentlassungsinformationen.typ_entlassung`: `...11.56@2015-11-17` instead of the source dataset's `...195.11.7@2024-02-14`.

These overrides are authoritative transaction decisions, not missing downloads.

## Inheritance differences

The transaction declares seven `inheritanceIssues`. They identify deliberate current-versus-inherited differences and must not trigger automatic grafting of old extras:

| Path | Inherited extras | Current extras |
|---|---:|---:|
| `notfallanamnese.unfallanamnese` | 1 | 0 |
| `klinische_basisdaten_patient` | 1 | 0 |
| `klinische_basisdaten_patient.allergien` | 6 | 0 |
| `diagnostik.bildgebende_diagnostik` | 1 | 0 |
| `diagnostik.bildgebende_diagnostik.magnetresonanztomographie` | 1 | 0 |
| `masnahmen.medikamentose_therapie` | 2 | 1 |
| `dokumentationsinformationen.berechnete_zeitintervalle` | 1 | 0 |

The selected transaction remains authoritative: historical extras are provenance and explicit exclusions unless the current concept omits the whole property being inherited.

## Mapping/link status

The present build produces a useful evidence inventory, but its executable count is optimistic until domain/revision compatibility is enforced:

- 177 dataset datapoints total
- 86 CDA-covered, 78 partial, 13 not covered
- items: 59 yes, 56 partial, 5 no
- groups: 27 yes, 22 partial, 8 no
- required items: 16 yes, 13 partial, 0 no
- 67 evidence-linked items
- 53 executable proposals before the stricter terminology checks described above
- evidence confidence: 22 strong, 57 medium, 7 weak, 91 none

Each human-reviewable mapping record should contain:

1. dataset path, concept ID, datatype, cardinality, and transaction selection;
2. logical options separately from the formal terminology binding;
3. target template chain, target path/element ID, datatype, cardinality, and exact vocabulary revision;
4. the complete evidence chain (`templateAssociation`, identity lineage, terminology/value-set, or transform);
5. transform class: identity, explicit crosswalk, lossless recode, lossy aggregation/split, or no mapping;
6. machine decision (`executable`, `review-required`, `blocked`) and a concrete reason;
7. artifact provenance for every edge.

This representation lets a reviewer understand and change a rule without reading raw ART-DECOR XML, while still making every rule reproducible.

## Artifacts still needed

### Required to close formal domains

1. Exact code-system definition `1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`, or an already-expanded `1.2.276.0.76.11.53@2015-11-17T00:00:00`. The selected `Typ Verlegung` value set contains an include of the whole code system, so its complete allowed code list cannot currently be enumerated. Explicit option-level associations in the transaction cover the known logical options, but they do not prove the complete value-set expansion.

### Required for strict CDA template closure

2. IHE template `1.3.6.1.4.1.19376.1.5.3.1.4.9` (dynamic), referenced as a missing `SPEC` by the historical split-dose medication template.
3. IHE template `1.3.6.1.4.1.19376.1.9.1.3.1` (dynamic), referenced as a missing `SPEC` by the medication material template.

ART-DECOR returned empty results for both, and the referring templates themselves mark `linkedartefactmissing="true"`. They should be obtained from an authoritative IHE source or explicitly waived with a documented reason; an empty response must never be treated as a template.

### Required for end-to-end validity and source semantics

4. The authoritative input serialization contract: actual field names, repetitions/keys, whether coded values arrive as codes or labels, null representation, identifiers, units, and time precision. The transaction defines clinical semantics, not the producer's physical JSON/CSV contract. The supplied RetrieveTransaction JSON is metadata serialization and can cross-check the XML parser, but it does not replace this input contract.
5. The CDA R2 XSD schema set and the exact ART-DECOR-generated Schematron (or equivalent validator package) for template `10.93@2026-03-25T11:04:07`. The compiled structural checks and 13 extracted assertions are valuable, but schema plus authoritative Schematron are the independent gates needed to claim a valid document.
6. At least one complete representative source record and its accepted reference CDA document. This is needed to verify narrative, identifiers, null flavors, repetition behavior, and rules whose semantics cannot be proved from terminology alone.

No additional historical dataset fetch should be used to “fill” the three transaction overrides or seven inheritance differences. Those are authority decisions, not closure gaps.

## Recommended implementation order

1. Introduce property-level provenance and split logical domains from formal terminology bindings.
2. Preserve option IDs/associations and exact CDA vocabulary flexibility.
3. Rebuild code defaults from formal bindings only; make ambiguity or lossiness a blocking status.
4. Recompute mappings and downgrade any OID-only or revision-incompatible executable proposal.
5. Fetch the one code-system expansion and resolve or formally waive the two IHE base templates.
6. Add the input serialization contract and reference record/CDA pair.
7. Validate generated output in three independent layers: XML/CDA XSD, exact template/Schematron, and source-to-output completeness with no silently dropped relevant datapoints.

The transaction JSON endpoint is useful as a regression fixture after these changes, but the exact resolved XML already contains the decisive transaction-local terminology and template evidence.

