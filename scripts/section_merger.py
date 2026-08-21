"""Merge matching article sections and chart summaries into Markdown or Word."""
import os
from pathlib import Path
import re


def find_sections(extract_root: Path):
    """Return {section_name: [(article_title, markdown_path), ...]} for extracted papers."""
    result = {}
    # Some runs produce only the full article Markdown (without Sections/).
    # Materialize standard sections from that source so it can still be merged.
    for article_dir in extract_root.iterdir() if extract_root.exists() else []:
        if not article_dir.is_dir() or article_dir.name == "MergedSections":
            continue
        sections_dir = article_dir / "Sections"
        source_files = [p for p in article_dir.glob("*.md") if "_合并" not in p.stem]
        if source_files:
            # Fill only missing standard sections; preserve explicitly extracted files.
            _materialize_standard_sections(source_files[0], sections_dir, only_missing=True)

    for sections_dir in extract_root.glob("*/Sections"):
        if not sections_dir.is_dir():
            continue
        title = sections_dir.parent.name
        for path in sorted(sections_dir.glob("*.md")):
            result.setdefault(path.stem, []).append((title, path))
    return result


def find_chart_markdowns(extract_root: Path):
    """Return ``[(article_title, markdown_path), ...]`` from each Word folder."""
    result = []
    article_dirs = sorted(
        (path for path in extract_root.iterdir() if path.is_dir()),
        key=lambda path: path.name.casefold(),
    ) if extract_root.exists() else []
    for article_dir in article_dirs:
        if article_dir.name == "MergedSections":
            continue
        word_dir = article_dir / "Word"
        if not word_dir.is_dir():
            continue
        markdown_files = sorted(
            (
                path for path in word_dir.glob("*.md")
                if "_合并" not in path.stem and path.stat().st_size > 0
            ),
            key=lambda path: path.name.casefold(),
        )
        for path in markdown_files:
            result.append((article_dir.name, path))
    return result


_MARKDOWN_LINK_RE = re.compile(
    r"(!?\[(?:[^\[\]]|\[[^\]]*\])*\]\()([^)]+)(\))"
)


def _rewrite_chart_links(
    content: str,
    source: Path,
    target: Path,
    extract_root: Path,
):
    """Keep local images valid after moving Word Markdown into MergedSections."""
    extract_root = extract_root.resolve()
    target_parent = target.parent.resolve()

    def replace(match):
        raw_destination = match.group(2).strip()
        destination = raw_destination
        if destination.startswith("<") and destination.endswith(">"):
            destination = destination[1:-1].strip()
        if (
            not destination
            or destination.startswith(("#", "/", "\\"))
            or re.match(r"^[a-z][a-z0-9+.-]*:", destination, re.IGNORECASE)
            or Path(destination).is_absolute()
        ):
            return match.group(0)

        resolved = (source.parent / destination).resolve()
        try:
            resolved.relative_to(extract_root)
        except ValueError:
            return match.group(0)

        relative = os.path.relpath(resolved, target_parent).replace("\\", "/")
        if any(character.isspace() for character in relative) or any(
            character in relative for character in "()"
        ):
            relative = f"<{relative}>"
        return f"{match.group(1)}{relative}{match.group(3)}"

    return _MARKDOWN_LINK_RE.sub(replace, content)


def _prepare_chart_markdown(
    content: str,
    source: Path,
    target: Path,
    extract_root: Path,
):
    """Remove the source title, nest its headings, and rebase local links."""
    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r"^#\s+", line):
            del lines[index]
        break

    nested = []
    for line in lines:
        heading = re.match(r"^(#{1,5})(\s+.*)$", line)
        if heading:
            line = f"#{heading.group(1)}{heading.group(2)}"
        nested.append(line)
    prepared = "\n".join(nested).strip()
    return _rewrite_chart_links(prepared, source, target, extract_root)


def _materialize_standard_sections(source: Path, sections_dir: Path, only_missing: bool = False):
    """Extract common paper sections from a full Markdown source file."""
    text = source.read_text(encoding="utf-8", errors="replace")
    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    if not headings:
        return
    aliases = {
        "abstract": "Abstract",
        "introduction": "Introduction",
        "method": "Methods",
        "methods": "Methods",
        "materials and methods": "Methods",
        "methodology": "Methods",
        "numerical model": "Methods",
        "mathematical model": "Methods",
        "results": "Results & Discussion",
        "results and discussion": "Results & Discussion",
        "results & discussion": "Results & Discussion",
        "discussion": "Results & Discussion",
        "model validation": "Results & Discussion",
        "conclusion": "Conclusion",
        "conclusions": "Conclusion",
    }
    def classify(title):
        normalized_title = re.sub(r"[^a-z]+", " ", title.lower()).strip()
        canonical_title = aliases.get(normalized_title)
        if canonical_title is None and normalized_title.replace(" ", "") == "abstract":
            canonical_title = "Abstract"
        return canonical_title, normalized_title

    extracted = {}
    for index, match in enumerate(headings):
        raw_title = match.group(2).strip().strip("#").strip()
        canonical, normalized = classify(raw_title)
        if not canonical:
            continue
        end = len(text)
        for next_match in headings[index + 1:]:
            next_title = next_match.group(2).strip().strip("#").strip()
            next_canonical, next_normalized = classify(next_title)
            if next_canonical and next_canonical != canonical:
                end = next_match.start()
                break
            if next_normalized in {"acknowledgment", "acknowledgments", "acknowledgement", "acknowledgements", "references", "bibliography"}:
                end = next_match.start()
                break
        content = text[match.end():end].strip()
        if content and canonical not in extracted:
            extracted[canonical] = content
    if extracted:
        sections_dir.mkdir(parents=True, exist_ok=True)
        for name, content in extracted.items():
            target = sections_dir / f"{name}.md"
            if not only_missing or not target.exists():
                target.write_text(content + "\n", encoding="utf-8")


