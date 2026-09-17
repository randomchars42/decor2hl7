# Clinical and ART-DECOR workflow guide

This part of the documentation is for people who select and review clinical
specifications, connect a local data export, or operate document generation. It
describes the work from the user's perspective and does not require knowledge
of decor2hl7 internals.

decor2hl7 separates three workflows because their decisions have different
owners and different reuse scopes:

| Workflow and user group | Receives | Produces | Main responsibility |
|---|---|---|---|
| **Specification and target mapping** — specification maintainer and clinical mapping reviewer | An exact ART-DECOR release and transaction | A reviewed, shareable dataset-to-target mapping | Decide what the specification means and which mappings are clinically valid |
| **Site and input configuration** — site integration administrator | The compiled dataset and a reviewed mapping, plus one site's export | A site-local input configuration | Describe files, columns, joins, local codes, identifiers, and deployment values |
| **Runtime operation** — runtime operator | Compiled models, reviewed mapping, site configuration, and an input snapshot | Validated output documents and delivery state | Check, transform, validate, monitor, and optionally send |

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

## Choose your workflow

- Start with [Review a specification and publish a mapping](specification-and-mapping.md)
  if you maintain the selected specification or make clinical mapping
  decisions.
- Start with [Configure a site's input](site-configuration.md) if you know the
  local export, source relationships, identifiers, and code conventions.
- Start with [Operate document generation](runtime-operation.md) if the mapping
  and site configuration are already approved and you need to process or send
  data.

## Shared working rules

- Select an exact release and transaction. Do not mix revisions or substitute a
  nearby artifact.
- Edit reviewed JSON configuration, not generated Markdown reports or XML
  previews.
- Keep clinical mapping decisions in the portable mapping and local source
  decisions in the site configuration.
- Treat unresolved mappings as review work. A plausible name match is not a
  clinical decision.
- Use generated models and reports for the exact selected identity; do not copy
  conclusions from another workspace.
- Choose the CLI and generated-report language with `output.language`; this is
  separate from ART-DECOR retrieval language and CDA document language. See
  [Output language and technical terminology](../topics/output-language.md).

References to organizations, profiles, or upstream projects identify artifact
provenance only. They do not imply endorsement of decor2hl7 by those parties.

For installation and workspace creation, see the [project README](../../README.md).
Developers and technical maintainers should use the
[technical documentation index](../index.md#developer-and-technical-reference).
