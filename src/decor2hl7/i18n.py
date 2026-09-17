"""Deterministic localization for decor2hl7-authored UI and report prose."""

from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any, Iterable, Mapping


DEFAULT_OUTPUT_LANGUAGE = "en"
SUPPORTED_OUTPUT_LANGUAGES = frozenset({"en", "de"})

# These words name project/domain concepts.  German prose deliberately keeps
# their English spelling because literal translations such as ``leaf`` ->
# ``Blatt`` are misleading in a dataset/CDA tree.
PROTECTED_TECHNICAL_TERMS = frozenset({
    "ART-DECOR",
    "CDA",
    "ValueSet",
    "dataset",
    "datapoint",
    "leaf",
    "leaves",
    "mapping",
    "model",
    "target",
    "template",
    "workspace",
})


_EN = {
    "cli.help": "show this help message and exit",
    "cli.root_help": "workspace root (default: current directory)",
    "cli.output_language_help": (
        "language for generated Markdown and CLI output (en or de); "
        "overrides output.language in decor2hl7.json"
    ),
    "cli.init_help": "create the workspace skeleton",
    "cli.init_source_language_help": "ART-DECOR retrieval language",
    "cli.list_versions_help": "list ART-DECOR project release keys",
    "cli.set_version_help": "select an ART-DECOR release by KEY from `list-versions`",
    "cli.list_transactions_help": "list transaction keys for the selected release",
    "cli.set_transaction_help": "select a transaction by KEY from `list-transactions`",
    "cli.fetch_help": "fetch the selected transaction specification to closure",
    "cli.build_help": "compile ART-DECOR models and CDA mapping proposal",
    "cli.propose_input_help": "inspect CSV input and propose CSV/code mappings",
    "cli.init_mapping_help": "initialize the shareable dataset-to-CDA mapping bundle",
    "cli.init_site_help": "initialize local CSV/code/site configuration",
    "cli.check_help": "check downloads, compiled models and configuration",
    "cli.check_mapping_help": "validate a shareable CDA mapping without site input",
    "cli.setup_test_help": "prepare isolated generated or authored CSV/config mapping test input",
    "cli.test_mapping_help": "run the isolated CDA mapping fixture",
    "cli.validate_cda_help": "validate CDA XML against the pinned CDA/SDTC XSD and generated Schematron",
    "cli.check_input_help": "validate the external CSV input snapshot without emitting CDA",
    "cli.transform_help": "read, normalize, validate and emit changed documents",
    "cli.send_help": "send emitted documents not already recorded as sent",
    "cli.run_help": "perform the runtime pipeline",
    "cli.status_help": "show sent/pending document state",
    "cli.prefix_help": "ART-DECOR project prefix",
    "cli.filter_help": "optional text filter",
    "cli.identifier_help": "KEY shown by the corresponding list command",
    "cli.ipv6_help": "diagnostic override; ART-DECOR uses IPv4 by default",
    "cli.retry_missing_help": "retry artifacts previously recorded as missing",
    "cli.offline_help": "use cached specification files only; make no HTTP requests",
    "cli.max_requests_help": "maximum number of network requests for this crawl",
    "cli.fetch_degraded_help": (
        "return nonzero when the retrieval closure is degraded; the crawl "
        "cannot yet tell which gaps a build consumes, so use "
        "`build --fail-on-degraded` to gate on that"
    ),
    "cli.build_degraded_help": (
        "return nonzero when a degraded artifact is consulted by this build "
        "(build-diagnostics.json `build_degraded`)"
    ),
    "cli.strict_specializations_help": (
        "reject a CDA template whose explicit constraints weaken a declared SPEC parent"
    ),
    "cli.input_help": "CSV input directory; overrides decor2hl7.json input.directory",
    "cli.join_column_help": "record-join column used in proposed CSV mappings",
    "cli.cda_mapping_help": (
        "cda-mapping.json (or its directory); overrides the selected workspace bundle"
    ),
    "cli.site_config_help": (
        "site config bundle directory (or site.json); CSV/code mappings are read beside it"
    ),
    "cli.reset_help": (
        "replace the reviewed mapping with the current generated proposal "
        "and refresh its model lock"
    ),
    "cli.test_dir_help": "test fixture directory; defaults to test/<release>/<transaction>",
    "cli.scenario_help": "authored scenario-set directory containing scenario.json and input/",
    "cli.force_help": "replace generated input/config/expected files",
    "cli.files_help": "CDA XML document(s) to validate",
    "cli.report_help": "report path without extension; defaults below model/",
    "cli.out_help": "result directory; defaults to the fixture's out directory",
    "cli.send_flag_help": "send documents after a successful transformation",
    "cli.workspace_initialized": "workspace initialized: {path}",
    "cli.aborted": "aborted by user",
    "cli.error": "error: {message}",
}


