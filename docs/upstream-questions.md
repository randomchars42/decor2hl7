# Open questions for the AKTIN project upstream

Register of items that cannot be resolved inside this repository because they
need an upstream specification change, a publication, or a clarification from
the AKTIN / HL7 Germany maintainers. Each item states the evidence, what is
blocked, and what would close it.

This is a living register, not a dated snapshot: update an item's status when
upstream answers. Evidence was collected against release `2026.1.2`,
transaction `notaufnahmeregister--60`, repository `d844470`, reference
workspace coverage `95/120` mapped datapoints.

Out of scope here: anything this repository can settle with a reviewed local
mechanism (`DEC-012` builtin/waiver, `DEC-021` attachment, `DEC-022` alias).
Those are tracked in `known-issues.md` and `decisions.md`.

## A. Blocking a selected datapoint

### A1. Which Kostenträger participant is authoritative?

The selected document instantiates **two** participants, both `typeCode="HLD"`
with `associatedEntity/@classCode="POLHOLD"`:

| Template | Document location | Mapped |
|---|---|---|
| `1.2.276.0.76.10.2022` (hl7de-) | `0.14.0` | nothing |
| `1.2.276.0.76.3.1.195.10.4` (AKTIN) | `0.15.0` | the `hauptkostentrager` group |

Do these denote the same payer or two distinct roles? If the same, one of them
should be retired or the relationship declared; if distinct, the second needs a
role discriminator, because the role codes are currently identical.

### A2. Is the dropped `associatedEntity/id` intentional?

`1.2.276.0.76.3.1.195.10.4` re-declares eight of its `SPEC` parent's elements
and keeps their element ids, but omits `associatedEntity/id`
(`2.16.840.1.113883.2.6.77.9.26`, `<desc>Versichertennummern</desc>`) while
keeping the insurance **status** code (`…9.27`). Deliberate narrowing, or an
oversight? The slot still exists physically through CDA/RIM expansion, but
without the declaration it carries no ART-DECOR identity or meaning.

### A3. Versichertennummer has no concept association

Dataset concept `2.16.840.1.113883.2.6.60.3.2.9.21582` "Identifikation" has no
association to element `…2.6.77.9.26`. The only associations to that element
come from `…3.2.2.808` / `…3.2.3.808`, which inherit
`…3.2.1.808` **"Versicherungsnummer"** — a concept family with no `inherit` or
`relationship` edge to `…21582`.

**Blocked:** `hauptkostentrager.versicherungsverhaltnis.identifikation`.
**Closes with:** a terminology/static association from `…21582` to that element,
or an identity edge between the two concept families. Without one, any local
rule would have to match on German label similarity, which this project does
not permit.

### A4. CodeSystem `1.2.276.0.76.3.1.195.5.53@2019-12-30` is unpublished

404 in all eight candidate projects and absent from every located DIVI /
HL7-Germany publication. It is the intension of ValueSet
`1.2.276.0.76.11.53` ("Referral actions"), which is bound on a selected field.

**Blocked:** that field's enumeration stays non-executable; the artifact is the
single remaining `build_degraded` terminology item.
**Closes with:** publishing the code system, or confirming a successor OID.

### A5. Dose and rate have no formal association

The active UV subordinate-administration branch exposes writable
`doseQuantity` and `rateQuantity`. The source rate field declares `g/h` and the
dose field explicitly permits a per-value unit and range, and this repository
now normalizes structured quantities — so the representation blocker is gone.
What is missing is any association, implementation path or crosswalk selecting
those targets.

**Blocked:** `dosierung.dosismenge_und_einheit`,
`dosierung.kontinuierliche_gabe_rate`.
**Closes with:** an upstream association or `implementation/@xpath` declaration
naming `doseQuantity` and `rateQuantity` separately.

## B. Structural gaps in active templates

### B1. Medication timing — is `SXPR_TS` the intended encoding?

