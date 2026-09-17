# CDA compilation and validation

`cda.json` is the compiled target boundary. It combines exact ART-DECOR
constraints with the pinned CDA R2/RIM and HL7 V3 datatype graph before mapping
or rendering begins.

Related decisions: DEC-013, DEC-014, DEC-017, DEC-019, DEC-020, DEC-021,
DEC-023, DEC-024, DEC-026, DEC-028, DEC-030, DEC-031, DEC-032, DEC-039,
DEC-040, and DEC-044.

## Effective physical model

Compilation selects exact reachable template revisions, expands executable
`include` and `contains`, applies reviewed exact overlays, and then overlays the
stored ART-DECOR constraints on the pinned CDA/RIM XSD structure. The first
template SPEC relationship remains prototype evidence and is not merged.

Open contexts may receive omitted CDA/RIM particles. Closed contexts may only
type and complete explicitly selected particles. An `NP` constraint prohibits
its complete physical subtree; generic XSD descendants cannot revive it.
Transparent include/contains wrappers do not create XML nodes, and an explicit
wrapped child satisfies the corresponding XSD particle without a duplicate
generic child.

Physical source identity includes template OID, effective date, element ID, and
template-local path. Flattened target names remain stable configuration keys,
while `path` and `locations` preserve the actual hierarchy.

## Datatypes and writable values

The XSD graph supplies structural types, datatype aliases, extension and
restriction inheritance, particles, attributes, defaults, and ordering.
ART-DECOR constraints refine that legal surface. A node is writable only when it
has a compiled scalar value representation and resolves to one unfixed,
non-prohibited physical location.

Representations cover element text, XML attributes, identifiers, timestamps,
quantities, coded values, and booleans. Mapping and rendering consume this
metadata rather than interpreting path names or maintaining separate datatype
switch tables.

Compound datatypes may declare `non_null_requires` companions. Proposal
generation, configuration validation, and rendering enforce the requirement per
occurrence. A null-flavoured value is exempt when the datatype permits it.

Reviewed polymorphic roots, currently `SXCM_TS`, expose legal concrete subtype
branches through compiled choice metadata. Assigning a descendant selects the
recorded `xsi:type`; conflicting branches in one occurrence are rejected.

XSD restrictions remove prohibited content and attributes; extensions add base
content. Formal terminology validation may retain a code-system identity even
when the concrete restricted datatype, such as `CS`, does not serialize a
`codeSystem` attribute.

## Examples, fixed values, and construction roles

Only fixed ART-DECOR constraints, normative XSD defaults, compiler-owned system
roles, mapped values, reviewed mapping defaults, and validated site values can
construct output. ART-DECOR examples are never copied into output defaults.

Required entry `text/reference/@value` branches are compiler-owned narrative
infrastructure when the exact constraints prove the relationship. Rendering
creates an occurrence-local fragment identifier and matching section
`content/@ID`; the fragment URI is not a clinical mapping target.

For `SD.TEXT` section narratives, rendering writes mapped facts as CDA
NarrativeBlock paragraphs and tables rather than flattening unrelated scalars.
Generated entry fragment IDs are placed in the first matching occurrence value
cell; unmatched fragments remain a list, so every reference still resolves.
For a plain text section target, the same labelled content uses a compact text
fallback. This presentation is derived from the reviewed mapping and normalized
record; it does not add clinical assignments.

## Schematron and assertions

The build uses pinned DECOR-core, Saxon, XML Resolver, and complete CDA/SDTC XSD
packages. It validates broad source-project evidence under a report-only policy
and separately assembles a validator from only the exact template revisions
selected at physical document locations. Assembly fails if a selected formal
include or contains reference is absent or revision-inconsistent.

Generated template Schematron supplies bounded supporting evidence such as
cardinality, fixed values, bindings, required attributes, and concrete
`xsi:type` choices. It may strengthen or disqualify an existing mapping
candidate, but it never creates a semantic source-to-target bridge.

A narrow parser also extracts error-level datatype presence/co-occurrence
clauses. It applies a clause only when one assignment plus fixed or required
direct content necessarily violates it. Unsupported XPath stays visible and is
left to the complete Schematron gate.

ART-DECOR assertions retain their in-scope namespace bindings. The in-process
evaluator runs after the complete CDA tree exists; unsupported error-level
expressions fail closed, while warning-level results are reported. The original
expressions are also emitted as Schematron.

`check` and `check-cda-mapping` run setup-time source verification from
`cda/parity.py`. They compare explicit source constraints with the compiled
model and report declared endpoint parity for the selected physical document
closure. Fixed structural attributes and reviewed branch replacements are
classified separately; an unexpected missing endpoint is an error. Runtime
validation does not import the ART-DECOR parser.

`validate-cda` verifies package and validator identity, validates against the
complete CDA/SDTC schema graph, and runs the exact generated Schematron. For a
reviewed foreign-namespace profile extension, it first checks compiled physical
paths and applies the base XSD to a projection with only those foreign nodes
removed; this is not presented as validation against an unavailable extension
schema.

The generated validator checksum records integrity between
`validator-manifest.json` and the exact stylesheet on disk. It is not a
cross-run reproducibility promise because Saxon-generated validator bytes are
not stable across independent compilations. The assembled source and generated
Schematron remain deterministically pinned, while validator behavior is checked
with valid and invalid documents.

Mapping coverage and CDA conformance remain independent. A legal leaf does not
prove clinical meaning, and a reviewed mapping does not prove that the complete
document passes its conformance gates.
