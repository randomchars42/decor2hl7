# Reviewed migration: 2026.1.3 / notaufnahmeregister--60

This profile remains separate from the `2026.1.2` reference used by
`make check-reference`. Its exact transaction is
`2.16.840.1.113883.2.6.60.3.4.60@2026-03-25T00:00:00`, with document template
`1.2.276.0.76.3.1.195.10.93@2026-03-25T11:04:07`.

The [identity-pinned recovery overlay](recovery/2026.1.3-notaufnahmeregister--60-reviewed-cda-overrides.json)
records the reviewed mapping and model additions. Apply its model additions
only for this selection, build from that workspace's own fetched closure, then
require both recorded model hashes, remove only the explicitly listed generated
rules, then apply mapping overrides. Create a
fresh mapping lock and regenerate guides. Do not reuse the older overlay or lock.

The [previous reference decisions](reference-transaction.md) provide the review
inventory, including medication narrative, diagnosis certainty, insurance
identity, time correspondences, intentional nulls and suspended EDIS entries.
The following differences are explicit decisions for this profile.

## Terminology and source input

Administrative gender retains its approved meaning and F/M/UN code-system pairs,
using the exact target-selected ValueSet
`2.16.840.1.113883.1.11.1@2018-08-12T00:00:00`. The other reviewed dataset
additions retain their former meaning and exact bindings. The owner-removed
documentation-start concept is not recreated.

Referral Actions `1.2.276.0.76.11.53@2015-11-17T00:00:00` now provides complete
membership for codes 1–6. Its direct formal coding replaces the old
unresolved-binding workaround. Observation-unit transfer, generic transfer to
another hospital and Sonstiges are logical source options outside this complete
binding; they are rejected rather than assigned code 7, an unapproved OTH, or a
nearby destination. Owner alignment is still required for these options.

Transport source terminology is
`1.2.276.0.76.11.41@2024-02-14T09:42:48`, while the selected CDA observation
requires the `2015-11-17T00:00:00` revision of the same OID. The SNOMED CT domain
does not prove a lossless legacy vehicle-category selection. The source field
therefore remains null under structured fields and is retained as a labelled
fact at `Transportmethod.section.text`. The
[suspension record](recovery/2026.1.3-notaufnahmeregister--60-suspended-cda-mappings.json)
preserves the rejected generated assignment, exact bindings and reopening
evidence. No lossy deployment transport crosswalk is supplied.

## Occurrences and completion

CEDIS code, wording, provisional concern onset and active concern status remain
in the Chief Complaint section. Their exact physical targets are qualified by
`Chiefcomplaintreasonforvisit.entry::`. The additional History of Present Illness
containment does not move or duplicate these facts. Provisional onset meaning
still needs the owner confirmation recorded in the open boundaries.

Pupil size and reaction retain separate right/left occurrences. Allergy category
booleans retain inverse negation, absence semantics and exact-agent coalescing.
The current owner antibiotic example supplies J01; contrast supplies V08. J01 is
retained as the profile-derived discriminator, not rewritten to satisfy an older
receiver. Agent fallback uses the complete current binding, including J01, while
OTH remains an exception.

Root medication status is now required by the owner template and is an explicit
activation-scoped site requirement, alongside the existing medication mood and
subordinate lifecycle requirements. No lifecycle state is inferred from times.
The selected simple medication branch and its intentional timing nulls remain.

MRI, repeated X-ray regions and EDIS facts retain their reviewed narratives.
EDIS structured attachments remain absent; a standalone definition does not
establish containment or receiver acceptance.

## Verification boundary

The authored synthetic cases are under
`src/decor2hl7/scenarios/2026.1.3/notaufnahmeregister--60/valid-reference-cases`.
They use the new transport domain directly and do not define production aliases
from legacy vehicle categories. Negative checks retain the rejected referral
options, legacy transport values and contradictory negative-isolation branch.

Exact-closure output conformance and validation by the unchanged provided
receiver are separate gates. The receiver publication rejects J01 allergy
discriminators accepted by this selected profile. A diagnostic copy replacing
only J01 with the older A07AA can isolate that difference, but is not an approved
clinical mapping or deployable output. Keep the original outputs and mapping.
Receiver alignment or a separately reviewed compatibility contract is required
before deployment. Correction/RPLC acceptance remains a separate open matter.

Source-project findings for invalid issue metadata, empty medication choices and
the stationary receiver actor remain report-only upstream findings. The missing
local supported-datatype catalogue that made the audit depend on network access
is a tooling defect; validators now resolve that dependency from the pinned
package. Use fresh offline generated reports for the exact checked inputs.
