#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure helpers for PaperMiner GPU telemetry and next-run recommendations."""

from __future__ import annotations

import math
import re
import time
from typing import Iterable


MAX_WORKERS_PER_GPU = 4


def _number(value, default=0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else float(default)


def _integer(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def parse_nvidia_smi_csv(output: str) -> list[dict]:
    """Parse index/utilization/memory.used/memory.total CSV rows.

    The parser also tolerates units so it can be tested with output produced
    without ``nounits``.
    """
    rows = []
    for raw_line in str(output or "").splitlines():
        parts = [part.strip() for part in raw_line.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpu_id = int(_number(parts[0], -1))
        except (TypeError, ValueError):
            continue
        if gpu_id < 0:
            continue
        total_mib = max(0.0, _number(parts[3]))
        rows.append(
            {
                "index": gpu_id,
                "utilization_percent": max(0.0, min(100.0, _number(parts[1]))),
                "memory_used_mib": max(0.0, _number(parts[2])),
                "memory_total_mib": total_mib,
            }
        )
    return rows


def _normalise_samples(samples: Iterable[dict]) -> list[dict]:
    normalised = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        total = _number(sample.get("memory_total_mib"))
        used = _number(sample.get("memory_used_mib"))
        util = _number(sample.get("utilization_percent"))
        if total <= 0:
            continue
        normalised.append(
            {
                "utilization_percent": max(0.0, min(100.0, util)),
                "memory_used_mib": max(0.0, min(used, total)),
                "memory_total_mib": total,
            }
        )
    return normalised


def build_gpu_recommendation(
    assignments: Iterable[dict],
    samples_by_gpu: dict,
    job_stats_by_gpu: dict,
    *,
    monitor_error: str = "",
    run_stopped: bool = False,
    created_at: str | None = None,
) -> dict:
    """Build a conservative per-GPU worker recommendation.

    A recommendation may move by at most one worker per completed run.  GPU
    telemetry is system-wide, so high memory pressure can reduce concurrency,
    while an increase requires several active samples and successful jobs.
    """
    per_gpu = []
    for raw_assignment in assignments or []:
        if not isinstance(raw_assignment, dict):
            continue
        gpu_id = _integer(raw_assignment.get("index"), -1)
        if gpu_id < 0:
            continue
        current_workers = max(
            1,
            min(MAX_WORKERS_PER_GPU, _integer(raw_assignment.get("workers"), 1)),
        )
        name = str(raw_assignment.get("name") or f"GPU {gpu_id}")
        samples = _normalise_samples(
            samples_by_gpu.get(gpu_id, samples_by_gpu.get(str(gpu_id), []))
        )
        raw_stats = job_stats_by_gpu.get(
            gpu_id,
            job_stats_by_gpu.get(str(gpu_id), {}),
        )
        stats = raw_stats if isinstance(raw_stats, dict) else {}
        jobs_started = max(0, _integer(stats.get("started")))
        jobs_succeeded = max(0, _integer(stats.get("succeeded")))
        jobs_failed = max(0, _integer(stats.get("failed")))
        oom_count = max(0, _integer(stats.get("oom_count")))
        native_crash_count = max(0, _integer(stats.get("native_crash_count")))
        total_job_seconds = max(0.0, _number(stats.get("total_seconds")))
        avg_job_seconds = total_job_seconds / jobs_started if jobs_started else 0.0

        if samples:
            initial_window = samples[: min(3, len(samples))]
            baseline_mib = min(item["memory_used_mib"] for item in initial_window)
            peak_memory_mib = max(item["memory_used_mib"] for item in samples)
            memory_total_mib = max(item["memory_total_mib"] for item in samples)
            active_samples = [
                item
                for item in samples
                if item["utilization_percent"] >= 5.0
                or item["memory_used_mib"] >= baseline_mib + 256.0
            ]
            utilization_basis = active_samples or samples
            avg_utilization = sum(
                item["utilization_percent"] for item in utilization_basis
            ) / len(utilization_basis)
            peak_utilization = max(
                item["utilization_percent"] for item in samples
            )
        else:
            baseline_mib = 0.0
            peak_memory_mib = 0.0
            memory_total_mib = max(
                0.0,
                _number(raw_assignment.get("memory_gb")) * 1024.0,
            )
            active_samples = []
            avg_utilization = 0.0
            peak_utilization = 0.0

        peak_memory_ratio = (
            peak_memory_mib / memory_total_mib if memory_total_mib > 0 else 0.0
        )
        headroom_mib = max(0.0, memory_total_mib - peak_memory_mib)
        observed_delta_mib = max(0.0, peak_memory_mib - baseline_mib)
        per_worker_mib = max(512.0, observed_delta_mib / current_workers)
        usable_for_workers = max(0.0, memory_total_mib * 0.82 - baseline_mib)
        safe_by_memory = max(
            1,
            min(
                MAX_WORKERS_PER_GPU,
                int(math.floor(usable_for_workers / per_worker_mib))
                if per_worker_mib > 0
                else current_workers,
            ),
        )

        recommended_workers = current_workers
        confidence = "低"
        if oom_count:
            recommended_workers = max(1, current_workers - 1)
            confidence = "高"
            reason = "本轮出现 CUDA OOM，下一轮先降低一档并发。"
        elif native_crash_count:
            recommended_workers = max(1, current_workers - 1)
            confidence = "高"
            reason = "本轮出现 CUDA/原生进程崩溃，下一轮先降低一档并发。"
        elif samples and (peak_memory_ratio >= 0.92 or headroom_mib < 1024.0):
            recommended_workers = max(1, current_workers - 1)
            confidence = "高"
            reason = "系统级显存峰值已接近上限，下一轮先降低一档并发。"
        elif run_stopped:
            reason = "本轮被提前停止，样本不完整，暂时保持当前并发。"
        elif monitor_error:
            reason = "GPU 运行期采样不完整，暂不根据残缺数据提高并发。"
        elif jobs_failed:
            reason = "本轮存在 GPU 解析失败，暂不建议提高并发。"
            confidence = "中" if samples else "低"
        elif len(active_samples) < 4 or jobs_started < max(2, current_workers):
            reason = "有效负载样本或已完成任务不足，暂时保持当前并发。"
        elif (
            current_workers < MAX_WORKERS_PER_GPU
            and safe_by_memory >= current_workers + 1
            and peak_memory_ratio < 0.82
            and avg_utilization < 65.0
        ):
            recommended_workers = current_workers + 1
            confidence = "高" if len(active_samples) >= 10 and jobs_started >= 3 else "中"
            reason = "GPU 平均利用率较低且显存仍有安全余量，建议只提高一档。"
        elif avg_utilization >= 85.0:
            confidence = "中"
            reason = "GPU 已接近持续忙碌，增加并发通常不会继续提速。"
        elif peak_memory_ratio >= 0.78:
            confidence = "中"
            reason = "显存峰值偏高，保持当前并发更稳妥。"
        else:
            confidence = "中"
            reason = "利用率与显存余量处于平衡区间，保持当前并发。"

        per_gpu.append(
            {
                "index": gpu_id,
                "name": name,
                "current_workers": current_workers,
                "recommended_workers": recommended_workers,
                "confidence": confidence,
                "reason": reason,
                "samples": len(samples),
                "active_samples": len(active_samples),
                "avg_utilization": round(avg_utilization, 1),
                "peak_utilization": round(peak_utilization, 1),
                "baseline_memory_mib": round(baseline_mib, 1),
                "peak_memory_mib": round(peak_memory_mib, 1),
                "memory_total_mib": round(memory_total_mib, 1),
                "peak_memory_ratio": round(peak_memory_ratio, 4),
                "jobs_started": jobs_started,
                "jobs_succeeded": jobs_succeeded,
                "jobs_failed": jobs_failed,
                "oom_count": oom_count,
                "native_crash_count": native_crash_count,
                "avg_job_seconds": round(avg_job_seconds, 1),
            }
        )

    plan_text = " + ".join(
        f"GPU {item['index']} × {item['recommended_workers']}"
        for item in per_gpu
    ) or "暂无 GPU 建议"
    return {
        "schema_version": 1,
        "created_at": created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plan_text": plan_text,
        "changed": any(
            item["recommended_workers"] != item["current_workers"]
            for item in per_gpu
        ),
        "run_stopped": bool(run_stopped),
        "monitor_error": str(monitor_error or ""),
        "per_gpu": per_gpu,
    }


def recommendation_evidence_text(recommendation: dict) -> str:
    """Return a concise, user-facing evidence line for the task board."""
    items = recommendation.get("per_gpu", []) if isinstance(recommendation, dict) else []
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("samples", 0):
            peak_gib = _number(item.get("peak_memory_mib")) / 1024.0
            total_gib = _number(item.get("memory_total_mib")) / 1024.0
            parts.append(
                f"GPU {item.get('index')}: 平均 {item.get('avg_utilization', 0):g}%，"
                f"显存峰值 {peak_gib:.1f}/{total_gib:.1f} GiB"
            )
        else:
            parts.append(f"GPU {item.get('index')}: 未取得有效采样")
    return "；".join(parts)
