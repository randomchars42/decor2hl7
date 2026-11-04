# Synthetic reference cases for 2026.1.3

These authored cases retain the six clinical branches from the 2026.1.2 fixture
and use the exact selected 2026.1.3 transaction and terminology domains.

- Transport facts are authored directly as ground ambulance or no transport in
  the new SNOMED CT domain. This fixture supplies no deployment conversion from
  legacy KTW/RTW/NEF categories.
- The removed documentation-start field is absent.
- Gender uses the exact target-selected 2018 ValueSet revision.
- Referral examples use admitted internal monitored-care destinations. Rejected
  legacy referral options require separate negative checks; they are not
  silently replaced with a nearby destination.
- Isolation remains affirmative in these valid cases because the selected
  dataset/profile conflict prevents a conforming negative case. The negative
  branch is checked separately as an expected rejection.
- Medication mood/status values are explicit synthetic-site configuration.
- Structured EDIS entries remain suspended; their facts stay in narrative.

The fixture is synthetic validation evidence, not a production export layout.
