"""Extract a paper's bibliography without rewriting or inventing citations.

MinerU already labels bibliography blocks as ``sub_type=ref_text`` in
``*_content_list.json``.  Those structured blocks are the authoritative source.
When that signal is absent, the extractor falls back to a constrained Markdown
section parser and, finally, to a validated numbered sequence near the end of
the document.  The fallback is deliberately deterministic: an LLM is not asked
to reproduce citations because doing so can silently alter authors, years,
titles, page ranges, or DOI strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re


REFERENCE_SCHEMA_VERSION = 1
REFERENCE_REPORT_FILENAME = "参考文献.md"
REFERENCE_SCAN_FILENAME = "references_scan.json"


@dataclass(frozen=True)
class ReferenceEntry:
    """One citation in original document order."""

    text: str
    original_label: str = ""
    page_number: int | None = None
    evidence_source: str = ""


@dataclass
class ReferenceExtractionResult:
    entries: list[ReferenceEntry]
    extraction_method: str
    warnings: list[str] = field(default_factory=list)
    structured_block_count: int = 0


_REFERENCE_HEADINGS = {
    "references",
    "reference",
    "referencesandnotes",
    "bibliography",
    "literaturecited",
    "workscited",
    "citedliterature",
    "参考文献",
    "主要参考文献",
    "引用文献",
    "文献",
}

_POST_REFERENCE_HEADINGS = {
    "appendix",
    "appendices",
    "supplementarymaterial",
    "supplementalinformation",
    "supportinginformation",
    "authorbiography",
    "authorbiographies",
    "abouttheauthors",
    "acknowledgment",
    "acknowledgments",
    "acknowledgement",
    "acknowledgements",
    "funding",
    "declaration",
    "declarationofcompetinginterest",
    "conflictofinterest",
    "conflictsofinterest",
    "competinginterests",
    "dataavailability",
    "codeavailability",
    "ethicsstatement",
    "作者简介",
    "附录",
    "补充材料",
    "致谢",
    "基金项目",
    "利益冲突",
    "数据可用性",
    "代码可用性",
}

_NUMBERED_ENTRY_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:"
    r"\[\s*(?P<bracket>[A-Za-z]?\s*\d+)\s*\]|"
    r"\(\s*(?P<paren>[A-Za-z]?\s*\d+)\s*\)|"
    r"(?P<plain>\d+)\s*[.)．、]"
    r")\s*",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
_YEAR_RE = re.compile(r"(?<!\d)(?:18|19|20)\d{2}[a-z]?(?!\d)", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(
    r"(?:https?\s*:\s*//|doi\s*:|10\.\d{4,9}/|arxiv\s*:|isbn\s*:)",
    re.IGNORECASE,
)
_PUBLICATION_RE = re.compile(
    r"(?:\bet\s+al\.?|\bvol\.?\s*\d|\bpp?\.?\s*\d|"
    r"\bjournal\b|\bproceedings\b|\btransactions\b|\bpress\b|"
    r"\[[JCMDR]\]|期刊|学报|出版社|会议|硕士|博士)",
    re.IGNORECASE,
)


def _normalise_heading(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    value = value.strip().strip("#*_` ")
    value = re.sub(r"^\s*(?:\d+(?:\.\d+)*|[IVXLCDM]+)[.)．、:]?\s*", "", value, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def _is_post_reference_heading(normalised: str) -> bool:
    if normalised in _POST_REFERENCE_HEADINGS:
        return True
    return normalised.startswith(("appendix", "supplementary", "附录"))


def _clean_entry(value: str) -> tuple[str, str]:
    value = str(value or "").replace("\u00a0", " ").replace("\u00ad", "")
    value = re.sub(r"(?i)<br\s*/?>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    match = _NUMBERED_ENTRY_RE.match(value)
    label = ""
    if match:
        label = next(
            (group for group in match.group("bracket", "paren", "plain") if group),
            "",
        )
        label = re.sub(r"\s+", "", label)
        value = value[match.end():].strip()
    return label, value.strip(" -\t")


def _split_numbered_blocks(value: str) -> list[str]:
    """Split one text block only at numbered markers that begin a line."""
    lines = str(value or "").splitlines()
    blocks: list[str] = []
    current: list[str] = []
    saw_marker = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                current.append("")
            continue
        if _NUMBERED_ENTRY_RE.match(stripped):
            saw_marker = True
            if current:
                blocks.append("\n".join(current).strip())
            current = [stripped]
        elif current:
            current.append(stripped)
        else:
            current = [stripped]
    if current:
        blocks.append("\n".join(current).strip())
    return blocks if saw_marker else ([str(value).strip()] if str(value).strip() else [])


def _deduplicate(entries: list[ReferenceEntry]) -> list[ReferenceEntry]:
    result: list[ReferenceEntry] = []
    seen: set[str] = set()
    for entry in entries:
        normalised_text = re.sub(r"[\W_]+", "", entry.text.casefold())
        # A paper can intentionally repeat the same citation under two distinct
        # numbers.  Preserve that source structure; remove only a duplicated
        # extraction of the same labelled item (or an exact unlabelled repeat).
        key = f"{entry.original_label.casefold()}|{normalised_text}"
        if not normalised_text or key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def _load_structured_references(path: Path | None) -> tuple[list[ReferenceEntry], int, list[str]]:
    if path is None or not path.is_file():
        return [], 0, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [], 0, [f"无法读取 content_list.json：{exc}"]
    if not isinstance(payload, list):
        return [], 0, ["content_list.json 顶层不是列表"]

    entries: list[ReferenceEntry] = []
    block_count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        subtype = str(item.get("sub_type") or "").strip().casefold()
        if subtype not in {"ref_text", "reference", "references"}:
            continue
        block_count += 1
        page_idx = item.get("page_idx")
        page_number = page_idx + 1 if isinstance(page_idx, int) and page_idx >= 0 else None
        values = item.get("list_items")
        if not isinstance(values, list) or not values:
            values = [item.get("text", "")]
        for value in values:
            for block in _split_numbered_blocks(str(value or "")):
                label, text = _clean_entry(block)
                if len(text) < 8:
                    continue
                entries.append(
                    ReferenceEntry(
                        text=text,
                        original_label=label,
                        page_number=page_number,
                        evidence_source="MinerU content_list/ref_text",
                    )
                )
    return _deduplicate(entries), block_count, []


def _bibliographic_score(value: str) -> int:
    value = re.sub(r"<[^>]+>", "", value or "")
    score = 0
    if _YEAR_RE.search(value):
        score += 1
    if _IDENTIFIER_RE.search(value):
        score += 1
    if _PUBLICATION_RE.search(value):
        score += 1
    if len(value) >= 35 and (value.count(",") >= 2 or "，" in value):
        score += 1
    return score


def _parse_markdown_entries(section: str, evidence_source: str) -> list[ReferenceEntry]:
    lines = section.splitlines()
    numbered_blocks: list[str] = []
    current: list[str] = []
    labels: list[str] = []
    for line in lines:
        stripped = line.strip()
        marker = _NUMBERED_ENTRY_RE.match(stripped) if stripped else None
        if marker:
            if current:
                numbered_blocks.append("\n".join(current).strip())
            current = [stripped]
            labels.append(
                re.sub(
                    r"\s+",
                    "",
                    next(
                        (
                            group
                            for group in marker.group("bracket", "paren", "plain")
                            if group
                        ),
                        "",
                    ),
                )
            )
        elif current and stripped:
            current.append(stripped)
        elif current and not stripped:
            current.append("")
    if current:
        numbered_blocks.append("\n".join(current).strip())

    entries: list[ReferenceEntry] = []
    if numbered_blocks:
        for block in numbered_blocks:
            label, text = _clean_entry(block)
            if len(text) >= 12:
                entries.append(
                    ReferenceEntry(
                        text=text,
                        original_label=label,
                        evidence_source=evidence_source,
                    )
                )
        return _deduplicate(entries)

    paragraphs = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"\n\s*\n", section)
        if part.strip()
    ]
    plausible = [part for part in paragraphs if _bibliographic_score(part) >= 2]
    if len(plausible) < 2:
        line_candidates = [
            re.sub(r"\s+", " ", line).strip()
            for line in lines
            if _bibliographic_score(line.strip()) >= 2
        ]
        if len(line_candidates) >= 2:
            plausible = line_candidates
    for text in plausible:
        _label, cleaned = _clean_entry(text)
        if len(cleaned) >= 20:
            entries.append(
                ReferenceEntry(text=cleaned, evidence_source=evidence_source)
            )
    return _deduplicate(entries)


@dataclass(frozen=True)
class _Heading:
    start: int
    end: int
    level: int
    title: str
    normalised: str


def _find_headings(markdown_text: str) -> list[_Heading]:
    headings: list[_Heading] = []
    offset = 0
    for line in markdown_text.splitlines(keepends=True):
        stripped = line.strip()
        match = _MARKDOWN_HEADING_RE.match(stripped)
        if match:
            title = match.group(2)
            headings.append(
                _Heading(
                    start=offset,
                    end=offset + len(line),
                    level=len(match.group(1)),
                    title=title,
                    normalised=_normalise_heading(title),
                )
            )
        else:
            normalised = _normalise_heading(stripped)
            if normalised in _REFERENCE_HEADINGS or _is_post_reference_heading(normalised):
                headings.append(
                    _Heading(
                        start=offset,
                        end=offset + len(line),
                        level=0,
                        title=stripped,
                        normalised=normalised,
                    )
                )
        offset += len(line)
    return headings


def _extract_from_markdown_heading(markdown_text: str) -> list[ReferenceEntry]:
    headings = _find_headings(markdown_text)
    candidates: list[tuple[int, int, list[ReferenceEntry]]] = []
    for index, heading in enumerate(headings):
        if heading.normalised not in _REFERENCE_HEADINGS:
            continue
        end = len(markdown_text)
        for following in headings[index + 1:]:
            if following.normalised in _REFERENCE_HEADINGS:
                continue
            same_or_higher = (
                heading.level > 0
                and following.level > 0
                and following.level <= heading.level
            )
            if same_or_higher or _is_post_reference_heading(following.normalised):
                end = following.start
                break
        section = markdown_text[heading.end:end]
        entries = _parse_markdown_entries(section, "MinerU Markdown/参考文献标题")
        if not entries:
            continue
        quality = sum(min(3, _bibliographic_score(entry.text)) for entry in entries)
        # Prefer a real bibliography near the end over a table-of-contents hit.
        position_bonus = int(10 * heading.start / max(1, len(markdown_text)))
        candidates.append((len(entries) * 4 + quality + position_bonus, heading.start, entries))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _numeric_label(label: str) -> int | None:
    match = re.search(r"\d+", label or "")
    return int(match.group(0)) if match else None


def _extract_numbered_tail(markdown_text: str) -> list[ReferenceEntry]:
    """Conservative fallback for a missing References heading.

    A candidate must start at 1, contain at least five mostly consecutive
    citations, and carry bibliographic signals.  This avoids treating ordinary
    numbered conclusions or appendix steps as references.
    """
    if not markdown_text.strip():
        return []
    tail_start = max(0, int(len(markdown_text) * 0.40))
    tail = markdown_text[tail_start:]
    lines = tail.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if (_NUMBERED_ENTRY_RE.match(line.strip()) and _numeric_label(_clean_entry(line)[0]) == 1)
    ]
    best: list[ReferenceEntry] = []
    for start in starts:
        entries = _parse_markdown_entries(
            "\n".join(lines[start:]),
            "MinerU Markdown/文末连续编号",
        )
        numbers = [
            number
            for number in (_numeric_label(entry.original_label) for entry in entries)
            if number is not None
        ]
        if len(entries) < 5 or len(numbers) < 5:
            continue
        adjacent = sum(b == a + 1 for a, b in zip(numbers, numbers[1:]))
        strong = sum(_bibliographic_score(entry.text) >= 1 for entry in entries)
        if adjacent < max(3, len(numbers) - 2):
            continue
        if strong < max(4, int(len(entries) * 0.70)):
            continue
        if len(entries) > len(best):
            best = entries
    return best


def extract_references(
    markdown_text: str,
    content_list_path: Path | None = None,
) -> ReferenceExtractionResult:
    """Extract references using structured MinerU data and safe fallbacks."""
    structured, block_count, warnings = _load_structured_references(content_list_path)
    if structured:
        return ReferenceExtractionResult(
            entries=structured,
            extraction_method="MinerU content_list/ref_text",
            warnings=warnings,
            structured_block_count=block_count,
        )

    from_heading = _extract_from_markdown_heading(markdown_text or "")
    if from_heading:
        if block_count:
            warnings.append("MinerU ref_text 块为空，已改用 Markdown 标题边界。")
        return ReferenceExtractionResult(
            entries=from_heading,
            extraction_method="MinerU Markdown/参考文献标题",
            warnings=warnings,
            structured_block_count=block_count,
        )

    from_tail = _extract_numbered_tail(markdown_text or "")
    if from_tail:
        warnings.append("未识别到参考文献标题，结果来自文末连续编号兜底。")
        return ReferenceExtractionResult(
            entries=from_tail,
            extraction_method="MinerU Markdown/文末连续编号",
            warnings=warnings,
            structured_block_count=block_count,
        )

    warnings.append("未找到可信的参考文献边界或条目。")
    return ReferenceExtractionResult(
        entries=[],
        extraction_method="未识别",
        warnings=warnings,
        structured_block_count=block_count,
    )


def write_reference_report(
    article_title: str,
    result: ReferenceExtractionResult,
    output_path: Path,
) -> Path | None:
    """Write one ordered Markdown bibliography when entries were found."""
    if not result.entries:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 参考文献",
        "",
        f"> 来源论文：{article_title}",
        f"> 提取方式：{result.extraction_method}",
        f"> 共识别 {len(result.entries)} 条；保持原文顺序，不调用 LLM 补写或改写书目信息。",
        "> MinerU/OCR 可能造成字符或断行误差，正式引用前请与原 PDF 核对。",
        "",
    ]
    for index, entry in enumerate(result.entries, start=1):
        label = entry.original_label or str(index)
        lines.append(f"{label}. {entry.text}")
        lines.append("")
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output_path


def write_reference_scan_marker(
    output_path: Path,
    result: ReferenceExtractionResult,
    report_written: bool,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pages = sorted(
        {
            entry.page_number
            for entry in result.entries
            if isinstance(entry.page_number, int)
        }
    )
    payload = {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "scan_completed": True,
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entry_count": len(result.entries),
        "extraction_method": result.extraction_method,
        "structured_block_count": result.structured_block_count,
        "source_pages": pages,
        "report_written": bool(report_written),
        "warnings": list(result.warnings),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def reference_scan_completed(extract_directory: Path) -> bool:
    marker = Path(extract_directory) / "References" / REFERENCE_SCAN_FILENAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("schema_version") == REFERENCE_SCHEMA_VERSION
        and payload.get("scan_completed") is True
    )
