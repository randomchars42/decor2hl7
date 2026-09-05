# Ordinal evidence correction

Date: 2026-09-05

Code baseline: local `main` at `37d2da4`

Reference workspace: local AKTIN `2026.1.2`, transaction
`notaufnahmeregister--60`

## Corrected finding

The phase-7 analysis stated that the safe ordinal guard covered the real CEDIS
shape. Its regression represented the collision as two primary labels beginning
with `101`. The selected transaction instead puts the classification numbers in
synonyms: a range header has synonym `101-150`, while a member has synonym
`101` (and likewise `251-300` / `251`).

The first guard rejected each hyphenated range before the injectivity check but
still accepted each bare numeric member synonym. The extracted member numbers
were unique, so the collision check never removed them. Compiling the selected
transaction therefore still placed ordinal metadata on 170 of 187 CEDIS
options even though the generated mapping did not consume it.

## Correction

A bare leading number is now considered only in an option's primary label.
Labels and synonyms remain eligible when they contain explicit rank/score
wording. The whole-list injectivity check remains in place. This produces the
following selected-transaction result:

- X-ray region: 0 of 13 options with ordinal metadata;
- MRI region: 0 of 15;
- CEDIS: 0 of 187;
- fall mechanism: 0 of 13;
- GCS eye response: 4 of 4; and
- modified Rankin: 7 of 7.

The five bare numeric synonyms on the CT/MR/DS angiography coded domain also
lose false ordinal metadata. That field uses an exact terminology-backed
`enum` mapping, so its executable behavior is unchanged. Modified Rankin is the
only reviewed/generated `ordinal` transform in the reference mapping, and its
explicit `Rankin N` synonyms remain recognized.

## Verification boundary

The focused regression now includes the exact CEDIS range-header/member synonym
shape as well as separate positive GCS/Rankin and duplicate-leading-label
controls. The reference workspace is evidence only and was not regenerated or
edited for this code change. Its generated model and identity hashes will change
the next time the workspace is deliberately rebuilt; reviewed mapping coverage
and CDA runtime behavior are expected to remain unchanged.
