# Phase 7–8 sequenced implementation

Date: 2026-09-04  
Code baseline: local `main` at `d16f986`  
Reference workspace: local AKTIN `2026.1.2`, transaction
`notaufnahmeregister--60`

## Scope and sequencing

This change executed the reviewed phase-7/8 sequence in evidence order:

1. remove unsafe ordinal evidence;
2. add target-neutral scalar/range quantity mechanics;
3. reopen dose/rate only if the repository proves a source-to-target bridge;
4. reopen medication timing only if the repository proves the branch semantics;
5. add X-ray singleton dispatch only after a complete reviewed 13-row
   crosswalk and conflict policy exist.

The first two steps are implemented. The last three deliberately stop at their
evidence gates. No CI workflow or CI configuration changed.

## Ordinal evidence guard

The old option parser accepted the first integer anywhere in a label or
synonym. That produced false ordinal metadata from:

- LOINC-shaped X-ray synonyms such as `30745-4`;
- the physical measurement in both fall-height labels;
- CEDIS classification numbers, including duplicate range-header/member
  prefixes such as `101-150` and `101`.

Extraction now requires either a leading integer that is not the first part of
a hyphenated code, or an integer explicitly accompanied by a rank/score word.
If extracted values collide anywhere in one option list, ordinal metadata is
removed from the entire list. Genuine leading-rank scales such as GCS retain
their ordinal values. Regression tests cover all four cases.

## Structured quantity mechanics

`quantity` input now normalizes to one target-neutral shape:

```json
{"value": 2.5, "unit": "mg"}
```

or:

```json
{
  "low": {"value": 1, "unit": "{tablet}"},
  "high": {"value": 2, "unit": "{tablet}"}
}
```

The parser accepts dot or configured comma decimals and hyphen, en-dash,
em-dash, or `..` range separators. A dataset-declared unit fills a unitless
input; a conflicting explicit unit, differing range units, malformed shape, or
reversed range is rejected. Record validation applies numeric minimum and
maximum constraints to both range bounds. `decimal` and `duration` keep their
existing scalar representation.

The CDA compiler already derives the scalar `value`/`unit` representation of
`IVL_PQ` through the pinned XSD base graph. It now additionally records the
exact writable `low` and `high` target names in that parent representation.
The binding layer projects ranges through those names, including mixed
scalar/range repeated values. The renderer remains unaware of `IVL_PQ`, dose,
rate, medication templates, and XPath suffixes.

The earlier draft recommendation to make `PQ/@unit` globally non-null is
rejected. The pinned CDA R2 schema declares that attribute optional with
default `1`, and active examples include countable administrations without a
unit. Units are preserved and template/field constraints remain enforceable,
but the compiler does not invent a universal requirement.

## Semantic gates

### Dose and rate

The active UV subordinate-administration branch has writable
`doseQuantity` and `rateQuantity` targets. The source rate field declares
`g/h`; the dose field explicitly permits a per-value unit and range. Their
accepted mapping entries nevertheless remain `null`: local transaction and
project evidence provide no formal association, exact implementation path, or
reviewed crosswalk selecting those targets. Structured quantity support removes
the representation blocker; it does not create clinical correspondence.

Reopen when an upstream association/implementation declaration or an explicit
reviewed local mapping decision identifies dose and rate separately within the
existing medication occurrence.

### Medication timing

Phase 6 materialized the `SXPR_TS` children needed for `IVL_TS`, `PIVL_TS`,
`EIVL_TS`, and recursive `SXPR_TS` choices. The three source timestamps still
have no formal evidence choosing those branches. In particular, a dosage
`zeitpunkt` is a datetime, while `PIVL_TS/period` is a quantity; treating one as
the other would invent frequency semantics. The compiled choice/`comp`
cardinality also needs an explicit within-occurrence construction rule.

All three accepted mapping entries therefore remain `null`. Reopen with an
approved start/stop interval rule and separate formal repetition/event evidence
that satisfies the selected branch's compound constraints.

### X-ray singleton dispatch

The repeated X-ray region field has 13 logical options. Only Thorax, entire
spine, and pelvis carry unqualified LOINC-shaped synonyms resembling reachable
fixed-code statements. Five fixed X-ray statements are reachable, while the
remaining source options and interactions with existing X-ray booleans have no
complete mapping, coalescing, or conflict decision.

No `concept_map`, singleton dispatcher, or `DEC-025` decision is added. Reopen
only with a reviewed table covering all 13 values plus explicit repeat,
coalescing, and conflict behavior (or a suitable active region-bearing target).

## Verification

Focused regressions cover structured parsing, invalid quantity shapes, range
bound validation, compiled low/high assignment, repeated scalar/range
rendering, and safe ordinal extraction. The complete local test suite passes:

```text
Ran 220 tests
OK
```

The reference workspace remains evidence and was not regenerated or edited.
Because no accepted clinical selection changed, reviewed mapping coverage is
unchanged at 95/120.
