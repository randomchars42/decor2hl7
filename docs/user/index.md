# Clinical and ART-DECOR workflow guide

This part of the documentation is for people who select and review clinical
specifications, connect a local data export, or operate document generation. It
describes the work from the user's perspective and does not require knowledge
of decor2hl7 internals.

decor2hl7 separates three workflows because their decisions have different
owners and different reuse scopes:

| Workflow and user group                                           | Receives                                                                                          | Produces                                                 | Main responsibility                                                                      |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Specification and target mapping** — clinical mapping reviewer  | An exact ART-DECOR release and transaction                                                        | A reviewed, shareable dataset-to-target mapping          | Decide what the specification means and which mappings are clinically valid              |
| **Site and input configuration** — site integration administrator | The compiled dataset and a reviewed mapping, plus one site's export or read-only replica          | A site-local input and optional extraction configuration | Describe queries, files, columns, joins, local codes, identifiers, and deployment values |
| **Runtime operation** — runtime operator                          | Compiled models, reviewed mapping, site configuration, and an input snapshot or configured source | Validated output documents and delivery state            | Extract when configured, check, transform, validate, monitor, and optionally deliver     |

These are handoffs, not one shared configuration task:

```text
ART-DECOR specification
  -> reviewed portable mapping
       -> site-local input configuration
            -> runtime documents and delivery state
```

A portable mapping can be reviewed once and reused by several sites. Each site
keeps its source layout and deployment policy separate. Runtime consumes both
products but does not revise either one.

Each guide begins with its relevant workspace folders and practice setup. Follow
the three guides in order to reuse the same fictional records, or use the
population instructions when starting at a later workflow.

## Choose your workflow

- Start with [Review a specification and publish a mapping](specification-and-mapping.md)
  if you are responsible for the selected specification and make clinical
  mapping decisions.
- Start with [Configure a site's input](site-configuration.md) if you have a
  reviewed specification mapping and are about to adapt decor2hl7 to your site.
- Start with [Operate document generation](runtime-operation.md) if the mapping
  and site configuration are already approved and you need to process or send
  data.

For installation and workspace creation, see the [project README](../../README.md).

## Set up testing

For a ready-to-run synthetic SQLite rehearsal, use the
[integration setup command](testing.md#build-a-runnable-sqlite-baseline). It
creates a new environment from your reviewed specification and its matching
packaged cases.

Use the [testing guide](testing.md) to prepare an isolated workspace, then choose
the level you are working on:

- [Specification and mapping tests](testing.md#1-test-the-specification-and-mapping):
  authored cases, expected fields/templates, mapping coverage, and CDA validation.
- [Site input tests](testing.md#2-test-the-site-input): your copied configuration,
  representative CSVs or a test database, and invalid-input checks.
- [Runtime and delivery tests](testing.md#3-test-runtime-and-delivery): local spool
  handover, unchanged replay, corrections, and failure diagnosis.

Developers and technical maintainers should use the
[technical documentation index](../index.md#developer-and-technical-reference).
