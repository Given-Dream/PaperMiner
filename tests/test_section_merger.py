import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from section_merger import (
    find_reference_markdowns,
    find_title_markdowns,
    merge_all_sections_charts_and_code_to_markdown,
    merge_all_sections_charts_code_and_references_to_markdown,
    merge_reference_markdowns,
    merge_title_markdowns,
)


def _write_report(article_dir: Path, entries: list[str]) -> Path:
    report = article_dir / "References" / "参考文献.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 参考文献", "", f"> 来源论文：{article_dir.name}", ""]
    for index, entry in enumerate(entries, start=1):
        lines.extend((f"{index}. {entry}", ""))
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _write_marker(article_dir: Path, entry_count: int, report_written: bool) -> Path:
    marker = article_dir / "References" / "references_scan.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scan_completed": True,
                "entry_count": entry_count,
                "report_written": report_written,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return marker


def _write_title(article_dir: Path, title: str, confidence: str = "高") -> Path:
    report = article_dir / "Title" / "文章标题.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"# 文章标题\n\n## 识别结果\n\n{title}\n",
        encoding="utf-8",
    )
    (report.parent / "title_scan.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scan_completed": True,
                "title": title,
                "confidence": confidence,
                "report_written": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report


class ReferenceDiscoveryTests(unittest.TestCase):
    def test_completed_report_is_found_and_uses_manifest_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary)
            article = extract_root / "pm-a1b2c3"
            report = _write_report(article, ["Doe J. First paper. 2020."])
            _write_marker(article, 1, True)
            (article / ".paperminer-source.json").write_text(
                json.dumps({"source_stem": "A very long original paper title"}),
                encoding="utf-8",
            )

            self.assertEqual(
                find_reference_markdowns(extract_root),
                [("A very long original paper title", report, 1)],
            )

    def test_zero_result_marker_suppresses_stale_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary)
            article = extract_root / "paper"
            _write_report(article, ["Stale citation that must not be merged. 2020."])
            _write_marker(article, 0, False)

            self.assertEqual(find_reference_markdowns(extract_root), [])

    def test_malformed_marker_is_not_treated_as_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary)
            article = extract_root / "paper"
            _write_report(article, ["Stale citation that must not be merged. 2020."])
            marker = article / "References" / "references_scan.json"
            marker.write_text("not json", encoding="utf-8")

            self.assertEqual(find_reference_markdowns(extract_root), [])

    def test_incomplete_marker_and_header_only_report_are_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary)
            incomplete = extract_root / "incomplete"
            _write_report(incomplete, ["Citation that is not ready. 2020."])
            marker = _write_marker(incomplete, 1, True)
            marker.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "scan_completed": False,
                        "entry_count": 1,
                        "report_written": True,
                    }
                ),
                encoding="utf-8",
            )

            header_only = extract_root / "header-only"
            report = _write_report(header_only, [])
            report.write_text("# 参考文献\n", encoding="utf-8")
            _write_marker(header_only, 3, True)

            self.assertEqual(find_reference_markdowns(extract_root), [])

    def test_legacy_numbered_report_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary)
            article = extract_root / "legacy"
            report = _write_report(
                article,
                ["First citation. 2019.", "Second citation. 2020."],
            )

            self.assertEqual(
                find_reference_markdowns(extract_root),
                [("legacy", report, 2)],
            )


class ReferenceMergeTests(unittest.TestCase):
    def test_reports_are_grouped_and_duplicate_citations_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary) / "extract"
            first = extract_root / "paper-a"
            second = extract_root / "paper-b"
            repeated = "Doe J. Shared source. Journal, 2020."
            _write_report(first, [repeated, "A second source. 2021."])
            _write_marker(first, 2, True)
            _write_report(second, [repeated])
            _write_marker(second, 1, True)

            target = extract_root / "MergedSections" / "参考文献_合并.md"
            output, paper_count, entry_count = merge_reference_markdowns(
                extract_root,
                target,
            )

            self.assertEqual(output, target)
            self.assertEqual(paper_count, 2)
            self.assertEqual(entry_count, 3)
            content = target.read_text(encoding="utf-8")
            self.assertIn("## 【paper-a】", content)
            self.assertIn("## 【paper-b】", content)
            self.assertEqual(content.count(repeated), 2)
            self.assertIn("不跨论文去重或改写", content)

    def test_full_merge_can_run_with_references_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary) / "extract"
            article = extract_root / "paper"
            _write_report(article, ["Doe J. Source. Journal, 2020."])
            _write_marker(article, 1, True)
            target = extract_root / "MergedSections"

            result = merge_all_sections_charts_code_and_references_to_markdown(
                extract_root,
                target,
            )

            self.assertEqual(len(result), 10)
            outputs, section_articles, sections, charts, reports, links, papers, entries, titles, reviews = result
            self.assertEqual(outputs, [target / "参考文献_合并.md"])
            self.assertEqual((section_articles, sections, charts, reports, links), (0, 0, 0, 0, 0))
            self.assertEqual((papers, entries), (1, 1))
            self.assertEqual((titles, reviews), (0, 0))

    def test_legacy_six_field_api_still_generates_reference_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary) / "extract"
            article = extract_root / "paper"
            _write_report(article, ["Doe J. Source. Journal, 2020."])
            _write_marker(article, 1, True)
            target = extract_root / "MergedSections"

            result = merge_all_sections_charts_and_code_to_markdown(
                extract_root,
                target,
            )

            self.assertEqual(len(result), 6)
            self.assertTrue((target / "参考文献_合并.md").is_file())


class TitleMergeTests(unittest.TestCase):
    def test_title_reports_are_merged_with_review_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary) / "extract"
            first = extract_root / "paper-a"
            second = extract_root / "paper-b"
            first_report = _write_title(first, "First Extracted Article Title")
            _write_title(second, "第二篇论文标题", "需核查")

            sources = find_title_markdowns(extract_root)
            self.assertEqual(sources[0], ("paper-a", "First Extracted Article Title", "高", first_report))

            target = extract_root / "MergedSections" / "文章标题_合并.md"
            output, title_count, review_count = merge_title_markdowns(
                extract_root,
                target,
            )
            self.assertEqual(output, target)
            self.assertEqual((title_count, review_count), (2, 1))
            content = target.read_text(encoding="utf-8")
            self.assertIn("First Extracted Article Title", content)
            self.assertIn("第二篇论文标题", content)
            self.assertIn("不跨论文去重", content)

    def test_full_merge_can_run_with_titles_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            extract_root = Path(temporary) / "extract"
            _write_title(extract_root / "paper", "A Standalone Paper Title")
            target = extract_root / "MergedSections"

            result = merge_all_sections_charts_code_and_references_to_markdown(
                extract_root,
                target,
            )

            self.assertEqual(len(result), 10)
            self.assertEqual(result[0], [target / "文章标题_合并.md"])
            self.assertEqual(result[8:], (1, 0))


if __name__ == "__main__":
    unittest.main()
