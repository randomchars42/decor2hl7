# Open coded allergy agent mapping

Date: 2026-09-01

## Question

The allergy group already maps structurally to the effective Allergies and
Intolerances section, but `Agens` previously stopped at section context. Is its
empty `conceptList` an unresolved terminology artifact, and can the source value
reach the required allergen code without an allergy-specific mapping rule?

## Source-domain finding

The selected source concept is
`2.16.840.1.113883.2.6.60.3.2.9.21593`. Its inherited PMP definition owns inline
`conceptList`
`2.16.840.1.113883.2.6.60.4.2.3.6124.20170805115646.0` below
`valueDomain type="code"`. The list has no members and no external `ref`.

An ART-DECOR concept list is subordinate to its dataset concept; it is not a
standalone ValueSet with a separate retrieval endpoint. The machine-readable
state is therefore an explicitly empty/open coded domain, not a failed
terminology download. Compilation now preserves:

- list ownership and identifier;
- `status: unconstrained`;
- zero members and zero references;
- `formal_terminology.status: unconstrained`;
- `bound: false`, `complete: true`; and
- no missing ValueSet or unresolved include.

Missing external ValueSets continue to compile as `unresolved` and incomplete.
Populated inline lists remain logical enumerations rather than being promoted to
formal target codes.

## Target evidence

Inside the formally mapped allergy section, the effective Allergy Intolerance
Observation requires
`participant/participantRole/playingEntity/code` with datatype `CE`. It binds
exact ValueSet revision
`1.2.276.0.76.11.52@2015-11-17T00:00:00`, whose fetched definition contains:

| Code | Code system | Display | Role |
|---|---|---|---|
| `ALGN` | `1.2.276.0.76.3.1.195.5.52` | Allergen | admitted member |
| `A07AA` | `2.16.840.1.113883.6.73` | Antibiotika | admitted member |
| `V08` | `2.16.840.1.113883.6.73` | Kontrastmittel | admitted member |
| `OTH` | `2.16.840.1.113883.5.1008` | Andere | exception / null flavor |

The compiled `CE` datatype also supplies the direct `originalText` child and
marks it with `content_role: coded_original_text`. The value-set index now
retains ART-DECOR `exception` entries as well as ordinary concepts.

The generic derivation requires all of the following:

1. the source code domain is explicitly unconstrained;
2. a parent group already establishes one CDA container context;
3. exactly one compatible writable descendant binds one exact ValueSet;
4. that ValueSet contains an explicit `OTH` exception; and
5. the coded target has exactly one compiled `coded_original_text` companion.

The mechanism contains no source path, allergy name, template OID, ValueSet OID,
CDA class or XML leaf constant. If two target descendants satisfy the contract,
neither is selected.

## Runtime representation

The generated `coded_fallback` transform carries the exact target binding and
its non-exception members. A supplied code is retained only when both its code
and code-system pair match one admitted target member. Every other non-empty
source value becomes `nullFlavor="OTH"` and retains its wording as `raw`; the
renderer's existing compiled content role writes that wording to
`originalText`. This target-specific fallback overrides a site's general
unmapped-code flavor, so a target that formally requires `OTH` cannot
accidentally receive `UNK`.

There is no source-to-target ConceptMap. The mapping is therefore classified as
STRONG indirect evidence: the container, target binding, exception and datatype
representation are formal and unique, while an arbitrary source code is not
claimed to be a target terminology member.

## Fresh-snapshot result

The supplied release `2026.1.2` snapshot builds with its pre-existing degraded
state of 21 unavailable auxiliary artifacts and one unresolved CDA reference.
The proposal increases from 73/120 to 74/120 mapped dataset fields (76 logical
CDA datapoints). The gained field is exactly:

`klinische_basisdaten_patient.allergien.agens`
→ `Allergyintoleranceobservation.observation.participant.participantRole.playingEntity.code`

Its persisted audit chain is:

`CTX[10009] → OPEN_CODED_DOMAIN(<owned-list-id>) → VS(<exact-revision>:OTH) → CODED_ORIGINAL_TEXT(<compiled-target>) → UNIQUE_DESCENDANT`

This also remains above the historical 64/120 after PR #9 and 59/120 after the
first model-expansion pass.

## Remaining allergy boundary

`allergie_beschreibung` still needs a reviewed narrative or observation-text
placement. The antibiotic and contrast-agent flags describe derived
diagnosis/disorder assertions (`Z88.1` and `293637006`), not individual
allergenic substances. They remain unmapped until an explicit occurrence and
negation representation can be established; they must not be sent as arbitrary
`playingEntity/code` values.

## Verification

- transaction regression: empty owned list is unconstrained, complete and not
  missing;
- mapping regression: only one `OTH` + `originalText` descendant is selected;
- runtime regression: an unknown agent emits `nullFlavor="OTH"` and source
  wording even when site policy says `UNK`;
- terminology regression: an exact admitted code/code-system pair is preserved;
- full repository suite: 143 tests;
- fresh snapshot: 74/120 proposed fields, 76 logical targets;
- bytecode and whitespace checks pass.

Implementation locations:

- `src/decor2hl7/compile/transaction.py`
- `src/decor2hl7/compile/structural.py`
- `src/decor2hl7/compile/mapping.py`
- `src/decor2hl7/transforms.py`
- `src/decor2hl7/semantics.py`
- `tests/test_core.py`
