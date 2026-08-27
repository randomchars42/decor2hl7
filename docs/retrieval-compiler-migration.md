# Retrieval/compiler migration result

Date: 2026-08-27

## Result

The current-API retrieval migration and the compiler-boundary refactoring are
implemented. The prefix/link inference patch is preserved in
`retrieval/resolution.py`: candidate repositories are ordered by authoritative
OID ownership, explicit reference link/prefix context, the exact revision-aware
owner cache, and only then the configured repository list.

No Release-2 `/decor/services/Retrieve*` URL or compatibility fallback remains.
Expanded templates use the current API `$extract?tree=expand` representation;
the code does not use `?format=expandedxml`. Source and expanded/analysis forms
are both cached and retained in the artifact record.

## Fresh-artifact findings now encoded in the compiler

- The transaction source is selection truth: 144 selected concepts (49 groups,
  95 items).
- The transaction analysis resolves the hierarchy and containment: 33 contained
  additions produce 177 model datapoints (57 groups, 120 fields).
- Requested and resolved artifact identities, source/analysis/expansion forms,
  dependency roles, and dynamic/static aliases remain explicit.
- Static effective dates resolve exactly. A newer or older template is never a
  substitute, and live project evidence cannot satisfy a build dependency.
- Direct terminology associations retain their original concept ID. Associations
  on the selected concept or its stable predecessor lineage may supply the field
  code; associations on related option concepts remain evidence only.
- Dataset logical choices, exact transaction terminology, and executable values
  are separate model properties.

The transport field demonstrates the terminology rule:

| Property | Values |
|---|---|
| Dataset logical domain | `Bodentransportmittel`, `Lufttransportmittel`, `Ohne` |
| Formal ValueSet | `1.2.276.0.76.11.41@2015-11-17T00:00:00` |
| Executable members | `KTW`, `RTW`, `NAW/NEF/ITW`, `RTH/ITH`, `Ohne`, `Andere` |

The coarse logical choices are no longer emitted as if they were formal codes.
An explicit crosswalk can still map them later if the user accepts the loss of
specificity.

## Fresh versus frozen semantic comparison

| Check | Frozen | Fresh/current compiler |
|---|---:|---:|
| Direct selections | 144 | 144 |
| Model datapoints | 177 | 177 |
| Field-code identities | 82 | 82 (all retained) |
| Effective CDA elements | 986 | 986 |
| Effective CDA attributes | 647 | 647 |
| Assertions | 13 | 13 |
| Mapping evidence covered | 86 | 89 |
| Context-only | 78 | 75 |
| Uncovered | 13 | 13 |
| Executable field proposals | 53 | 54 |
| Shared-target blocks | 6 | 8 |

The two additional shared-target blocks are deliberately not made executable:
mapping evidence exists, but an explicit repetition/merge rule is required
before two fields may write the same physical CDA target. Option-level SNOMED
associations (for example `Neutropenie` within the isolation-reason domain) stay
attached to their option provenance and are not misclassified as field codes.

## Local artifact and closure contract

The crawler records dependency purpose as `structure`, `formal-terminology`,
`expansion-support`, `mapping-evidence`, or `display-evidence`. Extensional
CodeSystem identifiers are recorded as optional display evidence and do not
cause HTTP requests. A CodeSystem used to expand an intensional ValueSet remains
a required dependency.

`crawl_complete` means that retrieval settled; `build_ready` means the exact
required artifact/forms contract is satisfied. Closures created before this
contract are rejected and must be refreshed. In particular, the supplied fresh
archive predates the root-template/readiness fix, so it remains suitable for the
semantic comparison above but is intentionally not accepted as a production
build closure by the revised compiler.

## Code structure

- `retrieval/references.py` extracts typed references and assigns roles.
- `retrieval/resolution.py` owns prefix/link/OID/cache inference.
- `retrieval/artifacts.py` is the manifest-to-compiler boundary.
- `compile/transaction.py`, `compile/cda.py`, and `compile/mapping.py` contain
  the procedural compiler implementations.
- `compile/reports.py` writes the annotated effective CDA XML/Markdown.
- `build/` contains compatibility re-exports for one release; the CLI no longer
  depends on it.

The mapping compiler writes `mapping-audit.json` as the complete structured
decision record. The editable proposal and both Markdown reports are generated
from the same analysis. `cda-expanded-readable.xml` adds human descriptions and
XML comments for CDA targets, source templates, and mapped dataset paths.

## Verification

- Python source and tests compile successfully.
- 84 unit tests pass.
- Fresh model: 57 groups, 120 fields, 144 direct selections, 33 contained
  additions.
- Fresh mapping audit: 177 datapoints, 89 evidence-covered, 75 contextual, 13
  uncovered, 54 executable fields, 8 shared-target blocks.
- No network retrieval was run during this implementation pass.
