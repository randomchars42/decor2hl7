# Current roadmap

This page lists unfinished work only. Completed implementation history remains
available through Git and is not duplicated in durable documentation.

## Specification and mapping

1. Obtain profile-owner clarification for the provisional
   presenting-complaint onset placement.
2. Complete medication timing only after branch-selection and occurrence
   semantics are established; keep current intentional nulls meanwhile.
3. Reopen ingredient and structured imaging-region mappings only with an
   owner-selected target or a complete reviewed profile/crosswalk; retain the
   reviewed imaging wording in section narrative meanwhile.
4. Replace the local EDIS attachments if upstream publishes explicit
   containment.
5. Replace the finite Referral Actions bridge when the exact target terminology
   becomes available.

## Tooling and operations

1. Add a bounded command for applying the identity-pinned reference recovery
   overlay if repeated regeneration makes the manual procedure burdensome.
2. Implement a receiver-specific transport adapter when authentication,
   acknowledgement, batching, and idempotency semantics are known.
3. Keep release verification local until a CI host and artifact-access policy
   are selected.

Every item remains subject to the ownership and evidence rules in
[`index.md`](index.md) and the concrete reopening criteria in
[`open-boundaries.md`](open-boundaries.md).
