# DECOR-core and complete CDA validation follow-up

Date: 2026-09-02

## Scope and result

This analysis follows the specification-derived writable-target recovery and
the post-PR #20 residual mapping audit for the selected AKTIN 2026.1.2
transaction. It asks whether incorporating the official DECOR-core and fuller
HL7 CDA packages is likely to recover additional dataset-to-CDA mappings or is
primarily a validation improvement.

The result is:

- incorporating these packages is valuable for source integrity, constraint
  interpretation and independent CDA conformance validation;
- no additional dataset-to-CDA semantic bridge was found that currently
  justifies increasing the mapped count;
- package-derived rules may expose new structural candidates, but those remain
  suggestions unless the selected transaction, an exact association, exact
  terminology or another explicit specification rule supplies the semantic
  connection;
- the work is therefore deferred while mapping recovery is the priority, but it
  becomes a prerequisite before claiming complete ART-DECOR/CDA conformance;
- one Core Schematron rule reveals that the previously selected medication
  event offset is not independently executable and must be revalidated or
  downgraded when this work resumes.

The published 93-mapped / 4-suggested / 23-no-target headline remains a dated
snapshot. This analysis does not revise generated counts without rebuilding the
model and audit. A future rebuild is expected to move at least the medication
offset out of the mapped category unless its required event can also be mapped.

## Evidence authority

The applicable source stack has distinct responsibilities:

