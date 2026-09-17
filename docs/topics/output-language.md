# Output language and technical terminology

The language used by decor2hl7 itself is a presentation setting. It is
independent of both the language requested from ART-DECOR and the language of a
generated CDA document.

## Three independent language settings

| Setting | Controls | Does not control |
|---|---|---|
| `decor2hl7.json:language` | Language requested while retrieving ART-DECOR artifacts | CLI text, generated reports, CDA narrative |
| `decor2hl7.json:output.language` | CLI text and generated Markdown reports | Retrieved owner content, mapping semantics, CDA narrative |
| The configured CDA `languageCode` | Human wording generated inside the CDA narrative | CLI text and review reports |

New workspaces use English output by default. English and German are supported;
BCP-47 variants such as `en-US` and `de-DE` normalize to `en` and `de`.
Unsupported output languages fail explicitly instead of producing a partly
translated report.

Select German output when creating a workspace:

```bash
decor2hl7 --output-language de init
```

For an existing workspace, set:

```json
{
  "output": {
    "language": "de"
  }
}
```

The global option overrides the workspace setting for one invocation:

```bash
decor2hl7 --output-language de build
```

The global option appears before the command name. Rerun the artifact-producing
command after changing the setting so its generated Markdown is refreshed.

## What is translated

decor2hl7-owned headings, help text, explanations, status messages, warnings,
and report labels are localized. Stable technical vocabulary remains English
where a literal German translation would be misleading. This includes terms
such as `leaf`, `dataset`, `datapoint`, `mapping`, `model`, `target`, `template`,
`ValueSet`, CDA, and ART-DECOR.

The following content is never translated:

- command names and options;
- JSON keys, paths, OIDs, codes, diagnostic codes, and CDA target names;
- names and descriptions obtained from owner artifacts;
- reviewer-authored reasons and decisions;
- data values and source labels.

This policy intentionally produces German explanatory prose containing familiar
English technical terms. For example, a CDA `leaf` remains a `leaf`, not a
literal “Blatt”.

## Semantic boundary

Output language affects presentation only. Changing it must not change
`model.json`, `cda.json`, mapping decisions, mapping locks, semantic digests,
runtime fingerprints, or generated CDA content. Generated Markdown keeps its
existing filenames and is replaced in the selected language.

The English catalog defines the complete message-key set. Other catalogs must
use the same keys and formatting placeholders. Missing messages, placeholder
drift, unsupported languages, and translation of protected technical terms are
test failures.
