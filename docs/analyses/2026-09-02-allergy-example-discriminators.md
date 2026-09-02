# Allergy boolean example discriminators

Date: 2026-09-02

## Scope

This analysis revisits the two derived allergy flags after a prior chat pointed
to neutral examples in the Allergy Intolerance Observation. The chat was a lead,
not project authority. Every conclusion below was re-established from the local
selected release, compiled model and active mapping proposal before becoming
DEC-018.

The inspected snapshot is release `2026.1.2`, transaction
`notaufnahmeregister--60`, using the local `test-workplace/spec/` closure and
canonical code `main` at `33d1dc9` as the baseline.

## Source and target evidence

The source booleans are optional, singular fields:

| Source | Meaning | Source terminology evidence |
|---|---|---|
| `Antibiotikaallergie` | suspected or existing antibiotic allergy | disorder assertion `Z88.1` |
| `Kontrastmittelallergie` | suspected or existing contrast-agent allergy | disorder assertion `293637006` |

Those disorder codes do not belong in the CDA allergen slot. The active exact
target template `1.2.276.0.76.10.4066@2015-09-18T00:00:00` instead contains two
category-specific neutral examples:

| Example caption | `negationInd` | `playingEntity/code` |
|---|---:|---|
| Antibiotika-Allergie bekannt seit 2010 | absent/false | `A07AA` in `2.16.840.1.113883.6.73` |
| Keine Kontrastmittel-Allergie/Unverträglichkeit bekannt | true | `V08` in `2.16.840.1.113883.6.73` |

Both code/code-system pairs are exact members of the template's bound ValueSet
`1.2.276.0.76.11.52@2015-11-17T00:00:00`. The observation is repeatable,
`@negationInd` is writable, and the required discriminator occupies the same
occurrence. The source fields already inherit the mapped Allergies and
Intolerances section context.

## Accepted generic rule

The compiler derives a `repeat_by_discriminator` branch only when:

1. a boolean source is still unmapped and has one exact mapped container
   context;
2. a long category-specific source name uniquely matches one neutral example
   caption;
3. the example is owned by the exact effective template of a writable
   `@negationInd` target;
4. one required coded target in the same occurrence binds one exact ValueSet
   revision and the example code/code-system is an admitted member; and
5. the target introduces exactly one repeat level beyond the source.

The branch transforms the boolean with `not`. Source `true` therefore writes a
positive assertion (`negationInd=false`); source `false` writes an explicit
negative assertion (`negationInd=true`); an absent value creates no occurrence.
The target example member becomes the discriminator constant. Source disorder
terminology is retained as evidence but is never copied into
`playingEntity/code`.

If one direct field already maps to the discriminator, the binding layer merges
the example-derived payload into that occurrence only when code and code system
are equal. Thus an explicit `Agens=A07AA` plus
`Antibiotikaallergie=true` produces one antibiotic occurrence, while an
unrelated agent and the antibiotic flag produce two. Conflicting payloads for
one equal discriminator raise an error.

## Fresh-snapshot result

| Measure | Baseline | With DEC-018 |
|---|---:|---:|
| Dataset fields | 120 | 120 |
| Dataset groups | 57 | 57 |
| Reachable templates | 308 | 308 |
| Physical named CDA targets | 24,940 | 24,940 |
| Logical mapped CDA datapoints | 93 | 95 |
| Proposed mapped fields | 91 | 93 |
| Unavailable artifacts | 21 | 21 |
| Unresolved CDA references | 1 | 1 |

The two gained fields are exactly the antibiotic and contrast-agent flags. No
unrelated boolean acquired an example-derived mapping. `check-cda-mapping`
passes, and the runtime regression verifies inverse polarity plus exact-agent
coalescing without duplication.

## Remaining occurrence boundary

The rule supplies the Allergy Intolerance Observation payload but cannot invent
the parent Allergy Concern Act's required `effectiveTime/low`. Template
`1.2.276.0.76.10.4065@2015-03-27T00:00:00` defines that value as the time the
allergy was first documented as a concern. The source transaction has no such
timestamp, and the mandatory target cannot use a null flavor.

The synthetic full-proposal fixture therefore continues to fail at exactly this
known boundary:

```text
mandatory CDA element hl7:act/hl7:effectiveTime/hl7:low
[1.2.276.0.76.10.4065@2015-03-27T00:00:00] has no fixed, mapped, or default
value and cannot use nullFlavor
```

Document time, encounter time and the example's illustrative dates are not
substitutes for this clinical assertion time.

## Verification

- focused runtime regression: exact `Agens=A07AA` plus both flags yields two,
  not three, discriminated occurrences with negations `[false, true]`;
- mapping validation: zero errors;
- fresh build: 93/120 proposed fields and 95 logical CDA datapoints;
- synthetic mapping fixture: reaches only the pre-existing mandatory Concern
  Act timestamp boundary described above.

