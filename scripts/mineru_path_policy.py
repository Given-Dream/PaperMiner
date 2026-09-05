#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bound MinerU/PaperMiner document paths for Windows compatibility.

MinerU uses the supplied document name as an output directory and writes
64-character image hashes below ``auto/images``.  On Windows installations
where legacy MAX_PATH handling is still active, an otherwise valid long PDF
name can therefore fail only when the first image is written.  This module
keeps storage names deterministic and records the original source name next
to shortened directories.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


SAFE_WINDOWS_PATH_LENGTH = 240
MAX_STORAGE_COMPONENT_LENGTH = 64
SOURCE_MANIFEST_NAME = ".paperminer-source.json"
SOURCE_MANIFEST_SCHEMA = 1
_HASH_LENGTH = 12
_MINERU_IMAGE_NAME = ("f" * 64) + ".jpg"


class DocumentPathTooLongError(ValueError):
    """Raised when even a hash-only document key cannot fit safely."""


def path_text_length(path: Path | str) -> int:
    """Return the absolute textual path length without requiring existence."""
    return len(os.path.abspath(os.fspath(path)))


def _digest(stem: str) -> str:
    return hashlib.sha256(stem.casefold().encode("utf-8")).hexdigest()[:_HASH_LENGTH]


def compact_document_name(
    stem: str,
    *,
    max_length: int = MAX_STORAGE_COMPONENT_LENGTH,
) -> str:
    """Build a readable, stable Windows directory component for ``stem``."""
    stem = str(stem).strip().rstrip(" .")
    if not stem:
        stem = "document"
    if len(stem) <= max_length:
        return stem

    suffix = "__" + _digest(stem)
    prefix_length = max(1, max_length - len(suffix))
    prefix = stem[:prefix_length].rstrip(" .") or "document"
    return prefix + suffix


def projected_mineru_image_path(raw_root: Path | str, storage_name: str) -> Path:
    return Path(raw_root) / storage_name / "auto" / "images" / _MINERU_IMAGE_NAME


def projected_extract_child_path(
    extract_root: Path | str,
    storage_name: str,
) -> Path:
    # Long filenames derived from the paper title are shortened separately by
    # ``choose_child_filename``.  This projection budgets the deepest fixed
    # PaperMiner metadata/report path while retaining the full outer folder
    # name whenever Windows can safely support it.
    return Path(extract_root) / storage_name / "References" / "references_scan.json"


def _choose_bounded_name(
    stem: str,
    projection,
    *,
    max_original_component_length: int = MAX_STORAGE_COMPONENT_LENGTH,
) -> str:
    original = str(stem).strip().rstrip(" .") or "document"
    if (
        len(original) <= max_original_component_length
        and path_text_length(projection(original)) <= SAFE_WINDOWS_PATH_LENGTH
    ):
        return original

    compact = compact_document_name(original)
    if path_text_length(projection(compact)) <= SAFE_WINDOWS_PATH_LENGTH:
        return compact

    hash_only = "pm_" + _digest(original)
    if path_text_length(projection(hash_only)) <= SAFE_WINDOWS_PATH_LENGTH:
        return hash_only

    projected = projection(hash_only)
    raise DocumentPathTooLongError(
        "输出根目录本身过深；即使使用短文档标识，预计路径仍为 "
        f"{path_text_length(projected)} 个字符：{projected}"
    )


def choose_mineru_storage_name(stem: str, raw_root: Path | str) -> str:
    """Choose the directory name passed to MinerU's ``pdf_file_names``."""
    return _choose_bounded_name(
        stem,
        lambda name: projected_mineru_image_path(raw_root, name),
    )


def choose_extract_storage_name(stem: str, extract_root: Path | str) -> str:
    """Choose a final document directory that leaves room for child files."""
    return _choose_bounded_name(
        stem,
        lambda name: projected_extract_child_path(extract_root, name),
        max_original_component_length=180,
    )


def choose_child_filename(
    parent: Path | str,
    preferred_name: str,
    fallback_name: str,
) -> str:
    """Use ``fallback_name`` when a preferred child would cross the budget."""
    preferred = Path(parent) / preferred_name
    if path_text_length(preferred) <= SAFE_WINDOWS_PATH_LENGTH:
        return preferred_name
    fallback = Path(parent) / fallback_name
    if path_text_length(fallback) <= SAFE_WINDOWS_PATH_LENGTH:
        return fallback_name
    raise DocumentPathTooLongError(
        "输出目录本身过深，短文件名仍无法安全写入："
        f"{fallback}"
    )


def write_source_manifest(
    document_directory: Path | str,
    *,
    source_stem: str,
    source_path: Path | str | None = None,
) -> Path:
    """Persist the original name for shortened raw/extract directories."""
    directory = Path(document_directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "source_stem": str(source_stem),
        "storage_name": directory.name,
    }
    if source_path is not None:
        payload["source_path"] = os.path.abspath(os.fspath(source_path))

    manifest = directory / SOURCE_MANIFEST_NAME
    temporary = directory / (SOURCE_MANIFEST_NAME + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, manifest)
    return manifest


def read_source_manifest(document_directory: Path | str) -> dict[str, Any] | None:
    manifest = Path(document_directory) / SOURCE_MANIFEST_NAME
    try:
        with open(manifest, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    source_stem = payload.get("source_stem")
    if not isinstance(source_stem, str) or not source_stem.strip():
        return None
    return payload


def source_stem_for_directory(document_directory: Path | str) -> str:
    directory = Path(document_directory)
    payload = read_source_manifest(directory)
    if payload is not None:
        return str(payload["source_stem"])
    return directory.name
