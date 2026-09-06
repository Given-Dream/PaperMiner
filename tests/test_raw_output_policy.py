import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from raw_output_policy import build_mineru_options, normalize_features


class RawOutputPolicyTests(unittest.TestCase):
    def test_text_only_uses_text_markdown_and_skips_heavy_dumps(self):
        options = build_mineru_options("text")

        self.assertFalse(options["formula_enable"])
        self.assertFalse(options["table_enable"])
        self.assertFalse(options["image_analysis"])
        self.assertEqual(options["f_make_md_mode"], "nlp_markdown")
        self.assertTrue(options["f_dump_md"])
        self.assertTrue(options["f_dump_content_list"])
        self.assertFalse(options["f_dump_middle_json"])
        self.assertFalse(options["f_dump_orig_pdf"])
        self.assertFalse(options["f_dump_model_output"])
        self.assertFalse(options["f_draw_layout_bbox"])
        self.assertFalse(options["f_draw_span_bbox"])

    def test_sections_only_needs_markdown_but_not_content_list(self):
        options = build_mineru_options(["sections"])

        self.assertTrue(options["f_dump_md"])
        self.assertFalse(options["f_dump_content_list"])
        self.assertEqual(options["f_make_md_mode"], "nlp_markdown")

    def test_figure_output_retains_reconstruction_evidence(self):
        options = build_mineru_options("figures")

        self.assertTrue(options["image_analysis"])
        self.assertEqual(options["f_make_md_mode"], "mm_markdown")
        self.assertTrue(options["f_dump_content_list"])
        self.assertTrue(options["f_dump_middle_json"])
        self.assertTrue(options["f_dump_orig_pdf"])

    def test_formula_and_table_models_follow_their_own_checkboxes(self):
        formula = build_mineru_options("formula")
        table = build_mineru_options("tables")

        self.assertTrue(formula["formula_enable"])
        self.assertFalse(formula["table_enable"])
        self.assertFalse(table["formula_enable"])
        self.assertTrue(table["table_enable"])

    def test_unknown_or_empty_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_features("")
        with self.assertRaises(ValueError):
            normalize_features("text,unknown")

    def test_legacy_omission_keeps_all_user_features(self):
        selected = normalize_features(None)

        self.assertIn("formula", selected)
        self.assertIn("figures", selected)
        self.assertIn("tables", selected)
        self.assertIn("references", selected)


if __name__ == "__main__":
    unittest.main()