`2.16.840.1.113883.10.21.4.6` offers `effectiveTime` as a `max 1` choice of
`TS` / `PIVL_TS` / `EIVL_TS` / `SXPR_TS` — there is **no `IVL_TS` branch** — and
the outer `Medikation` template `1.2.276.0.76.3.1.195.10.67` declares
`<element name="hl7:effectiveTime" conformance="NP"/>`. Start, stop and
frequency can therefore only be carried together through `SXPR_TS/comp`.

Two questions: is that the intended encoding, and how should
`dosierung.zeitangabe.zeitpunkt` be represented? It is a datetime, while
`PIVL_TS/period` is a quantity; treating one as the other would invent
frequency semantics.

**Blocked:** `startzeitpunkt_der_anwendung`, `stoppzeitpunkt_der_anwendung`,
`dosierung.zeitangabe.zeitpunkt` (all three currently share one atomic `TS`).

### B2. MRI region has no target particle

`1.2.276.0.76.10.4058` compiles to exactly one writable leaf (`value`, `CE`).
There is no `targetSiteCode`, no `approachSiteCode` and no region-bearing
particle of any kind, while the dataset carries an MRI Untersuchungsregion
field.

### B3. Event onset — is dropping `low` intended?

`1.2.276.0.76.10.4040` declares `effectiveTime` as `IVL_TS` with a single
required `width` child and no `low` / `high`. The dataset wants an onset
timestamp (`notfallanamnese.beschwerden_bei_vorstellung.ereigniseintritt`), for
which `effectiveTime/low` would be the natural leaf.

### B4. Roughly thirteen medication datapoints have no leaf anywhere

Ingredient name, ingredient code, active-ingredient indicator and strength;
PRN / "as needed"; administration method; body site; medication reason (free
text and coded); intake and additional instructions. These need profiled
template content that does not exist in the active branch — not a mapping rule.

### B5. Imaging region has no bound ValueSet

X-ray and MRI Untersuchungsregion carry 13 and 15 inline logical options
respectively, of which only three (Thorax `30745-4`, entire spine `38008-9`,
pelvis `28561-9`) carry LOINC-shaped synonyms. A bound ValueSet — or an active
region-bearing target per B2 — would remove the need for a reviewed local
crosswalk covering all 13 values plus repeat and conflict behaviour.

### B6. How should secondary ICD-10 be encoded?

Only one diagnosis `observation/value` slot is reachable and it is occupied by
the primary code. A second diagnosis needs an additional observation occurrence
plus relationship semantics, not a `translation`.

### B7. EDIS entries `.10.85` / `.86` / `.87` are not contained

`1.2.276.0.76.3.1.195.10.85`–`.87` are defined in project evidence but the
selected document does not contain them. This repository carries a reviewed
`DEC-021` containment attachment to the open Addendum section
`1.2.276.0.76.3.1.195.10.73`. Declaring the containment upstream would let the
local attachment be withdrawn.

## C. Data-quality reports — no action needed from us

### C1. Two malformed OIDs in the specification

- `2.16.840.1.1138836.96` should be `2.16.840.1.113883.6.96` (SNOMED CT);
- `2.16.840.1.1133883.17.3.10.1.34` should be
  `2.16.840.1.113883.17.3.10.1.34`.

Both are handled locally by reviewed `DEC-022` aliases; the upstream definitions
are untouched and still carry the typos.

### C2. A referenced template revision is published nowhere

`2.16.840.1.113883.10.20.1.53@2005-09-07` (the CCD "Product" `SPEC` parent) does
not exist at that revision in any reachable project. Only `@2007-04-01` from
`ccd1-` is published, and it must not substitute the referenced revision.

### C3. Two OID clusters have no owning project

`2.16.840.1.113883.3.2898` and `2.16.840.1.113883.17.3.10.1` resolve to no owner
in the project directory and are absent from project evidence. Who publishes
them?
