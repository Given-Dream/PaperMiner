"""Extract code and data availability links from the end of a paper.

The extractor uses deterministic URL discovery and DOI rejection first. An
optional LLM callback may classify only those discovered candidates; it is not
allowed to invent, rewrite, or supplement URLs. This keeps the result useful
on non-GitHub repositories such as Zenodo while limiting hallucinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urlsplit, urlunsplit


AVAILABILITY_SCHEMA_VERSION = 2
AVAILABILITY_REPORT_FILENAME = "代码与数据可用性.md"
AVAILABILITY_SCAN_FILENAME = "availability_scan.json"


@dataclass(frozen=True)
class OpenSourceLink:
    """One verified code/data link.

    The historical class name is retained for API compatibility with v1.4.6.
    ``resource_type`` is one of ``代码``, ``数据集`` or ``代码与数据``.
    """

    url: str
    platform: str
    confidence: str
    context: str
    evidence_source: str
    resource_type: str = "代码"
    detection_method: str = "规则"


@dataclass
class AvailabilityExtractionResult:
    links: list[OpenSourceLink]
    candidate_count: int
    llm_attempted: bool = False
    llm_succeeded: bool = False
    llm_error: str = ""


@dataclass(frozen=True)
class _Candidate:
    candidate_id: int
    url: str
    platform: str
    context: str
    evidence_source: str
    rule_type: str | None
    rule_confidence: str | None


_CODE_HOSTS = {
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "gitee.com": "Gitee",
    "bitbucket.org": "Bitbucket",
    "codeberg.org": "Codeberg",
    "sourceforge.net": "SourceForge",
    "codeocean.com": "Code Ocean",
}

_DATA_AND_ARCHIVE_HOSTS = {
    "zenodo.org": "Zenodo",
    "osf.io": "OSF",
    "figshare.com": "Figshare",
    "data.mendeley.com": "Mendeley Data",
    "datadryad.org": "Dryad",
    "dryad.figshare.com": "Dryad",
    "kaggle.com": "Kaggle",
    "huggingface.co": "Hugging Face",
    "openneuro.org": "OpenNeuro",
    "physionet.org": "PhysioNet",
    "pangaea.de": "PANGAEA",
    "icpsr.umich.edu": "ICPSR",
    "openicpsr.org": "openICPSR",
}

# Publisher reference resolvers point to cited literature, not to the current
# paper's code or dataset.  They can sit on the same final page as a Data
# availability statement, so spatial proximity alone is not sufficient.
_REFERENCE_RESOLVER_HOSTS = {
    "refhub.elsevier.com",
    "linkinghub.elsevier.com",
}

_CODE_KEYWORD_RE = re.compile(
    r"(?:"
    r"code\s+availability|availability\s+of\s+(?:the\s+)?code|"
    r"source\s+code|open[ -]?source|code\s+repository|software\s+repository|"
    r"repository\s+(?:is|was|are)\s+(?:publicly\s+)?available|"
    r"codes?\s+(?:(?:is|are|was)\s+)?(?:publicly\s+)?available|"
    r"implementation\s+(?:is|was|are)\s+(?:publicly\s+)?available|"
    r"scripts?\s+(?:is|are|was)\s+(?:publicly\s+)?available|"
    r"replication\s+package|reproducibility\s+package|software\s+availability|"
    r"开源代码|源代码|源码|代码地址|代码仓库|项目地址|代码可用|代码公开|实现代码"
    r")",
    re.IGNORECASE,
)

_DATA_KEYWORD_RE = re.compile(
    r"(?:"
    r"data\s+availability|availability\s+of\s+(?:the\s+)?data|"
    r"availability\s+of\s+data\s+and\s+materials|data\s+and\s+materials\s+availability|"
    r"data\s+(?:are|is|were|was)\s+(?:publicly\s+)?(?:available|accessible|deposited|archived)|"
    r"datasets?\s+(?:are|is|were|was)\s+(?:publicly\s+)?(?:available|accessible|deposited|archived)|"
    r"research\s+data|underlying\s+data|supporting\s+data|data\s+repository|dataset\s+repository|"
    r"data\s+and\s+code|code\s+and\s+data|availability\s+of\s+data\s+and\s+code|"
    r"数据可用|数据获取|数据集|数据地址|数据仓库|数据公开|研究数据|原始数据|支撑数据"
    r")",
    re.IGNORECASE,
)

_CODE_RESOURCE_RE = re.compile(
    r"(?:source\s+code|codebase|implementation|benchmark\s+scripts?|scripts?\s+(?:is|are|was)|"
    r"codes?\s+(?:publicly\s+)?available|"
    r"code\s+repository|software\s+repository|replication\s+package|reproducibility\s+package|"
    r"源代码|源码|代码仓库|实现代码)",
    re.IGNORECASE,
)
_DATA_RESOURCE_RE = re.compile(
    r"(?:source\s+data|research\s+data|underlying\s+data|supporting\s+data|"
    r"datasets?\s+(?:is|are|was|were)|data\s+(?:is|are|was|were)\s+(?:publicly\s+)?"
    r"(?:available|accessible|deposited|archived)|data\s+repository|dataset\s+repository|"
    r"数据集|数据仓库|研究数据|原始数据|支撑数据)",
    re.IGNORECASE,
)

_SCHEME_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>{}\[\]\"'，。；、]+")
_BARE_KNOWN_HOST_RE = re.compile(
    r"(?i)(?<![@\w])(?:www\.)?(?:"
    r"github\.com|gitlab\.com|gitee\.com|bitbucket\.org|codeberg\.org|"
    r"sourceforge\.net|codeocean\.com|zenodo\.org|osf\.io|figshare\.com|"
    r"data\.mendeley\.com|datadryad\.org|kaggle\.com|huggingface\.co|"
    r"openneuro\.org|physionet\.org|pangaea\.de|openicpsr\.org"
    r")/[A-Za-z0-9][^\s<>{}\[\]\"'，。；、]*"
)
_REPORT_LINK_RE = re.compile(r"(?m)^- 地址：")


def _clean_candidate(value: str) -> str:
    value = value.strip().lstrip("<(").rstrip(">")
    return value.rstrip(".,;:!?。，；、】）》)}]")


def _normalize_url(value: str) -> str:
    value = _clean_candidate(value)
    if not re.match(r"(?i)^https?://", value):
        value = "https://" + value

    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    try:
        parsed_port = parsed.port
    except ValueError:
        return ""
    port = f":{parsed_port}" if parsed_port else ""
    path = parsed.path.rstrip("/") or ""
    return urlunsplit(("https", host + port, path, parsed.query, ""))


def _is_doi_url(url: str) -> bool:
    """Reject DOI resolvers and publisher DOI endpoints, including Zenodo DOI URLs."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if host in {"doi.org", "dx.doi.org", "doi.pangaea.de"}:
        return True
    path = parsed.path.casefold()
    return bool(re.search(r"(?:^|/)doi/(?:abs/|full/|pdf/)?10\.\d{4,9}/", path))


