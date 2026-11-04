# Documentation

The documentation has two entry points. Choose the one that matches the work
you are doing:

- **Clinical and ART-DECOR workflow guides** explain what each user group
  receives, decides, produces, and hands over. Start with
  [`user/index.md`](user/index.md).
- **Developer and technical reference** explains implementation boundaries,
  evidence rules, generated formats, and the reasons behind current behavior.
  Continue with “Where should I look?” below.

The two tracks describe the same three workflows and artifact boundaries. The
user guides are task-oriented; the technical pages are the durable authority
for implementation and maintenance.

## Clinical and ART-DECOR workflow guides

| User group                                             | Workflow                                                                                              | Start here                                                               |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Specification maintainer and clinical mapping reviewer | Select an ART-DECOR specification, review dataset-to-target decisions, and publish a portable mapping | [`user/specification-and-mapping.md`](user/specification-and-mapping.md) |
| Site integration administrator                         | Connect one site's source export to the target-neutral dataset without changing the portable mapping  | [`user/site-configuration.md`](user/site-configuration.md)               |
| Runtime operator                                       | Validate input, create documents, monitor state, and deliver output                                   | [`user/runtime-operation.md`](user/runtime-operation.md)                 |

The overview in [`user/index.md`](user/index.md) explains the handoffs between
these groups and helps choose the correct workflow.

For test workspaces, authored cases, site input checks, and delivery rehearsals,
see [Set up tests for each workflow](user/testing.md).

## Developer and technical reference

### Where should I look?

| Question                                                                          | Current source                                                                         |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| What is the project trying to do, and who owns each artifact?                     | [`../Project-decor2hl7.md`](../Project-decor2hl7.md)                                   |
| How is the code divided and how does data move through it?                        | [`architecture.md`](architecture.md)                                                   |
| Which ART-DECOR constructs are authoritative?                                     | [`topics/art-decor-authority.md`](topics/art-decor-authority.md)                       |
| How are artifacts identified, fetched, cached, and admitted to a build?           | [`topics/retrieval-and-artifacts.md`](topics/retrieval-and-artifacts.md)               |
| How are dataset concepts, terminology, and quantities compiled?                   | [`topics/dataset-and-terminology.md`](topics/dataset-and-terminology.md)               |
| How are CDA constraints, datatypes, assertions, and validators compiled?          | [`topics/cda-compilation-and-validation.md`](topics/cda-compilation-and-validation.md) |
| How are mapping candidates, reviewed rules, defaults, and documentation produced? | [`topics/mapping-and-construction.md`](topics/mapping-and-construction.md)             |
| How is the CLI and generated-report language selected?                            | [`topics/output-language.md`](topics/output-language.md)                               |
| How do site input, occurrences, runtime state, and delivery work?                 | [`topics/input-runtime-and-delivery.md`](topics/input-runtime-and-delivery.md)         |
| How does the complete setup-time pipeline work internally?                        | [`specification-to-mapping-pipeline.md`](specification-to-mapping-pipeline.md)         |
| What has been decided for the selected reference transaction?                     | [`reference-transaction.md`](reference-transaction.md)                                 |
| What is genuinely unresolved?                                                     | [`open-boundaries.md`](open-boundaries.md)                                             |
| What does a `DEC-*` reference mean?                                               | [`decisions.md`](decisions.md)                                                         |

### Technical specifications

- [`specification-to-mapping-pipeline.md`](specification-to-mapping-pipeline.md)
  follows acquisition, compilation, evidence generation, and mapping
  initialization from an implementation perspective.
- [`mapping-documentation-format.md`](mapping-documentation-format.md) specifies
  the generated mapping-review documents.
- [`recovery/`](recovery/) contains source-controlled, identity-pinned reviewed
  mapping overrides that cannot be regenerated from owner rules alone, and the
  [suspended EDIS mapping restoration list](recovery/2026.1.2-notaufnahmeregister--60-suspended-cda-mappings.json).
