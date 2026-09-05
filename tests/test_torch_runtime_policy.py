import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import torch_runtime_policy as policy


class TorchSelectionPolicyTests(unittest.TestCase):
    def test_rtx_5060_with_current_driver_selects_cu130(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 5060, 596.21, 8192, 12.0\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertTrue(selected.blackwell_present)
        self.assertEqual(selected.cuda_index, "cu130")
        self.assertEqual(selected.package_spec, policy.DEFAULT_PACKAGE_SPEC)

    def test_rtx_50_name_is_enough_when_compute_capability_is_unavailable(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 5070 Laptop GPU, 596.21, 8192\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cu130")

    def test_blackwell_with_cuda_128_only_driver_uses_pinned_last_build(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 5060, 572.83, 8192, 12.0\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cu128")
        self.assertIn("torch==2.11.0", selected.package_spec)

    def test_blackwell_below_pytorch_cu130_windows_floor_stays_on_cu128(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 5090, 580.50, 32768, 12.0\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cu128")
        self.assertEqual(selected.minimum_driver, "570.65")

    def test_rtx_40_ada_uses_cu126_on_supported_driver(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 4090, 596.21, 24564, 8.9\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertFalse(selected.blackwell_present)
        self.assertEqual(selected.cuda_index, "cu126")
        self.assertEqual(selected.gpu_families, ("RTX 40 / Ada",))

    def test_rtx_30_ampere_uses_cu126_on_supported_driver(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 3090, 566.36, 24576, 8.6\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cu126")
        self.assertEqual(selected.gpu_families, ("RTX 30 / Ampere",))

    def test_rtx_30_with_older_driver_uses_cu121(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 3080, 552.22, 10240, 8.6\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cu121")

    def test_mixed_rtx_40_and_50_uses_blackwell_policy_for_all_cards(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 4090, 596.21, 24564, 8.9\n"
            "1, NVIDIA GeForce RTX 5060, 596.21, 8192, 12.0\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cu130")
        self.assertEqual(
            selected.gpu_families,
            ("RTX 40 / Ada", "RTX 50 / Blackwell"),
        )

    def test_blackwell_with_old_driver_cannot_keep_a_cuda_wheel(self):
        gpus = policy.parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 5060, 566.36, 8192, 12.0\n"
        )
        selected = policy.choose_torch_policy(gpus)
        self.assertEqual(selected.cuda_index, "cpu")
        self.assertEqual(selected.minimum_driver, "570.65")

    def test_cu126_does_not_satisfy_blackwell_cu130_policy(self):
        self.assertFalse(policy.cuda_runtime_meets_policy("12.6", "cu130"))
        self.assertTrue(policy.cuda_runtime_meets_policy("13.0", "cu130"))


class _FakeCuda:
    def is_available(self):
        return True

    def device_count(self):
        return 1

    def get_arch_list(self):
        return ["sm_90", "sm_120"]

    def get_device_name(self, _index):
        return "NVIDIA GeForce RTX 5060"

    def get_device_capability(self, _index):
        return (12, 0)


class TorchRuntimeVerificationTests(unittest.TestCase):
    def test_runtime_mismatch_is_rejected_before_kernel_probe(self):
        fake_torch = SimpleNamespace(
            __version__="2.14.0+cu126",
            version=SimpleNamespace(cuda="12.6"),
            cuda=_FakeCuda(),
        )
        with mock.patch.object(policy, "_probe_cuda_device") as probe:
            ok, messages = policy.verify_torch_runtime(
                "cu130",
                torch_module=fake_torch,
            )
        self.assertFalse(ok)
        probe.assert_not_called()
        self.assertIn("does not satisfy cu130", "\n".join(messages))

    def test_real_kernel_failure_rejects_otherwise_matching_runtime(self):
        fake_torch = SimpleNamespace(
            __version__="2.14.0+cu130",
            version=SimpleNamespace(cuda="13.0"),
            cuda=_FakeCuda(),
        )
        with mock.patch.object(
            policy,
            "_probe_cuda_device",
            side_effect=RuntimeError("no kernel image"),
        ):
            ok, messages = policy.verify_torch_runtime(
                "cu130",
                torch_module=fake_torch,
            )
        self.assertFalse(ok)
        self.assertIn("no kernel image", "\n".join(messages))

    def test_matching_runtime_and_kernel_are_accepted(self):
        fake_torch = SimpleNamespace(
            __version__="2.14.0+cu130",
            version=SimpleNamespace(cuda="13.0"),
            cuda=_FakeCuda(),
        )
        with mock.patch.object(policy, "_probe_cuda_device", return_value=272.0):
            ok, messages = policy.verify_torch_runtime(
                "cu130",
                torch_module=fake_torch,
            )
        self.assertTrue(ok)
        self.assertIn("CUDA float16 kernel OK", "\n".join(messages))

    def test_strict_cpu_policy_rejects_an_installed_cuda_wheel(self):
        fake_torch = SimpleNamespace(
            __version__="2.14.0+cu126",
            version=SimpleNamespace(cuda="12.6"),
            cuda=_FakeCuda(),
        )
        ok, messages = policy.verify_torch_runtime(
            "cpu",
            torch_module=fake_torch,
            require_cpu_wheel=True,
        )
        self.assertFalse(ok)
        self.assertIn("must be replaced", "\n".join(messages))


class InstallerTorchPolicyContractTests(unittest.TestCase):
    def test_setup_repairs_before_installing_selected_wheel(self):
        setup_text = (REPO_ROOT / "一键安装.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("torch_runtime_policy.py\" verify-auto", setup_text)
        self.assertIn("GPU_FAMILIES", setup_text)
        self.assertIn("MINIMUM_DRIVER", setup_text)
        self.assertIn(
            "uninstall torch torchvision torchaudio -y",
            setup_text,
        )
        self.assertIn(
            "install --upgrade !TORCH_PACKAGE_SPEC! --index-url "
            "https://download.pytorch.org/whl/!CUDA_INDEX!",
            setup_text,
        )
        self.assertLess(
            setup_text.index("uninstall torch torchvision torchaudio -y"),
            setup_text.index("install --upgrade !TORCH_PACKAGE_SPEC!"),
        )


if __name__ == "__main__":
    unittest.main()