_DE = {
    "cli.help": "diese Hilfe anzeigen und beenden",
    "cli.root_help": "workspace root (Standard: aktuelles Verzeichnis)",
    "cli.output_language_help": (
        "Sprache für generiertes Markdown und CLI-Ausgaben (en oder de); "
        "überschreibt output.language in decor2hl7.json"
    ),
    "cli.init_help": "workspace-Struktur anlegen",
    "cli.init_source_language_help": "ART-DECOR retrieval language",
    "cli.list_versions_help": "release keys des ART-DECOR project auflisten",
    "cli.set_version_help": "ART-DECOR release über KEY aus `list-versions` auswählen",
    "cli.list_transactions_help": "transaction keys des gewählten release auflisten",
    "cli.set_transaction_help": "transaction über KEY aus `list-transactions` auswählen",
    "cli.fetch_help": "gewählte transaction specification vollständig abrufen",
    "cli.build_help": "ART-DECOR models und CDA mapping proposal kompilieren",
    "cli.propose_input_help": "CSV input prüfen und CSV/code mappings vorschlagen",
    "cli.init_mapping_help": "teilbares dataset-to-CDA mapping bundle initialisieren",
    "cli.init_site_help": "lokale CSV/code/site configuration initialisieren",
    "cli.check_help": "Downloads, kompilierte models und configuration prüfen",
    "cli.check_mapping_help": "teilbares CDA mapping ohne site input validieren",
    "cli.setup_test_help": "isolierten generierten oder authored CSV/config mapping test vorbereiten",
    "cli.test_mapping_help": "isoliertes CDA mapping fixture ausführen",
    "cli.validate_cda_help": "CDA XML gegen gepinnte CDA/SDTC XSD und generiertes Schematron validieren",
    "cli.check_input_help": "externen CSV input snapshot ohne CDA-Ausgabe validieren",
    "cli.transform_help": "geänderte Dokumente lesen, normalisieren, validieren und ausgeben",
    "cli.send_help": "noch nicht als gesendet erfasste Dokumente senden",
    "cli.run_help": "runtime pipeline ausführen",
    "cli.status_help": "Status gesendeter/ausstehender Dokumente anzeigen",
    "cli.prefix_help": "ART-DECOR project prefix",
    "cli.filter_help": "optionaler Textfilter",
    "cli.identifier_help": "KEY aus dem entsprechenden list-Befehl",
    "cli.ipv6_help": "diagnostischer Override; ART-DECOR verwendet standardmäßig IPv4",
    "cli.retry_missing_help": "zuvor als fehlend erfasste artifacts erneut abrufen",
    "cli.offline_help": "nur gecachte specification-Dateien verwenden; keine HTTP-Requests senden",
    "cli.max_requests_help": "maximale Zahl von Netzwerk-Requests für diesen crawl",
    "cli.fetch_degraded_help": (
        "ungleich null zurückgeben, wenn die retrieval closure degraded ist; "
        "der crawl kennt noch nicht die von einem build verwendeten gaps, daher "
        "dafür `build --fail-on-degraded` verwenden"
    ),
    "cli.build_degraded_help": (
        "ungleich null zurückgeben, wenn dieser build ein degraded artifact verwendet "
        "(build-diagnostics.json `build_degraded`)"
    ),
    "cli.strict_specializations_help": (
        "ein CDA template ablehnen, dessen explizite constraints einen deklarierten SPEC parent abschwächen"
    ),
    "cli.input_help": "CSV input-Verzeichnis; überschreibt decor2hl7.json input.directory",
    "cli.join_column_help": "record-join-Spalte für vorgeschlagene CSV mappings",
    "cli.cda_mapping_help": (
        "cda-mapping.json (oder dessen Verzeichnis); überschreibt das gewählte workspace bundle"
    ),
    "cli.site_config_help": (
        "site config bundle-Verzeichnis (oder site.json); CSV/code mappings werden daneben gelesen"
    ),
    "cli.reset_help": (
        "reviewtes mapping durch das aktuelle generierte proposal ersetzen "
        "und dessen model lock aktualisieren"
    ),
    "cli.test_dir_help": "test fixture-Verzeichnis; Standard ist test/<release>/<transaction>",
    "cli.scenario_help": "authored scenario-set-Verzeichnis mit scenario.json und input/",
    "cli.force_help": "generierte input/config/expected-Dateien ersetzen",
    "cli.files_help": "zu validierende CDA XML-Dokumente",
    "cli.report_help": "report-Pfad ohne Erweiterung; Standard unter model/",
    "cli.out_help": "result-Verzeichnis; Standard ist das out-Verzeichnis des fixture",
    "cli.send_flag_help": "Dokumente nach erfolgreicher Transformation senden",
    "cli.workspace_initialized": "workspace initialisiert: {path}",
    "cli.aborted": "durch Benutzer abgebrochen",
    "cli.error": "Fehler: {message}",
}


CATALOGS: Mapping[str, Mapping[str, str]] = {"en": _EN, "de": _DE}


def normalize_output_language(value: Any) -> str:
    """Normalize a supported BCP-47-like output locale to its base language."""
    text = str(value or DEFAULT_OUTPUT_LANGUAGE).strip().replace("_", "-")
    language = text.split("-", 1)[0].casefold()
    if language not in SUPPORTED_OUTPUT_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_OUTPUT_LANGUAGES))
        raise ValueError(
            f"unsupported output language {value!r}; choose one of: {supported}"
        )
    return language