def merge_section_to_docx(extract_root: Path, section_name: str, output_path: Path):
    """Merge one same-named section from all papers into a DOCX."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    matches = find_sections(extract_root).get(section_name, [])
    if not matches:
        raise ValueError(f"未找到章节: {section_name}")
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(2.54)
    styles = doc.styles
    styles["Normal"].font.name = "Microsoft YaHei"
    styles["Normal"].font.size = Pt(10.5)
    title = doc.add_paragraph(section_name, style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for index, (article_title, path) in enumerate(matches):
        if index:
            doc.add_page_break()
        doc.add_heading(article_title, level=1)
        text = path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"\n\s*\n", text):
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            if len(lines) == 1 and re.match(r"^#{1,6}\s+", lines[0]):
                level = min(len(lines[0]) - len(lines[0].lstrip("#")), 3)
                doc.add_heading(re.sub(r"^#{1,6}\s+", "", lines[0]).strip(), level=level)
            else:
                p = doc.add_paragraph()
                p.add_run("\n".join(lines))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path, len(matches)


def merge_all_sections_to_docx(extract_root: Path, output_path: Path):
    """Merge every same-named section into a separate DOCX file."""
    grouped = find_sections(extract_root)
    if not grouped:
        raise ValueError("未找到可合并的章节")
    output_path.mkdir(parents=True, exist_ok=True)
    outputs = []
    total = 0
    for section_name in sorted(grouped):
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", section_name).strip() or "未命名章节"
        output, count = merge_section_to_docx(extract_root, section_name, output_path / f"{safe_name}_合并.docx")
        outputs.append(output)
        total += count
    return outputs, total, len(grouped)


def _write_section_markdowns(grouped, output_path: Path):
    """Write pre-grouped sections and return outputs plus source count."""
    output_path.mkdir(parents=True, exist_ok=True)
    outputs = []
    total = 0
    for section_name in sorted(grouped):
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", section_name).strip() or "未命名章节"
        target = output_path / f"{safe_name}_合并.md"
        chunks = [f"# {section_name}\n"]
        for article_title, source in grouped[section_name]:
            content = source.read_text(encoding="utf-8", errors="replace").strip()
            chunks.append(f"\n## 【{article_title}】\n\n{content}\n")
            total += 1
        target.write_text("\n".join(chunks), encoding="utf-8")
        outputs.append(target)
    return outputs, total


def merge_all_sections_to_markdown(extract_root: Path, output_path: Path):
    """Write one Markdown file per section, preserving source LaTeX verbatim."""
    grouped = find_sections(extract_root)
    if not grouped:
        raise ValueError("未找到可合并的章节")
    outputs, total = _write_section_markdowns(grouped, output_path)
    return outputs, total, len(grouped)


def merge_chart_markdowns(extract_root: Path, target: Path, sources=None):
    """Merge Word-folder chart Markdown and keep all relative media links valid."""
    sources = find_chart_markdowns(extract_root) if sources is None else sources
    if not sources:
        raise ValueError("未找到 Word 文件夹中的图表 Markdown")

    target.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        "# 图表汇总\n",
        "> 来源：各论文 Word 文件夹中的 Markdown 图表汇总。\n",
    ]
    for article_title, source in sources:
        content = source.read_text(encoding="utf-8", errors="replace")
        content = _prepare_chart_markdown(content, source, target, extract_root)
        chunks.append(f"\n## 【{article_title}】\n")
        if content:
            chunks.append(f"\n{content}\n")
        else:
            chunks.append("\n> 此图表 Markdown 为空。\n")

    target.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
    return target, len(sources)


def merge_all_sections_and_charts_to_markdown(
    extract_root: Path,
    output_path: Path,
):
    """Merge same-named sections plus Word-folder chart Markdown in one action."""
    grouped = find_sections(extract_root)
    chart_sources = find_chart_markdowns(extract_root)
    if not grouped and not chart_sources:
        raise ValueError("未找到可合并的章节或 Word 文件夹图表 Markdown")

    output_path.mkdir(parents=True, exist_ok=True)
    outputs = []
    total_section_articles = 0
    if grouped:
        section_outputs, total_section_articles = _write_section_markdowns(
            grouped,
            output_path,
        )
        outputs.extend(section_outputs)

    chart_count = 0
    if chart_sources:
        chart_output, chart_count = merge_chart_markdowns(
            extract_root,
            output_path / "图表汇总_合并.md",
            chart_sources,
        )
        outputs.append(chart_output)

    return outputs, total_section_articles, len(grouped), chart_count


def _legacy_merge_all_sections_to_docx(extract_root: Path, output_path: Path):
    """Legacy single-document implementation retained for compatibility."""
    from docx import Document
    from docx.shared import Cm, Pt
    grouped = find_sections(extract_root)
    if not grouped:
        raise ValueError("未找到可合并的章节")
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(2.54)
    doc.styles["Normal"].font.name = "Microsoft YaHei"
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_paragraph("合并章节", style="Title")
    total = 0
    for section_name in sorted(grouped):
        doc.add_heading(section_name, level=1)
        for article_title, path in grouped[section_name]:
            doc.add_heading(article_title, level=2)
            for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace")):
                block = block.strip()
                if block:
                    doc.add_paragraph(block)
            total += 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path, total, len(grouped)
