# AKTIN medication reviewed-mapping re-evaluation

Date: 2026-09-14

## Question

Which reviewed medication mappings remain defensible when compared directly
with the published transaction instance, and should a CDA/RIM-derived
`manufacturedMaterial/name` leaf be treated as an AKTIN target?

## Exact evidence

The selected release is `2026.1.2`; the transaction is
`2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`. The authoritative
published transaction instance is:

<https://aktin.art-decor.pub/aktin-cda-ig-20260427T185033/tr-2.16.840.1.113883.2.6.60.3.4.60-2026-03-25T000000._instance.html>

Its Medikation entry selects UV Medication Information (simple)
`2.16.840.1.113883.10.21.4.10@2021-09-29T19:15:16`. Under
`manufacturedMaterial`, the published expansion lists required `code`, optional
`translation`, and optional `lotNumberText`. It does not list `name`.

The compiled target
`UVMedicationInformationsimple.manufacturedProduct.manufacturedMaterial.name`
has no ART-DECOR element identifier. Its sole provenance is `cda-rim`, and it is
marked `datatype_derived: true`; it exists because the simple template is open
and the compiler expands the base CDA model. That proves schema-level
writability, but not that AKTIN intended it as the product-name slot for this
transaction.

The source `Arzneimittel-Name` is a product or trade name. Although
`Material.name` is physically compatible, the exact transaction supplies no
selected target-level association or constraint that resolves the intended
representation. The reviewed mapping is therefore removed. The field remains
unmapped rather than being presented as AKTIN-derived intent.

The same published branch explicitly declares `lotNumberText`. The source
`Chargennummer` is defined as “Chargennummer / Losnummer des Medikaments”, so a
manual review can select the exact transaction target without relying on a
generic relationship edge or on the richer, unselected medication-detail
branch. The automatic proposal remains `null`; the recovery overlay records
the reviewed assignment:

```text
Chargennummer → {UVMedicationInformationsimple.lotNumberText}
```

## Other medication mappings

Product code, dosage narrative, route and subordinate sequence number remain
selected: each target is explicitly present in the transaction and its reviewed
source meaning is direct. No additional mapping is selected for pharmaceutical
form, ingredients, strength, start/stop, timing event/offset, PRN, body site,
method, dose, rate, or medication reason. The transaction exposes some
physically compatible leaves, but not enough evidence to choose timing
alternatives, construct subordinate occurrences, or prove terminology and
compound-value semantics without further review.

## Conclusion

The reviewed mapping keeps the same total coverage, 95 of 120 datapoints, by
replacing one doubtful open-template mapping with one exact transaction-listed
mapping. This correction changes reviewed policy only; it deliberately does not
teach the automatic proposal generator to infer mappings from matching labels.