def configured_output_language(
    settings: Mapping[str, Any] | None,
    override: Any = None,
) -> str:
    """Resolve CLI override, workspace setting, then the stable default."""
    if override not in (None, ""):
        return normalize_output_language(override)
    output = settings.get("output", {}) if isinstance(settings, Mapping) else {}
    configured = output.get("language") if isinstance(output, Mapping) else None
    return normalize_output_language(configured or DEFAULT_OUTPUT_LANGUAGE)


def _placeholders(value: str) -> set[str]:
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(value)
        if field_name
    }


def catalog_problems() -> list[str]:
    """Return missing keys, placeholder drift, and translated technical terms."""
    errors: list[str] = []
    base_keys = set(_EN)
    for language, catalog in CATALOGS.items():
        missing = base_keys - set(catalog)
        extra = set(catalog) - base_keys
        if missing:
            errors.append(f"{language}: missing message keys: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{language}: unknown message keys: {', '.join(sorted(extra))}")
        for key in base_keys & set(catalog):
            if _placeholders(_EN[key]) != _placeholders(catalog[key]):
                errors.append(f"{language}:{key}: placeholders differ from English")
            if language == "de":
                for term in PROTECTED_TECHNICAL_TERMS:
                    if term in _EN[key] and term not in catalog[key]:
                        errors.append(
                            f"de:{key}: protected technical term {term!r} was changed"
                        )
    for catalog_name, replacements in (
        ("ui", _DE_UI_REPLACEMENTS),
        ("markdown", _DE_MARKDOWN_REPLACEMENTS),
    ):
        for source, translated in replacements.items():
            for term in PROTECTED_TECHNICAL_TERMS:
                if term in source and term not in translated:
                    errors.append(
                        f"de:{catalog_name}: protected technical term {term!r} "
                        f"was changed in {source!r}"
                    )
    return errors


@dataclass(frozen=True)
class Translator:
    """Format one complete catalog message in the selected output language."""

    language: str = DEFAULT_OUTPUT_LANGUAGE

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", normalize_output_language(self.language))

    def text(self, key: str, **values: Any) -> str:
        try:
            template = CATALOGS[self.language][key]
        except KeyError as error:
            raise ValueError(
                f"missing {self.language!r} translation for message {key!r}"
            ) from error
        return template.format(**values)


_DE_UI_REPLACEMENTS = {
    "usage:": "Verwendung:",
    "positional arguments:": "Positionsargumente:",
    "options:": "Optionen:",
    "show this help message and exit": "diese Hilfe anzeigen und beenden",
    "show program's version number and exit": (
        "Programmversion anzeigen und beenden"
    ),
    "select with:": "auswählen mit:",
    "selected release:": "release ausgewählt:",
    "selected transaction:": "transaction ausgewählt:",
    "transaction selection cleared;": "transaction selection gelöscht;",
    "workspace initialized:": "workspace initialisiert:",
    "retrieval summary:": "retrieval-Zusammenfassung:",
    "transaction closure:": "transaction closure:",
    "build resources": "build resources",
    "evidence resources": "evidence resources",
    "warning:": "Warnung:",
    "error:": "Fehler:",
    "model datapoints:": "model datapoints:",
    "code mapping defaults:": "code mapping defaults:",
    "aliases across": "Aliasse in",
    "coded fields": "codierten Feldern",
    "reachable templates": "erreichbare templates",
    "physical named targets": "benannte physische targets",
    "logical mapped datapoints": "logische gemappte datapoints",
    "CSV mapped proposal:": "CSV mapping proposal:",
    "input mapping proposals written to:": "input mapping proposals geschrieben nach:",
    "input snapshot inspected:": "input snapshot geprüft:",
    "created ": "erstellt ",
    "updated ": "aktualisiert ",
    "kept    ": "beibehalten ",
    "reset   ": "zurückgesetzt ",
    "review  ": "prüfen  ",
    "configuration errors:": "configuration-Fehler:",
    "configuration: OK": "configuration: OK",
    "CDA mapping errors:": "CDA mapping-Fehler:",
    "CDA mapping: OK": "CDA mapping: OK",
    "CDA source endpoint parity: unavailable": "CDA source endpoint parity: nicht verfügbar",
    "unexpected missing": "unerwartet fehlend",
    "fixed structural": "fixed structural",
    "reviewed replacements": "reviewte replacements",
    "required unmapped CDA leaves:": "erforderliche ungemappte CDA leaves:",
    "CDA unresolved templates:": "CDA unresolved templates:",
    "unavailable dependency artifacts": "nicht verfügbare dependency artifacts",
    "CDA site requirements:": "CDA site requirements:",
    "site config required:": "site config erforderlich:",
    "test fixture:": "test fixture:",
    "authored scenario set:": "authored scenario set:",
    "generated ": "generiert ",
    "model datapoint columns": "model datapoint-Spalten",
    "CDA-mapped fields covered by input:": "durch input abgedeckte CDA-mapped fields:",
    "records:": "Datensätze:",
    "errors:": "Fehler:",
    "warnings:": "Warnungen:",
    "input:": "input:",
    "skip ": "überspringe ",
    "send failed ": "Senden fehlgeschlagen ",
    "sent ": "gesendet ",
    "documents were emitted but not sent; pass --send to transmit them": (
        "Dokumente wurden ausgegeben, aber nicht gesendet; mit --send übertragen"
    ),
    "SELECTED": "AUSGEWÄHLT",
    "STATUS": "STATUS",
}


