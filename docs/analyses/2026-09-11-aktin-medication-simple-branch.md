# AKTIN medication baseline branch re-review

Date: 2026-09-11

Status: the branch-selection conclusion remains current. The mapping-specific
product-name and lot-number conclusions were superseded by the direct
transaction-instance review on 2026-09-14; see
[`2026-09-14-aktin-medication-reviewed-mappings.md`](2026-09-14-aktin-medication-reviewed-mappings.md).

## Question

Does the refreshed authoritative workspace justify replacing the medication
consumable branch selected by AKTIN with the richer inherited sibling?

## Available evidence

The transaction selects repeatable Medikamentöse Therapie and its Medikation
group. The contained medication dataset includes product, dose form, ingredient,
timing, dosage, rate and reason fields.

AKTIN Medikation
`1.2.276.0.76.3.1.195.10.67@2023-12-03` explicitly contains UV Medication
Information (simple)
`2.16.840.1.113883.10.21.4.10@2021-09-29T19:15:16`. Its exact UV Medication
Statement parent also declares UV Medication Information (detail)
`2.16.840.1.113883.10.21.4.11@2023-02-03T13:03:38` as a sibling choice at the
same consumable host. That proves structural availability for a separately
reviewed profile; it does not prove that AKTIN selected the sibling.

The simple branch carries medication code and `lotNumberText`; the generic
CDA/RIM expansion supplies the associated material-name slot. It has no dose-
form or ingredient model. The detail branch supplies those additional fields,
but selecting it changes the AKTIN branch rather than merely expanding a
constraint already selected by AKTIN.

## Conclusion

The reference baseline follows the exact AKTIN selection. The medication
`select_spec_branch` record is removed from `config/cda-extensions.json` and the
compiled workspace is regenerated with the simple branch. DEC-028 remains a
generic guarded mechanism for explicitly identified downstream profiles, but
its medication application is not baseline AKTIN evidence.

Product name, product code, sequence number, dosage narrative and route remain
executable through their independent evidence. Dose form and direct ingredient
name, code and active/inactive role return to unmapped. Chargennummer also
remains unmapped: `lotNumberText` is physically available in the simple branch,
but no current exact association selects it.

Timing, dose, rate, strength and medication reason are unaffected; their prior
semantic and compound-occurrence gaps remain.
