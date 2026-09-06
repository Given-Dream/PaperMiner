"""Translate PaperMiner extraction choices into MinerU raw-output switches.

MinerU performs layout/OCR as one document analysis pass.  Its public
``do_parse`` API can still disable formula/table recognition and avoid writing
debug or downstream files that PaperMiner will not consume.  Keeping this
mapping in one small module makes the contract auditable and testable without
loading MinerU, PyTorch or Tk.
"""

from __future__ import annotations

from collections.abc import Iterable


FEATURE_KEYS = (
    "title",
    "text",
    "formula",
    "figures",
    "tables",
    "sections",
    "open_source",
    "references",
)

FEATURE_LABELS = {
    "title": "文章标题",
    "text": "文字/Markdown",
    "formula": "公式",
    "figures": "图片与编号",
    "tables": "表格",
    "sections": "论文章节",
    "open_source": "代码/数据可用性",
    "references": "参考文献",
}

_FEATURE_SET = frozenset(FEATURE_KEYS)
_CONTENT_LIST_CONSUMERS = frozenset(
    {
        "title",
        "text",
        "formula",
        "figures",
        "tables",
        "open_source",
        "references",
    }
)
_ORIGIN_PDF_CONSUMERS = frozenset({"title", "figures", "open_source"})


def normalize_features(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """Return validated features in stable UI order.

    ``None`` means the legacy all-features behaviour.  This preserves command
    line compatibility for older launchers while the v1.4.24 GUI always sends
    an explicit selection.
    """

    if value is None:
        requested = set(FEATURE_KEYS)
    elif isinstance(value, str):
        requested = {part.strip() for part in value.split(",") if part.strip()}
    else:
        requested = {str(part).strip() for part in value if str(part).strip()}

    unknown = sorted(requested - _FEATURE_SET)
    if unknown:
        raise ValueError("未知 raw 提取项: " + ", ".join(unknown))
    if not requested:
        raise ValueError("至少需要一个 raw 提取项")
    return tuple(key for key in FEATURE_KEYS if key in requested)


def build_mineru_options(features: str | Iterable[str] | None) -> dict:
    """Build the supported MinerU ``do_parse`` switches for a selection."""

    selected = frozenset(normalize_features(features))
    has_visual_output = bool(selected & {"figures", "tables"})
    return {
        # These two switches really avoid the corresponding model stage.
        "formula_enable": "formula" in selected,
        "table_enable": "tables" in selected,
        # VLM/hybrid can skip semantic image analysis.  Pipeline still performs
        # joint layout analysis and may create image intermediates.
        "image_analysis": "figures" in selected,
        # NLP markdown omits image/chart/table blocks.  Multimedia markdown is
        # retained only when a selected downstream result consumes it.
        "f_make_md_mode": "mm_markdown" if has_visual_output else "nlp_markdown",
        "f_dump_md": True,
        "f_dump_content_list": bool(selected & _CONTENT_LIST_CONSUMERS),
        "f_dump_middle_json": "figures" in selected,
        "f_dump_orig_pdf": bool(selected & _ORIGIN_PDF_CONSUMERS),
        # PaperMiner never consumes these large diagnostic artefacts.  Runtime
        # errors are preserved in the application log instead.
        "f_dump_model_output": False,
        "f_draw_layout_bbox": False,
        "f_draw_span_bbox": False,
    }


def describe_policy(features: str | Iterable[str] | None) -> tuple[str, str]:
    """Return concise, user-facing selection and raw-file summaries."""

    selected = normalize_features(features)
    options = build_mineru_options(selected)
    selected_text = "、".join(FEATURE_LABELS[key] for key in selected)

    files = ["Markdown"]
    if options["f_dump_content_list"]:
        files.append("content list")
    if options["f_dump_middle_json"]:
        files.append("middle JSON")
    if options["f_dump_orig_pdf"]:
        files.append("原 PDF 副本")
    return selected_text, "、".join(files)
