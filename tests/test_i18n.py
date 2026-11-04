from __future__ import annotations

import unittest

from decor2hl7.i18n import (
    PROTECTED_TECHNICAL_TERMS,
    Translator,
    catalog_problems,
    configured_output_language,
    load_catalog,
    message, OUTPUT_LANGUAGE,
    message_ids,
    normalize_output_language,
)


class I18nTests(unittest.TestCase):
    def test_catalogs_have_matching_keys_placeholders_and_technical_terms(self) -> None:
        self.assertEqual(catalog_problems(), [])
        self.assertIn("leaf", PROTECTED_TECHNICAL_TERMS)
        self.assertNotIn("Blatt", " ".join(
            Translator("de").text(key)
            for key in ("cli.build_help", "cli.init_mapping_help")
        ))

    def test_packaged_catalogs_use_stable_namespaced_message_ids(self) -> None:
        self.assertIn("cli.workspace_initialized", message_ids("cli"))
        self.assertIn("ui.usage", message_ids("ui"))
        self.assertIn(
            "markdown.dataset_to_cda_mapping_decisions",
            message_ids("markdown"),
        )
        self.assertEqual(set(load_catalog("de")), set(message_ids()))
        self.assertEqual(
            load_catalog("de")["markdown.complete_dataset_tree"],
            "## Vollständiger dataset tree",
        )

    def test_output_language_normalizes_supported_bcp47_variants(self) -> None:
        self.assertEqual(normalize_output_language("de-DE"), "de")
        self.assertEqual(normalize_output_language("EN_us"), "en")
        with self.assertRaisesRegex(ValueError, "unsupported output language"):
            normalize_output_language("fr")

    def test_cli_override_precedes_workspace_configuration(self) -> None:
        settings = {"language": "de-DE", "output": {"language": "de"}}
        self.assertEqual(configured_output_language(settings), "de")
        self.assertEqual(configured_output_language(settings, "en-GB"), "en")
        self.assertEqual(configured_output_language({"language": "de-DE"}), "en")

    def test_translator_formats_parameters(self) -> None:
        self.assertEqual(
            Translator("de").text("cli.workspace_initialized", path="/tmp/ws"),
            "workspace initialisiert: /tmp/ws",
        )

    def test_message_construction_does_not_rewrite_owner_text(self) -> None:
        phrase = "No target-specific defaults are configured."
        token = OUTPUT_LANGUAGE.set("de")
        try:
            localized = message("markdown.build_diagnostics") + "\n\n" + phrase
        finally:
            OUTPUT_LANGUAGE.reset(token)
        self.assertIn("# Build-Diagnostik", localized)
        self.assertIn(phrase, localized)


if __name__ == "__main__":
    unittest.main()