_DE_MARKDOWN_REPLACEMENTS = {
    "# CDA Mapping Details": "# CDA Mapping-Details",
    "# CDA Mapping": "# CDA Mapping",
    "# Datapoint analysis": "# Datapoint-Analyse",
    "# Structural group context": "# Structural group-Kontext",
    "# Dataset-to-CDA mapping decisions": "# Dataset-to-CDA mapping-Entscheidungen",
    "# Accepted mappings": "# Akzeptierte mappings",
    "# Dataset-to-CDA coverage trees": "# Dataset-to-CDA coverage trees",
    "# Extended dataset-to-CDA coverage trees": "# Erweiterte dataset-to-CDA coverage trees",
    "# Expanded CDA template": "# Erweitertes CDA template",
    "# CSV-to-dataset mapping": "# CSV-to-dataset mapping",
    "# Input-value-to-dataset-code mapping": "# Input-value-to-dataset-code mapping",
    "# Build diagnostics": "# Build-Diagnostik",
    "# Conformance validation": "# Conformance-Validierung",
    "# CDA mapping test": "# CDA mapping-Test",
    "## Sections and entities": "## Abschnitte und Entities",
    "## Unresolved dataset tree": "## Ungeklärter dataset tree",
    "## CDA review tree": "## CDA review tree",
    "## Decisions": "## Entscheidungen",
    "## Summary by evidence": "## Zusammenfassung nach evidence",
    "## Executable structural rules": "## Ausführbare structural rules",
    "### Qualification": "### Qualifikation",
    "### Primary evidence": "### Primäre evidence",
    "### Confidence": "### Konfidenz",
    "## Complete dataset tree": "## Vollständiger dataset tree",
    "## Complete CDA coverage tree": "## Vollständiger CDA coverage tree",
    "## Complete physical CDA coverage tree": "## Vollständiger physischer CDA coverage tree",
    "## Accepted structural rules": "## Akzeptierte structural rules",
    "## Accepted narrative-only rules": "## Akzeptierte narrative-only rules",
    "## Reviewed intentional non-mappings": "## Reviewte absichtliche non-mappings",
    "## Accepted required-CDA completion": "## Akzeptierte required-CDA completion",
    "## Required site configuration": "## Erforderliche site configuration",
    "### Configuration still required": "### Weiterhin erforderliche configuration",
    "## Degraded artifacts (crawl)": "## Degraded artifacts (crawl)",
    "## Degraded artifacts affecting this build": "## Degraded artifacts, die diesen build betreffen",
    "## Unresolved CDA template references": "## Ungeklärte CDA template references",
    "## Unavailable CDA editor prototypes": "## Nicht verfügbare CDA editor prototypes",
    "## CDA constraint diagnostics": "## CDA constraint-Diagnostik",
    "## Stages": "## Stages",
    "## Diagnostics": "## Diagnostik",
    "## Errors": "## Fehler",
    "## Warnings": "## Warnungen",
    "## Scope": "## Umfang",
    "#### Evidence candidates": "#### Evidence candidates",
    "#### Possible targets (unproven)": "#### Possible targets (unbewiesen)",
    "This is the working report for completing `cda-mapping.json`. It shows the selected target,\nwhy it was selected, and the strongest alternatives. Full provenance is in\n`cda-mapping-details.md`.": (
        "Dies ist der Arbeitsbericht zum Vervollständigen von `cda-mapping.json`. Er zeigt den ausgewählten target,\nwarum er ausgewählt wurde, und die stärksten Alternativen. Die vollständige Provenienz steht in\n`cda-mapping-details.md`."
    ),
    "This is the evidence appendix for `cda-mapping.json`. Edit the JSON mapping,\nnot this generated report. Review the generated proposal in `cda-mapping.proposed.md` or the initialized reviewed bundle in `cda-mapping.md`.": (
        "Dies ist der evidence-Anhang für `cda-mapping.json`. Das JSON mapping bearbeiten,\nnicht diesen generierten Bericht. Das generierte proposal steht in `cda-mapping.proposed.md`, das initialisierte reviewte bundle in `cda-mapping.md`."
    ),
    "**Legend:** `YES` = concrete CDA evidence; `PARTIAL` = structural context only;\n`STRONG`/`MEDIUM`/`WEAK` describe evidence confidence independently from executability.": (
        "**Legende:** `YES` = konkrete CDA evidence; `PARTIAL` = nur structural context;\n`STRONG`/`MEDIUM`/`WEAK` beschreiben die evidence-Konfidenz unabhängig von der Ausführbarkeit."
    ),
    "Annotated template skeleton:": "Kommentiertes template skeleton:",
    "Edit `cda-mapping.json`, not this report.": "`cda-mapping.json` bearbeiten, nicht diesen Bericht.",
    "Edit `csv-mapping.json`. Each row connects one dataset datapoint to one\ninput column; parsing is shown only when it changes the input value.": (
        "`csv-mapping.json` bearbeiten. Jede Zeile verbindet einen dataset datapoint mit einer\n"
        "input-Spalte; Parsing wird nur gezeigt, wenn es den input-Wert verändert."
    ),
    "Edit `codes-mapping.json`. Canonical dataset values are accepted unchanged;\nthe tables therefore show only aliases that require translation and unresolved\ninput values observed in the CSV files. An unresolved value in a finite domain\nis an input error; source normalization does not choose an HL7 missing-data code.": (
        "`codes-mapping.json` bearbeiten. Kanonische dataset-Werte werden unverändert akzeptiert;\n"
        "die Tabellen zeigen deshalb nur zu übersetzende Aliasse und ungeklärte\n"
        "input-Werte aus den CSV-Dateien. Ein ungeklärter Wert in einer endlichen Domain\n"
        "ist ein input-Fehler; source normalization wählt keinen HL7 missing-data code."
    ),
    "This file is the manual decision workbench. It contains only unresolved dataset datapoints and the CDA leaves that may help resolve them. Accepted mappings are documented in `cda-mapping-details.md`; the exhaustive source and target trees are in `cda-mapping-trees.md`.": (
        "Diese Datei ist die manuelle Entscheidungsoberfläche. Sie enthält nur ungeklärte dataset datapoints und CDA leaves, die zur Klärung beitragen können. Akzeptierte mappings stehen in `cda-mapping-details.md`; die vollständigen source- und target-trees stehen in `cda-mapping-trees.md`."
    ),
    "Reviewed mappings, narrative-only decisions, and intentional nulls are resolved decisions and therefore omitted here. Their counts remain in the headline and their details remain in `cda-mapping-details.md` and the exhaustive trees.": (
        "Reviewte mappings, narrative-only Entscheidungen und absichtliche null-Werte sind geklärt und werden hier ausgelassen. Ihre Zahlen bleiben in der Überschrift, ihre Details in `cda-mapping-details.md` und den vollständigen trees."
    ),
    "Nothing in a candidate list is selected automatically. Edit `cda-mapping.json`. Do not edit the XML-like template skeletons in this report; all trees, tables, and excerpts below are generated read-only evidence.": (
        "Aus einer candidate-Liste wird nichts automatisch ausgewählt. `cda-mapping.json` bearbeiten. Die XML-ähnlichen template skeletons in diesem Bericht nicht bearbeiten; alle folgenden trees, Tabellen und Auszüge sind generierte read-only evidence."
    ),
    "- ! **Evidence candidate** — related evidence exists, but no executable mapping is selected.": (
        "- ! **Evidence candidate** — zugehörige evidence ist vorhanden, aber kein ausführbares mapping ist ausgewählt."
    ),
    "- ? **Possible target (unproven)** — type-compatible and reachable, but not semantic evidence.": (
        "- ? **Possible target (unbewiesen)** — typkompatibel und erreichbar, aber keine semantic evidence."
    ),
    "- × **No generated target** — manual template review has not yet produced a candidate.": (
        "- × **No generated target** — das manuelle template review hat noch keinen candidate ergeben."
    ),
    "Dataset decisions": "Dataset-Entscheidungen",
    "no generated target inventory": "kein generiertes target inventory",
    "Dataset datapoint:": "Dataset datapoint:",
    "No usable CDA target evidence was found for this dataset datapoint.": (
        "Für diesen dataset datapoint wurde keine verwendbare CDA target evidence gefunden."
    ),
    "Find a representation manually, or retain `null`.": (
        "Eine Repräsentation manuell bestimmen oder `null` beibehalten."
    ),
    "Define the required repetition or merge rule.": (
        "Die erforderliche repetition- oder merge-rule definieren."
    ),
    "Choose one selectable target in `cda-mapping.json`, or retain `null`.": (
        "Einen auswählbaren target in `cda-mapping.json` wählen oder `null` beibehalten."
    ),
    "Use the evidence to find a value-bearing target, or retain `null`.": (
        "Mit der evidence einen werttragenden target bestimmen oder `null` beibehalten."
    ),
    "This report is exhaustive. The status gutter is the first column of every leaf line; hierarchy branches remain visually independent from status.": (
        "Dieser Bericht ist vollständig. Die Statusspalte ist die erste Spalte jeder leaf-Zeile; Hierarchieäste bleiben visuell unabhängig vom Status."
    ),
    "- ✓ **Mapped** — selected executable mapping.": (
        "- ✓ **Mapped** — ausgewähltes ausführbares mapping."
    ),
    "- ! **Suggested** — a writable CDA leaf exists, but no executable mapping is selected.": (
        "- ! **Suggested** — eine beschreibbare CDA leaf ist vorhanden, aber kein ausführbares mapping ist ausgewählt."
    ),
    "- × **No target** — no suitable writable CDA leaf was found.": (
        "- × **No target** — es wurde keine passende beschreibbare CDA leaf gefunden."
    ),
    "- = **Intentionally unmapped** — the field remains `null` by an explicit reviewed decision.": (
        "- = **Intentionally unmapped** — das field bleibt durch eine explizite reviewte Entscheidung `null`."
    ),
    "- ○ **No source** — a reportable writable CDA leaf has no dataset counterpart.": (
        "- ○ **No source** — eine berichtsfähige beschreibbare CDA leaf hat kein dataset counterpart."
    ),
    "- ▲ **Required gap** — an active owner-required CDA value has no portable configured source; this combines with its coverage symbol (for example `○▲`).": (
        "- ▲ **Required gap** — ein aktiver owner-required CDA-Wert hat keine portable konfigurierte source; dies wird mit seinem coverage-Symbol kombiniert (zum Beispiel `○▲`)."
    ),
    "- ◆ **Site-owned requirement** — an active owner-required CDA value is explicitly delegated to the named `cda.values` or `cda.fallback_if_active` site channel; `○◆` means configuration-owned construction with no dataset-field source.": (
        "- ◆ **Site-owned requirement** — ein aktiver owner-required CDA-Wert ist explizit an den benannten `cda.values`- oder `cda.fallback_if_active`-site channel delegiert; `○◆` bedeutet configuration-owned construction ohne dataset-field source."
    ),
    "- ✓! **Mapped and suggested** — one datapoint is selected and another remains under review.": (
        "- ✓! **Mapped and suggested** — ein datapoint ist ausgewählt, ein anderer bleibt im review."
    ),
    "The CDA tree excludes generic datatype-expansion plumbing and fixed, conditional-fixed, or system-supplied values. Those remain available in `cda.json`.": (
        "Der CDA tree schließt generische datatype-expansion-Strukturen sowie fixed, conditional-fixed oder system-supplied Werte aus. Diese bleiben in `cda.json` verfügbar."
    ),
    "The required-gap and site-ownership markers evaluate the mapping rendered for this report. `◆` records a portable ownership declaration; it does not claim that a concrete site value was checked.": (
        "Die required-gap- und site-ownership-Marker bewerten das für diesen Bericht gerenderte mapping. `◆` dokumentiert eine portable ownership declaration; der Marker behauptet nicht, dass ein konkreter site-Wert geprüft wurde."
    ),
    "The primary tree line is kept compact. Indented evidence lines mean:": (
        "Die primäre tree-Zeile bleibt kompakt. Eingerückte evidence-Zeilen bedeuten:"
    ),
    "- `S:` source concept OID, stable dataset path, logical type and cardinality;": (
        "- `S:` source concept OID, stabiler dataset path, logischer Typ und cardinality;"
    ),
    "- `T:` owning template/revision, template-relative XPath, CDA datatype, cardinality, conformance and required ValueSet where available;": (
        "- `T:` owning template/revision, template-relative XPath, CDA datatype, cardinality, conformance und erforderliches ValueSet, soweit verfügbar;"
    ),
    "- `R:` executable transform, structural rule, reviewed default or site responsibility;": (
        "- `R:` ausführbarer transform, structural rule, reviewter default oder site responsibility;"
    ),
    "- `G:` reviewed non-transmission or unresolved evidence gate and reopening condition.": (
        "- `G:` reviewte non-transmission oder ungeklärtes evidence gate mit reopening condition."
    ),
    "Status: `✓` mapped; `!` suggested but not selected; `×` no approved target; `=` intentionally unmapped; `○` physical CDA leaf without a dataset counterpart; `D` exact reviewed target default; `▲` unresolved required construction; `◆` site-owned required construction. Markers may combine.": (
        "Status: `✓` mapped; `!` suggested, aber nicht ausgewählt; `×` kein freigegebener target; `=` intentionally unmapped; `○` physische CDA leaf ohne dataset counterpart; `D` exakter reviewter target default; `▲` ungeklärte required construction; `◆` site-owned required construction. Marker können kombiniert werden."
    ),
    "Logical targets identify separately reviewable occurrences. When several logical occurrences write one repeatable CDA leaf, the report also names the shared physical target. The inverse no-source count is therefore computed after logical-to-physical resolution.": (
        "Logical targets kennzeichnen separat reviewbare occurrences. Wenn mehrere logische occurrences eine wiederholbare CDA leaf schreiben, nennt der Bericht auch den gemeinsamen physischen target. Der inverse no-source-Zähler wird deshalb nach der logical-to-physical resolution berechnet."
    ),
    "This section records **": "Dieser Abschnitt dokumentiert **",
    " executable dataset datapoints writing **": " ausführbare dataset datapoints, die **",
    " logical CDA leaves. Edit `cda-mapping.json`; the XML excerpts below are read-only consequences of that configuration.": (
        " logische CDA leaves schreiben. `cda-mapping.json` bearbeiten; die folgenden XML-Auszüge sind read-only Folgen dieser configuration."
    ),
    "Abridged configuration excerpt — edit the corresponding entry in the full JSON file:": (
        "Gekürzter configuration-Auszug — den entsprechenden Eintrag in der vollständigen JSON-Datei bearbeiten:"
    ),
    "Resulting CDA placement — read-only consequence of the JSON configuration:": (
        "Resultierende CDA-Platzierung — read-only Folge der JSON configuration:"
    ),
    "Text in `{braces}` names a generated CDA datapoint. It is an explanatory placeholder, not XML to enter manually.": (
        "Text in `{braces}` benennt einen generierten CDA datapoint. Er ist ein erklärender placeholder und kein manuell einzugebendes XML."
    ),
    "Every card corresponds to an explicit `null` entry in `cda-mapping.json`. Retaining `null` is valid when the clinical representation remains unproven.": (
        "Jede Karte entspricht einem expliziten `null`-Eintrag in `cda-mapping.json`. `null` beizubehalten ist gültig, solange die klinische Repräsentation unbewiesen bleibt."
    ),
    "No unresolved datapoint currently has a generated CDA candidate.": "Kein ungeklärter datapoint hat derzeit einen generierten CDA candidate.",
    "No dataset datapoints currently require target selection.": "Derzeit benötigt kein dataset datapoint eine target-Auswahl.",
    "No semantic evidence candidate was generated.": "Es wurde kein semantic evidence candidate generiert.",
    "No usable CDA target evidence was found for this datapoint.": (
        "Für diesen datapoint wurde keine verwendbare CDA target evidence gefunden."
    ),
    "Selectable values established by the mapping evidence:": "Durch mapping evidence bestätigte auswählbare Werte:",
    "Example edit (choose only after review):": "Beispieländerung (nur nach review auswählen):",
    "Current editable state:": "Aktueller bearbeitbarer Zustand:",
    "These type-compatible writable descendants are an admissibility inventory, not semantic mapping evidence. Nothing in this list is selected automatically.": (
        "Diese typkompatiblen beschreibbaren descendants sind ein admissibility inventory, keine semantic mapping evidence. Aus dieser Liste wird nichts automatisch ausgewählt."
    ),
    "These rules create or coordinate CDA occurrences; they are configuration, not XML edits.": "Diese rules erzeugen oder koordinieren CDA occurrences; sie sind configuration, keine XML-Änderungen.",
    "These reviewed rules preserve source wording in a section narrative without claiming a structured CDA value mapping.": "Diese reviewten rules bewahren source wording in einer section narrative, ohne ein strukturiertes CDA value mapping zu behaupten.",
    "These dataset fields remain explicit `null` selections by review, not because the proposal engine forgot them.": "Diese dataset fields bleiben durch review explizite `null` selections, nicht weil die proposal engine sie vergessen hat.",
    "The following reviewed targets use a more specific default:": "Die folgenden reviewten targets verwenden einen spezifischeren default:",
    "General rule: an active required nullable leaf without a mapped value receives `nullFlavor=\"NI\"`. A real mapped value always takes precedence. Mandatory (`M`) values cannot use this rule.": (
        "Allgemeine rule: Eine aktive required nullable leaf ohne gemappten Wert erhält `nullFlavor=\"NI\"`. Ein realer gemappter Wert hat immer Vorrang. Mandatory (`M`) Werte können diese rule nicht verwenden."
    ),
    "No target-specific defaults are configured.": "Es sind keine target-spezifischen defaults konfiguriert.",
    "No CDA values are explicitly delegated to site configuration.": "Keine CDA-Werte sind ausdrücklich an site configuration delegiert.",
    "All active mandatory CDA slots have a configured value source.": "Alle aktiven verpflichtenden CDA slots haben eine konfigurierte value source.",
    "Mapped automatically:": "Automatisch gemappt:",
    "Candidate scores are suggestions only. Unmapped rows remain `null` in the JSON\nuntil a user chooses a source column.": "Candidate scores sind nur Vorschläge. Ungemappte Zeilen bleiben `null` im JSON,\nbis ein Benutzer eine source-Spalte auswählt.",
    "Review candidates:": "Candidates prüfen:",
    "No aliases require configuration.": "Keine Aliasse benötigen configuration.",
    "canonical values accepted directly;": "kanonische Werte direkt akzeptiert;",
    "observed input values mapped.": "beobachtete input-Werte gemappt.",
    "**UNRESOLVED — outside executable dataset domain**": "**UNRESOLVED — außerhalb der ausführbaren dataset domain**",
    "The compiler used only downloaded artifacts with their exact requested identity. It did not replace a missing revision with another revision.": "Der Compiler verwendete nur heruntergeladene artifacts mit ihrer exakt angeforderten Identität. Eine fehlende revision wurde nicht durch eine andere revision ersetzt.",
    "These `SPEC` targets are optional comparison evidence. Their absence does not omit executable child-template constraints.": "Diese `SPEC` targets sind optionale comparison evidence. Ihr Fehlen lässt keine ausführbaren child-template constraints aus.",
    "No dependency gaps were detected.": "Es wurden keine dependency gaps erkannt.",
    "Package validation is independent of dataset-to-CDA mapping coverage. A legal structural slot is not semantic mapping evidence.": "Package validation ist unabhängig von dataset-to-CDA mapping coverage. Ein legaler structural slot ist keine semantic mapping evidence.",
    "No conformance diagnostics were emitted.": "Es wurde keine Conformance-Diagnostik ausgegeben.",
    "This test uses the production ingestion, normalization, validation, binding, and CDA rendering code.": "Dieser Test verwendet den produktiven Code für ingestion, normalization, validation, binding und CDA rendering.",
    "It does not write production state and never invokes transport.": "Er schreibt keinen production state und ruft transport nie auf.",
    "The companion XML is the effective compiled constraint tree. It retains\nhuman-readable descriptions and inserts XML comments at nodes with named\nCDA targets, source-template identities, or mapped dataset paths.": "Das zugehörige XML ist der effektive kompilierte constraint tree. Es bewahrt\nlesbare Beschreibungen und fügt XML-Kommentare an nodes mit benannten\nCDA targets, source-template identities oder gemappten dataset paths ein.",
    "Mapping decisions and alternatives are recorded in `mapping-audit.json`.": "Mapping-Entscheidungen und Alternativen stehen in `mapping-audit.json`.",
    "Target CDA template:": "Target CDA template:",
    "Transaction:": "Transaction:",
    "Dataset datapoints:": "Dataset datapoints:",
    "CDA covered:": "CDA abgedeckt:",
    "Partial:": "Partiell:",
    "Not covered:": "Nicht abgedeckt:",
    "Required items:": "Required items:",
    "Named CDA targets:": "Benannte CDA targets:",
    "Renderable targets:": "Renderbare targets:",
    "Evidence-linked items:": "Evidence-verknüpfte items:",
    "Executable proposal:": "Ausführbares proposal:",
    "Unresolved templates:": "Ungeklärte templates:",
    "| Name in dataset | `model.json` datapoint | `cda-mapping.json` target | Name in CDA template | Status |": "| Name im dataset | `model.json` datapoint | `cda-mapping.json` target | Name im CDA template | Status |",
    "| Dataset datapoint | CSV source and column | Parsing or review note |": "| Dataset datapoint | CSV source und Spalte | Parsing- oder review-Hinweis |",
    "| Input value | Dataset value |": "| Input-Wert | Dataset-Wert |",
    "| CDA target | Site configuration | Reason |": "| CDA target | Site configuration | Begründung |",
    "| Relation | Template | Requested revision |": "| Relation | Template | Angeforderte revision |",
    "| Relation | Template | Requested revision | Used by |": "| Relation | Template | Angeforderte revision | Verwendet von |",
    "| Artifact | Roles | Status | Build effect |": "| Artifact | Roles | Status | Build-Auswirkung |",
    "| Artifact | Consulted by | Status | Build effect |": "| Artifact | Verwendet von | Status | Build-Auswirkung |",
    "| Severity | Code | Template path | Detail |": "| Schweregrad | Code | Template path | Detail |",
    "| Severity | Phase | Location | Message |": "| Schweregrad | Phase | Ort | Meldung |",
    "Generated documents:": "Generierte Dokumente:",
    "Model fields represented in CSV:": "In CSV dargestellte model fields:",
    "CDA-mapped fields:": "CDA-mapped fields:",
    "Fields exercised after normalization:": "Nach normalization ausgeübte fields:",
    "Authored scenario set:": "Authored scenario set:",
    "Reachable template revisions:": "Erreichbare template revisions:",
    "Effective elements:": "Effektive Elemente:",
    "Effective attributes:": "Effektive Attribute:",
    "Named targets:": "Benannte targets:",
    "Writable value targets:": "Beschreibbare value targets:",
    "Executable dataset mappings:": "Ausführbare dataset mappings:",
    "Showing the first ": "Angezeigt werden die ersten ",
    " diagnostics. The complete list is in ": " Diagnosen. Die vollständige Liste steht in ",
    "**Why review is required:**": "**Warum review erforderlich ist:**",
    "**Action:**": "**Aktion:**",
    "no suitable writable CDA leaf": "keine passende beschreibbare CDA leaf",
    "no dataset counterpart": "kein dataset counterpart",
    "intentionally unmapped": "absichtlich unmapped",
    "read-only": "read-only",
}


