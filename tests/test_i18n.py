from __future__ import annotations

import unittest

from decor2hl7.i18n import (
    PROTECTED_TECHNICAL_TERMS,
    Translator,
    catalog_problems,
    configured_output_language,
    localize_markdown,
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

    def test_markdown_localization_preserves_supplied_owner_text(self) -> None:
        phrase = "No target-specific defaults are configured."
        localized = localize_markdown(
            f"# Build diagnostics\n\n{phrase}\n",
            "de",
            protected_values=({"owner_name": phrase},),
        )
        self.assertIn("# Build-Diagnostik", localized)
        self.assertIn(phrase, localized)


if __name__ == "__main__":
    unittest.main()
