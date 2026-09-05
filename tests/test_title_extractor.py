import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from title_extractor import (
    TITLE_REPORT_FILENAME,
    TITLE_SCAN_FILENAME,
    extract_article_title,
    title_scan_completed,
    write_title_report,
    write_title_scan_marker,
)


class TitleEvidenceTests(unittest.TestCase):
    def test_structured_title_wins_and_is_cross_checked_by_markdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            content_list = Path(temporary) / "paper_content_list.json"
            content_list.write_text(
                json.dumps(
                    [
                        {
                            "type": "title",
                            "text": "A Reliable Method for Rock Failure Prediction",
                            "page_idx": 0,
                            "bbox": [80, 120, 900, 190],
                        },
                        {
                            "type": "text",
                            "text": "John Doe, Jane Roe",
                            "page_idx": 0,
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = extract_article_title(
                "# A Reliable Method for Rock Failure Prediction\n\n## Abstract\nText",
                content_list,
                source_stem="download_12345",
            )

            self.assertEqual(
                result.title,
                "A Reliable Method for Rock Failure Prediction",
            )
            self.assertEqual(result.confidence, "高")
            self.assertIn("content_list", result.extraction_method)
            self.assertGreaterEqual(result.candidates[0].agreeing_sources, 2)

    def test_markdown_h1_is_preferred_over_generic_heading(self):
        result = extract_article_title(
            "# Abstract\n\n# Coupled Thermo-Hydro-Mechanical Behaviour of Granite\n\nText",
            source_stem="scan_001",
        )
        self.assertEqual(
            result.title,
            "Coupled Thermo-Hydro-Mechanical Behaviour of Granite",
        )
        self.assertEqual(result.confidence, "高")

    def test_filename_only_fallback_is_cleaned_and_requires_review(self):
        result = extract_article_title(
            "## Abstract\n\nShort body.",
            source_stem="001_Underground_storage_of_hydrogen",
        )
        self.assertEqual(result.title, "Underground storage of hydrogen")
        self.assertEqual(result.confidence, "需核查")
        self.assertTrue(result.filename_fallback)
        self.assertTrue(result.warnings)

    def test_plain_journal_header_does_not_beat_descriptive_filename(self):
        result = extract_article_title(
            "Journal of Example Studies\n\nARTICLE INFO\n\n## Abstract\nBody",
            source_stem="A descriptive paper title about underground storage",
        )
        self.assertEqual(
            result.title,
            "A descriptive paper title about underground storage",
        )
        self.assertTrue(result.filename_fallback)

    def test_author_and_affiliation_blocks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            content_list = Path(temporary) / "content_list.json"
            content_list.write_text(
                json.dumps(
                    [
                        {"type": "title", "text": "John Doe 1, Jane Roe 2", "page_idx": 0},
                        {
                            "type": "title",
                            "text": "Department of Engineering, Example University",
                            "page_idx": 0,
                        },
                    ]
                ),
                encoding="utf-8",
            )
            result = extract_article_title(
                "## Abstract\nBody",
                content_list,
                source_stem="A valid article title from the source file",
            )
            self.assertEqual(
                result.title,
                "A valid article title from the source file",
            )
            self.assertTrue(result.filename_fallback)

    def test_comma_separated_title_phrases_are_not_treated_as_authors(self):
        result = extract_article_title(
            "# Rock Mechanics, Rock Engineering, and Underground Construction\n",
            source_stem="download-42",
        )
        self.assertEqual(
            result.title,
            "Rock Mechanics, Rock Engineering, and Underground Construction",
        )


class TitleOutputTests(unittest.TestCase):
    def test_report_and_marker_are_utf8_and_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            article = Path(temporary)
            result = extract_article_title(
                "# 岩石多轴破坏准则研究\n\n## 摘要\n正文",
                source_stem="source-file",
            )
            title_dir = article / "Title"
            report = write_title_report(
                "source-file",
                result,
                title_dir / TITLE_REPORT_FILENAME,
            )
            marker = write_title_scan_marker(
                title_dir / TITLE_SCAN_FILENAME,
                "source-file",
                result,
                report is not None,
            )

            self.assertIsNotNone(report)
            self.assertIn("岩石多轴破坏准则研究", report.read_text(encoding="utf-8"))
            self.assertTrue(marker.is_file())
            self.assertTrue(title_scan_completed(article))
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["title"], "岩石多轴破坏准则研究")
            self.assertTrue(payload["scan_completed"])


if __name__ == "__main__":
    unittest.main()
