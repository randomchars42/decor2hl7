# External artifact phase 1

Date: 2026-08-30

## Status

This is an evidence snapshot for open decision `DEC-012`. The mechanism and
the first catalog entries require review; this document does not declare them
accepted project policy.

## Problem

The selected ART-DECOR closure contains identifiers whose defining content is
maintained by IHE, HL7, WHO, IANA, terminology publishers or local standards
pages rather than by the queried ART-DECOR repository. Treating every failed
request as either a complete missing file or an invitation to crawl arbitrary
websites loses the distinction between:

- a required complete structural or terminology dependency;
- an optional display/reference CodeSystem;
- a public but externally maintained artifact;
- a specification-only marker without an independent machine artifact;
- a malformed or misclassified identifier.

## Phase-1 boundary

The exact-identity source catalog gains only two modes:

1. `builtin`: a small reviewed XML artifact is installed with the package,
   verified by its catalog checksum and requested identity, copied into the
   release cache, and recorded with origin/source/completeness provenance.
2. `waiver`: a cited decision settles repeated retrieval attempts but has no
   compiler artifact. Its status is `waived`, never `ok`, and required uses
   remain degraded.

No generic HTTP downloader, FHIR terminology client, MediaWiki extractor, PDF
scraper or licensed terminology importer is introduced in this phase.

## Initial catalog entries

### Metastasis location CodeSystem

Identifier: `1.2.276.0.76.5.401`

Source:
`https://wiki.hl7.de/index.php?title=cdapad%3AMetastasen-Section_%28Template%29`

The page exposes ten symbols with German/English labels: `PUL`, `OSS`, `HEP`,
`BRA`, `LYM`, `OTH`, `MAR`, `PLE`, `ADR`, and `SKI`. They are packaged in
`retrieval/external/metastasis-location.xml` and provisionally labelled
`complete`. Review must confirm that the table is the intended complete
CodeSystem rather than only the value domain used by that template, and must
confirm redistribution terms.

### IHE split-dose marker

Identifier: `1.3.6.1.4.1.19376.1.5.3.1.4.9` (`dynamic`)

Source:
`https://www.ihe.net/uploadedFiles/Documents/Pharmacy/IHE_Pharmacy_Suppl_MTP_Rev1.3_TI_2017-10-11.pdf`

IHE describes the OID as a split-dose form of Medication Entry using
subordinate `substanceAdministration` acts. No independent template body was
located. The initial catalog therefore records a provisional `spec-only`
waiver rather than fabricating an expanded ART-DECOR template. Review must
decide whether this genuinely adds no independent constraints or whether a
curated structural extract is required.

## Still unresolved

- IHE Medicine Entry `1.3.6.1.4.1.19376.1.9.1.3.1`: the catalog retains the
  existing `ch-pharm-` resolution hint, but no external artifact is promoted.
- AKTIN/DIVI CodeSystem
  `1.2.276.0.76.3.1.195.5.53@2019-12-30T00:00:00`: observed code fragments do
  not prove a complete exact expansion.
- Licensed, large or algorithmic systems such as SNOMED CT, RxNorm, ICD and
  UCUM need publisher/local-file semantics, not bundled copies.
- The malformed SNOMED OID and dataset/transaction classification errors need
  diagnostics rather than external artifacts.

## Cache behavior verified by tests

- A builtin is materialized under `fetch --offline` with zero HTTP calls.
- Deleting `manifest.json` while leaving valid deterministic files under
  `spec/` causes the manifest to be rebuilt and files to be reused.
- A builtin reconstructed after manifest deletion recovers its external origin,
  completeness, source and package checksum from the durable catalog.
- A waiver remains settled but non-successful.

The cache reconstruction guarantee does not bless arbitrary orphan files:
payload parsing, requested identity, exact static revision and known/catalog
checksums remain validation gates.
