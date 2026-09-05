import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from reference_extractor import (
    REFERENCE_REPORT_FILENAME,
    REFERENCE_SCAN_FILENAME,
    extract_references,
    reference_scan_completed,
    write_reference_report,
    write_reference_scan_marker,
)


class StructuredReferenceTests(unittest.TestCase):
    def test_content_list_ref_text_is_primary_and_keeps_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_list = root / "paper_content_list.json"
            content_list.write_text(
                json.dumps(
                    [
                        {
                            "type": "text",
                            "text": "A numbered paragraph [1] that is not a bibliography.",
                            "page_idx": 1,
                        },
                        {
                            "type": "list",
                            "sub_type": "ref_text",
                            "page_idx": 8,
                            "list_items": [
                                "[ 1 ] Zhang Z, Li X. First paper[J]. Journal A, 2022, 1: 1-9.",
                                "[2] Wang Y, et al. Second paper. 2023.\nhttps://doi.org/10.1000/test.",
                            ],
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = extract_references(
                "## References\n\n[1] Wrong fallback, 1999.",
                content_list,
            )

            self.assertEqual(result.extraction_method, "MinerU content_list/ref_text")
            self.assertEqual([item.original_label for item in result.entries], ["1", "2"])
            self.assertEqual([item.page_number for item in result.entries], [9, 9])
            self.assertIn("First paper", result.entries[0].text)
            self.assertIn("https://doi.org/10.1000/test", result.entries[1].text)
            self.assertNotIn("Wrong fallback", " ".join(item.text for item in result.entries))

    def test_duplicate_structured_entries_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "content_list.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "type": "list",
                            "sub_type": "ref_text",
                            "list_items": [
                                "[1] Doe J. Stable citation. Journal, 2020.",
                                "[1] Doe J. Stable citation. Journal, 2020.",
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = extract_references("", path)
            self.assertEqual(len(result.entries), 1)


class MarkdownFallbackTests(unittest.TestCase):
    def test_heading_fallback_stops_before_appendix(self):
        markdown = """
# Paper title

## Results

The experiment result is 42.

## References

[1] Doe J, Roe R. First study. Journal of Tests, 2020, 2: 1-9.

[2] Li X, et al. Second study. Proceedings, 2021, pp. 10-20.

## Appendix A

[1] This is an appendix step, not a citation.
"""
        result = extract_references(markdown)

        self.assertEqual(result.extraction_method, "MinerU Markdown/参考文献标题")
        self.assertEqual(len(result.entries), 2)
        self.assertNotIn("appendix step", " ".join(item.text for item in result.entries))

    def test_unnumbered_author_year_paragraphs_are_supported(self):
        markdown = """
## Bibliography

Smith, J., Jones, A., 2019. A useful method. Journal of Testing 4, 10-20.

王强，李明，2021．岩石试验方法研究[J]．岩土工程学报，43(2)：20-30．
"""
        result = extract_references(markdown)
        self.assertEqual(len(result.entries), 2)
        self.assertTrue(all(not item.original_label for item in result.entries))

    def test_missing_heading_requires_a_strong_numbered_tail(self):
        body = "Introduction text.\n" * 50
        references = "\n".join(
            f"[{index}] Author {index}, Coauthor. Study {index}. Journal, 20{index:02d}, 2: 1-9."
            for index in range(1, 7)
        )
        result = extract_references(body + references)
        self.assertEqual(result.extraction_method, "MinerU Markdown/文末连续编号")
        self.assertEqual(len(result.entries), 6)

    def test_ordinary_numbered_steps_are_not_references(self):
        markdown = "Conclusion\n1. Install the program.\n2. Click Start.\n3. Close it."
        result = extract_references(markdown)
        self.assertEqual(result.entries, [])


class ReferenceOutputTests(unittest.TestCase):
    def test_report_and_scan_marker_are_utf8_and_auditable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = extract_references(
                "## 参考文献\n\n[1] 张三，李四．测试论文[J]．岩石学报，2020，1：1-8．\n\n"
                "[2] Doe J, Roe R. Test article. Journal, 2021, 2: 9-18."
            )
            report = write_reference_report(
                "示例论文",
                result,
                root / "References" / REFERENCE_REPORT_FILENAME,
            )
            marker = write_reference_scan_marker(
                root / "References" / REFERENCE_SCAN_FILENAME,
                result,
                report is not None,
            )

            self.assertIsNotNone(report)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("# 参考文献", report_text)
            self.assertIn("来源论文：示例论文", report_text)
            self.assertIn("不调用 LLM 补写或改写", report_text)
            self.assertTrue(marker.is_file())
            self.assertTrue(reference_scan_completed(root))
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["entry_count"], 2)


if __name__ == "__main__":
    unittest.main()
