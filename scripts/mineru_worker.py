#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one MinerU document in an isolated process.

PaperMiner starts this helper with the same Conda interpreter as the GUI.  A
native CUDA/ONNX/PyTorch failure can therefore terminate this process without
terminating PaperMiner itself, and Windows releases all per-document CPU/GPU
resources when the helper exits.
"""

from __future__ import annotations

import argparse
import faulthandler
import importlib.metadata
import io
import os
from pathlib import Path
import re
import sys
import traceback

try:
    from raw_output_policy import build_mineru_options, describe_policy, normalize_features
except ImportError:
    from scripts.raw_output_policy import (
        build_mineru_options,
        describe_policy,
        normalize_features,
    )


MIN_MINERU_VERSION = (3, 1)
MAX_MINERU_VERSION = (4, 0)


def _prepare_standard_stream(stream_name: str):
    stream = getattr(sys, stream_name, None)
    if stream is None or getattr(stream, "encoding", None) is None:
        stream = open(os.devnull, "w", encoding="utf-8", errors="replace")
        setattr(sys, stream_name, stream)
        return stream
    try:
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, OSError, ValueError):
        if hasattr(stream, "buffer"):
            stream = io.TextIOWrapper(
                stream.buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
            )
            setattr(sys, stream_name, stream)
    return stream


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PaperMiner isolated MinerU worker")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--document-name",
        help="Bounded single-component output name selected by PaperMiner",
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--backend", default="pipeline")
    parser.add_argument("--model-source", default="modelscope")
    parser.add_argument(
        "--features",
        help=(
            "Comma-separated PaperMiner extraction features. "
            "Omitting it preserves legacy all-feature behaviour."
        ),
    )
    return parser.parse_args()


def main() -> int:
    _prepare_standard_stream("stdout")
    _prepare_standard_stream("stderr")
    try:
        faulthandler.enable(all_threads=True)
    except (RuntimeError, OSError, ValueError):
        pass

    args = _parse_args()
    try:
        selected_features = normalize_features(getattr(args, "features", None))
    except ValueError as exc:
        print(f"[WORKER ERROR] raw 输出策略无效: {exc}", flush=True)
        return 14
    mineru_options = build_mineru_options(selected_features)
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if not input_path.is_file():
        print(f"[WORKER ERROR] 输入 PDF 不存在: {input_path}", flush=True)
        return 10

    document_name = args.document_name or input_path.stem
    if (
        document_name in {"", ".", ".."}
        or Path(document_name).name != document_name
        or "/" in document_name
        or "\\" in document_name
    ):
        print(f"[WORKER ERROR] 非法文档目录名: {document_name!r}", flush=True)
        return 13

    os.environ["MINERU_DEVICE_MODE"] = args.device
    os.environ["MINERU_MODEL_SOURCE"] = args.model_source
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONNOUSERSITE", "1")

    try:
        mineru_version = importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        print("[WORKER ERROR] 未安装 MinerU。请从安装程序执行重装。", flush=True)
        return 11

    parsed_version = _version_tuple(mineru_version)
    if not (MIN_MINERU_VERSION <= parsed_version < MAX_MINERU_VERSION):
        print(
            "[WORKER ERROR] 不支持的 MinerU 版本: "
            f"{mineru_version}；需要 >=3.1.0,<4.0。请从安装程序执行重装。",
            flush=True,
        )
        return 12

    try:
        import mineru
        from mineru.cli.common import do_parse, read_fn

        print(
            f"mineru: {mineru_version}  路径: {Path(mineru.__file__).resolve().parent}",
            flush=True,
        )
        print(
            "参数: "
            f"device={args.device}, backend={args.backend}, "
            f"model_source={args.model_source}",
            flush=True,
        )
        print(f"输入: {input_path.name}", flush=True)
        print(f"输出: {output_path}", flush=True)
        feature_text, file_text = describe_policy(selected_features)
        print(f"勾选内容: {feature_text}", flush=True)
        print(f"raw 保留: {file_text}", flush=True)
        print(
            "识别开关: "
            f"formula={'on' if mineru_options['formula_enable'] else 'off'}, "
            f"table={'on' if mineru_options['table_enable'] else 'off'}, "
            f"image_analysis={'on' if mineru_options['image_analysis'] else 'off'}",
            flush=True,
        )
        if args.backend == "pipeline" and not mineru_options["image_analysis"]:
            print(
                "提示: pipeline 使用联合版面分析，未勾选图片时仍可能产生必要的图片中间文件。",
                flush=True,
            )
        if document_name != input_path.stem:
            print(f"路径保护: 使用短目录 {document_name}", flush=True)
        print("正在处理，请稍候...", flush=True)

        output_path.mkdir(parents=True, exist_ok=True)
        pdf_bytes = read_fn(input_path)
        do_parse(
            output_dir=str(output_path),
            pdf_file_names=[document_name],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=["ch"],
            backend=args.backend,
            parse_method="auto",
            **mineru_options,
        )
        print("[WORKER OK] MinerU 处理完成", flush=True)
        return 0
    except Exception as exc:
        print(f"[WORKER ERROR] MinerU 处理失败: {exc}", flush=True)
        traceback.print_exc()
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
