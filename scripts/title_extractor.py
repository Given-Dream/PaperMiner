"""Extract a paper title from independent, auditable document evidence.

The extractor intentionally does not ask an LLM to invent or rewrite a title.
It combines PDF metadata, MinerU's first-page structure, the leading Markdown
heading, and the source filename.  Agreement between independent sources raises
confidence; a filename-only result is retained but explicitly marked for review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from html import unescape
import json
from pathlib import Path
import re


TITLE_SCHEMA_VERSION = 1
TITLE_REPORT_FILENAME = "文章标题.md"
TITLE_SCAN_FILENAME = "title_scan.json"


@dataclass(frozen=True)
class TitleCandidate:
    text: str
    source: str
    base_score: float
    page_number: int | None = None
    adjusted_score: float = 0.0
    agreeing_sources: int = 1


@dataclass
class TitleExtractionResult:
    title: str
    confidence: str
    extraction_method: str
    candidates: list[TitleCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    filename_fallback: bool = False


_GENERIC_TITLES = {
    "abstract",
    "摘要",
    "introduction",
    "引言",
    "绪论",
    "conclusion",
    "conclusions",
    "结论",
    "references",
    "bibliography",
    "参考文献",
    "contents",
    "tableofcontents",
    "目录",
    "researcharticle",
    "originalarticle",
    "reviewarticle",
    "article",
    "paper",
    "title",
    "articletitle",
    "articleinfo",
    "authorinformation",
    "keywords",
    "keyword",
    "关键词",
    "文章标题",
    "论文题目",
    "untitled",
}
_BOILERPLATE_RE = re.compile(
    r"(?:all rights reserved|copyright|creative commons|"
    r"received\s+\d|accepted\s+\d|available online|"
    r"journal homepage|downloaded from|supplementary material)",
    re.IGNORECASE,
)
_URL_OR_ID_RE = re.compile(
    r"^(?:https?://|www\.|doi\s*:|10\.\d{4,9}/|arxiv\s*:)",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
_AFFILIATION_RE = re.compile(
    r"(?:\bdepartment\b|\buniversity\b|\binstitute\b|\blaborator(?:y|ies)\b|"
    r"\bcollege\b|\bschool of\b|\bhospital\b|\bacademy of\b|"
    r"大学|学院|研究所|实验室|医院|科学院)",
    re.IGNORECASE,
)
_AFFILIATION_START_RE = re.compile(
    r"^\s*(?:department|college|school|institute|laborator(?:y|ies)|hospital|"
    r"faculty|affiliation)\b",
    re.IGNORECASE,
)
_PERSON_NAME_RE = re.compile(
    r"^(?:[A-Z][A-Za-z'’.-]+)(?:\s+(?:[A-Z]\.?|[A-Z][A-Za-z'’.-]+)){0,3}"
    r"(?:\s*[\d*†‡]+)?$"
)


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def _clean_title(value: object, *, filename: bool = False) -> str:
    text = unescape(str(value or ""))
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"^\s*#{1,6}\s*", "", text)
    text = re.sub(r"^\s*(?:title|article\s+title|题目|标题|论文题目)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Microsoft\s+Word\s*[-:：]\s*", "", text, flags=re.IGNORECASE)
    if filename:
        text = Path(text).stem
        text = re.sub(r"^\s*\d{1,5}\s*[_-]+\s*", "", text)
        text = text.replace("_", " ")
    # MinerU sometimes preserves a soft line-wrap hyphen as "word-\nword".
    text = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n#*`\"'“”‘’")
    text = re.sub(r"\.(?:pdf|docx?|rtf)$", "", text, flags=re.IGNORECASE).strip()
    return text


def _is_plausible_title(value: str) -> bool:
    if not value or len(value) > 400:
        return False
    key = _normalise_key(value)
    if not key or key in _GENERIC_TITLES:
        return False
    meaningful = re.findall(r"[A-Za-z\u4e00-\u9fff]", value)
    if len(meaningful) < 6:
        return False
    if _URL_OR_ID_RE.match(value) or "@" in value:
        return False
    if _BOILERPLATE_RE.search(value):
        return False
    affiliation_signals = _AFFILIATION_RE.findall(value)
    if len(affiliation_signals) >= 2 or _AFFILIATION_START_RE.search(value):
        return False
    author_parts = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"\s*(?:,|，|;|；|\band\b|和)\s*", value)
        if part.strip()
    ]
    if 2 <= len(author_parts) <= 12:
        english_names = sum(bool(_PERSON_NAME_RE.fullmatch(part)) for part in author_parts)
        chinese_names = sum(
            bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}(?:\s*[\d*†‡]+)?", part))
            for part in author_parts
        )
        author_marker = bool(
            re.search(r"(?:\b[A-Z]\.\s*|[\d*†‡]\s*(?:,|，|;|；|$))", value)
        )
        # Two title-cased phrases separated by a comma can be a real paper
        # title.  Require author-specific markers, a longer name list, or at
        # least three short Chinese names before rejecting the candidate.
        if (
            (english_names >= 2 and (author_marker or len(author_parts) >= 4))
            or chinese_names >= 3
        ):
            return False
    latin_words = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    if len(latin_words) > 60:
        return False
    visible = [character for character in value if not character.isspace()]
    if visible:
        alphanumeric = sum(character.isalnum() for character in visible)
        if alphanumeric / len(visible) < 0.48:
            return False
    return True


def _candidate(
    value: object,
    source: str,
    score: float,
    *,
    page_number: int | None = None,
    filename: bool = False,
) -> TitleCandidate | None:
    text = _clean_title(value, filename=filename)
    if not _is_plausible_title(text):
        return None
    return TitleCandidate(
        text=text,
        source=source,
        base_score=float(score),
        page_number=page_number,
    )


def _source_family(source: str) -> str:
    if source.startswith("PDF 元数据"):
        return "pdf_metadata"
    if source.startswith("PDF 首页"):
        return "pdf_page"
    if source.startswith("MinerU content_list"):
        return "mineru_structure"
    if source.startswith("MinerU Markdown"):
        return "mineru_markdown"
    return "filename"


def _similarity(left: str, right: str) -> float:
    left_key = _normalise_key(left)
    right_key = _normalise_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    shorter, longer = sorted((left_key, right_key), key=len)
    if len(shorter) >= 12 and shorter in longer and len(shorter) / len(longer) >= 0.78:
        return 0.94
    return SequenceMatcher(None, left_key, right_key).ratio()


def _read_json_items(path: Path | None) -> tuple[list[dict], list[str]]:
    if path is None or not Path(path).is_file():
        return [], []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [], [f"无法读取 content_list.json：{exc}"]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], []
    if isinstance(payload, dict):
        for key in ("content_list", "items", "blocks"):
            values = payload.get(key)
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)], []
    return [], ["content_list.json 中没有可识别的块列表"]


def _item_page_index(item: dict) -> int | None:
    for key in ("page_idx", "page_index", "page_no", "page"):
        value = item.get(key)
        if isinstance(value, int) and value >= 0:
            # ``page_no`` is commonly one-based; MinerU's page_idx is zero-based.
            if key == "page_no" and value > 0:
                return value - 1
            return value
    return None


def _structured_candidates(path: Path | None) -> tuple[list[TitleCandidate], list[str]]:
    items, warnings = _read_json_items(path)
    if not items:
        return [], warnings
    page_indices = [index for item in items if (index := _item_page_index(item)) is not None]
    first_page = min(page_indices) if page_indices else 0
    first_page_items = [
        item
        for item in items
        if (_item_page_index(item) in (None, first_page))
    ][:45]

    results: list[TitleCandidate] = []
    first_text_position = 0
    for position, item in enumerate(first_page_items):
        item_type = str(item.get("type") or "").casefold()
        subtype = str(item.get("sub_type") or item.get("subtype") or "").casefold()
        label = re.sub(r"[^a-z0-9]+", "", f"{item_type}{subtype}")
        level = item.get("text_level")
        values: list[tuple[object, str]] = []
        if item.get("title"):
            values.append((item.get("title"), "title 字段"))
        if item.get("text"):
            values.append((item.get("text"), "text 字段"))
        if item.get("content") and isinstance(item.get("content"), str):
            values.append((item.get("content"), "content 字段"))
        if not values:
            continue

        explicit = any(token in label for token in ("title", "doctitle", "papertitle"))
        for value, field_name in values:
            if explicit:
                score = 112
                reason = f"标题块/{field_name}"
            elif level == 1 or str(level) == "1":
                score = 106
                reason = f"一级文本/{field_name}"
            elif level == 2 or str(level) == "2":
                score = 80
                reason = f"二级文本/{field_name}"
            elif item_type in {"text", "paragraph", "heading"} and first_text_position < 5:
                # Reading order alone is weak evidence: a journal masthead or
                # article type often appears before the real title.
                score = 46 - first_text_position * 2
                reason = f"首页前部文本/{field_name}"
            else:
                continue

            bbox = item.get("bbox")
            if isinstance(bbox, list) and len(bbox) >= 4:
                try:
                    if float(bbox[1]) <= 220:
                        score += 3
                except (TypeError, ValueError):
                    pass
            candidate = _candidate(
                value,
                f"MinerU content_list/{reason}",
                score,
                page_number=first_page + 1,
            )
            if candidate:
                results.append(candidate)
        if item_type in {"text", "paragraph", "heading"}:
            first_text_position += 1
    return results, warnings


def _markdown_candidates(markdown_text: str) -> list[TitleCandidate]:
    text = (markdown_text or "").lstrip("\ufeff")[:16000]
    if not text.strip():
        return []
    results: list[TitleCandidate] = []
    lines = text.splitlines()[:180]
    nonempty_position = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading = _MARKDOWN_HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            if level == 1:
                score = 102 - min(nonempty_position, 8)
            elif level == 2 and nonempty_position <= 20:
                score = 82 - min(nonempty_position, 8)
            else:
                nonempty_position += 1
                continue
            candidate = _candidate(
                heading.group(2),
                f"MinerU Markdown/H{level} 标题",
                score,
                page_number=1,
            )
            if candidate:
                results.append(candidate)
        nonempty_position += 1

    # Some publishers yield a title as an unheaded, wrapped first paragraph.
    before_abstract = re.split(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:abstract|摘要)\s*[:：]?\s*$",
        text,
        maxsplit=1,
    )[0]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", before_abstract) if part.strip()]
    for position, paragraph in enumerate(paragraphs[:6]):
        if _MARKDOWN_HEADING_RE.match(paragraph) or len(paragraph.splitlines()) > 4:
            continue
        candidate = _candidate(
            paragraph,
            "MinerU Markdown/首页首部段落",
            44 - position * 2,
            page_number=1,
        )
        if candidate:
            results.append(candidate)
    return results


def _pdf_candidates(path: Path | None) -> tuple[list[TitleCandidate], list[str]]:
    if path is None or not Path(path).is_file():
        return [], []
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], ["未安装 pypdf，已跳过 PDF 元数据核验"]
    try:
        reader = PdfReader(str(path))
        metadata = reader.metadata
    except Exception as exc:  # malformed/encrypted PDFs vary by pypdf version
        return [], [f"无法读取 PDF 元数据：{exc}"]

    results: list[TitleCandidate] = []
    title = getattr(metadata, "title", None) if metadata is not None else None
    if not title and metadata is not None:
        try:
            title = metadata.get("/Title")
        except (AttributeError, KeyError, TypeError):
            title = None
    candidate = _candidate(title, "PDF 元数据/Title", 94)
    if candidate:
        results.append(candidate)

    # Plain PDF text is a low-priority cross-check only.  It never outranks a
    # structured title by itself because journal headers can precede the title.
    try:
        first_page_text = reader.pages[0].extract_text() if reader.pages else ""
    except Exception:
        first_page_text = ""
    nonempty = [line.strip() for line in str(first_page_text or "").splitlines() if line.strip()]
    for position, line in enumerate(nonempty[:8]):
        candidate = _candidate(
            line,
            "PDF 首页/文本顺序交叉核验",
            40 - position,
            page_number=1,
        )
        if candidate:
            results.append(candidate)
    # A title is often wrapped over two or three lines by the PDF text layer.
    # Joined spans remain weak evidence unless another independent source agrees.
    for start in range(min(4, len(nonempty))):
        for width in (2, 3):
            if start + width > len(nonempty):
                continue
            candidate = _candidate(
                " ".join(nonempty[start:start + width]),
                "PDF 首页/连续文本行交叉核验",
                43 - start,
                page_number=1,
            )
            if candidate:
                results.append(candidate)
    return results, []


def _deduplicate(candidates: list[TitleCandidate]) -> list[TitleCandidate]:
    result: list[TitleCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (_source_family(candidate.source), _normalise_key(candidate.text))
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _rank(candidates: list[TitleCandidate]) -> list[TitleCandidate]:
    ranked: list[TitleCandidate] = []
    for candidate in candidates:
        agreeing_families = {_source_family(candidate.source)}
        for other in candidates:
            if other is candidate:
                continue
            other_family = _source_family(other.source)
            if other_family in agreeing_families:
                continue
            if _similarity(candidate.text, other.text) >= 0.88:
                agreeing_families.add(other_family)
        agreement_bonus = min(30, 12 * (len(agreeing_families) - 1))
        ranked.append(
            TitleCandidate(
                text=candidate.text,
                source=candidate.source,
                base_score=candidate.base_score,
                page_number=candidate.page_number,
                adjusted_score=candidate.base_score + agreement_bonus,
                agreeing_sources=len(agreeing_families),
            )
        )
    return sorted(
        ranked,
        key=lambda item: (item.adjusted_score, item.agreeing_sources, len(item.text)),
        reverse=True,
    )


def extract_article_title(
    markdown_text: str = "",
    content_list_path: Path | None = None,
    pdf_path: Path | None = None,
    source_stem: str = "",
) -> TitleExtractionResult:
    """Select the best title and retain the evidence used for that decision."""
    candidates: list[TitleCandidate] = []
    warnings: list[str] = []

    pdf_candidates, pdf_warnings = _pdf_candidates(pdf_path)
    structured_candidates, structured_warnings = _structured_candidates(content_list_path)
    candidates.extend(pdf_candidates)
    candidates.extend(structured_candidates)
    candidates.extend(_markdown_candidates(markdown_text))
    warnings.extend(pdf_warnings)
    warnings.extend(structured_warnings)

    filename_candidate = _candidate(
        source_stem,
        "源 PDF 文件名/回退",
        48,
        filename=True,
    )
    if filename_candidate:
        candidates.append(filename_candidate)

    ranked = _rank(_deduplicate(candidates))
    if not ranked:
        warnings.append("未找到可用的文章标题候选。")
        return TitleExtractionResult(
            title="",
            confidence="未识别",
            extraction_method="未识别",
            candidates=[],
            warnings=warnings,
            filename_fallback=False,
        )

    best = ranked[0]
    family = _source_family(best.source)
    filename_fallback = family == "filename" and best.agreeing_sources == 1
    if filename_fallback:
        confidence = "需核查"
        warnings.append("没有独立文档证据与文件名相互印证，当前标题来自源文件名。")
    elif best.adjusted_score >= 108 or best.base_score >= 100:
        confidence = "高"
    elif best.adjusted_score >= 78:
        confidence = "中"
    else:
        confidence = "需核查"
        warnings.append("当前结果仅有低强度版面证据，建议核对原 PDF 首页。")
    return TitleExtractionResult(
        title=best.text,
        confidence=confidence,
        extraction_method=best.source,
        candidates=ranked,
        warnings=warnings,
        filename_fallback=filename_fallback,
    )


def write_title_report(
    source_stem: str,
    result: TitleExtractionResult,
    output_path: Path,
) -> Path | None:
    if not result.title:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    needs_review = result.confidence in {"需核查", "未识别"}
    lines = [
        "# 文章标题",
        "",
        "## 识别结果",
        "",
        result.title,
        "",
        f"- 置信度：{result.confidence}",
        f"- 提取方式：{result.extraction_method}",
        f"- 来源文件：{source_stem}.pdf",
        f"- 需要人工核查：{'是' if needs_review else '否'}",
        "",
        "> 判定策略：PDF 元数据、MinerU 首页结构、Markdown 标题和源文件名交叉核验；",
        "> 不调用 LLM 补写或润色标题。排版/OCR 异常时请以原 PDF 首页为准。",
    ]
    if result.warnings:
        lines.extend(("", "## 核查提示", ""))
        lines.extend(f"- {warning}" for warning in result.warnings)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output_path


def write_title_scan_marker(
    output_path: Path,
    source_stem: str,
    result: TitleExtractionResult,
    report_written: bool,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": TITLE_SCHEMA_VERSION,
        "scan_completed": True,
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_stem": source_stem,
        "title": result.title,
        "confidence": result.confidence,
        "extraction_method": result.extraction_method,
        "filename_fallback": result.filename_fallback,
        "report_written": bool(report_written),
        "warnings": list(result.warnings),
        "candidates": [asdict(candidate) for candidate in result.candidates[:12]],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def title_scan_completed(extract_directory: Path) -> bool:
    marker = Path(extract_directory) / "Title" / TITLE_SCAN_FILENAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("schema_version") == TITLE_SCHEMA_VERSION
        and payload.get("scan_completed") is True
    )
