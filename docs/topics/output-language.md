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
Guides copied into initialized bundles retain their source report language;
regenerate them with `build` or `propose-input` before refreshing the bundle.

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

## Catalogs and stable message IDs

Translations are data files rather than Python source:

- `src/decor2hl7/locales/en.json` is the canonical catalog;
- `src/decor2hl7/locales/de.json` supplies the German messages.

Both files are packaged with the application. Every entry has a stable,
namespaced message ID: `cli.*` for complete command messages and help,
`ui.*` for composed terminal output, and `markdown.*` for generated report
prose. Presentation code constructs messages directly through these IDs;
there is no runtime search or substitution of English fragments. An explicit
report language scopes nested presentation helpers, while supplied owner text
is inserted unchanged. Argparse labels are constructed in the chosen language
before formatting. English source text is not a catalog key. Changing the wording or translation
does not require changing its ID. An existing ID must not be renamed or reused
for a different meaning merely because its wording changes.

New decor2hl7-owned text belongs in both locale files, not in an inline Python
translation table. Prefer a short semantic ID that describes the message's
role and remains meaningful when its wording changes. Avoid ordinal suffixes
or IDs derived solely from the entire English sentence.

The English catalog defines the complete message-ID set. Other catalogs must
use the same IDs and formatting placeholders. Invalid IDs, missing messages, placeholder drift,
unsupported languages, and translation of protected technical terms are test
failures.
