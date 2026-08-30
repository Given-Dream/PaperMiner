import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from gpu_advisor import build_gpu_recommendation, parse_nvidia_smi_csv


def make_samples(count=12, utilization=24, used_mib=4096, total_mib=24576):
    return [
        {
            "index": 0,
            "utilization_percent": utilization,
            "memory_used_mib": used_mib,
            "memory_total_mib": total_mib,
        }
        for _ in range(count)
    ]


class NvidiaSmiParserTests(unittest.TestCase):
    def test_parses_plain_and_unit_suffixed_rows(self):
        rows = parse_nvidia_smi_csv(
            "0, 21, 4096, 24576\n1, 78 %, 12288 MiB, 24576 MiB\n"
        )

        self.assertEqual([row["index"] for row in rows], [0, 1])
        self.assertEqual(rows[0]["utilization_percent"], 21)
        self.assertEqual(rows[1]["memory_used_mib"], 12288)

    def test_ignores_headers_and_incomplete_rows(self):
        rows = parse_nvidia_smi_csv(
            "index, utilization.gpu, memory.used, memory.total\n0, 30, 5000\n"
        )

        self.assertEqual(rows, [])


class GpuRecommendationTests(unittest.TestCase):
    def test_low_utilization_and_memory_headroom_increase_one_step(self):
        result = build_gpu_recommendation(
            [{"index": 0, "name": "GPU A", "workers": 1, "memory_gb": 24}],
            {0: make_samples()},
            {
                0: {
                    "started": 5,
                    "succeeded": 5,
                    "failed": 0,
                    "oom_count": 0,
                    "native_crash_count": 0,
                    "total_seconds": 250,
                }
            },
            created_at="2026-08-30T00:00:00",
        )

        card = result["per_gpu"][0]
        self.assertEqual(card["current_workers"], 1)
        self.assertEqual(card["recommended_workers"], 2)
        self.assertTrue(result["changed"])
        self.assertEqual(result["plan_text"], "GPU 0 × 2")

    def test_oom_reduces_only_one_step(self):
        result = build_gpu_recommendation(
            [{"index": 0, "name": "GPU A", "workers": 3}],
            {0: make_samples(utilization=70, used_mib=18000)},
            {
                0: {
                    "started": 3,
                    "succeeded": 2,
                    "failed": 1,
                    "oom_count": 1,
                    "native_crash_count": 0,
                }
            },
        )

        self.assertEqual(result["per_gpu"][0]["recommended_workers"], 2)
        self.assertIn("OOM", result["per_gpu"][0]["reason"])

    def test_incomplete_monitor_never_increases_concurrency(self):
        result = build_gpu_recommendation(
            [{"index": 0, "name": "GPU A", "workers": 1}],
            {0: make_samples()},
            {0: {"started": 5, "succeeded": 5}},
            monitor_error="nvidia-smi timeout",
        )

        self.assertEqual(result["per_gpu"][0]["recommended_workers"], 1)
        self.assertIn("不完整", result["per_gpu"][0]["reason"])

    def test_stopped_run_keeps_current_plan(self):
        result = build_gpu_recommendation(
            [{"index": 0, "name": "GPU A", "workers": 2}],
            {0: make_samples()},
            {0: {"started": 4, "succeeded": 4}},
            run_stopped=True,
        )

        self.assertEqual(result["per_gpu"][0]["recommended_workers"], 2)
        self.assertIn("提前停止", result["per_gpu"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