def _is_reference_resolver_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    return host in _REFERENCE_RESOLVER_HOSTS


def _is_rejected_url(url: str) -> bool:
    return _is_doi_url(url) or _is_reference_resolver_url(url)


def _canonical_key(url: str) -> str:
    parsed = urlsplit(url)
    return (
        (parsed.hostname or "").casefold()
        + parsed.path.rstrip("/").casefold()
        + ("?" + parsed.query if parsed.query else "")
    )


def _platform_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    for known_host, label in {**_CODE_HOSTS, **_DATA_AND_ARCHIVE_HOSTS}.items():
        if host == known_host or host.endswith("." + known_host):
            return label
    if "dataverse" in host:
        return "Dataverse"
    if "figshare" in host:
        return "Figshare"
    if host.startswith("gitlab.") or ".gitlab." in host:
        return "GitLab"
    return host or "其他网站"


def _is_known_platform(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    return (
        any(host == item or host.endswith("." + item) for item in _CODE_HOSTS)
        or any(
            host == item or host.endswith("." + item)
            for item in _DATA_AND_ARCHIVE_HOSTS
        )
        or "dataverse" in host
        or "figshare" in host
        or host.startswith("gitlab.")
        or ".gitlab." in host
    )


def _context_for(text: str, start: int, end: int, radius: int = 260) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    context = re.sub(r"\s+", " ", text[left:right]).strip()
    if len(context) > 460:
        context = context[:457].rstrip() + "..."
    return context


def _preceding_line_context(text: str, start: int, end: int) -> str:
    """Return the candidate line and its nearest availability heading.

    Stop when a Markdown/availability heading is reached so adjacent Code and
    Data availability sections do not cause every link to be labelled ``both``.
    """
    current_line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    lines = [text[current_line_start:line_end]]
    cursor = current_line_start
    for _ in range(3):
        if cursor <= 0:
            break
        previous_end = cursor - 1
        previous_start = text.rfind("\n", 0, previous_end) + 1
        previous_line = text[previous_start:previous_end].strip()
        cursor = previous_start
        if not previous_line:
            break
        lines.insert(0, previous_line)
        normalized = previous_line.lstrip("#*- ").strip()
        is_heading = bool(re.match(r"^#{1,6}\s+", previous_line))
        is_availability_heading = (
            len(normalized) <= 120
            and bool(
                _CODE_KEYWORD_RE.fullmatch(normalized)
                or _DATA_KEYWORD_RE.fullmatch(normalized)
            )
        )
        if is_heading or is_availability_heading:
            break
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _reference_boundary(text: str) -> int | None:
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip().lstrip("#*- ").strip()
        stripped = re.sub(r"^\d+(?:\.\d+)*[.)]?\s*", "", stripped)
        compact = re.sub(r"[^a-z\u4e00-\u9fff]+", "", stripped.casefold())
        if compact in {
            "references",
            "referencesandnotes",
            "bibliography",
            "literaturecited",
            "参考文献",
        } and len(stripped) <= 80:
            return offset
        offset += len(line)
    return None


def _markdown_scan_regions(markdown_text: str):
    if not markdown_text.strip():
        return []
    boundary = _reference_boundary(markdown_text)
    article_body = markdown_text[:boundary] if boundary is not None else markdown_text
    window = max(12_000, int(len(article_body) * 0.45))
    window = min(100_000, len(article_body), window)
    regions = [("Markdown 文末正文", article_body[-window:], False)]

    # Availability statements can appear after the bibliography. That region
    # requires explicit code/data wording so citation hyperlinks cannot qualify.
    if boundary is not None and boundary < len(markdown_text):
        after_references = markdown_text[boundary:]
        regions.append(("Markdown 参考文献后区域", after_references[-40_000:], True))
    return regions


def _content_list_tail(content_list_path: Path | None) -> str:
    if content_list_path is None or not content_list_path.is_file():
        return ""
    try:
        payload = json.loads(content_list_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(payload, list):
        return ""

    pages = [item.get("page_idx") for item in payload if isinstance(item, dict)]
    pages = [page for page in pages if isinstance(page, int) and page >= 0]
    if not pages:
        return ""
    first_page, last_page = min(pages), max(pages)
    page_count = last_page - first_page + 1
    # Long publisher PDFs can have more than 12 pages of references; availability
    # statements immediately before them would otherwise fall outside the scan.
    tail_page_count = min(20, max(3, math.ceil(page_count * 0.40)))
    tail_start = max(first_page, last_page - tail_page_count + 1)

    chunks: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        page_idx = item.get("page_idx")
        if not isinstance(page_idx, int) or page_idx < tail_start:
            continue
        if item.get("sub_type") == "ref_text":
            continue
        if item.get("type") in {"header", "footer", "page_number"}:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
        for field in ("list_items", "image_caption", "image_footnote", "table_caption"):
            values = item.get(field)
            if isinstance(values, list):
                chunks.extend(str(value).strip() for value in values if str(value).strip())
    return "\n".join(chunks)


def _pdf_annotation_regions(origin_pdf_path: Path | None):
    """Recover external hyperlinks embedded as PDF annotations on ending pages.

    MinerU Markdown normally preserves visible URLs, but a label such as
    ``available here`` may hide the actual URI in the PDF annotation. pypdf is
    optional at import time; missing or malformed PDFs simply skip this source.
    """
    if origin_pdf_path is None or not origin_pdf_path.is_file():
        return []
    try:
        from pypdf import PdfReader
        try:
            from pypdf._text_extraction import mult as multiply_text_matrix
        except ImportError:
            multiply_text_matrix = None

        reader = PdfReader(str(origin_pdf_path), strict=False)
    except Exception:
        return []

    page_count = len(reader.pages)
    if page_count <= 0:
        return []
    tail_page_count = min(20, max(3, math.ceil(page_count * 0.40)))
    tail_start = max(0, page_count - tail_page_count)
    regions = []
    annotation_count = 0
    for page_index in range(tail_start, page_count):
        try:
            page = reader.pages[page_index]
            fragments = []

            def collect_text(text, current_matrix, text_matrix, _font, _font_size):
                cleaned = re.sub(r"\s+", " ", text or "").strip()
                if not cleaned:
                    return
                try:
                    position_matrix = (
                        multiply_text_matrix(text_matrix, current_matrix)
                        if multiply_text_matrix is not None
                        else text_matrix
                    )
                    fragments.append(
                        (
                            float(position_matrix[4]),
                            float(position_matrix[5]),
                            cleaned,
                        )
                    )
                except (IndexError, TypeError, ValueError):
                    pass

            try:
                page_text = page.extract_text(visitor_text=collect_text) or ""
            except TypeError:
                # Older pypdf fallback: annotation labels and LLM validation
                # still work, but no page-wide text is attached to every URI.
                page_text = page.extract_text() or ""
            annotations = page.get("/Annots", [])
            if hasattr(annotations, "get_object"):
                annotations = annotations.get_object()
        except Exception:
            continue
        if not isinstance(annotations, (list, tuple)):
            try:
                annotations = list(annotations)
            except (TypeError, ValueError):
                continue

        reference_page = _reference_boundary(page_text) is not None
        text_lines = page_text.splitlines()
        for annotation_ref in annotations:
            try:
                annotation = (
                    annotation_ref.get_object()
                    if hasattr(annotation_ref, "get_object")
                    else annotation_ref
                )
                action = annotation.get("/A") if hasattr(annotation, "get") else None
                if hasattr(action, "get_object"):
                    action = action.get_object()
                uri = action.get("/URI") if hasattr(action, "get") else None
                if not isinstance(uri, str) or not re.match(r"(?i)^https?://", uri):
                    continue
                label = ""
                for key in ("/Contents", "/T", "/TU"):
                    value = annotation.get(key) if hasattr(annotation, "get") else None
                    if isinstance(value, str) and value.strip():
                        label = value.strip()
                        break
                rect = annotation.get("/Rect") if hasattr(annotation, "get") else None
                if hasattr(rect, "get_object"):
                    rect = rect.get_object()
                rect_values = [float(value) for value in rect] if rect is not None else []
            except Exception:
                continue

            context_lines = []
            uri_parsed = urlsplit(uri)
            uri_host = (uri_parsed.hostname or "").casefold().removeprefix("www.")
            path_parts = [part for part in uri_parsed.path.split("/") if part]
            association_needles = []
            if uri_host:
                association_needles.append(uri_host + uri_parsed.path.rstrip("/"))
                if path_parts:
                    association_needles.append(uri_host + "/" + path_parts[0])
            for line_index in range(len(text_lines)):
                window = " ".join(
                    line.strip()
                    for line in text_lines[max(0, line_index - 2):line_index + 3]
                    if line.strip()
                )
                compact_window = re.sub(r"\s+", "", window).casefold()
                if not any(
                    needle and needle.casefold() in compact_window
                    for needle in association_needles
                ):
                    continue
                if _CODE_KEYWORD_RE.search(window) or _DATA_KEYWORD_RE.search(window):
                    host_position = window.casefold().find(uri_host)
                    if host_position >= 0:
                        sentence_end = re.search(
                            r"[.!?](?:\s|$)",
                            window[host_position + len(uri_host):],
                        )
                        if sentence_end:
                            end_position = (
                                host_position
                                + len(uri_host)
                                + sentence_end.end()
                            )
                            window = window[:end_position].strip()
                    context_lines = [window]
                    break

            if not context_lines and len(rect_values) == 4 and fragments:
                x1, y1, x2, y2 = rect_values
                x_low, x_high = min(x1, x2), max(x1, x2)
                y_low, y_high = min(y1, y2), max(y1, y2)
                try:
                    page_width = float(page.mediabox.width)
                except (AttributeError, TypeError, ValueError):
                    page_width = 0.0
                link_center = (x_low + x_high) / 2
                for x, y, text_fragment in fragments:
                    same_column = True
                    if page_width > 0:
                        if link_center < page_width / 2:
                            same_column = x <= page_width / 2 + 36
                        else:
                            same_column = x >= page_width / 2 - 36
                    if same_column and y_low - 105 <= y <= y_high + 105:
                        if text_fragment not in context_lines:
                            context_lines.append(text_fragment)
                availability_context = [
                    item
                    for item in context_lines
                    if _CODE_KEYWORD_RE.search(item) or _DATA_KEYWORD_RE.search(item)
                ]
                if availability_context:
                    # Keep the decisive statement immediately before the URI;
                    # classification intentionally inspects only nearby lines.
                    context_lines = availability_context[-4:]
                else:
                    context_lines = context_lines[-6:]
            if label:
                context_lines.append(label)
            context_lines.append(uri)
            regions.append(
                (
                    f"PDF 文末超链接（第 {page_index + 1} 页）",
                    "\n".join(context_lines),
                    bool(reference_page),
                )
            )
            annotation_count += 1
            if annotation_count >= 40:
                return regions
    return regions


def _resource_type_for_context(context: str) -> str | None:
    has_code = bool(_CODE_KEYWORD_RE.search(context))
    has_data = bool(_DATA_KEYWORD_RE.search(context))
    has_code_resource = bool(_CODE_RESOURCE_RE.search(context))
    has_data_resource = bool(_DATA_RESOURCE_RE.search(context))
    if has_code and has_code_resource and not (has_data and has_data_resource):
        return "代码"
    if has_data and has_data_resource and not (has_code and has_code_resource):
        return "数据集"
    if has_code and has_data:
        return "代码与数据"
    if has_code:
        return "代码"
    if has_data:
        return "数据集"
    return None


def _iter_candidates(text: str):
    occupied: list[tuple[int, int]] = []
    for regex in (_SCHEME_URL_RE, _BARE_KNOWN_HOST_RE):
        for match in regex.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            occupied.append((match.start(), match.end()))
            yield match.group(0), match.start(), match.end()


def _collect_candidates(
    markdown_text: str,
    content_list_path: Path | None,
    origin_pdf_path: Path | None,
) -> list[_Candidate]:
    regions = _markdown_scan_regions(markdown_text)
    content_tail = _content_list_tail(content_list_path)
    if content_tail:
        boundary = _reference_boundary(content_tail)
        if boundary is None:
            regions.append(("MinerU 文末页面", content_tail, False))
        else:
            before_references = content_tail[:boundary]
            after_references = content_tail[boundary:]
            if before_references.strip():
                regions.append(("MinerU 文末页面", before_references, False))
            if after_references.strip():
                regions.append(("MinerU 参考文献后区域", after_references, True))
    regions.extend(_pdf_annotation_regions(origin_pdf_path))

    found: dict[str, dict] = {}
    confidence_rank = {None: 0, "中": 1, "高": 2}
    for evidence_source, text, requires_keyword in regions:
        for raw_url, start, end in _iter_candidates(text):
            url = _normalize_url(raw_url)
            if not url or _is_rejected_url(url):
                continue
            context = _context_for(text, start, end)
            classification_context = _preceding_line_context(text, start, end)
            rule_type = _resource_type_for_context(classification_context)
            known_platform = _is_known_platform(url)
            if requires_keyword and rule_type is None:
                continue
            if rule_type is None and not known_platform:
                continue

            rule_confidence = None
            if rule_type is not None:
                rule_confidence = "高" if known_platform else "中"

            key = _canonical_key(url)
            record = {
                "url": url,
                "platform": _platform_for_url(url),
                "context": context,
                "evidence_source": evidence_source,
                "rule_type": rule_type,
                "rule_confidence": rule_confidence,
            }
            previous = found.get(key)
            if previous is None or confidence_rank[rule_confidence] > confidence_rank[
                previous["rule_confidence"]
            ]:
                found[key] = record

    records = list(found.values())

    def is_likely_truncated(short_record: dict, long_record: dict) -> bool:
        """Detect a line-wrapped/OCR-truncated repository URL.

        Examples seen in publisher PDFs include ``PINN-`` + ``FGM`` and
        ``phase-field-fracture with-pidl`` where the PDF annotation retains the
        complete hyphenated URI.  The suffix must either follow a trailing
        hyphen directly or appear immediately after the short URL as plain
        text; two separately listed repository URLs are therefore preserved.
        """

        short_parsed = urlsplit(short_record["url"])
        long_parsed = urlsplit(long_record["url"])
        if (short_parsed.hostname or "").casefold() != (
            long_parsed.hostname or ""
        ).casefold():
            return False
        short_path = short_parsed.path.rstrip("/")
        long_path = long_parsed.path.rstrip("/")
        if not short_path or not long_path.startswith(short_path):
            return False
        suffix = long_path[len(short_path):]
        if not suffix:
            return False
        if short_path.endswith("-"):
            return True
        if not suffix.startswith("-"):
            return False

        context = short_record.get("context", "")
        position = context.casefold().find(short_record["url"].casefold())
        if position < 0:
            return False
        tail = context[position + len(short_record["url"]):position + len(short_record["url"]) + 120]
        # A second explicit URL means these may be two intentionally listed
        # repositories, not one wrapped URL.
        tail = re.split(r"(?i)https?://", tail, maxsplit=1)[0]
        suffix_token = re.sub(r"[^a-z0-9]+", "", suffix.casefold())
        tail_token = re.sub(r"[^a-z0-9]+", "", tail.casefold())
        return len(suffix_token) >= 3 and suffix_token in tail_token

    # PDF annotations sometimes contain the complete repository URI while the
    # extracted nearby text contains only its owner/group prefix. Transfer the
    # availability evidence from that prefix to the more specific URI before
    # removing the redundant fragment.
    for record in records:
        parsed = urlsplit(record["url"])
        host = (parsed.hostname or "").casefold()
        path = parsed.path.rstrip("/")
        for other in records:
            if other is record:
                continue
            other_parsed = urlsplit(other["url"])
            if (other_parsed.hostname or "").casefold() != host:
                continue
            other_path = other_parsed.path.rstrip("/")
            same_evidence_owner_prefix = (
                other_path.startswith(path + "/")
                and record["evidence_source"] == other["evidence_source"]
            )
            truncated_prefix = is_likely_truncated(record, other)
            if (
                (same_evidence_owner_prefix or truncated_prefix)
                and confidence_rank[record["rule_confidence"]]
                > confidence_rank[other["rule_confidence"]]
            ):
                other["rule_type"] = record["rule_type"]
                other["rule_confidence"] = record["rule_confidence"]
                other["context"] = record["context"]
    pruned_records = []
    for record in records:
        parsed = urlsplit(record["url"])
        host = (parsed.hostname or "").casefold()
        path = parsed.path.rstrip("/")
        redundant = False
        for other in records:
            if other is record:
                continue
            other_parsed = urlsplit(other["url"])
            if (other_parsed.hostname or "").casefold() != host:
                continue
            other_path = other_parsed.path.rstrip("/")
            # Prefer a repository over its owner/group page when both occur in
            # the same availability evidence, and drop OCR link fragments that
            # differ only by a trailing hyphen.
            if (
                other_path.startswith(path + "/")
                and record["evidence_source"] == other["evidence_source"]
            ) or is_likely_truncated(record, other):
                redundant = True
                break
        if not redundant:
            pruned_records.append(record)

    records = pruned_records[:40]
    return [
        _Candidate(candidate_id=index, **record)
        for index, record in enumerate(records, start=1)
    ]


def _build_llm_prompt(candidates: list[_Candidate]) -> str:
    payload = [
        {
            "id": item.candidate_id,
            "url": item.url,
            "platform": item.platform,
            "context": item.context,
            "rule_type": item.rule_type or "未确定",
        }
        for item in candidates
    ]
    return (
        "你是科研论文代码与数据可用性审计器。请判断每个候选超链接是否是本论文作者提供的"
        "源代码、实现脚本或研究数据集地址。\n"
        "严格规则：\n"
        "1. 只能分类下面已有的候选 id，不得生成、补全、修改或重写任何 URL。\n"
        "2. DOI、论文正文链接、出版商主页、作者主页、参考文献中的他人项目都标为 ignore。\n"
        "3. Zenodo、OSF、Figshare、Dataverse、Mendeley Data 等可属于 code、data 或 both，"
        "必须结合上下文判断。\n"
        "4. 仅在上下文明确表明链接属于本论文的 Code availability / Data availability 时保留。\n"
        "5. 只输出 JSON，不要 Markdown。格式："
        '{"classifications":[{"id":1,"type":"code|data|both|ignore",'
        '"confidence":"high|medium","reason":"简短理由"}]}。\n\n'
        "候选：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _parse_llm_classifications(response: str) -> dict[int, tuple[str, str]]:
    cleaned = (response or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM 未返回 JSON 对象")
    payload = json.loads(cleaned[start:end + 1])
    items = payload.get("classifications") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM JSON 缺少 classifications 列表")

    type_map = {
        "code": "代码",
        "data": "数据集",
        "both": "代码与数据",
        "ignore": "忽略",
        "代码": "代码",
        "数据": "数据集",
        "数据集": "数据集",
        "代码与数据": "代码与数据",
    }
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            candidate_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        resource_type = type_map.get(str(item.get("type", "")).strip().casefold())
        if resource_type is None:
            continue
        confidence_raw = str(item.get("confidence", "medium")).strip().casefold()
        confidence = "高" if confidence_raw in {"high", "高"} else "中"
        result[candidate_id] = (resource_type, confidence)
    return result


def extract_availability_links(
    markdown_text: str,
    content_list_path: Path | None = None,
    origin_pdf_path: Path | None = None,
    llm_callback: Callable[[str], str | None] | None = None,
) -> AvailabilityExtractionResult:
    """Extract trusted code/data links, optionally validating candidates with an LLM."""
    candidates = _collect_candidates(markdown_text, content_list_path, origin_pdf_path)
    classifications: dict[int, tuple[str, str]] = {}
    llm_attempted = bool(llm_callback and candidates)
    llm_succeeded = False
    llm_error = ""
    if llm_attempted:
        try:
            response = llm_callback(_build_llm_prompt(candidates))
            if not response:
                raise ValueError("LLM 未返回内容")
            classifications = _parse_llm_classifications(response)
            llm_succeeded = True
        except Exception as exc:
            llm_error = str(exc)

    links: list[OpenSourceLink] = []
    for candidate in candidates:
        llm_classification = classifications.get(candidate.candidate_id)
        if llm_classification is not None:
            llm_type, llm_confidence = llm_classification
            if llm_type == "忽略":
                # Explicit high-confidence availability rules remain deterministic;
                # LLM rejection only suppresses medium/ambiguous candidates.
                if candidate.rule_confidence != "高":
                    continue
                resource_type = candidate.rule_type
                confidence = candidate.rule_confidence
                method = "规则（LLM 保守冲突）"
            else:
                resource_type = llm_type
                confidence = (
                    "高"
                    if "高" in {candidate.rule_confidence, llm_confidence}
                    else "中"
                )
                method = "规则 + LLM" if candidate.rule_type else "LLM 核验"
        else:
            resource_type = candidate.rule_type
            confidence = candidate.rule_confidence
            method = "规则"

        if resource_type is None or confidence is None:
            continue
        links.append(
            OpenSourceLink(
                url=candidate.url,
                platform=candidate.platform,
                confidence=confidence,
                context=candidate.context,
                evidence_source=candidate.evidence_source,
                resource_type=resource_type,
                detection_method=method,
            )
        )

    links.sort(
        key=lambda item: (
            {"代码": 0, "数据集": 1, "代码与数据": 2}.get(item.resource_type, 3),
            item.platform.casefold(),
            item.url.casefold(),
        )
    )
    return AvailabilityExtractionResult(
        links=links,
        candidate_count=len(candidates),
        llm_attempted=llm_attempted,
        llm_succeeded=llm_succeeded,
        llm_error=llm_error,
    )


def extract_open_source_links(
    markdown_text: str,
    content_list_path: Path | None = None,
    origin_pdf_path: Path | None = None,
) -> list[OpenSourceLink]:
    """Compatibility wrapper returning rule-based code/data links."""
    return extract_availability_links(
        markdown_text,
        content_list_path,
        origin_pdf_path,
    ).links


def write_availability_report(
    article_title: str,
    links: list[OpenSourceLink],
    output_path: Path,
) -> Path | None:
    """Write a Markdown report only when at least one trusted link exists."""
    if not links:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 代码与数据可用性",
        "",
        f"> 来源论文：{article_title}",
        "> 识别范围：论文文末 Code availability / Data availability 等声明及其超链接；参考文献默认排除。",
        "> DOI 地址不收录。结果由规则与可选 LLM 核验，访问或使用前仍需结合原文人工确认。",
        "",
    ]
    for index, link in enumerate(links, 1):
        lines.extend(
            [
                f"## {index}. {link.platform}",
                "",
                f"- 类型：{link.resource_type}",
                f"- 地址：[{link.url}](<{link.url}>)",
                f"- 置信度：{link.confidence}",
                f"- 识别方式：{link.detection_method}",
                f"- 识别来源：{link.evidence_source}",
                f"- 文末上下文：{link.context}",
                "",
            ]
        )
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output_path


def write_open_source_report(
    article_title: str,
    links: list[OpenSourceLink],
    output_path: Path,
) -> Path | None:
    """Compatibility alias for the v1.4.6 report writer."""
    return write_availability_report(article_title, links, output_path)


def write_availability_scan_marker(
    output_path: Path,
    result: AvailabilityExtractionResult,
    report_written: bool,
) -> Path:
    """Persist completion state without creating an empty Markdown report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    code_count = sum(
        link.resource_type in {"代码", "代码与数据"} for link in result.links
    )
    data_count = sum(
        link.resource_type in {"数据集", "代码与数据"} for link in result.links
    )
    payload = {
        "schema_version": AVAILABILITY_SCHEMA_VERSION,
        "scan_completed": True,
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "candidate_count": result.candidate_count,
        "trusted_link_count": len(result.links),
        "code_link_count": code_count,
        "data_link_count": data_count,
        "llm_attempted": result.llm_attempted,
        "llm_succeeded": result.llm_succeeded,
        "report_written": bool(report_written),
    }
    # Write directly: Codex Guard workspaces may allow create/write while
    # intentionally denying rename/delete, so a temp-file replace would fail.
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def availability_scan_completed(article_extract_dir: Path) -> bool:
    marker = article_extract_dir / "OpenSource" / AVAILABILITY_SCAN_FILENAME
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8", errors="replace"))
        return bool(
            isinstance(payload, dict)
            and payload.get("scan_completed") is True
            and int(payload.get("schema_version", 0)) >= AVAILABILITY_SCHEMA_VERSION
        )
    except (OSError, ValueError, TypeError):
        return False


def count_report_links(markdown_text: str) -> int:
    return len(_REPORT_LINK_RE.findall(markdown_text))