def _replace_all(value: str, replacements: Mapping[str, str]) -> str:
    for source in sorted(replacements, key=len, reverse=True):
        value = value.replace(source, replacements[source])
    return value


def localize_ui(value: str, output_language: str = "en") -> str:
    """Localize one decor2hl7-authored terminal message."""
    language = normalize_output_language(output_language)
    return value if language == "en" else _replace_all(value, _DE_UI_REPLACEMENTS)


def _protected_markdown_strings(values: Iterable[Any]) -> set[str]:
    protected: set[str] = set()
    visited: set[int] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if any(source in item for source in _DE_MARKDOWN_REPLACEMENTS):
                protected.add(item)
            return
        if isinstance(item, Mapping):
            identity = id(item)
            if identity in visited:
                return
            visited.add(identity)
            for key, nested in item.items():
                visit(key)
                visit(nested)
            return
        if isinstance(item, (list, tuple, set, frozenset)):
            identity = id(item)
            if identity in visited:
                return
            visited.add(identity)
            for nested in item:
                visit(nested)

    for value in values:
        visit(value)
    return protected


def localize_markdown(
    value: str,
    output_language: str = "en",
    *,
    protected_values: Iterable[Any] = (),
) -> str:
    """Localize generated Markdown without translating supplied owner content."""
    language = normalize_output_language(output_language)
    if language == "en":
        return value
    tokens: dict[str, str] = {}
    for index, source in enumerate(
        sorted(_protected_markdown_strings(protected_values), key=len, reverse=True)
    ):
        token = f"\x00decor2hl7-protected-{index}\x00"
        while token in value:
            token += "x"
        if source in value:
            value = value.replace(source, token)
            tokens[token] = source
    value = _replace_all(value, _DE_MARKDOWN_REPLACEMENTS)
    for token, source in tokens.items():
        value = value.replace(token, source)
    return value