| Source | Authority in this project | What it cannot establish alone |
|---|---|---|
| Selected AKTIN transaction, exact associations and active template closure | Source selection, cardinality and dataset-to-CDA semantic evidence | Generic CDA structures outside the active profile |
| [DECOR-core](https://repository.art-decor.org/exist/apps/stable3/packages/DECOR-core.html?eXist-db-min-version=5.3.0) | DECOR XML representation, cross-artifact consistency and ART-DECOR Schematron-generation behaviour | A missing clinical correspondence between a dataset concept and CDA leaf |
| [ART-DECOR associations](https://docs.art-decor.org/introduction/associations/) | Association types and relationship qualities | Equivalence where no association or explicit rule exists |
| [HL7 Templates Standard as referenced by ART-DECOR](https://docs.art-decor.org/introduction/publication/) | Template constraint, inclusion, versioning and conformance semantics | Project-specific dataset meaning |
| CDA R2, RIM and HL7 V3 datatypes | Legal CDA class, relationship and datatype semantics | Selection of one legal slot for a particular source concept |
| [ART-DECOR datatype Core Schematron](https://docs.art-decor.org/documentation/datatypes/) | ART-DECOR's executable datatype co-constraints | A semantic mapping merely because the datatype accepts a value |
| [HL7 CDA StructureDefinition publication](https://hl7.org/cda/stds/core/) | Useful machine-readable cross-check including current errata and extensions | Replacement for the CDA specification; HL7 labels this representation informative |

The physical and semantic mapping gates remain independent:

1. **Physical:** the CDA/RIM/datatype model permits the representation and every
   applicable template and datatype constraint still permits it.
2. **Semantic:** an association, fixed discriminator, exact terminology
   relationship or another explicit specification rule connects the source
   meaning to that representation.

Core packages substantially strengthen the first gate. They do not relax the
second gate.

## Package inspected

The official stable3 package page exposed `DECOR-core` version `2.2.28`. The
download inspected for this analysis had SHA-256:

```text
14bda739197800f754dff57a6242aa780c01004e58af0d33fc85de72888f9110
```

Relevant package contents include:

- `DECOR.xsd`;
- `DECOR-datatypes.xsd`;
- `DECOR.sch`;
- `DECOR2schematron.xsl` and the template-fragment transform;
- datatype Core Schematrons under `coreschematrons/`;
- package test material.

The package manifest identifies version `2.2.28`, eXist-db 5.3.0 as the minimum
processor environment and GNU LGPL licensing. Its repository metadata labels
the library `beta`, even though it is distributed through the stable3 feed.
The exact compatible DECOR-core version used by, or appropriate for, the server
that produced the selected release must therefore be established before making
it a locked compiler dependency. The current latest package must not silently
be assumed to be the historical production version.

The complete HL7 Templates Standard text was not present in the local archives
and was not substituted with a secondary description. ART-DECOR's publication
documentation is sufficient to identify it as an authority, but disputed
template semantics should be checked against an authorized copy of the exact
standard before being encoded as project policy.

## Additional rules to incorporate later

### Validate the DECOR artifact before interpreting it

`DECOR.xsd` should validate the appropriate complete/assembled DECOR artifact.
`DECOR.sch` should then check cross-reference and compilation constraints. API
fragments must not be treated as complete compiled projects merely because
they contain a dataset or template element.

Diagnostics should distinguish:

- invalid DECOR syntax;
- an unresolved source-project reference;
- a compiled-project completeness error;
- a warning or informational quality rule;
- a valid but semantically unassociated concept.

### Distinguish source-project and compiled-project association rules

The general association model permits zero or more associations. DECOR-core
adds a stricter rule for a compiled project: a concept used in a transaction
connected to a template is reported as an error when the expected
`templateAssociation` is still absent.

Therefore the statement "an absent association is allowed" is correct for a
source project but incomplete for a compiled project. The compiler must retain
which form it is validating and must not apply compiled-project completeness
rules to isolated source fragments.

### Validate exact association identity

DECOR-core requires template associations to resolve through the exact template
identity/revision and concept identity/revision. A template-association concept
uses `elementId`, not `elementPath`, and the indicated element must exist in
the indicated template revision.

The mapping analyser should reject or downgrade evidence when:

- the template or dataset revision does not resolve exactly;
- an element identifier is absent from that revision;
- a name/path heuristic is standing in for the required identity;
- a terminology association is expired or unresolved.

### Preserve terminology and relationship semantics

DECOR-core checks that a terminology association has `code` or `valueSet`, but
not both, and that flexibility is used only with a value-set reference. The
compiled form is expected to contain resolved referenced terminology.

Association relationship qualities such as equal, equivalent, wider, narrower,
related and unmatched must continue to affect confidence and executability. A
generic relationship or a broader/narrower relationship does not by itself
prove a lossless assignment.

### Compile the complete template constraint closure

The future integration must preserve and validate:

- include, contains, inheritance and specialization;
- open versus closed templates;
- static versus dynamic bindings;
- transparent choices and predicates;
- conditional scope;
- cardinality and O/R/M/C/F/NP conformance;
- fixed values and prohibited nodes;
- template assertions, reports and variables.

The ART-DECOR publication documentation distinguishes mandatory content, which
requires a valid value, from required content that may permit omission or an
explicit null representation. This distinction must remain visible in required
CDA completion diagnostics.

### Treat datatype descendants as compound representations

A datatype leaf is executable only when all required sibling/co-occurrence
rules can also be satisfied. The Core Schematrons add constraints that are not
fully expressible in the CDA XSD, including:

- `code`/`codeSystem` and `nullFlavor` combinations;
- restrictions on coded translations and original text;
- interval boundary, center and width combinations;
- low/high ordering and timestamp precision;
- quantity value/unit and permitted time-unit rules;
- event-related timing dependencies.

This evidence should filter candidates and generate required-sibling metadata.
It should not generate a source-to-target semantic connection.

### Add independent output validation

Generated output should pass three independent gates:

1. the complete, pinned CDA XML Schema import graph;
2. the exact effective template Schematron plus datatype Core Schematrons;
3. source-to-output completeness and mapping execution checks.

The current compiler pins official HL7 CDA R2 schema material but fetches four
files for structural/datatype expansion. The complete validation graph must
also include the required narrative and vocabulary schema dependencies. A
matching SDTC extension schema should be included only if the active template
closure uses those extensions.

The current CDA StructureDefinition publication is useful for comparison and
errata discovery, but it explicitly says that it does not replace the CDA
specification. It must not be mixed into the selected historical profile as an
unversioned source of additional writable structures.

## Concrete correction: medication event offset

The post-PR #20 audit recorded this executable mapping:

```text
masnahmen.medikamentose_therapie.medikation.dosierung.zeitangabe.
ereignisbezogene_wiederholung.offset
  -> UVSubordinateadministration.substanceAdministration.
     effectiveTime_xsi_type_EIVL_TS.offset
```

The pinned CDA XSD declares both `event` and `offset` optional. The XSD itself
warns that its inheritance structure accepts combinations prohibited by the
normative datatype description and that schema-valid fragments may still be
illegal.

DECOR-core's `DTr1_EIVL_TS.sch` contains an error assertion equivalent to:

```xpath
@nullFlavor or hl7:event
```

Consequently, a non-null EIVL interval containing only an offset is invalid
under the ART-DECOR Core Schematron. A valid event-related representation needs
an event as well as any offset:

```xml
<effectiveTime xsi:type="EIVL_TS">
  <event code="{TimingEvent}"/>
  <offset value="{offset-value}" unit="{UCUM-time-unit}"/>
</effectiveTime>
```

The source event concept describes examples such as morning, noon, evening and
night, but its active source evidence supplies no sufficiently unambiguous
terminology correspondence to the target TimingEvent codes. The mapping
compiler must not invent that crosswalk from labels.

When this follow-up is implemented, the offset should therefore be handled as
one of:

1. mapped together with an explicitly proven event and valid offset
   representation;
2. review required if only structural compatibility is available;
3. no executable target if the active evidence remains unchanged.

Until then, the six-medication-mapping statement in the dated residual audit is
historical. The other five mappings—product name, product code, dosage
narrative, route and sequence number—are not challenged by this finding.

## Expected effect on remaining boundaries

| Boundary | Expected effect of core-package integration |
|---|---|
| Allergy agent/narrative and category occurrences | Validate the existing representations; no new mapping expected |
| Allergy Concern Act `effectiveTime/low` | Remains a mandatory non-nullable completion failure; no source date is created |
| Medication offset | Likely mapping loss unless event and offset can be proven and rendered together |
| Medication form, ingredient, strength and lot | May expose generic structural slots, but no active-profile semantic bridge is added |
| Medication start/stop, dose/rate, PRN, body site and reason | May improve candidate rejection and compound-value diagnostics; no new executable mapping is currently justified |
| Secondary ICD-10 | Continues to reject `CD.translation` as another diagnosis occurrence; occurrence semantics remain unresolved |
| Seven smaller residuals | May be reclassified more precisely as structural possibilities or constraint failures; no new formal source connection was found |

Thus the likely short-term coverage effect is neutral or slightly negative,
not an increase. Future mapping gains are possible only indirectly: a core rule
could prove that one already-associated source has exactly one surviving legal
representation. No such additional case was identified in this audit.

## Deferred implementation plan

Resume this work when independent conformance validation becomes a release gate
or when a future mapping candidate depends on a datatype/template co-constraint.

1. Determine and record the DECOR-core version compatible with the producing
   ART-DECOR environment; pin URL, version, checksum and license.
2. Add the package to specification acquisition/cache provenance rather than
   treating an unversioned local installation as ambient truth.
3. Select an XPath 2.0-capable Schematron pipeline. `DECOR.sch` and generated
   rules use expressions beyond libxml2/lxml's XSLT 1.0 support.
4. Validate the correct assembled source and compiled DECOR forms separately.
5. Generate the exact transaction/template Schematron through the pinned
   DECOR transform and resolve its Core Schematron includes reproducibly.
6. Fetch and validate against the complete pinned CDA R2 schema graph. Select a
   matching SDTC schema only when demanded by the active closure.
7. Add focused CDA fixtures per datatype/branch. Do not rely only on the one
   all-fields synthetic document, which currently stops first at the known
   allergy Concern Act timestamp boundary.
8. Compare package validation with the built-in compiler/assertion evaluator and
   classify every disagreement as a compiler defect, unsupported rule, package
   version mismatch or disputed authority.
9. Re-run the 120-datapoint mapping audit, reclassify the medication offset and
   regenerate `cda-mapping.md` and its details from `mapping-audit.json`.

Acceptance requires reproducible package identity, no silent rule omissions,
separate error/warning reporting, targeted regression fixtures and unchanged
semantic evidence thresholds. The integration must not derive clinical
mappings merely from the existence of a legal CDA/RIM/datatype slot.

## Priority decision

This follow-up is intentionally not a current mapping-recovery priority because
it found no additional executable mapping and may remove one. It remains
important validation debt and must be completed before the project claims that
generated documents have been independently validated against the complete
ART-DECOR/CDA rule stack.
