# Association identity-lineage closure

Date: 2026-09-06

## Question and conclusion

The field
`hauptkostentrager.versicherungsverhaltnis.identifikation` has more formal
mapping evidence than the earlier audit reported. Its selected concept and a
historical concept statically associated with CDA participant template
`.10.2022` meet at the same HL7-DE ancestor. The missing link was acquisition:
the default closure retained the static association declaration but did not
retrieve the exact foreign concept that carries the other half of the lineage.

This is sufficient to report a medium-confidence semantic bridge to the
historical `.10.2022` `associatedEntity/id`. It is not sufficient to emit the
requested mapping to active occurrence `.3.1.195.10.4`: both participant
occurrences are physically present in the selected document, and the evidence
does not identify them as the same occurrence.

## Formal chain

The selected transaction establishes both of these identity edges for item
`.60.3.2.9.21582` (Identifikation des Versicherungsverhältnisses):

- `inherit/@originalId = .77.2.2.60210`;
- `relationship[@type='SPEC']/@ref = .77.2.2.60210`.

The exact eVent concept `.60.12.2.358@2016-11-06T13:10:51` inherits the same
HL7-DE item `.77.2.2.60210@2015-10-15`. Historical template
`.10.2022@2014-08-25` then statically associates eVent `.358` with element
`.77.9.26`, whose path is its participant's `associatedEntity/id` and whose
datatype is `II`.

The two equivalent evidence paths are therefore:

```text
.60.3.2.9.21582 --ORIGINAL--> .77.2.2.60210
                  <--INHERIT-- .60.12.2.358 --STATIC_ASSOC--> .10.2022/.77.9.26

.60.3.2.9.21582 --SPEC------> .77.2.2.60210
                  <--INHERIT-- .60.12.2.358 --STATIC_ASSOC--> .10.2022/.77.9.26
```

There is additional supporting—but not decisive—template evidence. Active
Hauptkostenträger template `.3.1.195.10.4@2024-08-09` declares `SPEC` of
historical `.10.2022`. Its open CDA structure physically permits a writable
`associatedEntity/id` of datatype `II`.

## Why the active mapping remains review-only

The compiled selected document contains the historical `.10.2022` participant
at one physical location and the active `.3.1.195.10.4` participant at another.
The static association names only the historical element. Template
specialization and concept identity do not establish which physical participant
occurrence owns the selected transaction group when both are instantiated.

The active `associatedEntity/id` is XSD-derived and currently carries no ART-DECOR
element id. Its CDA/RIM provenance records `datatype_part = hl7:id` but an empty
owning datatype, so DEC-015 cannot prove one unique owner-class/particle slot
across the template boundary. Selecting it from the common leaf spelling or
relative path would be a new inference, not formal evidence.

The corrected audit consequently retains the historical candidate with
`occurrence_mismatch: true`, `actionable: false`, and the warning that explicit
occurrence evidence is required. Generated Schematron and transform discovery
are forbidden from making that candidate executable.

## Implementation boundary

`fetch` now treats exact `templateAssociation/concept` and
`staticAssociations/origconcept` endpoints as typed, analysis-only mapping
evidence. After any evidence concept is resolved, it recursively follows only
identity-style concept edges: `SPEC`, `INHERIT`, `ORIGINAL`, `EQUIV`, `VERSION`,
and `COPY`. It deliberately does not recurse through `ADAPT`, other derivations,
template links, terminology links, or whole external datasets.

Exact concept scoping matters. An early whole-dataset experiment imported many
unrelated siblings, selected the historical insurance occurrence, displaced the
existing Kostenträger-name context, and encountered an unrelated server error.
The final implementation instead keeps the semantic graph bounded and processes
dataset groups parent-first so a child's historical evidence is evaluated
inside the already selected parent occurrence.

## Reference-workspace audit

An isolated copy of release `2026.1.2`, transaction
`notaufnahmeregister--60`, completed the endpoint-scoped crawl with
`crawl_complete: true` and `build_ready: true`. The audit contained 513 build
resources and 828 evidence resources: 747 successful/cached, 80 terminal
missing, three waived, and no unavailable or erroneous resources. The measured
pass used 268 recursive HTTP requests; the final analysis-only endpoint request
rule removes the optional source-form request and is covered separately by the
fetch regressions. A subsequent final-code `fetch --offline` reproduced the same
513/828 closure entirely from cache with zero HTTP requests.

After rebuilding with the occurrence guard, executable field coverage remains
95/120 datapoints to 97 CDA leaves; five datapoints remain suggested and twenty
remain without a target. Thus the correction adds evidence without silently
changing reviewed field mappings or reducing efficacy.
The build retained the reference snapshot's three build-degrading artifacts and
its report-only conformance result (381 errors, 1780 warnings); neither changed
the mapping comparison or arose from this lineage correction.

## Similar chains

The complete comparison found two additional field-relevant families:

- The neighbouring Kostenträger concepts share the same eVent/HL7-DE pattern.
  `.21578`/`.21579` connect through `.60090`/`.60100` to eVent `.354`/`.355`
  and historical `.10.2022` `scopingOrganization` evidence. The existing active
  Kostenträger-name mapping remains authoritative; historical direct targets are
  occurrence-mismatch alternatives, while a unique active structural projection
  may provide group context.
- The medication Arzneimittel group gains a
  `SPEC -> SPEC^-1 -> STATIC_ASSOC -> CDA_RIM_SLOT` bridge to the active
  `manufacturedMaterial` container. This is a structural group placement, not a
  new scalar field mapping, and does not change the 95 executable fields.

No other selected or proposed scalar field changed because of the new lineage
evidence. Sixteen exact association endpoints and five identity ancestors were
terminally missing from the publishing server in this snapshot. Their absence
is explicit in `closure.json`; they may conceal additional chains, but the
compiler does not infer them. A later `--retry-missing` crawl is the bounded way
to re-evaluate those artifacts if the publisher changes.

## Regression evidence

The tests cover typed endpoint discovery, analysis-only requests, transitive
identity closure, exclusion of `ADAPT`, sibling concepts returned in one API
response, the selected-occurrence guard, Schematron non-revival, and preservation
of the existing unique CDA/RIM-slot projection rule.
